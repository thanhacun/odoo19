import datetime
import re
import time as _time
from urllib.parse import urlencode as url_encode

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, http, models, _
from odoo.exceptions import UserError, ValidationError

vn_tz = pytz.timezone(' '.join(pytz.country_timezones('vn')))
utc_diff = 7


class HrMixinManager(models.TransientModel):
    _name = 'hr.mixin.manager'
    _description = 'Wizard to pick a manager/employee'

    active_id = fields.Integer()
    active_model = fields.Char()
    employee_id = fields.Many2one('hr.employee')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)

        active_model = self.env.context.get('active_model', False)
        active_id = self.env.context.get('active_id', False)
        defaults['active_model'] = active_model
        defaults['active_id'] = active_id

        return defaults

    @api.onchange('active_id', 'active_model')
    def compute_employee_domain(self):
        related_record = False
        employee_domain = []
        if self.active_id and self.active_model:
            related_record = self.env[self.active_model].browse([self.active_id])
        if related_record:
            manager_ids = self.env['hr.employee'].sudo().search([]).mapped('admin_manager_id.id')
            employee_domain = [('id', 'not in', [related_record.employee_id.id, related_record.employee_id.parent_id.id]), ('id', 'in', manager_ids)]

        return {
            'domain': {'employee_id': employee_domain}
        }

    def action_save(self):
        self.ensure_one()
        related_record = False
        if self.active_id and self.active_model:
            related_record = self.env[self.active_model].browse([self.active_id])
        if related_record and 'approve_manager_id' in related_record:
            related_record.approve_manager_id = self.employee_id.id


class HrMixinRevise(models.TransientModel):
    _name = 'hr.mixin.revise'
    _description = 'Wizard to revise a request'

    active_id = fields.Integer()
    active_model = fields.Char()
    revise_reason = fields.Char()



