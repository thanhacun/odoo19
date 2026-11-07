# from calendar import day_abbr, leapdays
from collections import defaultdict
import copy as _copy
import time as _time
import datetime
import calendar
import math
import json
import re
from dateutil.relativedelta import relativedelta
# from dateutil import tz
from pytz import utc
import pytz
import random
import requests
import logging
from itertools import chain
from time import process_time
from calendar import month_abbr
import psycopg2
from datetime import timezone, timedelta


# from werkzeug.routing import parse_converter_args

from odoo import models, fields, api, tools, _
# from odoo import exceptions
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_round
from odoo.osv import expression
# from odoo.tools.profiler import profile

from .rounding import roundPartial

vn_tz = pytz.timezone(' '.join(pytz.country_timezones('vn')))

# vn_tz = tz.gettz('Asia/Ho_Chi_Minh')
# utc = tz.gettz('UTC')
utc_diff = 7

_logger = logging.getLogger(__name__)


def summary_key(employee_id, at_year, at_month):
    """Id of hr.attendance.summary (a SQL view) and of hr.attendance.summary_id: employee_id * 10000 + months since Jan 2000.
    Same formula as the SQL in the views, the index and the migration. (Until 12.0.1.0.2 the id was employee*1000000 + year*100 + month,
    which overflows an integer from employee id 2147.)"""
    return int(employee_id) * 10000 + (int(at_year) - 2000) * 12 + int(at_month)


def summary_key_decode(key):
    employee_id, idx = divmod(int(key), 10000)
    return employee_id, 2000 + (idx - 1) // 12, (idx - 1) % 12 + 1



