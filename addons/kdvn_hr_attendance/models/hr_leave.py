from collections import namedtuple
import datetime
import logging
import re
from dateutil.relativedelta import relativedelta
import pytz
from pytz import timezone, utc

# from temp.odoo.odoo.addons.hr_holidays.models.hr_leave_allocation import HolidaysAllocation
from odoo import models, fields, api, _
from odoo.tools.date_utils import float_to_time
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.osv import expression

from odoo.tools.float_utils import float_round
# from odoo.tools.profiler import profile

_logger = logging.getLogger(__name__)
# vn_timedelta = datetime.timedelta(hours=7)
vn_tz = pytz.timezone(' '.join(pytz.country_timezones('vn')))
# vn_tz = datetime.timezone(vn_timedelta, 'VNT')
DummyAttendance = namedtuple('DummyAttendance', 'hour_from, hour_to, dayofweek, day_period')


class KderpHolidayRequestCover(models.Model):
    """
    - Class leave.cover allowing making multiple leave-type requests
    - All the leave request here are use default value for KDVN:
       + Calculate leave by day and half day
       + States by KDVN definition
       + User cover states instead of request states
    - leave.cover states mapped to its leaves states:
       + draft => confirm (default state in original model)
       + [waiting_fman, waiting_fhr, waiting_fman2, done] => validate
       + refuse => refuse

    """
    _name = 'hr.leave.cover'
    _description = 'KDERP HR Leave Request Cover'
    _inherit = ['mail.thread', 'hr.mixin']
    _order = "date_from desc"
    _mail_post_access = 'read'

    def _default_employee(self):
        return self.env.context.get('default_employee_id') or self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)

    # Description
    name = fields.Text('Description')
    reason_id = fields.Many2one('hr.leave.cover.reason', string='Reason', required=True, default=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_fman', 'Manager approve'),
        ('waiting_fhr', 'HR validate'),
        ('waiting_fman2', 'GM approve'),
        ('done', 'Done'),
        ('refuse', 'Refuse')
    ], string='Status', readonly=True, copy=False, default='draft', tracking=False,
       help="The status is set to 'Draft', when a leave request is created." +
            "\nThe status is 'Manager approve', when the leave request is approved by the user." +
            "\nThe status is 'HR validate', when the leave request is confirmed by the manager." +
            "\nThe status is 'Done', when the leave request is checked by HR or older than a defined period, normally 2 days")
    number_of_days = fields.Float(compute='_compute_date', search="_search_for_zero_duration")
    # HR info
    employee_id = fields.Many2one('hr.employee', default=_default_employee)
    department_id = fields.Many2one('hr.department', related="employee_id.admin_dept_id", store=True)
    # leave requests
    date_from = fields.Datetime(compute='_compute_date', store=True, readonly=True)
    date_to = fields.Datetime(compute='_compute_date', store=True, readonly=True)
    date_from_period = fields.Selection([('am', 'Morning'), ('pm', 'Afternoon')], string="From AM/PM", compute='_compute_date', store=True)
    date_to_period = fields.Selection([('am', 'Morning'), ('pm', 'Afternoon')], string="To AM/PM", compute='_compute_date', store=True)
    leave_request_ids = fields.One2many('hr.leave', 'leave_cover_id')
    # allocation summary
    allocation_summary = fields.Html(compute='_compute_allocation_summary', help="Current leave allocation")
    dt_from = fields.Date(compute='_compute_date', store=True)
    dt_to = fields.Date(compute='_compute_date', store=True)
    special_leave = fields.Boolean(compute='_compute_special_leave', search='_search_special_leave')
    leave_on_sat = fields.Boolean(compute='_compute_leave_on_sat', search='_search_leave_on_sat')
    status_sync = fields.Boolean(compute='_compute_status_sync', search='_search_status_sync', help="Whether the cover status insync with leave status or not")

    # View users
    # SQL Update command (for empty table)
    # INSERT INTO hr_leave_cover_res_users_rel (hr_leave_cover_id, res_users_id)
    # SELECT DISTINCT lc.hr_leave_cover_id, vu.res_users_id
	#   FROM hr_attendance_hr_leave_cover_rel lc
	#   JOIN hr_attendance_res_users_rel vu ON lc.hr_attendance_id = vu.hr_attendance_id
    view_user_ids = fields.Many2many('res.users', string="View users", readonly=True)  # data will update in CRUD method

    def _legacy_name_get(self):
        res = []
        for cover in self:
            display_name = cover.employee_id.name
            display_name = ''
            if cover.leave_request_ids:
                if cover.date_from and cover.date_to:
                    if cover.date_from.date() == cover.date_to.date():
                        display_name += _("Leave on %(date)s %(period)s") % {
                            'date': cover.date_from.date().strftime('%d-%m-%Y'),
                            'period': cover.date_from_period or ''
                        }
                    else:
                        display_name += _("Leave from %(date_from)s %(date_from_period)s to %(date_to)s %(date_to_period)s") % {
                            'date_from': cover.date_from.date().strftime('%d-%m-%Y'),
                            'date_from_period': cover.date_from_period or '',
                            'date_to': cover.date_to.date().strftime('%d-%m-%Y'),
                            'date_to_period': cover.date_to_period or '',
                        }
                if len(cover.leave_request_ids) == 1:
                    if cover.leave_request_ids.substitute_for_date:
                        display_name += _(' (sub. for {})'.format(cover.leave_request_ids.substitute_for_date.strftime('%d/%m/%Y')))
                else:
                    display_name += _(' (for {})'.format(cover.reason_id.name))
            res.append((cover.id, display_name))
        return res


    @api.depends('employee_id', 'date_from', 'date_to', 'date_from_period', 'date_to_period', 'reason_id', 'leave_request_ids', 'leave_request_ids.substitute_for_date')
    def _compute_display_name(self):
        """Odoo 19 has no name_get(): display_name is computed. The Odoo 12 body is kept as _legacy_name_get (same strings)."""
        names = dict(self._legacy_name_get())
        for rec in self:
            rec.display_name = names.get(rec.id) or ''

    @api.model
    def create_cover(self, reason_id, holiday_status_id, fr_date, fr_date_pm=False, to_date=None, to_date_am=False, employee_id=None, sub_hol_id=False, sub_period=None):
        """
            - Create leave cover with a related leave
            - TODO [X]: return exitsted leave cover if possible

        """
        # TODO []: check existed leaves and make change if need
        leave_type = self.env['hr.leave.type'].browse(holiday_status_id)
        if leave_type.category == 'sub_holiday' and not sub_hol_id:
            raise UserError(_('Do not have substituted holiday! Please inform IT.'))
        if not to_date:
            to_date = fr_date
        if not employee_id:
            employee_id = self.env.user.employee_id.id
        employee = self.env['hr.employee'].browse(employee_id)

        reason = self.env['hr.leave.cover.reason'].browse(reason_id)
        cover = {'reason_id': reason_id, 'name': reason.name, 'employee_id': employee_id}
        holiday = {
            'name': reason.name,
            'holiday_status_id': leave_type.id,
            'employee_id': employee_id,
            'request_date_from': fr_date,
            'date_from': datetime.datetime.combine(fr_date, datetime.time.min),
            'request_date_to': to_date,
            'date_to': datetime.datetime.combine(to_date, datetime.time.max),
            'request_date_from_pm': fr_date_pm,
            'request_date_to_am': to_date_am,
            'substitute_for_at_id': sub_hol_id,
            'substitute_period': sub_period
        }

        existed_leaves = self.env['hr.leave'].sudo().with_context(active_test=False).search([('employee_id', '=', employee_id), ('request_date_from', '<=', fr_date), ('request_date_to', '>=', to_date)])
        # ! NOTE: case of 1/2 L how to handle
        if existed_leaves:
            _logger.warning(_('Leave existed: {}'.format(existed_leaves)))
            if len(existed_leaves) == 1 and existed_leaves.holiday_status_id.id == leave_type.id and existed_leaves.request_date_from_pm == fr_date_pm and existed_leaves.request_date_to_am == to_date_am:
                return existed_leaves.leave_cover_id
            else:
                raise UserError(_('Leave existed: {}'.format(existed_leaves)))

        cover['leave_request_ids'] = [(0, False, holiday)]

        try:
            new_cover = self.with_context(run_holiday_onchange=True).create(cover)
            return new_cover
        except Exception as e:
            # TODO []: If error happened, need to unlink already created hr.leave records
            orphan_leave = self.env['hr.leave'].search([('employee_id', '=', holiday['employee_id']), ('date_from', '=', holiday['date_from']), ('date_to', '=', holiday['date_to'])])
            if orphan_leave:
                if orphan_leave.state in ['confirm', 'validate', 'validate1']:
                    orphan_leave.action_refuse()
                if orphan_leave.state not in ['draft']:
                    orphan_leave.action_draft()
                orphan_leave.with_context(do_not_update_at_leave_ids=True).unlink()
            _logger.warning(_('Cannot create leave, please ask HR for instruction! REF: {} @ {} on {}. Technical error {}'.format(employee.code, fr_date, leave_type.name, e)))
            raise UserError(_('Cannot create leave, please ask HR for instruction! REF: {} @ {} on {}. Technical error {}'.format(employee.code, fr_date, leave_type.name, e)))

    def related_at_ids(self):
        """
            - Helper method to return related attendance records of leave covers
            - Should include related at for sub_leave as well
            - Return: record set
        """
        # self.ensure_one()
        at_ids = self.env['hr.attendance'].sudo().with_context(active_test=False)
        at_ids = at_ids | at_ids.search([('employee_id', '=', self.employee_id.id), ('at_date', '>=', self.dt_from), ('at_date', '<=', self.dt_to)])
        # sub_at_dates = self.leave_request_ids.filtered(lambda h: h.holiday_status_id.category == 'sub_holiday').mapped('substitute_for_date')
        # at_ids = at_ids | at_ids.search([('employee_id', '=', self.employee_id.id), ('at_date', 'in', sub_at_dates)])
        return at_ids

    def button_quick_create(self):
        # Just for triggering saving record
        self.quick_create()
        return True

    def quick_create(self):
        # Quick creating leave based on input leave reason
        self.ensure_one()
        c = self
        employee = c.employee_id
        dt_from = datetime.datetime.now(vn_tz).date()
        dt_to = dt_from

        LeaveRequest = self.env['hr.leave']
        LeaveType = self.env['hr.leave.type']
        l_type_domain = [('validity_start', '<=', dt_from), ('validity_stop', '>=', dt_to)]
        LeaveAllocation = self.env['hr.leave.allocation']

        leave = {
            'leave_cover_id': c.id,
            'request_date_from': dt_from,
            'date_from': datetime.datetime.combine(dt_from, datetime.time.min),
            'request_date_to': dt_to,
            'date_to': datetime.datetime.combine(dt_to, datetime.time.max),
            'employee_id': c.employee_id.id
        }

        if c.reason == 'AH':
            # create new leave with leave type = current AH and with in validity dates of today
            # REF: https://stackoverflow.com/questions/56092261/how-to-create-a-record-without-saving-it-in-database
            l_type_domain.append(('is_ah', '=', True))
            l_type = LeaveType.search(l_type_domain, limit=1)
            if l_type:
                leave['holiday_status_id'] = l_type.id
                # c.leave_request_ids = [(0, False, leave)]

        if c.reason in ['marriage_ceremony']:
            # [] If refuse: also refuse allocation request
            l_type_domain.append(('name', '=', c.name))
            l_type = LeaveType.search(l_type_domain, limit=1)
            if l_type:
                # [X] Choosing this leave type in leave
                leave['holiday_status_id'] = l_type.id
                if not LeaveAllocation.search_count([('name', '=', c.name), ('employee_id', '=', employee.id)]):
                    # [X] Create an allowcation request and approve it for this case
                    # [] WHO will be the user to create? HR admin?
                    a = LeaveAllocation.create({
                        'name': c.name,
                        'holiday_status_id': l_type.id,
                        'holiday_type': 'employee',
                        'employee_id': employee.id,
                        'number_of_days': 5
                    })
                    # [] TODO: WHO approve? Should use sudo here
                    a.action_approve()

        l = LeaveRequest.create(leave)
        l._onchange_leave_dates()
        c._compute_date()
        # c._compute_number_of_days()

    @api.onchange('reason_id')
    def _compute_name(self):
        for c in self:
            c.name = c.reason_id.name

    @api.onchange('leave_request_ids')
    def _onchange_leave_request(self):
        # A kind of get default values for leave base on its parent id
        # [X] TODO: date should be around the date of parent record (ex: from attendance open the leave cover)
        # !NOTE: Keep running when any fields in leave_request_ids changed (looping)
        self.ensure_one()
        # TODO []: need review, may be too tricky
        if self.leave_request_ids and len(self.leave_request_ids) > 1:
            if type(self.leave_request_ids[-1].id) != int:
                if self.leave_request_ids[-1].request_date_from < self.leave_request_ids[-2].request_date_to:
                    self.leave_request_ids[-1].request_date_from = self.leave_request_ids[-2].request_date_to

    @api.depends('leave_request_ids')
    def _compute_date(self):
        for r in self:
            if r.leave_request_ids:
                leaves = r.leave_request_ids.sorted(key='date_from')
                r.date_from = leaves[0].date_from
                r.dt_from = r.date_from.date() if r.date_from else False
                r.date_from_period = leaves[0].request_date_from_period
                r.date_to = leaves[-1].date_to
                r.dt_to = r.date_to.date() if r.date_to else False
                r.date_to_period = leaves[-1].request_date_to_period
                # ! NOTE: review
                # r.number_of_days = sum(r.leave_request_ids.filtered(lambda h: not h.holiday_status_id.is_ah or h.substitute_for_date).mapped('number_of_days'))
                r.number_of_days = sum(r.leave_request_ids.mapped('number_of_days'))
            else:  # Odoo 19: every field must be assigned
                r.date_from = r.date_to = r.dt_from = r.dt_to = False
                r.date_from_period = r.date_to_period = False
                r.number_of_days = 0

    def _search_for_zero_duration(self, operator, value):
        if operator == '=' and value == 0:
            return [('leave_request_ids.number_of_days', '=', 0)]

    def _compute_allocation(self, employee_id=False):
        """
            - Compute an employee current leave allocation
            - TODO [X]: must possible to compute even in case of no leave cover yet
            - Single record or no record
        """
        # self.ensure_one()
        c = self
        if not employee_id:
            employee_id = c.employee_id.id or False
        
        # values = {'employee_name': c.employee_id.name_get()[0][1] if c.employee_id else None}
        values = {'summary': []}
        # domain = [('state', '=', 'validate'), ('employee_id', '=', employee_id), ('holiday_status_id.is_ah', '=', False)]
        domain = [('state', '=', 'validate'), ('employee_id', '=', employee_id)]
        # ! NOTE: need employee_id context here for calculating holiday_status_id values
        allocations = c.env['hr.leave.allocation'].with_context(employee_id=employee_id).search(domain).filtered(lambda a: a.holiday_status_id.is_ah == False and a.holiday_status_id.valid).sorted(lambda a: a.holiday_status_id.name)
        summary = []
        allocation_action_id = self.env.ref('hr_holidays.hr_leave_allocation_action_all')
        valid_allocation_date = self.env.context.get('valid_allocation_date') if 'valid_allocation_date' in self.env.context else fields.Date.context_today(self)
        valid_allocation_date = valid_allocation_date.strftime('%b. %d, %Y')
        
        def sort_allocation(a):
            """
                - Helper method to sort allocation object
            """
            sort_weight = 9999
            this_year = datetime.date.today().year
            if a['type'] == 'Annual Leave':
                sort_weight = 1
                if a['name'] == 'OT Compensation':
                    sort_weight = 2
            if a['type'] == 'Last Year Leave':
                sort_weight = 3
                
            if a['leave_type'].is_special and a['leave_type'].category == 'other':  # Special Leave
                sort_weight = 5
            if a['leave_type'].is_special and a['leave_type'].category == 'summer_vacation':
                sort_weight = 10
            if not a['leave_type'].is_special and a['leave_type'].category == 'special_leave':  # Yearly Special Leave
                sort_weight = 15
                year = re.search(r'(\d{4})\s*$', a['name'] or '')   # a name without a final year keeps the default weight
                if year:
                    sort_weight = this_year - int(year.group(1)) + 15
            
            return sort_weight
        
        for a in allocations:
            a = a.with_context(employee_id=employee_id)
            if not a.holiday_status_id.is_special and a.holiday_status_id.category == 'special_leave':
                # can_request = a.holiday_status_id.virtual_remaining_leaves and a.holiday_status_id.valid and a.allow_to_use
                can_request = a.holiday_status_id.virtual_remaining_leaves
            else:
                can_request = a.holiday_status_id.virtual_remaining_leaves and a.holiday_status_id.valid
            
            a_info = {
                'name': a.name,
                'type': a.holiday_status_id.name,
                'leave_type': a.holiday_status_id,
                'total_allowed': a.total_allowed,
                'remain': a.remaining_leaves,
                'can_request': can_request,
                'allocation_url': self.env['hr.mixin'].get_full_url('hr.leave.allocation', allocation_action_id.id, record_id=a.id),
                'valid_allocation_date': valid_allocation_date
            }
            summary.append(a_info)
            summary.sort(key=sort_allocation)
            # !Tricky modify summary type to keep only one appear
            # !Handled in xml views
            # for i in reversed(range(len(summary))):
            #     if i > 0 and summary[i]['type'] == summary[i - 1]['type']:
            #         summary[i]['type'] = ''
        values['summary'] = summary
        return values

    @api.model
    def get_allocation(self, uid):
        user = self.env['res.users'].search([('id', '=', uid)])
        if user and user.employee_id:
            employee_id = user.employee_id.id
            view = self.env.ref('kdvn_hr_attendance.allocation_summary')
            allocations = self._compute_allocation(employee_id=employee_id)
            # return allocations
            return self.env['ir.qweb']._render(view.id, allocations) if allocations['summary'] else None
        else:
            return None

    @api.onchange('employee_id')
    def _compute_allocation_summary(self):
        view = self.env.ref('kdvn_hr_attendance.allocation_summary')
        for c in self:
            values = c._compute_allocation()
            html = self.env['ir.qweb']._render(view.id, values)
            c.allocation_summary = html

    def _compute_special_leave(self):
        for c in self:
            if c.leave_request_ids.filtered(lambda h: h.holiday_status_id.is_special or h.holiday_status_id.category == 'special_leave'):
                c.special_leave = True
            else:
                c.special_leave = False

    def _search_special_leave(self, operator, value):
        if operator == '=' and value in [True, False]:
            ids = self.search([]).filtered(lambda c: c.special_leave == value).mapped('id')
            return [('id', 'in', ids)]
        else:
            return []
    
    def _compute_leave_on_sat(self):
        for c in self:
            leave_on_sat = False
            for h in c.leave_request_ids:
                duration = [h.request_date_from + relativedelta(days=d) for d in range((h.request_date_from - h.request_date_to).days + 1)]
                if any([d.weekday() == 5 for d in duration]):
                    leave_on_sat = not h.holiday_status_id.is_ah
            c.leave_on_sat = leave_on_sat

    def _search_leave_on_sat(self, operator, value):
        if operator == '=' and value in [True, False]:
            ids = self.search([]).filtered(lambda c: c.leave_on_sat == value).mapped('id')
            return [('id', 'in', ids)]
        return []

    def _compute_status_sync(self):
        for c in self:
            c.status_sync = all(c.leave_request_ids.mapped('status_sync'))

    def _search_status_sync(self, operator, value):
        if operator == '=' and value in [True, False]:
            ids = self.search([]).filtered(lambda c: c.status_sync == value).mapped('id')
            return [('id', 'in',  ids)]
        return []
    
    def button_next_state(self):
        for c in self:
            if c.state == 'draft':
                c.action_submit()
            elif c.state == 'waiting_fman':
                c.action_approve()
            elif c.state == 'waiting_fhr':
                c.action_validate()
            else:
                pass

    def button_previous_state(self):
        for c in self:
            c.action_refuse()

    # ===== Status Actions =====
    def _holiday_state_to_validate(self, holiday):
        """
            - Helper method to validate holidays
        """
        # ! NOTE: sudo here
        holiday = holiday.sudo()
        if holiday.state == 'draft':
            holiday.action_confirm()
        if holiday.state == 'confirm':
            holiday.action_approve()

    def _onchange_cover_state(self):
        for c in self:
            # import odoo_repl; odoo_repl.set_trace()
            if c.state in ['draft', 'waiting_fman']:
                for holiday in c.leave_request_ids.sudo():
                    if holiday.state != 'draft':
                        holiday.action_refuse()
                        holiday.action_draft()
                # c._sync_related_at_data()

            # if c.state == 'waiting_fman':
            #     # After action_submit
            #     for holiday in c.leave_request_ids.sudo():
            #         self._holiday_state_to_validate(holiday)
                # c._sync_related_at_data()

            if c.state == 'waiting_fhr':
                # After action_approve
                for holiday in c.leave_request_ids.sudo():
                    if holiday.state in ['draft', 'confirm']:
                        self._holiday_state_to_validate(holiday)

            if c.state == 'refuse':
                # After action_refuse => save_refuse_comment
                for holiday in c.leave_request_ids.sudo():
                    if holiday.state != 'draft':
                        holiday.action_refuse()
                        holiday.action_draft()
                # c._sync_related_at_data()

            if c.state == 'done':
                # After action_validate or force done
                for holiday in c.leave_request_ids:
                    self._holiday_state_to_validate(holiday)

                if any(holiday.state != 'validate' for holiday in c.leave_request_ids):
                    raise UserError(_('Holiday states not in-sync with Cover state! Please contact IT. REF ID {}'.format(c.id)))

            c.related_at_ids()._compute_related_states()

    def action_sync_status(self):
        """
            - Force sync state between cover and leave
            - Using in UI
        """
        for c in self:
            if not c.status_sync:
                c._onchange_cover_state()
    
    def action_submit(self):
        # if (any(cover.state != 'draft' for cover in self)):
        #     raise UserError(_('Leave requests must be in state [Draft] to proceed!'))
        for c in self.filtered(lambda r: r.state == 'draft'):
            # TODO [X]: if holiday type is AH directly write to done
            state = 'waiting_fman'
            if len(c.leave_request_ids) == 1 and c.leave_request_ids.holiday_status_id.is_ah and c.number_of_days <= 1 and c.date_from.weekday() == 5:
                if not c.date_from_period:
                    # AH and not working on AH
                    if c.related_at_ids().absence == 'absence':
                        state = 'done'
                else:
                    # 1/2 AH and not working on AH
                    if c.related_at_ids().absence and c.related_at_ids().absence[-2:] == c.date_from_period:
                        state = 'done'
            c.state = state
        # self._onchange_cover_state()

    def action_approve(self):
        # if any(cover.state != 'waiting_fman' for cover in self):
        #     raise UserError(_('Leave requests must be in state [Manager Approve] to proceed!'))
        # TODO []: OdooBot can approve
        for c in self:

            is_manager = c.env.user.has_group('kdvn_hr_attendance.group_hr_attendance_section_admin')
            is_odoo_bot = self.env.uid == 1
            is_hr_admin = c.groups()['hr_staff']
            if not any([is_manager, is_odoo_bot, is_hr_admin]):
                if any([cover.employee_id.user_id.id == self.env.uid for cover in c]):
                    raise UserError(_('Only HR Manager can approve his/her own requests!'))
                else:
                    raise UserError(_('Only Manager can approve or refuse his/her section requests'))

            c.filtered(lambda r: (is_odoo_bot or is_hr_admin) or r.state == 'waiting_fman').write({'state': 'waiting_fhr'})
        # self._onchange_cover_state()

    def action_validate(self):
        super().action_validate()
        # self._onchange_cover_state()

    def action_approve_man2(self):
        # if any([r.state != 'waiting_fman2' for r in self]):
        #     raise UserError(_('All records must be in [Director Approve] state to proceed!'))
        self.filtered(lambda r: r.state == 'waiting_fman2').write({'state': 'done'})

    def action_revise(self):
        # TODO [X]: Allow HR to set draft at any state
        # is_hr_manager = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        # is_section_manager = self.groups().get('section_manager', False)
        # if any(cover.state not in ['done', 'refuse', 'waiting_fman'] and not (is_hr_manager or is_section_manager and cover.sudo().employee_id.admin_manager_id.user_id.id == self.env.uid) for cover in self):
        #     raise UserError(_('Leave request must NOT be in [done, refuse] state and only HR and section manager can proceed!'))

        # import odoo_repl; odoo_repl.set_trace()
        for cover in self:
            for holiday in cover.leave_request_ids.sudo():
                try:
                    if holiday.state in ['confirm', 'validate', 'validate1']:
                        holiday.action_refuse()
                    if holiday.state not in ['draft']:
                        holiday.action_draft()
                    holiday.write_uid = self.env.uid  # Keep track of records changed
                except Exception as ex:
                    # _logger.error('===== just continue! {}'.format(ex))
                    _logger.exception('Error happen. Just continue! {}'.format(ex))
                if holiday.state != 'draft':
                    raise UserError(_('Not successfully, please contact IT. REF_ID {}').format(cover.id))
            # ! NOTE: careful with sudo here
            super(__class__, cover).action_revise()
            # cover.sudo().state = 'draft'
            # self._onchange_cover_state()
            # cover.sudo()._sync_related_at_data()

    def _sync_related_at_data(self, additional_at_dates=None):
        """
            - additional_at_dates: other related at_dates such as change sub_date
        """
        # TODO []: check carefully to prevent loop when running _compute_at_status
        # TODO [X]: SYNC cover state and at state
        # TODO [X]: Do not create ats if take a long leave (more than 01 week into the future)
        self.ensure_one()
        cover = self
        employee_id = cover.employee_id
        max_days = 7

        fr_date = cover.dt_from if cover.dt_from else False
        to_date = cover.dt_to if cover.dt_to else False

        if not any([fr_date, to_date]):
            _logger.error('===== NO cover.date_from or cover.date_to')
            return False

        # TODO [X]: should update sub_at as well
        # domain = [('employee_id', '=', cover.employee_id.id), '|', ('at_date', 'in', cover.leave_request_ids.mapped('substitute_for_date')), '&', ('at_date', '>=', fr_date), ('at_date', '<=', to_date)]
        # related_at = self.env['hr.attendance'].search(domain)
        # !NOTE: is this enough for sync cover state and at state?
        # related_at._compute_related_states()
        # related_at._compute_at_status()

        days_between = min([max_days, (to_date - fr_date).days + 1])
        at_dates = [fr_date + datetime.timedelta(days=i) for i in range(days_between)]
        sub_dates = cover.leave_request_ids.filtered('substitute_for_date').mapped('substitute_for_date')
        if sub_dates:
            at_dates += sub_dates
        if additional_at_dates:
            at_dates += additional_at_dates

        # TODO [X]: Create future ats for the leaves (only when leave cover state is waiting_fman)
        # if cover.state == 'waiting_fman' and (len(related_at) < days_between or fr_date > fields.Date.context_today(self)):
        ats = self.env['hr.attendance']
        # for at_date in [fr_date + datetime.timedelta(days=d) for d in range(days_between)]:
        for at_date in at_dates:
            at_code = 'AT-{}-{}'.format(at_date.strftime('%y%m%d'), employee_id.code)
            at = self.env['hr.attendance'].sudo().with_context(active_test=False).search([('code', '=', at_code)])
            if not at:  
                # !NOTE: sudo here
                at = self.env['hr.attendance'].with_context(do_not_run_at_status=True).sudo().create({
                    'employee_id': employee_id.id,
                    'at_date': at_date,
                    'code': at_code
                })

            ats |= at
            # at._compute_related_states()
            # at._compute_at_status
        # ats._compute_related_states()
        # if not self.env.context.get('do_not_run_at_status', False):
        do_not_run_at_status = self.env.context.get('do_not_run_at_status', False)
        for at in ats:
            if (sub_dates and at.at_date in sub_dates) or (additional_at_dates and at.at_date in additional_at_dates):
                at.with_context(do_not_run_at_status=False)._compute_at_status()
            else:
                at._compute_leave_cover_ids()
                at.with_context(do_not_run_at_status=do_not_run_at_status)._compute_at_status()

    # ===== CRUD =====
    @api.model_create_multi
    def create(self, vals_list):
        """Odoo 19 passes a list of dicts; the Odoo 12 body below handles one dict at a time."""
        records = self.browse()
        for vals in vals_list:
            records |= self._legacy_create(vals)
        return records

    def _legacy_create(self, values):
        if not values.get('leave_request_ids') and not self.env.context.get('kdvn_legacy_import'):   # the legacy import creates the cover first, its leaves after
            raise ValidationError(_('Leave cover without leaves! Please check your data!'))
        cover_ids = super(KderpHolidayRequestCover, self.with_context(mail_create_nolog=True)).create(values)
        if self.env.context.get('kdvn_no_compute'):
            return cover_ids   # legacy import: Odoo 12 values as they are (no sync of the days, no submit; viewers and day links copied by the importer)
        for c in cover_ids:
            # This method will create new at records if needed
            if c.state != 'draft':
                c.with_context(do_not_run_at_status=True)._sync_related_at_data()
            for at in c.related_at_ids():
                at._compute_leave_cover_ids()

            # Update view_user_ids for leave_cover
            # Avoid using at here
            c.update_view_users_by_model()
            # view_employee_ids = [c.employee_id.parent_id, c.employee_id.admin_manager_id, c.employee_id.gm_id, c.employee_id.admin_gm_id]
            # user_ids = [e.user_id.id for e in view_employee_ids if e.user_id]
            # c.view_user_ids = [(6, False, user_ids)]
            
            # submit the request for better user experience
            if c.state == 'draft':
                c.action_submit()
        return cover_ids

    def write(self, values):
        if self.env.context.get('kdvn_no_compute'):
            return super().write(values)   # legacy import (re-run)
        # TODO []: Update change sub_date
        changed_sub_dates = []
        for c in self:
            changed_sub_dates += c.leave_request_ids.filtered('substitute_for_date').mapped('substitute_for_date') or []
        result = super().write(values)
        # This method will create new at records if needed
        # Note: it is a need when user modify a leave cover that may
        # affect other at_date (in the past or may be in the future)
        for c in self:
            if not changed_sub_dates and c.state not in ['draft']:
                c.with_context(do_not_run_at_status=True)._sync_related_at_data()
            else:
                c.with_context(do_not_run_at_status=True)._sync_related_at_data(additional_at_dates=changed_sub_dates or None)
        if values.get('state'):
            states = dict(self.env['hr.leave.cover']._fields['state'].selection)
            if not self.env.context.get('do_not_run_onchange_cover_state', False):
                self._onchange_cover_state()
            for c in self:
                if c.state in ['draft', 'waiting_fman']:
                    c.employee_id.sudo().parent_id.user_id.notify_danger(message='Please update the UI!')
            
            # Logging changes to hr.attendance chatter
            for at in self.related_at_ids():
                for c in self:
                    str_leave_dates = f'from [{c.dt_from} - {c.dt_to}]' if (c.dt_from < c.dt_to) else f'on [{c.dt_from}]'
                    at.message_post(body=f'**Leave Request** {str_leave_dates} **state** changes to [{states[c.state]}] by {c.write_uid.name}')
        return result

    # @profile
    def unlink(self):
        allowed_cover = self.filtered(lambda c: c.state == 'draft')
        if allowed_cover < self:
            _logger.warning(_('Can delete only [Draft] leave(s)'))
            raise UserError(_('Can delete only [Draft] leave(s)'))

        # TODO [X]: Delete sub leave and some other tasks for related ats
        related_ats = related_sub_ats = self.env['hr.attendance']
        related_sub_dates = []
        for cover in allowed_cover:
            domain = [('employee_id', '=', cover.employee_id.id), ('leave_cover_ids', '=', cover.id)]
            related_ats |= self.env['hr.attendance'].search(domain)
            # TODO []: Update related sub ats
            related_sub_dates += cover.leave_request_ids.filtered('substitute_for_date').mapped('substitute_for_date') or []
            related_sub_domain = [('employee_id', '=', cover.employee_id.id), ('at_date', 'in', related_sub_dates)]
            related_sub_ats = self.env['hr.attendance'].search(related_sub_domain)
            for holiday in cover.leave_request_ids:
                holiday.with_context(do_not_update_at_leave_ids=True).unlink()

        _super = super().unlink()

        # TODO [X]: delete unused future attendances
        for at in related_ats:
            if at.at_date > fields.Date.context_today(self) and not at.leave_cover_ids and not at.at_request_ids:
                at.sudo().unlink()
                # TODO []: consider to delete unused special leave allocations
            else:
                at.write({'request_leave': False})
                at._compute_leave_cover_ids()
                at._compute_related_states()

        for at in related_sub_ats:
            at._compute_at_status()
        return _super

    # @api.model
    # def search(self, args, offset=0, limit=None, order=None, count=False):
    #     print('===== search', args, self.env.context)
    #     return super().search(args=args, offset=offset, limit=limit, order=order, count=count)

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """
            - Handling show_ah cases in groupby mode
        """
        if not self.env.context.get('show_ah'):
            domain = expression.AND([[('reason_id.code', '!=', 'ah')], domain])
        return super().read_group(domain, fields, groupby,
                                                 offset=offset, limit=limit,
                                                 orderby=orderby, lazy=lazy)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        """
            - Handling show_ah search
        """
        # Odoo 19 reads a record's fields through _search([('id', 'in', ids)]) (Odoo 12 did not): such a lookup
        # must never hide an AH cover, or reading it fails with a false access error.
        is_id_lookup = (isinstance(domain, (list, tuple)) and len(domain) == 1
                        and isinstance(domain[0], (list, tuple)) and tuple(domain[0][:2]) == ('id', 'in'))
        if not self.env.context.get('show_ah') and not is_id_lookup:
            domain = Domain([('reason_id.code', '!=', 'ah')]) & Domain(domain)
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)

    # ===== MESSAGING =====
    def _track_subtype(self, init_values):
        return False
        self.ensure_one()
        if self._name == 'hr.leave.cover':
            if 'state' in init_values and self.state == 'waiting_fhr':
                return 'kdvn_hr_attendance.cover_manager_approved'

            return super()._track_subtype(init_values)

        return super()._track_subtype(init_values)

    def _notify_get_groups(self, message, groups):
        groups = super()._notify_get_groups(message, groups)

        actions = []
        if self.state == 'waiting_fhr':
            validate_action = self._notify_get_action_link('method', method='action_validate')
            actions = [{'url': validate_action, 'title': _('Cancel')}]

        new_group = (
            'hr_attendance.group_hr_attendance_manager',
            lambda partner: bool(partner.user_ids) and any(user.has_group('hr_attendance.group_hr_attendance_manager') for user in partner.user_ids),
            {
                'actions': actions
            }
        )
        return [new_group] + groups

    def message_subscribe(self, partner_ids=None, channel_ids=None, subtype_ids=None):
        if self.state == 'waiting_fhr':
            self.check_access_rights('read')
            self.check_access_rule('read')
            return super(__class__, self.sudo()).message_subscribe(partner_ids=partner_ids, channel_ids=channel_ids, subtype_ids=subtype_ids)
        return super(__class__, self.sudo()).message_subscribe(partner_ids=partner_ids, channel_ids=channel_ids, subtype_ids=subtype_ids)

    # ===== CONSTRAINS =====
    @api.constrains('leave_request_ids')
    def _check_continue_holidays(self):
        at_policy = self.env.user.company_id.at_policy()
        leave_request_before = at_policy['leave_request_before']
        today = fields.Date.context_today(self)
        at_date = self[:1].dt_from  # Date (Vietnam day) of the first day of the leave
        # leave_before = datetime.datetime.combine(at_date, datetime.time(17, 0, 0)) + relativedelta(leave_request_before) if isinstance(leave_request_before, relativedelta) else None
        leave_before = self.env['hr.mixin'].request_cutoff(leave_request_before, at_date) if at_date else None

        # Holidays should have different holiday_status
        if len(self.leave_request_ids) > 1:
            # TODO [X]: different holiday_status
            if len(self.leave_request_ids) > len(set(self.leave_request_ids.mapped('holiday_status_id'))):
                raise ValidationError(_('Leaves must have the same type! Please contact HR for instruction.'))

            # TODO [X]: continuous holidays
            sorted_holidays = self.leave_request_ids.sorted('date_from')
            for i in range(len(sorted_holidays) - 1):
                error = (sorted_holidays[i + 1].date_from.date() - sorted_holidays[i].date_to.date()).days > 1 \
                         or (sorted_holidays[i + 1].date_from.date() - sorted_holidays[i].date_from.date()).days == 1 \
                         and sorted_holidays[i].request_date_from_period == 'am'
                if error:
                    raise ValidationError(_('Leaves must be continuous! You might want to make separated requests or make your request through Sunday.'))
                
        # Not allow to register leave before time defined in AT Rules
        if leave_before and datetime.datetime.now().astimezone(vn_tz).replace(tzinfo=None) >= leave_before:
            raise ValidationError(_(f'You can NOT register Leave request before {leave_before.astimezone(vn_tz).strftime("%d-%h-%Y %H:%M")} - Please contact HR for instruction!'))

    @api.constrains('date_from', 'date_to')
    def _check_related_at_state(self):
        # User must NOT request leave on DONE attendance day
        delay_duration = self.env.user.company_id.at_policy()['delay_duration'] if self.env.user.company_id else 2
        today = fields.Date.context_today(self)
        # TODO [X]: Should allow if user is bot or admin
        if self.env.uid not in [1, 2] or not self.groups()['hr_staff']:
            if self.related_at_ids().filtered(lambda a: a.state == 'done' and (today - a.at_date).days >= delay_duration):
                raise ValidationError(_('Cannot request leave for a [Done] attendance day. Please contact HR!'))

    # ===== FIXES =====
    def _fix_leave_duration(self):
        """
            - Helper method to fix leave duration (for auto AH)
        """
        for c in self:
            if c.number_of_days == 0:
                org_state = c.state
                c.sudo().action_revise()
                for h in c.leave_request_ids:
                    h._onchange_request_parameters()
                # c.sudo().action_submit()
                # if org_state == 'done':
                    # c.sudo().action_submit()
                    # c.sudo().action_approve()
                    # c.sudo().action_validate()
            