class HrMixin(models.AbstractModel):
    _name = 'hr.mixin'
    _description = 'Sharing class for KDVN Attendance App'

    next_button_visible = fields.Char(compute='_compute_buttons_visible')
    refuse_button_visible = fields.Boolean(compute='_compute_buttons_visible')
    revise_button_visible = fields.Boolean(compute='_compute_buttons_visible')
    need_director_button_visible = fields.Boolean(compute='_compute_buttons_visible')
    man2_approve = fields.Boolean('Director Approve', default=False)
    approve_manager_id = fields.Many2one('hr.employee', default=False)
    refuse_comment = fields.Text(compute='_get_refuse_comment')

    single_mode = fields.Boolean(compute='_compute_single_mode', help='Whether the user is staff or admin/manager?')
    active = fields.Boolean(default=True, groups='hr_attendance.group_hr_attendance_user')

    # Odoo 12 fields_view_get removed some list columns (employee, request times...) in 'single mode' (staff see only their own rows).
    # Odoo 19: the list views hide those columns themselves with column_invisible="context.get('attendance_single_mode')" etc.

    def _compute_buttons_visible(self):
        for r in self:
            user_groups = r.groups()  # one lookup per record, not one per role
            # user_groups = self.env.user.all_group_ids
            user_is_at_staff = user_groups.get('at_staff', False)
            user_is_hr_staff = user_groups.get('hr_staff', False)

            # TODO [X]: Allow past managers to approve based on view_user_ids
            user_is_section_man = user_groups.get('section_manager', False) and (r.sudo().employee_id.admin_manager_id.user_id.id == self.env.uid 
                                                                                or r.sudo().approve_manager_id.user_id.id == self.env.uid 
                                                                                or r._name == 'hr.attendance' and self.env.uid in r.sudo().view_user_ids.mapped('id'))
            user_is_hr_manager = user_groups.get('hr_manager', False)
            user_is_gm = user_groups.get('gm', False) and self.env.uid in r.sudo().employee_id.admin_manager_user_ids.mapped('id')
            user_is_director = user_groups.get('director', False)

            next_button_visible = False
            refuse_button_visible = False
            revise_button_visible = False
            need_director_button_visible = False

            user_is_employee = r.employee_id.user_id.id == self.env.uid if 'employee_id' in r else False

            if user_is_at_staff:
                refuse_button_visible = False
                if r.state == 'draft':
                    next_button_visible = 'submit'
                if r.state in ['waiting_fman', 'refuse']:
                    # next_button_visible = False
                    revise_button_visible = True

            if user_is_section_man:
                # submit self request
                if r.state == 'draft' and user_is_employee:
                    next_button_visible = 'submit'
                if r.state == 'waiting_fman':
                    if not user_is_employee:
                        refuse_button_visible = True
                        next_button_visible = 'approve'
                        # if r._name == 'hr.leave.cover' or (r._name == 'hr.attendance' and (r.leave_cover_ids or r.at_request_ids.filtered(lambda r: r.request_type == 'working_time'))):
                        #     revise_button_visible = True
                    else:
                        revise_button_visible = True
                if r.state == 'waiting_fhr':
                    revise_button_visible = True

            if user_is_hr_staff or user_is_hr_manager or self.env.uid == 1:
                if r.state != 'draft':
                    revise_button_visible = True
                else:
                    revise_button_visible = False

                if r.state == 'draft':
                    next_button_visible = 'submit'
                    # if r.employee_id.user_id.id == self.env.uid:
                    #     next_button_visible = 'submit'
                    # else:
                    #     next_button_visible = 'delete'

                if r.state == 'waiting_fman' and user_is_section_man and not user_is_employee:
                    refuse_button_visible = True
                    next_button_visible = 'approve'

                if r.state == 'waiting_fhr':
                    next_button_visible = 'validate'
                    if not user_is_employee:
                        refuse_button_visible = True
                    if user_is_hr_staff or user_is_hr_manager:
                        need_director_button_visible = True

                related_refuse = self.env['hr.attendance.refuse'].search(['|', ('related_request_id', '=', r.id), ('related_leave_cover_id', '=', r.id)])
                if related_refuse:
                    if not user_is_employee:
                        refuse_button_visible = True

            if user_is_gm:
                if r.state == 'waiting_fman2':
                    next_button_visible = 'approve2'
                    refuse_button_visible = True

            # TODO [X]: for hr.attendance revise and refuse button should only show when there is ONLY ONE request or no request at all
            if r._name == 'hr.attendance':
                if not all([not r.at_request_ids and (r.leave_cover_ids and len(r.leave_cover_ids) == 1), not r.leave_cover_ids and (r.at_request_ids and len(r.at_request_ids) == 1)]) <= 1:
                    revise_button_visible = False
                    refuse_button_visible = False

            # TODO [X]: for hr.leave, hr.leave.cover: show revise button for AH Leave created by OdooBot so that user can make change
            if r._name == 'hr.leave.cover':
                if revise_button_visible == False and len(r) == 1 and len(r.leave_request_ids) == 1 and r.leave_request_ids.holiday_status_id.is_ah and r.create_uid.id == 1 and r.state in ['done'] and user_is_at_staff:
                    revise_button_visible = True

            r.update({'next_button_visible': next_button_visible, 'refuse_button_visible': refuse_button_visible,
                      'revise_button_visible': revise_button_visible, 'need_director_button_visible': need_director_button_visible})

    def _compute_single_mode(self):
        for r in self:
            user_groups = r.groups()
            is_at_staff = user_groups['at_staff']
            is_admin_or_manager = any([user_groups['hr_staff'], user_groups['hr_manager'], 
                                       user_groups['section_admin'], user_groups['section_manager'], user_groups['director']])
            r.single_mode = is_at_staff and not is_admin_or_manager

    def _get_refuse_comment(self):
        for r in self:
            refuse_domain = []
            if r._name == 'hr.attendance.request':
                refuse_domain = [('related_request_id', '=', r.id)]
            if r._name == 'hr.leave.cover':
                refuse_domain = [('related_leave_cover_id', '=', r.id)]
            r.refuse_comment = self.env['hr.attendance.refuse'].search(refuse_domain, limit=1).name or ''

    # ====== ACTIONS ======
    def action_need_director(self):
        if any([r.state != 'waiting_fhr' for r in self]):
            raise UserError(_('Only records in the state [HR validate] can ask for Director approve!'))
        for r in self:
            r.man2_approve = True
            r.action_validate()

    def action_validate(self):
        # if any([r.state != 'waiting_fhr' for r in self]):
        #     raise UserError(_('Only records in [Waiting for HR] state can validate!'))

        is_odoo_bot = self.env.uid == 1
        for r in self:
            if r.state != 'waiting_fhr' and not is_odoo_bot:
                raise UserError(_('Only records in [HR validated] state can be validated! REF.: {}').format(r))
            if not r.man2_approve and not is_odoo_bot:
                reasons = r._gm_reasons()
                if reasons:
                    r._set_need_gm(reasons)
            if r.man2_approve:
                r.state = 'waiting_fman2'
            else:
                r.state = 'done'

    def _gm_reasons(self):
        """Why this leave cover / OT-WT request needs the GM (RQ-12): company limits that have a value (0 = off). [] = HR alone."""
        self.ensure_one()
        company = self.env.user.company_id
        reasons = []
        if self._name == 'hr.leave.cover':
            limit = company.gm_leave_days_limit
            if limit and self.number_of_days > limit:
                reasons.append(_('leave of %s days (limit %s)') % (self.number_of_days, limit))
            limit = company.gm_absence_days_limit
            if limit:
                absence = sum(self.leave_request_ids.filtered(lambda l: l.holiday_status_id.category == 'absence').mapped('number_of_days'))
                if absence > limit:
                    reasons.append(_('%s Absence days (limit %s)') % (absence, limit))
        elif self._name == 'hr.attendance.request' and self.at_id:
            limit = company.gm_ot_over_hours_limit
            if limit and self.request_type == 'over_time':
                self.env.flush_all()   # the monthly summary is a SQL view: Odoo 19 does not flush pending attendance writes by itself
                self.env.invalidate_all()
                summary = self.at_id.sudo().summary_id
                over = (summary.exceed_wd_overtime or 0) + (summary.exceed_hd_overtime or 0)
                if over > limit:
                    reasons.append(_('OT %s hours over the allowed OT of the month (limit %s)') % (over, limit))
            if company.gm_late_request and self.create_date:
                ot_before, wt_before, _days = self._request_cutoffs()
                before = ot_before if self.request_type == 'over_time' else wt_before
                created = pytz.utc.localize(self.create_date).astimezone(vn_tz).replace(tzinfo=None)
                if before and created > before:
                    reasons.append(_('request registered after the cutoff (%s)') % before.strftime('%d-%b-%Y %H:%M'))
        return reasons

    def _set_need_gm(self, reasons):
        """Same effect as the HR button 'Need director': the record (and its attendance) waits for the GM."""
        for r in self:
            r.man2_approve = True
            ats = r.at_id if r._name == 'hr.attendance.request' else r.related_at_ids()
            ats.sudo().write({'man2_approve': True})
            target = r if hasattr(r, 'message_post') else ats[:1]
            if target:
                target.sudo().message_post(body=_('Sent to the GM automatically: %s') % '; '.join(reasons))

    # @api.multi
    # def action_set_done(self):
    #     """
    #         - Force state=done
    #         - ! only for hr admin
    #     """
    #     for r in self:
    #         r.state = 'done'

    def action_change_approve_manager(self):
        """
            - Common action to change approve manager for temporary short time
            - Using wizard to pick the manager employee_id
        """
        # [X] TODO STILL cannot change domain for field here
        # Using onchange method
        self.ensure_one()

        action = {
            "type": "ir.actions.act_window",
            "name": "Change approve manager",
            "res_model": "hr.mixin.manager",
            "views": [(False, "form")],
            "view_mode": "list,form",
            "target": "new"
        }

        return action

    def _set_draft(self, record):
        if record._name == 'hr.attendance':
            record.with_context(set_draft=True).state_id = self.env.ref('kdvn_hr_attendance.state_draft').id
        if record._name in ['hr.attendance.request', 'hr.leave.cover']:
            record.with_context(set_draft=True).state = 'draft'

    def action_revise(self):
        for r in self:
            user_is_at_staff = r.groups().get('at_staff', False)
            user_is_hr_staff = r.groups().get('hr_staff', False)
            user_is_section_man = r.groups().get('section_manager', False) and r.sudo().employee_id.admin_manager_id.user_id.id == self.env.uid
            user_is_hr_manager = r.groups().get('hr_manager', False)
            user_is_employee = r.employee_id.user_id.id == self.env.uid if 'employee_id' in r else False
            if user_is_at_staff:
                if r.state in ['refuse', 'waiting_fman']:
                    self._set_draft(r)
                elif r.state == 'done' and r.create_uid.id == 1:
                    self._set_draft(r)
            if user_is_section_man and r.state in ['refuse', 'waiting_fman', 'waiting_fhr']:
                self._set_draft(r)
            if user_is_hr_staff or user_is_hr_manager and r.state not in ['draft']:
                self._set_draft(r)
            if r.state == 'draft' and r.man2_approve:
                r.man2_approve = False

    def action_refuse(self):
        # [X] TODO: recalculate ot => move to hr.attendance.refuse save method
        # TODO [X]: open comment/refuse 
        # TODO []: refuse in attendance
        self.ensure_one()
        refuse_model_id = False
        refuse_record_id = False
        if self._name == 'hr.attendance.request':
            refuse_model_id = 'related_request_id'
            refuse_record_id = self.id
        if self._name == 'hr.leave.cover':
            refuse_model_id = 'related_leave_cover_id'
            refuse_record_id = self.id
        if self._name == 'hr.attendance':
            if self.at_request_ids and len(self.at_request_ids) == 1 and not self.leave_cover_ids:
                refuse_model_id = 'related_request_id'
                refuse_record_id = self.at_request_ids.id
            elif self.leave_cover_ids and len(self.leave_cover_ids) == 1 and not self.at_request_ids:
                refuse_model_id = 'related_leave_cover_id'
                refuse_record_id = self.leave_cover_ids.id
            else:
                return False

        refuse = self.env['hr.attendance.refuse']
        if refuse_model_id:
            refuse = self.env['hr.attendance.refuse'].search([(refuse_model_id, '=', self.id)], limit=1)

        action = {
            "type": "ir.actions.act_window",
            "name": "Open refuse comment",
            "res_model": "hr.attendance.refuse",
            "views": [(False, "form")],
            "view_mode": "list,form",
            "domain": [],
            # "res_id": refuse.id if refuse else self.env['hr.attendance.refuse'].create({refuse_model_id: self.id}).id,
            "res_id": refuse.id if refuse else False,
            "target": "new",
            "context": {'default_%s' %refuse_model_id: refuse_record_id}
        }

        return action

    def action_unlink(self):
        """
            - !NOTE: DANGER SHOULD use with care (need confirm)
        """
        for r in self:
            user_is_employee = r.employee_id.user_id.id == self.env.uid if 'employee_id' in r else False
            user_is_hr_staff = r.groups().get('hr_staff', False)
            user_is_hr_manager = r.groups().get('hr_manager', False)
            if r._name in ['hr.attendance.request', 'hr.leave.cover'] and r.state == 'draft' and (user_is_employee or user_is_hr_staff or user_is_hr_manager):
                r.unlink()

    def action_toggle_active(self):
        for r in self:
            r.active = not r.active

    # ====== CRUD Methods =====
    def write(self, values):
        result = super().write(values)
        # Sync approve_manager_id (only when it is written)
        if self._name == 'hr.attendance' and 'approve_manager_id' in values:
            for a in self:
                if not a.approve_manager_id and 'approve_manager_id' in values:
                    # Clear approve_manager_id
                    for c in a.leave_cover_ids:
                        if c.approve_manager_id:
                            c.approve_manager_id = False
                        other_at_ids = c.related_at_ids() - a
                        if other_at_ids:
                            for at in other_at_ids:
                                if at.approve_manager_id:
                                    at.approve_manager_id = False
                    for r in a.at_request_ids:
                        if r.approve_manager_id:
                            r.approve_manager_id = False
                if a.approve_manager_id:
                    # Set approve_manager_id
                    for c in a.leave_cover_ids:
                        if not c.approve_manager_id:
                            c.approve_manager_id = a.approve_manager_id
                        other_at_ids = c.related_at_ids() - a
                        if other_at_ids:
                            for at in other_at_ids:
                                if not at.approve_manager_id:
                                    at.approve_manager_id = a.approve_manager_id
                    for r in a.at_request_ids:
                        if not r.approve_manager_id:
                            r.approve_manager_id = a.approve_manager_id

        return result

    # ====== COMMON Methods =====
    @api.model
    def today_vn(self):
        """Today's date in Vietnam. The Odoo process runs in UTC, so date.today() is yesterday between 00:00 and 07:00 Vietnam time."""
        return datetime.datetime.now(vn_tz).date()

    @api.model
    def request_cutoff(self, setting_dt, at_date):
        """Latest moment (naive Vietnam time) to register a request for at_date (RQ-05).
        setting_dt = company setting ot_/wt_/leave_request_before (Datetime, stored UTC): its Vietnam TIME is the cutoff clock time
        on the day AFTER at_date (forgot to check out today: register tomorrow at the latest), and its Vietnam DATE is the day
        the setting applies from. None when the setting is empty or at_date is before that date.
        Before 1 Nov 2026 the three checks mixed UTC hours and server-local conversions (see attendance_rules.md RQ-05)."""
        if not setting_dt:
            return None
        local = pytz.utc.localize(setting_dt).astimezone(vn_tz).replace(tzinfo=None)
        if at_date < local.date():
            return None
        return datetime.datetime.combine(at_date + relativedelta(days=1), local.time())

    def get_early_check_in(self, at_date=None, employee_id=None):
        """
            - Return True if check_in_early for the employee
            - at_date based on vn_tz
        """
        early_check_in = False
        if employee_id and at_date:
            early_check_in = self.env['hr.attendance']._at_rules(employee_id=employee_id, at_date=at_date)['early_check_in']
        return early_check_in
    
    def get_early_offset(self, at_date=None, employee_id=None):
        """Memoised per transaction (see hr.attendance.clear_at_rules_memo): raw import asks it twice per check-in row."""
        emp_id = employee_id if isinstance(employee_id, int) else (employee_id.id if employee_id else 0)
        memo = self.env.cr.cache.setdefault('kderp_early_offset_memo', {})
        key = (emp_id, at_date)
        hit = memo.get(key)
        now = _time.monotonic()
        if hit is None or now - hit[0] > 60:
            hit = (now, self._get_early_offset(at_date=at_date, employee_id=employee_id))
            memo[key] = hit
        return hit[1]

    def _get_early_offset(self, at_date=None, employee_id=None):
        # Using sudo() for performance
        early_offset = 0
        # for early checkin applied by rules
        if employee_id and at_date:
            early_offset = self.env['hr.attendance']._at_rules(employee_id=employee_id, at_date=at_date)['early_offset'] or 0
        # for early checkin requested by at_date
        if not early_offset and at_date and 'hr.attendance.request' in self.env:   # the model comes with stage C
            early_request_domain = [('sub_request_type_id.code', '=', 'early_in'), ('employee_id', '=', employee_id if isinstance(employee_id, int) else (employee_id.id if employee_id else 0)), ('at_id.at_date', '=', at_date)]
            early_request = self.env['hr.attendance.request'].sudo().with_context(active_test=False).search(early_request_domain)

            # at_domain = [('employee_id', '=', employee_id if isinstance(employee_id, int) else employee_id.id), ('at_date', '=', at_date)]
            # at = self.env['hr.attendance'].with_context(active_test=False).search(at_domain)
            if len(early_request) == 1:
                # request_early = at.at_request_ids.filtered(lambda r: r.sub_request_type_id.code == 'early_in' and r.state not in ['draft', 'refuse'])
                # if request_early and len(request_early) == 1:
                early_offset = early_request.early_offset
        return early_offset

    def get_at_date(self, dt_value, get_time=False, start_hour=0, employee_id=None):
        """Return at_date from a datetime by tz and start_hour policy

        Args:
            dt_value [datetime]: datetime value to convert, utc time zone
            start_hour (int, optional): [Start hour of the day: 1~24]. Defaults to 0.
            tz ([timezone], optional): [description]. Defaults to vn_tz.
            consider early_checkin or early_offset rule or request

            - Ex: (10-15-21 05:50:00, start_hour=6, tz=vn_tz) => 10-14-21
            - Ex: (10-15-21 07:50:00, start_hour=6, tz=vn_tz) => 10-15-21
            - Ex.: input 5:30 15/12/2021 => 6:00 14/12/2021 (vn_tz)
            - Ex.: input 7:53 18/12/2021 => 6:00 18/12/2021 (vn_tz)
            - Input should be utc
        """
        res = False
        company = self.env.user.company_id
        if not company:
            raise UserError(_('User {} should belong to a company!'.format(self.env.user.name)))
        start_hour = start_hour or company.at_policy()['day_start']
        if not dt_value or not isinstance(dt_value, datetime.datetime):
            raise UserError(_('Need datetime as an required input! REF: Calling method [{}]'.format(__name__)))
        
        # NOTE: the use of early_employee_ids here: if False will force to run get_early_offset method
        # which is quite resource consuming
        early_offset, next_day_offset = 0, 0
        early_employee_ids = self.env.context.get('early_employee_ids', False)
        
        if employee_id and (early_employee_ids == False or employee_id.id in early_employee_ids):
            early_offset = self.get_early_offset(employee_id=employee_id, at_date=dt_value.astimezone(vn_tz).date())
            next_day_offset = self.get_early_offset(employee_id=employee_id, at_date=dt_value.astimezone(vn_tz).date() + relativedelta(days=1))
        early_minute_offset = early_offset
        late_minute_offset = next_day_offset
        
        start_time = (dt_value.astimezone(vn_tz) + relativedelta(hour=start_hour, minute=0)) - relativedelta(minutes=early_minute_offset)
        end_time = start_time + relativedelta(days=1, minutes=early_minute_offset-late_minute_offset)
        if dt_value.astimezone(vn_tz) < start_time:
            res = start_time.date() - datetime.timedelta(days=1)
        elif dt_value.astimezone(vn_tz) > end_time:
            res = end_time.date()
        else:
            res = start_time.date()
        if get_time:
            res = vn_tz.localize(datetime.datetime.combine(res, datetime.time(start_hour, 0, 0)) - relativedelta(minutes=early_minute_offset))
        return res

        # if dt_value.astimezone(vn_tz) < start_time:
        #     res = dt_value.astimezone(vn_tz).date() - relativedelta(days=1)
        #     if get_time:
        #         res = datetime.datetime.combine(res, datetime.time(start_hour, minute_offset, 0)).replace(tzinfo=vn_tz)
        #     return res
        # else:
        #     res = dt_value.astimezone(vn_tz).date()
        #     if get_time:
        #         res = datetime.datetime.combine(res, datetime.time(start_hour, minute_offset, 0)).replace(tzinfo=vn_tz)
        #     return res
    
    def get_at_datetime(self, at_date):
        """
            - Return datetime value of start hour of the at_date (utc)
            - Ex: (2022-4-30) => 23:00 2022-4-29
            - Use start_hour policy
            - !NOTE: Do not use early_check_in rule because do not know employee yet.
        """
        res = False
        company = self.env.user.company_id
        start_hour = company.at_policy()['day_start'] if company else 6
        if not isinstance(at_date, datetime.date):
            raise UserError(_('Please input datetime.date value! REF: method {}.{}').format(__class__, __name__))

        res = datetime.datetime.combine(at_date, datetime.time(start_hour, 0, 0))  # get native datetime
        res = res + relativedelta(hours=-utc_diff)  # get utc datetime: DO NOT USE tz here
        return res

    def groups(self):
        res = {'at_staff': False, 'hr_staff': False, 'hr_manager': False,
               'section_admin': False, 'section_manager': False, 'gm': False, 'director': False}
        user_groups = self.env.user.all_group_ids
        if self._name in ['hr.attendance', 'hr.attendance.request', 'hr.leave.cover', 'hr.attendance.ot.holiday']:
            res['at_staff'] = (self.employee_id.user_id == self.env.user) if len(self) == 1 else False
        # res['at_staff'] = self.env.ref('hr_attendance.group_hr_attendance_manual') in user_groups
        res['hr_staff'] = self.env.ref('hr_attendance.group_hr_attendance_user') in user_groups
        res['section_manager'] = self.env.ref('kdvn_hr_attendance.group_hr_attendance_section_manager') in user_groups
        res['hr_manager'] = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        res['gm'] = self.env.user.has_group('kdvn_hr_attendance.group_hr_attendance_gm')
        res['director'] = self.env.user.has_group('kdvn_hr_attendance.group_hr_attendance_director')
        return res

    def at_start_day(self):
        """First day of the attendance month: company policy `rule_at_start_date` (21 when not set)."""
        company = self.env.user.company_id
        return int((company.at_policy() if company else {}).get('date_start') or 21)

    def at_period_end(self, at_year, at_month):
        """Exclusive end date of attendance month (at_year, at_month): the start day of that month number
        (21/mm/yyyy by default). The month starts one month earlier."""
        return datetime.date(at_year, at_month, self.at_start_day())

    def at_period_last_day(self, at_year, at_month):
        """Last day of attendance month (at_year, at_month): 20/mm/yyyy by default."""
        return self.at_period_end(at_year, at_month) - relativedelta(days=1)

    def get_start_dt(self, a_date=None, for_month=False):
        """
            - Helper method: return starting date of an attendance period
            - if for_month=True: return starting date of an at month (21/mm/yyyy)
            - else: return starting date of an at year (21/12/yyyy)
        """
        if not a_date:
            a_date = fields.Date.context_today(self)
        start_date = self.at_start_day()

        if a_date.month == 12 and a_date.day >= start_date:
            start_dt = a_date + relativedelta(day=start_date)  # apply for both year and month
        else:
            if for_month:
                start_dt = a_date + (relativedelta(months=-1, day=start_date) if a_date.day < start_date else relativedelta(day=start_date))
            else:
                start_dt = a_date + relativedelta(years=-1, month=12, day=start_date)
        return start_dt

    def get_at_year_month(self, a_date):
        """
            Helper method return tuple of at_year and at_month from a_date
            a_date [date] required
            return (year:int, month:int)
        """
        month_start_date = self.get_start_dt(a_date, for_month=True)
        # Using end_date to ensure the year (not so logical)
        month_end_date = month_start_date + relativedelta(months=1, day=month_start_date.day - 1)
        return (month_end_date.year, month_end_date.month)

    def monthly_working_weekday(self, a_date):
        """
            Helper method return a list of working day (not holiday) for a specific weekday
            For Ex: List of working SATs
        """
        start_dt = self.get_start_dt(a_date=a_date, for_month=True)
        end_dt = start_dt + relativedelta(months=1)
        weekday_ls = [start_dt + relativedelta(days=d) for d in range((end_dt - start_dt).days) if (start_dt + relativedelta(days=d)).weekday() == a_date.weekday() and self.env['hr.holidays.public'].is_public_holiday(start_dt + relativedelta(days=d)) == 0]
        return weekday_ls

    def in_first_half_month(self, a_date):
        """
            Return True if a_date is in first second weeks of the attendance month
        """
        start_dt = self.get_start_dt(a_date=a_date, for_month=True)
        # end_dt = start_dt + relativedelta(months=1)
        return a_date < (start_dt + relativedelta(days=14))
    
    def in_last_half_month(self, a_date):
        """
            Return True if a_date's weekday is one of the last weekday of the attendance month
            NOTE: Currently using for determining a saturday is last-two-sat or not
        """
        # TODO [X]: Must skip SAT as a Holiday
        # start_dt = self.get_start_dt(a_date=a_date, for_month=True)
        # end_dt = start_dt + relativedelta(months=1)
        # weekday_ls = [start_dt + relativedelta(days=d) for d in range((end_dt - start_dt).days) if (start_dt + relativedelta(days=d)).weekday() == a_date.weekday() and self.env['hr.holidays.public'].is_public_holiday(start_dt + relativedelta(days=d)) == 0]
        # print('=====', a_date in weekday_ls[-2:])
        # return a_date > (end_dt - relativedelta(days=15))  # end_dt starts as 21st
        # return a_date in weekday_ls[-2:]
        return a_date in self.monthly_working_weekday(a_date=a_date)[-2:]


    def float_to_time(self, float_time):
        """
            - Helper method to convert float to time tuple
            - Only Hour and Minute
        """
        if not float_time or not isinstance(float_time, float):
            raise UserError(_('Need an input of float number! REF: float_to_time'))
        time_tuple = tuple(map(lambda e: int(e), divmod(float_time * 60, 60)))
        return datetime.time(*time_tuple)

    def float_to_datetime(self, float_time, a_date, employee_id=None, is_in_time=False):
        """
            - Helper method to convert float and a_date to datetime in utc
            - Using employee_id for early_check_in cases
            - [is_in_time::Boolean]: time inputed as in time => handle case inputting out of regular range (6:00 ~ 5:59)
        """
        if not (isinstance(float_time, float) and isinstance(a_date, datetime.date)):
            raise ValidationError(_('Need float as a time input, and date as a date input!'))

        day_start = self.at_policy()['day_start']
        time_value = self.float_to_time(float_time)
        t0 = datetime.time(0, 0)  # Mid night

        # TODO [X]: consider early check in cases
        early_offset = self.get_early_offset(at_date=a_date, employee_id=employee_id)

        if employee_id and early_offset:
            # t1 = datetime.time(day_start - 1, early_offset)  # 5:xx
            t1 = (datetime.datetime.combine(datetime.date.today(), datetime.time(day_start, 0)) - relativedelta(minutes=early_offset)).time()  # 5:xx
            # ref: https://stackoverflow.com/a/656394
        else:
            t1 = datetime.time(day_start, 0)  # 6:00

        if time_value >= t0 and time_value <= t1:
            if is_in_time:  # Set to equal t1
                return vn_tz.localize(datetime.datetime.combine(a_date, t1)).astimezone(pytz.utc).replace(tzinfo=None)  # 6:00 same day
            else:  # From midnight to 6:00 => understand as next day
                if time_value == t1:
                    return vn_tz.localize(datetime.datetime.combine(a_date + relativedelta(days=1), time_value)).astimezone(pytz.utc).replace(tzinfo=None) - relativedelta(seconds=1)
                else:
                    return vn_tz.localize(datetime.datetime.combine(a_date + relativedelta(days=1), time_value)).astimezone(pytz.utc).replace(tzinfo=None)
        else:
            return vn_tz.localize(datetime.datetime.combine(a_date, time_value)).astimezone(pytz.utc).replace(tzinfo=None)

    def time_to_float(self, a_datetime=None):
        """
            - Helper method to covert time/datetime object into time float value
            - without tz information
            - Only Hour and Minute
        """

        if not a_datetime:
            return False
        if not (isinstance(a_datetime, datetime.time) or isinstance(a_datetime, datetime.datetime)):
            raise ValidationError(_('Need an input of time/datetime object! REF: time_to_float'))

        time_value = a_datetime
        if isinstance(a_datetime, datetime.datetime):
            time_value = a_datetime.astimezone(vn_tz).time()

        res = time_value.hour + time_value.minute / 60.0
        return res

    def at_policy(self):
        company = self.env.user.company_id
        if not company:
            raise UserError(_('User {} should belong to a company! Please contact HR.'.format(self.env.user.name)))
        return company.at_policy()

    def get_full_url(self, model_name, action_id, record_id=None, menu_id=None):
        """
            - Helper method to return record url to open in back_end
            - REF: https://stackoverflow.com/a/54944421
        """
        # self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        url_params = {
            'model': model_name,
            'action': action_id,
        }
        # Seem to be no need to use menu_id
        if menu_id:
            url_params['menu_id'] = menu_id,

        if record_id:
            url_params['id'] = record_id,
            url_params['view_type'] = 'form'
        params = '/web?#%s' % url_encode(url_params)
        return base_url + params

    def get_url(self):
        return http.request.httprequest.full_path

    def url_contain_ip(self, url):
        """
            Check the URL contain ip address or not
        """
        # regex to check ip addres xxx.xxx.xxx.xxx
        # ref.: https://stackoverflow.com/a/2890905
        ip_pattern = r'[0-9]+(?:\.[0-9]+){3}'  
        return  bool(re.findall(ip_pattern, url))
    
    def do_not_have_data_yet(self, employee_id, at_date):
        """
            - Helper method that return True if data not available yet
            - True if all employee history locations still do not have data yet
            - TODO []: weighting?
        """
        res = True
        # sql_employee_locations = """
        #     SELECT employee_id, he.name,
        #            ARRAY_REMOVE((
        #                 SELECT ARRAY(
        #                     SELECT DISTINCT UNNEST(array_agg(DISTINCT check_in_location_id) || array_agg(DISTINCT check_out_location_id))
        #                 )
        #             ), NULL) AS location_ids
        #         FROM hr_attendance ha
        #         JOIN hr_employee he ON ha.employee_id = he.id
        #         WHERE ha.active = TRUE AND ha.employee_id = {employee_id}
        #         GROUP BY employee_id, he.name
        # """.format(employee_id=employee_id)

        # ! NOTE: the use of LATERAL keyword here
        sql_employee_locations = """
            SELECT employee_id, he.name,
                (SELECT array_agg(ARRAY[w.location, w.weight]) FROM
                    (SELECT location, COUNT(*) AS weight FROM
                        LATERAL UNNEST(ARRAY_REMOVE(array_agg(check_in_location_id) || array_agg(check_out_location_id), NULL)) AS location
                        GROUP BY location) AS w) AS location_ids
            FROM hr_attendance ha
            JOIN hr_employee he ON ha.employee_id = he.id
            WHERE ha.active = TRUE AND ha.employee_id = {employee_id}
            GROUP BY employee_id, he.name
        """.format(employee_id=employee_id)
        self.env.cr.execute(sql_employee_locations)
        machine_location_ids = self.env.cr.dictfetchall()

        if machine_location_ids and machine_location_ids[0]['location_ids']:
            sorted_locations = sorted(machine_location_ids[0]['location_ids'], key=lambda e: e[1], reverse=True)
            sql_data_status = """
                SELECT machine_location_id, at_date, data_status 
                FROM hr_attendance_raw_data_status rd
                JOIN hr_attendance_location al ON rd.machine_location_id = al.id
                WHERE machine_location_id IN ({machine_location_ids}) AND at_date='{at_date}' AND al.active = TRUE OR (al.active = FALSE AND al.inactive_date >= '{at_date}')
            """.format(machine_location_ids=', '.join(map(lambda m: str(m[0]), sorted_locations)) , at_date=at_date.strftime('%Y-%m-%d'))
            self.env.cr.execute(sql_data_status)
            res = not any([s['data_status'] for s in self.env.cr.dictfetchall()])
        return res

    def may_be_forget(self, employee_id, at_date):
        """
            - Helper method return True when employee may be forget check_in or check_out
        """
        delay_duration = self.env.user.company_id.at_policy()['delay_duration'] if self.env.user.company_id else 2
        today = fields.Date.context_today(self)
        at_record = self.env['hr.attendance'].sudo().with_context(active_test=False).search([('employee_id', '=', employee_id), ('at_date', '=', at_date)])
        if at_record and at_record.absence:
            # TODO [X]: do NOT count holidays and leaves
            # TODO [X]: get data one more time => Should handle it before calling this method
            if (at_date < today and (today - at_date).days > delay_duration) and not self.do_not_have_data_yet(employee_id, at_date):
                if not at_record._is_holiday(at_date): 
                    if not at_record.leave_cover_ids:
                        return True
                    elif at_record.leave_cover_ids and '1/2 X' in at_record.status_ids.mapped('code'):
                        return True
        return False
    
    def to_lunar(self, solar_date):
        """
            Convert a solar date to lunar date
        """
        from lunarcalendar import Converter  # optional library, not in the Odoo 19 image yet
        lunar_date = Converter.Solar2Lunar(solar_date)
        return lunar_date
        # return (lunar_date.year, lunar_date.month, lunar_date.day)
    
    def is_ot_holiday(self, a_date, employee_id=None, no_sat_working=False):
        """
            Return True if a_date is public holiday, sunday or last 2 saturdays
            - employee_id: hr.employee object: is used to determine sat working or not
        """
        res = self.env['hr.attendance']._is_holiday(a_date)
        if not res:
            if a_date.weekday() == 5:
                sat_ls = self.monthly_working_weekday(a_date)
                is_no_sat_working = employee_id and self.env['hr.attendance'].is_no_sat_working(employee_id=employee_id, at_date=a_date)
                if no_sat_working or is_no_sat_working:
                    res = a_date in sat_ls
                else:
                    res = a_date in sat_ls[-2:]
        return bool(res)
    
    def get_ot_holidays(self, a_date, employee_id=None, no_sat_working=False):
        """
            Return a list of date considered as holidays (KDVN rule) for an at month
            Including: public holidays, sundays and last 2 saturdays
            - no_sat_working is used to compute ot_holidays for employees that not working on SAT at all
            - even when the no_sat_working=True, must check the resource_calendar_id of 40-hours is set for
            any employee in the at_month or not
        """
        start_dt = self.get_start_dt(a_date, for_month=True)
        end_dt = start_dt + relativedelta(months=1)
        # default_rc_id = self.env.company.resource_calendar_id
        # is_no_sat_working_apply = bool(self.env['hr.attendance.rule'].search([('state', '=', 'done'), ('valid_start', '>=', start_dt), ('valid_start', '<', end_dt), ('resource_calendar_id', '!=', False), ('resource_calendar_id', '!=', default_rc_id.id)]))
        # if no_sat_working:
        #     no_sat_working = is_no_sat_working_apply
        ot_holidays = [start_dt + relativedelta(days=d) for d in range((end_dt - start_dt).days) if self.is_ot_holiday(start_dt + relativedelta(days=d), employee_id=employee_id, no_sat_working=no_sat_working)]
        return ot_holidays
    
    def update_view_users_by_model(self):
        """
            Update view_user_ids for self having employee_id
        """
        for r in self:
            if 'employee_id' in r and 'view_user_ids' in r:
                if r.employee_id:
                    view_employee_ids = [r.employee_id.parent_id, r.employee_id.admin_manager_id, r.employee_id.gm_id, r.employee_id.admin_gm_id]
                    user_ids = [e.user_id.id for e in view_employee_ids if e.user_id]
                    r.view_user_ids = [(6, False, user_ids)]