class KderpHrAttendance(models.Model):
    _name = 'hr.attendance'
    _inherit = ['kderp.base.state.model', 'mail.thread', 'hr.attendance', 'kderp.base.model', 'hr.mixin']
    _description = 'KDERP HR Attendance'
    _order = 'code'

    # name is required by default in kderp.base.state.model
    name = fields.Text(required=False, string="Working time reason")
    code = fields.Char(size=16, readonly=True)
    # active = fields.Boolean(default=True)
    # override: check_in not required, no need default value
    check_in = fields.Datetime(required=False, default=False, readonly=True)
    check_out = fields.Datetime(readonly=True)
    # override: store deparment_id value for groupby function
    department_id = fields.Many2one(related="employee_id.admin_dept_id", store=True)
    admin_manager_id = fields.Many2one(related="employee_id.admin_manager_id", store=True, string="SM")
    admin_gm_id = fields.Many2one(related="employee_id.admin_gm_id", store=True, string="GM")
    area_id = fields.Many2one(related="department_id.area_id", store=True, string="Area")

    # check_in, check_out
    at_date = fields.Date(compute='_compute_at_date', store=True, readonly=True, index=True)
    at_day = fields.Selection(list(zip(calendar.day_abbr, calendar.day_name)), store=True, compute='_compute_at_date', readonly=True)
    at_day_str = fields.Char('Weekdays', compute='_compute_at_date', readonly=True)
    check_in_manual = fields.Datetime()
    check_out_manual = fields.Datetime()
    check_in_location_id = fields.Many2one('hr.attendance.location', compute='_compute_in_out_location', store=True, context={'active_test': False})
    check_out_location_id = fields.Many2one('hr.attendance.location', compute='_compute_in_out_location', store=True, context={'active_test': False})
    compute_in = fields.Datetime(compute='compute_compute_in_out', store=True)
    compute_out = fields.Datetime(compute='compute_compute_in_out', store=True)

    # OT and AT status
    wd_ot = fields.Float('Weekday OT')
    wd_st = fields.Float('Weekday ST')
    hd_ot = fields.Float('Holiday OT')
    hd_st = fields.Float('Holiday ST')
    ph_ot = fields.Float('Pub. Holiday OT')
    ph_st = fields.Float('Pub. Holiday ST')
    ot_am = fields.Float('Day OT')
    ot_pm = fields.Float('Night OT')
    ot_wd = fields.Float('Weekday OT')
    ot_hd = fields.Float('Holiday OT')
    ot_total = fields.Float('OT Total')
    ot_wd_remain = fields.Float('Remain WD', compute='_compute_ot_allow', store=True, readonly=True, aggregator="min")
    ot_hd_remain = fields.Float('Remain HD', compute='_compute_ot_allow', store=True, readonly=True, aggregator="min")
    ot_wd_ratio = fields.Float('Ratio WD', compute='_compute_ot_allow', store=True, readonly=True)
    ot_hd_ratio = fields.Float('Ratio HD', compute='_compute_ot_allow', store=True, readonly=True)
    wd_block_no = fields.Integer('Week Block', compute='_compute_ot_allow', store=True, readonly=True)
    weekly_wd_remain = fields.Float('Remain Weekly', compute='_compute_ot_allow', store=True, readonly=True, aggregator="avg")
    weekly_wd_ratio = fields.Float('Week Ratio', compute='_compute_ot_allow', store=True, readonly=True, aggregator="avg")
    # avg_section_ot = fields.Float('Avg. Section OT', compute='_compute_avg_ot', readonly=True, aggregator='min')
    # avg_area_ot = fields.Float('Avg. Area OT', compute='_compute_avg_ot', readonly=True, aggregator='min')

    late_in = fields.Boolean('Late in', compute='_compute_in_out_status', store=True)
    early_out = fields.Boolean('Early out', compute='_compute_in_out_status', store=True)
    is_holiday = fields.Boolean(compute='_compute_is_holiday', store=True)
    is_public_holiday = fields.Boolean(compute='_compute_is_holiday', store=True)
    is_other_holiday = fields.Boolean(compute='_compute_is_holiday', store=True)
    ot_apply = fields.Boolean(compute='_compute_ot_apply')
    show_ot = fields.Boolean(compute='_compute_ot_apply')
    e_ot_am = fields.Float('Est. Day OT')  # update by write, create method in attendance_request model
    e_ot_pm = fields.Float('Est. Night OT')  # update by write, create method in attendance_request model
    allow_late_ot = fields.Boolean(default=False)  # set by HR Admin allowing late OT request register
    ot_warning = fields.Text('OT Warning', compute='_compute_ot_warning', store=True, default=False)
    
    # work/absence status
    absence = fields.Selection([
        ('absence', 'Absence'),
        ('absence_am', 'AM absence'),
        ('absence_pm', 'PM Absence')
    ], default=False, readonly=True, compute='_compute_in_out_status', store=True)
    work_on_holiday = fields.Selection([
        ('work', 'Work'),
        ('work_am', 'AM work'),
        ('work_pm', 'PM work'),
    ], default=False, readonly=True, compute='_compute_in_out_status', store=True)
    ah = fields.Selection([
        ('ah', 'AH'),
        ('ah_am', 'AM AH'),
        ('ah_pm', 'PM AH')], string="Appointed Holiday", compute='_compute_ah_status', default=False)

    man2_approve = fields.Boolean('Need GM approve', default=False)

    # ====== REQUESTS ======
    at_request_ids = fields.One2many('hr.attendance.request', 'at_id', context={'active_test': False})
    request_description = fields.Text('Request marks', compute='_compute_request_description', store=True)
    raw_request_description = fields.Text('Raw Request marks', compute='_compute_request_description', store=True)
    request_leave = fields.Selection([
        ('full_day', 'Full day'),
        ('half_day', 'Half day')])
    convert_leave = fields.Selection([
        ('full_day', 'Full day'),
        ('half_day', 'Half day')])

    can_request_leave = fields.Boolean(compute='_compute_can_request_leave')
    can_convert_leave = fields.Boolean(compute='_compute_can_request_leave')
    can_request_ot = fields.Boolean(compute='_compute_can_request_buttons')
    can_request_wt = fields.Boolean(compute='_compute_can_request_buttons')

    # ===== OTHER ======
    leave_cover_ids = fields.Many2many('hr.leave.cover', string='Leave Covers', compute='_compute_leave_cover_ids', store=True, context={'active_test': False})
    # sub_leave_ids = fields.Many2many('hr.leave', string='Sub Leaves', compute='_compute_leave_cover_ids', store=True)
    leave_ids = fields.Many2many('hr.leave', string='Leaves', compute='_compute_leave_cover_ids', store=True, context={'active_test': False})
    related_leaves_count = fields.Integer(compute='_compute_leave_cover_ids', store=True)
    at_rule_ids = fields.Many2many('hr.attendance.rule', string='Attendance Rules', compute='_compute_rule_ids')

    status_ids = fields.Many2many(
        'kderp.base.code', string='Attendance Marks', ondelete='restrict',
        domain=lambda self: [("model_name", "=", self._name), ("type_code", "=", "at_status")]
    )

    status_codes = fields.Char('AT marks', compute='_compute_status_codes', size=32, store=True)

    show_leaves = fields.Boolean(related='employee_id.show_leaves')
    leaves_count = fields.Float(related='employee_id.leaves_count')
    ah_leaves_count = fields.Float(compute='_compute_ah_leaves_count')

    current_absence_date = fields.Text(compute='_compute_current_absence_date', default='[]')
    aval_substitute_date = fields.Text(compute='_compute_aval_substitute_date')

    start_date = fields.Date(compute='_compute_start_end_date', store=True, readonly=True)
    end_date = fields.Date(compute='_compute_start_end_date', store=True, readonly=True)
    at_month = fields.Integer(compute='_compute_start_end_date', store=True, readonly=True)
    at_year = fields.Integer(compute='_compute_start_end_date', store=True, readonly=True)
    on_current_month_at = fields.Boolean(compute='_compute_on_current_month_at', search='_search_on_current_month_at')

    worked_count = fields.Float(compute='_compute_worked_count', default=0, store=True)
    absence_count = fields.Float(compute='_compute_absence_count', default=0, store=True)
    refuse_comment = fields.Text(compute='_compute_refuse_comment', readonly=True)
    at_rules = fields.Html(compute='_compute_at_rules')

    data_enough = fields.Boolean(compute='_compute_data_enough')
    states_sync = fields.Boolean(compute='_compute_request_description', store=True)
    # single_mode = fields.Boolean(compute='_compute_single_mode', help='Whether the user is staff or admin/manager?')
    at_raw_id = fields.Many2one('hr.attendance.raw', compute='_compute_at_raw')

    # ! NOTE: index=True here is NOT working
    # ! NOTE: Have to use manual SQL commands to create indexs:
    # CREATE INDEX idx_hr_attendance_users_user ON hr_attendance_res_users_rel (res_users_id);
    # CREATE INDEX idx_hr_attendance_users_attendance ON hr_attendance_res_users_rel (hr_attendance_id);
    view_user_ids = fields.Many2many('res.users', string="View users")  # data will update in CRUD methods

    # ===== SUMMARY =====
    summary_id = fields.Many2one('hr.attendance.summary', compute='_compute_summary_id', store=True, default=False, index=True)
    at_date_str = fields.Char(compute='_compute_display_summary_fields')
    at_day_dsp = fields.Char(compute='_compute_display_summary_fields')

    # ===== States =====
    # https://www.odoo.com/id_ID/forum/help-1/8-show-a-state-depending-on-a-field-89160
    # Showing different states based on other fields values
    state_gm = fields.Selection(related='state')
    state_no_gm = fields.Selection(related='state')

    # ===== METHODS =====
    # @api.model
    # @api.depends('employee_id')
    # def compute_dept(self):
    #     all_ats = self.env['hr.attendance'].search([])
    #     for at in all_ats:
    #         at.department_id = at.employee_id.admin_dept_id.id

    def _read_group_employee_id(self, resources, domain):
        """Core filters the employees of an expanded group by `attendance_manager_id` for everyone outside "Attendance user".
        That field is readable only by the Officer group, so our section managers got an access error when a list is grouped
        by employee (the web client sets read_group_expand). Our record rules already limit the records: keep only the
        employees found in them."""
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_officer'):
            return resources
        return super()._read_group_employee_id(resources, domain)

    def _legacy_name_get(self):
        result = []
        for at in self:
            if at.compute_in and at.compute_out:
                display_name = _("%(empl_name)s on %(at_day)s %(at_date)s from %(check_in)s to %(check_out)s") % {
                    'empl_name': at.employee_id.name,
                    'at_day': at.at_day,
                    'at_date': at.at_date.strftime('%d/%m/%Y'),
                    'check_in': datetime.datetime.strftime(at.compute_in.astimezone(vn_tz), '%H:%M'),
                    'check_out': datetime.datetime.strftime(at.compute_out.astimezone(vn_tz), '%H:%M'),
                }
            elif at.compute_in:
                display_name = _("%(empl_name)s on %(at_day)s %(at_date)s from %(check_in)s") % {
                    'empl_name': at.employee_id.name,
                    'at_day': at.at_day,
                    'at_date': at.at_date.strftime('%d/%m/%Y'),
                    'check_in': datetime.datetime.strftime(at.compute_in.astimezone(vn_tz), '%H:%M')
                }
            else:
                display_name = _("%(empl_name)s on %(at_day)s %(at_date)s") % {
                    'empl_name': at.employee_id.name,
                    'at_day': at.at_day,
                    'at_date': at.at_date.strftime('%d/%m/%Y')
                }

            result.append((at.id, display_name))
        return result


    def _compute_color(self):
        """Odoo 19 core colours a record from check_in; our attendance days (absence, leave, no check) often have neither
        check_in nor check_out and core raises "'<' not supported between bool and datetime". Those days get colour 0."""
        no_check = self.filtered(lambda a: not a.check_in and not a.check_out)
        super(KderpHrAttendance, self - no_check)._compute_color()
        for attendance in no_check:
            attendance.color = 0

    @api.depends('employee_id', 'compute_in', 'compute_out', 'at_date')
    def _compute_display_name(self):
        """Odoo 19 has no name_get(): display_name is computed. The Odoo 12 body is kept as _legacy_name_get (same strings)."""
        names = dict(self._legacy_name_get())
        for rec in self:
            rec.display_name = names.get(rec.id) or ''

    # Customize restrictions
    # @api.multi
    # def read(self, fields=None, load='_classic_read'):
    #     if not self.env.user.has_group('base.group_system'):  # skip for admins
    #         if self.env.uid not in self.mapped('view_user_ids.ids'):
    #             raise AccessError("You are not allowed to access some records.")

    #     return super().read(fields, load)

    # @api.model
    # def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
    #     if not self.env.user.has_group('base.group_system'):
    #         domain = expression.AND([domain or [], [('view_user_ids', 'in', [self.env.user.id])]])
    #     return super().search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order)


    # @api.model
    # def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
    #     res = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)

    #     print('=====', view_type, self.env.context, self.env.context.get('active_id'))
    #     if view_type == 'form':
    #         params = self.env.context.get('params', {})
    #         active_id = params.get('id')
    #         if active_id:
    #             rec = self.browse(active_id)
    #             if self.env.user.id not in rec.view_user_ids.ids:
    #                 raise AccessError("You are not allowed to access this record.")
    #     return res
    
    @api.depends('code')
    def _compute_at_date(self):
        for at in self:
            if at.code:
                at.at_date = datetime.datetime.strptime(at.code[3:9], '%y%m%d').date()
            if at.at_date:
                at.at_day = calendar.day_abbr[at.at_date.weekday()]
                at.at_day_str = at.at_date.strftime('%a %d/%m/%Y')
            else:
                at.at_day = False  # Odoo 19: every field must be assigned
                at.at_day_str = False

    @api.depends('employee_id', 'at_month', 'at_year')
    def _compute_summary_id(self):
        for at in self:
            # summary_domain = [('employee_id', '=', at.employee_id.id), ('at_year', '=', at.at_year), ('at_month', '=', at.at_month)]
            # summary = self.env['hr.attendance.summary'].search(summary_domain, limit=1)
            # at.summary_id = summary.id if summary else False
            at.summary_id = summary_key(at.employee_id.id, at.at_year, at.at_month)
    
    # Use only for initlize database
    def _compute_summary_id_init_backup(self):
        total = 0
        for s in self.env['hr.attendance.summary'].search([]):
            ats = self.sudo().with_context(active_test=False).search([('employee_id', '=', s.employee_id.id), ('at_year', '=', s.at_year), ('at_month', '=', s.at_month)])
            ats.update({'summary_id': s.id})
            total += len(ats)
        _logger.warning('Total at records updated {}'.format(total))

    def _compute_summary_id_init(self):
        # REF: https://itecnote.com/tecnote/sql-get-count-of-records-affected-by-insert-or-update-in-postgresql/
        sql_str = """
            WITH ROWS AS (
                UPDATE hr_attendance
	            SET summary_id = (employee_id::bigint * 10000 + (at_year - 2000) * 12 + at_month)::int
                RETURNING 1
            )
            SELECT COUNT(*) FROM ROWS
        """
        try:
            self.env.cr.execute(sql_str)
            _logger.warning('Total at records updated {}'.format(self.env.cr.fetchall()[0][0]))
        except Exception as e:
            _logger.error('Error happen {}'.format(e))

    def _compute_display_summary_fields(self):
        for at in self:
            at_date_str = at.at_date.strftime('%d/%m')
            at_day_dsp = at.at_day[:3]

            at.update({
                'at_date_str': at_date_str,
                'at_day_dsp': at_day_dsp
            })

    def _compute_at_raw(self):
        for at in self:
            at_raw = self.with_context(active_test=False).env['hr.attendance.raw'].sudo().search([('at_code', '=', at.code)])
            at.at_raw_id = at_raw.id if at_raw else False

    def _compute_ot_total(self):
        for at in self:
            at.ot_total = False if (not at.ot_am and not at.ot_pm) else ((at.ot_am or 0) + (at.ot_pm or 0))

    # ===== STATES =====
    def _groups(self):
        res = {'at_staff': False, 'hr_staff': False, 'hr_manager': False, 'section_admin': False, 'section_manager': False, 'director': False}
        for at in self:
            user_groups = self.env.user.all_group_ids
            res['at_staff'] = at.employee_id.user_id == self.env.user
            res['hr_staff'] = self.env.ref('hr_attendance.group_hr_attendance_user') in user_groups
            res['section_manager'] = self.env.ref('kdvn_hr_attendance.group_hr_attendance_section_manager') in user_groups
            res['hr_manager'] = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        return res

    def _compute_related_states(self):
        """
            - Compute wt_requests state
            - Compute ot_request state
            - Compute leave_cover state
            - Compute self state
            - TODO [X]: special case: AH in draft state in SAT having wt/ot requests => follow state of wt/ot
        """
        for at in self:
            states = ['draft', 'waiting_fman', 'waiting_fhr', 'waiting_fman2', 'done', 'refuse']
            r_states = at.at_request_ids.mapped('state')
            
            # Not counting draft ah cover on SAT
            if at.leave_cover_ids and at.at_day == 'Sat' and len(at.leave_ids) == 1 and at.leave_ids.holiday_status_id.is_ah and at.leave_cover_ids.state == 'draft':
                l_states = []
            else:
                l_states = at.leave_cover_ids.mapped('state')
            all_states = list(set(r_states + l_states))

            if 'refuse' not in all_states and len(all_states) > 0:
                indexs = list(map(lambda s: states.index(s), all_states))
                new_state = states[min(indexs)]
                at.state_id = at.state_id.search([('model_id.model', '=', 'hr.attendance'), ('code', '=', new_state)], limit=1).id
            elif 'refuse' in all_states and at.state != 'refuse':
                at.state_id = at.state_id.search([('model_id.model', '=', 'hr.attendance'), ('code', '=', 'refuse')], limit=1).id
            elif len(all_states) == 0 and (at.state == 'refuse' or at.state != 'done'):
                # !Note: reset to draft: check carefully
                at.state_id = at.state_id.search([('model_id.model', '=', 'hr.attendance'), ('code', '=', 'draft')], limit=1).id
            else:
                pass

    def _compute_data_enough(self):
        """
            - Determind an attendance recored is enough data or not
            - => No need waiting for any further action => Validate
        """
        # Leave full day and leave state >= waiting_fhr
        # Enough check_in, check_out data (or check_in_manual, check_out_manual) and no OT request
        # All records that more than 2 days in the past
        today = fields.Date.context_today(self)
        # TODO [X]: should use at policy
        not_check_period = self.env.user.company_id.at_policy()['delay_duration'] if self.env.user.company_id else 2
        for at in self:
            in_out_enough = False
            no_more_ot_request = False
            no_more_wt_request = False
            no_more_leave_request = False
            status_enough = False
            over_duration = False
            # TODO []: 1/2 cases
            # TODO [X]: add one more day for at in Saturday
            if (today - at.at_date).days >= ((not_check_period + 1) if at.at_day == 'Sat' else not_check_period):
                if not (not at.status_ids or (len(at.status_ids) == 1 and at.status_ids.code.startswith('1/2'))):
                    status_enough = True

                if all([at.compute_in, at.compute_out]) and not at.absence:
                    in_out_enough = True
                if {'L', 'H', 'PH', 'SH', 'OH', 'AH'} & set(at.status_ids.mapped('code')):
                    # do not have check_in, check_out
                    if not at.compute_in and not at.compute_out:
                        in_out_enough = True
                if {'1/2 L', '1/2 AH'} & set(at.status_ids.mapped('code')):
                    if '1/2 O' in set(at.status_ids.mapped('code')):
                        in_out_enough = True

                # do not have OT request
                ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
                if not ot_request:
                    no_more_ot_request = True
                else:
                    if ot_request.state == 'done':
                    # if all(at.at_request_ids.filtered(lambda r: r.request_type == 'over_time').mapped(lambda r1: r1.state == 'done')):
                        no_more_ot_request = True

                wt_request = at.at_request_ids.filtered(lambda r: r.request_type == 'working_time')
                # do not have WT request
                if not wt_request:
                    no_more_wt_request = True
                else:
                    if all(wt_request.mapped(lambda r: r.state == 'done')):
                    # if all(at.at_request_ids.filtered(lambda r: r.request_type == 'working_time').mapped(lambda r1: r1.state == 'done')):
                        no_more_wt_request = True

                # do not have any Leave request
                if not at.leave_cover_ids:
                    no_more_leave_request = True
                else:
                    if all(at.leave_cover_ids.mapped(lambda c: c.state == 'done')):
                        no_more_leave_request = True

                if at.state not in ['waiting_fman', 'waiting_fhr', 'waiting_fman2']:
                    over_duration = True
            # _logger.warning('{}, {}, {}, {}, {}, {}'.format(over_duration, status_enough, in_out_enough, no_more_ot_request, no_more_wt_request, no_more_leave_request))
            at.data_enough = (over_duration and status_enough) or (status_enough and in_out_enough and no_more_ot_request and no_more_wt_request and no_more_leave_request)

    # @api.multi
    # @api.depends()
    # def _compute_single_mode(self):
    #     for at in self:
    #         at_groups = at.groups()
    #         is_at_staff = at_groups['at_staff']
    #         is_admin_or_manager = any([at_groups['hr_staff'], at_groups['hr_manager'], at_groups['section_admin'], at_groups['section_manager'], at_groups['director']])
    #         at.single_mode = is_at_staff and not is_admin_or_manager

    # override
    def button_next_state(self):
        for at in self:
            if at.state_id.code == 'draft':
                at.action_submit()
            elif at.state_id.code == 'waiting_fman':
                at.action_approve()
            elif at.state_id.code == 'waiting_fhr':
                at.action_validate()
            elif at.state_id.code == 'waiting_fman2':
                at.action_approve_man2()
            else:
                return True

    # override
    def button_previous_state(self):
        for at in self:
            at.state_id = self.env.ref('kdvn_hr_attendance.state_refuse')
        return True

    # ===== ACTIONS =====
    def action_submit(self):
        # if any([at.state_id.code != 'draft' for at in self]):
        #     raise UserError(_('Only attendances in [Draft] state can submit!'))
        for at in self:
            if at.state == 'draft':
                if at.at_request_ids or at.leave_cover_ids:
                    at.at_request_ids.filtered(lambda r: r.state == at.state).action_submit()
                    at.leave_cover_ids.filtered(lambda r: r.state == at.state).action_submit()
                # if not at.at_request_ids:
                    # at._compute_related_states()
                # at.update({'state_id': self.env.ref('kdvn_hr_attendance.state_waiting_fman')})

    def action_approve(self):
        # if any([at.state_id.code != 'waiting_fman' for at in self]):
        #     raise ValidationError(_('Only attendances in [Waiting for Manager] state can approve!'))
        # TODO []: allow past managers to approve - a little difficult for leave requests
        for at in self:
            can_approve_users = at.sudo().department_id.manager_id
            other_mans = self.env['hr.employee']
            if at.approve_manager_id:
                can_approve_users |= at.sudo().approve_manager_id
            if at.view_user_ids:
                other_mans = at.sudo().view_user_ids.filtered(lambda u: u.has_group('kdvn_hr_attendance.group_hr_attendance_section_manager')).mapped('employee_id')
                if other_mans and not at.sudo().department_id.manager_id in other_mans:
                    can_approve_users |= other_mans
            user_can_approve = self.env.uid in can_approve_users.mapped('user_id.id')
            # user_can_approve = at.sudo().department_id.manager_id.user_id.id == self.env.uid or at.sudo().approve_manager_id.user_id.id == self.env.uid
            if not (user_can_approve or self.env.uid in [1, 2] or at.groups()['hr_staff']):
                if len(self) > 1:
                    _logger.error(_('Only {} can approve!'.format(', '.join(can_approve_users.mapped('name')))))
                    continue
                else:
                    raise UserError(_('Only {} can approve!'.format(', '.join(can_approve_users.mapped('name')))))
            if at.state == 'waiting_fman' and (user_can_approve or self.env.uid in [1, 2] or at.groups()['hr_staff']):
                if at.at_request_ids or at.leave_cover_ids:
                    if other_mans and self.env.uid in other_mans.mapped('user_id.id'):
                        at.at_request_ids.filtered(lambda r: r.state == 'waiting_fman').action_approve()
                        at.leave_cover_ids.filtered(lambda r: r.state == 'waiting_fman').action_approve()
                        ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
                    else:
                        at.at_request_ids.filtered(lambda r: r.state == 'waiting_fman').action_approve()
                        at.leave_cover_ids.filtered(lambda r: r.state == 'waiting_fman').action_approve()
                        ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
                    if ot_request:
                        at._compute_ot_request()
                # if not at.at_request_ids:
                    # at._compute_related_states()
                # at.update({'state_id': self.env.ref('kdvn_hr_attendance.state_waiting_fhr')})

    def action_validate(self):
        for at in self:
            if at.at_request_ids or at.leave_cover_ids:
                if at.state != 'waiting_fhr':
                    _logger.warning(_('Only attendances in [HR Validate] state can be validated! REF.: {}').format(at.code))
                    # raise UserError(_('Only attendances in [Waiting for HR] state can validate! REF.: {}').format(at.code))
                at.at_request_ids.filtered(lambda r: r.state == 'waiting_fhr').action_validate()
                at.leave_cover_ids.filtered(lambda r: r.state == 'waiting_fhr').action_validate()

    def action_approve_man2(self):
        # if any([at.state_id.code != 'waiting_fman2' for at in self]):
        #     raise UserError(_('Only attendances in [Waiting for Director] state can approve!'))
        
        for at in self:
            if at.at_request_ids or at.leave_cover_ids:
                at.at_request_ids.filtered(lambda r: r.state == at.state).action_approve_man2()
                at.leave_cover_ids.filtered(lambda r: r.state == at.state).action_approve_man2()
            # if not at.at_request_ids:
                # at._compute_related_states()
            # at.update({'state_id': self.env.ref('kdvn_hr_attendance.state_done')})

    # @api.multi
    # def action_refuse_backup(self):
    #     if any([at.state_id.code in ('draft') for at in self]):
    #         raise UserError(_('Attendances should NOT in [Draft] state to be refused!'))
    #     # [X] TODO: popup a dialog for comment/reason
    #     self.ensure_one()

    #     refuse = self.env['hr.attendance.refuse'].search([('at_id', '=', self.id)], limit=1)
    #     action = {
    #         "type": "ir.actions.act_window",
    #         "name": "Open refuse comment",
    #         "res_model": "hr.attendance.refuse",
    #         "views": [(False, "form")],
    #         "view_mode": "list,form",
    #         "domain": [],
    #         "res_id": refuse.id if refuse else self.env['hr.attendance.refuse'].create({'at_id': self.id}).id,
    #         "target": "new"
    #     }

    #     return action

    def action_revise(self):
        for at in self:
            super(__class__, at).action_revise()
            if at.state_id.code == 'draft':
                # [X] TODO: consider using action_revise in hr.attendance.request model
                if at.at_request_ids or at.leave_cover_ids:
                    at.at_request_ids.action_revise()
                    at.leave_cover_ids.action_revise()

    def action_need_director(self):
        if any([at.state_id.code != 'waiting_fhr' for at in self]):
            raise UserError(_("Only attendances in the state [HR validate] can ask for director approve!"))
        for at in self:
            at.man2_approve = True
            at.at_request_ids.filtered(lambda r: r.state == at.state).action_need_director()
            at.leave_cover_ids.filtered(lambda r: r.state == at.state).action_need_director()
            # at.action_validate()

    def action_ot_request(self):
        action = {
            "type": "ir.actions.act_window",
            "name": "OT Request",
            "res_model": "hr.attendance.wizard",
            "views": [(False, "form")],
            "view_mode": "list,form",
            "context": {'default_request_mode': 'ot'},
            "target": "new"
        }
        return action

    def action_wt_request(self):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": "WT Request",
            "res_model": "hr.attendance.wizard",
            "views": [(False, "form")],
            "view_mode": "list,form",
            "context": {'default_request_mode': 'wt'},
            "target": "new"
        }
        return action
    
    def action_leave_cover_request(self):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": "Leave Cover Request",
            "res_model": "hr.leave.cover",
            "views": [(False, "form")],
            "view_mode": "list,form",
            # "context": {'default_request_mode': 'wt'},
            "target": "new"
        }
        return action

    def action_leave_request(self):
        self.ensure_one()
        default_reason_id = self.env.ref('kdvn_hr_attendance.reason_private').id
        if self.at_day == 'Sat':
            LeaveType = self.env['hr.leave.type'].with_context(employee_id=self.employee_id.id, default_date_from=self.at_date)
            lt = LeaveType.search([('valid', '=', True)])
            for t in lt:
                if t.is_ah and t.remaining_leaves > 0:
                    default_reason_id = self.env.ref('kdvn_hr_attendance.reason_ah').id
                    
        action_context = {
            'default_reason_id': default_reason_id,
            'at_id': self.id,
            'default_employee_id': self.employee_id.id
        }
        # if self.absence == 'absence_am':
        #     action_context['default_request_date_from_pm'] = True
        # elif self.absence == 'absence_pm':
        #     action_context['default_request_date_to_am'] = True

        action = {
            "type": "ir.actions.act_window",
            "name": "Leave Request",
            "res_model": "hr.leave.cover",
            "views": [(False, "form")],
            "view_mode": "list,form",
            "target": "new",
            "context": action_context,
            "res_id": self.leave_cover_ids.mapped('id')[0] if self.leave_cover_ids else False
        }
        return action

    def action_allow_late_ot(self):
        for a in self:
            a.allow_late_ot = True

    def auto_done(self):
        # ats = self.env['hr.attendance'].search([('state', 'not in', ['done', 'refuse'])])
        for at in self:
            if at.state not in ['done', 'refuse'] and at.data_enough:
                at.with_context(do_not_run_at_status=True).update({'state_id': self.env.ref('kdvn_hr_attendance.state_done').id})

        # ats.with_context(do_not_run_at_status=True).filtered('data_enough').update({'state_id': self.env.ref('kdvn_hr_attendance.state_done').id})

    # ! NOTE: for fixing past auto_done errors, will not be used in production mode
    @api.model
    def auto_done_fixed(self):
        ats = self.env['hr.attendance'].search([('state', 'in', ['done'])])
        for at in ats:
            at._compute_related_states()

    @api.model
    def auto_archive(self, at_id=None):
        """
            - Model method to auto archive last months records
            - TODO [X]: keep 12 months
        """
        # months_to_keep = 12
        if at_id:
            at_ids = self.env['hr.attendance'].browse([at_id])
        today = fields.Date.context_today(self)
        start_date = self.get_start_dt(a_date=today, for_month=True)
        # last_month_start_date = start_date - relativedelta(months=1)
        date_to_archive = start_date - relativedelta(years=1, months=-1)
        domain = [('state', '=', 'done'),('at_date', '<', date_to_archive)]
        at_ids = self.env['hr.attendance'].with_context(active_test=False).search(domain)
        request_ids = at_ids.mapped('at_request_ids').filtered(lambda r: r.state == 'done')
        leave_cover_ids = at_ids.mapped('leave_cover_ids').filtered(lambda c: c.state == 'done')
        refuse_ids = self.env['hr.attendance.refuse'].search(['|', ('related_request_id', 'in', request_ids.mapped('id')), ('related_leave_cover_id', 'in', leave_cover_ids.mapped('id'))])

        at_ids.with_context(do_not_run_at_status=True).filtered('active').write({'active': False})
        # TODO []: archive WT/OT requests
        request_ids.with_context(do_not_run_at_status=True).filtered('active').write({'active': False})
        # TODO []: archive Leave cover
        leave_cover_ids.with_context(do_not_run_at_status=True).filtered('active').write({'active': False})
        # TODO []: archive Refuse
        refuse_ids.with_context(do_not_run_at_status=True).filtered('active').write({'active': False})

    def toggle_archive(self):
        """ Toggle active value of records """
        for at in self:
            at.active = not at.active

    def update_view_users(self):
        for at in self:
            view_employee_ids = [at.employee_id.parent_id, at.employee_id.admin_manager_id, at.employee_id.gm_id, at.employee_id.admin_gm_id]
            user_ids = [e.user_id.id for e in view_employee_ids if e.user_id]
            at.view_user_ids = [(6, False, user_ids)]
            # Update View Users for hr.attendance.request and hr.leave.cover
            for r in at.at_request_ids:
                r.view_user_ids = [(6, False, user_ids)]
            for c in at.leave_cover_ids:
                c.view_user_ids = [(6, False, user_ids)]

    # ===== CRUD =====
    @api.model_create_multi
    def create(self, vals_list):
        """Odoo 19 passes a list of dicts; the Odoo 12 body below handles one dict at a time."""
        records = self.browse()
        for vals in vals_list:
            records |= self._legacy_create(vals)
        return records

    def _legacy_create(self, values):
        new_at_ids = super(KderpHrAttendance, self.with_context(mail_create_nolog=True)).create(values)
        for at in new_at_ids:
            at = at.sudo()  # need sudo to access other employee information
            at._compute_ot_allow(only_wd_block_no=True)
            # at._compute_ot_warning()

            # Create view_user_ids
            # user_ids = []
            users = [at.employee_id.parent_id, at.employee_id.admin_manager_id, at.employee_id.gm_id, at.employee_id.admin_gm_id]
            user_ids = [e.user_id.id for e in users if e.user_id]  # check user existed
            # for e in [at.employee_id.parent_id, at.employee_id.admin_manager_id, at.employee_id.gm_id, at.employee_id.admin_gm_id]:  # check user existed
            #     if e.user_id:
            #         user_ids.append(e.user_id.id)
            at.view_user_ids = [(6, False, user_ids)]

            if any([at.check_in, at.check_out, at.check_in_manual, at.check_out_manual]):
                at._compute_at_status()  # keep at last command as _compute_at_status having return
        return new_at_ids

    def write(self, values):
        result = super().write(values)
        # NOTE: in compute_at_status method there are 2 calling to _compute_ot_request method
        # so if run_compute_at_status is set to True => no need set recompute_ot to True anymore => other wise duplicate running
        # it is also True for the case of change in status_ids because method compute_at_status will make change to status_ids
        # => no need to set the variable recompute_ot

        run_compute_at_status = False
        # recompute_ot = False

        # when absence field change, need to update at status
        if {'check_in', 'check_out', 'check_in_manual', 'check_out_manual', 'absence'} & set(values.keys()):
            run_compute_at_status = True
            # recompute_ot = True
        if 'state_id' in values:
            new_state = self.state_id.search([('model_id.model', '=', self._name), ('id', '=', values.get('state_id'))])
            if new_state.code == 'refuse':
                # Send noti email to employee
                _logger.warning(_('Send notification email to {}'.format(self.employee_id.name)))
                self.sudo()._send_noti_refuse_email(at_ids=[self.id], force_send=True)
            # Log the change to chatter
            # self.message_post(body=f'**state** changed to **{[self.state_id.name]}** by **{self.write_uid.name}**')

            # NOTE: handle by schedule action
            # if new_state.code == 'done' and not self.states_sync:
            #     # Send states unsync noti email
            #     _logger.warning(_('Send states unsync email to {}'.format(self.employee_id.name)))
            #     self.sudo()._send_noti_states_unsync_email(at_ids=[self.id])
            run_compute_at_status = True
        if 'allow_late_ot' in values:
            self.message_post(body=f'**Allow Late OT** changed to **{[self.allow_late_ot]}** by **{self.write_uid.name}**')

        # if 'approve_manager_id' in values:
        #     apporve_manager_id = values.get('approve_manager_id')
        # elif self.approve_manager_id:
        #     apporve_manager_id = self.approve_manager_id.id
        # else:
        #     apporve_manager_id = False
        # if self.at_request_ids:
        #     self.at_request_ids.write({'approve_manager_id': apporve_manager_id})
        # if self.leave_cover_ids:
        #     self.leave_cover_ids.write({'approve_manager_id': apporve_manager_id})

        if run_compute_at_status and not self.env.context.get('do_not_run_at_status', False):
            self._compute_at_status()
        
        # Recompute OT when status change
        # Sometime when user made OT request too early => need to recompute ot when check_in_out info changes
        # if ('status_ids' in values) or recompute_ot:
        #     for at in self:
        #         if at.at_request_ids.filtered(lambda r: r.request_type == 'over_time'):
        #             if at.leave_ids and at.leave_ids.filtered(lambda h: h.holiday_status_id.is_ah):
        #                 at._compute_ah_status()
        #             at._compute_ot_request()
        return result

    # @api.multi
    # def unlink(self):
    #     return super().unlink()

    # ===== Other methods =====
    @api.depends("at_date", "employee_id")
    def _compute_is_holiday(self):
        for at in self:
            holiday = at._is_holiday(at.at_date)

            at.update({
                "is_holiday": holiday == "H",
                "is_public_holiday": holiday == "SH",
                "is_other_holiday": holiday == "OH",
            })

    @api.model
    def _update_is_holiday(self, a_date=None):
        """
            - Helper method to update is_holiday, is_public_holiday, is_other_holiday
            when there is a change in public holiday model
            - !NOTE: use with care
        """
        start_dt = None
        if not a_date or type(a_date) is not datetime.date:
            start_dt = self.get_start_dt(a_date=fields.Date.context_today(self))
        start_dt = self.get_start_dt(a_date=a_date)
        at_ids = self.env['hr.attendance'].search([('at_date', '>=', start_dt), ('at_date', '<', start_dt + relativedelta(years=1))])
        at_ids._compute_is_holiday()

    @api.depends('employee_id', 'status_ids')
    def _compute_ot_apply(self):
        for at in self:
            at_rules = at._at_rules()
            no_ot = set(['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8'])
            ot_wd_allow = at_rules.get('wd_allowed_ot', 0)
            # ot_hd_allow = at_rules.get('hd_allowed_ot', 0)

            # no_ot_allowance = at._at_rules().get('wd_allowed_ot', 0) == 0
            # ot_apply, show_ot = False, False
            ot_apply = show_ot = not (ot_wd_allow == 0 or no_ot & set(at.employee_id.category_ids.mapped('name')))
            # if ot_wd_allow == 0 or no_ot & set(at.employee_id.category_ids.mapped('name')):
            #     ot_apply = False
            #     show_ot = False
            # else:
            #     ot_apply = True
            #     show_ot = True
            at.update({'ot_apply': ot_apply, 'show_ot': show_ot})

    def batch_compute_ot_allow(self, batch_employees, start_date, all_ats, at_year, at_month, wd_of_month, wd_block, only_wd_block_no):
        """
            Helper method to compute ot_allows for a batch_employees for a specific at_year, at_month
        """
        # Improve by AI recommendation
        # [ ] Pre-prepare ats and self_ats to reduce computing in the loop
        # [ ] Pre-prepare previous_xxx to reduce computing in the loop
        # [ ] Avoid using continue in the loop for better code practice (easy to read and troubleshooting)
        ats_group = {e.code: all_ats.filtered(lambda a: a.employee_id.id == e.id) for e in batch_employees}
        self_ats_group = {e.code: self.filtered(lambda a: a.employee_id.id == e.id and a.at_year == at_year and a.at_month == at_month) for e in batch_employees}
        for e in batch_employees:
            at_rules = self._at_rules(employee_id=e, at_date=start_date)
            month_wd_allow = at_rules.get('wd_allowed_ot', 0)
            month_hd_allow = at_rules.get('hd_allowed_ot', 0)
            
            # NOTE: self_ats <= ats
            # ats is used for compute remains
            # self_ats is used for looping
            
            # ats = all_ats.filtered(lambda a: a.employee_id.id == e.id)
            # self_ats = self.filtered(lambda a: a.employee_id.id == e.id and a.at_year == at_year and a.at_month == at_month)

            ats = ats_group.get(e.code, [])
            self_ats = self_ats_group.get(e.code, [])

            # plain-python copy of the fields the "previous" lookups need (same order as ats): the filtered() calls below
            # were quadratic ORM reads. A row is refreshed from the record after each update, so rounding stays identical.
            # read() only these columns first: the first plain field access would otherwise prefetch every column of every record
            if len(ats):
                ats.read(['at_date', 'wd_block_no', 'ot_wd_remain', 'ot_hd_remain', 'weekly_wd_remain', 'ot_wd', 'ot_hd', 'status_ids',
                          'ot_wd_ratio', 'ot_hd_ratio', 'weekly_wd_ratio'])
            rows = [[a.at_date, a.wd_block_no, a.ot_wd_remain, a.ot_hd_remain, a.weekly_wd_remain] for a in ats]
            # previous_data = {}
            for idx, at in enumerate(ats):
                at_status = at.status_ids.mapped('name')

                staff_wd_of_month = sorted(wd_of_month + ([at.at_date] if (at.at_date not in wd_of_month and 'O' in at_status) else []))
                
                wd_block_no = min(4, (staff_wd_of_month.index(at.at_date) // wd_block + 1)) if at.at_date in staff_wd_of_month else 0

                ot_allow = { 'wd_block_no': wd_block_no }

                if any([month_wd_allow, month_hd_allow]):
                    # previous_wd_at = ats.filtered(lambda r: r.at_date < at.at_date and r.wd_block_no != 0)
                    # previous_hd_at = ats.filtered(lambda r: r.at_date < at.at_date and r.wd_block_no == 0)
                    # previous_weekly_wd_at = ats.filtered(lambda r: r.wd_block_no != 0 and r.at_date < at.at_date and r.wd_block_no == wd_block_no)

                    cur_date = at.at_date
                    previous_wd_at = [r for r in rows if r[0] < cur_date and r[1] != 0]
                    previous_hd_at = [r for r in rows if r[0] < cur_date and r[1] == 0]
                    previous_weekly_wd_at = [r for r in rows if r[1] != 0 and r[0] < cur_date and r[1] == wd_block_no]
                    
                    # Calculate remains
                    ot_wd_remain = (previous_wd_at[-1][2] if previous_wd_at else month_wd_allow) - at.ot_wd
                    ot_hd_remain = (previous_hd_at[-1][3] if previous_hd_at else month_hd_allow) - at.ot_hd
                    weekly_wd_remain = (previous_weekly_wd_at[-1][4] if previous_weekly_wd_at else month_wd_allow / 4) - at.ot_wd

                    ot_allow.update({'ot_wd_remain': ot_wd_remain, 'ot_hd_remain': ot_hd_remain,'weekly_wd_remain': weekly_wd_remain})

                    if only_wd_block_no:
                        self._update_ot_allow_changed(at, ot_allow)
                        rows[idx] = [at.at_date, at.wd_block_no, at.ot_wd_remain, at.ot_hd_remain, at.weekly_wd_remain]
                        continue  # !NOTE escape the loop here
                    
                    # Calculate ratios
                    # ot_wd_ratio = 0 if month_wd_allow == 0 else at.ot_wd / month_wd_allow
                    # ot_hd_ratio = 0 if month_hd_allow == 0 else at.ot_hd / month_hd_allow
                    # weekly_wd_ratio = 0 if month_wd_allow == 0 else at.ot_wd / (month_wd_allow / 4)

                    ot_allow.update({
                        'ot_wd_ratio': 0 if month_wd_allow == 0 else at.ot_wd / month_wd_allow, 
                        'ot_hd_ratio': 0 if month_hd_allow == 0 else at.ot_hd / month_hd_allow,
                        'weekly_wd_ratio': 0 if month_wd_allow == 0 else at.ot_wd / (month_wd_allow / 4)
                    })

                    # Store for future iterations
                    # previous_data = {'previous_wd_at': previous_wd_at, 'previous_hd_at': previous_hd_at, 'previous_weekly_wd_at': previous_weekly_wd_at}
                else:
                    if only_wd_block_no:
                        self._update_ot_allow_changed(at, ot_allow)
                        rows[idx] = [at.at_date, at.wd_block_no, at.ot_wd_remain, at.ot_hd_remain, at.weekly_wd_remain]
                        continue  # !NOTE escape the loop here
                
                self._update_ot_allow_changed(at, ot_allow)
                rows[idx] = [at.at_date, at.wd_block_no, at.ot_wd_remain, at.ot_hd_remain, at.weekly_wd_remain]


                
    
    @api.model
    def _update_ot_allow_changed(self, at, ot_allow):
        """at.update(ot_allow) but only the fields whose value really changes: most recomputes change nothing and each write
        runs the whole hr.attendance write() chain."""
        changed = {k: v for k, v in ot_allow.items() if at[k] != v}
        if changed:
            at.update(changed)

    @api.depends('ot_total')
    def _compute_ot_allow(self, only_wd_block_no=False, delay=False):
        # return False
        # TODO: use queue_job when number of records is big enough

        # Configurable parameters
        BATCH_SIZE = 60
        END_DATE_DAY = self.env['hr.mixin'].at_start_day()  # company policy
        WD_BLOCK_SIZE = 6
        AVG_DAYS_OF_MONTH = 30

        # Determine if delayed processing is needed
        if len(self) > (BATCH_SIZE * AVG_DAYS_OF_MONTH):
            delay = True

        # Pre-compute unique year-month combination and employee records
        at_year_month = list(set(self.mapped(lambda a: (a.at_year, a.at_month))))
        employees = list(set(self.mapped('employee_id')))

        for (at_year, at_month) in at_year_month:
            end_date = datetime.date(at_year, at_month, END_DATE_DAY)
            start_date = end_date - relativedelta(months=1)

            # Pre-compute dates and holidays
            days_of_month = [start_date + relativedelta(days=d) for d in range((end_date - start_date).days)]
            hd_of_month = {d for d in days_of_month if self.env['hr.attendance']._is_holiday(d)}
            sats_of_month = {d for d in days_of_month if (d not in hd_of_month and d.weekday() == 5)}
            ah_sats = sorted(list(sats_of_month))[-2:]
            hd_ot_of_month = hd_of_month.union(ah_sats)
            wd_of_month = [d for d in days_of_month if d not in hd_ot_of_month]
            
            # !NOTE: for future
            # weekly_wd_of_month = [wd_of_month[j:j+6] for j in range(0, (len(wd_of_month)//6)*6, 6)]  # block of 6-weekday, skip the last block less than 6-element
            # weekly_wd_of_month = [wd_of_month[j:j + wd_block] for j in range(0, len(wd_of_month), wd_block)]  # block of 6-weekday, last block may not has enough 6-element
            
            # Fetch attendance records for the month
            # only the affected employees (the batches below keep these employees anyway): not the whole company month
            all_ats = self.search([('at_year', '=', at_year), ('at_month', '=', at_month), ('employee_id', 'in', [e.id for e in employees])])
            batches = [employees[i:i + BATCH_SIZE] for i in range(0, len(employees), BATCH_SIZE)]
            for batch_employees in batches:
                batch_ats = all_ats.filtered(lambda a: a.employee_id in batch_employees)

                if delay and self.delayable:
                    # _logger.warning(_(f'This task will take a long time: using queue_job technology to handle! Please check the result later!'))
                    _logger.warning(f"Processing {len(batch_employees)} employees asynchronously.")
                    delayable = self.delayable()
                    delayable.set(description=_(f"Update {len(batch_employees)} employees ot_allows for {at_month}-{at_year} (UID: {self.env.uid})"))
                    delayable.batch_compute_ot_allow(
                        batch_employees=batch_employees, 
                        start_date=start_date, 
                        all_ats=batch_ats, 
                        at_year=at_year, 
                        at_month=at_month, 
                        wd_of_month=wd_of_month, 
                        wd_block=WD_BLOCK_SIZE, 
                        only_wd_block_no=only_wd_block_no)
                    delayable.delay()
                else:
                    self.batch_compute_ot_allow(
                        batch_employees=batch_employees, 
                        start_date=start_date, 
                        all_ats=batch_ats, 
                        at_year=at_year, 
                        at_month=at_month, 
                        wd_of_month=wd_of_month, 
                        wd_block=WD_BLOCK_SIZE, 
                        only_wd_block_no=only_wd_block_no)

                
    
    # @api.depends('ot_total')
    def _compute_avg_ot(self):
        return False
        at_year_month = list(set(self.mapped(lambda a: (a.at_year, a.at_month))))
        sections = list(set(self.mapped('department_id')))
        for (at_year, at_month) in at_year_month:
            section_sql = """
                SELECT at_year, at_month, att.department_id,
                    SUM(CASE WHEN section_ot_staff = 0 THEN 0 ELSE (ot_total/section_ot_staff) END) avg_section_ot
                FROM hr_attendance att
                LEFT JOIN hr_department dept ON att.department_id=dept.id
                WHERE att.at_year={at_year} AND att.at_month={at_month}
                GROUP BY att.at_year, att.at_month, att.department_id
            """.format(at_year=at_year, at_month=at_month)

            area_sql = """
                SELECT at_year, at_month, att.area_id,
		            SUM(CASE WHEN area_ot_staff = 0 THEN 0 ELSE (ot_total/area_ot_staff) END) avg_area_ot
                FROM hr_attendance att
                LEFT JOIN hr_department dept ON att.area_id=dept.id
                WHERE att.at_year={at_year} AND att.at_month={at_month}
                GROUP BY att.at_year, att.at_month, att.area_id
            """.format(at_year=at_year, at_month=at_month)
            self.env.cr.execute(section_sql)
            section_res = {e[2]:e[3] for e in self.env.cr.fetchall()}
            self.env.cr.execute(area_sql)
            area_res = {e[2]:e[3] for e in self.env.cr.fetchall()}
            for s in sections:
                self.filtered(lambda a: a.at_year == at_year and a.at_month == at_month and a.department_id.id == s.id).update({
                    'avg_section_ot': section_res[s.id] if s.id in section_res else None,
                    'avg_area_ot': area_res[s.area_id.id] if (s.area_id and s.area_id.id in area_res) else None
                    })
            
    
    def _compute_ot_daily_over(self):
        return False
    
    def _compute_ot_weekly_over(self):
        return False
    
    @api.depends('ot_total', 'weekly_wd_remain', 'ot_wd_remain', 'ot_hd_remain')
    def _compute_ot_warning(self):
        # return False
        wd_daily_limit = 4
        hd_daily_limit = 12
        for a in self:
            # ot_over = {'daily_over_wd': False, 'daily_over_hd': False, 'weekly_over_wd': False, 'monthly_over_wd': False, 'monthly_over_hd': False}
            # ot_over['daily_over_wd'] = a.ot_wd
            # ot_over['daily_over_hd'] = a.ot_hd
            # ot_over['monthly_over_wd'] = a.ot_wd_remain
            # ot_over['monthly_over_hd'] = a.ot_hd_remain
            # ot_over['weekly_over_wd'] = a.weekly_wd_remain
            ot_warning = []
            if a.wd_block_no != 0 and (a.ot_wd > wd_daily_limit or (a.at_request_ids.filtered(lambda r: r.request_type == 'over_time' and r.state in ['draft', 'waiting_fman']) and (a.e_ot_am + a.e_ot_pm) > wd_daily_limit)):
                ot_warning.append(_(f'Over weekday limit of {wd_daily_limit} hours.'))
            if a.wd_block_no == 0 and (a.ot_hd > hd_daily_limit or (a.at_request_ids.filtered(lambda r: r.request_type == 'over_time' and r.state in ['draft', 'waiting_fman']) and (a.e_ot_am + a.e_ot_pm) > hd_daily_limit)):
                ot_warning.append(_(f'Over holiday limit of {hd_daily_limit} hours.'))
            if a.weekly_wd_remain < 0:
                ot_warning.append(_(f'Over weekly limit.'))
            if a.ot_wd_remain < 0:
                ot_warning.append(_(f'Over monthly weekday limit.'))
            if a.ot_hd_remain < 0:
                ot_warning.append(_(f'Over monthly holiday limit.'))

            a.ot_warning = '\n'.join(ot_warning) if ot_warning else False

    @api.depends('at_date')
    def _compute_leave_cover_ids(self):
        """
            - Compute related leave, leave_cover ids
            - Should be called when some change in leave cover (create method or constraint methods)
        """
        # company = self.env.user.company_id
        # if not company:
        #     raise UserError(_('{} should belong to a company! REF: {}'.format(self.env.user.name, '_compute_leave_cover_ids')))
        # at_policy = company.at_policy()
        for at in self:
            if at.at_date:
                # ! Consider showing draft, refuse leave as well for better interaction
                leave_cover_domain = [('employee_id', '=', at.employee_id.id), ('dt_from', '<=', at.at_date), ('dt_to', '>=', at.at_date)]
                leave_domain = [('employee_id', '=', at.employee_id.id), ('request_date_from', '<=', at.at_date), ('request_date_to', '>=', at.at_date), ('leave_cover_id', '!=', False)]
                leave_cover_ids = self.env['hr.leave.cover'].with_context(show_ah=True, active_test=False).search(leave_cover_domain)
                leave_ids = self.env['hr.leave'].with_context(active_test=False).search(leave_domain)

                at.leave_cover_ids = [(6, False, leave_cover_ids.mapped('id'))] if leave_cover_ids else False
                at.related_leaves_count = len(leave_cover_ids.mapped('leave_request_ids'))
                at.leave_ids = [(6, False, leave_ids.mapped('id'))] if leave_ids else False

    @api.depends('at_request_ids', 'at_request_ids.state', 'at_request_ids.name', 'request_leave', 'convert_leave', 'related_leaves_count', 'leave_cover_ids', 'leave_cover_ids.state', 'state_id')
    def _compute_request_description(self):
        # [X] Based on at state and leave state for better language
        # import odoo_repl; odoo_repl.set_trace()
        states = ['draft', 'waiting_fman', 'waiting_fhr', 'waiting_fman2', 'done', 'refuse']
        for at in self:
            # Making sure states sync
            # at._compute_related_states()
            states_sync = True
            at_state_index = states.index(at.state) if at.state else 0
            if any([at.at_request_ids, at.can_request_leave, at.can_convert_leave, at.related_leaves_count]):
                raw_description = []
                description = []

                for r in at.at_request_ids:
                    # request_des = '- ' + r.name_get()[0][1]
                    request_des = r.display_name
                    if r.state != at.state and states.index(r.state) < at_state_index and at.state != 'refuse':
                        raw_description.append(request_des)
                        description.append('<span class="text-danger font-weight-bold">' + request_des + '</span>')
                        states_sync = False
                    else:
                        raw_description.append(request_des)
                        description.append('<span>' + request_des + '</span>')
                        states_sync = True

                if at.leave_ids:
                    for l in at.leave_ids:
                        leave_des = []
                        at_date_leaves = l.by_at_date_leave(at.at_date)
                        is_holiday = bool(at._is_holiday(at.at_date))
                        if not is_holiday:
                            for n, e in enumerate(at_date_leaves):
                                if e['holiday_type'].is_ah:
                                    if e['substitute_for_date']:
                                        leave_des.append('AH{}: sub. for {}'.format(' (AM)' if e['period'] == 'AM' else ' (PM)' if e['period'] == 'PM' else '', e['substitute_for_date'].strftime('%d/%m/%Y') if e['substitute_for_date'] else ''))
                                    else:
                                        if l.state in ('draft', 'confirm') or l.write_uid == l.employee_id.user_id :  # show description for better undertanding
                                            leave_des.append('- AH{}'.format(' (AM)' if e['period'] == 'AM' else ' (PM)' if e['period'] == 'PM' else ''))
                                elif e['holiday_type'].category == 'sub_holiday':
                                    leave_des.append('H{}: sub. for {}{}'.format(' (AM)' if e['period'] == 'AM' else ' (PM)' if e['period'] == 'PM' else '', e['substitute_for_date'].strftime('%d/%m/%Y') if e['substitute_for_date'] else '', (' of ' + str(l.number_of_days) + ' days') if l.number_of_days > 1 else ''))
                                else:
                                    # leave_des.append('- {}{}'.format(l.holiday_status_id.name, ' (AM)' if e['period'] == 'AM' else ' (PM)' if e['period'] == 'PM' else ' for ' + str(l.number_of_days) + ' days' if l.number_of_days > 1 else ''))
                                    
                                    # more_detail = f' ({l.leave_cover_id.name})' if l.leave_cover_id.name != l.leave_cover_id.reason_id.name else ''
                                    # leave_des.append('- {}{}{}{}'.format(l.holiday_status_id.name, more_detail, ' (AM)' if e['period'] == 'AM' else ' (PM)' if e['period'] == 'PM' else '', (' of ' + str(l.number_of_days) + ' days') if l.number_of_days > 1 else ''))
                                    leave_des.append('{}{}{}'.format(l.leave_cover_id.name, ' (AM)' if e['period'] == 'AM' else ' (PM)' if e['period'] == 'PM' else '', (' of ' + str(l.number_of_days) + ' days') if l.number_of_days > 1 else ''))
                                    # leave_des.append('- {}{}'.format(l.holiday_status_id.name, ' (AM)' if e['period'] == 'AM' else ' (PM)' if e['period'] == 'PM' else (' day ' + str(e['day_th']) + '/' + str(l.number_of_days)) if l.number_of_days > 1 else ''))

                            raw_description += leave_des
                            if l.leave_cover_id.state and l.leave_cover_id.state != at.state and states.index(l.leave_cover_id.state) < at_state_index and at.state != 'refuse':
                                leave_des = ['<span class="text-danger font-weight-bold">' + des + '</span>' for des in leave_des]
                                states_sync = False
                            else:
                                leave_des = ['<span>' + des + '</span>' for des in leave_des]
                                states_sync = True
                            description += leave_des

                if at.can_convert_leave and at.convert_leave:
                    # REF: https://stackoverflow.com/questions/44968895/how-to-get-string-of-selection-field/44968971
                    convert_leave_label = dict(at._fields['request_leave'].selection).get(at.convert_leave)
                    description.append('Convert leave for {}'.format(convert_leave_label))

                at.request_description = '<br/>'.join(description)
                at.raw_request_description = '\n'.join(raw_description)
                at.states_sync = states_sync
            else:
                at.request_description = False
                at.raw_request_description = False
                at.states_sync = True

    # @api.depends('status_ids')
    def _compute_can_request_leave(self):
        for at in self:
            can_request_leave = False
            can_convert_leave = False
            if not at.data_enough or at.state in ['draft']:
                if at.absence:
                    if len(at.leave_cover_ids) == 0:  # no request
                        can_request_leave = True
                    else:
                        holidays = at.leave_ids.by_at_date_leave(at.at_date)
                        if len(holidays) == 1 and holidays[0]['period'] and at.absence == 'absence':  # 01 leave half day
                            can_request_leave = True
            if not can_request_leave and len(at.leave_cover_ids) > 0:
                can_request_leave = True
            # if not at.status_ids or {'X', '1/2 X'} & set(at.status_ids.mapped('code')):
            #     at.can_request_leave = True
            # else:
            #     at.can_request_leave = False

            # [] TODO compare total works with total required works of the at month
            # print(at.read_group([('employee_id', '=', at.employee_id.id), ('at_month', '=', at.at_date.month)], ['worked_count:sum'], ['at_month']))
            at.update({'can_request_leave': can_request_leave, 'can_convert_leave': can_convert_leave})

    def _compute_can_request_buttons(self):
        for at in self:
            can_request_ot, can_request_wt = (False, False)
            ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
            wt_request = at.at_request_ids.filtered(lambda r: r.request_type == 'working_time')
            if not at.data_enough or at.state in ['draft']:
                if not ot_request:  # no ot request yet
                    can_request_ot = True
                if len(wt_request) == 0 or (len(wt_request) == 1 and not all([wt_request.request_in, wt_request.request_out])):  # no or 01 wt request
                    can_request_wt = True

            if not can_request_ot and ot_request:
                can_request_ot = True
            if not can_request_wt and wt_request:
                can_request_wt = True
            at.update({'can_request_ot': can_request_ot, 'can_request_wt': can_request_wt})

    def _compute_refuse_comment(self):
        for at in self:
            refuse = self.env['hr.attendance.refuse'].search(['|', ('related_request_id', 'in', at.at_request_ids.mapped('id')), ('related_leave_cover_id', 'in', at.leave_cover_ids.mapped('id'))])
            if refuse:
                at.refuse_comment = '\n'.join(refuse.mapped(lambda r: r.name if r.name else ''))
            else:
                at.refuse_comment = False

    # depends: override
    def _compute_worked_hours(self):
        # check_in not available case
        for attendance in self:
            if attendance.check_in and attendance.check_out:
                # return super()._compute_worked_hours()
                delta = attendance.check_out - attendance.check_in
                attendance.worked_hours = delta.total_seconds() / 3600.0
            else:
                attendance.worked_hours = 0

    def get_at_time(self, employee_id, at_date=None, working_start=None):
        """[Return a list of check_ins, check_outs for a specific date in utc]

        Args:
            employee_id
            working_start ([integer]): hour start
            at_date ([date]): [attendance date]
        """
        # [X] TODO: by today KDVN time
        # [X] TODO: Should using working intervals or at least calendar resources
        # New way to dynamically get check_in, check_out time using resource calendar
        # to cover special cases
        
        default_rc = self.env.company.resource_calendar_id
        at_date = at_date or self.env['hr.mixin'].today_vn()
        at_rules = self._at_rules(employee_id=employee_id.id or self.employee_id.id, at_date=at_date)
        working_start = int(at_rules['working_start'])
        rc = self.env['resource.calendar'].browse(at_rules.get('resource_calendar_id', [default_rc.id])[0])
        start = datetime.datetime.combine(self.at_date, datetime.time(working_start - 7), tzinfo=utc)
        end = start + relativedelta(days=1)
        
        if rc:
            at_intervals = rc._attendance_intervals(start, end)
            if at_intervals and len(at_intervals) == 2:
                check_in_am, check_out_am, check_in_pm, check_out_pm = [a_period for sub in rc._attendance_intervals(start, end) for a_period in sub[:2]]
            else:
                # For not working days, still return in out as same as other working days for compute OT
                first_rc_attendances = rc.attendance_ids[:2].mapped(lambda p: [p.hour_from, p.hour_to])
                periods = [int(e) for sub in first_rc_attendances for e in sub]
                check_in_am, check_out_am, check_in_pm, check_out_pm = [vn_tz.localize(datetime.datetime.combine(at_date, datetime.time(period, 0, 0))) for period in periods]
        else:
            # Safe return (hardcode default in out)
            check_in_am = vn_tz.localize(datetime.datetime.combine(at_date, datetime.time(working_start, 0, 0)))
            check_out_am = vn_tz.localize(datetime.datetime.combine(at_date, datetime.time(working_start + 4, 0, 0)))
            check_in_pm = vn_tz.localize(datetime.datetime.combine(at_date, datetime.time(working_start + 5, 0, 0)))
            check_out_pm = vn_tz.localize(datetime.datetime.combine(at_date, datetime.time(working_start + 9, 0, 0)))

        result = list(map(lambda dt: dt.astimezone(utc).replace(tzinfo=None), [check_in_am, check_out_am, check_in_pm, check_out_pm]))
        return result

    @api.depends('check_in', 'check_out', 'check_in_manual', 'check_out_manual', 'status_ids')
    def _compute_in_out_status(self):
        for at in self:
            at.update(at._compute_in_out())
    
    def _compute_in_out(self, compute_in=False, compute_out=False):
        """
            - Helper method to compute in out status (late, early, absence)
            - Allowing compute a child_care user late, early as normal user to support computing OT
        """
        self.ensure_one()
        at = self

        # TODO [X]: time zone
        # TODO [X]: counting for working SAT
        # TODO [X]: not counting if having ot request when working on AH and H
        # TODO []: How about 1/2 AH, 1/2 H
        # TODO [X]: child care

        at_date = at.at_date
        at_rules = at._at_rules(at.employee_id, at_date)
        no_need_check = at_rules.get('no_need_check', False)
        check_in_time, check_out_time, check_in_absence, check_out_absence = None, None, None, None
        day_start, work_start, late, early, absence_minutes, child_care = at_rules['day_start'], at_rules['working_start'], at_rules['late_in'], at_rules['early_out'], at_rules['absence'], at_rules['child_care_period']
        check_dt = at.get_at_time(at.employee_id, at_date)
        (late_in, early_out, absence, work_on_holiday) = [False, False, False, False]
        # wt_requests = at.at_request_ids.filtered(lambda r: r.request_type == 'working_time')
        ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')

        check_in_time, check_in_absence, check_in_time_pm, check_in_absence_pm, check_out_time, check_out_time_am, check_out_absence, check_out_absence_am = [False for e in range(8)]

        compute_in = compute_in or at.compute_in
        compute_out = compute_out or at.compute_out
        if self.env.context.get('do_not_use_child_care', False):
            child_care = 0

        absence_status = set([])
        if no_need_check:
            absence_status = set([])
        else:

            if not (compute_in and compute_out):
                absence_status.add('absence')
            else:
                # child_care_offset = 60 if child_care else 0
                if compute_in >= check_dt[0] and compute_in < check_dt[2]:  # AM check_in: after 8:00
                    work_half = compute_out < check_dt[3] - relativedelta(minutes=absence_minutes + child_care)
                    check_in_time = check_dt[0] + relativedelta(minutes=late + (child_care / 2 if work_half else child_care))  # 08:05:00 or 08:35:00 or 09:05:00
                    check_in_absence = check_dt[0] + relativedelta(minutes=absence_minutes + (child_care / 2 if work_half else child_care))   # 08:30:00 or 09:00:00 or 09:30:00
                if compute_in >= check_dt[2]:  # PM check_in: after 13:00
                    check_in_time_pm = check_dt[2] + relativedelta(minutes=late + child_care / 2)  # 13:05:00 or 13:35:00
                    check_in_absence_pm = check_dt[2] + relativedelta(minutes=absence_minutes + child_care / 2)  # 13:30 or 14:00

                if compute_out <= check_dt[3] and compute_out > check_dt[1]:  # PM check_out: before 17:00
                    work_half = compute_in > check_dt[0] + relativedelta(minutes=absence_minutes + child_care)
                    check_out_time = check_dt[3] - relativedelta(minutes=early + (child_care / 2 if work_half else child_care))  # 17:00:00 or 16:30:00 or 16:00:00
                    check_out_absence = check_dt[3] - relativedelta(minutes=absence_minutes + (child_care / 2 if work_half else child_care))  # 16:30:00 or 16:00 or 15:30:00
                if compute_out <= check_dt[2]:  # AM check_out
                    check_out_time_am = check_dt[1] - relativedelta(minutes=early + child_care / 2)  # 12:00:00 or 11:30:00
                    check_out_absence_am = check_dt[1] - relativedelta(minutes=absence_minutes + child_care / 2)  # 11:30:00 or 11:00:00

                if check_in_absence:
                    if compute_in >= check_in_absence:
                        absence_status.add('absence_am')
                    elif compute_in >= check_in_time:
                        late_in = True
                if check_in_absence_pm:
                    absence_status.add('absence_am')
                    if compute_in >= check_in_absence_pm:
                        absence_status.add('absence_pm')
                    elif compute_in >= check_in_time_pm:
                        late_in = True

                if check_out_absence:
                    if compute_out <= check_out_absence:
                        absence_status.add('absence_pm')
                    elif compute_out < check_out_time:  # actual early policy is 0
                        early_out = True
                if check_out_absence_am:
                    absence_status.add('absence_pm')
                    if compute_out <= check_out_absence_am:
                        absence_status.add('absence_am')
                    elif compute_out < check_out_time_am:
                        early_out = True

        absence = 'absence' if len(absence_status) > 1 else absence_status.pop() if len(absence_status) == 1 else False

        at._compute_is_holiday()  # need this to update stored-computed holidays fields
        if any([at.is_holiday, at.is_public_holiday, at.is_other_holiday, at.ah]):
            if not ot_request:
                work_on_holiday = False
            else:
                if not at.ah or at.ah == 'ah':
                    work_on_holiday = 'work_am' if absence == 'absence_pm' else 'work_pm' \
                        if absence == 'absence_am' else 'work' if not absence else False
                else:
                    work_on_holiday = 'work_am' if (at.ah == 'ah_am' and absence != 'absence' and absence != 'absence_am') \
                        else 'work_pm' if (at.ah == 'ah_pm' and absence != 'absence' and absence != 'absence_am') else False
                if not (work_on_holiday in ['work_am', 'work_pm'] and '1/2 O' in at.status_ids.mapped('code')):
                    # !Review
                    work_on_holiday = False

            if not ({'O', '1/2 O'} & set(at.status_ids.mapped('code'))):
                late_in, early_out = [False, False]
        else:
            for leave in at.leave_ids.filtered('holiday_status_id.is_ah'):
                if absence != 'absence':
                    if leave.request_date_from_period == 'am' and absence != 'absence_am':
                        work_on_holiday = 'work_am'
                    elif leave.request_date_from_period == 'pm' and absence != 'absence_pm':
                        work_on_holiday = 'work_pm'
                    elif not leave.request_date_from_period:
                        work_on_holiday = 'work_am' if absence == 'absence_pm' else 'work_pm' \
                            if absence == 'absence_am' else 'work' if not absence else False

        if {'L', 'AH'} & set(at.status_ids.mapped('code')):
            late_in, early_out = False, False
        elif {'1/2 L', '1/2 AH', '1/2 SH'} & set(at.status_ids.mapped('code')):
            holiday = at.leave_ids.by_at_date_leave(at_date=at.at_date)
            if holiday and len(holiday) == 1:
                if holiday[0]['period'] == 'AM':
                    if check_in_absence:
                        late_in = False
                    if check_out_absence_am:
                        early_out = False
                elif holiday[0]['period'] == 'PM':
                    if check_in_absence_pm:
                        late_in = False
                    if check_out_absence:
                        early_out = False

        return {'late_in': late_in, 'early_out': early_out, 'absence': absence, 'work_on_holiday': work_on_holiday}

    def _compute_ah_status(self):
        # TODO [X]: do not count leave with number_of_days == 0 (register AH leave in Public holiday for example)
        for at in self:
            ah = False
            count_draft_ah = at.env.context.get('count_draft_ah', False)
            not_in_states = ['refuse'] if count_draft_ah else ['refuse', 'draft']
            if at.leave_ids:
                ah_leave = at.leave_ids.filtered(lambda leave: leave.holiday_status_id.is_ah and leave.state not in not_in_states and leave.number_of_days > 0)
                if ah_leave:
                    if len(ah_leave) > 1:
                        _logger.warning(_('More than 1 AH Leaves for a day. Please careful! REF: hr.leave({})'.format(ah_leave.mapped('id'))))
                        ah = 'ah'
                    else:
                        if ah_leave.request_date_from == at.at_date:  # Double check to make sure ah_leave is for at_date
                            ah = 'ah_am' if ah_leave.request_date_to_am else 'ah_pm' if ah_leave.request_date_from_pm else 'ah'
            at.ah = ah

    @api.model
    def compute_manual_attendance_and_code(self):
        # TODO [X]: will NOT compute manual in out any more
        # Using this method just for update back manual_in, manual_out value
        # !check_in_manual and check_out_manual value should not be changed (only accept from user input)
        # !this method wil not need in the future

        ats = self.search([])

        for at in ats.sudo(self.env.uid == 1):
            if at.check_in_manual and at.check_in and at.check_in_manual == at.check_in:
                # reset check_in_manual
                at.check_in_manual = False
            if at.check_out_manual and at.check_out and at.check_out_manual == at.check_out:
                # reset check_out_manual
                at.check_out_manual = False

    @api.depends('check_in', 'check_out', 'check_in_manual', 'check_out_manual')
    def compute_compute_in_out(self):
        """
            - Compute compute_in, compute_out value
            - Also update check_in_location_id and check_out_location_id if need
        """
        for at in self:
            wt_requests = at.at_request_ids.filtered(lambda r: r.request_type == 'working_time' and r.state not in ['refuse'])
            wt_in = wt_requests.filtered(lambda r: r.request_in is not False)
            wt_out = wt_requests.filtered(lambda r: r.request_out is not False)
            if wt_in:
                # wt_in = wt_in[0]
                wt_in = wt_in[0] if wt_in[0].request_in <= wt_in[-1].request_in else wt_in[-1]
            if wt_out:
                # wt_out = wt_out[0]
                wt_out = wt_out[0] if wt_out[0].request_out >= wt_out[-1].request_out else wt_out[-1]

            ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time' and r.state not in ['refuse'])
            at_rules = at._at_rules()

            compute_in = False
            compute_out = False

            if at.check_in and at.check_in_manual:
                check_in = wt_in.request_in if wt_in else at.check_in

                if ot_request:
                    if at_rules['ot_apply_rule'] == 'actual':
                        compute_in = check_in
                    elif at_rules['ot_apply_rule'] == 'register':
                        compute_in = check_in if check_in >= at.check_in_manual else at.check_in_manual
                else:
                    compute_in = check_in

            elif not at.check_in and at.check_in_manual:
                if wt_in:
                    compute_in = wt_in.request_in
                else:
                    compute_in = False
                # if not wt_requests or (wt_requests and len(wt_requests) == 1 and 'forget_out' in wt_requests.mapped('sub_request_type_id.code')):
                #     at.compute_in = False

            else:  # either or both not available
                compute_in = at.check_in if at.check_in else at.check_in_manual  # maybe False

            if at.check_out and at.check_out_manual:
                check_out = wt_out.request_out if wt_out else at.check_out

                if ot_request:
                    if at_rules['ot_apply_rule'] == 'actual':
                        compute_out = check_out
                    elif at_rules['ot_apply_rule'] == 'register':
                        compute_out = check_out if check_out <= at.check_out_manual else at.check_out_manual
                else:
                    compute_out = check_out

            elif not at.check_out and at.check_out_manual:
                compute_out = wt_out.request_out if wt_out else False
                # if not wt_requests or (wt_requests and len(wt_requests) == 1 and 'forget_in' in wt_requests.mapped('sub_request_type_id.code')):
                #     at.compute_out = False
            else:  # either or both not available
                compute_out = at.check_out if at.check_out else at.check_out_manual  # maybe False

            # check_in_location_id = at.check_in_location_id
            # check_out_location_id = at.check_out_location_id
            # if compute_in and compute_in != at.check_in:
            #     check_in_location_id = False
            # if compute_out and compute_out != at.check_out:
            #     check_out_location_id = False
            at.update({'compute_in': compute_in, 'compute_out': compute_out})

    @api.depends('check_in', 'check_out', 'compute_in', 'compute_out')
    def _compute_in_out_location(self):
        for at in self:
            check_in_location_id = False
            check_out_location_id = False
            at_raw =self.env['hr.attendance.raw'].sudo().search([('at_code', '=', at.code)])
            if at.check_in and at.compute_in == at.check_in:
                check_in_location_id = at_raw.first_location_id.id if at_raw and at_raw.first_location_id else False
            if at.check_out and at.compute_out == at.check_out:
                check_out_location_id = at_raw.last_location_id.id if at_raw and at_raw.last_location_id else False
            at.update({'check_in_location_id': check_in_location_id, 'check_out_location_id': check_out_location_id})
    
    def _compute_at_status(self, force_run=False, reset_status=False):
        """
        [Compute attendance marks based on actual check_in, check_out and leave status]
        - reset_status: set status_ids to False: need in case of wrongly computed status_ids (for admin only)
        """
        # TODO [X]: Holiday, Public Holiday, Special Holiday, halfs
        # TODO [X]: use employee working time
        # TODO [X]: half leave
        # TODO []: loop performance
        # TODO [X]: use at_rules
        # TODO [X]: OH
        # TODO [X]: 1/2 O and O for working days only NOT for H, SH, OH and AH
        # TODO [X]: batch commit for heavy task
        # TODO [X]: no need checkin employees: always O for working_intervals

        if reset_status:
            for r in self:
                # r.with_context(do_not_run_at_status=True).status_ids.unlink()
                r.with_context(do_not_run_at_status=True).status_ids = False
                r.with_context(do_not_run_at_status=True)._compute_status_codes()
            return
        
        # statuses
        L = self.env.ref('kdvn_hr_attendance.at_status_leave')
        O = self.env.ref('kdvn_hr_attendance.at_status_work')
        X = self.env.ref('kdvn_hr_attendance.at_status_absence')
        half_L = self.env.ref('kdvn_hr_attendance.at_status_leave_half')
        half_O = self.env.ref('kdvn_hr_attendance.at_status_work_half')
        half_X = self.env.ref('kdvn_hr_attendance.at_status_absence_half')
        H = self.env.ref('kdvn_hr_attendance.at_status_holiday')
        SH = self.env.ref('kdvn_hr_attendance.at_status_sh')
        OH = self.env.ref('kdvn_hr_attendance.at_status_oh')
        AH = self.env.ref('kdvn_hr_attendance.at_status_ah')
        half_H = self.env.ref('kdvn_hr_attendance.at_status_holiday_half')
        half_SH = self.env.ref('kdvn_hr_attendance.at_status_sh_half')
        half_OH = self.env.ref('kdvn_hr_attendance.at_status_oh_half')
        half_AH = self.env.ref('kdvn_hr_attendance.at_status_ah_half')
        delay_duration = self.env.user.company_id.at_policy()['delay_duration'] or 2

        # !NOTE: directly use rc for better performance
        default_rc = self.env.company.resource_calendar_id
        if not default_rc:
            _logger.error(_('Can NOT find default resource calendar. Please create one!'))
            return
        
        def _handle_special_ah_cases(sat_ats):
                # TODO [X]: Handling special case 1/2 AH on an absence day => try change to AH day to avoid
                # 2 status of 1/2 AH, 1/2 L on Saturday that cause error on FSC software (when import data into it)

                # Find another (previous) 1/2 AH and set this 1/2 AH to draft
                last_half_ah_ats = sat_ats.filtered(lambda a: a.ah in ['ah_am', 'ah_pm'] and a.at_date != at.at_date)
                last_half_ah_at = last_half_ah_ats[-1] if last_half_ah_ats else False
                if last_half_ah_at:
                    last_half_ah_at.leave_cover_ids.with_context(do_not_run_at_status=True).action_revise()
                    return last_half_ah_at
                return False

        for at in self:
            if at.env.context.get('do_not_run_at_status', False):
                continue
            at_rules = at._at_rules(employee_id=at.employee_id.id, at_date=at.at_date)
            rc = self.env['resource.calendar'].browse(at_rules.get('resource_calendar_id', (default_rc.id, default_rc.name))[0])
            at_date = at.at_date
            required_checkout = at.get_at_time(at_date=at_date, employee_id=at.employee_id)[3]
            have_wt_request = at.at_request_ids.filtered(lambda r: r.request_type == 'working_time' and r.state not in ['draft', 'refuse'])
            have_ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time' and r.state not in ['draft', 'refuse'])
            have_ot_on_holiday_request = any([at.is_holiday, at.is_public_holiday, at.is_other_holiday]) and at.at_request_ids.filtered(lambda r: r.request_type == 'over_time' and r.state in ['draft'])
            no_need_check = at_rules.get('no_need_check', False)
            
            # Add 01 more day to avoid determine SAT status on next Monday when staff may not finish his/her requests
            over_delay_duration = force_run or (fields.Date.context_today(at) - at.at_date).days >= (delay_duration if at.at_day != 'Sat' else (delay_duration + 1))
            over_checkout = datetime.datetime.now() > (required_checkout + relativedelta(hours=2))
            
            # Submit draft ot_on_holiday if have check_in data
            if have_ot_on_holiday_request and any([at.check_in, at.compute_in]):
                try:
                    have_ot_on_holiday_request.action_submit()
                except Exception as e:
                    _logger.error(_(f'Error happen when submit the OT on holiday request {have_ot_on_holiday_request.at_id.code}. REF.: {e}'))
                    raise UserError(_(f'Error happen when submit the OT on holiday request {have_ot_on_holiday_request.at_id.code}. REF.: {e}'))

            # !Note: Will run only when reach required_checkout
            if force_run and datetime.datetime.now() > required_checkout:
                over_checkout = True

            # TODO [X]: Review method do_not_have_data_yet
            # if at.do_not_have_data_yet(employee_id=at.employee_id.id, at_date=at.at_date) and not over_delay_duration:
            if not over_checkout:
                # TODO [X]: should NOT skip if employee made future leave requests
                # TODO [X]: should NOT skip if at is holiday, having leave request, having wt request
                do_not_skip = False
                # Having leave request
                if bool(at.leave_cover_ids) or any([at.is_holiday, at.is_other_holiday, at.is_public_holiday]):
                    do_not_skip = True
                # if not at.leave_cover_ids and not any([at.is_holiday, at.is_other_holiday, at.is_public_holiday]) and not bool(have_wt_request):
                #     continue

                # Having working request for both check_in and check_out (enough to determine at_status)
                # NOTE: in somecase have_wt_request having more than 01 request
                elif bool(have_wt_request) and any(have_wt_request.mapped(lambda e: all([e.request_in, e.request_out]))):
                    do_not_skip = True
                # elif bool(have_wt_request) and not all([have_wt_request.request_in, have_wt_request.request_out]):
                #     continue

                # Having OT request need to determine at_status to estimate OT hours correctly
                elif bool(have_ot_request and at.at_day == 'Sat'):
                    do_not_skip = True
                # elif not ((have_ot_request or at.leave_cover_ids) and at.at_day == 'Sat'):
                #     continue
                if not do_not_skip:
                    continue

            start_dt = datetime.datetime.combine(at_date, datetime.time.min, tzinfo=utc)
            end_dt = datetime.datetime.combine(at_date, datetime.time.max, tzinfo=utc)

            # !Note: may have 2 sub_leave (2 half)
            all_sub_leaves = self.env['hr.leave'].search([('employee_id', '=', at.employee_id.id), ('substitute_for_date', '=', at.at_date)])
            sub_leaves = all_sub_leaves.filtered(lambda holiday: holiday.leave_cover_id.state not in ['draft', 'waiting_fman', 'refuse'])
            related_at = sub_at = self.env['hr.attendance']
            statuses = []

            # TODO [X] Check related requests and leaves
            # TODO [X] Automatically register AH cases: marked as AH as long as working enough for previous SATs (halfs)
            # ! NOTE: Case took AH on day other than SAT
            # TODO [X] On the last SAT or maybe the last at day of month: need to re-calculate AH
            # !NOTE: Check very carefully here to make sure it is not loop otherwise cannot create ah leave

            if at.at_day == 'Sat' and ((over_delay_duration or bool(have_ot_request)) and over_checkout) and not no_need_check:
                # TODO [X]: do not create ah leave if the SAT is registered for substitute
                # TODO [X]: remove AH when having enough data if needed
                # TODO [X]: compute total halfs by current ah leave allocation
                
                # month work intervals: only needed on Saturdays (moved here from the top of the loop, P8)
                start = datetime.datetime.combine(at.start_date, datetime.time.min, tzinfo=utc)
                end = datetime.datetime.combine(at.end_date - relativedelta(days=1), datetime.time.max, tzinfo=utc)
                month_work_intervals = rc._attendance_intervals(start, end) \
                    - rc._public_holidays_leave_intervals(start, end, False, utc)
                ah_leave_type = self.env['hr.leave.type'].with_context(no_filter_leave_type=True).search([('is_ah', '=', True), ('validity_start', '<=', at.at_date), ('validity_stop', '>=', at.at_date)])
                ah_leave_allocation = self.env['hr.leave.allocation'].sudo().search([('employee_id', '=', at.employee_id.id), ('holiday_status_id', '=', ah_leave_type.id), ('state', '=', 'validate')], limit=1)
                total_ah_halfs = ah_leave_allocation.number_of_days * 2 if ah_leave_allocation else 0
                month_ats_domain = [('employee_id', '=', at.employee_id.id), ('at_year', '=', at.at_year), ('at_month', '=', at.at_month)]
                sat_ats_domain = month_ats_domain + [('at_day', '=', 'Sat'), ('is_holiday', '=', False), ('is_public_holiday', '=', False), ('is_other_holiday', '=', False)]
                sat_ats = at.sudo().with_context(active_test=False).search(sat_ats_domain)
                # ah_halfs = sum(at.with_context(active_test=False).search(month_ats_domain).mapped(lambda a: 1 if a.ah in ['ah_am', 'ah_pm'] else 2 if a.ah == 'ah' else 0))
                ah_halfs = sum(at.sudo().with_context(active_test=False, count_draft_ah=True).search(month_ats_domain).mapped(lambda a: 1 if a.ah in ['ah_am', 'ah_pm'] else 2 if a.ah == 'ah' else 0))
                
                if ah_halfs > total_ah_halfs:  # !NOTE: it must not happen, keep here for detecting code error
                    _logger.warning(_('Used AH halfs ({}) > Total AH halfs ({}), please check for error! REF.: {}'.format(ah_halfs, total_ah_halfs, at.code)))
                    _logger.warning(at.sudo().with_context(active_test=False).search(month_ats_domain).filtered(lambda a: a.ah).mapped('code'))
                    _logger.warning('{} {} {}'.format(ah_halfs, total_ah_halfs, month_ats_domain))
                # working sats: not including at.at_date
                # TODO [X]: L, 1/2 L in SAT should consider as O, 1/2 O
                # TODO [X]: Not sum date after current at_date
                # TODO [X]: SH, 1/2 SH in SAT should consider as O, 1/2 O
                # sat_work_halfs = sum(sat_ats.mapped(lambda a: 0 if not a else 0 if a.at_date >= at.at_date else 1 if '1/2 O' in a.status_ids.mapped('code') else 2 if 'O' in a.status_ids.mapped('code') else 0))
                # sat_work_halfs += sum(sat_ats.mapped(lambda a: 0 if not a else 0 if a.at_date >= at.at_date else 1 if '1/2 L' in a.status_ids.mapped('code') else 2 if 'L' in a.status_ids.mapped('code') else 0))
                # sat_work_halfs += sum(sat_ats.mapped(lambda a: 0 if not a else 0 if a.at_date >= at.at_date else 1 if '1/2 SH' in a.status_ids.mapped('code') else 2 if 'SH' in a.status_ids.mapped('code') else 0))

                # ! New way to compute sat_work_halfs
                sat_work_halfs = sum(sat_ats.mapped(lambda a: 0 if not a else 0 if a.at_date >= at.at_date 
                                                    else (1 * len({'1/2 O', '1/2 L', '1/2 SH'} & set(a.status_ids.mapped('code'))) + 2 * len({'O', 'L', 'SH'} & set(a.status_ids.mapped('code'))))))

                # Compute Sats but NOT holidays
                # ref: resource.py and resouce_calendar.py in hr_holidays_public
                month_sat_work_intervals = list(filter(lambda w: w[0].weekday() == 5, month_work_intervals))
                sat_halfs_remain = len(month_sat_work_intervals) - total_ah_halfs - sat_work_halfs
                work_month_sats = at.monthly_working_weekday(at.at_date)

                create_ah_leave = False
                ah_reason_id = self.env.ref('kdvn_hr_attendance.reason_ah')
                no_ah_employee = ({'House Maid', 'Driver', 'Outsource'} & set(at.employee_id.category_ids.mapped('name'))) or not ah_leave_allocation

                # is_last_sat = (at.end_date - at.at_date).days <= 7
                # is_second_last_sat = (at.end_date - at.at_date).days <= 14 and (at.end_date - at.at_date).days > 7

                is_last_sat = at.at_date == work_month_sats[-1]
                is_second_last_sat = at.at_date == work_month_sats[-2]
                # print('=====', work_month_sats, is_last_sat, is_second_last_sat)

                if not no_ah_employee and not sub_leaves and not at.ah and not any([at.is_public_holiday, at.is_other_holiday]):
                    # TODO []: case 1/2 Leave , 1/2 Absence
                    if ah_halfs < total_ah_halfs:
                        # create AH leave for absence days and skip for OT registed days
                        # Only skip for submmited OT requests
                        # if at.absence and {'X', '1/2 X'} & set(at.status_ids.mapped('code')):
                        if at.absence: 
                            if not have_wt_request or not have_wt_request.filtered(lambda r: r.state in ['waiting_fman']):
                                create_ah_leave = bool(over_delay_duration)
                        else:
                            # !NOTE: Review - redundance
                            if sat_halfs_remain <= 2:
                                create_ah_leave = bool(over_delay_duration) or bool(have_ot_request)

                            # if sat_halfs_remain <= 1:
                            #     create_ah_leave = bool(over_delay_duration) or bool(have_ot_request)
                            # elif sat_halfs_remain <= 2:
                            #     create_ah_leave = bool(over_delay_duration) or bool(have_ot_request)
                                # create_ah_leave = True or is_last_sat  # NOTE: may skip some cases leading to not create enough AH

                if create_ah_leave:
                    # TODO [X]: create AH for last sats when already worked enough in previous SATS
                    # TODO [X]: create AH only if there are no AH in other days than SAT
                    # (otherwise it make sat_halfs_remain caculation wrongly, and become too complicated)
                    am, pm, skip_create_ah = (False, False, False)
                    if not at.absence:
                        if is_last_sat:
                            ah_halfs_remain = total_ah_halfs - ah_halfs
                            if ah_halfs_remain == 1:
                                pm = True
                            elif ah_halfs_remain >=2:
                                pm = False
                            else:
                                skip_create_ah = True
                            # pm = True if (total_ah_halfs - ah_halfs) == 1 else False
                        elif is_second_last_sat:
                            last_sat = at.search([('employee_id', '=', at.employee_id.id), ('at_date', '=', work_month_sats[-1])])
                            if last_sat and last_sat.ah:  # Last SAT already having status
                                ah_halfs_remain = total_ah_halfs - ah_halfs
                                if ah_halfs_remain == 1:
                                    pm = True
                                elif ah_halfs_remain >=2:
                                    pm = False
                                else:
                                    skip_create_ah = True
                                # pm = True if (total_ah_halfs - ah_halfs) == 1 else False
                            else:
                                ah_halfs_remain = total_ah_halfs - ah_halfs - 2
                                if ah_halfs_remain == 1:
                                    pm = True
                                elif ah_halfs_remain >= 2:
                                    pm = False
                                else:
                                    skip_create_ah = True
                                # pm = True if (total_ah_halfs - ah_halfs - 2) == 1 else False
                        else:
                            skip_create_ah = True
                    elif at.absence == 'absence':
                        if '1/2 L' in at.status_ids.mapped('code'):
                            am = True if any(at.leave_ids.mapped('request_date_from_pm')) else False
                            pm = True if any(at.leave_ids.mapped('request_date_to_am')) else False
                        else:
                            pm = True if (total_ah_halfs - ah_halfs) == 1 else False
                    else:  # absence_am or absence_pm
                        am = True if at.absence[-2:] == 'am' else False
                        pm = True if at.absence[-2:] == 'pm' else False
                        if is_second_last_sat:
                            last_sat = at.search([('employee_id', '=', at.employee_id.id), ('at_date', '=', work_month_sats[-1])])
                            if last_sat and last_sat.ah:  # Last SAT already having status
                                if (total_ah_halfs - ah_halfs) >= 2:
                                    # am = False if am else am
                                    # pm = False if pm else pm
                                    am = pm = False
                            else:
                                if (total_ah_halfs - ah_halfs - 2) >= 2:
                                    am = False if am else am
                                    pm = False if pm else pm
                        if is_last_sat and (total_ah_halfs - ah_halfs) >= 2:
                            am = False if am else am
                            pm = False if pm else pm

                    if not skip_create_ah:
                        # Setting AH request to draft => skip creating AH
                        if at.env.context.get('set_draft', False) and at.leave_ids.filtered(lambda h: h.holiday_status_id.is_ah):
                            skip_create_ah = True
                        # SAT having WT requests waiting for approve => skip creating AH
                        if have_wt_request and have_wt_request.filtered(lambda r: r.state == 'waiting_fman'):
                            skip_create_ah = True

                    if not skip_create_ah:
                        try:
                            existed_ah = at.leave_ids.filtered(lambda h: h.holiday_status_id.is_ah and h.request_date_from == h.request_date_to == at.at_date and h.state in ['refuse', 'draft'])
                            existed_ah_cover = existed_ah and existed_ah.leave_cover_id
                            safe_to_go = False

                            if existed_ah_cover:
                                if existed_ah_cover.leave_request_ids and len(existed_ah_cover.leave_request_ids) == 1:
                                    existed_ah_cover.sudo().with_context(do_not_run_at_status=True).unlink()
                                    safe_to_go = True
                            else:
                                safe_to_go = True

                            if safe_to_go:
                                affected_at = False
                                if at.absence == 'absence' and (am or pm):  # handling the case of 1/2 AH in an absence day
                                    affected_at = _handle_special_ah_cases(sat_ats=sat_ats)
                                    if affected_at:
                                        am = pm = False

                                cover = self.env['hr.leave.cover'].sudo().with_context(do_not_run_at_status=True).create_cover(ah_reason_id.id, ah_leave_type.id, at.at_date, pm, at.at_date, am, employee_id=at.employee_id.id)
                                # [X] TODO: test case when 0.5 left on leaves, these below method cannot be run
                                # If not run these mothods, number_of_days will be 0.
                                # FIXED: modify hr.leave _onchange_request_parameters() method
                                # !NOTE: cover action_submit and action_approve will call this method _compute_at_status again: check LOOP!
                                # !NOTE: using break here ensuring this method _compute_at_status run once!
                                if cover and not cover.env.context.get('set_draft', False):
                                    # TODO [X]: will not submit if running action_revise to prevent from looping creating leave
                                    cover.sudo().action_submit()
                                    cover.sudo().action_approve()
                                    cover.sudo().action_validate()
                                    if affected_at:
                                        affected_at.leave_cover_ids.unlink()  #!NOTE: check here
                                        # TODO [X]: update status after unlink AH leave
                                        # !NOTE: check why affected_at NOT update at status after unlink AH leave
                                        affected_at._compute_at_status()
                                        # TODO []: update LEAVE if needed
                            else:
                                _logger.warning('===== Not safe to create AH Leave - Please ask IT for support')

                        except Exception as e:
                            # get error message
                            # REF: https://stackoverflow.com/a/45532289
                            # message = getattr(e, 'message', repr(e))
                            # if message.find('Leave existed:'):
                                # a-not-AH leave existed
                            _logger.exception('===== Cannot create AH leave {}'.format(e))
                else:
                    remove_ah = False
                    update_ah = {}
                    affected_at = False
                    
                    # Request WT for a day (forget / working out cases)
                    if at.ah and not at.absence:
                        # ah_leave_holiday = at.leave_cover_ids.leave_request_ids.filtered(lambda l: l.holiday_status_id.is_ah)
                        if at.at_date in sorted(list(set([w[0].date() for w in month_sat_work_intervals])))[:-2]:  # in first 2 or 3 sat (if having 4, 5 sat a month)
                            # ! Only remove if ah is created by odoo_bot (meaning automatically)
                            remove_ah = at.leave_cover_ids.create_uid.id == 1

                        # in second last sat
                        elif at.at_date == sorted(list(set([w[0].date() for w in month_sat_work_intervals])))[-2] and have_wt_request:
                            if ah_halfs in  [3, 2]:  # second last sat and 1/2 AH, 01 AH left
                                # ! Only remove if ah is created by odoo_bot (meaning automatically)
                                remove_ah = at.leave_cover_ids.create_uid.id == 1
                            elif ah_halfs == 1:
                                if at.ah == 'ah':
                                    update_ah = {'request_date_from_pm': True}
                            elif ah_halfs  == 0:
                                if at.ah != 'ah':
                                    update_ah = {'request_date_from_pm': False, 'request_date_from_am': False}

                    # Request WT for half day (forget / working out cases)
                    if at.ah == 'ah' and (at.absence in ['absence_am', 'absence_pm'] and have_wt_request):
                        if at.at_date in sorted(list(set([w[0].date() for w in month_sat_work_intervals])))[:2]:  # in first 2 or 3 sat (if having 4, 5 sat a month)
                            if len(at.leave_cover_ids) == 1 and at.leave_cover_ids.create_uid.id == 1:
                                if at.absence == 'absence_am':
                                    update_ah['request_date_to_am'] = True
                                else:
                                    update_ah['request_date_from_pm'] = True
                    
                    # Handling the case of 1/2 AH on an absence day
                    if at.ah in ['ah_am', 'ah_pm'] and at.absence == 'absence':
                        affected_at = _handle_special_ah_cases(sat_ats=sat_ats)
                        if affected_at:
                            update_ah['request_date_to_am'] = update_ah['request_date_from_pm'] = False

                    if remove_ah:
                        if len(at.leave_cover_ids) == 1:
                            _logger.warning('===== Remove this AH leaves {}'.format(at.leave_cover_ids))
                            at.leave_cover_ids.sudo().with_context(do_not_run_at_status=True).action_revise()
                            at.leave_cover_ids.sudo().unlink()
                            at.auto_done()
                    
                    if update_ah:  # to 1/2 AH or either full AH
                        _logger.warning(f'===== Update this AH {at.at_date} to {"AH" if affected_at else "1/2 AH"}')
                        at.leave_cover_ids.sudo(self.env.uid == 1).with_context(do_not_run_at_status=True).action_revise()
                        holiday = at.leave_cover_ids.leave_request_ids
                        holiday.update(update_ah)
                        holiday.onchange_period()
                        # at.leave_cover_ids.leave_request_ids = holiday
                        at.leave_cover_ids.sudo().action_submit()
                        at.leave_cover_ids.sudo().action_approve()
                        at.leave_cover_ids.sudo().action_validate()
                        at.auto_done()
                        if affected_at:
                            affected_at.leave_cover_ids.unlink()  # !NOTE: check here
                            affected_at._compute_at_status()

            # Holidays: order: SH => OH => H
            leaves = at.leave_ids
            # NOTE: work_intervals result depends on leaves state (hr_validate => now change to leave.cover draft/submit)
            work_intervals = rc.with_context(exclude_public_holidays=True)._work_intervals(start_dt, end_dt, resource=at.employee_id.resource_id)
            # no_sat_working = (at.at_day == 'Sat' and at.is_no_sat_working(employee_id=at.employee_id, at_date=at.at_date))
            # no_sat_working is handled in _compute_is_holiday already
            if any([at.is_holiday, at.is_other_holiday, at.is_public_holiday]):
                # [X] TODO: only when there is no substitute
                # [X] TODO: If work_on_holiday for OT: check for being substituted
                H_mark = H if (at.is_holiday) else OH if at.is_other_holiday else SH
                half_H_mark = half_H if (at.is_holiday) else half_OH if at.is_other_holiday else half_SH

                if sub_leaves:
                    if len(sub_leaves) == 2:
                        statuses = [O]
                    elif sub_leaves.request_date_from_period or sub_leaves.request_date_to_period:  # sub_leave half_day
                        statuses = [half_O, half_H_mark]
                    else:  # not sub_leave.request_date_from_period:  # sub_leave whole day
                        if not at.absence:
                            statuses = [O]
                        elif at.absence in ['absence_am', 'absence_pm']:
                            statuses = [half_O, half_H_mark]
                        else:
                            statuses = [X]
                    related_at = self.search([('leave_ids', 'in', sub_leaves.mapped('id'))])
                else:
                    statuses = [H_mark]
                
            # Works, Leaves, AH, Absence
            else:
                # Wholeday leave: may be 2 half-leave
                if len(work_intervals) == 0:
                    for e in leaves.by_at_date_leave(at.at_date):
                        # TODO [X]: change the way register for substitute holidays. Check carefully
                        sub_date = e['substitute_for_date']
                        sub_at = False if not sub_date else self.search([('employee_id', '=', at.employee_id.id), ('at_date', '=', sub_date)])

                        hol = at._is_holiday(sub_date)
                        hol_statuses = [(H, half_H), (OH, half_OH), (SH, half_SH), (AH, half_AH), (X, half_X), (L, half_L)]
                        index = -1
                        status_id, status_half_id = hol_statuses[index]

                        # [X] TODO: substitute cases
                        # [X] TODO: update sub_hol status
                        if e['holiday_type'].is_ah:
                            index = 3
                        elif e['holiday_type'].is_special or e['holiday_type'].category == 'special_leave':
                            # index = 1 if e['holiday_type'].category == 'summer_vacation' else 2
                            index = 2
                        elif e['holiday_type'].category == 'sub_holiday':  # sub. on H
                            index = 0 if hol == 'H' else 1 if hol == 'OH' else 2 if hol == 'SH' else -1
                        elif e['holiday_type'].category == 'absence':
                            index = 4
                        else:
                            index = -1
                        status_id, status_half_id = hol_statuses[index]

                        if e['period']:
                            statuses.append(status_half_id)
                        else:
                            statuses = [status_id]
                        
                # Half day leave
                elif len(work_intervals) == 1:
                    for e in leaves.by_at_date_leave(at.at_date): # ! only one element
                        sub_date = e['substitute_for_date']
                        sub_at = False if not sub_date else self.search([('employee_id', '=', at.employee_id.id), ('at_date', '=', sub_date)])

                        hol = at._is_holiday(sub_date)
                        hol_statuses = [half_H, half_OH, half_SH, half_AH, half_X, half_L]
                        index = -1

                        if e['holiday_type'].is_ah:
                            index = 3
                        elif e['holiday_type'].is_special or e['holiday_type'].category == 'special_leave':
                            # index = 1 if e['holiday_type'].category == 'summer_vacation' else 2
                            index = 2
                        elif e['holiday_type'].category == 'sub_holiday':
                            index = 0 if hol == 'H' else 1 if hol == 'OH' else 2 if hol == 'SH' else -1
                        elif e['holiday_type'].category == 'absence':
                            index = 4
                        else:
                            index = -1
                        status_half_id = hol_statuses[index]

                        if sub_date and sub_at:
                            statuses.append(half_X if at.absence == 'absence' else half_O)
                            statuses.append(status_half_id)
                        else:
                            statuses.extend([status_half_id, half_X if at.absence == 'absence' else half_O])

                # absence, work
                else:
                    if at.absence == 'absence':
                        statuses.append(X)
                    elif at.absence == 'absence_am' or at.absence == 'absence_pm':
                        statuses = [half_X, half_O]
                    else:
                        # For no_need_check cases need to do it in reverse:
                        # if they submit leaves but still not approve yet => show X or 1/2 X
                        # for a constructive meaning to manager
                        # !NOTE: can NOT use work_intervals here because it depends on leave state and not logic
                        # !NOTE: construct a dictionary with keys are the dates and values are a list of either 'am' or 'pm'
                        if no_need_check and at.leave_cover_ids:
                            periods = at.leave_cover_ids.filtered(lambda e: e.state in ['waiting_fman']).mapped(lambda c: [c.dt_from, c.date_from_period, c.dt_to, c.date_to_period])
                            leave_day_maps = []
                            for period in periods:
                                dates = [period[0] + relativedelta(days=n) for n in range((period[2] - period[0]).days + 1)]
                                leave_day_maps.append({d: ['' if d == period[0] and period[1] == 'pm' else 'am', '' if d == period[2] and period[3] == 'am' else 'pm'] for d in dates})
                            D = defaultdict(set)
                            for d in leave_day_maps:
                                for key, values in d.items():
                                    for v in values:
                                        if v:
                                            D[key].add(v)
                            periods_by_date = {k: sorted(list(v)) for k, v in D.items()}
                            period_halfs = len(periods_by_date.get(at.at_date, []))
                            if period_halfs == 1:
                                statuses = [half_X, half_O]
                            elif period_halfs == 2:
                                statuses = [X]
                            else:
                                statuses = [O]

                        else:
                            statuses.append(O)

            # [X] TODO: 1/2 AH, 1/2 L cases => status will have more than 2 values such as 1/2 AH, 1/2 L, 1/2 X
            if {half_AH, half_L, half_X}.issubset(set(statuses)):
                leaves_status = at.leave_ids.mapped(lambda h: ('AH' if h.holiday_status_id.is_ah else 'L', h.state)) 
                if ('L', 'validate') in leaves_status and ('AH', 'validate') in leaves_status:
                    statuses = [half_L, half_AH]
                elif ('L', 'validate') in leaves_status and ('AH', 'validate') not in leaves_status:
                    statuses = [half_L, half_X]
                elif ('L', 'validate') not in leaves_status and ('AH', 'validate') in leaves_status:
                    statuses = [half_X, half_AH]
                else:
                    statuses = [X]
            
            # TODO [X]: this assert should NOT for production
            if len(statuses) > 2:
                if len(statuses) == 4 and len(set(statuses)) == 2:
                    _logger.warning(f'Just continue! {list(map(lambda s: s.name, statuses))}')
                else:
                    raise AssertionError(f'Statuses variable must have maximum 2 values. Dev, please check your code! REF.: {at.code, list(map(lambda s: s.name, statuses))}')
            # assert len(statuses) <= 2, 'Statuses variable must have maximum 2 values. Dev, please check your code! REF.: {}'

            # TODO [X]: 2-equaled halfs => 1-full
            STATUS_MAP = {half_O: O, half_AH: AH, half_H: H, half_L: L, half_OH: OH, half_SH: SH, half_X: X}
            if len(statuses) == 2 and statuses[0] == statuses[1]:
                replacement = STATUS_MAP.get(statuses[0])
                if replacement is not None:
                    statuses = [replacement]

                # for s in [(O, half_O), (AH, half_AH), (H, half_H), (L, half_L), (OH, half_OH), (SH, half_SH),
                #           (X, half_X)]:
                #     if s[1] == statuses[0]:
                #         statuses = [s[0]]
                #         break

            ids = list(map(lambda s: s.id, statuses))
            if set(ids) != set(at.status_ids.ids):
                at.status_ids = [(6, False, ids)]
            # TODO []: Update OT calculation
            if sub_leaves or have_ot_request or (at.at_day == 'Sat' and have_ot_request):
                at._compute_ot_request()
            
            if related_at:
                related_at = related_at.filtered(lambda a: a.id != at.id)  # avoid duplicate at
                _logger.warning(_('====== related ats and sub_leaves {} {}'.format(related_at, sub_leaves)))
                related_at._compute_at_status()

    def _compute_month_ah(self):
        """
            - Recompute all automatically created AH in an AT Month by:
            + Unlink all AH of the month
            + Recompute all AH from the beginning of the month
            - Should be run only when AH not compute exactly and already have enough data and status
        """
        for at in self:
            sat_ats = at.search([('employee_id', '=', at.employee_id.id), ('at_year', '=', at.at_year), ('at_month', '=', at.at_month), ('at_day', '=', 'Sat')])
            # Unlink without recreate AH
            for a in sat_ats:
                if a.ah:
                    pass


    def _compute_ot_request(self):
        for at in self:
            at.update(at._compute_ot_hour())
    
    def _compute_ot_hour(self, estimate=False):
        # NOTE: using UTC to calculate all time related computing, only use local timezone when there is a need
        #       to show the date/time on UI.
        # NOTE: check_in, check_out time will be rounded by 15 minute (round down) => then calculate Overtime hours
        # TODO [X]: Child care
        # TODO [X]: apply OT rule and policy here
        # TODO [X]: Estimate OT
        # TODO [X]: OT on AH as a holiday only apply for last two Saturdays (but still count as normal day)
        # TODO []: Test

        def _round_dt(a_dt, step=15, round_down=True):
            """
                - Helper method to round a datetime by 15-minute or 0.25-hour steps
                - a_dt: datetime
            """
            minutes = a_dt.hour * 60 + a_dt.minute
            minutes = roundPartial(minutes, step, round_down=round_down)
            if minutes == 1440:
                return a_dt + relativedelta(days=1, hour=0, minute=0, second=0)
            else:
                return a_dt + relativedelta(hour=minutes // 60, minute=minutes % 60)

        at = self
        at_rules = at._at_rules()
        day_start, working_start, child_care = int(at_rules['day_start']), int(at_rules['working_start']), at_rules['child_care_period']
        at_requests = at.at_request_ids
        if estimate:  # Allow to compute ot_hour for estimation
            ot_request = at_requests.filtered(lambda r: r.request_type == 'over_time')
        else:
            # ot_request = at_requests.filtered(lambda r: r.request_type == 'over_time' and r.state not in ['draft', 'waiting_fman', 'refuse'])
            ot_request = at_requests.filtered(lambda r: r.request_type == 'over_time' and r.state in ['waiting_fhr', 'done'])
        if len(ot_request) > 1:
            # Only 01 OT request is expected per attendance; if duplicates exist (e.g. remote sync), use the newest non-refused one
            _logger.warning('Attendance %s has %s OT requests %s, using the newest non-refused one', at.code, len(ot_request), ot_request.ids)
            ot_request = (ot_request.filtered(lambda r: r.state != 'refuse') or ot_request).sorted('id', reverse=True)[:1]
        ot_sub_request = ot_request.sub_request_type_id.code
        sub_leaves = self.env['hr.leave'].search([('employee_id', '=', at.employee_id.id), ('substitute_for_date', '=', at.at_date)])
        special_ot_hour = at_rules['special_ot_hour']
        st_time = datetime.datetime.combine(at.at_date, datetime.time(special_ot_hour[0] - utc_diff)) # 22:00
        start_time = datetime.datetime.combine(at.at_date, datetime.time(working_start - utc_diff))  # 8:00
        end_am_time = datetime.datetime.combine(at.at_date, datetime.time(working_start + 4 - utc_diff))  # 12:00
        start_pm_time = datetime.datetime.combine(at.at_date, datetime.time(working_start + 5 - utc_diff))  # 13:00
        end_time = datetime.datetime.combine(at.at_date, datetime.time(working_start + 9 - utc_diff))  # 17:00
        added_hours = (0, 0)  # will be used in case OT for 1/2 AH, H and another OT for 1/2 W: (normal_hour, special_hour)

        ot_apply = False
        if estimate:
            # compute_in = at.compute_in if at.compute_in else (ot_request.request_in if ot_sub_request in ['am', 'both'] else start_time)
            # compute_out = at.compute_out if at.compute_out else (ot_request.request_out if ot_sub_request in ['pm', 'both'] else end_time)
            compute_in = ot_request.request_in if ot_sub_request in ['am', 'both'] else start_time
            compute_out = ot_request.request_out if ot_sub_request in ['pm', 'both'] else end_time
        else:
            compute_in, compute_out = at.compute_in, at.compute_out

        # Handle compute_out in case HR Admin choose Out By Register option
        if ot_request and ot_request.out_by_reg:
            compute_out = ot_request.request_out

        # weekday, holiday or public holiday
        # no_sat_working = at.at_day == 'Sat' and at.employee_id.resource_calendar_id.name == 'KINDEN VIETNAM 40 Hours/Week'
        no_sat_working = at.at_day == 'Sat' and at.is_no_sat_working(employee_id=at.employee_id, at_date=at.at_date)
        day_type = 'P' if at.is_public_holiday else 'H' if (at.is_holiday or at.is_other_holiday or no_sat_working) else 'W'
        
        # Working in AH day consider as holiday ONLY IF in last two saturdays
        in_last_half_month = at.in_last_half_month(at.at_date)
        wd_as_hd = False # weekday treated as holiday. Ex.: case 1/2 AH OT weekday
        if at.ah == 'ah':  # AH OT
            day_type = 'H'
            wd_as_hd = 'hd_ot' if in_last_half_month else 'wd_ot'
        elif at.ah in ['ah_am', 'ah_pm'] and not at.absence:  # 1/2 AH OT
            day_type = 'H'
            wd_as_hd = 'hd_ot' if in_last_half_month else 'wd_ot'
        elif at.ah in ['ah_am', 'ah_pm'] and at.absence in ['absence_am', 'absence_pm']:  # 1/2 day OT
            day_type = 'W'
        # Double check OT Holidays Plan if having wd_as_hd = 'hd_ot'
        if wd_as_hd == 'hd_ot':
            ot_holiday_line = self.env['hr.attendance.ot.holiday.line'].search([('employee_id', '=', at.employee_id.id), ('at_date', '=', at.at_date), ('ot_register', '=', True), ('state', '=', 'done')])
            if not ot_holiday_line and not ot_holiday_line.env.context.get('set_draft', False):
                # !NOTE: raise error here will break for loop calling from other method
                _logger.error(_(f'OT on holidays without register for the OT schedule in advance! Please contact HR for instruction! REF.: {at.code}'))
                wd_as_hd = 'wd_ot'
                # raise ValidationError(_(f'OT on holidays without register for the OT schedule in advance! Please contact HR for instruction! REF.: {at.code}'))

        # Force ot_sub_request = 'both' in OT in holidays
        if ot_sub_request != 'both' and (day_type in ['H', 'P'] and not at.ah):
            ot_sub_request = 'both'
        # This rule does NOT apply for OT in holidays EXCEPT out_by_reg case
        if compute_in and ot_sub_request in ['am', 'both'] and not (day_type in ['P', 'H'] and not at.ah and not ot_request.out_by_reg):
            if ot_request.request_in and ot_request.request_in > compute_in:
                compute_in = ot_request.request_in
        # ot_hour_minus = False  # minus 4-hour in case of working half_day for work_on_holiday days

        # TODO [X]: No OT Morning for HO/HCMC area also means no OT Morning in Holidays
        # !NOTE: this rule should using attendance rule allowing a specialcase can override
        # if compute_in and at.employee_id.admin_dept_id.area_id.code in ['CA00', 'SA00'] and day_type in ['P', 'H']:
        #     compute_in = start_time if compute_in < start_time else start_pm_time if compute_in > end_am_time and compute_in < start_pm_time else compute_in

        if child_care:
            # When user having child_care work as normal: compute as normal + offset
            if ot_sub_request == 'pm' and day_type in ['W']:
                offset_minutes = child_care if not at.absence else child_care / 2
                start_dt = start_time if (not at.absence or at.absence == 'absence_pm') else start_pm_time
                end_dt = end_time if (not at.absence or at.absence == 'absence_am') else end_am_time
                if compute_in and compute_in > start_dt:
                    in_out_status = at.with_context(do_not_use_child_care=True)._compute_in_out()
                    if in_out_status['late_in']:
                        offset_minutes -= (compute_in - start_dt).total_seconds() // 60
                    if in_out_status['early_out'] and compute_out:
                        offset_minutes -= roundPartial((end_dt - compute_out).total_seconds() // 60, 15, round_down=False)
                if compute_out and compute_out >= st_time - relativedelta(minutes=child_care):
                    st_time = st_time + relativedelta(minutes=child_care)  # to avoid compute over special time
                if compute_out:
                    compute_out = compute_out + relativedelta(minutes=offset_minutes)

        # Working OT in Holiday can be absence
        if (not compute_in or not compute_out) or (compute_in and compute_out and at.absence == 'absence' and not day_type in ['P', 'H']):
            ot_apply = estimate or False
        else:
            if sub_leaves and len(sub_leaves) == 1:
                if sub_leaves.request_date_from_period or sub_leaves.request_date_to_period:
                    if at.absence:
                        ot_apply = False
                    else:
                        if sub_leaves.request_date_from_period == 'am':
                            compute_in = compute_in + relativedelta(hour=working_start + 5 - utc_diff, minute=0)
                        else:
                            compute_out = compute_out + relativedelta(hour=working_start + 4 - utc_diff, minute=0)
                        ot_apply = True
                if not sub_leaves.request_date_from_period:
                    ot_apply = False
            # elif sub_leaves and len(sub_leaves) == 2:
            #     ot_apply = False

            if day_type in ['P', 'H']:
                if not at.absence == 'absence':
                    if 'O' in at.status_ids.mapped('code'):
                        ot_apply = True
                        day_type = 'W'  # treat the day as normal weekday
                    elif '1/2 O' in at.status_ids.mapped('code'):
                        # !NOTE: Employee can request OT for 1/2 O and the other half as OT for holiday
                        # !NOTE: May need to compute OT for holiday here
                        # !NOTE: Will consider only 1/2 AH OT or 1/2 H OT. 1/2 O OT will not count
                        # TODO []: Using additional hours to add to H or P day (1/2 cases)
                        if not at.absence:
                            # Case: 1/2 O 1/2 AH: OT on AH
                            if at.ah == 'ah_am':
                                ot_apply = True
                                compute_out, normal_compute_out = end_am_time, _round_dt(compute_out)
                                if ot_sub_request == 'both':
                                    if normal_compute_out <= st_time:
                                        added_hours = (max((normal_compute_out - end_time).total_seconds(), 0) / 3600, 0)
                                    else:
                                        added_hours = (max((st_time - end_time).total_seconds(), 0) / 3600, max((normal_compute_out - st_time).total_seconds(), 0) / 3600)
                            
                            if at.ah == 'ah_pm':
                                ot_apply = True
                                compute_in, normal_compute_in = start_pm_time, _round_dt(compute_in, round_down=False)
                                if ot_sub_request == 'both':
                                    if normal_compute_in < start_time:
                                        added_hours = (max((start_time - normal_compute_in).total_seconds(), 0) / 3600, 0)
                            
                            if not at.ah:
                                ot_apply = True

                            # if ot_sub_request == 'both' and ot_request.request_in >= start_pm_time:
                            #     ot_hour_minus = False
                            # else:
                            #     ot_hour_minus = True
                        # if ot_sub_request == 'am':
                        #     pass
                        # if ot_sub_request == 'pm':
                        #     pass
                        # if ot_sub_request == 'both':
                        #     pass
                    else:
                        ot_apply = True
                else:
                    # Still apply if working on holiday (regardless of absence status)
                    ot_apply = compute_in and compute_out
            else:
                ot_apply = True

        ot_hour = {'wd_ot': 0, 'wd_st': 0, 'hd_ot': 0, 'hd_st': 0, 'ph_ot': 0, 'ph_st': 0, 'ot_am': 0, 'ot_pm': 0, 'ot_wd': 0, 'ot_hd': 0, 'ot_total': 0}
        if ot_apply and ot_request:
            # special_ot_hour = at_rules['special_ot_hour']
            # Partial through noon: 12:00 => check_in => 13:00 => check_out OR check_in => 12:00 => check_out => 13:00
            if compute_in > end_am_time and compute_in < start_pm_time and compute_out > start_pm_time:
                compute_in = start_pm_time
            # if compute_in <= end_am_time and compute_out > end_am_time and compute_out <= start_pm_time:
            #     compute_out = end_am_time
            if compute_in <= end_am_time and compute_out > end_am_time:
                if compute_out <= start_pm_time:
                    compute_out = end_am_time
                elif compute_out <= end_time:
                    if not ot_request.include_absence_hour:
                        if day_type == 'W':
                            if not at.ah:
                                compute_out = end_am_time
                            elif at.absence:
                                compute_out = end_am_time

            # [X] More precise calculation (round down by 15-minute or 0.25-hour steps)
            check_in_minutes = compute_in.hour * 60 + compute_in.minute
            check_in_minutes = roundPartial(check_in_minutes, 15, round_down=False)
            if check_in_minutes == 1440:
                check_in_manual = compute_in + relativedelta(days=1, hour=0, minute=0, second=0)
            else:
                check_in_manual = compute_in + relativedelta(hour=check_in_minutes // 60, minute=check_in_minutes % 60, second=0)

            # !NOTE: when second is 59, it is due to system automatically change user input from 6:00 to 5:59:59
            # !NOTE: to ensure the time input is with in attendance day
            check_out_minutes = compute_out.hour * 60 + compute_out.minute + (1 if compute_out.second == 59 else 0)
            check_out_minutes = roundPartial(check_out_minutes, 15)
            if check_out_minutes == 1440:
                check_out_manual = compute_out + relativedelta(days=1, hour=0, minute=0, second=0)
            else:
                check_out_manual = compute_out + relativedelta(hour=check_out_minutes // 60, minute=check_out_minutes % 60, second=0)

            # Full through noon: check_in => 12:00 => 13:00 => check_out
            through_noon = check_in_manual <= end_am_time and check_out_manual >= start_pm_time

            ot_time_am = (start_time - check_in_manual) if start_time > check_in_manual else datetime.timedelta(0)

            if check_out_manual and check_out_manual < st_time:  # normal ot time
                if day_type == 'W':
                    if '1/2 O' in set(at.status_ids.mapped('code')) and at.absence == 'absence_pm':  # absence pm
                        if '1/2 AH' in set(at.status_ids.mapped('code')):
                            # NOTE: it seems that OT for 1/2 AH here is never happen => OT in 1/2 O as wd_ot (even in the last 2-sat)
                            # wd_as_hd = 'hd_ot' if in_last_half_month else 'wd_ot'
                            wd_as_hd = 'wd_ot'
                        ot_time_pm = (check_out_manual - start_pm_time) if check_out_manual >= start_pm_time else datetime.timedelta(0)
                    else:  # absence_am or not absence compute the same way
                        ot_time_pm = (check_out_manual - end_time) if check_out_manual >= end_time else datetime.timedelta(0)
                else:
                    if {'1/2 O', '1/2 AH'} == set(at.status_ids.mapped('code')) and not at.absence:  # OT for 1/2 AH
                        through_noon = False

                    ot_time_pm = check_out_manual - (start_time if check_in_manual <= start_time else check_in_manual)

                    if through_noon:
                        ot_time_pm = ot_time_pm - datetime.timedelta(hours=1)

                ot_time_pm = ot_time_pm if ot_time_pm > datetime.timedelta(0) else datetime.timedelta(0)
                st_time_pm = datetime.timedelta(0)
            elif check_out_manual and check_out_manual >= st_time:  # special ot time => also taking care cases that check_in later than st_time
                ot_time_pm = st_time - end_time
                if day_type == 'W':
                    ot_time_pm = st_time - end_time
                else:
                    ot_time_pm = datetime.timedelta(0) if st_time <= check_in_manual else (st_time - check_in_manual) if check_in_manual > start_time else st_time - start_time
                    if through_noon:
                        ot_time_pm = ot_time_pm - datetime.timedelta(hours=1)
                st_time_pm = check_out_manual - (st_time if st_time > check_in_manual else check_in_manual)
            else:
                pass  # !NOTE: nothing here

            # TODO [X]: When check in early the OT time to 6:00 considered as Special OT
            if ot_time_am > datetime.timedelta(hours=2):
                st_time_pm += ot_time_am - datetime.timedelta(hours=2)
                ot_time_am = datetime.timedelta(hours=2)

            ot_time = datetime.timedelta(0)
            st_time = datetime.timedelta(0)
            ot_am = datetime.timedelta(0)
            ot_pm = datetime.timedelta(0)

            if ot_sub_request == 'am':
                ot_time = ot_time_am
                ot_am = ot_time_am
            if ot_sub_request == 'pm':
                ot_time = ot_time_pm
                st_time = st_time_pm or datetime.timedelta(0)
                ot_pm = ot_time + st_time
            if ot_sub_request == 'both':
                ot_time = ot_time_am + ot_time_pm
                st_time = st_time_pm or datetime.timedelta(0)
                ot_am = ot_time_am
                ot_pm = ot_time_pm + st_time

            # adjust_ot_hour = datetime.timedelta(hours=4) if ot_hour_minus else datetime.timedelta(0)
            ot_time = max(ot_time.total_seconds(), 0) / 3600
            st_time = max(st_time.total_seconds(), 0) / 3600
            ot_am = max(ot_am.total_seconds(), 0) / 3600
            ot_pm = max(ot_pm.total_seconds(), 0) / 3600

            # TODO [X] !Review
            ot_time = max(0, ot_time)
            st_time = max(0, st_time)
            ot_am = max(0, ot_am)
            ot_pm = max(0, ot_pm)

            if day_type in ['P', 'H']:  #! NOTE: follow HR instruction
                if at.ah != 'ah':
                    ot_am = ot_am + ot_pm
                    ot_pm = 0

            ot_hour.update({'ot_am': ot_am + sum(added_hours), 'ot_pm': ot_pm})

            if day_type == 'P':
                ot_hour['ph_ot'] = ot_time
                ot_hour['ph_st'] = st_time
            if day_type == 'H':
                if wd_as_hd == 'wd_ot':
                    ot_hour['wd_ot'] = ot_time + added_hours[0]
                    ot_hour['wd_st'] = st_time + added_hours[1]
                else:
                    ot_hour['hd_ot'] = ot_time + added_hours[0]
                    ot_hour['hd_st'] = st_time + added_hours[1]
            if day_type == 'W':
                if wd_as_hd == 'hd_ot':

                    ot_hour['hd_st'] = st_time  # NOTE: seem no need this line
                else:
                    ot_hour['wd_ot'] = ot_time
                    ot_hour['wd_st'] = st_time
            ot_hour['ot_wd'] = ot_hour['wd_ot'] + ot_hour['wd_st']
            ot_hour['ot_hd'] = ot_hour['hd_ot'] + ot_hour['hd_st'] + ot_hour['ph_ot'] + ot_hour['ph_st']
            ot_hour['ot_total'] = ot_hour['ot_wd'] + ot_hour['ot_hd']
            return ot_hour
        else:
            # reset all OT
            return ot_hour

    # @api.onchange('at_request_ids')
    def _onchange_at_requests(self):
        for at in self:
            manual_in, manual_out = False, False
            wt_requests = at.at_request_ids.filtered(lambda r: r.request_type == 'working_time')
            # ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
            for r in wt_requests:
                # print('=====', r.state)
                if r.request_in:
                    manual_in = r.request_in if r.state not in ['draft', 'waiting_fman', 'refuse'] else False
                if r.request_out:
                    manual_out = r.request_out if r.state not in ['draft', 'waiting_fman', 'refuse'] else False
            at.update({'check_in_manual': manual_in, 'check_out_manual': manual_out})
            # at.check_in_manual = manual_in
            # at.check_out_manual = manual_out

    @api.depends('status_ids')
    def _compute_status_codes(self):
        for at in self:
            at.status_codes = ', '.join(at.status_ids.mapped('code'))

    def _compute_rule_ids(self):
        # Return all at rules applying to an employee (regardless of valid dates)
        for at in self:
            at_rules_domain = [('is_active', '=', True), '|', '|', ('employee_ids', '=', at.employee_id.id),
                               ('department_ids', '=', at.department_id.id if at.department_id else 0), ('company_id', '=', at.employee_id.company_id.id)]

            at_rule_ids = self.env['hr.attendance.rule'].search(at_rules_domain)
            at.at_rule_ids = at_rule_ids.with_context(at_date=at.at_date)
            # self = self.with_context(at_date=at.at_date)

    def _compute_at_rules(self):
        # generate current at_rules to show in UI (form view)
        # the view is defined in data/mail_templates.xml
        at_view = self.env.ref('kdvn_hr_attendance.at_rules')
        for at in self:  # Odoo 19: per record (a prefetch batch may hold several)
            at_rules = at._at_rules()
            rule_desc = at._at_rules(get_rule_desc=True)
            rules = []
            for key in at_rules.keys():
                label = self.env['hr.attendance.rule'].fields_get().get(key, {'string': None})['string']
                value = at_rules.get(key, None)
                desc = rule_desc.get(key, ['', ''])
                rules.append((key, label or key, value, desc[0], desc[1]))
            values = {'rules': rules, 'employee_name': at.employee_id.display_name}
            at.at_rules = self.env['ir.qweb']._render(at_view.id, values)

    @api.depends('at_date')
    def _compute_start_end_date(self):
        for at in self:
            # Using common method to get start_date
            start_date = at.get_start_dt(a_date=at.at_date, for_month=True)
            end_date = start_date + relativedelta(months=1)
            # date_start = at._at_rules()['date_start'] or 21
            # if at.at_date.day >= date_start:
            #     start_date = datetime.date(at.at_date.year, at.at_date.month, date_start)
            #     end_date = start_date + relativedelta(months=1)
            # else:
            #     end_date = datetime.date(at.at_date.year, at.at_date.month, date_start)
            #     start_date = end_date - relativedelta(months=1)
            at_month, at_year = end_date.month, end_date.year

            at.update({'start_date': start_date, 'end_date': end_date, 'at_month': at_month, 'at_year': at_year})

    def current_month_at(self):
        """Return a list of current month (by KDVN definition) attendances
        of a specific employee

        Returns:
            [list]: [{'at_date': date, 'status_codes': list}]
        """
        # [] TODO: perfromance | repeated a month (30 times)
        self.ensure_one()
        at_date = self.at_date
        at_rules = self._at_rules()
        if at_date.day >= at_rules['date_start']:  # 21 ~ 31
            date_start = datetime.date(at_date.year, at_date.month, at_rules['date_start'])
            date_end = date_start + relativedelta(months=1)
        else:  # 01 ~ 20
            date_end = datetime.date(at_date.year, at_date.month, at_rules['date_start'])
            date_start = date_end - relativedelta(months=1)
        domain = [('at_date', '>=', date_start), ('at_date', '<', date_end), ('employee_id', '=', self.employee_id.id)]
        at_data = self.env['hr.attendance'].search(domain)
        result = at_data.mapped(lambda at: dict([('at_date', at.at_date), ('status_codes', at.status_ids.mapped('code'))]))
        return result

    def _compute_current_absence_date(self):
        for at in self:
            month_at = at.current_month_at()
            # month_absence = filter(lambda e: any(status in e['status_codes'] for status in ['X', '1/2X']) , month_at)
            month_absence = filter(lambda e: set(['X', '1/2 X']).intersection(set(e['status_codes'])), month_at)
            at.current_absence_date = json.dumps(list(map(lambda e: e['at_date'].strftime('%Y-%m-%d'), month_absence)))

    def _compute_aval_substitute_date(self):
        """Compute available working date on holidays for exchanging with absence
        By compute work_intervals (minus 2 days for AH)
        """
        for at in self:
            def _work_on_holiday(a):
                return any([a.is_holiday, a.is_public_holiday, a.is_other_holiday]) and (a.absence != 'absence')

            month_ats_domain = [('employee_id', '=', at.employee_id.id), ('at_year', '=', at.at_year), ('at_month', '=', at.at_month)]
            work_on_holiday_ats = at.search(month_ats_domain).filtered(_work_on_holiday)
            aval_subtitute_date = json.dumps(list(map(lambda e: e['at_date'].strftime('%Y-%m-%d'), work_on_holiday_ats)))

            at.aval_substitute_date = aval_subtitute_date

    def convert_to_leave(self):
        self.ensure_one
        # at = self
        print('Increase annual leave')
        print('Changing status')

    @api.depends('status_ids')
    def _compute_worked_count(self):
        for at in self:
            worked_count = 0
            at_marks = set(at.status_ids.mapped('code'))
            if set(['O', 'L']) & at_marks:
                worked_count = 1
            if '1/2 O' in at_marks:
                worked_count += 0.5
            if '1/2 L' in at_marks:
                worked_count += 0.5
            at.worked_count = worked_count

    @api.depends('status_ids', 'absence')
    def _compute_absence_count(self):
        for at in self:
            absence_count = 0
            if at.absence == 'absence':
                absence_count = 1
            if at.absence == 'absence_am' or at.absence == 'absence_pm':
                absence_count = 0.5
            at.absence_count = absence_count

    def action_related_leaves_form(self):
        # Return dynamic action to open leave form
        # TODO [X]: Allow admin to create leave when at state is done

        self.ensure_one()
        at = self
        domain = [('id', 'in', at.leave_cover_ids.mapped('id'))] if at.leave_cover_ids else []
        context = {'show_ah': True if not at.leave_ids else bool(at.leave_ids.filtered(lambda h: h.holiday_status_id.is_ah)), 
                   'at_id': at.id, 'default_employee_id': at.employee_id.id, 'is_readonly': False, 
                #    'form_view_initial_mode': 'edit'
                   }
        view_id = self.env.ref('kdvn_hr_attendance.hr_leave_cover_form').id
        action = {
            'res_model': 'hr.leave.cover',
            
            'view_mode': 'list,form',
            'type': 'ir.actions.act_window',
            # 'target': 'new',
            # 'res_id': False,
            'domain': domain,
            'context': context
        }
        if len(at.leave_cover_ids) == 1 or not at.leave_cover_ids:
            action.update({'name': _('New Leaves'), 'views': [(view_id, 'form')], 'view_id': view_id, 'target': 'new', 
                           'res_id': at.leave_cover_ids.id if at.leave_cover_ids else False})

        # TODO []: DRY - same as leave_cover constrains
        delay_duration = self.env.user.company_id.at_policy()['delay_duration'] if self.env.user.company_id else 2
        today = fields.Date.context_today(self)
        if self.env.uid not in [1, 2] or not self.groups()['hr_staff']:
            if self.state == 'done' and (today - self.at_date).days >= delay_duration:
                # action['context']['is_readonly'] = True
                # NOTE: Disable the button (action)
                return False

        else:
            action.update({'name': _('Related Leaves')}) 
        return action

    def action_leaves_form(self):
        # Return dynamic action to open leaves form (employee_id)
        self.ensure_one()
        at = self
        domain = [('employee_id', '=', at.employee_id.id)]
        show_ah_leave = self.env.context.get('ah_leave', False)
        # ah_keyword = 'AH for'
        if show_ah_leave:
            domain += [
                ('leave_request_ids.holiday_status_id.is_ah', '=', True), 
                ('leave_request_ids.holiday_status_id.validity_start', '<=', self.at_date),
                ('leave_request_ids.holiday_status_id.validity_stop', '>=', self.at_date)
            ] 
            # domain.append(('leave_request_ids.holiday_status_id.is_ah', '=', True))
        else:
            domain.append(('leave_request_ids.holiday_status_id.is_ah', '=', False))

        return {
            'name': _('Leaves'),
            'res_model': 'hr.leave.cover',
            
            'view_mode': 'list,form',
            'type': 'ir.actions.act_window',
            'domain': domain
        }
    
    @api.model
    def action_get_and_sync_remote_staff_at_request(self, server_url, staff_map, at_date):
        """
            Get and sync remote staff at_request
            staff_map: ('remote_staff_code', 'local_staff_code')
            Autocreate working time request based on actual check in/out due to the backward compartible with Bizone Sync
            !Note: Assuming there will be only 01 wt_request and/or 01 ot_request
            TODO [ ]: When staff come back original office, but HR still not update (delete) his/her remote straff code. Should stop creating 
            WT request.
        """
        api_uri = f'{server_url}/at_request/{staff_map[0]}/{at_date}'
        response = requests.get(api_uri, timeout=120)
        if response.status_code == 200:
            r = response.json()
            at = self.search([('at_date', '=', at_date), ('employee_id.code', '=', staff_map[1])])
            ot_holiday_line = self.env['hr.attendance.ot.holiday.line'].search([('at_date', '=', at_date), ('employee_id.code', '=', staff_map[1])])
            ot_hol_line_update = False
            local_employee = self.env['hr.employee'].search([('code', '=', staff_map[1])])

            if not at:
                return False

            if not ot_holiday_line and r['ot_holiday']:
                self.env['hr.attendance.ot.holiday'].generate_monthly_record(employee_id=at.employee_id, at_year=at.at_year, at_month=at.at_month)
                ot_holiday_line = self.env['hr.attendance.ot.holiday.line'].search([('at_date', '=', at_date), ('employee_id.code', '=', staff_map[1])])
                
            if ot_holiday_line and r['ot_holiday']:
                ot_register = r['ot_holiday'][0].get('ot_register', False)
                if ot_register and any(e['request_type'] == 'over_time' for e in r['at_requests']):
                    ot_hol_line_update = {
                        'ot_register': True,
                        'ot_detail': r['ot_holiday'][0].get('ot_detail', ''),
                        'ot_refuse': r['ot_holiday'][0].get('ot_refuse', ''),
                        'state': r['ot_holiday'][0].get('state', '')
                    }

            new_request = []
            bizone_tag = 'BZ'
            # This wt_request only exist if there in no wt_request from staff
            bz_wt_request = at.at_request_ids.filtered(lambda e: e.request_type == 'working_time' and e.name == bizone_tag)

            # Process refused requests first so an active remote OT request wins when both map to the single local OT request
            for n in sorted(r['at_requests'], key=lambda e: e.get('state') != 'refuse'):
                current_request = at.at_request_ids.filtered(lambda e: n['name'] == e.name)
                if current_request:
                    # Update current_request state
                    current_request.state = n['state']
                    if current_request.request_type == 'working_time':
                        if all([at.check_in, at.compute_in]):
                            current_request.request_in = at.check_in
                        if all([at.check_out, at.compute_out]):
                            current_request.request_out = at.check_out
                else:
                    n['at_id'] = at.id
                    n['sub_request_type_id'] = self.env['hr.attendance.request.type'].search([('code', '=', n['sub_request_code'])]).id
                    n['request_in'] = datetime.datetime.strptime(n['request_in'], '%Y-%m-%d %H:%M') if n['request_in'] else False
                    n['request_out'] = datetime.datetime.strptime(n['request_out'], '%Y-%m-%d %H:%M') if n['request_out'] else False

                    if n['request_type'] == 'working_time':
                        if bz_wt_request:
                            # update bz_wt_request
                            bz_wt_request.name = n['name']
                            bz_wt_request.sub_request_type_id = self.env['hr.attendance.request.type'].search([('code', '=', n['sub_request_code'])]).id
                            bz_wt_request.request_in = n['request_in'] or bz_wt_request.request_in  # already parsed above
                            bz_wt_request.request_out = n['request_out'] or bz_wt_request.request_out
                            bz_wt_request.state = n['state']
                        else:
                            # update the request to include check in/out time
                            n['request_in'] = n['request_in'] or at.check_in
                            n['request_out'] = n['request_out'] or at.check_out
                            new_request.append(n)
                    elif n['request_type'] == 'over_time' and at.at_request_ids.filtered(lambda e: e.request_type == 'over_time'):
                        # Only 01 OT request per attendance: remote name changed (or a new OT replaced a refused one)
                        # => update the existing local OT request instead of creating a duplicate
                        local_ot = at.at_request_ids.filtered(lambda e: e.request_type == 'over_time').sorted('id', reverse=True)[:1]
                        local_ot.write({
                            'name': n['name'],
                            'sub_request_type_id': n['sub_request_type_id'],
                            'request_in': n['request_in'] or local_ot.request_in,
                            'request_out': n['request_out'] or local_ot.request_out,
                            'state': n['state'],
                        })
                    else:
                        new_request.append(n)

                    if n['request_type'] == 'over_time' and at_date <= fields.Date.context_today(self):
                        at.allow_late_ot = True

            if new_request:
                at.with_context(set_draft=True).at_request_ids = [(0, False, e) for e in new_request]

            # Create bz_wt_request
            # Only create bz_wt if staff check-in/out at remote (not local) server
            if not at.at_request_ids.filtered(lambda e: e.request_type == 'working_time'):
                if any([at.check_in, at.check_out]):
                    new_wt_request = {
                        'at_id': at.id,
                        'request_type': 'working_time',
                        'sub_request_type_id': self.env['hr.attendance.request.type'].search([('request_type', '=', 'working_time'),('code', '=', 'work_out')]).id,
                        'name': bizone_tag,
                        'request_in': at.check_in if not at.check_in_location_id.is_local else False,
                        'request_out': at.check_out if not at.check_out_location_id.is_local else False
                    }
                    if any([new_wt_request['request_in'], new_wt_request['request_out']]):
                        at.at_request_ids = [(0, False, new_wt_request)]

                    bz_wt_request = at.at_request_ids.filtered(lambda e: e.request_type == 'working_time' and e.name == bizone_tag)

            if bz_wt_request:
                # Set state to draft before update request_in and request_out to avoid constraint error
                bz_wt_request.state = 'draft'
                bz_wt_request.request_in = at.check_in
                bz_wt_request.request_out = at.check_out
                bz_wt_request.state = 'done'

            if ot_holiday_line and ot_hol_line_update:
                ot_holiday_line.update(ot_hol_line_update)
                ot_holiday_line.ot_holiday_reg_id.with_context(set_draft=False).sync_ot_request()

            at._onchange_at_requests()

            ##### Leaves #####
            current_leave_covers = at.leave_cover_ids
            for c in r['leave_requests']:
                reason_id = self.env['hr.leave.cover.reason'].search([('code', '=', c['reason_code'])])
                cover = {
                    'employee_id': local_employee.id,
                    'reason_id': reason_id.id,
                    'name': c['name'],
                    'leave_request_ids': [],
                    'state': c['state']
                }
                for h in c['leave_request_ids']:
                    holiday_status_id = self.env['hr.leave.type'].search([('name', '=', h['holiday_status'])])
                    fr_date = datetime.datetime.strptime(h['request_date_from'], '%Y-%m-%d')
                    to_date = datetime.datetime.strptime(h['request_date_to'], '%Y-%m-%d')
                    if holiday_status_id and fr_date and to_date:
                        cover['leave_request_ids'].append((0, False, {
                            'holiday_status_id': holiday_status_id.id,
                            'employee_id': local_employee.id,
                            'request_date_from': fr_date,
                            'date_from': datetime.datetime.combine(fr_date, datetime.time.min),
                            'request_date_to': to_date,
                            'date_to': datetime.datetime.combine(to_date, datetime.time.max),
                            'request_date_from_pm': h['request_date_from_pm'],
                            'request_date_to_am': h['request_date_to_am']
                        }))

                if cover and cover['leave_request_ids']:
                    current_cover = current_leave_covers.sudo().filtered(lambda cur_cover: cur_cover.name == cover['name'])
                    if not current_cover:
                        new_cover = self.env['hr.leave.cover'].sudo().with_context(run_holiday_onchange=True).create(cover)
                        new_cover.action_sync_status()
                    else:
                        current_cover.state = cover['state']
                        current_cover.action_sync_status()
                    at._compute_related_states()

        return False

    @api.depends('employee_id')
    def _compute_ah_leaves_count(self):
        # [X] counting ah leaves for current at month
        for at in self:  # Odoo 19: a form can compute several records of the prefetch batch
            ah_domain = [
                ('employee_id', '=', at.employee_id.id),
                ('holiday_status_id.allocation_type', '!=', 'no'),
                ('holiday_status_id.active', '=', 'True'),
                ('holiday_status_id.is_ah', '=', True),
                ('state', '=', 'validate'),
                ('holiday_status_id.validity_start', '<=', at.at_date),
                ('holiday_status_id.validity_stop', '>=', at.at_date)
            ]

            ah_leaves = self.env['hr.leave.report'].read_group(ah_domain, fields=['number_of_days', 'employee_id'], groupby=['employee_id'])
            ah_mapping = dict([(l['employee_id'][0], l['number_of_days']) for l in ah_leaves])
            at.ah_leaves_count = float_round(ah_mapping.get(at.employee_id.id, 0), precision_digits=2)

    def _compute_on_current_month_at(self):
        today = fields.Date.context_today(self)
        start_date = self.get_start_dt(today, for_month=True)
        # end_date = start_date + relativedelta(months=1)
        # end_date = start_date + relativedelta(months=2, day=1)
        for at in self:
            if today.day >= start_date.day:
                at.on_current_month_at = at.end_date >= start_date
            else:
                at.on_current_month_at = at.end_date >= today

    @api.model
    def _search_on_current_month_at(self, operator, value):
        # TODO [X]: Using at policy for date_start value
        today = fields.Date.context_today(self)
        start_date = self.get_start_dt(today, for_month=True)
        # end_date = start_date + relativedelta(months=1)
        # end_date = start_date + relativedelta(months=2, day=1)
        # company = self.env.user.company_id
        # if not company:
        #     raise UserError(_('User {} should belong to a company to continue!'.format(self.env.user.name)))
        # at_policy = company.at_policy()
        # date_start = at_policy['date_start'] or 0

        domain = []
        if today.day >= start_date.day:
            # domain.append(['end_date', '>=', datetime.date(today.year, today.month, start_date.day)])
            domain.append(['end_date', '>=', start_date])
        else:
            domain.append(['end_date', '>=', today])

        # domain = [('at_date', '>=', start_date), ('at_date', '<', end_date)]

        return domain

    def _compute_view_users_backup(self, employee_id, from_date=None, force_run=False):
        """
            - Compute view_user_ids for a record to allowing users who can see the employee attendance record
            - Use cases: Old managers want to see records of his/her staffs
        """
        emp_ats = self.env['hr.attendance'].sudo().search([('employee_id', '=', employee_id.id)]).with_context(active_test=False)
        for h in employee_id.department_history_ids.sorted('effective_date', reverse=True):
            affected_ats = emp_ats if force_run else emp_ats.filtered(lambda a: a.at_date >= (from_date if from_date else h.effective_date))
            for at in affected_ats:
                manager_ids = []
                if h.department_id.manager_id.user_id:
                    manager_ids.append(h.department_id.manager_id.user_id.id)
                if employee_id.gm_id and employee_id.gm_id.user_id:
                    manager_ids.append(employee_id.gm_id.user_id.id)
                at.view_user_ids = [(6, False, manager_ids)]
                for r in at.at_request_ids:
                    r.view_user_ids = [(6, False, manager_ids)]
                for c in at.leave_cover_ids:
                    c.view_user_ids = [(6, False, manager_ids)]
            emp_ats -= affected_ats

        emp_ats = self.env['hr.attendance'].sudo().search([('employee_id', '=', employee_id.id)]).with_context(active_test=False)
        
        for h in employee_id.department_history_ids.sorted('admin_effv_date', reverse=True):
            affected_ats = emp_ats if force_run else emp_ats.filtered(lambda a: a.at_date >= (from_date if from_date else h.effective_date))
            for at in affected_ats:
                manager_ids = []
                if h.admin_dept_id.manager_id.user_id:
                    manager_ids.append(h.admin_dept_id.manager_id.user_id.id)
                if employee_id.admin_gm_id and employee_id.admin_gm_id.user_id:
                    manager_ids.append(employee_id.admin_gm_id.user_id.id)
                at.view_user_ids = [(6, False, manager_ids)]
                for r in at.at_request_ids:
                    r.view_user_ids = [(6, False, manager_ids)]
                for c in at.leave_cover_ids:
                    c.view_user_ids = [(6, False, manager_ids)]
            emp_ats -= affected_ats

    def _compute_view_users(self, employee_id, from_date=None, force_run=False):
        """
        Compute view_user_ids for a record to allow users who can see the employee attendance records.
        Asked AI to optimize the code, avoiding repeats - hopfully performance
        """

        Attendance = self.env['hr.attendance']
        all_attendances = Attendance.sudo().search([('employee_id', '=', employee_id.id)], order='at_date asc').with_context(active_test=False)

        def assign_view_users(histories, dept_attr, gm_attr, date_field):
            remaining_ats = all_attendances
            for h in sorted(histories, key=lambda d: getattr(d, date_field), reverse=True):
                effective_date = from_date if from_date else getattr(h, date_field)
                if not force_run:
                    affected_ats = remaining_ats.filtered(lambda a: a.at_date >= effective_date)
                else:
                    affected_ats = remaining_ats

                manager_ids = []
                dept = getattr(h, dept_attr, False)
                if dept and dept.manager_id and dept.manager_id.user_id:
                    manager_ids.append(dept.manager_id.user_id.id)

                gm = getattr(employee_id, gm_attr, False)
                if gm and gm.user_id:
                    manager_ids.append(gm.user_id.id)

                for at in affected_ats:
                    at.view_user_ids = [(6, 0, manager_ids)]
                    for r in at.at_request_ids:
                        r.view_user_ids = [(6, 0, manager_ids)]
                    for c in at.leave_cover_ids:
                        c.view_user_ids = [(6, 0, manager_ids)]

                remaining_ats -= affected_ats

        assign_view_users(employee_id.department_history_ids, 'department_id', 'gm_id', 'effective_date')
        assign_view_users(employee_id.department_history_ids, 'admin_dept_id', 'admin_gm_id', 'admin_effv_date')


    def _compute_history_data(self):
        """
            at_date
            return admin_dept_id, area_id, adm_manager_id, adm_gm_id of the employee_id during period including the at_date
        """
        self.ensure_one()
        ref_date = self.at_date
        result = {'effective_date': ref_date, 'admin_dept': None, 'admin_manager': None, 'admin_gm': None}
        if not self.employee_id:
            return result
        admin_dept = self.employee_id.compute_dept_by_date(ref_date=ref_date)
        if admin_dept:
            result['admin_dept'] = admin_dept
            admin_manager = self.employee_id.admin_dept_id.compute_manager_by_date(ref_date=ref_date)
            result['admin_manager'] = admin_manager
            if admin_manager:
                admin_gm = admin_manager.admin_dept_id.compute_manager_by_date(ref_date=ref_date)
                result['admin_gm'] = admin_gm

        print('=====', result, result['admin_dept'].area_id.name)
        return result

    # ===== CONSTRAINS =====
    @api.constrains('check_in', 'check_out', 'employee_id')
    def _check_validity(self):
        """
        - Override to remove constrain of maximum 1 "open" attendance
        - Change to validate check_in, check_out should be on the same day
        """
        if self.env.context.get('kdvn_skip_checkin_check'):
            return   # data import: Odoo 12 already validated the row; the early-in request that moves the day start is imported later
        # hours difference from utc time
        for at in self:
            if at.check_in and at.check_out:
                working_start = at.get_at_date(at.check_in, employee_id=at.employee_id, get_time=True)
                # !NOTE: vn_tz having 7 minutes in the timezone that make compration sometime not
                # correct. Using this trick to convert vn_tz to naive
                working_start = (working_start - relativedelta(hours=utc_diff)).replace(tzinfo=None)
                working_end = working_start + relativedelta(hours=24)

                # NOTE: here check_in using utc time, but working_start using vn_tz timezone
                if not(at.check_in >= working_start and at.check_out < working_end):
                    _logger.warning('===== {} [{} <= {}] [{} > {}]'.format(at.code, working_start, at.check_in, working_end, at.check_out))
                    raise ValidationError(_('check_in ({}) and check_out ({}) of {} must be on the same day (by KDVN definition)'.format(at.check_in, at.check_out, at.code)))

    @api.constrains('approve_manager_id')
    def _check_other_validity(self):
        for at in self:
            if at.approve_manager_id:
                if at.approve_manager_id == at.employee_id or at.approve_manager_id == at.department_id.manager_id:
                    raise ValidationError(_('Please choose someone other than yourself or your section manager for New Approve Manager! REF: {}'.format(at.code)))

    ###### Messaging method - REF: auth_admin_passkey module ######
    
    
    # def prepare_waiting_request_qweb(self, manager):
    #     print('=====', type(manager))
    #     qweb_values = {}
    #     if manager.manager:
    #         if manager.user_id.has_group('kdvn_hr_attendance.group_hr_attendance_section_manager'):
    #             # app_url = self.get_full_url(model_name='hr.attendance', 
    #             #                                menu_id=self.env.ref('hr_attendance.menu_hr_attendance_view_attendances_for_manager').id,
    #             #                                action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_action_for_manager').id)
    #             app_url = self.get_full_url(model_name='hr.attendance', action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_action_for_manager').id)
    #         else:  # GM view
    #             # app_url = self.get_full_url(model_name='hr.attendance', 
    #             #                                menu_id=self.env.ref('hr_attendance.menu_hr_attendance_view_attendances_for_manager_gm').id,
    #             #                                action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_action_for_manager_gm').id)
    #             app_url = self.get_full_url(model_name='hr.attendance', 
    #                                         action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_action_for_manager_gm').id)

    #         man_requests = requests.filtered(lambda r: r.manager_id.id == e.id)
    #         effected_ids = json.loads(man_requests.ats) if man_requests else []
    #         # effected_ats = self.env['hr.attendance'].browse(effected_ids).filtered(lambda r: r.at_date >= date_start).sorted(key='at_date')
    #         effected_ats = self.env['hr.attendance'].browse(effected_ids).filtered('on_current_month_at').sorted(key='at_date')
    #         if effected_ats:
    #             qweb_values = {
    #                 'name': manager.name, 
    #                 'company_id': manager.company_id.id or 1,
    #                 'company_name': manager.company_id.name or '',
    #                 'app_url': app_url,
    #                 'pre': 'Mr.' if manager.sex == 'male' else 'Mrs.' if manager.sex == 'female' else 'Mr/Mrs.',
    #                 'today': fields.Date.context_today(self).strftime('%d-%m-%Y'),
    #                 'now': datetime.datetime.now().astimezone(vn_tz).strftime('%d-%m-%Y %H:%M'),
    #                 'extra_data': [{
    #                     'employee': d.employee_id.name, 
    #                     'section': d.department_id.name,
    #                     'date': d.at_date.strftime('%d-%m-%y'),
    #                     'state': 'Manager' if d.state_id.name == 'Manager Approve' else 'GM' if d.state_id.name == 'GM Approve' else d.state_id.name,
    #                     'at_status': d.status_codes,
    #                     'request_marks': d.request_description,
    #                     'action_approve': d._notify_get_action_link('controller', controller='/attendance/sm_approve')
    #                 } for d in effected_ats]
    #             }
    #         return qweb_values
    #     else:
    #         return qweb_values

    @api.model
    def _send_noti_email(self, manager_ids=[], force_send=False):
        """
            - Helper method to send notification email to section managers and general managers
            - about there waiting for approval request
            - Used in schedule action
            - manager_ids: list of employee_ids (hr.emplyee)
            - [ ]: Add information for OT on Holiday Schedule
        """
        # TODO [X]: move date_start to settings
        # TODO [X]: only notification for current month records
        # Prepare data
        Mail = self.env['mail.mail'].sudo()
        today = fields.Date.context_today(self)
        date_start = self.get_start_dt(today, for_month=True)
        at_year, at_month = self.get_at_year_month(today)
        requests = self.env['hr.attendance.manager.request'].search([('manager_id', 'in', manager_ids)] if manager_ids else [])
        ot_holiday_requests = self.env['hr.attendance.ot.holiday.manager.request'].search([('manager_id', 'in', manager_ids)] if manager_ids else [])
        # OT Warnings
        ots_time_domain = [('at_year', '=', at_year), ('at_month', '=', at_month)]
        ots_warning_domain = [ '|', '|', ('ot_wd_over', '=', True), ('ot_hd_over', '=', True), ('weekly_over', '=', True)]
        ots_manager_domain = ['|', ('admin_manager_id', 'in', manager_ids), ('admin_gm_id', 'in', manager_ids)] if manager_ids else []
        ots_domain = expression.AND([ots_time_domain, ots_warning_domain, ots_manager_domain])
        monthly_ots = self.env['hr.attendance.ot.holiday.summary'].search(ots_domain)
        wd_allow_values_sql = 'SELECT DISTINCT wd_allowed_ot FROM hr_attendance_rule WHERE wd_allowed_ot !=0'
        hd_allow_values_sql = 'SELECT DISTINCT hd_allowed_ot FROM hr_attendance_rule WHERE hd_allowed_ot !=0'
        self.env.cr.execute(wd_allow_values_sql)
        wd_allow_values = [e[0] for e in self.env.cr.fetchall()]
        self.env.cr.execute(hd_allow_values_sql)
        hd_allow_values = [e[0] for e in self.env.cr.fetchall()]
        monthly_ots.filtered(lambda o: o.ot_wd_allow not in wd_allow_values or o.ot_hd_allow not in hd_allow_values).mapped('at_ids')._compute_ot_allow()
        
        if not manager_ids:
            managers = requests.mapped('manager_id') | ot_holiday_requests.mapped('manager_id') | monthly_ots.mapped('employee_id.admin_gm_id') | monthly_ots.mapped('admin_manager_id')
        else:
            managers = self.env['hr.employee'].browse(manager_ids)
        
        for e in managers:
            if e.user_id.has_group('kdvn_hr_attendance.group_hr_attendance_section_manager'):
                app_url = self.get_full_url(model_name='hr.attendance', action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_action_for_manager').id)
            else:  # GM view
                app_url = self.get_full_url(model_name='hr.attendance', 
                                            action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_action_for_manager_gm').id)
            
            ot_holidays_url = self.get_full_url(model_name='hr.attendance.ot.holiday.manager', action_id=self.env.ref('kdvn_hr_attendance.action_hr_attendance_ot_holiday_manager').id)
            ot_warning_url = self.get_full_url(model_name='hr.attendance.ot.holiday.summary', action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_ot_holiday_summary').id)

            man_requests = requests.filtered(lambda r: r.manager_id.id == e.id)
            effected_ids = json.loads(man_requests.ats) if man_requests else []
            effected_ats = self.env['hr.attendance'].browse(effected_ids).filtered(lambda r: r.at_date >= date_start).sorted(key='at_date')

            man_ot_holiday_request = ot_holiday_requests.filtered(lambda r: r.manager_id.id == e.id)
            effected_ot_holiday_line_ids = self.env['hr.attendance.ot.holiday.line'].browse(json.loads(man_ot_holiday_request.othls) if man_ot_holiday_request else [])

            effected_ot_warnings = monthly_ots.filtered(lambda o: o.admin_manager_id.id == e.id or o.admin_gm_id.id == e.id)
            
            if effected_ats or effected_ot_holiday_line_ids or effected_ot_warnings:
                qweb_values = {
                    'name': e.name, 
                    'company_id': e.company_id.id or 1,
                    'company_name': e.company_id.name or '',
                    'app_url': app_url,
                    'ot_holidays_url': ot_holidays_url,
                    'ot_warning_url': ot_warning_url,
                    'pre': 'Mr.' if e.sex == 'male' else 'Mrs.' if e.sex == 'female' else 'Mr/Mrs.',
                    'today': fields.Date.context_today(self).strftime('%d-%m-%Y'),
                    'now': datetime.datetime.now().astimezone(vn_tz).strftime('%H:%M %d-%m-%Y'),
                    'extra_data': [{
                        'employee': d.employee_id.name, 
                        'section': d.department_id.name,
                        'date': d.at_date.strftime('%d-%m-%y'),
                        'state': 'Manager' if d.state_id.name == 'Manager Approve' else 'GM' if d.state_id.name == 'GM Approve' else d.state_id.name,
                        'at_status': d.status_codes,
                        'request_marks': d.request_description,
                        'action_approve': d._notify_get_action_link('controller', controller='/attendance/sm_approve')
                    } for d in effected_ats],
                    'ot_holiday_data': [{
                        'employee': o.employee_id.name,
                        'section': o.employee_id.admin_dept_id.name,
                        'date': o.at_date.strftime('%d-%m-%y'),
                        'state': 'Manager' if o.state == 'waiting_fman' else 'GM' if o.state == 'waiting_fman2' else '',
                        'request_marks': o.ot_detail
                    } for o in effected_ot_holiday_line_ids],
                    'ot_warning': {
                        'employee_ids': effected_ot_warnings.mapped('employee_id')
                    }
                }
                subject = _('Attendance App Notification to %s' % e.name)
                # body_html = self._prepare_noti_email(e, 'kdvn_hr_attendance.noti_email_for_manager', values=qweb_values)
                body_html = self._prepare_noti_email(e, 'kdvn_hr_attendance.combined_noti_email_for_manager', values=qweb_values)

                # Only create email if app_url does NOT contain internal ipaddress
                if self.url_contain_ip(app_url):
                    _logger.warning(_('App URL contains ip address, will NOT process sending email!'))
                    return False
                
                email = Mail.create({
                    'email_to': e.work_email or e.user_id.email or None,
                    'subject': subject,
                    'body_html': body_html,
                    'auto_delete': True
                })

                if force_send:
                    email.send()

    @api.model
    def _send_noti_refuse_email(self, at_ids=[], employee_ids=[], force_send=False, date_start=None):
        """
            - Helper method to send notification email to employees
            - about there refused requests
        """
        Mail = self.env['mail.mail'].sudo()
        if not date_start:
            date_start = self.get_start_dt(a_date=self.env['hr.mixin'].today_vn(), for_month=True)
        domain =[('at_date', '>=', date_start), ('state', '=', 'refuse')]

        if employee_ids:
            domain.append(('employee_id', 'in', employee_ids))

        if at_ids:
            refuse_ats = self.env['hr.attendance'].browse(at_ids)
        else:
            refuse_ats = self.env['hr.attendance'].search(domain)

        for e in refuse_ats.mapped('employee_id'):
            if not e.working:
                continue
            employee_at_url = self.get_full_url(model_name='hr.attendance', 
                                               menu_id=self.env.ref('hr_attendance.menu_hr_attendance_root').id,
                                               action_id=self.env.ref('hr_attendance.hr_attendance_action').id)
            qweb_values = {
                'name': e.name,
                'company_id': e.company_id.id or 1,
                'company_name': e.company_id.name or '',
                'pre':  'Mr.' if e.sex == 'male' else 'Mrs.' if e.sex == 'female' else 'Mr/Mrs.',
                'today': fields.Date.context_today(self).strftime('%d-%m-%Y'),
                'now': datetime.datetime.now().astimezone(vn_tz).strftime('%d-%m-%Y %H:%M'),
                'app_url': employee_at_url,
                'extra_data': [{
                    'employee': at.employee_id.name, 
                    'section': at.department_id.name,
                    'date': at.at_date.strftime('%d-%m-%Y'), 
                    'request_marks': at.request_description,
                    'refuse_marks': at.refuse_comment,
                    'action_open': '#'
                    } for at in refuse_ats.filtered(lambda r: r.employee_id.id == e.id).sorted(key='at_date')]
            }
            subject = _("%s's attendance requests refused." % e.name)
            body_html = self._prepare_noti_email(e, 'kdvn_hr_attendance.noti_email_for_refuse_request', values=qweb_values)
            
            # Only create email if app_url does NOT contain internal ipaddress
            if self.url_contain_ip(employee_at_url):
                _logger.warn(_('App URL contains ip address, will NOT process sending email!'))
                return False
            
            email = Mail.create({
                'email_to': e.work_email or e.user_id.email or None,
                'subject': subject,
                'body_html': body_html,
                'auto_delete': True
            })
            if force_send:
                email.send()

    @api.model
    def _send_noti_states_unsync_email(self, at_ids=[], employee_ids=[], force_send=False, date_start=None):
        """
            - Helper method to send notification email to employees having
            - unsynced states requests (mostly in draft state)
        """
        Mail = self.env['mail.mail'].sudo()
        if not date_start:
            date_start = self.get_start_dt(for_month=True)
        domain =[('at_date', '>=', date_start), ('states_sync', '=', False)]
        if employee_ids:
            domain.append(('employee_id', 'in', employee_ids))
        if at_ids:
            ats = self.env['hr.attendance'].browse(at_ids)
        else:
            ats = self.env['hr.attendance'].search(domain)
        # ats = ats.filtered(lambda r: r.at_date >= start_dt)

        for e in ats.mapped('employee_id'):
            if not e.working:
                continue
            employee_at_url = self.get_full_url(model_name='hr.attendance', 
                                               menu_id=self.env.ref('hr_attendance.menu_hr_attendance_root').id,
                                               action_id=self.env.ref('hr_attendance.hr_attendance_action').id)
            qweb_values = {
                'name': e.name,
                'company_id': e.company_id.id or 1,
                'company_name': e.company_id.name or '',
                'pre':  'Mr.' if e.sex == 'male' else 'Mrs.' if e.sex == 'female' else 'Mr/Mrs.',
                'today': fields.Date.context_today(self).strftime('%d-%m-%Y'),
                'now': datetime.datetime.now().astimezone(vn_tz).strftime('%d-%m-%Y %H:%M'),
                'app_url': employee_at_url,
                'extra_data': [{
                    'employee': at.employee_id.name, 
                    'section': at.department_id.name,
                    'date': at.at_date.strftime('%d-%m-%Y'), 
                    'request_marks': at.request_description,
                    # 'refuse_marks': at.refuse_comment,
                    'action_open': '#'
                    } for at in ats.filtered(lambda r: r.employee_id.id == e.id).sorted(key='at_date')]
            }
            subject = _("%s's States unsynced attendances." % e.name)
            body_html = self._prepare_noti_email(e, 'kdvn_hr_attendance.noti_email_for_states_unsync', values=qweb_values)
            # Only create email if app_url does NOT contain internal ipaddress
            if self.url_contain_ip(employee_at_url):
                _logger.warn(_('App URL contains ip address, will NOT process sending email!'))
                continue
                # return False
            
            
            email = Mail.create({
                'email_to': e.work_email or e.user_id.email or None,
                'subject': subject,
                'body_html': body_html,
                'auto_delete': True
            })
            if force_send:
                email.send()

    @api.model
    def _send_ot_warning_email_to_manager(self, at_year, at_month, force_send=False):
        """
            Method to send ot warning to manager
            - at_date: based date to compute ot warning (weekly and/or monthly)
        """
        Mail = self.env['mail.mail'].sudo()
        def _gen_qweb_values(ots, sm=True):
            """
                Helper method to generate qweb values
                ots: monthly overtime recordsets
                sm: generate for SM otherwise gm
            """
            return {
                'name': m.name,
                'company_id': m.company_id.id or 1,
                'company_name': m.company_id.name or '',
                'pre':  'Mr.' if m.sex == 'male' else 'Mrs.' if m.sex == 'female' else 'Mr/Mrs.',
                'today': fields.Date.context_today(self).strftime('%d-%m-%Y'),
                'now': datetime.datetime.now().astimezone(vn_tz).strftime('%d-%m-%Y %H:%M'),
                'app_url': manager_at_url,
                'extra_data': [{
                    'staff_code': o.employee_id.code,
                    'employee': o.employee_id.name,
                    'location': o.area_id.name,
                    'sm_pm': o.admin_gm_id.name if sm else o.admin_manager_id.name,
                    'wd_allow': o.ot_wd_allow,
                    'hd_allow': o.ot_hd_allow,
                    'wd_used': o.ot_wd,
                    'hd_used': o.ot_hd,
                    'wd_remain': o.ot_wd_remain,
                    'hd_remain': o.ot_hd_remain
                } for o in ots]
            }

        hr_manager = self.env['hr.employee'].search([('job_title', '=', 'HR Manager'),('working', '=', True)], limit=1)
        ots_domain = [('at_year', '=', at_year), ('at_month', '=', at_month), '|', '|', ('ot_wd_over', '=', True), ('ot_hd_over', '=', True), ('weekly_over', '=', True)]
        monthly_ots = self.env['hr.attendance.ot.holiday.summary'].search(ots_domain)
        
        wd_allow_values_sql = 'SELECT DISTINCT wd_allowed_ot FROM hr_attendance_rule WHERE wd_allowed_ot !=0'
        hd_allow_values_sql = 'SELECT DISTINCT hd_allowed_ot FROM hr_attendance_rule WHERE hd_allowed_ot !=0'
        self.env.cr.execute(wd_allow_values_sql)
        wd_allow_values = {r[0] for r in self.env.cr.fetchall()}
        self.env.cr.execute(hd_allow_values_sql)
        hd_allow_values = {r[0] for r in self.env.cr.fetchall()}
        # Re compute ot_allow
        monthly_ots.filtered(lambda o: o.ot_wd_allow not in wd_allow_values or o.ot_hd_allow not in hd_allow_values).mapped('at_ids')._compute_ot_allow()

        pm_ids = set(monthly_ots.mapped('employee_id.admin_gm_id'))
        sm_ids = set(monthly_ots.mapped('admin_manager_id'))

        for (is_sm, m_ids) in enumerate([pm_ids, sm_ids]):
            is_sm = bool(is_sm)
            for m in m_ids:
                manager_field = 'admin_manager_id' if is_sm else 'admin_gm_id'
                sorted_field = 'admin_gm_id' if is_sm else 'admin_manager_id'
                m_ots = monthly_ots.filtered(lambda o: o[manager_field].id == m.id).sorted(key=lambda r: (r[sorted_field].code, r.employee_id.code))
                manager_at_url = self.get_full_url(model_name='hr.attendance', 
                                                menu_id=self.env.ref('hr_attendance.menu_hr_attendance_root').id,
                                                action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_ot_holiday_summary').id)
                qweb_values = _gen_qweb_values(ots=m_ots, sm=is_sm)
                subject = _(f'Overtime warnings of {at_month}-{at_year} need your attention - {m.name}')
                body_html = self._prepare_noti_email(m, 'kdvn_hr_attendance.ot_warning_for_manager', values=qweb_values)
                if self.url_contain_ip(manager_at_url):
                    _logger.warning(_('App URL contains ip address, will NOT process sending email!'))
                    continue

                email = Mail.create({
                    'email_to': m.work_email or m.user_id.email or None,
                    'email_cc': (hr_manager.work_email or hr_manager.user_id.email) if hr_manager else None,
                    'subject': subject,
                    'body_html': body_html,
                    'auto_delete': True
                })
                if force_send:
                    email.send()


    @api.model
    def _prepare_noti_email(self, employee, views_or_xmlid, **kwagrs):
        # [X] TODO: using qweb template to generate body
        # REF: mail.thread's message_post_with_view method
        values = kwagrs.pop('values', None) or dict()
        if isinstance(views_or_xmlid, str):
            views = self.env.ref(views_or_xmlid, raise_if_not_found=False)
        else:
            views = views_or_xmlid

        if views:
            rendered_template = self.env['ir.qweb']._render(views.id, values)
        else:
            return
        return rendered_template

    # @api.multi
    # def _send_noti_email2(self):
    #     self.ensure_one()
    #     self.message_post_with_view('kdvn_hr_attendance.noti_email', values={'extra_data': 'Test'}, author_id=2, email_from='kindenvietnam@gmail.com')


# class KderpHrAttendanceMonthSummary(models.Model):
#     _name = "hr.attendance.month.summary"
#     _description = "KDErp Attendance AT Month summary"

#     employee_id = fields.Many2one('hr.employee', required=True)
#     at_month = fields.Integer(require=True)
#     at_year = fields.Integer(require=True)
#     # AT
#     late_in_count = fields.Float(compute='_compute_count', store=True)
#     early_out_count = fields.Float(compute='_compute_count', store=True)
#     forget_count = fields.Float(compute='_compute_count', store=True)
#     attendance_count = fields.Float(compute='_compute_count', store=True)
#     absence_count = fields.Float(compute='_compute_count', store=True)
#     leaves_count = fields.Float(compute='_compute_count', store=True)
#     oh_count = fields.Float(compute='_compute_count', store=True)
#     sh_count = fields.Float(compute='_compute_count', store=True)
#     working_days_sum = fields.Float(compute='_compute_count', store=True)
#     # OT
#     wd_ot_sum = fields.Float(compute='_compute_count', store=True)
#     wd_st_sum = fields.Float(compute='_compute_count', store=True)
#     hd_ot_sum = fields.Float(compute='_compute_count', store=True)
#     hd_st_sum = fields.Float(compute='_compute_count', store=True)
#     ph_ot_sum = fields.Float(compute='_compute_count', store=True)
#     ph_st_sum = fields.Float(compute='_compute_count', store=True)
#     wd_sum = fields.Float(compute='_compute_count', store=True)
#     hd_sum = fields.Float(compute='_compute_count', store=True)
#     # weekday overtime
#     allow_wd_overtime = fields.Float(compute='_compute_count', store=True)
#     allow_wd_ot = fields.Float(compute='_compute_count', store=True)
#     allow_wd_st = fields.Float(compute='_compute_count', store=True)
#     # holiday overtime
#     allow_hd_overtime = fields.Float(compute='_compute_count', store=True)
#     allow_hd_ot = fields.Float(compute='_compute_count', store=True)
#     allow_hd_st = fields.Float(compute='_compute_count', store=True)
#     allow_ph_ot = fields.Float(compute='_compute_count', store=True)
#     allow_ph_st = fields.Float(compute='_compute_count', store=True)
#     # exceed
#     exceed_wd_overtime = fields.Float(compute='_compute_count', store=True)
#     exceed_hd_overtime = fields.Float(compute='_compute_count', store=True)
#     exceed_ot_to_leave = fields.Float(compute='_compute_count', store=True)
#     exceed_ot_subtitude = fields.Float(compute='_compute_count', store=True)
    
#     at_ids = fields.One2many('hr.attendance', 'summary_id')
#     summary_for_at = fields.Html(compute='_compute_at_monthly_summary')

#     _sql_constraints = [('AT month summary unique', 'unique(employee_id, at_year, at_month)', 'AT month summary unique!')]

#     def _month_ats(self):
#         self.ensure_one()
#         summary = self
#         related_ats_domain = [('employee_id', '=', summary.employee_id.id), ('at_year', '=', summary.at_year), ('at_month', '=', summary.at_month)]
#         return self.env['hr.attendance'].search(related_ats_domain)

#     def _substitute_ats(self):
#         # Return list of ids of allowed (requested) working holidays (holiday, special_holiday, other_holiday and AH)
#         self.ensure_one()
#         summary = self

#         domain = [('employee_id', '=', summary.employee_id.id), ('at_month', '=', summary.at_month), ('at_year', '=', summary.at_year),
#                   ('work_on_holiday', '!=', False), ('request_ot_for', '!=', False),
#                  '|', ('absence', '=', False), ('absence', '!=', 'absence'), 
#                  '|', '|', '|', ('is_holiday', '=', True), ('is_public_holiday', '=', True), ('is_other_holiday', '=', True), ('ah', '!=', False)]
#         sub_ids = self.env['hr.attendance'].search(domain)
#         occupied_ids = self.env['hr.leave'].search([('substitute_for_at_id', 'in', sub_ids.mapped('id'))]).mapped('substitute_for_at_id')
#         aval_ids = sub_ids - occupied_ids

#         if aval_ids:
#             return aval_ids.mapped('id')
#         return False

#     # TODO []: use read_group for better performance
#     @api.depends('employee_id', 'at_month', 'at_year')
#     def _compute_count(self):
#         # return False
#         for summary in self:
#             related_ats = summary._month_ats()

#             # [X][] Performance
#             def _count(at):
#                 res = []
#                 status = at.status_ids.mapped('code')
#                 res.extend([int(at.late_in), int(at.early_out), at.wd_ot, at.wd_st, at.hd_ot, at.hd_st, at.ph_ot, at.ph_st])
#                 # forget check_in, check_out
#                 res.append(sum(['forget_in' in at.at_request_ids.mapped('sub_request_type_id.code'), 'forget_out' in at.at_request_ids.mapped('sub_request_type_id.code')]))
#                 for keys in [
#                     ('1/2 O', 'O'), ('1/2 X', 'X'), ('1/2 L', 'L'), ('1/2 OH', 'OH'), ('1/2 SH', 'SH')
#                 ]:
#                     res.append(0.5 if keys[0] in status else 1 if keys[1] in status else 0)
#                 return res

#             def _count_allow(actual_list, allow_number):
#                 """
#                     return a list of number matched with actual_list to make sure 
#                     the total number of return list equal to allow_number
#                 """
#                 res = []
#                 if sum(actual_list) <= allow_number:
#                     res = actual_list
#                 else:
#                     # REF: https://stackoverflow.com/questions/3705670/best-way-to-create-a-reversed-list-in-python
#                     # reverse a list 
#                     for n in actual_list[::-1]:
#                         if n >= allow_number - sum(res):
#                             res.append(allow_number - sum(res))
#                         else:
#                             res.append(n)
#                     res.reverse()
#                 return res

#             # unzip result into variables
#             # REF: https://stackoverflow.com/questions/3972872/python-variables-as-keys-to-dict
#             (late_in_count, early_out_count, wd_ot_sum, wd_st_sum, hd_ot_sum, hd_st_sum, ph_ot_sum, ph_st_sum, forget_count,
#                 attendance_count, absence_count, leaves_count, oh_count, sh_count) = zip(*related_ats.mapped(_count))
#             key_list = ['late_in_count', 'early_out_count', 'wd_ot_sum', 'wd_st_sum', 'hd_ot_sum', 'hd_st_sum', 'ph_ot_sum', 'ph_st_sum', 'forget_count',
#                         'attendance_count', 'absence_count', 'leaves_count', 'oh_count', 'sh_count']
#             loc = locals()
#             counts = {k : sum(loc[k]) for k in key_list}

#             # overtime sum
#             counts['wd_sum'] = counts['wd_ot_sum'] + counts['wd_st_sum']
#             counts['hd_sum'] = counts['hd_ot_sum'] + counts['hd_st_sum'] + counts['ph_ot_sum'] + counts['ph_st_sum']

#             # total working days
#             at0 = related_ats[0]
#             start_dt = datetime.datetime.combine(at0.start_date, datetime.time.min, tzinfo=vn_tz)
#             # end_dt should be the day of 20
#             end_dt = datetime.datetime.combine(at0.end_date - datetime.timedelta(days=1), datetime.time.max, tzinfo=vn_tz)
#             work_intervals = at0.employee_id.resource_calendar_id._work_intervals(start_dt, end_dt)
#             working_days_sum = (len(work_intervals) / 2) - 2
#             counts['working_days_sum'] = working_days_sum

#             # allow overtime
#             at_rules = at0._at_rules()
#             counts['allow_wd_overtime'] = at_rules.get('wd_allowed_ot', 0)
#             counts['allow_hd_overtime'] = at_rules.get('hd_allowed_ot', 0)
#             if counts['allow_wd_overtime'] > 0:
#                 (counts['allow_wd_ot'], counts['allow_wd_st']) = _count_allow([counts['wd_ot_sum'], counts['wd_st_sum']], counts['allow_wd_overtime'])
#                 (counts['allow_hd_ot'], counts['allow_hd_st'], counts['allow_ph_ot'], counts['allow_ph_st']) = _count_allow([counts['hd_ot_sum'], counts['hd_st_sum'], counts['ph_ot_sum'], counts['ph_st_sum']], counts['allow_hd_overtime'])

#             # exceed overtime
#             counts['exceed_wd_overtime'] = 0 if counts['wd_sum'] <= counts['allow_wd_overtime'] else counts['wd_sum'] - counts['allow_wd_overtime']
#             counts['exceed_hd_overtime'] = 0 if counts['hd_sum'] <= counts['allow_hd_overtime'] else counts['hd_sum'] - counts['allow_hd_overtime']

#             # exceed OT to leaves
#             exceed_hours = counts['exceed_wd_overtime'] + counts['exceed_hd_overtime']
#             if exceed_hours > 0:
#                 counts['exceed_ot_to_leave'] = roundPartial(exceed_hours, 0.5)
#             else:
#                 counts['exceed_ot_to_leave'] = 0
            
#             counts['exceed_ot_subtitude'] = roundPartial(counts['exceed_ot_to_leave'] / 8, 0.5, False)

#             # TODO []: Validate some key number based on company policy
#             # forget_count <= 1 for a month
#             # if counts['forget_count'] > 1:
#                 # raise UserError(_('{} can NOT have more than {} forget check_in|check_out in a month. Please consider change your request!'.format(self.employee_id.name, 1)))

#             summary.update(counts)

#     def _compute_at_monthly_summary(self):
#         view = self.env.ref('kdvn_hr_attendance.at_monthly_summary')
#         for s in self:
#             values = {'monthly_summary': []}
#             categories = [
#                 {'category': 'AT', 'fields': ['late_in_count', 'early_out_count', 'forget_count', 'attendance_count', 'absence_count', 'leaves_count', 'oh_count', 'sh_count', 'working_days_sum']},
#                 {'category': 'OT', 'fields': ['wt_ot_sum', 'wd_st_sum', 'hd_ot_sum', 'hd_st_sum', 'ph_ot_sum', 'ph_st_sum', 'wd_sum', 'hd_sum']},
#                 {'category': 'Allow WD', 'fields': ['allow_wd_overtime', 'allow_wd_ot', 'allow_wd_st']},
#                 {'category': 'Allow HD', 'fields': ['allow_hd_overtime', 'allow_hd_ot', 'allow_hd_st', 'allow_ph_ot', 'allow_ph_st']},
#                 {'category': 'Exceed', 'fields': ['exceed_wd_overtime', 'exceed_hd_overtime', 'exceed_ot_to_leave', 'exceed_ot_subtitude']}
#             ]
#             for c in categories:
#                 for f in c['fields']:
#                     if f in s:
#                         values['monthly_summary'].append({'category': c['category'], 'field': s.fields_get()[f]['string'], 'value': s[f]})
#             html = view.render(values, engine='ir.qweb')
#             s.summary_for_at = html