class KderpHolidaysRequest(models.Model):
    _name = 'hr.leave'
    _description = 'KDERP HR Leave Request'
    _inherit = ['hr.leave', 'hr.mixin']
    _order = 'sequence, id'


    def _check_validity(self):
        """Odoo 12 let leaves (notably AH, made by the system) go beyond the allocation; Odoo 19 core refuses it. The data import copies
        leaves that Odoo 12 already accepted, so it skips this one check (context set by kdvn_legacy_import only)."""
        if self.env.context.get('kdvn_legacy_import'):
            return
        return super()._check_validity()

    leave_cover_id = fields.Many2one('hr.leave.cover', ondelete='cascade')
    # Description
    name = fields.Text(related='leave_cover_id.name', readonly=True)
    sequence = fields.Integer('Rank')
    # override: disable track change for state
    state = fields.Selection(tracking=False)
    # override: do not using domain to enable register leave in the past
    holiday_status_id = fields.Many2one(domain=[])

    # request type
    holiday_type = fields.Selection([('employee', 'By Employee')], default='employee', string='Allocation Mode')   # Odoo 12 core field
    request_date_from_pm = fields.Boolean('Afternoon', default=False)
    request_date_from_period = fields.Selection(default=False)
    request_date_to_am = fields.Boolean('Morning', default=False)
    same_request_date = fields.Boolean(compute='_is_same_request_date')
    # duration
    date_from = fields.Datetime(tracking=False)
    date_to = fields.Datetime(tracking=False)
    # to be used in search/filter
    dt_from = fields.Date(compute='_compute_date', store=True)
    dt_to = fields.Date(compute='_compute_date', store=True)
    # substitute
    # using with holiday_status_id of subtitute type
    # show_substitute = fields.Boolean(compute='_compute_substitute', default=False, store=True)
    substitute_period = fields.Selection([('am', 'Morning'), ('pm', 'Afternoon')], string="Sub. AM/PM")
    # aval_date_for_substitute = fields.Text(compute='_compute_aval_date_for_substitute', store=True)
    substitute_for_at_id = fields.Many2one('hr.attendance', domain=[('id', '<', 0)])

    substitute_for_date = fields.Date()
    show_substitute_for_date = fields.Boolean(compute='_compute_show_sub_for_date', default=False)
    is_substitute = fields.Boolean(compute='_compute_show_sub_for_date', default=False)

    # at_year_from = fields.Integer(compute='_compute_at_year_month', store=True)
    # at_month_from = fields.Integer(compute='_compute_at_year_month', store=True)
    # at_year_to = fields.Integer(compute='_compute_at_year_month', store=True)
    # at_month_to = fields.Integer(compute='_compute_at_year_month', store=True)
    status_sync = fields.Boolean(compute='_compute_status_sync', help="Wether cover status insync with leave status")

    state = fields.Selection(tracking=False)
    employee_id = fields.Many2one(tracking=False)
    number_of_days = fields.Float(tracking=False)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        # active_model = self.env.context.get('active_model', None)
        # active_id = self.env.context.get('active_id', None)
        at_id = self.env.context.get('at_id', False)
        # active_at = self.env[active_model].browse([active_id]) if active_model == 'hr.attendance' and active_id else False
        active_at = self.env['hr.attendance'].browse([at_id]) if at_id else False

        request_date = active_at.at_date if active_at else fields.Date.context_today(self)
        defaults['request_date_from'] = request_date
        defaults['request_date_to'] = request_date
        if active_at and active_at.absence == 'absence_am':
            defaults['request_date_to_am'] = True
        if active_at and active_at.absence == 'absence_pm':
            defaults['request_date_from_pm'] = True

        return defaults

    @api.onchange('request_date_from')
    def _domain_for_leave_type(self):
        """
        Customize domain for holiday_status_id (leave type)
        [ ]: Do not show substitute for no-sat-working employees but only if the request_date_from is SAT or SUN
        """
        self.ensure_one()
        lt_domain = []
        if self.request_date_from:
            leave_reason_id = self.env.context.get('leave_reason_id', None)
            leave_reason_code = self.env['hr.leave.cover.reason'].search([('id', '=', leave_reason_id)]).code if leave_reason_id else False

            employee_id = self.env['hr.employee'].browse(self.env.context['default_employee_id']) if self.env.context.get('default_employee_id', None) else None
            # no_sat_working = self.env['hr.attendance'].is_no_sat_working(employee_id=employee_id, at_date=self.request_date_from) if employee_id else False
            # is_holiday = False
            # if self.substitute_for_date:
                # is_holiday = self.env['hr.attendance'].with_context(active_test=False).search([('at_date', '=', self.substitute_for_date)], limit=1)._compute_is_holiday()

            LeaveType = self.env['hr.leave.type']

            lt_domain = ['|', ('validity_stop', '=', False), '&',
                         ('validity_stop', '>=', self.request_date_from),
                         ('validity_start', '<=', self.request_date_from)]

            lt_ids = LeaveType.search(lt_domain)
            lt = []
            if leave_reason_code == 'ah':
                # lt_domain.append(('is_ah', '=', True))
                lt = lt_ids.filtered(lambda t: t.is_ah)
            if leave_reason_code == 'summer_vacation':
                # lt_domain.append(('category', '=', 'summer_vacation'))
                lt = lt_ids.filtered(lambda t: t.category == 'summer_vacation')
            if leave_reason_code == 'absence':
                # lt_domain.append(('category', '=', 'absence'))
                lt = lt_ids.filtered(lambda t: t.category == 'absence')

            if lt:
                self.holiday_status_id = lt[0].id

        return {'domain': {'holiday_status_id': lt_domain}}

    @api.onchange('request_date_from')
    def _date_from_change(self):
        for holiday in self:
            if holiday.request_date_to < holiday.request_date_from:
                holiday.request_date_to = holiday.request_date_from

    @api.onchange('request_date_to')
    def _date_to_change(self):
        for holiday in self:
            if holiday.request_date_from > holiday.request_date_to:
                holiday.request_date_from = holiday.request_date_to

    # @api.depends('request_date_from', 'request_date_to')
    def _is_same_request_date(self):
        for holiday in self:
            if (holiday.request_date_from and holiday.request_date_to):
                holiday.same_request_date = holiday.request_date_from == holiday.request_date_to
            else:
                holiday.same_request_date = False

    @api.depends('date_from', 'date_to')
    def _compute_date(self):
        for h in self:
            h.dt_from = h.date_from.date() if h.date_from else False
            h.dt_to = h.date_to.date() if h.date_to else False
            # if h.date_from:
            #     h.dt_from = h.date_from.date()
            # if h.date_to:
            #     h.dt_to = h.date_to.date()

    # @api.multi
    # @api.onchange('holiday_status_id', 'employee_id', 'request_date_from', 'request_date_to', 'request_date_from_pm', 'request_date_to_am', 'request_date_from_period', 'request_date_to_period')
    # def _compute_related_fields_in_leave_cover(self):
    #     self.ensure_one()
    #     if self.leave_cover_id:
    #         self.leave_cover_id._compute_date()

    # def _compute_substitute(self):
    #     self.ensure_one()
    #     leave = self
    #     domain = [('id', '<', 0)]
    #     # [] TODO: using summary_id's method for consistence and avoid DRY
    #     if all([leave.holiday_status_id, leave.employee_id, leave.request_date_from, leave.request_date_to]) \
    #            and leave.holiday_status_id.category == 'sub_holiday' and leave.request_date_from == leave.request_date_to:
    #         sub_hol_domain = [('employee_id', '=', leave.employee_id.id), ('start_date', '<=', leave.request_date_from), ('end_date', '>=', leave.request_date_from), 
    #             ('work_on_holiday', '!=', False), ('request_ot_for', '=', False),
    #             '|', ('absence', '=', False), ('absence', '!=', 'absence'), 
    #             '|', '|', '|', ('is_holiday', '=', True), ('is_public_holiday', '=', True), ('is_other_holiday', '=', True), ('ah', '!=', False)]
    #         sub_hol_ids = self.env['hr.attendance'].search(sub_hol_domain).mapped('id')
    #         occupied_sub_hol_ids = self.env['hr.leave'].search([('substitute_for_at_id', 'in', sub_hol_ids)]).mapped('substitute_for_at_id').mapped('id')
    #         avai_ids = list(set(sub_hol_ids) - set(occupied_sub_hol_ids))
    #         domain = [('id', 'in', avai_ids)]

    #         leave.show_substitute = True
    #     else:
    #         leave.substitute_for_at_id = False
    #         leave.show_substitute = False

    #     return {'domain': {'substitute_for_at_id': domain}}

    @api.depends('holiday_status_id', 'request_date_from')
    def _compute_show_sub_for_date(self):
        for leave in self:
            show = False
            is_substitute = False
            if leave.holiday_status_id.is_ah and leave.request_date_from.weekday() != 5:
                is_substitute = True
            if leave.request_date_from and leave.holiday_status_id.category == 'sub_holiday':
                if not self.env['hr.attendance']._is_holiday(leave.request_date_from):
                    show = True
                    is_substitute = True
            leave.update({'show_substitute_for_date': show, 'is_substitute': is_substitute})

    @api.onchange('substitute_for_at_id')
    def _compute_substitute_period(self):
        self.ensure_one()
        leave = self

        if leave.substitute_for_at_id and leave.substitute_for_at_id.absence:
            if leave.substitute_for_at_id.absence == 'absence_am':
                leave.substitute_period = 'pm'
            elif leave.substitute_for_at_id.absence == 'absence_pm':
                leave.substitute_period = 'am'
        else:
            leave.substitute_period = False

    # @api.multi
    # @api.depends('request_date_from', 'request_date_to', 'request_date_from_period', 'request_date_to_period')
    # def _compute_at_year_month(self):
    #     for h in self:
    #         ym_from = self.get_at_year_month(h.request_date_from)
    #         ym_to = self.get_at_year_month(h.request_date_to)
    #         h.at_year_from, h.at_month_from = ym_from
    #         h.at_year_to, h.at_month_to = ym_to

    def _compute_status_sync(self):
        for h in self:
            status_sync = False
            if h.leave_cover_id.state in ['draft', 'waiting_fman']:
                status_sync = h.state in ['draft', 'confirm']
            elif h.leave_cover_id.state in ['refuse']:
                status_sync = h.state in ['refuse', 'draft']
            else:
                status_sync = h.state == 'validate'
            h.status_sync = status_sync
    
    def leave_by_at_date(self):
        """
            - Helper method
            - Return list of dict for each day leave information
            - [{employee, leave, at_date, holiday_type, period, substitute_for_date, at, day_th}]
        """
        res = []
        for leave in self:
            at_dates = [leave.request_date_from + relativedelta(days=d) for d in range((leave.request_date_to - leave.request_date_from).days + 1)]
            # one search for the whole leave instead of one per day (same records, same order)
            ats_by_date = {}
            if at_dates:
                for at in self.env['hr.attendance'].search([('employee_id', '=', leave.employee_id.id),
                                                            ('at_date', '>=', at_dates[0]),
                                                            ('at_date', '<=', at_dates[-1])]):
                    ats_by_date.setdefault(at.at_date, []).append(at.id)
            for n, at_date in enumerate(at_dates):
                leave_info = {
                    'employee': leave.employee_id,
                    'leave': leave,
                    'at_date': at_date,
                    'holiday_type': leave.holiday_status_id,
                    'period': 'AM' if (leave.request_date_to_am and leave.request_date_to == at_date) else 'PM' if (leave.request_date_from_pm and leave.request_date_from == at_date) else '',
                    'substitute_for_date': leave.substitute_for_date or False,
                    'at': self.env['hr.attendance'].browse(ats_by_date.get(at_date, [])),
                    'day_th': n + 1
                }
                res.append(leave_info)

        res.sort(key=lambda e: e['at_date'])
        return res

    def by_at_date_leave(self, at_date):
        """
            - Helper method
            - Return list of leave dict for an at_date
            - Maximum 2 element (2 halfs with 2 different leave types)
        """
        if not at_date:
            raise UserError(_('Need a date to run! REF: at_date_leave'))
        res = []
        for r in self:
            res += list(filter(lambda e: e['at_date'] == at_date, r.leave_by_at_date()))
        return res

    # @api.onchange('substitute_for_date')
    # def onchange_holiday_fields(self):
    #     print('=====', self.substitute_for_date)
    #     if self.substitute_for_date:
    #         self._validate_sub_date()

    # ===== CRUD =====
    @api.model_create_multi
    def create(self, vals_list):
        """Odoo 19 passes a list of dicts; the Odoo 12 body below handles one dict at a time."""
        records = self.browse()
        for vals in vals_list:
            records |= self._legacy_create(vals)
        return records

    def _legacy_create(self, values):
        holiday = super().create(values)
        if self.env.context.get('kdvn_no_compute'):
            return holiday   # legacy import: Odoo 12 values as they are
        for h in holiday:
            if self.env.context.get('run_holiday_onchange', False):
                h.onchange_period()
                # h._onchange_request_parameters()
            h.leave_cover_id._compute_date()
            
            # TODO: review for performance. Still need in unlink then recreate cases
            h.leave_cover_id.related_at_ids()._compute_leave_cover_ids()
        return holiday

    def write(self, values):
        if self.env.context.get('kdvn_no_compute'):
            return super().write(values)   # legacy import (re-run)
        date_changed = values.get('request_date_from', None) or values.get('request_date_to', None)
        period_changed = values.get('request_date_from_period', None) or values.get('request_date_to_period', None)
        old_dt_from, old_dt_to = None, None
        if date_changed:
            old_dt_from = self.request_date_from
            old_dt_to = self.request_date_to
            old_dt_from = old_dt_from or old_dt_to
            old_dt_to = old_dt_to or old_dt_from

        result = super().write(values)
        effected_at_ids = self.env['hr.attendance'].sudo().with_context(active_test=False)

        # Update Leave cover dates
        for h in self:
            if date_changed or period_changed:
                h.sudo().leave_cover_id._compute_date()
            effected_at_ids |= h.sudo().leave_cover_id.related_at_ids()

        # Update related_at_ids leave_cover_ids, leave_ids
        if date_changed:
            effected_at_ids |= self.env['hr.attendance'].search([('employee_id', '=', self.employee_id.id), ('at_date', '>=', old_dt_from), ('at_date', '<=', old_dt_to)])
            effected_at_ids._compute_leave_cover_ids()

        return result

    # @profile
    def unlink(self):
        # TODO [X]: Recompute leave_ids for related ats (calling _compute_leave_cover_ids method)
        related_at_ids = self.env['hr.attendance']
        for h in self:
            if not self.env.context.get('do_not_update_at_leave_ids', False):
                related_at_ids |= h.leave_cover_id.related_at_ids()
        res = super().unlink()
        for at in related_at_ids:
            at._compute_leave_cover_ids()
        return res

    # ===== Business Methods =====

    def _create_resource_leave(self):
        """ 
        Override this method to create resource leaves with calendar_id reflecting calendar working hours
        by date (there is a change in apply which kind of working calendar to be used)
        - Using at_rules to get correct resource calendar
        """
        for leave in self:
            date_from = fields.Datetime.from_string(leave.date_from)
            date_to = fields.Datetime.from_string(leave.date_to)
            at_rules = self.env['hr.attendance']._at_rules(employee_id=leave.employee_id, at_date=date_from.date())
            current_rc_id = at_rules['resource_calendar_id'][0]

            self.env['resource.calendar.leaves'].create({
                'name': leave.name,
                'date_from': fields.Datetime.to_string(date_from),
                'holiday_id': leave.id,
                'date_to': fields.Datetime.to_string(date_to),
                'resource_id': leave.employee_id.resource_id.id,
                'calendar_id': current_rc_id,
                'time_type': leave.holiday_status_id.time_type,
            })
        return True

    # @api.multi
    # def _remove_resource_leave(self):
    #     """ This method will create entry in resource calendar leave object at the time of holidays cancel/removed """
    #     return self.env['resource.calendar.leaves'].search([('holiday_id', 'in', self.ids)]).unlink()    

    
    # ===== Report =====
    def report_leave_by_at_date(self, month=False, year=False):
        """
            Generate list of dict for leave report in order to import into FSC database
            {'staff_no', 'staff_name', 'at_date', 'leave_reason': L or SH, 'leave_type': 0 or 3}
        """
        res = []
        today = fields.Date.context_today(self)
        current_date_fr = self.get_start_dt(today, for_month=True)
        if not year:
            year = current_date_fr.year
        if not month:
            month = current_date_fr.month
        date_to = datetime.date(year, month, current_date_fr.day)  # 21/mm/yyyy
        date_fr = date_to - relativedelta(months=1)  # 21/mm-1/yyyy

        # leave_domain = [('state', 'not in', ('draft', 'refuse')),
        #                 '!', '&', ('holiday_status_id.is_ah', '=', True), ('substitute_for_date', '=', False),
        #                 '!', '|', ('request_date_from', '>', date_to), ('request_date_to', '<=', date_fr)]
        # leave_domain = [('state', 'not in', ('draft', 'confirm', 'refuse')),
        #                 '!', '|', ('request_date_from', '>=', date_to), ('request_date_to', '<', date_fr)]
        leave_domain = [('state', '=', 'validate'),
                        '!', '|', ('request_date_from', '>=', date_to), ('request_date_to', '<', date_fr)]
        # month_leaves = self.search(leave_domain).filtered(lambda h: not (h.holiday_status_id.is_ah and h.request_date_from.weekday() == 5) and not h.substitute_for_date)
        month_leaves = self.search(leave_domain).filtered(lambda h: not (h.holiday_status_id.is_ah and h.request_date_from.weekday() == 5))
        for leave in month_leaves:
            # leave_reason = 'L' if leave.holiday_status_id.category == 'annual_leave' else 'SH'
            for e in filter(lambda r: r['at_date'] >= date_fr and r['at_date'] < date_to, leave.leave_by_at_date()):
                is_half_day = e['period'] != ''
                leave_type = 3 if is_half_day else 0
                # remove '1/2 O' marks if any
                leave_reason = set(e['at'].status_ids.mapped('code')) - {'1/2 O'}
                # not counting substitute leave but absence on holiday or AH
                if not (len(leave_reason) == 1 and {'1/2 X', 'X'} & leave_reason):
                    if '1/2 X' in leave_reason:
                        if leave_type == 0:
                            leave_type = 3
                        leave_reason = leave_reason - {'1/2 X'}
                    leave_info = {
                        'staff_no': e['employee'].code,
                        'staff_name': e['employee'].name,
                        'at_date': e['at_date'],
                        'leave_reason': ', '.join(leave_reason),
                        'leave_type': leave_type,
                    }
                    # TODO [X]: 2 half leaves of the same day, which the same type
                    existed_info = list(filter(lambda e: e['staff_no'] == leave_info['staff_no'] and e['at_date'] == leave_info['at_date'] and e['leave_reason'] == leave_info['leave_reason'], res))
                    if existed_info:
                        existed_info[0]['leave_type'] = 0
                    else:
                        res.append(leave_info)

        # TODO [X]: remove 1/2 from leave_reason
        # REF: https://stackoverflow.com/questions/1452995/why-doesnt-a-python-dict-update-return-the-object
        res = [e if e['leave_type'] != 3 else (e.update({'leave_reason': e['leave_reason'].replace('1/2 ', '')}) or e) for e in res]
        res.sort(key=lambda e: (e['staff_no'], e['at_date']))
        print(res)
        return(res)

    # ====== CONSTRAINTS =====
    @api.constrains('request_date_from_period', 'request_date_to_period', 'request_date_from_pm', 'request_date_to_am')
    def _check_halfday(self):
        for holiday in self:
            # Leaves must be continuous
            if holiday.request_date_from != holiday.request_date_to:
                if holiday.request_date_from_period == 'am':
                    raise ValidationError(_('You should choose continuous date range!'))
            # If substitute period is selected then is either request_date_from_pm or request_date_to_am
            if holiday.substitute_for_date and holiday.substitute_period and not holiday.request_date_from_pm and not holiday.request_date_to_am:
                raise ValidationError(_('You must choose Afternoon or Morning'))

    @api.constrains('holiday_status_id', 'substitute_for_date', 'substitute_period')
    def _validate_sub_date(self):
        for leave in self:
            if leave.show_substitute_for_date and not leave.substitute_for_date:
                raise ValidationError(_('Please input substitute date!'))
            if leave.show_substitute_for_date and leave.substitute_for_date:
                # TODO [X]: duration <= 01 day
                # TODO [X]: request_date_from == request_date_to
                if leave.holiday_status_id.category == 'sub_holiday':
                    # sub_at = self.env['hr.attendance'].search([('employee_id', '=', leave.employee_id.id), ('at_date', '=', leave.substitute_for_date)])
                    no_sat_working = self.env['hr.attendance'].is_no_sat_working(employee_id=leave.employee_id, at_date=leave.request_date_from) if leave.employee_id else False
                    # is_holiday = self.env['hr.attendance']._is_holiday(leave.substitute_for_date)
                    is_holiday = self.env['hr.attendance'].with_context(active_test=False).search([('at_date', '=', leave.substitute_for_date), ('employee_id', '=', leave.employee_id.id)])._is_holiday(leave.substitute_for_date)
                    related_sub = self.search([('id', '!=', leave.id), ('employee_id', '=', leave.employee_id.id), ('substitute_for_date', '=', leave.substitute_for_date)])
                    if not is_holiday:
                        raise ValidationError(_('Substitute Date is NOT a Holiday!'))
                    elif no_sat_working and is_holiday == 'H':
                        raise ValidationError(_(f'You are not allowing to register substitute leave for this day! {leave.substitute_for_date}'))
                    elif leave.request_date_from != leave.request_date_to:
                        raise ValidationError(_('Register subtitute leave for the same day only!'))
                    elif self.get_at_year_month(leave.request_date_from) != self.get_at_year_month(leave.substitute_for_date):
                        # TODO [X]: check holiday in the current month
                        raise ValidationError(_('Sub. date must be the same month with leave date!'))
                    elif related_sub and not (related_sub.substitute_period and leave.substitute_period and related_sub.substitute_period != leave.substitute_period):
                        # TODO [X]: check holiday already registered before
                        raise ValidationError(_('Sub. date already registered!'))
                    else:
                        pass
                else:
                    raise ValidationError(_('Only apply substitute Date for Holidays!'))
            if leave.substitute_for_date and not leave.holiday_status_id.category == 'sub_holiday':
                # clear substitute for date
                leave.substitute_for_date = False
                leave.substitute_period = False
            # Must use last year leave first
            if leave.holiday_status_id.category == 'annual_leave' and leave.holiday_status_id.name == 'Annual Leave':
                domain = [('category', '=', 'annual_leave'), ('name', '=', 'Last Year Leave'), ('valid', '=', True)]
                last_year_lt = self.env['hr.leave.type'].with_context(default_date_from=leave.request_date_from).search(domain)  # need a date to compute leave type valid
                # remaining_leaves must > 0 (case number_of_days == remaining_leaves == 0)
                if last_year_lt and last_year_lt.virtual_remaining_leaves > 0 and last_year_lt.virtual_remaining_leaves >= leave.number_of_days:
                    raise ValidationError(_(f'You still have {last_year_lt.virtual_remaining_leaves} days of Last Year Leaves. Please use them!'))

    @api.constrains('holiday_status_id', 'request_date_from')
    def _validate_allow_use_special_leave(self):
        for h in self:
            if h.holiday_status_id and h.holiday_status_id.category == 'special_leave':
                # Check leave allocation allowing for use yearly special leave
                la = self.env['hr.leave.allocation'].search([('employee_id', '=', h.employee_id.id), ('holiday_status_id', '=', h.holiday_status_id.id)])
                if len(la) == 1 and not la.allow_to_use:
                    raise ValidationError(_('Cannot use yearly special leaves! Please contact HR for further support. REF.: {}'.format(la.name)))

    @api.constrains('request_date_from', 'request_date_to', 'holiday_status_id')
    def _validate_request_leave_on_sat(self):
        for h in self:
            # User must NOT request none-AH leave on first 2/3 sats (for month of 4/5 sats) as long as still having AH allocation
            # User must NOT request 1/2 Leave (Leave, Absence, AH) on an absence day (not allow 2-leave-status on a day)
            # TODO [X]: Must consider SAT is not Holiday
            # TODO [X]: Must ignore Summer Holiday register
            # Absence leave?
            leave_dates = [h.request_date_from + relativedelta(days=d) for d in range((h.request_date_to - h.request_date_from).days + 1)]
            for a_date in leave_dates:
                if not any([self.env.uid in [1, 2], self.env['hr.mixin'].groups()['hr_staff'], {'House Maid', 'Driver', 'Outsource'} & set(h.employee_id.category_ids.mapped('name'))]):
                    if a_date.weekday() == 5 and not self.env['hr.attendance']._is_holiday(a_date) and not (h.holiday_status_id.is_special and h.holiday_status_id.category == 'summer_vacation'):
                        ah_lt = self.env['hr.leave.type'].search([('is_ah', '=', True), ('validity_start', '<=', a_date), ('validity_stop', '>=', a_date)])
                        if not (h.holiday_status_id.category == 'absence' or h.holiday_status_id.is_ah or (not h.holiday_status_id.is_ah and ah_lt.virtual_remaining_leaves == 0)):
                            # if h.number_of_days >= 1:
                            raise ValidationError(_(f'You should request AH leave for {a_date}! If you have special needs, Please contact HR for support.'))
                            
                    related_at = self.env['hr.attendance'].search([('employee_id', '=', h.employee_id.id), ('at_date', '=', a_date)])
                    if related_at.data_enough and related_at.absence == 'absence' and h.number_of_days == 0.5:
                        raise ValidationError(_(f'You should NOT request 1/2 L for an absence day of {a_date}! Please contact HR for instruction.'))
    
    @api.constrains('holiday_status_id')
    def _validate_allow_duration_for_special_leave(self):
        for h in self:
            if h.holiday_status_id.is_special and h.holiday_status_id.category == 'other':
                related_al = self.env['hr.leave.allocation'].search([('employee_id', '=', h.employee_id.id), ('holiday_status_id', '=', h.holiday_status_id.id), ('state', '=', 'validate'),
                                                                     '|', ('valid_to', '=', False), ('valid_to', '>=', fields.Date.context_today(self))])
                valid_from = min(related_al.mapped('valid_from') or [False])
                valid_to = max(related_al.mapped('valid_to') or [False])
                if valid_from and valid_to:
                    if not (h.request_date_from >= valid_from and h.request_date_to <= valid_to):
                        raise ValidationError(_(f'You are only allowed to register special leave between {valid_from} and {valid_to}! If you think this is a mistake, please contact HR for instruction.'))
    
    @api.constrains('date_from', 'date_to', 'state', 'employee_id')
    def _check_leave_type(self):
        for holiday in self.filtered('employee_id'):
            for h in filter(lambda e: e['period'], self.leave_by_at_date()):
                domain = [
                    ('employee_id', '=', holiday.employee_id.id),
                    ('date_from', '<=', h['at_date']),
                    ('date_to', '>=', h['at_date']),
                    ('state', 'not in', ['cancel', 'refuse']),
                    ('id', '!=', h['leave'].id)
                ]
                other_leaves = self.env['hr.leave'].search(domain)
                another_h = other_leaves.by_at_date_leave(at_date=h['at_date'])
                another_h = another_h[0] if another_h else {}
                allow = False
                if another_h:
                    if h['leave'].holiday_status_id.is_ah and (another_h['leave'].holiday_status_id.is_ah or another_h['leave'].holiday_status_id.category == 'absence'):
                        allow = True
                    elif another_h['leave'].holiday_status_id.is_ah and (h['leave'].holiday_status_id.is_ah or h['leave'].holiday_status_id.category == 'absence'):
                        allow = True
                    elif not h['leave'].holiday_status_id.is_ah and not another_h['leave'].holiday_status_id.is_ah:
                        allow = True
                else:
                    allow = True

                if not allow:
                    raise ValidationError(_(f'You cannot create leave in this case. Please ask HR for instruction!'))
    
    # override
    # def _check_leave_type_validity(self):
    #     # just disable for allowing taking leave in the past
    #     return True


    @api.onchange('request_date_from_pm', 'request_date_to_am')
    def onchange_period(self):
        """Morning / afternoon tick boxes -> request_date_from_period / request_date_to_period (read by the Odoo 19 core date computation).
        Same day: morning only = am/am, afternoon only = pm/pm. Several days: first day afternoon only (from=pm), last day morning only (to=am)."""
        for holiday in self:
            if holiday.same_request_date:
                if holiday.request_date_from_pm and not holiday.request_date_to_am:
                    holiday.request_date_from_period = holiday.request_date_to_period = 'pm'
                elif holiday.request_date_to_am and not holiday.request_date_from_pm:
                    holiday.request_date_from_period = holiday.request_date_to_period = 'am'
                else:
                    holiday.request_date_from_period = holiday.request_date_to_period = False
            else:
                holiday.request_date_from_period = 'pm' if holiday.request_date_from_pm else False
                holiday.request_date_to_period = 'am' if holiday.request_date_to_am else False

    @api.depends('leave_type_request_unit')
    def _compute_request_unit_half(self):
        """KDVN leave is always counted in days and half days."""
        for holiday in self:
            holiday.request_unit_half = True

    @api.depends('leave_type_request_unit')
    def _compute_request_unit_hours(self):
        for holiday in self:
            holiday.request_unit_hours = False

    # ###################################
    # APIS
    # ###################################

    def _onchange_request_parameters(self):
        """Odoo 12 computed date_from / date_to here. In Odoo 19 core `_compute_date_from_to` does (it supports half days through the periods)."""
        return

    def action_draft(self):
        """Odoo 12 'To Submit' state does not exist in Odoo 19 (states: confirm, refuse, validate1, validate, cancel): back to 'confirm'."""
        return self.with_context(leave_skip_state_check=True).write({'state': 'confirm'})

    def _onchange_leave_dates(self):
        """Odoo 12 core method (set number_of_days from date_from/date_to), gone in Odoo 19 where the duration is a compute."""
        for leave in self:
            if leave.date_from and leave.date_to:
                days, hours = leave._get_durations()[leave.id]
                leave.number_of_days = days
                leave.number_of_hours = hours
            else:
                leave.number_of_days = 0

    # override
    def _onchange_employee_id(self):
        self._sync_employee_details()
        LeaveType = self.env['hr.leave.type'].with_context(employee_id=self.employee_id, default_date_from=self.date_from or fields.Datetime.now())
        lt = LeaveType.search([('valid', '=', True)])
        self.holiday_status_id = lt[0].id if len(lt) > 0 else False

    def _compute_intervals(self, leave=True):
        """[Return leave intervals for a given date]

        """
        self.ensure_one()

        r_id = self.employee_id.resource_id.id
        r_leave = self.env['resource.calendar.leaves'].search([('resource_id', '=', r_id), ('holiday_id', '=', self.id)])

        if r_leave:
            if not r_leave.date_from.tzinfo:
                d_from = r_leave.date_from.replace(tzinfo=utc)
            else:
                d_from = r_leave.date_from
            if not r_leave.date_to.tzinfo:
                d_to = r_leave.date_to.replace(tzinfo=utc)
            else:
                d_to = r_leave.date_to

            if leave:
                # print(self.employee_id.name, len(self.with_context(exclude_public_holidays=True).employee_id.resource_id.calendar_id._work_intervals(d_from, d_to)))
                return r_leave.with_context(exclude_public_holidays=True).calendar_id._work_intervals(d_from, d_to)
            else:
                return r_leave.with_context(exclude_public_holidays=True).calendar_id._attendance_intervals(d_from, d_to)
        else:
            return None

    # ===== Activity methods =====

    def activity_update(self):
        # override to disable this method, use hr.leave.cover model instead
        return False

    # ===== Messaging methods =====

    def _track_subtype(self, init_values):
        # override to disable this method, use hr.leave.cover model instead
        return False

    # ===== STATES =====


