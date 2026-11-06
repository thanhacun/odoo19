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
try:
    import pyodbc  # SQL Server (bizone) link: stage E, not in the Odoo 19 image
except ImportError:
    pyodbc = None
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



class KderpHrAttendanceRequestType(models.Model):
    _name = 'hr.attendance.request.type'
    _description = 'HR Attendance Request Type'
    _order = 'sequence'

    name = fields.Char(string='Description')
    code = fields.Char(string='Request code')
    request_type = fields.Selection([
        ('working_time', 'Working time'),
        ('over_time', 'Over time')
    ], required=True)
    need_description = fields.Boolean(default=False)
    auto_in_out = fields.Selection([
        ('in', 'Auto check_in'),
        ('out', 'Auto check_out'),
        ('both', 'Auto in-out')
    ], default=False)
    sequence = fields.Integer()
    active = fields.Boolean(default=True)


class KderpHrAttendanceRequest(models.Model):
    _name = 'hr.attendance.request'
    _inherit = ['hr.mixin']
    _description = 'KD HR attendance related request: Working and Overtime'

    at_id = fields.Many2one('hr.attendance', context={'active_test': False}, index=True)
    employee_id = fields.Many2one('hr.employee', related='at_id.employee_id', store=True)
    department_id = fields.Many2one('hr.department', related='at_id.department_id', store=True)
    name = fields.Char()
    description = fields.Char(compute='_compute_description')
    request_type = fields.Selection([
        ('working_time', 'Working time'),
        ('over_time', 'Over time')
    ], required=True, string="Type")
    # [X] TODO: Should combine OT type here?
    sub_request_type_id = fields.Many2one('hr.attendance.request.type', string="Sub. Type")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_fman', 'Manager Approve'),
        ('waiting_fhr', 'HR Validate'),
        ('waiting_fman2', 'GM Approve'),
        ('done', 'Done'),
        ('refuse', 'Refuse')
    ], default='draft')

    request_in = fields.Datetime()
    request_out = fields.Datetime()
    batch_id = fields.Char(help="Unique number for requests that created in multimode", default=False)
    early_offset = fields.Integer(default=0, help="Number of minutes check_in early")  # Early offset for single attendance
    # Estimated OT hour
    estimate_ot = fields.Float(compute='_compute_estimate_ot', store='True', readonly=True)
    estimate_ot_dsp = fields.Char(compute='_compute_estimate_ot', store='True', string="Estimate OT", readonly=True)
    out_by_reg = fields.Boolean('Out by register', help="Only by HR Admin", default=False)
    include_absence_hour = fields.Boolean('Include absence hours', help="Only by HR Admin: allow calculating absence hours", default=False)
    # view users
    # Update query:
    # INSERT INTO hr_attendance_request_res_users_rel (hr_attendance_request_id, res_users_id)
    #   SELECT hr.id hr_attendance_request_id, user_id.res_users_id res_users_id
    #       FROM hr_attendance_res_users_rel user_id
	#       JOIN hr_attendance_request hr ON user_id.hr_attendance_id=hr.at_id
    view_user_ids = fields.Many2many('res.users', string="View users", readonly=True)  # data will update in create method (and maybe at_id depends method)

    def name_get(self):
        res = []
        for r in self:
            res.append((r.id, r.description))
        return res

    def _compute_description(self):
        # description_size = self.env.user.company_id.description_size or 25
        for r in self:
            description = ''
            # new_name = False
            # if r.name and len(r.name) > description_size:
            #     new_name = r.name[0:description_size]
            if r.request_type == 'working_time':
                wt_in = (r.request_in + relativedelta(hours=utc_diff)).strftime('%H:%M') if r.request_in else ''
                wt_out = (r.request_out + relativedelta(hours=utc_diff)).strftime('%H:%M') if r.request_out else ''
                if r.sub_request_type_id.code == 'early_in':
                    wt_in = (self.get_at_datetime(r.at_id.at_date) + relativedelta(hours=utc_diff, minutes=-r.early_offset)).strftime('%H:%M') if r.at_id else ''
                wt_time = ' - '.join([e for e in [wt_in, wt_out] if e])
                wt_request = ' [{}]'.format(wt_time) if (r.state not in ['waiting_fhr', 'done'] or r.name == 'BZ') else ''
                description = 'W: {}{}'.format(r.name if r.name else r.sub_request_type_id.name, wt_request)
            elif r.request_type == 'over_time':
                sub_leave = self.env['hr.leave'].search([('substitute_for_at_id', '=', r.at_id.id or 0)])  # Note the use of 0 here to prevent using False value
                if not sub_leave or (sub_leave and sub_leave.substitute_period):
                    # period = ' (AM)' if r.sub_request_type_id.code == 'am' else ' (PM)' if r.sub_request_type_id.code == 'pm' else ''
                    ot_in = r.request_in.astimezone(vn_tz).strftime('%H:%M') if r.request_in else ''
                    ot_out = r.request_out.astimezone(vn_tz).strftime('%H:%M') if r.request_out else ''
                    ot_time = ot_in if r.sub_request_type_id.code == 'am' else ot_out if r.sub_request_type_id.code == 'pm' else '{} - {}'.format(ot_in, ot_out)
                    ot_estimate = ' [Est.: ' + str(r.estimate_ot) + ' hrs]' if r.state not in ['waiting_fhr', 'done'] else ''
                    description = 'O: ({}): {}{}'.format(ot_time, r.name, ot_estimate)
            r.description = description

    def _compute_other_related_records(self):
        for r in self:
            other_requests = self.search([('at_id', '=', r.at_id.id), ('id', '!=', r.id)])
    
    # @api.depends('state', 'sub_request_type_id', 'request_in', 'request_out')
    # update will be handled in write, create method
    def _compute_estimate_ot(self):
        for r in self:
            estimate_ot, estimate_ot_dsp = (0, None)
            if r.request_type == 'over_time':
                estimate_hour = r.at_id._compute_ot_hour(estimate=True)
                estimate_ot = sum([item[1] for item in estimate_hour.items() if item[0] not in ['ot_am', 'ot_pm', 'ot_wd', 'ot_hd', 'ot_total']])
                estimate_ot_dsp = ', '.join([': '.join(map(str, item)) for item in estimate_hour.items() if item[0] not in ['ot_am', 'ot_pm', 'ot_wd', 'ot_hd', 'ot_total'] and item[1] > 0])
                estimate_ot_dsp = re.sub(r'\D{3}ot', 'OT' , estimate_ot_dsp)
                estimate_ot_dsp = re.sub(r'\D{3}st', 'ST' , estimate_ot_dsp)

            r.update({'estimate_ot': estimate_ot, 'estimate_ot_dsp': estimate_ot_dsp})
            r.at_id.update({'e_ot_am': estimate_hour['ot_am'], 'e_ot_pm': estimate_hour['ot_pm']})

    @api.depends('at_id')
    def compute_view_users(self):
        # !NOTE: check if this method is a need?
        for r in self:
            r.view_user_ids = [(6, False, r.at_id.view_user_ids.mapped('id'))] if r.at_id else False
    
    # ===== APIs =====
    def action_submit(self):
        for r in self:
            if r.state == 'draft':
                r.state = 'waiting_fman'
                # r.at_id._compute_related_states()

    def action_approve(self):
        self.filtered(lambda r: r.state == 'waiting_fman').write({'state': 'waiting_fhr'})
        # for r in self:
        #     if r.state == 'waiting_fman':
        #         r.state = 'waiting_fhr'
                # r.at_id._compute_related_states()

    # @api.multi
    # def action_validate(self):
    #     super().action_validate()
        # for r in self:
        #     r.at_id._compute_related_states()

    def action_approve_man2(self):
        # if any([r.state != 'waiting_fman2' for r in self]):
        #     raise UserError(_('All recores must be in [GM Approve] state to proceed!'))
        self.filtered(lambda r: r.state == 'waiting_fman2').write({'state': 'done'})
        # self.at_id._compute_related_states()

    def action_revise_backup(self):
        for r in self:
            if r.state != 'draft':
                if r.state in ['refuse', 'waiting_fman']:
                    r.state = 'draft'
                    # r.at_id._compute_related_states()
                if r.state != 'refuse' and r.at_id._groups().get('hr_manager', False):
                    r.state = 'draft'
                    # r.at_id._compute_related_states()

    def action_open_wt_request(self):
        self.ensure_one()
        if self.at_id:
            return self.at_id.action_wt_request()
        else:
            return False

    def action_open_ot_request(self):
        self.ensure_one()
        if self.at_id:
            return self.at_id.action_ot_request()
        else:
            return False
    
    # ===== CRUD =====
    @api.model
    def create(self, values):
        self.env['hr.attendance'].clear_at_rules_memo()
        request_ids = super().create(values)
        self.env['hr.attendance'].clear_at_rules_memo()
        # effected_at_ids = request_ids.filtered(lambda r: r.state != 'draft').mapped('at_id')
        # effected_at_ids.with_context(do_not_run_at_status=True)._compute_related_states()
        # effected_at_ids._onchange_at_requests()
        
        # Submit draft request for better user experience
        for r in request_ids:
            if r.request_type == 'over_time':
                r._compute_estimate_ot()
            if r.state == 'draft' and not self.env.context.get('set_draft', False):
                r.action_submit()
                # self.env.user.notify_success(message='You just created a request')
                # r.employee_id.sudo().parent_id.user_id.notify_danger(message='Please update the UI.')
            
            # Update view_user_ids
            # Avoid using r.at_id
            r.update_view_users_by_model()
            # view_employee_ids = [r.employee_id.parent_id, r.employee_id.admin_manager_id, r.employee_id.gm_id, r.employee_id.admin_gm_id]
            # user_ids = [e.user_id.id for e in view_employee_ids if e.user_id]
            # r.view_user_ids = [(6, False, user_ids)]
            # r.view_user_ids = [(6, False, r.at_id.view_user_ids.mapped('id'))]
        return request_ids

    def write(self, values):
        self.env['hr.attendance'].clear_at_rules_memo()
        result = super().write(values)
        self.env['hr.attendance'].clear_at_rules_memo()
        # if any([values.get('request_in'), values.get('request_out')] or self.name != values.get('name')):
        #     effected_at_ids._compute_request_description()

        if 'state' in values:
            states = dict(self.env['hr.attendance.request']._fields['state'].selection)
            request_types = dict(self.env['hr.attendance.request']._fields['request_type'].selection)
            # Logging change to hr.attendance chatter
            for r in self:
                if r.at_id:
                    r.at_id.message_post(body=f'**{request_types[r.request_type]}** request **state** changes to {[states[r.state]]} by {r.write_uid.name}')

            effected_at_ids = self.mapped('at_id')
            effected_at_ids.with_context(do_not_run_at_status=True)._compute_related_states()
            effected_at_ids._onchange_at_requests()
            # CHECK: set do_not_run_at_status=True here will prevent at records update its attendance status
            # effected_at_ids.with_context(do_not_run_at_status=True)._onchange_at_requests()
            
            if values.get('state', '') in ['draft', 'waiting_fman']:
                for r in self:
                    # !NOTE: seems not good
                    # r.employee_id.sudo().parent_id.user_id.notify_danger(message='Please update the UI!')
                    if r.request_type == 'over_time':
                        if r.at_id.ot_total:
                            r.at_id._compute_ot_request()
                        r._compute_estimate_ot()

            # Update check in, out for early case
            if values.get('state', '') in ['waiting_fhr', 'done', 'refuse']:
                # Multiple records case
                for r in self:
                # for r in self.filtered(lambda e: e.sub_request_type_id.code == 'early_in'):
                    if r.sub_request_type_id.code == 'early_in' and r.state == 'waiting_fhr':
                        at_date = r.at_id.at_date - relativedelta(days=1) if r.at_id else False # need to update back one day to correct check out late
                        if at_date:
                            self.env['hr.attendance.raw'].sudo()._get_raw_data(at_date=at_date, duration=1, employee_ids=[r.employee_id.id])
                            self.env['hr.attendance.raw'].sudo()._sync_attendance_record(at_date=at_date, duration=1, employee_ids=[r.employee_id.id])
                    if r.request_type == 'over_time':
                        r._compute_estimate_ot()
            
        elif any(k in values for k in ['sub_request_type_id', 'request_in', 'request_out']):
            for r in self:
                if r.request_type == 'over_time':
                    r._compute_estimate_ot()
        
        # if any(k in values for k in ['state', 'sub_request_type_id', 'request_in', 'request_out']):
        #     for r in self:
        #         if r.request_type == 'over_time':
        #             if r.state in ['waiting_fhr', 'done']:
        #                 r.at_id._compute_ot_request()
        #             else:
        #                 r._compute_estimate_ot()
        else:
            pass

        return result

    def unlink(self):
        self.env['hr.attendance'].clear_at_rules_memo()
        allowed_ids = self.filtered(lambda r: r.state == 'draft')
        if allowed_ids < self:
            _logger.warning(_('Can delete only [Draft] requests! REF: {}'.format((self & allowed_ids).mapped('id'))))
        effected_at_ids = self.env['hr.attendance'].browse(allowed_ids.mapped('at_id.id'))
        for r in allowed_ids:
            if r.request_type == 'over_time':
                # update related attendance record estimate ots
                r.at_id.e_ot_am = r.at_id.e_ot_pm = 0
        result = super().unlink()
        effected_at_ids._compute_related_states()
        effected_at_ids._onchange_at_requests()
        return result

    def _request_cutoffs(self):
        """(ot_before, wt_before, days_before) of this request (RQ-05): latest moment (naive Vietnam time) to register OT / WT for
        the attendance day, and how many days ahead OT may be requested. Holidays, last 2 Saturdays and AH days close one day
        earlier and may be requested up to 7 days ahead."""
        self.ensure_one()
        at_policy = self.env.user.company_id.at_policy()
        at_date = self.at_id.at_date
        is_holiday = self.at_id._is_holiday(at_date)
        is_last_2_sat = False
        if not is_holiday and at_date.weekday() == 5:
            is_last_2_sat = self.in_last_half_month(at_date)
        is_ah = False
        if not is_holiday and not is_last_2_sat:
            is_ah = self.at_id.ah
        mixin = self.env['hr.mixin']
        ot_before = mixin.request_cutoff(at_policy['ot_request_before'], at_date)
        wt_before = mixin.request_cutoff(at_policy['wt_request_before'], at_date)
        days_before = 2
        if ot_before and any([is_holiday, is_last_2_sat, is_ah]):
            ot_before = ot_before - relativedelta(days=1)
            days_before = 7
        return ot_before, wt_before, days_before

    # ===== CONSTRAINS =====
    @api.constrains('early_offset')
    def _check_early_offset_limit(self):
        limit = self.env.user.company_id.at_policy()['early_offset_max']
        for r in self:
            if not 0 <= r.early_offset <= limit:
                raise ValidationError(_('Early check-in must be between 0 and %s minutes (Settings > Attendance).') % limit)

    @api.constrains('at_id', 'state', 'request_type', 'sub_request_type_id', 'request_in', 'request_out')
    def _validate_at_requests(self):
        at_policy = self.env.user.company_id.at_policy()
        delay_duration = at_policy['delay_duration'] if self.env.user.company_id else 2
        today = fields.Date.context_today(self)

        for r in self:
            is_admin_staff = self.env.uid in [1, 2] or self.groups()['hr_staff']
            # No request allowed after delay_duration days
            if r.at_id and r.at_id.state == 'done' and (today - r.at_id.at_date).days >= delay_duration:
                # TODO [X]: allow in set draft cases
                allowed_cases = is_admin_staff or (r.at_id.allow_late_ot and r.request_type == 'over_time')
                if not allowed_cases:
                    raise ValidationError(_('Request in [Done] state and already over {} days. Please contact HR!'.format(delay_duration)))

            if r.state in ['draft', 'waiting_fman'] and r.at_id.state_id.code == 'done' and r.at_id.data_enough:
                # TODO [X]: allow in set draft cases
                if not is_admin_staff:
                    raise ValidationError(_('Requests state not in sync with Attendance state! Affected at record: {}'.format(r.at_id.code)))
            # Working time request should have at least 01 check_in or check_out EXCEPT for early_in request
            is_early_in = r.sub_request_type_id.code == 'early_in'
            has_no_times = not r.request_in and not r.request_out
            is_not_draft = r.state != 'draft'
            if not is_early_in and has_no_times and is_not_draft:
                raise ValidationError(_('WT/OT Request should have either request_in or request_out! REF {}'.format(r.at_id.code)))

            # Maximum 2 working time requests and 01 overtime request
            domain = [('at_id', '=', r.at_id.id), ('id', '!=', r.id)]
            other_requests = self.env['hr.attendance.request'].search(domain)
            if other_requests:
                if r.request_type == 'working_time':
                    if len(other_requests.filtered(lambda r: r.request_type == 'working_time')) > 1:
                        raise ValidationError(_('You cannot have more than 02 working time requests!'))
                    if len(other_requests.filtered(lambda r: r.request_type == 'over_time')) > 1:
                        raise ValidationError(_('You cannot have more than 01 overtime request!'))
                if r.request_type == 'over_time':
                    if len(other_requests.filtered(lambda r: r.request_type == 'working_time')) > 2:
                        raise ValidationError(_('You cannot have more than 02 working time requests!'))

            # One month, one forget only
            if r.at_id and r.request_type == 'working_time' and r.sub_request_type_id.code in ('forget_in', 'forget_out'):
                if self.env.uid != 1:  # Allowing OdooBot to bypass the rule to fix some error
                    if r.at_id.sudo().summary_id and r.at_id.sudo().summary_id['forget_count'] > 1:
                        raise ValidationError(_('Cannot have more than 01 forget request!'))
                    if r.batch_id:  # Create request in Multiple mode can bypass the rule (WHY?)
                        domain = [('id', '!=', r.id), ('batch_id', '=', r.batch_id), ('sub_request_type_id.code', 'in', ('forget_in', 'forget_out'))]
                        forget_requests = r.search(domain)
                        if forget_requests and forget_requests.filtered(lambda e: e.at_id.at_month == r.at_id.at_month and e.at_id.at_year == r.at_id.at_year):
                            raise ValidationError(_('Cannot have more than 01 forget request!'))

            # NO OT request for G8 employees and employees in NO Overtime Rule
            if r.request_type == 'over_time' and not r.at_id.ot_apply:
                raise ValidationError(_('You are not allowed to register OT! Please contact HR for more detail.'))
            
            # NOTE: do NOT reject WT requests whose request_in/request_out equal check_in/check_out. The remote sync
            # creates such requests on purpose (name 'BZ', see bizone_tag in the sync), and at_monthly_workingtime.ods reads them.

            # Not allowing morning OT request defined by AT rules
            at_rules = self.env['hr.attendance']._at_rules(r.employee_id.id, r.at_id.at_date)
            if r.request_type == 'over_time' and (r.sub_request_type_id.code == 'am' or r.sub_request_type_id.code == 'both') and not at_rules['allow_morning_ot']:
                raise ValidationError(_(f'You are not allowed to register morning OT - Plase contact HR for more detail! REF.: {r.at_id.code}'))
            
            
            # Not allowing user to register OT and/or WT request after time defined by AT policy: - 2 days
            # EXECPTION: should allow ot request to be created by admin_user for OT ON Holidays. These requests may be ahead of time nearly a month.
            # [X]: Exploit state == 'draft'
            # !NOTE: be very careful with timezone
            if r.state in ["waiting_fman"]:
                ot_before, wt_before, days_before = r._request_cutoffs()

                if not r.at_id.allow_late_ot and r.request_type == 'over_time' and ot_before and datetime.datetime.now().astimezone(vn_tz).replace(tzinfo=None) > ot_before and r.create_date.astimezone(vn_tz).replace(tzinfo=None) > ot_before:
                    raise ValidationError(_(f'You can NOT request Over Time after [{ot_before.strftime("%d-%h-%Y %H:%M")}] - Please contact HR for instruction!'))
                
                if r.request_type == 'working_time' and wt_before and datetime.datetime.now().astimezone(vn_tz).replace(tzinfo=None) > wt_before and r.create_date.astimezone(vn_tz).replace(tzinfo=None) > wt_before:
                    raise ValidationError(_(f'You can NOT request Working Time after [{wt_before.strftime("%d-%h-%Y %H:%M")}] - Please contact HR for instruction!'))

                # OT request no further than 7 days for request OT for holidays
                set_draft_context = r.env.context.get('set_draft', False)
                if r.request_type == 'over_time' and r.at_id and (r.at_id.at_date - relativedelta(days=days_before)) >= fields.Date.context_today(self):
                    if not set_draft_context:
                        raise ValidationError(_(f'Please only request Overtime no further than {days_before} days from today!'))
                
                # OT request: NOT allow if at_date is in OT Holidays and DO NOT have any linked OT Holiday line record which state is not 'done'
                if r.request_type == 'over_time' and r.at_id.at_date in r.get_ot_holidays(r.at_id.at_date, employee_id=r.employee_id):
                    # - Case 1: last 2 sats and NO more AH => OT as normal working day
                    # - Case 2: last 2 sats and having 1/2 AH
                    # - Case 3: last 2 sats and having 1 AH
                    # - Case 4: last 2 sats and having 1 1/2 AH
                    ot_holiday_line_domain = [
                        ('employee_id', '=', r.employee_id.id), ('at_date', '=', r.at_id.at_date),
                        ('state', '=', 'done'),
                    ]
                    ot_holiday_line = self.env['hr.attendance.ot.holiday.line'].search(ot_holiday_line_domain)

                    # !NOTE: Need to check carefully the compute for OT on a SAT as a normal day => causing total OT for a SAT tobe 8 hours
                    ot_on_sat_as_normal_day = False
                    if r.at_id.at_date.weekday() == 5:
                        is_last_sat = (r.at_id.at_date + relativedelta(days=7)) not in r.get_ot_holidays(r.at_id.at_date, employee_id=r.employee_id)
                        ah_lt_domain = [('is_ah', '=', True), ('validity_start', '<=', r.at_id.at_date), ('validity_stop', '>=', r.at_id.at_date)]
                        ah_lt = self.env['hr.leave.type'].sudo().with_context(active_test=False).search(ah_lt_domain)
                        ah_al = self.env['hr.leave.allocation'].sudo().with_context(active_test=False).search([('employee_id', '=', r.employee_id.id), ('holiday_status_id', '=', ah_lt.id if ah_lt else False), ('state', '=', 'validate')])
                        # Shoud only apply when the employee have to work for at-least 2 SATs
                        ot_on_sat_as_normal_day = True if (ah_al and (ah_lt.virtual_remaining_leaves == 0 or (not is_last_sat and ah_lt.virtual_remaining_leaves <= 1))) else False

                    # !NOTE: need to review
                    if not ot_holiday_line and not ot_on_sat_as_normal_day:
                        _logger.error(_(f'You can NOT request OT on holidays without register for the OT schedule in advance! Please contact HR for instruction! REF: {r.at_id.code}'))
                        raise ValidationError(_(f'You can NOT request OT on holidays without register for the OT schedule in advance! Please contact HR for instruction! REF: {r.at_id.code}'))
    
    @api.constrains('name')
    def _validate_description_size(self):
        """
            - We want to limit the description not too long
            - Base on setting: description_size
            - !NOTE: only apply for WT requests
        """
        description_size = self.env.user.company_id.description_size or 25
        for r in self:
            if r.request_type == 'working_time' and r.name and len(r.name) > description_size:
                raise ValidationError(_('Please use concise language to describe your working time request! It must be less than {} characters.'.format(description_size)))

    @api.constrains('out_by_reg', 'include_absence_hour')
    def _validate_out_of_reg(self):
        """
            - out_of_reg only apply for both or pm case
            - only HR Admin can change the value of out_of_reg
        """
        for r in self:
            if r.out_by_reg and not (r.request_type == 'over_time' and r.sub_request_type_id.code in ['pm', 'both'] and r.request_out):
                raise ValidationError(_('Cannot set [Out by register] value in this case - Please ask IT!'))
            if not (self.env.uid != 1 or self.groups()['hr_staff']):
                raise ValidationError(_('You are not allowed to change [Out by register] or [Include Absebce Hours] values - Please ask HR!'))
    
    # ===== Methods used for changing database structure --- CAREFULLY--- =====
    @api.model
    def update_request_in_out_data(self):
        # !NOTE: for admin only
        # To update data due to change in the model structure
        requests = self.env['hr.attendance.request'].search([])
        for r in requests:
            if not r.request_in:
                r.request_in = r.at_id.check_in_manual
            if not r.request_out:
                r.request_out = r.at_id.check_out_manual

    @api.model
    def _restructure_states(self):
        requests = self.search([])
        for r in requests:
            if r.state == 'confirm':
                r.state = 'waiting_fman'
            if r.state == 'approved':
                r.state = 'waiting_fhr'
            if r.state == 'validate':
                r.state = 'waiting_fman2' if r.man2_approve else 'done'