class KderpHolidaysType(models.Model):
    _name = "hr.leave.type"
    _description = "KDERP Leave Type"
    _inherit = ["hr.leave.type"]

    # --- Odoo 12 core fields that Odoo 19 hr_holidays no longer has (stage B decides how each is really used) ---
    validity_start = fields.Date('Valid From')
    validity_stop = fields.Date('Valid To')
    allocation_type = fields.Selection([('no', 'No Limit'), ('fixed_allocation', 'Allow Employees Requests'), ('fixed', 'Set by Time Off Officer')],
                                       default='fixed', string='Mode')

    is_ah = fields.Boolean(default=False, string="AH leave")
    is_special = fields.Boolean(default=False, string="Special leave")

    max_leaves = fields.Float(search="_search_max_leaves")
    leaves_taken_past = fields.Float(compute='_compute_leaves')
    remaining_leaves = fields.Float(compute='_compute_leaves', string='Remaining Time Off')   # Odoo 12 core field (max_leaves - leaves_taken), set by our _compute_leaves
    category = fields.Selection([
        ('annual_leave', 'Annual Leave'),
        ('special_leave', 'Special Leave'),
        ('summer_vacation', 'Summer Vacation'),
        ('sub_holiday', 'Substituted Holiday'),
        ('absence', 'Absence'),
        ('other', 'Other')
    ], default='other')
    sort_weight = fields.Integer('Sort weight', compute='_compute_sort_weight', help="Determine how to sort leave type in name_get")

    # Override
    # @api.multi
    # def name_get(self):
    #     res = super().name_get()
    #     valid_allocation_date = self.env.context.get('valid_allocation_date', None)
    #     if not valid_allocation_date:
    #         return res
    #     else:
    #         end_dt = self.env['hr.mixin'].get_start_dt(a_date=valid_allocation_date) + relativedelta(years=1)
    #         if end_dt.year >= fields.Date.context_today(self).year:
    #             return res
    #         else:
    #             new_res = [list(e) for e in res]
    #             for r in new_res:
    #                 if r[1].startswith('Last Year Leave'):
    #                     r[1] = f'Annual Leave {end_dt.year}'
    #             return new_res
    
    def _compute_accrual_count(self):
        """Core counts the accrual plans as the current user: users without read access on them (section managers) could not
        open the leave type form. Only a number is exposed, so count as superuser."""
        return super(KderpHolidaysType, self.sudo())._compute_accrual_count()

    # @api.depends('name', 'category', 'is_ah', 'is_special')
    def _compute_sort_weight(self):
        for t in self:
            sort_weight = 999
            today = datetime.date.today()
            remaining_leaves = t.virtual_remaining_leaves > 0 and t.max_leaves > 0
            if t.name == 'Annual Leave':
                sort_weight = 150
            if t.name == 'Last Year Leave':
                sort_weight = 100 if remaining_leaves else 600
            if t.is_ah:
                additional_weight = (today - t.validity_start).days // 30
                sort_weight = 500 + additional_weight if remaining_leaves else 700 + additional_weight
            if t.is_special and t.category == 'other':
                sort_weight = 400 if remaining_leaves else 800
            if t.is_special and t.category == 'summer_vacation':
                sort_weight = 200 if remaining_leaves else 900
            if t.category == 'special_leave':
                year = re.search(r'(\d{4})\s*$', t.name or '')   # a name without a final year keeps the default weight
                sort_weight = 900 + datetime.date.today().year - int(year.group(1)) if year else 900

            t.sort_weight = sort_weight

    def _get_contextual_employee_id(self):
        """
            - override to handle more cases that can get employee_id
            - try to get employee_id in case context having active_id
        """
        if 'active_id' in self.env.context and 'active_model' in self.env.context and 'employee_id' in self.env[self.env.context.get('active_model')]:
            employee_id = self.env[self.env.context.get('active_model')].browse(self.env.context.get('active_id')).employee_id.id
        elif 'employee_id' in self.env.context:
            employee_id = self.env.context['employee_id']
        elif 'default_employee_id' in self.env.context:
            employee_id = self.env.context['default_employee_id']
        elif 'at_id' in self.env.context:
            employee_id = self.env['hr.attendance'].browse([self.env.context['at_id']]).employee_id.id
        else:
            employee_id = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1).id
        
        return employee_id

    def _legacy_name_get(self):
        """
            - Override
        """
        employee_id = self._get_contextual_employee_id()
        no_filter_leave_type = self.env.context.get('no_filter_leave_type', False)
        if not employee_id :
            # leave counts is based on employee_id, would be inaccurate if not based on correct employee
            return []
        res = []
        for record in self:
            name = record.name
            if record.category == 'special_leave':
                al = self.env['hr.leave.allocation'].search([('employee_id', '=', employee_id), ('holiday_status_id', '=', record.id)])
                if len(al) == 1 and not al.allow_to_use or len(al) == 0:
                    name = f'--{name}--'
            if record.allocation_type != 'no':
                name = "%(name)s (%(count)s)" % {
                    'name': name,
                    'count': _('%g') % (
                        float_round(record.virtual_remaining_leaves, precision_digits=2) or 0.0
                        # float_round(record.max_leaves, precision_digits=2) or 0.0,
                    ) + (_(' hours') if record.request_unit == 'hour' else _(' days'))
                }
            res.append((record.id, name))
        return res

    @api.depends('name', 'category', 'allocation_type', 'request_unit')
    @api.depends_context('employee_id', 'default_employee_id', 'at_id', 'no_filter_leave_type', 'uid')
    def _compute_display_name(self):
        """Odoo 19: display_name is computed. With an employee in the context the name carries the remaining days (Odoo 12 name_get)."""
        if not self._get_contextual_employee_id():
            return super()._compute_display_name()
        names = dict(self._legacy_name_get())
        for rec in self:
            rec.display_name = names.get(rec.id) or rec.name

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        """
            - Override to change the sort mechanism
            - !NOTE: be careful with the filtered because by default this method will set
            - context search_disable_custom_filters to True to disable all filters when
            - having active_id or active_ids
            - TODO []: in_probation_period but having OT Compensation => will allow
        """
        # Odoo 19 reads a record's fields through _search([('id', 'in', ids)]): such a lookup must not run the sorting / filtering below (it reads
        # fields to sort, which searches again: endless recursion for any user who has an employee in the context)
        if (isinstance(domain, (list, tuple)) and len(domain) == 1 and isinstance(domain[0], (list, tuple)) and tuple(domain[0][:2]) == ('id', 'in')):
            return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)
        # apply for showing all leave type and leave allocation for hr admin
        is_admin_user = self.env.uid in [1, 2] or 'HR Admin' in self.env.user.all_group_ids.mapped('name')
        no_filter_leave_type = self.env.context.get('no_filter_leave_type', False) or is_admin_user
        
        employee_id = self._get_contextual_employee_id()
        post_sort = (not order and employee_id)
        query = super()._search(domain, offset=offset, limit=(None if post_sort else limit), order=order, **kwargs)
        leave_ids = list(query)   # Odoo 19: _search returns a Query, Odoo 12 a list of ids
        leaves = self.browse(leave_ids)
        request_date_from = self.env.context.get('request_date_from', False)
        if request_date_from:
            at_date = datetime.datetime.strptime(request_date_from, '%Y-%m-%d').date()
            leaves = leaves.filtered(lambda t: t.validity_start <= at_date and (t.validity_stop == False or t.validity_stop >= at_date))
        
        def show_leave_type(leave_type):
            """
                - helper method to determine showing leave type on Many2one or not
            """
            in_probation_period = False
            if employee_id:
                employee = self.env['hr.employee'].browse(employee_id)
                in_probation_period = True if (employee.official_working_date and employee.official_working_date > self.env['hr.mixin'].today_vn()) else False

                if in_probation_period and leave_type.category == 'annual_leave':
                    ot_la = self.env['hr.leave.allocation'].search([('employee_id', '=', employee_id), ('holiday_status_id', '=', leave_type.id), ('name', '=', 'OT Compensation')])
                    if ot_la.number_of_days > 0:
                        in_probation_period = False
                
            res = False if (in_probation_period and (leave_type.category != 'absence' and not leave_type.is_ah)) else True
            
            if leave_type.category == 'special_leave' and not in_probation_period:
                la = self.env['hr.leave.allocation'].search([('employee_id', '=', employee_id), ('holiday_status_id', '=', leave_type.id)])
                if not la or (la and len(la) == 1 and not la.allow_to_use):
                    res = False
            if leave_type.category == 'other' and leave_type.is_special and not in_probation_period:
                if not self.env['hr.mixin'].groups().get('hr_staff', False) and leave_type.with_context(employee_id=employee_id).remaining_leaves <=0:
                    res = False
                else:
                    res = True
            if leave_type.is_ah and leave_type.with_context(employee_id=employee_id).remaining_leaves <=0:
                res = False
            return res
        
        if post_sort:
            # !NOTE: filter leave type here will effect other models like allocation, leave...
            # !Danger => need better approach
            new_leave_ids = leaves.sorted(key=lambda r: r.sort_weight)
            if not no_filter_leave_type:
                new_leave_ids = new_leave_ids.filtered(lambda r: show_leave_type(r))
            return self.browse(new_leave_ids.ids[:limit])._as_query()
        return query

    valid = fields.Boolean(compute='_compute_valid', search='_search_valid', help='This indicates if it is still possible to use this type of leave')   # Odoo 12 core field, gone in Odoo 19

    def _search_valid(self, operator, value):
        wanted = (True in value) if operator in ('in', 'not in') else bool(value)
        if operator in ('!=', 'not in'):
            wanted = not wanted
        types = self.with_context(no_filter_leave_type=True, active_test=False).search([], order='id')
        ids = types.filtered(lambda t: t.valid).ids
        return [('id', 'in' if wanted else 'not in', ids)]

    def _compute_valid(self):
        """
            - Override because duplicate date_from fields that make default_date_from
            is datetime instead of date type
            - Ability to compute allocation based on a specific date using context valid_allocation_date
        """
        super()._compute_valid()  # Odoo 19 core computes has_valid_allocation here; our override replaced it
        if self.env.context.get('valid_allocation_date', None):
            dt = self.env.context.get('valid_allocation_date')
        else:
            dt = self.env.context.get('default_date_from') or fields.Date.context_today(self)
        if isinstance(dt, str) and len(dt) >= 10:
            dt = datetime.datetime.strptime(dt[:10], '%Y-%m-%d').date()
        if isinstance(dt, datetime.datetime):
            dt = dt.date()

        for holiday_type in self:
            if holiday_type.validity_start and holiday_type.validity_stop:
                holiday_type.valid = ((dt <= holiday_type.validity_stop) and (dt >= holiday_type.validity_start))
            elif holiday_type.validity_start and not holiday_type.validity_stop:
                holiday_type.valid = dt >= holiday_type.validity_start
            else:
                holiday_type.valid = True
    
    def get_days(self, employee_id):
        """
            - Override to compute leaves taken in past for last_year leave that changed to
            - special leave xxxx
        """
        # need to use `dict` constructor to create a dict per id
        result = dict((id, dict(max_leaves=0, leaves_taken=0, leaves_taken_past=0, remaining_leaves=0, virtual_remaining_leaves=0)) for id in self.ids)

        # [X] TODO: Need to get archived leaves as well
        requests = self.env['hr.leave'].sudo().with_context(active_test=False).search([
            ('employee_id', '=', employee_id),
            ('state', 'in', ['confirm', 'validate1', 'validate']),
            ('holiday_status_id', 'in', self.ids)
        ])

        allocations = self.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee_id),
            ('state', 'in', ['confirm', 'validate1', 'validate']),
            ('holiday_status_id', 'in', self.ids)
        ])
        # ad hoc Special Leave: a grant is valid for one month; once valid_to has passed it (and the leaves taken
        # inside its window) no longer count, the allocation itself stays approved
        today = fields.Date.context_today(self)
        adhoc_types = self.filtered(lambda t: t.is_special and t.category == 'other')
        if adhoc_types:
            expired = allocations.filtered(lambda a: a.holiday_status_id in adhoc_types and a.valid_to and a.valid_to < today)
            allocations -= expired
            window_start = {}
            for a in allocations.filtered(lambda a: a.holiday_status_id in adhoc_types):
                window_start[a.holiday_status_id.id] = min(a.valid_from or datetime.date.min,
                                                           window_start.get(a.holiday_status_id.id, datetime.date.max))
            requests = requests.filtered(lambda r: r.holiday_status_id not in adhoc_types or (
                r.holiday_status_id.id in window_start and r.request_date_from >= window_start[r.holiday_status_id.id]))

        for request in requests:
            status_dict = result[request.holiday_status_id.id]
            status_dict['virtual_remaining_leaves'] -= (request.number_of_hours_display
                                                    if request.leave_type_request_unit == 'hour'
                                                    else request.number_of_days)
            if request.state == 'validate':
                status_dict['leaves_taken'] += (request.number_of_hours_display
                                            if request.leave_type_request_unit == 'hour'
                                            else request.number_of_days)
                status_dict['remaining_leaves'] -= (request.number_of_hours_display
                                                if request.leave_type_request_unit == 'hour'
                                                else request.number_of_days)
                
                if request.request_date_to < request.holiday_status_id.validity_start:
                    # leave taken in the past due to change in leave type validity date
                    status_dict['leaves_taken_past'] += (request.number_of_hours_display
                                            if request.leave_type_request_unit == 'hour'
                                            else request.number_of_days)
        for allocation in allocations:
            status_dict = result[allocation.holiday_status_id.id]
            if allocation.state == 'validate':
                # note: add only validated allocation even for the virtual
                # count; otherwise pending then refused allocation allow
                # the employee to create more leaves than possible
                status_dict['virtual_remaining_leaves'] += (allocation.number_of_hours_display
                                                          if allocation.type_request_unit == 'hour'
                                                          else allocation.number_of_days)
                status_dict['max_leaves'] += (allocation.number_of_hours_display
                                            if allocation.type_request_unit == 'hour'
                                            else allocation.number_of_days)
                status_dict['remaining_leaves'] += (allocation.number_of_hours_display
                                                  if allocation.type_request_unit == 'hour'
                                                  else allocation.number_of_days)

        return result

    def _compute_leaves(self):
        data_days = {}
        employee_id = self._get_contextual_employee_id()

        if employee_id:
            data_days = self.get_days(employee_id)

        for holiday_status in self:
            result = data_days.get(holiday_status.id, {})
            holiday_status.max_leaves = result.get('max_leaves', 0)
            holiday_status.leaves_taken = result.get('leaves_taken', 0)
            holiday_status.leaves_taken_past = result.get('leaves_taken_past', 0)
            holiday_status.remaining_leaves = result.get('remaining_leaves', 0)
            holiday_status.virtual_remaining_leaves = result.get('virtual_remaining_leaves', 0)


class KderpHolidaysAllocation(models.Model):
    _name = "hr.leave.allocation"
    _description = "KDERP Leave Allocation"
    _inherit = ['hr.leave.allocation']

    def _compute_leaves(self):
        """Core assigns max_leaves, leaves_taken and virtual_remaining_leaves in one method. Our class computes leaves_taken
        with its own method (_compute_remaining_leaves), which splits that group and leaves max_leaves unassigned
        ("Compute method failed to assign"). Same as core, without leaves_taken."""
        date_from = fields.Date.today()
        employee_days_per_allocation = self.employee_id._get_consumed_leaves(self.holiday_status_id, date_from)[0]
        for allocation in self:
            origin = allocation._origin
            virtual_leave = employee_days_per_allocation[origin.employee_id][origin.holiday_status_id][origin]
            allocation.max_leaves = virtual_leave['max_leaves']
            allocation.virtual_remaining_leaves = virtual_leave['virtual_remaining_leaves']

    # Odoo 19 refuses allocations of 0 days; Odoo 12 had expired grants with 0 days (kept as history)
    _duration_check = models.Constraint("CHECK( number_of_days >= 0 OR allocation_type != 'regular' )", 'The duration cannot be negative.')

    holiday_type = fields.Selection([('employee', 'By Employee')], default='employee', string='Allocation Mode')   # Odoo 12 core field

    @api.depends('holiday_status_id', 'number_of_days')
    def _compute_description(self):
        """Odoo 19 renames an allocation every time its days change ('Annual Leave (2.5 day(s))'). KDVN finds allocations by their name
        ('OT Compensation', 'Last Year Leave') and Odoo 12 never renamed them: only give a name when there is none."""
        for allocation in self:
            if not allocation.name:
                allocation.name = allocation._get_title()

    @api.model_create_multi
    def create(self, vals_list):
        """Odoo 19 allocations have their own validity dates (date_from defaults to today) and a leave needs an allocation that covers its
        days. Odoo 12 had no dates on the allocation: its validity was the validity of the leave type. Same here unless dates are given."""
        for vals in vals_list:
            leave_type = self.env['hr.leave.type'].browse(vals.get('holiday_status_id'))
            if leave_type.validity_start and not vals.get('date_from'):
                vals['date_from'] = leave_type.validity_start
            if leave_type.validity_stop and not vals.get('date_to'):
                vals['date_to'] = leave_type.validity_stop
        return super().create(vals_list)
    _order = 'employee_id, holiday_status_id'

    # name = fields.Char(states={'draft': [('readonly', False)], 'confirm': [('readonly', False)], 'validate': [('readonly', False)]})
    # override to allow choosing holiday type in the future (next month AH for example)
    holiday_status_id = fields.Many2one(domain=[])
    validity_start = fields.Date(related='holiday_status_id.validity_start')
    validity_stop = fields.Date(related='holiday_status_id.validity_stop')
    leaves_taken_past = fields.Float('Past leaves', compute='_compute_remaining_leaves', help='Compute by leave type.')
    leaves_taken = fields.Float('Leaves taken', compute='_compute_remaining_leaves', help='Compute by leave type.')
    remaining_leaves = fields.Float('Remain leaves', compute='_compute_remaining_leaves', help='Compute by leave type.')
    total_allowed = fields.Float('Total allowed', compute='_compute_remaining_leaves', help='Actual total allowed leaves')
    allow_to_use = fields.Boolean(default=False, help='Apply for yearly special leaves only')
    leave_ids = fields.One2many('hr.leave', string="Related Leaves", compute='_compute_related_leaves')
    valid_from = fields.Date(default=False, help='Apply for special leave only')
    valid_to = fields.Date(default=False, help='Apply for special leave only')
    leave_type_name = fields.Char(related='holiday_status_id.name', store=True)
    is_expired = fields.Boolean('Expired', compute='_compute_is_expired', search='_search_is_expired',
                                help='Ad hoc Special Leave whose valid-to date has passed. It stays approved but no longer counts in the balance.')
    ot_last_update = fields.Date('OT Last Update Month', help="Last AT Month OT Compensation Already Update", readonly=False)

    @api.depends('valid_to', 'holiday_status_id')
    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for a in self:
            lt = a.holiday_status_id
            a.is_expired = bool(lt.is_special and lt.category == 'other' and a.valid_to and a.valid_to < today)

    def _search_is_expired(self, operator, value):
        today = fields.Date.context_today(self)
        expired = ('holiday_status_id.is_special', '=', True), ('holiday_status_id.category', '=', 'other'), ('valid_to', '<', today)
        wanted = (True in value) if operator in ('in', 'not in') else bool(value)   # Odoo 19 rewrites '=' into 'in'
        positive = wanted if operator in ('=', 'in') else not wanted
        if positive:
            return ['&', '&'] + list(expired)
        return ['|', '|', ('holiday_status_id.is_special', '=', False), ('holiday_status_id.category', '!=', 'other'), '|', ('valid_to', '=', False), ('valid_to', '>=', today)]

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        defaults['valid_from'] = self.env['hr.mixin'].today_vn()
        defaults['valid_to'] = defaults['valid_from'] + relativedelta(months=1)
        return defaults

    def _compute_remaining_leaves(self):
        """
            - Compute remain leave by leave type
            - Maximum leaves - already approved leaves
            - Using _compute_leaves method in hr.leave.type
        """
        for a in self:
            if not a.employee_id:
                continue
            a.leaves_taken_past = a.with_context(employee_id=a.employee_id.id).holiday_status_id.leaves_taken_past
            a.remaining_leaves = a.with_context(employee_id=a.employee_id.id).holiday_status_id.remaining_leaves
            a.leaves_taken = a.with_context(employee_id=a.employee_id.id).holiday_status_id.leaves_taken - a.leaves_taken_past
            a.total_allowed = a.number_of_days
            if a.holiday_status_id.category == 'annual_leave' and a.name == a.holiday_status_id.name == 'Annual Leave':
                # a.total_allowed = a.employee_id.employee_annual_leave()
                a.total_allowed = a.employee_annual_leave(employee_id=a.employee_id.id, year=(a.holiday_status_id.validity_start.year + 1))
            if a.holiday_status_id.category == 'special_leave':
                a.total_allowed = a.with_context(employee_id=a.employee_id.id).holiday_status_id.max_leaves - a.leaves_taken_past

    @api.model
    def create_ah_allocation_for_current_period(self, at_year=None, at_months=[]):
        # automatically create AH leave allocation for current year
        # Using monthly schedule action
        # [X] Create leave type for current year
        # [X] Create leave allocation for these leave types
        # !NOTE: original hr.leave.allocation only allow (constraints) to create allocation between hr.leave.type validity start and stop
        # [ ] Modify for 40 hours working week (no working on SATs)

        today = fields.Date.context_today(self) or datetime.date.today()
        start_dt = self.env['hr.mixin'].get_start_dt(a_date=today)
        ah_duration = 2
        # in_at_year = not((today.month == 1 and today.day < 21) or (today.month == 12 and today.day > 20))
        # current_year = today.year if (in_at_year or today.month == 1) else today.year + 1
        if not at_year:
            at_year = start_dt.year + 1

        for month in at_months or range(1, 13):
            end_date = datetime.date(at_year, month, start_dt.day - 1)  # 20/01/yyyy ~ 20/12/yyyy
            start_date = end_date - relativedelta(months=1, day=start_dt.day)  # 21/12/yyyx ~ 21/11/yyyy
            domain = [('is_ah', '=', True), ('validity_start', '=', start_date), ('validity_stop', '=', end_date)]
            ah_leave_type = self.env['hr.leave.type'].with_context(active_test=False, no_filter_leave_type=True).search(domain)
            allocation_domain = [('holiday_status_id', '=', ah_leave_type.id), ('mode_company_id', '=', self.env.user.company_id.id or 1)]

            def _create_allocation(leave_type, holiday_type='company', duration=ah_duration):
                return self.env['hr.leave.allocation'].sudo().create({
                    'name': leave_type.name,
                    'holiday_status_id': leave_type.id,
                    'holiday_type': holiday_type,
                    'mode_company_id': self.env.user.company_id.id or 1,
                    'number_of_days': duration
                })

            if not ah_leave_type:
                # Create leave type
                ah_leave_type = self.env['hr.leave.type'].sudo().create({
                    'name': 'AH for {month}. {year}'.format(month=end_date.strftime('%b'), year=at_year),
                    'is_ah': True,
                    'allocation_type': 'fixed',  # as default
                    'exclude_public_holidays': True,  # as default
                    'validity_start': start_date,
                    'validity_stop': end_date,
                    'request_unit': 'day'
                })
            else:
                _logger.warning(_(f'===== AH leave type already created for {ah_leave_type.name}'))
            
            # Create AH leave allocations
            # List of employees having AH Allocation
            working_emp_ids = self.env['hr.employee'].search([('working', '=', True)])
            # Remove not-allowed AH staffs and 40-hour working week staffs
            ah_emp_ids = working_emp_ids.filtered(lambda e: not bool({'House Maid', 'Driver', 'Outsource'} & set(e.category_ids.mapped('name'))))
            # ah_emp_ids = ah_emp_ids.filtered(lambda e: bool(e.resource_calendar_id) and e.resource_calendar_id.name == 'KINDEN VIETNAM 48 Hours/Week')
            ah_emp_ids = ah_emp_ids.filtered(lambda e: not self.env['hr.attendance'].is_no_sat_working(employee_id=e, at_date=ah_leave_type.validity_start))
            created_ah_als = 0
            for e in ah_emp_ids:
                ah_al_domain = [('employee_id', '=', e.id), ('holiday_status_id', '=', ah_leave_type.id)]
                ah_al = self.env['hr.leave.allocation'].search(ah_al_domain)
                if not ah_al:
                    ah_al = self.env['hr.leave.allocation'].sudo().create({
                        'name': ah_leave_type.name,
                        'holiday_status_id': ah_leave_type.id,
                        'holiday_type': 'employee',
                        'employee_id': e.id,
                        # 'mode_company_id': self.env.user.company_id.id or 1,
                        'number_of_days': ah_duration
                    })
                    ah_al.sudo().action_approve()
                    created_ah_als = created_ah_als + 1
                else:
                    _logger.warning(_('===== AH Allocation {} was already created for {}'.format(ah_al.name, e.name)))
            
            _logger.warning(_('===== {} AH Allocations were created named {}'.format(created_ah_als, ah_leave_type.name)))

            # if not self.env['hr.leave.allocation'].search(allocation_domain):
            #     new_ah_allocation = _create_allocation(ah_leave_type)
            #     new_ah_allocation.sudo().action_approve()
                
            #     # Remove ah_al from that of not-allowed staffs (House Maid, Driver, Outsource)
            #     emp_ah_al_domain = [('holiday_status_id', '=', ah_leave_type.id), ('state', '=', 'validate'), ('holiday_type', '=', 'employee')]
            #     ah_al = self.env['hr.leave.allocation'].search(emp_ah_al_domain)
            #     not_allowed_ah_al = ah_al.filtered(lambda a: bool({'House Maid', 'Driver', 'Outsource'} & set(a.employee_id.category_ids.mapped('name'))))
            #     for a in not_allowed_ah_al:
            #         if a.state == 'validate':
            #             a.sudo().action_refuse()
            #             a.sudo().action_draft()
            #             warning_msg = f'===== Remove {a.name} for {a.employee_id.name}'
            #             a.sudo().unlink()
            #             _logger.warning(warning_msg)
                
            #     _logger.warning(_('===== {} allocations created named {}'.format(self.env['hr.leave.allocation'].search_count(emp_ah_al_domain), ah_leave_type.name)))
            # else:
            #     _logger.warning(_('===== {} {} AH Allocation already created'.format(start_date, end_date)))

    def _action_validate_create_childs(self):
        # override to skip not working employee
        childs = self.env['hr.leave.allocation']
        if self.state == 'validate' and self.holiday_type in ['category', 'department', 'company']:
            if self.holiday_type == 'category':
                employees = self.category_id.employee_ids
            elif self.holiday_type == 'department':
                employees = self.department_id.member_ids
            else:
                employees = self.env['hr.employee'].search([('company_id', '=', self.mode_company_id.id)])
            
            employees = employees.filtered('working')

            for employee in employees:
                childs += self.with_context(
                    mail_notify_force_send=False,
                    mail_activity_automation_skip=True
                ).create(self._prepare_holiday_values(employee))
            # TODO is it necessary to interleave the calls?
            childs.action_approve()
            if childs and self.holiday_status_id.validation_type == 'both':
                childs.action_validate()
        return childs

    def action_update_allocation_to_new_member(self):
        """
            Allow update leave allocation to new employees
            Make use of the method: _action_validate_create_childs
        """
        # TODO [X]: only hr_manager can do it
        is_hr_manager = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        if not is_hr_manager:
            raise ValidationError(_('You are NOT HR Manager!'))
        for a in self:
            if a.employee_id or a.state != 'validate':
                raise UserError(_('Only work on non-emloyee and [Approved] state!'))

            childs = self.env['hr.leave.allocation']
            if a.state == 'validate' and a.holiday_type in ['category', 'department', 'company']:
                if a.holiday_type == 'category':
                    employees = a.category_id.employee_ids
                elif a.holiday_type == 'department':
                    employees = a.department_id.member_ids
                else:
                    employees = a.env['hr.employee'].search([('company_id', '=', a.mode_company_id.id)])

                employees = employees - a.mapped('linked_request_ids').mapped('employee_id')
                for employee in employees.filtered(lambda e: a.employee_id != e):
                    # TODO [X]: Do not apply for BOD/GM
                    bod = self.env['hr.department'].search([('name', '=', 'B.O.D')], limit=1)
                    if employee.admin_dept_id == bod.id or bod.manager_id.id == employee.id:
                        continue
                    childs += self.with_context(
                        mail_notify_force_send=False,
                        mail_activity_automation_skip=True
                    ).create(a._prepare_holiday_values(employee))
                childs.action_approve()
                if childs and a.holiday_status_id.validation_type == 'both':
                    childs.action_validate()

    def compute_start_dt(self, a_date):
        """
            - Helper method: return starting date of an attendance year: 21/12/YYYY
        """
        if not a_date:
            a_date = fields.Date.context_today(self)
        start_date = self.env['hr.mixin'].at_start_day()

        if a_date.month == 12 and a_date.day >= start_date:
            start_dt = a_date + relativedelta(day=start_date)
        else:
            start_dt = a_date + relativedelta(years=-1, month=12, day=start_date)
        return start_dt

    def compute_annual_leaves(self, employee_ids=[], force_run=False):
        """
            - This helper method will be triggered by scheduled action every 21/12/YYYY, 00:00:01 and 21/06/YYYY, 00:00:01
            - to compute, modify, create, update, generate KDVN annual leave types: 
              Annual Leave, Last Year Leave, Special Leave, OT Compensation
            - and compute, modify, create, update, generate related leave allocations
            - REF: KDVN Leave policy

            - employee_ids: list of employee_id: default []
            - force_run: False
            - test_run: Using shell without commit
        """
        today = fields.Date.context_today(self)
        # start_dt = self.compute_start_dt(today)
        start_dt = self.env['hr.mixin'].get_start_dt(a_date=today)  # 21/12/yyyy
        end_dt = datetime.date(start_dt.year + 2, 6, start_dt.day - 1)  # 20/6/yyyy+2
        period_dt = datetime.date(start_dt.year + 1, 6, start_dt.day)  # 21/6/yyyy+1
        if not employee_ids:
            employees = self.env['hr.employee'].search([('active', '=', True), ('working', '=', True)])
        else:
            employees = self.env['hr.employee'].browse(employee_ids)
        LT = self.env['hr.leave.type']
        AL = self.env['hr.leave.allocation']

        # Handling Leave Types Domain
        # lt_domain = [('active', '=', True)]
        year_lt_domain = [('category', '=', 'annual_leave')]
        la_domain = [('holiday_type', '=', 'employee')]

        if today == start_dt or (force_run and today > start_dt and today < period_dt):  # 21/12/yyyy+1
            # Make new Annual Leave Type with validity of 21/12/yyyy > 20/6/yyyy+2
            # Annual Leave Type => Last Year Leave Type (validity no change)
                # Annual Leave Allocation => Last Year Leave Allocation
                # OT Compensation Allocation number_of_days add up to Last Year Leave Allocation
                # Make new Annual Leave Allocation based on fomular for number_of_days
                # OT Compensation Allocation holiday_status_id change to new Annual Leave Type with number_of_days = 0
            # Special Leave yyyy-1, yyyy-2, yyyy-3: NO changes
            new_lt = LT.search(year_lt_domain + [('validity_start', '=', start_dt)])
            if not new_lt:
                new_lt = LT.sudo(self.env.uid == 1).create({
                        'name': 'Annual Leave',
                        'allocation_type': 'fixed',  # as default
                        'exclude_public_holidays': True,  # as default
                        'validity_start': start_dt,
                        'validity_stop': end_dt,
                        'request_unit': 'day',
                        'category': 'annual_leave'
                    })
            else:
                _logger.warning(_('New Year Leave Type already existed!'))
            
            last_lt = LT.search(year_lt_domain + [('validity_start', '=', start_dt - relativedelta(years=1))])  # it actually Annual Leave type
            if last_lt:
                last_lt.name = 'Last Year Leave'
                related_allocations = AL.search(la_domain + [('holiday_status_id', '=', last_lt.id), ('name', 'in', ['Annual Leave', 'Last Year Leave'])])
                for a in related_allocations.filtered(lambda r: r.employee_id.working).sudo(self.env.uid == 1):  # Only allocations of working employees
                    a.name = 'Last Year Leave'
                    related_ot_allocation = AL.search(la_domain + [('employee_id', '=', a.employee_id.id), ('holiday_status_id', '=', last_lt.id), ('name', '=', 'OT Compensation')])
                    if related_ot_allocation:
                        a.number_of_days += related_ot_allocation.number_of_days
                        a.ot_last_update = related_ot_allocation.ot_last_update
                        related_ot_allocation.number_of_days = 0
                        related_ot_allocation.holiday_status_id = new_lt.id
                
                # Create Annual Leave (new year)
                for e in employees:
                    if not AL.search(la_domain + [('employee_id', '=', e.id), ('holiday_status_id', '=', new_lt.id), ('name', '=', 'Annual Leave')]):
                        new_la = AL.sudo(self.env.uid == 1).create({
                            'name': new_lt.name,
                            'holiday_status_id': new_lt.id,
                            'holiday_type': 'employee',
                            'employee_id': e.id,
                            'number_of_days': self.employee_annual_leave(e.id, year=(new_lt.validity_start.year + 1))
                        })
                        new_la.action_approve()

                # Create OT Compensation if needed
                for e in employees:
                    if not AL.search(la_domain + [('employee_id', '=', e.id), ('holiday_status_id', '=', new_lt.id), ('name', '=', 'OT Compensation')]):
                        new_ot = AL.sudo(self.env.uid == 1).create({
                            'name': 'OT Compensation', 
                            'holiday_status_id': new_lt.id,
                            'holiday_type': 'employee',
                            'employee_id': e.id,
                            'number_of_days': 0
                        })
                        new_ot.action_approve()
            else:
                _logger.warning('There is no leave type for current year')
            
            # if not LT.search(year_lt_domain + [('validity_start', '=', start_dt)]):
            #     try:
            #         new_lt = LT.sudo(self.env.uid == 1).create({
            #             'name': 'Annual Leave',
            #             'allocation_type': 'fixed',  # as default
            #             'exclude_public_holidays': True,  # as default
            #             'validity_start': start_dt,
            #             'validity_stop': end_dt,
            #             'request_unit': 'day',
            #             'category': 'annual_leave'
            #         })
            #     except Exception as e:
            #         _logger.error('There are some error as {}'.format(e))
            # else:
            #     raise UserError(_('The new year leave type already exists. Please ask IT for support'))

        if today == period_dt or (force_run and today > period_dt):  # 21/06/yyyy+1
            # Last Year Leave Type => Special Leave yyyy with validity from 21/06/yyyy+1 to 20/06/yyyy + 4
                # Last Year Leave Allocation => Special Leave yyyy-1
            # Delete oldest Special Leave yyyy-4 allocation
                # Delete/Unactive oldest Special Leave Type yyyy-3
            # Annual Leave no change

            last_lt = LT.search(year_lt_domain + [('validity_start', '=', start_dt - relativedelta(years=1))])
            if last_lt:
                related_special_allocations = AL.search(la_domain + [('holiday_status_id', '=', last_lt.id), ('name', '=', 'Last Year Leave'), ('employee_id', 'in', employees.mapped('id')), ('employee_id.working', '=', True)])
                related_special_allocations.sudo().write({'name': 'Special Leave {}'.format(start_dt.year)})

                # for a in related_special_allocations:
                #     a.sudo().name = 'Special Leave {}'.format(start_dt.year)

                # related_special_allocations.filtered(lambda r: r.employee_id.working).sudo().write({
                #     'name': last_lt.name  # Special Leave yyyy-1
                # })

                
                # !NOTE: no need to update like below because need to keep history of data. The allocation already invalid!
                # last_special_lt = LT.search([('active', '=', True), ('category', '=', 'special_leave'), ('validity_start', '=', period_dt - relativedelta(years=3))])  # 21/6/yyyy-3
                # if last_special_lt:
                #     related_special_allocations = AL.search(la_domain + [('holiday_status_id', '=', last_special_lt.id), ('name', '=', 'Special Leave {}'.format(period_dt.year - 4)), ('state', '=', 'validate')])
                #     batchs = [related_special_allocations[n:n+100] for n in range(0, len(related_special_allocations), 100)]
                #     for batch in batchs:
                #         for a in batch:
                #             a.sudo().action_refuse()
                #             a.action_draft()
                #         self.env.cr.commit()

                #     last_special_lt.sudo().active = False


                last_lt.sudo().update({
                    'name': 'Special Leave {}'.format(start_dt.year),  #yyyy-1
                    'validity_stop': period_dt + relativedelta(years=3, day=period_dt.day - 1),
                    'validity_start': period_dt,
                    'category': 'special_leave'
                })
            else:
                _logger.warning('There is no leave type for last year')

    def employee_annual_leave(self, employee_id, year=None):
        """
            - employee_id: [int]
            - year: [int] attendance year: Ex: 2022 (21/12/2021 ~ 20/12/2022)
            - TODO [X]: additional bonus 7 days for 15, 20, 25 and 30 years staff
        """
        employee = self.env['hr.employee'].browse(employee_id)
        today = fields.Date.context_today(self) if not year else datetime.date(year, 1, 1)
        start_dt = self.env['hr.mixin'].get_start_dt(a_date=today)  #21/12
        end_dt = start_dt + relativedelta(years=1)
        joining_date = employee.joining_date
        annual_leave = 0
        bonus_leave = 0
        if not joining_date:
            _logger.warning(_('===== Please update {}''s joining date').format(employee.display_name))
            return annual_leave
        
        if start_dt <= joining_date and end_dt > joining_date:  # Joining under 12 months
            annual_leave = round((end_dt - joining_date).days / 30 / 0.5) * 0.5  # Round to 0.5
        elif (start_dt > joining_date) and (start_dt - relativedelta(years=5) <= joining_date):  # Joining under 5 year
            annual_leave = 12
        elif (start_dt - relativedelta(years=5) > joining_date) and (start_dt - relativedelta(years=10) <= joining_date):  # Joining from 5 to under 10 years
            annual_leave = 14
        else:
            # New rule: Annual leave for over 25 year is 17 days
            # So Year 26 and 31 will have total of 17 + 9 and 17 + 10
            annual_leave = 16
            if start_dt - relativedelta(years=25) >= joining_date:  # 25 completed years of service (year 26 on)
                annual_leave = 17
            for index, duration in enumerate([15, 20, 25, 30]):  # 7, 8, 9 10 bonus day for year 16, 21, 26, 31
                if start_dt - relativedelta(years=duration) >= joining_date and start_dt - relativedelta(years=duration + 1) < joining_date:
                    bonus_leave = 7 + index
                    break
        res = annual_leave + bonus_leave
        return res

    def add_ot_compensation(self, employee_id, at_start_dt, add_duration=0, allow_past_update=False):
        """
            - Add OT compensation to the related allocation
            - Create if not exists
            - Need annual_lt
            - If OT belong to last year => add to last year leave (apply for OT in attendance month 12)
            - at_start_dt: start date of the at_month and at_year: at_month=5, at_year=2022 => 21/04/2022
            - allow_past_update: Only use when need to update OT compensation of a month that is older than ot_last_update value
        """
        employee = self.env['hr.employee'].browse(employee_id)
        annual_lt = self.env['hr.leave.type'].search([('name', '=', 'Annual Leave'), ('category', '=', 'annual_leave')])
        last_lt, add_to_last_year = False, False

        if not annual_lt:
            _logger.error(_(f'Do not have Annual Leave Type. Pleae create one!'))
            return False

        if annual_lt.validity_start > at_start_dt:
            last_lt = self.env['hr.leave.type'].search([('name', '=', 'Last Year Leave'), ('category', '=', 'annual_leave')])
            add_to_last_year = True

        ot_al = self.env['hr.leave.allocation'].search([('employee_id', '=', employee.id), ('name', '=', 'OT Compensation'), ('state', '=', 'validate')])

        if add_to_last_year:
            last_al = self.env['hr.leave.allocation'].search([('name', '=', 'Last Year Leave'), ('holiday_status_id', '=', last_lt.id), ('employee_id', '=', employee.id)])
            if last_lt and (not last_al.ot_last_update or (last_al.ot_last_update < at_start_dt)):
                last_al.sudo(self.env.uid == 1).number_of_days += add_duration
                last_al.sudo(self.env.uid == 1).ot_last_update = at_start_dt
            else:
                _logger.warning(_('Do not have Last Year Leave!'))
        else:
            if not ot_al:
                ot_al = self.sudo(self.env.uid == 1).create({
                            'name': 'OT Compensation',
                            'holiday_status_id': annual_lt.id,
                            'holiday_type': 'employee',
                            'employee_id': employee.id,
                            'number_of_days': add_duration,
                            'ot_last_update': at_start_dt
                        })
                ot_al.action_approve()
            else:
                if not ot_al.ot_last_update or (ot_al.ot_last_update < at_start_dt) or (ot_al.ot_last_update > at_start_dt and allow_past_update):
                    ot_al.sudo(self.env.uid == 1).with_context(al_message='add_ot_compensation').number_of_days += add_duration
                    ot_al.sudo(self.env.uid == 1).ot_last_update = at_start_dt if (not ot_al.ot_last_update or ot_al.ot_last_update < at_start_dt) else ot_al.ot_last_update

    @api.model
    def recompute_ot_compensation_by_year(self, employee_id, at_year):
        """
            - Recompute OT Compensation by yearly to compensate errors during each month of the at_year
            - Only run when the at_year already finished
        """
        today = fields.Date.context_today(self)
        staff = self.env['hr.employee'].search([]).browse(employee_id)
        res = {'staff_code': staff.code,
               'error': None, 'changes': []
               }
        # Only run when the at_year already finished
        if today.year - 1 == at_year:
            at_summaries = self.env['hr.attendance.summary'].search([('employee_id', '=', employee_id), ('at_year', '=', at_year)])
            total_ot_compensation = sum(at_summaries.mapped('exceed_ot_subtitude')) if at_summaries else 0
            last_year_leave = self.employee_annual_leave(employee_id, at_year)
            current_last_year_leave = self.search([('employee_id', '=', employee_id), ('holiday_status_id.name', '=', 'Last Year Leave'), ('holiday_status_id.category', '=', 'annual_leave'), ('holiday_status_id.valid', '=', True)])
            if current_last_year_leave and len(current_last_year_leave) == 1:
                current_allocation = current_last_year_leave.number_of_days
                new_allocation = last_year_leave + total_ot_compensation
                if current_allocation != new_allocation:
                    # Update new value to current_last_year_leave
                    current_last_year_leave.sudo().with_context(al_message='recompute_ot_compensation_by_year').number_of_days = last_year_leave + total_ot_compensation
                    current_last_year_leave.sudo().ot_last_update = datetime.date(at_year, 11, self.env['hr.mixin'].at_start_day())  # 21/11/xxxx = start of AT month 12
                    res['changes'].append({'current_allocation': current_allocation, 'new_allocation': new_allocation})
            else:
                res['error'] = 'NO or more than 01 allocation'
        else:
            res['error'] = 'Selected year is NOT last year'
        return res
    
    @api.model
    def prepare_initial_allocations(self, year=None, employee_ids=[], force_update=False):
        """
            - Running the first time to initial employee leaves allocation
            - Using leaves balance input in hr.employee
            - Assuming leave types already create !NOTE !IMPORTANCE
            - Create:
              + Annual Leave: using balance
              + Last Year Leave: using balance
              + OT compensation Leave:
              + Special 0, 1, 2: using balance
              + Create AH leave
            - TODO []: Do NOT create allocation if number_of_days = 0
            - force_update=True: will update number_of_days form hr.employee allocation related fields
            - TODO [X]: update balance must consider remaining leaves for correctioness
        """
        LT = self.env['hr.leave.type'].with_context(no_filter_leave_type=True).sudo(self.env.uid == 1)
        AL = self.env['hr.leave.allocation'].sudo(self.env.uid == 1)
        if not employee_ids:
            employees = self.env['hr.employee'].search([('active', '=', True), ('working', '=', True)])
        else:
            employees = self.env['hr.employee'].browse(employee_ids)

        if not year:
            year = self.env['hr.mixin'].get_start_dt(a_date=fields.Date.context_today(self)).year + 1

        lt_domain = [('active', '=', True)]
        annual_lt = LT.search(lt_domain + [('name', '=', 'Annual Leave'), ('category', '=', 'annual_leave')], limit=1)
        special_lt = LT.search(lt_domain + [('category', '=', 'special_leave')])
        last_year_lt = LT.search(lt_domain + [('name', '=', 'Last Year Leave'), ('category', '=', 'annual_leave')], limit=1)

        for employee in employees:
            if employee.need_action and not employee.joining_date:
                _logger.error('Need HR action for {}. REF: No joining date'.format(employee.display_name))
                continue

            al_domain = [('state', '=', 'validate'), ('employee_id', '=', employee.id)]
            annual_domain = al_domain + [('name', '=', 'Annual Leave')]
            last_year_domain = al_domain + [('name', '=', 'Last Year Leave')]
            ot_domain = al_domain + [('name', '=', 'OT Compensation')]
            special_domain = al_domain + [('holiday_status_id.category', '=', 'special_leave')]

            annual_al = AL.search(annual_domain)
            ot_al = AL.search(ot_domain)
            legal_annual_days = self.employee_annual_leave(employee.id, year=year)

            # TODO []: annual_days = legal_annual_days only when annual_al not existed
            # NOTE: leaves_bal = 0 or False is the same that cause mistake here
            # For ex.: case leaves_bal really remained 0 
            annual_days = employee.leaves_bal or (legal_annual_days if not annual_al else 0)
            ot_days = employee.ot_compensation_leave_bal or 0
            if annual_lt:
                # compute number_of_days so that it balance out with remaining leave
                # and do not greater than annual_leave (will be balanced when compute ot compensation)
                # balance_offset = annual_days + ot_days - (annual_lt.with_context(employee_id=employee.id).remaining_leaves - annual_al.number_of_days if annual_al else 0 - ot_al.number_of_days if ot_al else 0)
                # annual_days += balance_offset
                annual_days = annual_days - (annual_lt.with_context(employee_id=employee.id).remaining_leaves - (annual_al.number_of_days if annual_al else 0) - (ot_al.number_of_days if ot_al else 0))
                # if annual_days > legal_annual_days:
                #     annual_days = legal_annual_days
                #     # TODO []: offset the differnce to ot_days (is this happen?)
                
                if not annual_al:
                    annual_al = AL.create({
                        'name': annual_lt.name,
                        'holiday_status_id': annual_lt.id,
                        'holiday_type': 'employee',
                        'employee_id': employee.id,
                        'number_of_days': annual_days
                    })
                    annual_al.action_approve()
                elif annual_al and force_update:
                    annual_al.sudo(self.env.uid == 1).update({'number_of_days': annual_days})

                if not ot_al:
                    if ot_days:
                        ot_al = AL.create({
                            'name': 'OT Compensation',
                            'holiday_status_id': annual_lt.id,
                            'holiday_type': 'employee',
                            'employee_id': employee.id,
                            'number_of_days': ot_days
                        })
                        ot_al.action_approve()
                elif ot_al and force_update:
                    ot_al.update({'number_of_days': ot_days})
            
            last_year_al = AL.search(last_year_domain)
            number_of_days = employee.leaves_carry_forward_bal or 0
            if last_year_lt:
                number_of_days = number_of_days - (last_year_lt.with_context(employee_id=employee.id).remaining_leaves - last_year_al.number_of_days if last_year_al else 0)
                if not last_year_al:
                    last_year_al = AL.create({
                        # 'name': 'Annual Leave {}'.format(year - 1),
                        'name': 'Last Year Leave',
                        'holiday_status_id': last_year_lt.id,
                        'holiday_type': 'employee',
                        'employee_id': employee.id,
                        'number_of_days': number_of_days
                    })
                    last_year_al.action_approve()
                elif last_year_al and force_update:
                    last_year_al.update({'number_of_days': number_of_days})

            special_lt = special_lt.sorted(key=lambda t: t.name[-4:], reverse=True)
            for i, lt in enumerate(special_lt):
                special_al = AL.search(special_domain + [('name', '=', lt.name)])
                special_leave_key = 'special_leaves_{}'.format(i)
                number_of_days = (employee[special_leave_key] or 0) if special_leave_key in employee else 0
                number_of_days = number_of_days - (lt.with_context(employee_id=employee.id).remaining_leaves - special_al.number_of_days if special_al else 0)
                if not special_al:
                    if number_of_days:
                        special_al = AL.create({
                            'name': lt.name,
                            'holiday_status_id': lt.id,
                            'holiday_type': 'employee',
                            'employee_id': employee.id,
                            'number_of_days': number_of_days,
                        })
                        special_al.action_approve()
                elif special_al and force_update:
                    special_al.update({'number_of_days': number_of_days})
            
            ah_lt = LT.search(lt_domain + [('is_ah', '=', True), ('validity_stop', '>=', employee.joining_date)])
            for i, lt in enumerate(ah_lt):
                ah_al = AL.search(al_domain + [('holiday_status_id', '=', lt.id)])
                if not ah_al and not({'House Maid', 'Driver', 'Outsource'} & set(employee.category_ids.mapped('name'))):
                    ah_al = AL.create({
                        'name': lt.name,
                        'holiday_status_id': lt.id,
                        'holiday_type': 'employee',
                        'employee_id': employee.id,
                        'number_of_days': 2
                    })
                    ah_al.action_approve()

    @api.model
    def fix_leave_name(self):
        """
            - USE WITH CARE
        """
        la = self.env[self._name].search([('holiday_type', '=', 'employee'), ('holiday_status_id.is_ah', '=', False), ('holiday_status_id.is_special', '=', False), ('holiday_status_id.name', '=', 'Annual Leave')])
        count = 0
        for a in la:
            if a.name == 'Annual Leave 2022':
                a.name = 'Annual Leave'
                count += 1
            elif a.name == 'OT Compensation 2022':
                a.name = 'OT Compensation'
                count += 1
        print('===== {}/{}'.format(count, len(la)))

        la = self.env[self._name].search([('holiday_type', '=', 'employee'), ('holiday_status_id.is_ah', '=', False), ('holiday_status_id.is_special', '=', False), ('holiday_status_id.name', '=', 'Last Year Leave')])
        count = 0
        for a in la:
            if a.name == 'Annual Leave 2021':
                a.name = 'Last Year Leave'
                count += 1
            # elif a.name == 'OT Compensation 2022':
            #     a.name = 'OT Compensation'
                count += 1
        print('===== {}/{}'.format(count, len(la)))
    
    @api.model
    def fix_ot_compensation(self):
        # ONLY FOR DEV
        ot_la = self.env[self._name].search([('name', '=', 'OT Compensation 2021'), ('holiday_status_id.name', '=', 'Last Year Leave')])
        ot_count = 0
        for a in ot_la:
            last_year_allocation = self.env[self._name].search([('employee_id', '=', a.employee_id.id), ('name', '=', 'Last Year Leave')])
            last_year_allocation.sudo().number_of_days += a.number_of_days
            a.sudo().action_refuse()
            a.sudo().action_draft()
            a.unlink()
            ot_count += 1
        print('===== delete {} ot compensation'.format(ot_count))

    @api.model
    def fix_ot_compensation_2(self, employee_ids = []):
        # ONLYE FOR DEV
        if not employee_ids:
            employees = self.env['hr.employee'].search([('active', '=', True), ('working', '=', True)])
        else:
            employees = self.env['hr.employee'].browse(employee_ids)
        for e in employees:
            ot_al = self.env['hr.leave.allocation'].search([('employee_id', '=', e.id), ('name', '=', 'OT Compensation')])
            if len(ot_al) >= 2:
                ot_last_update = max(ot_al.filtered('ot_last_update').mapped('ot_last_update'))
                number_of_days = sum(ot_al.mapped('number_of_days'))
                keep_ot_al = ot_al.filtered(lambda a: a.ot_last_update == ot_last_update)
                if keep_ot_al:
                    keep_ot_al.sudo(self.env.uid == 1).number_of_days = number_of_days
                    keep_ot_al.sudo(self.env.uid == 1).action_approve()
                    for a in (ot_al - keep_ot_al).sudo(self.env.uid == 1):
                        a.action_refuse()
                        a.action_draft()
                        a.unlink()
            if ot_al.ot_last_update:
                last_al = self.env['hr.leave.allocation'].search([('employee_id', '=', e.id), ('name', '=', 'Last Year Leave')])
                if last_al:
                    last_al.sudo(self.env.uid == 1).ot_last_update = ot_al.ot_last_update
    
    @api.model
    def fix_ot_compensation_3(self, employee_ids = []):
        # ONLY FOR DEV
        if not employee_ids:
            employees = self.env['hr.employee'].search([('active', '=', True), ('working', '=', True)])
        else:
            employees = self.env['hr.employee'].browse(employee_ids)

        for e in employees:
            ot_al = self.env[self._name].search([('name', '=', 'OT Compensation'), ('employee_id', '=', e.id)])
            for a in ot_al:
                a.sudo().number_of_days = 0
                a.sudo().ot_last_update = False
            print(f'===== set 0 to ot compensation of {e.name}')
    
    @api.model
    def fix_wrong_compute_annual_leave(self, employee_ids=[]):
        # ONLY FOR DEV
        if not employee_ids:
            employees = self.env['hr.employee'].search([('active', '=', True), ('working', '=', True)])
        else:
            employees = self.env['hr.employee'].browse(employee_ids)

        for e in employees:
            annual_al = self.env[self._name].search([('name', '=', 'Annual Leave'), ('employee_id', '=', e.id)])
            if len(annual_al) == 1:
                old_number_of_days = annual_al.number_of_days
                new_number_of_days = self.employee_annual_leave(employee_id=e.id, year=annual_al.holiday_status_id.validity_start.year+1)
                if new_number_of_days != old_number_of_days:
                    annual_al.sudo().number_of_days = new_number_of_days
                    _logger.warning(f'Changed {annual_al.holiday_status_id.validity_start.year+1} Annual Leave of {e.name} | {e.joining_date} from {old_number_of_days} to {annual_al.number_of_days}')
                else:
                    _logger.warning(f'No changed {annual_al.holiday_status_id.validity_start.year+1} Annual Leave of {e.name} | {e.joining_date} ')
            else:
                _logger.error(f'Something wrong with Annual Leave of {e.name}')

    def _compute_related_leaves(self):
        for a in self:
            # []: Must show leaves that archive already
            leave_ids = self.env['hr.leave'].sudo().with_context(active_test=False).search([('employee_id', '=', a.employee_id.id), ('holiday_status_id', '=', a.holiday_status_id.id), ('state', '=', 'validate')])
            a.leave_ids = leave_ids

    @api.onchange('valid_from')
    def onchange_valid_from(self):
        for a in self:
            if a.valid_from:
                if a.holiday_status_id.is_special and a.holiday_status_id.category == 'other':
                    a.valid_to = a.valid_from + relativedelta(months=1)
            else:
                a.valid_to = False
    
    # ORM
    def _legacy_name_get(self):
        # override
        res = []
        for allocation in self:
            if allocation.holiday_type == 'company':
                target = allocation.employee_company_id.name   # Odoo 19: no mode_company_id
            elif allocation.holiday_type == 'department':
                target = allocation.department_id.name
            elif allocation.holiday_type == 'category':
                target = ''   # Odoo 19 allocation has no category target
            else:
                target = allocation.employee_id.sudo().name

            res.append(
                (allocation.id,
                 _("Allocation of %s : %.2f %s to %s") %
                 (allocation.name,
                  allocation.number_of_hours_display if allocation.type_request_unit == 'hour' else allocation.number_of_days,
                  _('hours') if allocation.type_request_unit == 'hour' else _('days'),
                  target))
            )
        return res
    

    @api.depends('name', 'holiday_type', 'employee_company_id', 'department_id', 'employee_id', 'number_of_days')
    def _compute_display_name(self):
        """Odoo 19 has no name_get(): display_name is computed. The Odoo 12 body is kept as _legacy_name_get (same strings)."""
        names = dict(self._legacy_name_get())
        for rec in self:
            rec.display_name = names.get(rec.id) or ''

    @api.onchange('employee_id')
    def _onchange_employee_update_holiday_type(self):
        # Return domain like this just to trigger name_get method
        return {
            'domain': {'holiday_status_id': [('id', '>', 0)]}
        }


    # ===== Constrains =====
    # override
    def _check_leave_type_validity(self):
        # Allow allocate back to past period
        for allocation in self:
            if allocation.holiday_status_id.validity_start and allocation.holiday_status_id.validity_stop:
                vstart = allocation.holiday_status_id.validity_start
                vstop = allocation.holiday_status_id.validity_stop
                today = self.env['hr.mixin'].today_vn()

                if vstart > today or vstop < today:
                    _logger.warning('===== KDVN', 'You can allocate {} only between {} and {}'.format(allocation.holiday_status_id.display_name,
                                                                                  allocation.holiday_status_id.validity_start, allocation.holiday_status_id.validity_stop))
    @api.constrains('holiday_status_id', 'valid_from', 'valid_to')
    def _check_valid_dates_for_special_leave(self):
        for al in self:
            if al.holiday_status_id.is_special and al.holiday_status_id.category == 'other':
                if not all([al.valid_from, al.valid_to]):
                    raise ValidationError(_(f'Must have valid_from and valid_to for special leave'))
                else:
                    if (al.valid_from + relativedelta(months=1)) < al.valid_to:
                        raise ValidationError(_(f'Only allow for one month {al.valid_from} ~ {al.valid_to}'))
                    overlap = self.search([('id', '!=', al.id), ('employee_id', '=', al.employee_id.id),
                                           ('holiday_status_id', '=', al.holiday_status_id.id), ('state', '!=', 'refuse'),
                                           ('valid_from', '<=', al.valid_to), ('valid_to', '>=', al.valid_from)], limit=1)
                    if al.employee_id and overlap:
                        raise ValidationError(_(f'{al.employee_id.name} already has a special leave valid {overlap.valid_from} ~ {overlap.valid_to}. Please extend that one or wait until it ends.'))

    @api.constrains('ot_last_update')
    def validate_edit_user(self):
        """
            - Only admin/hr_admin can change value of this field
        """
        user_is_hr_staff = self.env['hr.mixin'].groups().get('hr_staff', False)
        if not (user_is_hr_staff or self.env.uid == 1):
            raise ValidationError(_('Only HR Admin can change the value of this field! Please contact HR!'))

    @api.constrains('allow_to_use')
    def validate_allow_fields_to_use_in_special_leave(self):
        """
            - allow_to_use: apply for yearly special leave only
        """
        for a in self:
            if a.allow_to_use and not (not a.holiday_status_id.is_special and a.holiday_status_id.category == 'special_leave'):
                raise ValidationError(_('[Allow to use] field must used with Yearly Special Leave only!'))
            # if (a.valid_from or a.valid_to) and not (a.holiday_status_id.is_special and a.holiday_status_id.category == 'other'):
            #     raise ValidationError(_('[Valid From] and [Valid To] fields must only use with Special Leave only!'))

    # ======
    def report_leave_allocation_remain(self):
        """
            - Returing data for the report remaining leave allocation
            - Updated by current time
            - TODO [X]: Sorting
            - TODO [X]: Column names
            - TODO [X]: Number of column name not fix: may be 4, 5 or 6
        """
        res = []
        all_al_domain = [('state', '=', 'validate'), ('holiday_type', '=', 'employee'), ('employee_id.working', '=', True),
                         ('holiday_status_id.is_ah', '=', False), ('holiday_status_id.valid', '=', True), ('holiday_status_id.is_special', '=', False), 
                         ('holiday_status_id.category', 'not in', ['summer_vacation', 'sub_holiday', 'absence'])]
        # !NOTE: need sudo here to get correct allocation data
        all_al = self.env['hr.leave.allocation'].sudo().search(all_al_domain).sorted(key=lambda a: f'a{a.holiday_status_id.validity_start}' if a.holiday_status_id.category == 'special_leave' else f'b{a.holiday_status_id.validity_start}')
        # al_names = list(set(all_al.mapped(lambda a: a.name.capitalize())))  # get the list of allocation name
        # al_names = sorted(al_names, key=lambda e: f'0{e}' if e.find('Special') != -1 else f'1{e}' if e.find('Last') != -1 else f'2{e}')  # sort the list

        start_dt = self.env['hr.mixin'].get_start_dt(for_month=True) + relativedelta(months=1)
        at_year, at_month = self.env['hr.mixin'].get_at_year_month(start_dt)
        if at_month > 6:
            al_names = [f'Special leave {at_year-3}', f'Special leave {at_year-2}', f'Special leave {at_year-1}', 'Annual leave', 'Ot compensation']
        else:
            al_names = [f'Special leave {at_year-4}', f'Special leave {at_year-3}', f'Special leave {at_year-2}', 'Last year leave', 'Annual leave', 'Ot compensation']
        
        employee_ids = all_al.mapped('employee_id').sorted(key='code')
        for index, e in enumerate(employee_ids):
            e_al = {
                'index': index + 1,
                'staff_no': e.code,
                'staff_name': e.name,
            }
            # filtered out allocation does not have a name
            e_all_al = all_al.filtered(lambda al: al.name and al.employee_id == e)
            for name_index, name in enumerate(al_names):
                if name in e_all_al.mapped(lambda a: a.name.capitalize()):
                    if name.find('Ot') != -1:
                        e_al[name_index] = e_all_al.filtered(lambda a: a.name.capitalize() == name).number_of_days
                    else:
                        e_al[name_index] = e_all_al.filtered(lambda a: a.name.capitalize() == name).remaining_leaves
                else:
                    e_al[name_index] = 0
            res.append(e_al)
        return (al_names, res, datetime.datetime.now(vn_tz).strftime('%d/%h/%Y %H:%M'))

    # ===== CRUD =====
    def write(self, values):
        if 'employee_id' not in values and 'message_follower_ids' not in values:
            for r in self:
                if r.need_update_follower(r.employee_id.id):
                    r.message_unsubscribe(partner_ids=r.message_follower_ids.mapped('partner_id').ids)
                    r.message_subscribe(partner_ids=r.employee_id.user_id.partner_id.ids)
        return super().write(values)
    
    # ===== Activity methods =====
    # override
    def activity_update(self):
        # Disable sending notification email about Leave Allocation Activity
        return False
    
    # ===== Messaging methods =====
    def _track_subtype(self, init_values):
        """
            - Disable for state changing
            - Enable for number_of_days changing for keep track of change especialy for OT Compensation
        """
        # Tracking change of number_of_days but not for AH and only for working employee
        al_message = self.env.context.get('al_message', None)
        if 'number_of_days' in init_values and not self.holiday_status_id.is_ah and self.employee_id.working:
            if al_message == 'recompute_ot_compensation_by_year':
                return 'kdvn_hr_attendance.number_of_days_change_by_yearly_recompute'
            elif al_message == 'add_ot_compensation':
                return 'kdvn_hr_attendance.number_of_days_change_by_ot_compensation'
            else:
                return 'kdvn_hr_attendance.number_of_days_change'
        else:
            return False

        # Only use in case of KINDEN special leave
        if 'state' in init_values and self.state == 'validate':
            if self.holiday_status_id.is_special:
                return 'hr_holidays.mt_leave_allocation_approved'

        return False
        # return super()._track_subtype(init_values)

    def need_update_follower(self, employee_id):
        employee_id = self.env['hr.employee'].browse(employee_id)
        if employee_id.user_id:
            current_follower_ids = self.message_follower_ids.mapped('partner_id').ids
            update_follower_ids = employee_id.user_id.partner_id.ids
            return current_follower_ids != update_follower_ids
        else:
            return False

    @api.model
    def fix_allocation_follower_ids(self):
        # TODO: Take too long time
        al_ids = self.env['hr.leave.allocation'].search([])
        for a in al_ids:
            if a.need_update_follower(a.employee_id.id):
                current_follower_ids = a.message_follower_ids.mapped('partner_id').ids
                update_follower_ids = a.employee_id.user_id.partner_id.ids
                unsubscribe_ids = list(set(current_follower_ids) - set(update_follower_ids))
                a.message_unsubscribe(partner_ids=unsubscribe_ids)
                # a.message_subscribe(partner_ids=a.employee_id.user_id.partner_id.ids)



class KderpLeaveCoverReason(models.Model):
    _name = 'hr.leave.cover.reason'
    _description = 'KDERP Leave Cover Reasons'
    _order = 'sequence'

    name = fields.Char('Reason', required=True)
    code = fields.Char('Reason code', required=True)
    sequence = fields.Integer('Rank')
    category = fields.Selection(selection=[
        ('normal', 'Always'),
        ('special', 'For Special'),
        ('absence', 'For Absence')
    ], string='Category', default='normal')
    active = fields.Boolean(default=True)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        query = super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)
        employee_id = self.env.context.get('employee_id', False)
        if employee_id:
            special_lt_ids = self.env['hr.leave.type'].search([('valid', '=', True), ('category', '=', 'other'), ('is_special', '=', True)])
            if not special_lt_ids:
                return self.browse(self.browse(list(query)).filtered(lambda r: r.category != 'special').ids[:limit])._as_query()
        return query

