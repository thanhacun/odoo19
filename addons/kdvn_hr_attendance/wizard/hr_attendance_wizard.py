import base64
import io

# from collections import defaultdict
import datetime
import pytz
import json
from dateutil.relativedelta import relativedelta
import uuid
import time
from calendar import month_abbr
# from collections import Counter
try:
    from lunarcalendar import Converter, Solar, Lunar, DateNotExist   # only used to generate the Vietnamese holidays of a year
except ImportError:
    Converter = Solar = Lunar = DateNotExist = None
import logging
_logger = logging.getLogger(__name__)

# For pdf conversion
# pip install WeasyPrint==52.5 (https://stackoverflow.com/questions/68720486/how-to-fix-function-symbol-pango-context-set-round-glyph-positions-error)
# Remember WeasyPrint has system dependencies (Cairo, Pango, GDK-Pixbuf).
try:
    from weasyprint import HTML, CSS
    _has_weasyprint = True
except ImportError:
    _has_weasyprint = False
    _logger.warning("WeasyPrint is not installed, HTML to PDF conversion will not work.")

# For Excel conversion
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Border, Side, Alignment, PatternFill  # For more advanced styling
    from openpyxl.utils import get_column_letter
    _has_openpyxl = True
except ImportError:
    _has_openpyxl = False
    _logger.warning("Openpyxl is not installed, Excel conversion will not work.")


from odoo import models, fields, api, tools, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.osv import expression
# from odoo.addons.kderp_base.models.kderp_base_function import roundPartial

utc = pytz.utc
# vn_timedelta = datetime.timedelta(hours=7)
vn_tz = pytz.timezone(' '.join(pytz.country_timezones('vn')))
# vn_tz = datetime.timezone(vn_timedelta, 'VNT')
utc_diff = 7


class KderpAttendanceWizard(models.TransientModel):
    _name = 'hr.attendance.wizard'
    _inherit = ['hr.mixin']
    _description = 'HR attendance related requests wizard'

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        at = self.env['hr.attendance']
        if self.env.context.get('active_model', '') == 'hr.attendance':
            at = at.sudo().browse(self.env.context.get('active_id'))
        elif self.env.context.get('active_model', '') == 'hr.attendance.request':
            at = self.env['hr.attendance.request'].sudo().browse(self.env.context.get('active_id')).at_id
        else:
            pass
        # multi_request_mode = self.env.context.get('default_multi_request_mode', False)
        reset = self.env.context.get('form_reset', False)

        if at:
            defaults['at_id'] = at.id
            batch_id = at.at_request_ids[0].batch_id if at.at_request_ids else False
            defaults['batch_id'] = batch_id
            defaults['single_mode'] = at.single_mode
            if batch_id:
                related_request_ids = self.env['hr.attendance.request'].sudo().search([('batch_id', '=', batch_id)])
                related_ats = self.env['hr.attendance'].sudo().search([('at_request_ids.batch_id', '=', batch_id)])
                defaults['multi_from_date'] = related_ats[0].at_date if related_ats else False
                defaults['multi_to_date'] = related_ats[-1].at_date if related_ats else False
                employee_ids = related_request_ids.mapped('at_id.employee_id.id')
                defaults['employee_ids'] = employee_ids
                defaults['multi_request_mode'] = True
            else:
                defaults['multi_from_date'] = False
                defaults['multi_to_date'] = False
                defaults['employee_ids'] = False
                defaults['multi_request_mode'] = False
            ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
            if ot_request:
                defaults['ot_estimate_dsp'] = ot_request.estimate_ot_dsp
                defaults['out_by_reg'] = ot_request.out_by_reg
                defaults['include_absence_hour'] = ot_request.include_absence_hour
            

        if reset:
            # TODO []: approved state requests
            # TODO []: reset by input mode (WT or OT)
            if self.request_mode in ['ot', 'both']:
                defaults['at_request_type_id'] = False
                defaults['name'] = False
                defaults['wt_in'] = False
                defaults['wt_out'] = False
                defaults['wt_in_time'] = False
                defaults['wt_out_time'] = False
                defaults['early_offset'] = 0
                defaults['at_request_type_id1'] = False
                defaults['name1'] = False
                defaults['wt_in1'] = False
                defaults['wt_out1'] = False
                defaults['wt_in_time1'] = False
                defaults['wt_out_time1'] = False
                defaults['early_offset1'] = 0
            if self.request_mode in ['wt', 'both']:
                defaults['request_ot_for_id'] = False
                defaults['ot_description'] = False
                defaults['ot_in'] = False
                defaults['ot_out'] = False
                defaults['ot_in_time'] = False
                defaults['ot_out_time'] = False
                # defaults['request_leave'] = False
                # defaults['convert_leave'] = False

            if at and at.at_request_ids:  # ! Too complicated - not nice
                wt_requests = at.at_request_ids.filtered(lambda r: r.request_type == 'working_time')
                ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
                # approved_wt = wt_requests.filtered(lambda r: r.state not in ['draft', 'refuse'])
                if wt_requests:
                    for i in range(len(wt_requests)):
                        if wt_requests[i].state in ['waiting_fhr', 'waiting_fman2', 'done']:
                            defaults['at_request_type_id{}'.format('' if i == 0 else 1)] = wt_requests[i].sub_request_type_id.id
                            defaults['name{}'.format('' if i == 0 else 1)] = wt_requests[i].name
                            defaults['at_request{}_state'.format('' if i == 0 else 1)] = wt_requests[i].state
                            # defaults['wt_refuse{}'.format('' if i == 0 else 1)] = wt_requests[i].refuse_comment
                            if i == 1:
                                defaults['at_request_show_request_1'] = True

                if ot_request and ot_request.state in ['wating_fhr', 'waiting_fman2', 'done']:
                    defaults['request_ot_for_id'] = ot_request.sub_request_type_id.id
                    defaults['ot_description'] = ot_request.name
                    # defaults['ot_refuse'] = ot_request.refuse_comment
        else:
            wt_requests = at.at_request_ids.filtered(lambda r: r.request_type == 'working_time')
            ot_request = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')

            wt = wt_requests[0] if wt_requests else False
            defaults['at_request_type_id'] = wt.sub_request_type_id.id if wt else False
            defaults['name'] = wt.name if wt else False
            defaults['wt_in'] = wt.request_in if wt else False
            defaults['wt_out'] = wt.request_out if wt else False
            defaults['wt_in_time'] = self.time_to_float(wt.request_in) if (wt and wt.request_in) else False
            defaults['wt_out_time'] = self.time_to_float(wt.request_out) if (wt and wt.request_out) else False
            defaults['early_offset'] = wt.early_offset if wt and wt.early_offset else 0

            wt1 = wt_requests[1] if len(wt_requests) > 1 else False
            defaults['at_request_type_id1'] = wt1.sub_request_type_id.id if wt1 else False
            defaults['name1'] = wt1.name if wt1 else False
            defaults['wt_in1'] = wt1.request_in if wt1 else False
            defaults['wt_out1'] = wt1.request_out if wt1 else False
            defaults['wt_in_time1'] = self.time_to_float(wt1.request_in) if (wt1 and wt1.request_in) else False
            defaults['wt_out_time1'] = self.time_to_float(wt1.request_out) if (wt1 and wt1.request_out) else False
            defaults['early_offset1'] = wt1.early_offset if wt1 and wt1.early_offset else 0
            defaults['at_request_show_request_1'] = wt1

            defaults['request_ot_for_id'] = ot_request.sub_request_type_id.id if ot_request else False
            defaults['ot_description'] = ot_request.name if ot_request else False
            defaults['ot_in'] = ot_request.request_in if ot_request else False
            defaults['ot_out'] = ot_request.request_out if ot_request else False
            defaults['ot_in_time'] = self.time_to_float(ot_request.request_in) if (ot_request and ot_request.request_in) else False
            defaults['ot_out_time'] = self.time_to_float(ot_request.request_out) if (ot_request and ot_request.request_out) else False

            # defaults['request_leave'] = at.request_leave
            # defaults['convert_leave'] = at.convert_leave

        defaults['employee_id'] = at.sudo().employee_id.id or self.env.user.employee_id and self.env.user.employee_id.id or False
        defaults['current_absence_date'] = at.current_absence_date or False
        end_time = time.time()
        return defaults

    def _default_at_id(self):
        # self.ensure_one()
        return self.env['hr.attendance'].sudo().browse(self.env.context.get('active_id'))

    name = fields.Text(string="Working time reason")
    name1 = fields.Text(string="Working time reason (other)")
    at_id = fields.Many2one('hr.attendance', require=True, readonly=True)
    employee_id = fields.Many2one('hr.employee', readonly=True)
    department_id = fields.Many2one('hr.department', related='employee_id.admin_dept_id', readonly=True)
    at_date = fields.Date(related='at_id.at_date', readonly=True)
    # actual_in = fields.Datetime(related='at_id.check_in', readonly=True, string="Check in")
    # actual_out = fields.Datetime(related='at_id.check_out', readonly=True, string="Check out")
    actual_in = fields.Datetime(related='at_id.compute_in', readonly=True, string="Check in")
    actual_out = fields.Datetime(related='at_id.compute_out', readonly=True, string="Check out")
    check_in = fields.Datetime(string="Request IN")
    check_out = fields.Datetime(string="Request OUT")
    at_state = fields.Char('kderp.base.state', related='at_id.state_id.code', readonly=True)
    status_ids = fields.Many2many(related='at_id.status_ids')

    at_request_type_id = fields.Many2one('hr.attendance.request.type', string='Request type', domain=[('request_type', '=', 'working_time')])
    at_request_code = fields.Char(related='at_request_type_id.code', readonly=True)
    at_request_need_description = fields.Boolean(related='at_request_type_id.need_description', readonly=True)
    at_request_auto_in_out = fields.Selection(related='at_request_type_id.auto_in_out')
    at_request_state = fields.Char(compute='compute_requests_state')
    wt_in = fields.Datetime()
    wt_out = fields.Datetime()
    wt_in_time = fields.Float()
    wt_out_time = fields.Float()
    early_offset = fields.Integer(default=0, help="Number of minutes check_in early")  # Early offset for single attendance
    # wt_refuse = fields.Text(compute='_compute_refuse_comments', readonly=True)

    at_request_type_id1 = fields.Many2one('hr.attendance.request.type', string='Request type (2nd)', domain=[('request_type', '=', 'working_time')])
    at_request_code1 = fields.Char(related='at_request_type_id1.code', readonly=True)
    at_request_need_description1 = fields.Boolean(related='at_request_type_id1.need_description', readonly=True)
    at_request_auto_in_out1 = fields.Selection(related='at_request_type_id1.auto_in_out')
    at_request1_state = fields.Char(compute='compute_requests_state')
    at_request_show_request_1 = fields.Boolean('One more request', default=False)
    wt_in1 = fields.Datetime()
    wt_out1 = fields.Datetime()
    wt_in_time1 = fields.Float()
    wt_out_time1 = fields.Float()
    early_offset1 = fields.Integer(default=0, help="Number of minutes check_in early")  # Early offset for single attendance
    # wt_refuse1 = fields.Text(compute='_compute_refuse_comments', readonly=True)

    request_ot_for_id = fields.Many2one('hr.attendance.request.type', domain=[('request_type', '=', 'over_time')])
    ot_description = fields.Text('Detail of OT work')
    ot_request_state = fields.Char(compute='compute_requests_state')
    ot_request_auto_in_out = fields.Selection(related='request_ot_for_id.auto_in_out')
    ot_in = fields.Datetime()
    ot_out = fields.Datetime()
    ot_in_time = fields.Float()
    ot_out_time = fields.Float()
    # ot_refuse = fields.Text(compute='_compute_refuse_comments', readonly=True)
    ot_estimate_dsp = fields.Text(string="Estimate OT", readonly=True, default=False)

    # request_leave = fields.Selection([
    #     ('full_day', 'Full day'),
    #     ('half_day', 'Half day')])
    # convert_leave = fields.Selection([
    #     ('full_day', 'Full day'),
    #     ('half_day', 'Half day')])

    # substitute_at_id = fields.Many2one('hr.attendance')

    # can_request_leave = fields.Boolean(related='at_id.can_request_leave')
    # can_convert_leave = fields.Boolean(related='at_id.can_convert_leave')

    current_absence_date = fields.Text()
    # show_leave_request = fields.Boolean(compute='_compute_show_leave_request')
    ot_apply = fields.Boolean(related='at_id.ot_apply')

    # show_leaves = fields.Boolean(related='employee_id.show_leaves')
    # leaves_count = fields.Float(related='employee_id.leaves_count')
    # related_leaves_count = fields.Integer(related='at_id.related_leaves_count')
    # next_month_available_at = fields.Text(compute='_compute_next_month_available_at', default='[]')

    show_buttons = fields.Boolean(compute='_compute_show_buttons')
    show_wt_buttons = fields.Boolean(compute='_compute_show_buttons')
    show_wt1_buttons = fields.Boolean(compute='_compute_show_buttons')
    show_ot_buttons = fields.Boolean(compute='_compute_show_buttons')
    request_mode = fields.Selection([
        ('ot', 'Over time'),
        ('wt', 'Working time'),
        ('both', 'Both')
    ], default='both')

    multi_request_mode = fields.Boolean(default=False)
    multi_dates = fields.Char()
    employee_ids = fields.Many2many('hr.employee', string="Employees")
    multi_from_date = fields.Date()
    multi_to_date = fields.Date()
    multi_check_in = fields.Datetime()
    multi_check_out = fields.Datetime()
    batch_id = fields.Char(default=False)

    future_request_mode = fields.Boolean(default=False)
    future_check_in = fields.Datetime()
    future_check_out = fields.Datetime()

    # Other
    out_by_reg = fields.Boolean('Out by register', help="Only by HR Admin", default=False)
    include_absence_hour = fields.Boolean('Include absence hours', help="Only by HR Admin: allow calculating absence hours.", default=False)

    # @api.depends('employee_id')
    def _compute_next_month_available_at(self):
        """Return a list of date of 31 days from today that do not have AT data yet

        Returns:
            [list]: [description]
        """
        self.ensure_one()
        if not self.employee_id:
            return False

        result = []
        if self.at_id and self.at_date:
            result.append(self.at_date)
        else:
            start_date = self.env['hr.mixin'].today_vn()
            end_date = start_date + relativedelta(days=30)
            domain = [
                ('employee_id', '=', self.employee_id.id), ('at_date', '>=', start_date.strftime('%Y-%m-%d')),
                ('at_date', '<=', end_date.strftime('%Y-%m-%d'))]

            available_at_dates = set(self.env['hr.attendance'].search(domain).mapped('at_date'))
            date_range = set([start_date + relativedelta(days=i + 1) for i in range(31)])
            result = list(date_range - available_at_dates)

        self.next_month_available_at = json.dumps(list(map(lambda e: e.strftime('%Y-%m-%d'), result)))

    # @api.depends('at_id')
    def compute_requests_state(self):
        for record in self:
            requests_states = {
                'at_request_state': False,
                'at_request1_state': False,
                'ot_request_state': False
            }
            if record.at_id and record.at_id.at_request_ids:
                wt_requests = record.at_id.at_request_ids.filtered(lambda e: e.request_type == 'working_time')
                ot_request = record.at_id.at_request_ids.filtered(lambda e: e.request_type == 'over_time')
                if wt_requests:
                    requests_states['at_request_state'] = wt_requests[0].state
                    requests_states['at_request1_state'] = wt_requests[1].state if len(wt_requests) > 1 else False
                if ot_request:
                    requests_states['ot_request_state'] = ot_request.state
            record.update(requests_states)

    def action_related_leaves_form(self):
        if self.at_id:
            return self.at_id.action_related_leaves_form()
        else:
            return False

    @api.onchange('at_request_type_id', 'at_request_type_id1', 'request_ot_for_id')
    def _compute_check_in_out(self):
        # ! minimize changing data here
        # ! consider that only for user convenience

        # ! Because this method always happen when open the wizard
        # ! be very carefull here
        r = self
        company = self.env.user.company_id
        if not company:
            raise UserError(_('{} should belong to a company! Please contact HR admin!'.format(self.env.user.name)))
        at_policy = company.at_policy()
        if r.at_request_type_id:
            if r.at_request_type_id.id != r.default_get(['at_request_type_id'])['at_request_type_id']:
                if not r.wt_in_time or r.wt_in_time == at_policy['working_start']:
                    if r.at_request_type_id.auto_in_out in ['in', 'both']:
                        r.wt_in_time = at_policy['working_start']
                        if r.at_request_type_id.auto_in_out == 'in':
                            r.wt_out_time = False
                            r.wt_out = False
                    else:
                        # TODO []: do NOT override default values (when loadding values)
                        r.wt_in_time = False
                        r.wt_in = False
                if not r.wt_out_time or r.wt_out_time == at_policy['working_start'] + 9:
                    if r.at_request_type_id.auto_in_out in ['out', 'both']:
                        r.wt_out_time = at_policy['working_start'] + 9
                        if r.at_request_type_id.auto_in_out == 'out':
                            r.wt_in_time = False
                            r.wt_in = False
                    else:
                        r.wt_out_time = False
                        r.wt_out = False
        else:
            r.wt_in = False
            r.wt_out = False
            r.wt_in_time = False
            r.wt_out_time = False
            r.name = False

        if r.at_request_type_id1:
            if r.at_request_type_id1.id != r.default_get(['at_request_type_id1'])['at_request_type_id1']:
                if not r.wt_in_time1 or r.wt_in_time1 == at_policy['working_start']:
                    if r.at_request_type_id1.auto_in_out in ['in', 'both']:
                        r.wt_in_time1 = at_policy['working_start']
                        if r.at_request_type_id1.auto_in_out == 'in':
                            r.wt_out_time1 = False
                            r.wt_out1 = False
                    else:
                        r.wt_in_time1 = False
                        r.wt_in1 = False
                if not r.wt_out_time1 or r.wt_out_time1 == at_policy['working_start'] + 9:
                    if r.at_request_type_id1.auto_in_out in ['out', 'both']:
                        r.wt_out_time1 = at_policy['working_start'] + 9
                        if r.at_request_type_id1.auto_in_out == 'out':
                            r.wt_in_time1 = False
                            r.wt_in1 = False
                    else:
                        r.wt_out_time1 = False
                        r.wt_out1 = False
        else:
            r.wt_in1 = False
            r.wt_out1 = False
            r.wt_in_time1 = False
            r.wt_out_time1 = False
            r.name1 = False

        if r.request_ot_for_id:
            if r.request_ot_for_id.code == 'am' and r.ot_out_time:
                r.ot_out_time = False
                r.ot_out = False
            if r.request_ot_for_id.code == 'pm' and r.ot_in_time:
                r.ot_in_time = False
                r.ot_in = False
            # if not r.ot_in_time and r.request_ot_for_id.code in ['am', 'both']:
            # if not r.ot_out_time and r.request_ot_for_id.code in ['pm', 'both']:
            
            if False and r.request_ot_for_id.id != r.default_get(['request_ot_for_id'])['request_ot_for_id']:
                if not r.ot_in_time or r.ot_in_time == at_policy['working_start']:
                    # r.ot_in_time = self.time_to_float(r.at_id.compute_in) if (r.at_id and r.at_id.compute_in) else at_policy['working_start']
                    if r.request_ot_for_id.code in ['am', 'both']:
                        r.ot_in_time = at_policy['working_start']
                        if r.request_ot_for_id.code == 'am':
                            r.ot_out_time = False
                            r.ot_out = False
                    else:
                        r.ot_in_time = False
                        r.ot_in = False
                if not r.ot_out_time or r.ot_out_time == at_policy['working_start'] + 9:
                    # r.ot_out_time = self.time_to_float(r.at_id.compute_out) if (r.at_id and r.at_id.compute_out) else at_policy['working_start'] + 9
                    if r.request_ot_for_id.code in ['pm', 'both']:
                        r.ot_out_time = at_policy['working_start'] + 9
                        if r.request_ot_for_id.code == 'pm':
                            r.ot_in_time = False
                            r.ot_in = False
                    else:
                        r.ot_out_time = False
                        r.ot_out = False
        else:
            r.ot_in = False
            r.ot_out = False
            r.ot_in_time = False
            r.ot_out_time = False
            r.ot_description = False

        # r._onchange_time_input()
        r.check_in = r.wt_in or r.wt_in1
        r.check_out = r.wt_out or r.wt_out1

    @api.onchange('wt_in_time', 'wt_out_time', 'wt_in_time1', 'wt_out_time1', 'ot_in_time', 'ot_out_time')
    def _onchange_time_input(self, at_date=False):
        # !NOTE: why cannot write data here? => memory model
        dt_keys = ['wt_in', 'wt_out', 'wt_in1', 'wt_out1', 'ot_in', 'ot_out']
        time_keys = ['wt_in_time', 'wt_out_time', 'wt_in_time1', 'wt_out_time1', 'ot_in_time', 'ot_out_time']
        r = self
        if not at_date:
            at_date = r.at_date
        if at_date:
            for i in range(len(time_keys)):
                # Need employee_id for early_check_in cases
                is_in_time = True if dt_keys[i] in ['wt_in', 'wt_in1', 'ot_in'] else False
                r.update({dt_keys[i]: False if not r[time_keys[i]] else self.float_to_datetime(r[time_keys[i]], at_date, employee_id=r.employee_id, is_in_time=is_in_time)})


    # @api.onchange('request_leave')
    # def _compute_sub_hol(self):
    #     self.ensure_one()
    #     at = self.at_id
    #     if at:
    #         domain = [('employee_id', '=', at.employee_id.id), ('at_month', '=', at.at_month),
    #                   ('work_on_holiday', '!=', False), ('request_ot_for', '=', False),
    #                   '|', ('absence', '=', False), ('absence', '!=', 'absence'),
    #                   '|', '|', ('is_holiday', '=', True), ('is_public_holiday', '=', True), ('is_other_holiday', '=', True)]
    #         sub_hol_ids = self.env['hr.attendance'].search(domain).mapped('id')
    #         occupied_sub_hol_ids = self.env['hr.leave'].search([('substitute_for_at_id', 'in', sub_hol_ids)]).mapped('substitute_for_at_id').mapped('id')
    #         avai_ids = list(set(sub_hol_ids) - set(occupied_sub_hol_ids))
    #         return {'domain': {'substitute_at_id': [('id', 'in', avai_ids)]}}
    #     else:
    #         return False

    @api.depends('at_id', 'multi_request_mode', 'at_request_show_request_1', 'request_mode')
    def _compute_show_buttons(self):
        is_hr_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        for r in self:
            # show_buttons = not at.at_id or (at.at_id and at.at_id.state in ['draft'] and ((self.env.user == self.employee_id.user_id) or is_hr_admin))
            show_buttons = not r.at_id or (r.at_id and ((self.env.user == self.employee_id.user_id) or is_hr_admin) and r.at_id.state in ['draft', 'waiting_fman'])
            wt_request = r.at_id.at_request_ids.filtered(lambda r: r.request_type == 'working_time')
            ot_request = r.at_id.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
            wt_buttons = False
            wt1_buttons = False
            ot_buttons = False
            if not ot_request or len(ot_request) == 1 and ot_request.state in ['draft', 'waiting_fman']:
                ot_buttons = True

            if not wt_request:
                wt_buttons = True
                wt1_buttons = True
            elif len(wt_request) == 1:
                wt1_buttons = True
                wt_buttons = wt_request.state in ['draft', 'waiting_fman']
            elif len(wt_request) == 2:
                wt_buttons = wt_request[0].state in ['draft', 'waiting_fman']
                wt1_buttons = wt_request[1].state in ['draft', 'waiting_fman']
            
            r.show_buttons = show_buttons
            r.show_wt_buttons = wt_buttons and r.request_mode == 'wt'
            r.show_wt1_buttons = wt1_buttons and r.request_mode == 'wt' and r.at_request_show_request_1
            r.show_ot_buttons = ot_buttons and r.request_mode == 'ot'

    # No need?
    def _compute_ot_estimate_dsp(self):
        for r in self:
            ot_estimate_dsp = None
            if r.at_id and r.request_ot_for_id:
                ot_estimate_dsp = r.at_id.at_request_ids.filtered(lambda e: e.request_type == 'over_time').estimate_ot_dsp
            r.update({'ot_estimate_dsp': ot_estimate_dsp})
    
    @api.onchange('multi_request_mode')
    def onchange_multi_mode(self):
        emp_domain = []
        if not self.multi_request_mode:
            self.employee_ids = False
            self._compute_check_in_out()
            self.multi_dates = False
        else:
            # add active employee_id to employee_ids
            self.employee_ids = [(4, self.employee_id.id, 0)]
            if self.at_id and self.at_id.single_mode:
                emp_domain = [('id', 'in', [self.employee_id.id])]

        return {
            'domain': {'employee_ids': emp_domain}
        }

    @api.onchange('multi_from_date')
    def onchange_multi_from_date(self):
        for r in self:
            if r.multi_from_date and not r.multi_to_date:
                r.multi_to_date = r.multi_from_date

    # ===== API =====
    def save_multi(self):
        # TODO [X]: multi request mode
        # TODO [X]: get each request for each day and each employee
        # TODO [X]: run save method for each record
        # TODO []: reset all => delete
        # TODO []: not allow to register for a long duration (maximum 5 days)

        save_submit = self.env.context.get('save_submit', False)
        max_duration = 5
        if self.multi_request_mode:
            if all([self.multi_from_date, self.multi_to_date]):
                at_dates = [self.multi_from_date + relativedelta(days=d) for d in range((self.multi_to_date - self.multi_from_date).days + 1)]
                if (self.multi_to_date - self.multi_from_date).days >= max_duration and 'biz_trip' not in (self.at_request_type_id.code, self.at_request_type_id1.code) :
                    _logger.error('Cannot create multiple requests for longer than {} days! Please ask HR.'.format(max_duration))
                    raise UserError(_('Cannot create multiple requests for longer than {} days! Please ask HR.'.format(max_duration)))
            elif any([self.multi_from_date, self.multi_to_date]):
                at_dates = [self.multi_from_date if self.multi_from_date else self.multi_to_date]
            else:
                at_dates = []
            batch_id = str(uuid.uuid4()) if (len(at_dates) > 1 or len(self.employee_ids) > 1) else False
            for employee in self.employee_ids:
                new_wizard = {}
                new_wizard['employee_id'] = employee.id

                # [] create hr.attendance.wizard request record
                # at_ids = self.env['hr.attendance'].search([('employee_id', '=', employee.id), ('at_date', 'in', at_dates)])
                for k in ('name', 'name1', 'ot_description'):
                    new_wizard[k] = self[k]
                for k in ('at_request_type_id', 'at_request_type_id1', 'request_ot_for_id'):
                    new_wizard[k] = self[k].id

                for at_date in at_dates:
                    # import odoo_repl; odoo_repl.set_trace()
                    at_id = self.env['hr.attendance'].search([('employee_id', '=', employee.id), ('at_date', '=', at_date)])
                    new_wizard['at_id'] = at_id.id if at_id else False
                    new_wizard['batch_id'] = batch_id
                    # new_wizard['at_date'] = at_date

                    # in, out times
                    self._onchange_time_input(at_date)  # compute at_date
                    new_wizard['wt_in'] = self.wt_in if self.wt_in else False
                    new_wizard['wt_out'] = self.wt_out if self.wt_out else False
                    new_wizard['wt_in1'] = self.wt_in1 if self.wt_in1 else False
                    new_wizard['wt_out1'] = self.wt_out1 if self.wt_out1 else False
                    new_wizard['ot_in'] = self.ot_in if self.ot_in else False
                    new_wizard['ot_out'] = self.ot_out if self.ot_out else False
                    new_wizard['multi_from_date'], new_wizard['multi_to_date'] = at_date, at_date

                    # calling method save on each record
                    new_wizard_id = self.create(new_wizard)
                    if save_submit:
                        new_wizard_id.submit()
                    else:
                        new_wizard_id.save()
                    # _logger.warning('====== Saving/Delete {}, {}'.format(at_date, new_wizard))

        # return {
        #     'type': 'ir.actions.close_wizard_refresh_view'
        # }

    def submit_multi(self):
        self.with_context(save_submit=True).save_multi()

    def _handle_switching_in_out(self, at_id):
        """
            - In some cases, system may recognize wrongly check_in to check_out and vice verse
            - For example: check_in at 12:30 and forget checkout or work outside afternoon
            - In this case, the system will record check_out time as 12:30
            - When user make a working time request, he/she will choose Requese Out time
            - We need to change at_raw record, at record and update status again.
            - !Note We also need a way to tell system not update back the at_raw in future update
        """
        at = self.env['hr.attendance'].browse(at_id)
        # ! sudo here
        at_raw = self.env['hr.attendance.raw'].search([('at_code', '=', at.code)])
        if at and at_raw:
            # TODO []: pop up a warning
            # Modify at_raw (switching)
            if at_raw.check_in and not at_raw.check_out:
                switch_from = 'check_in'
                switch_to = 'check_out'
            elif at_raw.check_out and not at_raw.check_in:
                switch_from = 'check_out'
                switch_to = 'check_in'

            check_dt = at_raw[switch_from]
            at_raw[switch_from] = False
            at_raw[switch_to] = check_dt
            # Lock at_raw (prevent hr.attendance.raw._get_raw_data method to update the record again)

            # Sync back or modify at
            # Recompute at status
            # ! sudo here
            self.env['hr.attendance.raw']._sync_attendance_record(at_date=at.at_date, duration=0, employee_ids=[at.employee_id.id])

    def save(self):
        """
            - Saving current input into requests
            - Create empty Attendance request if needed
            - Return related AT
        """
        self.ensure_one()
        save_submit = self.env.context.get('save_submit', False)
        # TODO [X]: also delete related requests if current request content is empty
        # TODO []: consider delete future at if there is NO more request

        # import odoo_repl; odoo_repl.set_trace()
        company = self.employee_id.company_id or self.env.user.company_id
        if not company:
            raise UserError(_('{} should belong to a company!'.format(self.employee_id.name)))

        aval_dates = list(filter(lambda d: d is not False, [self.wt_in, self.wt_out, self.wt_in1, self.wt_out1, self.ot_in, self.ot_out]))
        multi_at_date = self.multi_from_date if all([self.multi_from_date, self.multi_to_date]) and self.multi_from_date == self.multi_to_date else False
        at_date = self.at_date or False
        if not at_date and any(aval_dates):
            at_date = self.get_at_date(aval_dates[0], employee_id=self.employee_id)
        if not at_date and multi_at_date:
            at_date = multi_at_date
        if at_date:
            domain = [('at_date', '=', at_date), ('employee_id', '=', self.employee_id.id if self.employee_id else 0)]
            related_at = self.env['hr.attendance'].search(domain)
            if related_at and len(related_at) == 1:
                self.at_id = related_at.id

        at_request_id = self.at_request_type_id
        name = self.name
        wt_in, wt_out = self.wt_in, self.wt_out
        at_request_id1 = self.at_request_type_id1
        name1 = self.name1
        wt_in1, wt_out1 = self.wt_in1, self.wt_out1
        request_ot_for = self.request_ot_for_id
        ot_description = self.ot_description
        ot_in, ot_out = self.ot_in, self.ot_out
        # request_leave = self.request_leave
        # convert_leave = self.convert_leave
        check_in = wt_in or wt_in1 or False
        check_out = wt_out or wt_out1 or False

        batch_id = self.batch_id
        early_offset = self.early_offset
        early_offset1 = self.early_offset1

        out_by_reg = self.out_by_reg
        include_absence_hour = self.include_absence_hour

        wt = {'name': name, 'request_type': 'working_time', 'early_offset': early_offset,
              'sub_request_type_id': at_request_id.id, 'request_in': wt_in, 'request_out': wt_out, 'batch_id': batch_id}
        wt1 = {'name': name1, 'request_type': 'working_time', 'early_offset': early_offset1,
               'sub_request_type_id': at_request_id1.id, 'request_in': wt_in1, 'request_out': wt_out1, 'batch_id': batch_id}
        ot = {'name': ot_description, 'request_type': 'over_time',
              'sub_request_type_id': request_ot_for.id, 'request_in': ot_in, 'request_out': ot_out, 'batch_id': batch_id, 'out_by_reg': out_by_reg, 'include_absence_hour': include_absence_hour}

        if not self.at_id:
            # create new record (future request)
            employee_id = self.employee_id
            if not employee_id:
                raise UserError(_('There is NO linked employee for user {} - please contact HR!'.format(self.env.user.login)))

            if not at_date:
                raise UserError(_('at_date not available, please contact HR or IT!'))

            at_code = '-'.join(['AT', at_date.strftime('%y%m%d'), employee_id.code])

            # TODO [X]: not SAVE if request content is empty
            # TODO []: What if user want to substitute holiday?
            if not any([at_request_id, name, request_ot_for, ot_description]):
                pass
            else:
                # ! TODO []: Check why need hr.employee write here? (may be a write to resource?)
                at = self.env['hr.attendance'].create({
                    'employee_id': employee_id.id,
                    # 'check_in_manual': check_in,
                    # 'check_out_manual': check_out,
                    'code': at_code,
                    # 'request_leave': request_leave,
                    # 'convert_leave': convert_leave,
                })
                at_request_ids = []
                if at_request_id:
                    wt['at_id'] = at.id
                    at_request_ids.append(wt)
                if at_request_id1:
                    wt1['at_id'] = at.id
                    at_request_ids.append(wt1)
                if request_ot_for:
                    ot['at_id'] = at.id
                    at_request_ids.append(ot)

                # import odoo_repl; odoo_repl.set_trace()
                at.at_request_ids = [(0, False, r) for r in at_request_ids]

        else:
            at = self.at_id
            working_time_requests = self.at_id.at_request_ids.filtered(lambda r: r.request_type == 'working_time')
            working_time_request = len(working_time_requests) >= 1 and working_time_requests[0]
            working_time_request1 = len(working_time_requests) > 1 and working_time_requests[1]
            over_time_request = self.at_id.at_request_ids.filtered(lambda r: r.request_type == 'over_time')

            update = {}
            new_request = []
            # TODO [X]: DO NOT unlink if user add one more request
            if not at_request_id and not name and working_time_request and not request_ot_for and not ot_description:
                working_time_request.sudo().unlink()
            if not at_request_id1 and not name1 and working_time_request1 and not request_ot_for and not ot_description:
                working_time_request1.sudo().unlink()
            if not request_ot_for and not ot_description and over_time_request and (not at_request_id and not name) or (at_request_id1 and name1):
                over_time_request.sudo().unlink()

            # TODO: DRY
            if at_request_id:
                if working_time_request:
                    working_time_request.write(wt)
                else:
                    wt['at_id'] = at.id
                    new_request.append(wt)

            if at_request_id1:
                if working_time_request1:
                    working_time_request1.write(wt1)
                else:
                    wt1['at_id'] = at.id
                    new_request.append(wt1)

            if request_ot_for:
                if over_time_request:
                    over_time_request.write(ot)
                else:
                    ot['at_id'] = at.id
                    new_request.append(ot)

            if new_request:
                if list(filter(lambda r: r['request_type'] == 'working_time', new_request)):
                    # TODO []: check carefully here for other case
                    if (self.actual_in and check_in and not self.actual_out and not check_out) or (self.actual_out and check_out and not self.actual_in and not check_in):
                        _logger.warning(_('===== Calling method to handle switching check_in and check_out case'))
                        # self._handle_switching_in_out(at_id=at.id)
                update['at_request_ids'] = [(0, False, r) for r in new_request]

            # update['request_leave'] = self.request_leave
            # update['convert_leave'] = self.convert_leave

            # TODO [] always using self.check_in, self.check_out for at.check_in_manual, at.check_out_manual
            # update['check_in_manual'] = check_in
            # update['check_out_manual'] = check_out

            at.write(update)
            # at._compute_at_status()
            
        # ====== OT Calculation ======
        if request_ot_for:
            at._compute_ot_request()
            
        # ===== END OT Calculation =====

        # submit request
        if save_submit:
            at.at_request_ids.action_submit()
            # Force at sync if request for early_in
            request_early_in = at.at_request_ids.filtered(lambda r: r.sub_request_type_id.code == 'early_in' and r.state not in ['draft', 'refuse'])
            if request_early_in and request_early_in.early_offset:
                at_date = request_early_in.at_id.at_date - relativedelta(days=1)  # sync back 01 day to fix check out late data
                self.env['hr.attendance.raw'].sudo()._get_raw_data(at_date=at_date, duration=1, employee_ids=[at.employee_id.id], force_sync=True)
                self.env['hr.attendance.raw'].sudo()._sync_attendance_record(at_date=at_date, duration=1, employee_ids=[at.employee_id.id], force_sync=True)

        # [] Check warning for OT
        if request_ot_for:
            e_ot = at.e_ot_am + at.e_ot_pm
            weekly_wd_over = (at.weekly_wd_remain - e_ot) < 0
            month_wd_over = (at.ot_wd_remain - e_ot) < 0
            month_hd_over = (at.ot_hd_remain - e_ot) < 0
            message_action = {}

            action_revise = {
                'type': 'ir.actions.act_window_close',
                'name': 'Revise',
                'classes': 'btn btn-success'
            }

            action_continue = {
                'type': 'ir.actions.act_window',
                'name': 'Continue',
                'res_model': 'hr.attendance',
                'view_mode': 'form',
                'views': [[False, 'list'], [False, 'form']],
                'context': {'search_default_filter_current_month_at': 1},
                'classes': 'btn btn-warning'
            }

            if month_wd_over:
                message_action = {
                    'type': 'ir.actions.act_window.message',
                    'title': _('Reached monthly OT limit for weekday!'),
                    'message': _(f'Your total overtime hours this month have been over the limit. Kindly organize your workload to prevent it from occuring further during the remaining days of this month'),
                    'close_button_title': _('Revise'),
                    'buttons': [
                        action_continue
                    ]
                }
            else:
                if weekly_wd_over:
                    message_action = {
                        'type': 'ir.actions.act_window.message',
                        'title': _('Reached weekly OT limit for weekday!'),
                        'message': _(f'Your total overtime hours this week have been over the average weekly limit. Kindly organize your workload to prevent it from occuring.'),
                        'close_button_title': _('Revise'),
                        'buttons': [
                            action_continue
                        ]
                    }
            
            if month_hd_over:
                message_action = {
                        'type': 'ir.actions.act_window.message',
                        'title': _('Reached monthly OT limit for holiday!'),
                        'message': _(f'Your total overtime hours this week have been over the average monthly limit. Kindly organize your workload to prevent it from occuring further during the remaining days of this month.'),
                        'close_button_title': _('Revise'),
                        'buttons': [
                            action_continue
                        ]
                    }
            
            return message_action
        
        # print('=====', self.env.context)
        # refresh view
        # return {
        #     'type': 'ir.actions.close_wizard_refresh_view'
        # }

    def submit(self):
        self.ensure_one()
        if self.at_id and self.at_id.state in ['refuse'] or (self.at_id.data_enough and self.at_id.state == 'done'):
            _logger.warning(_('Cannot submit when attendance is [Refuse] or [Done] for morethan 2 days! REF: {}. Please ask HR!'.format(self.at_id.code)))
            # raise UserError(_('Cannot submit when attendance is [Refuse] or [Done] for morethan 2 days! REF: {}. Please ask HR!'.format(self.at_id.code)))
            return False
        self.with_context(save_submit=True).save()

    def reset(self):
        # REF: https://stackoverflow.com/questions/31963214/odoo-prevent-button-from-closing-wizard
        # Method 01
        # return {
        #     'type': ' ir.actions.do_nothing',
        # }

        self.ensure_one()
        self.at_request_type_id = False
        self.at_request_type_id1 = False
        self.request_ot_for_id = False

        if self.at_id:
            # Method 02
            # Reopen a new record with_context of form_reset to trigger defaults function
            return {
                'context': self.with_context(form_reset=True)._context,
                
                'view_mode': 'form',
                'res_model': 'hr.attendance.wizard',
                'view_id': False,
                'type': 'ir.actions.act_window',
                'target': 'new',
            }
        else:
            action = self.env.ref('kdvn_hr_attendance.hr_attendance_wizard').read()[0]
            return action

    @api.depends('status_ids')
    def _compute_show_leave_request(self):
        print('====== leaves')
        self.ensure_one()
        if set(['X', '1/2 X']).intersection(self.status_ids.mapped('code')):
            self.show_leave_request = True
        else:
            self.show_leave_request = False

    # ===== CONSTRAINTS =====

    @api.constrains('check_in', 'check_out')
    def _validate_check_in_check_out(self):
        for r in self:
            if not r.employee_id:
                raise ValidationError(_('The at record need a valid employee/staff'))
            else:
                at_rules = self.env['hr.attendance']._at_rules(r.employee_id.id)
                day_start = at_rules['day_start']

                if r.multi_request_mode:
                    pass

                # check_in and check_out are in the same at_date (by at_rule)
                if r.check_in and r.check_out:
                    check_in_date = self.env['hr.attendance.raw'].date_by_start_hour(r.check_in, day_start, employee_id=r.employee_id)
                    check_out_date = self.env['hr.attendance.raw'].date_by_start_hour(r.check_out, day_start, employee_id=r.employee_id)

                    if check_in_date and check_out_date and check_in_date != check_out_date:
                        raise ValidationError(_('Check in and check out must be on the same date (defined by at policy)'))

                # overtime
                if r.request_ot_for_id:
                    if r.request_ot_for_id.code in ['am', 'pm']:
                        if all([not r.ot_in, not r.ot_out]):
                            raise ValidationError(_('Need {} to request overtime!'.format('Request IN' if r.request_ot_for_id.code == 'am' else 'Request OUT')))
                    if r.request_ot_for_id.code == 'both':
                        if not all([r.ot_in, r.ot_out]):
                            raise ValidationError(_('Need both [Request IN, Request OUT] to request overtime!'))

                # working time
                # TODO [X]: more detail cases of forget_in and forget_out
                if any([r.at_request_type_id, r.at_request_type_id1]):
                    if 'forget_in' in [r.at_request_type_id.code, r.at_request_type_id1.code] and not r.check_in:
                        raise ValidationError(_('Need Request IN to request for [Forget check in]!'))
                    if 'forget_out' in [r.at_request_type_id.code, r.at_request_type_id1.code] and not r.check_out:
                        raise ValidationError(_('Need Request OUT to request for [Forget check out]!'))
                    if all([not r.check_in, not r.check_out]):
                        raise ValidationError(_('Need either Request IN or Request OUT to request working time!'))

    @api.constrains('at_request_type_id', 'at_request_type_id1')
    def _check_request_type(self):
        for r in self:
            if r.at_request_type_id and r.at_request_type_id == r.at_request_type_id1:
                raise ValidationError(_('2 working time requests have the same reason!'))
            if r.at_request_type_id == False and r.at_request_type_id1 != False:
                raise ValidationError(_('Fill in first request first!'))


class KderpAttendanceAdminControl(models.TransientModel):
    _name = 'hr.attendance.admin.control.wizard'
    _description = "Admin Control Wizard"

    at_month = fields.Integer('AT Month', compute='_compute_at_month_year', readonly=True)
    at_year = fields.Integer('AT Year', compute='_compute_at_month_year', readonly=True)
    at_date = fields.Date('AT Date')
    to_date = fields.Date('To Date', default=False, help="Get data until the date input here.")
    employee_ids = fields.Many2many('hr.employee')
    monthly_report = fields.Selection([
        ('overtime', 'Overtime Report'),
        ('estimate_overtime', 'Estimate Overtime Report'),
        ('workingtime', 'Working Time Report'),
        ('leave', 'Leave Report'),
        ('attendance', 'Attendance Record'),
        ('ot_compensation', 'Yearly OT Compensation'),
        ('at_performance', 'Yearly AT Performance'),
        ('leave_remain', 'Leave Allocation Remain'),
        ('attendance_location', 'AT Location Report')
    ])
    archive_message = fields.Text(compute='_compute_archive_message', readonly=True)
    dynamic_notice = fields.Text(compute='_compute_dynamic_notice', readonly=True)
    dynamic_input = fields.Text(help="Used for special quick input - need instruction from IT")

    def action_run_get_raw_data(self):
        """Buttons "Get data (1)" / "Sync data (2)": Odoo 12 ran the scheduled action through type="action"; Odoo 19 runs it with method_direct_trigger."""
        self.env.ref('kdvn_hr_attendance.at_get_raw_data').sudo().method_direct_trigger()
        return True

    def action_run_sync_raw_data(self):
        self.env.ref('kdvn_hr_attendance.at_sync_raw_data').sudo().method_direct_trigger()
        return True

    @api.depends('at_date')
    def _compute_at_month_year(self):
        AT = self.env['hr.attendance']
        for r in self:
            if r.at_date:
                r.at_year, r.at_month = AT.get_at_year_month(r.at_date)

    @api.depends('at_date')
    def _compute_archive_message(self):
        today = fields.Date.context_today(self)
        archive_date = today - relativedelta(months=14)
        old_at_count = self.env['hr.attendance'].search_count([('at_date', '<', archive_date)])

        # AT = self.env['hr.attendance']
        # date_to_archive = AT.get_start_dt(fields.Date.context_today(self), for_month=True) - relativedelta(years=1, months=-1)
        # old_ats = AT.search([('at_date', '<', date_to_archive)])
        # not_done_ats = AT.search([('at_date', '<', date_to_archive), ('state', '!=', 'done')])
        self.archive_message = _('{} records before {} will be archived. \n Only IT admin can perform this action!'.format(old_at_count, archive_date))

    @api.depends('at_date', 'to_date', 'employee_ids')
    def _compute_dynamic_notice(self):
        thread_hold = 200
        dynamic_notice = False
        if self.at_date and self.to_date and self.to_date > self.at_date:
            duration = (self.to_date - self.at_date).days
            if self.employee_ids:
                if duration * len(self.employee_ids) * 3 > thread_hold:
                    dynamic_notice = 'Consider reduce duration or number of employees for better performance'
        self.dynamic_notice = dynamic_notice

    
    def action_get_sync_data(self):
        if self.at_date:
            employee_ids = self.employee_ids.mapped('id') if self.employee_ids else []
            duration = 0

            if self.to_date and self.to_date > self.at_date:
                duration = (self.to_date - self.at_date).days
            
            if not employee_ids and duration == 0:
                # Allow Get and Sync data for all employees for 01 day
                employee_ids = self.env['hr.employee'].search([('working', '=', True)]).mapped('id')
            
            servers = ['CMC']
            self.env['hr.attendance.raw']._get_raw_data(at_date=self.at_date, employee_ids=employee_ids, duration=duration, servers=servers)
            self.env['hr.attendance.raw']._sync_attendance_record(at_date=self.at_date, employee_ids=employee_ids, duration=duration, commit_size=100)
    
    def action_print_monthly_reports(self):
        if not self.monthly_report and not self.at_date:
            raise UserError(_('Need at_date and report_name to export the report!'))
        report_names = {
            'overtime': 'at_monthly_overtime_report_py3o',
            'estimate_overtime': 'at_monthly_estimate_overtime_report_py3o',
            'workingtime': 'at_monthly_workingtime_report_py3o',
            'leave': 'at_monthly_leave_report_py3o',
            'attendance': 'at_monthly_attendance_report_py3o',
            'ot_compensation': 'at_yearly_ot_compensation_report_py3o',
            'at_performance': 'at_yearly_performance_report_py3o',
            'leave_remain': 'at_leave_allocation_remain_py3o',
            'attendance_location': 'at_location_report_py3o'
        }
        report_name = 'kdvn_hr_attendance.{}'.format(report_names[self.monthly_report])
        if self.monthly_report == 'at_performance':
            datas = self.read()[0]
            report_data, total_works = self.report_at_performance(at_year=self.at_year)
            datas['extra_data'] = [report_data, total_works]
            res = self.env.ref(report_name).with_context(wizard_report=True).report_action(self, data=datas)  # Odoo 19: the report needs the wizard as its record
            # res["close_on_report_download"] = True
            return res
        else:
            datas = self.read()[0]
            res = self.env.ref(report_name).with_context(wizard_report=True).report_action(self, data=datas)  # Odoo 19: the report needs the wizard as its record
            # res["close_on_report_download"] = True
            return res
        # datas = self.read()[0]
        # res = self.env.ref(report_name).with_context(wizard_report=True).report_action(self, data=datas)  # Odoo 19: the report needs the wizard as its record
        # res["close_on_report_download"] = True
        # return res

    def report_ot_by_at_date(self, at_month=None, at_year=None):
        self.env.flush_all()   # raw SQL below: Odoo 19 does not flush pending ORM writes by itself
        if not at_year:
            at_year = self.at_year
        if not at_month:
            at_month = self.at_month

        # no_ot_emp_ids = self.env['hr.attendance.rule'].search([('name', '=', 'NO Overtime')], limit=1).employee_ids.mapped('id')
        # report_domain = [('at_month', '=', at_month), ('at_year', '=', at_year), ('employee_id', 'not in', no_ot_emp_ids)]
        # ats = self.env['hr.attendance'].search(report_domain)
        end_date = self.env['hr.mixin'].at_period_end(at_year, at_month)
        start_date = end_date - relativedelta(months=1)
        month_at_days = [start_date + relativedelta(days=d) for d in range((end_date - start_date).days)]
        month_sats = list(filter(lambda d: d.weekday() == 5, month_at_days))

        # s = time.process_time()

        # method 1 cost 15 ~ 20 seconds
        # res = [{
        #     'staff_no': e.code,
        #     'staff_name': e.name,
        #     'attendances': [{
        #         'at_date': at.at_date,
        #         'ot_am': at.ot_am,
        #         'ot_pm': at.ot_pm,
        #         'is_last_sat': at.at_date in month_sats[-2:]
        #     } for at in ats.filtered(lambda r: r.employee_id.id == e.id)]
        # } for e in ats.mapped('employee_id')]
        # res = list(filter(lambda e: any([at['ot_am'] + at['ot_pm'] for at in e['attendances']]), res))

        # method 2 cost under 1 seconds
        sql_string = """
            SELECT emp.code, emp.name, json_agg(att.at_date) at_dates, json_agg(COALESCE(att.ot_am, 0)) ot_ams, json_agg(COALESCE(att.ot_pm, 0)) ot_pms
            FROM hr_attendance AS att
                JOIN 
                    (SELECT a.employee_id, e.code, e.name, sum(ot_am + ot_pm) is_ot
                    FROM hr_attendance AS a
                        JOIN hr_employee AS e ON a.employee_id = e.id
                    WHERE at_month={at_month} AND at_year={at_year}
                    GROUP BY a.employee_id, e.code, e.name) AS emp
                ON att.employee_id = emp.employee_id
            WHERE emp.is_ot != 0 AND att.at_month={at_month} AND att.at_year={at_year}
            GROUP BY emp.code, emp.name
        """.format(at_month=at_month, at_year=at_year)
        self.env.cr.execute(sql_string)
        res = [{
            'staff_no': e[0],
            'staff_name': e[1],
            'attendances': [{
                'at_date': datetime.datetime.strptime(at[0], '%Y-%m-%d').date(),
                'ot_am': at[1] if at[1] else '',
                'ot_pm': at[2] if at[2] else '',
                'is_last_sat': datetime.datetime.strptime(at[0], '%Y-%m-%d').date() in month_sats[-2:]
            } for at in zip(e[2], e[3], e[4])]
        } for e in self.env.cr.fetchall()]

        for r in res:
            if len(r['attendances']) < len(month_at_days):
                for at_date in (set(month_at_days) - set([d['at_date'] for d in r['attendances']])):
                    r['attendances'].append({
                        'at_date': at_date,
                        'ot_am': '',
                        'ot_pm': '',
                        'is_last_sat': at_date in month_sats[-2:]
                    })
            ot_total = sum(map(lambda e: ((e['ot_am'] if e['ot_am'] else 0) + (e['ot_pm'] if e['ot_pm'] else 0)), r['attendances']))
            hd_total = sum(map(lambda e: ((e['ot_am'] if e['ot_am'] else 0) + (e['ot_pm'] if e['ot_pm'] else 0)) if (e['at_date'].weekday() == 6 or e['is_last_sat']) else 0, r['attendances']))
            wd_total = ot_total - hd_total
            r['wd_total'] = wd_total or ''
            r['hd_total'] = hd_total or ''

            r['attendances'].sort(key=lambda e: e['at_date'])
        # e = time.process_time()
        # print('=====', e - s)
        return res

    def report_estimate_ot_by_at_date(self, at_month=None, at_year=None):
        self.env.flush_all()   # raw SQL below: Odoo 19 does not flush pending ORM writes by itself
        if not at_year:
            at_year = self.at_year
        if not at_month:
            at_month = self.at_month

        end_date = self.env['hr.mixin'].at_period_end(at_year, at_month)
        start_date = end_date - relativedelta(months=1)
        month_at_days = [start_date + relativedelta(days=d) for d in range((end_date - start_date).days)]
        month_sats = list(filter(lambda d: d.weekday() == 5, month_at_days))

        # method 2 cost under 1 seconds
        sql_string = """
            SELECT emp.code, emp.name, json_agg(att.at_date) at_dates, json_agg(COALESCE(att.e_ot_am, 0)) ot_ams, json_agg(COALESCE(att.e_ot_pm, 0)) ot_pms
            FROM hr_attendance AS att
                JOIN 
                    (SELECT a.employee_id, e.code, e.name, sum(e_ot_am + e_ot_pm) is_ot
                    FROM hr_attendance AS a
                        JOIN hr_employee AS e ON a.employee_id = e.id
                    WHERE at_month={at_month} AND at_year={at_year}
                    GROUP BY a.employee_id, e.code, e.name) AS emp
                ON att.employee_id = emp.employee_id
            WHERE emp.is_ot != 0 AND att.at_month={at_month} AND att.at_year={at_year}
            GROUP BY emp.code, emp.name
        """.format(at_month=at_month, at_year=at_year)
        self.env.cr.execute(sql_string)
        res = [{
            'staff_no': e[0],
            'staff_name': e[1],
            'attendances': [{
                'at_date': datetime.datetime.strptime(at[0], '%Y-%m-%d').date(),
                'ot_am': at[1] if at[1] else '',
                'ot_pm': at[2] if at[2] else '',
                'is_last_sat': datetime.datetime.strptime(at[0], '%Y-%m-%d').date() in month_sats[-2:]
            } for at in zip(e[2], e[3], e[4])]
        } for e in self.env.cr.fetchall()]

        for r in res:
            if len(r['attendances']) < len(month_at_days):
                for at_date in (set(month_at_days) - set([d['at_date'] for d in r['attendances']])):
                    r['attendances'].append({
                        'at_date': at_date,
                        'ot_am': '',
                        'ot_pm': '',
                        'is_last_sat': at_date in month_sats[-2:]
                    })
            ot_total = sum(map(lambda e: ((e['ot_am'] if e['ot_am'] else 0) + (e['ot_pm'] if e['ot_pm'] else 0)), r['attendances']))
            hd_total = sum(map(lambda e: ((e['ot_am'] if e['ot_am'] else 0) + (e['ot_pm'] if e['ot_pm'] else 0)) if (e['at_date'].weekday() == 6 or e['is_last_sat']) else 0, r['attendances']))
            wd_total = ot_total - hd_total
            r['wd_total'] = wd_total or ''
            r['hd_total'] = hd_total or ''

            r['attendances'].sort(key=lambda e: e['at_date'])
        # e = time.process_time()
        # print('=====', e - s)
        return res
    
    def action_update_staff_locations(self):
        """Open the 4-step wizard (machines, preview, confirm, result)."""
        return self.env['kderp.staff.location.update.wizard'].action_open()

    def action_push_staff_locations(self):
        """Open the 3-step wizard (machine names, remote locations, confirm)."""
        return self.env['kderp.staff.location.sync.wizard'].action_open()

    def action_update_estimate_ot(self):
        at_year, at_month = self.at_year, self.at_month
        if not all([at_year, at_month]):
            raise UserError(_('Please select a date'))
        ot_ids = self.env['hr.attendance.request'].sudo().with_context(active_test=False).search([('request_type', '=', 'over_time'), ('at_id.at_year', '=', at_year), ('at_id.at_month', '=', at_month)])
        total = len(ot_ids)
        skip = 0
        for o in ot_ids:
            if o.request_in or o.request_out:
                o._compute_estimate_ot()
            else:
                skip += 1
        _logger.warning(f'Total: {total} / Skip: {skip}')

    def report_monthly_attendance(self, at_year, at_month):
        """
            - Attendance Monthly Report for current Working Employees
            - [X] TODO: add pit hours and bonus level
        """
        monthly_summaries = self.env['hr.attendance.summary'].search([('at_year', '=', at_year), ('at_month', '=', at_month)])
        res = []
        for s in monthly_summaries:
            if s.employee_id.working:
                res.append({
                    'staff_no': s.employee_id.code.strip(),
                    'name': s.employee_id.name,
                    'attendance': s.attendance_count or None,
                    'absence': s.absence_count or None,
                    'leaves': s.leaves_count or None,
                    'ot_compensation': s.exceed_ot_subtitude or None,
                    'special_holiday': s.ssh_count or None,
                    'company_holiday': s.oh_count or None,
                    'public_holiday': s.psh_count or None,
                    'total': sum([s.attendance_count, s.absence_count, s.leaves_count, s.exceed_ot_subtitude, s.ssh_count, s.oh_count, s.psh_count]) or None,
                    'wd_ot': s.allow_wd_ot or None,
                    'wd_st': s.allow_wd_st or None,
                    'hd_ot': s.allow_hd_ot or None,
                    'hd_st': s.allow_hd_st or None,
                    'ph_ot': s.allow_ph_ot or None,
                    'ph_st': s.allow_ph_st or None,
                    'bonus_ot_hours': s.bonus_ot_hours or None,
                    'bonus_ot_level': s.bonus_ot_level or None,
                })
        res = sorted(res, key=lambda r: r['staff_no'])
        return res

    def report_yearly_ot_compensation(self, at_year, at_month=1):
        """
            - Serving data for Yearly OT Compensation report
            - at_year: Year to show data
            - at_month: From with month to show. Default from 1
        """
        keys = [m for m in range(at_month, 13)]
        # employee_ids = self.env['hr.employee'].search([('working', '=', True)])
        year_at_summaries = self.env['hr.attendance.summary'].search([('at_year', '=', at_year), ('at_month', '>=', at_month)])
        res = []
        for e in year_at_summaries.mapped('employee_id').filtered('working').sorted(key=lambda x: x.code):
            ot = year_at_summaries.filtered(lambda s: s.employee_id == e)
            # if ot and any(ot.mapped('exceed_ot_subtitude')) > 0:
            ot_compensation_info = {
                'staff_no': e.code, 'name': e.name,
                # 'ot': { m: o or None for m, o in zip(keys, [r['exceed_ot_subtitude'] for r in ot])},
                'ot': { m: o for m, o in [(k, ot.filtered(lambda s: s.at_month == k).exceed_ot_subtitude or None) for k in keys]}
            }
            res.append(ot_compensation_info)
        return res

    def report_at_performance(self, at_year):
        """
            - Serving data for Yearly AT Performance
        """
        res = []
        keys = [month_abbr[m] for m in range(1, 13)]
        yearly_at_summaries = self.env['hr.attendance.summary'].search([('at_year', '=', at_year)])
        for e in yearly_at_summaries.mapped('employee_id').filtered('working').sorted(key=lambda x: x.code):
            is_maid_driver = int(bool({'House Maid', 'Driver', 'Outsource'} & set(e.category_ids.mapped('name'))))  # Somehow bool value not working in excel
            at_matrix = {month_abbr[s.at_month]: {
                'late': s.late_in_count or None, 'early': s.early_out_count or None, 'total_late_early': (s.late_in_count + s.early_out_count) or None,
                'forget': s.forget_count or None,
                # 'attendance': s.attendance_count or None, 
                # 'attendance': (s.working_days_sum - s.absence_count) or None, 
                # 'attendance': (s.attendance_count + s.leaves_count + s.oh_count + s.sh_count - s.absence_count) or None, 
                'attendance': (s.attendance_count + s.leaves_count + s.oh_count + s.sh_count) or None, 
                'working': s.working_days_sum or None} 
                for s in yearly_at_summaries.filtered(lambda r: r.employee_id == e)}
            at_none_info = {'late': None, 'early': None, 'total_late_early': None, 'forget': None, 'attendance': None, 'working': None}
            at_performance_info = {
                'staff_no': e.code, 'name': e.name, 'is_maid_driver': is_maid_driver, 
                'performance': {k: at_matrix.get(k, at_none_info) for k in keys},
            }
            at_performance_info.update({
                'sum_late_early': sum([r['total_late_early'] or 0 for r in at_performance_info['performance'].values()]) or None,
                'sum_forget': sum([r['forget'] or 0 for r in at_performance_info['performance'].values()]) or None,
                'sum_attendance': sum([r['attendance'] or 0 for r in at_performance_info['performance'].values()]) or None,
                # 'sum_working': sum([r['working'] or 0 for r in at_performance_info['performance'].values()]) or None,
            })
            # at_performance_info['attendance_rate'] = at_performance_info['sum_attendance'] / at_performance_info['sum_working'] if all([at_performance_info['sum_attendance'], at_performance_info['sum_working']]) else None
            res.append(at_performance_info)
        total_works = {m: max([s['performance'][m]['working'] or 0 for s in res] or [0]) for m in keys}
        return (res, total_works)
    
    @api.model
    def report_at_locations(self, at_month=None, at_year=None):
        self.env.flush_all()   # raw SQL below: Odoo 19 does not flush pending ORM writes by itself
        if not at_year:
            at_year = self.at_year
        if not at_month:
            at_month = self.at_month

        # end_date = self.env['hr.mixin'].at_period_end(at_year, at_month)
        # start_date = end_date - relativedelta(months=1)

        sql_string = """
            SELECT emp.code, emp.name, json_agg(att.at_date) at_dates, array_agg(ARRAY[att.check_in_location_id, att.check_out_location_id]) locations
            FROM hr_attendance AS att
                JOIN 
                    (SELECT a.employee_id, e.code, e.name, sum(ot_am + ot_pm) is_ot
                    FROM hr_attendance AS a
                        JOIN hr_employee AS e ON a.employee_id = e.id
                    WHERE at_month={at_month} AND at_year={at_year}
                    GROUP BY a.employee_id, e.code, e.name) AS emp
                ON att.employee_id = emp.employee_id
            WHERE att.at_month={at_month} AND att.at_year={at_year}
            GROUP BY emp.code, emp.name
            ORDER BY emp.code, emp.name
        """.format(at_month=at_month, at_year=at_year)
        self.env.cr.execute(sql_string)
        # raw data
        res = [{'staff_no': e[0],
                'staff_name': e[1],
                'locations': [item for l in e[3] for item in l if item]
                } for e in self.env.cr.fetchall()]
        # most frequently location
        res = [{
                'staff_no': r['staff_no'],
                'staff_name': r['staff_name'],
                'project': max(r['locations'], key=r['locations'].count) if r['locations'] else None
            } for r in res]
        # project name and SM name
        res = [{
                'number': n+1,
                'staff_no': r['staff_no'],
                'staff_name': r['staff_name'],
                'project': self.env['hr.attendance.location'].search([]).browse(r['project']).name if r['project'] else None,
                'section_manager': self.env['hr.employee'].search([('code', '=', r['staff_no'])]).admin_manager_id.name or None
            } for n, r in enumerate(res)]
        
        # print('=====', res)
        return res

    @api.model
    def action_print_current_attendance(self):
        """
            - Print current attendance record: may be 2 month if the date of print
            is is greater than 21
        """
        report_name = 'kdvn_hr_attendance.attendance_approved_report_py3o'
        today = fields.Date.context_today(self)
        company = self.env.user.company_id
        date_start = company.at_policy()['date_start'] if company else 21
        if today.day >= date_start:
            # at_years, at_months = zip(self.env['hr.attendance'].get_at_year_month(today), self.env['hr.attendance'].get_at_year_month(today - relativedelta(months=1)))
            at_year, at_month = self.env['hr.attendance'].get_at_year_month(today)
            at_year0, at_month0 = self.env['hr.attendance'].get_at_year_month(today - relativedelta(months=1))
            domain = [('employee_id.user_id.id', '=', self.env.uid), '|', '&', ('at_year','=', at_year), ('at_month', '=', at_month), '&', ('at_year','=', at_year0), ('at_month', '=', at_month0)]
        else:
            at_year, at_month = self.env['hr.attendance'].get_at_year_month(today)
            domain = [('employee_id.user_id.id', '=', self.env.uid), ('at_year','=', at_year), ('at_month', '=', at_month)]
        res_ids = self.env['hr.attendance.summary'].search(domain).mapped('id')
        res = self.env.ref(report_name).with_context(wizard_report=False).report_action(res_ids, data={})
        res["close_on_report_download"] = True
        return res

    def action_archive_old_data(self):
        """
            - Helper method to archive old data
            - hr.attendance: at_date older than 14-month
            - hr.attendance.request: at_id is archived
            - hr.leave.cover and hr.leave: data having leave_type not active for more than 14-month
            - 
        """
        # Testing old records
        # today = fields.Date.context_today(self)
        # archive_date = today - relativedelta(months=14)
        # old_at_ids = self.env['hr.attendance'].search([('at_date', '<', archive_date)])
        # old_request_ids = old_at_ids.mapped('at_request_ids')
        # old_leave_type = self.env['hr.leave.type'].search([('validity_stop', '<', archive_date)])
        # old_leave_ids = self.env['hr.leave'].search([('holiday_status_id', 'in', old_leave_type.ids)])
        # old_leave_cover_ids = old_leave_ids.mapped('leave_cover_id')

        # SQL commands
        # Except for hr_attendance sql base on 14 months INTERVAL
        # Other SQL will base on hr_attendance archived records
        old_at_ids_update_sql = """UPDATE hr_attendance SET active = false WHERE at_date < CURRENT_DATE - INTERVAL '14 months';"""
        old_request_ids_update_sql = """UPDATE hr_attendance_request SET active = false WHERE id IN (SELECT har.id FROM hr_attendance_request har JOIN hr_attendance ha ON har.at_id=ha.id WHERE har.active = false);"""
        old_leave_cover_ids_update_sql = """UPDATE hr_leave_cover SET active=false WHERE id IN (SELECT hlc.id FROM hr_leave_cover hlc JOIN hr_attendance_hr_leave_cover_rel alcr ON hlc.id=alcr.hr_leave_cover_id JOIN hr_attendance ha ON alcr.hr_attendance_id=ha.id WHERE ha.active=false)"""
        old_leave_ids_update_sql = """UPDATE hr_leave SET active=false WHERE id IN (SELECT hl.id FROM hr_leave hl JOIN hr_leave_cover hlc ON hl.leave_cover_id=hlc.id WHERE hlc.active=false)"""

        if not self.env.user.has_group('base.group_system'):
            raise UserError("Only IT admin can perform this operation!")
        
        with self.env.cr.savepoint():
            self.env.cr.execute(old_at_ids_update_sql)
            self.env.cr.execute(old_request_ids_update_sql)
            self.env.cr.execute(old_leave_cover_ids_update_sql)
            self.env.cr.execute(old_leave_ids_update_sql)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Archive Complete',
                'message': 'Old records (14 months) have been archived successfully.',
                'type': 'success',
                }
            }
        
    def action_force_done_old_data(self):
        """
            - Helper method to set old data to done status then archived them
            - Old data: from selected at_month and at_year to the past
            - !NOTE: keep for 12 months
            - !NOTE: NO need to set done
        """
        # if not self.at_date:
        #     raise UserError(_('Need at_month and at_year to proceed!'))
        AT = self.env['hr.attendance']
        date_to_archive = AT.get_start_dt(fields.Date.context_today(self), for_month=True) - relativedelta(years=1, months=-1)
        # at_date = AT.get_start_dt(self.at_date, for_month=True) + relativedelta(months=1)
        # current_end_date = AT.get_start_dt(fields.Date.context_today(self), for_month=True) + relativedelta(months=1)
        # if at_date + relativedelta(months=2) >= current_end_date:
        #     raise UserError(_('Please do NOT archive data since last 2 months!'))
        not_done_ats = AT.sudo().search([('at_date', '<', date_to_archive), ('state', '!=', 'done')])
        time_limit = 60
        start = time.process_time()
        end = None
        # not_done_ats = old_ats.filtered(lambda a: a.state != 'done')
        _logger.warning(_('Force done for {} records'.format(len(not_done_ats))))
        for at in not_done_ats:
            try:
                if not at.at_request_ids and not at.leave_cover_ids:
                    at.state_id = self.env.ref('kdvn_hr_attendance.state_done').id
                if at.at_request_ids:
                    at.at_request_ids.write({'state': 'done'})
                if at.leave_cover_ids:
                    at.leave_cover_ids.write({'state': 'done'})
                end = time.process_time()
                if end - start >= time_limit:
                    _logger.warning(_('Commit before timeout! {}'.format(end-start)))
                    self.env.cr.commit()
                    start = time.process_time()
                    end = None
                    self._compute_archive_message()
                    # break
            except Exception as e:
                # self.env.cr.rollback() # rollback when error happen
                _logger.error(_(e))
        old_ats = AT.sudo().search([('at_date', '<', date_to_archive), ('state', '=', 'done')])
        _logger.warning(_('Acrhive {} attendance records'.format(len(old_ats))))
        old_ats.write({'active': False})

        old_requests = old_ats.mapped('at_request_ids').filtered(lambda r: r.state == 'done')
        _logger.warning(_('Archive {} OT/WT records'.format(len(old_requests))))
        old_requests.write({'active': False})

    def action_ot_compensation(self):
        """
            - Add the month OT Compensation into Allocation
            - Mark last update AT Month
        """

        at_month, at_year, employee_ids = self.at_month, self.at_year, self.employee_ids
        if not at_month and not at_year:
            return False
        if not employee_ids:
            employee_ids = self.env['hr.employee'].search([('working', '=', True)])

        date_start = self.env.user.company_id.at_policy()['date_start'] or None
        if not date_start:
            _logger.error(_(f'User not belong to any company!'))
            return False

        at_start_dt = datetime.date(at_year, at_month, date_start) - relativedelta(months=1)
        at_summary = self.env['hr.attendance.summary'].search([('at_month', '=', at_month), ('at_year', '=', at_year), ('employee_id', 'in', employee_ids.mapped('id'))])
        for s in at_summary:
            ot_compensation = s['exceed_ot_subtitude']
            if ot_compensation:
                try:
                    self.env['hr.leave.allocation'].add_ot_compensation(s.employee_id.id, at_start_dt, ot_compensation)
                    _logger.warning(_(f'OT Compensation {s.employee_id.name} {at_month}-{at_year} {ot_compensation}'))
                except Exception as e:
                    _logger.error(f'Error happen {e}')

    def action_recompute_last_year_leave(self):
        """
            - Recompute last year leave to fix ot compensation errors during the year
            - 
        """
        at_year, employee_ids = self.at_year, self.employee_ids
        if not at_year:
            return False
        if not employee_ids:
            employee_ids = self.env['hr.employee'].search([('working', '=', True)])

        for e in employee_ids:
            res = self.env['hr.leave.allocation'].recompute_ot_compensation_by_year(e.id, at_year)
            _logger.info(res)
            

    def action_create_ah_leave_allocation(self):
        """
            - Create AH leave allocation for the selected month
            - Note: 01 month only
        """
        at_year, at_months = self.at_year, [self.at_month]
        self.env['hr.leave.allocation'].create_ah_allocation_for_current_period(at_year=at_year, at_months=at_months)

    def action_update_employee_subordinate(self):
        """
            - In many cases, when changing user right/group, need to update related subordinate employees
            to reflect correctly the user right to view/edit
            - This method allow such an update to reduce hassle for hr staff
        """
        all_sub_emps = self.env['hr.employee']
        for emp in self.employee_ids:
            all_sub_emps |= emp.all_childs()

        for e in all_sub_emps:
            e.compute_current_dept()
        all_sub_emps._compute_parent_users()

        _logger.warning(f"Updated {len(all_sub_emps)} employees' parent users for these parent {self.employee_ids.mapped('name')}")

    def action_update_employee_at_view_users(self):
        """
            - When having a change in staff section, need to update his/her
            - attendance records viewing users accordingly
            - Due to the performance: only allow update 01 staff at a time
        """
        if self.at_date:
            from_date = self.at_date
            force_run = False
        else:
            from_date = None
            force_run = True
        if self.employee_ids:
            for e in self.employee_ids:
                self.env['hr.attendance']._compute_view_users(employee_id=e, from_date=from_date, force_run=force_run)
                _logger.warning(f"Update view_users for {e.code} {'from ' + str(from_date) if from_date else ''}")
    
    def action_create_summer_holiday_allocation(self):
        """
            - Create Summer Holiday #### Leave Type if needed (from 21/06/#### to 30/09/####)
            - Create Summer Holiday Allocation for staff having Official Working Date equal or before 01/07/lastyear
        """
        if not self.at_date:
            raise UserError(_('Please input a year for creating Summer Holiday'))

        at_year = self.at_year
        valid_start = self.at_date
        
        # valid_start must NOT earlier than June 01
        if valid_start < datetime.date(at_year, 6, 1) or valid_start > datetime.date(at_year, 9, 30):
            raise UserError(_(f'Please input a date from Jun. 1, {at_year} to Sep. 30, {at_year}'))
        valid_stop = datetime.date(at_year, 9, 30)
        summer_hol_lt = self.env['hr.leave.type'].search([('is_special', '=', True), ('category', '=', 'summer_vacation')]).filtered(lambda t: t.validity_start.year == at_year)
        
        if not summer_hol_lt:
            summer_hol_lt = self.env['hr.leave.type'].create({
                'name': f'Summer Holiday {at_year}',
                'is_special': True,
                'category': 'summer_vacation',
                'allocation_type': 'fixed',
                'validity_start': valid_start,
                'validity_stop': valid_stop
            })
        elif len(summer_hol_lt) > 1:
            raise UserError(_(f'There is more than 01 Summer Holiday Leave Type for the year {at_year}. Please correct this error before creating Summer Holiday Allocations.'))
        else:
            summer_hol_lt.update({
                'validity_start': valid_start
            })
        
        # latest_official_working_date = datetime.date(at_year - 1, 7, 1)
        latest_official_working_date = self.at_date - relativedelta(years=1)
        valid_emps = self.env['hr.employee'].search([('working', '=', True), ('joining_date', '!=', False), ('joining_date', '<=', latest_official_working_date)])
        for e in valid_emps:
            summer_hol_al = self.env['hr.leave.allocation'].search([('employee_id', '=', e.id), ('holiday_status_id', '=', summer_hol_lt.id)], limit=1)
            if not summer_hol_al:
                summer_hol_al = self.env['hr.leave.allocation'].create({
                    'name': f'Summer Holiday {at_year}',
                    'holiday_status_id': summer_hol_lt.id,
                    'number_of_days': 2,
                    'holiday_type': 'employee',
                    'employee_id': e.id
                })
                summer_hol_al.action_approve()
            else:
                _logger.warn(_(f'Summer Holiday Allocation for {e.code} - {e.name} already existed.'))

    def action_create_summer_holiday_leaves(self):
        """
            - Quick create Summer Holiday Leaves for staffs by HR Admin
            - Limitation:
               + Only apply for Summer Holiday Leave Type
               + 
        """
        employee_ids = self.employee_ids
        from_date = self.at_date
        to_date = self.to_date
        
        if not all([employee_ids, from_date, to_date]):
            raise UserError(_(f'Please input Employees, From Date and To Date'))
        
        reason_id = self.env['hr.leave.cover.reason'].search([('code', '=', 'summer_vacation')])  # !NOTE: assuming always existed
        holiday_status_id = self.env['hr.leave.type'].search([('is_special', '=', True), ('category', '=', 'summer_vacation')]).filtered(lambda t: t.validity_start.year == from_date.year)

        if not holiday_status_id or len(holiday_status_id) > 1:
            raise UserError(_(f'Do NOT have or having more than 01 [Summer Holiday Leave Type]. Please fix this error before continue!'))
        
        for e in employee_ids:
            try:
                self.env['hr.leave.cover'].create_cover(
                    reason_id=reason_id.id, holiday_status_id=holiday_status_id.id,
                    fr_date=from_date, to_date=to_date, 
                    employee_id=e.id
                )
            except Exception as error:
                _logger.error(error)

    def action_quick_employees_input(self):
        """
            - Get data from dynamic_input field and paste into employee_ids:
               + Staff Code by line
               + Staff Code by comma
            - REF.: https://www.odoo.com/forum/help-1/odoo-13-don-t-close-a-wizard-when-click-a-button-167754
        """
        if self.dynamic_input:
            codes = self.dynamic_input.split('\n')
            employee_ids = self.env['hr.employee'].search([('code', 'in', codes)])
            self.employee_ids = [(6, 0, employee_ids.mapped('id'))]
        
            return {
                'name': 'HR Admin Control (Loaded w. employees data)',
                'view_mode': 'form',
                'view_id': False,
                'res_model': self._name,
                'domain': [],
                'context': dict(self.env.context, active_ids=self.ids),
                'type': 'ir.actions.act_window',
                'target': 'new',
                'res_id': self.id,
            }
        
        # Do nothing actions
        # both working: using latter for easy understanding
        
        # return {"type": "set_scrollTop"}  # method 1
        return {"type": "ir.actions.do_nothing"}  # method 2
    
    def action_create_public_holidays(self):
        """
            - Generate public holidays for a selected year
            - Using python module LunarCalendar
            - Ref.: https://pypi.org/project/LunarCalendar/
        """

        if self.at_year:
            at_year = self.at_year
        else:
            raise UserError(_(f'Please select a year!'))
        
        public_year = self.env['hr.holidays.public'].search([('year', '=', at_year)])
        if not public_year:
            public_year= self.env['hr.holidays.public'].create({'year': at_year})
        else:
            raise UserError(_(f'Public holidays for {at_year} existed. Please input other information manually!'))
        
        holidays = []
        solar_holidays = []
        lunar_holidays = []

        # Fixed solar days

        # International new year's day
        solar_holidays.append({'date': datetime.date(at_year, 1, 1), 'name': "International new year's day", 'is_company_day': False, 'is_substitute': False, 'variable_date': False})
        # Reunification Day
        solar_holidays.append({'date': datetime.date(at_year, 4, 30), 'name': "Reunification Day", 'is_company_day': False, 'is_substitute': False, 'variable_date': False})
        # International Labor Day
        solar_holidays.append({'date': datetime.date(at_year, 5, 1), 'name': "International Labor Day", 'is_company_day': False, 'is_substitute': False, 'variable_date': False})
        # Company Establishment Day
        solar_holidays.append({'date': datetime.date(at_year, 7, 29), 'name': "Company Establishment Day", 'is_company_day': True, 'is_substitute': False, 'variable_date': False})
        # National Day Holiday
        solar_holidays.append({'date': datetime.date(at_year, 9, 1), 'name': "National Day Holiday", 'is_company_day': False, 'is_substitute': False, 'variable_date': False})
        # National Day
        solar_holidays.append({'date': datetime.date(at_year, 9, 2), 'name': "National Day", 'is_company_day': False, 'is_substitute': False, 'variable_date': False})
        # Vietnam Culture Day
        solar_holidays.append({'date': datetime.date(at_year, 11, 24), 'name': "Vietnam Culture Day", 'is_company_day': False, 'is_substitute': False, 'variable_date': False})

        # Check substitute day. KDVN allow only if holidays are on Sunday
        for d in solar_holidays:
            holidays.append(d)
            if d['date'].weekday() == 6:  # need check duplicate dates
                if (d['date'] + relativedelta(days=1)) == Converter.Lunar2Solar(Lunar(at_year, 3, 10)).to_date() or (d['date'] + relativedelta(days=1)) in [e['date'] for e in solar_holidays]:
                    holidays.append({'date': d['date'] + relativedelta(days=2), 'name': "Substituted Holiday", 'is_company_day': False, 'is_substitute': True, 'variable_date': True})
                else:
                    holidays.append({'date': d['date'] + relativedelta(days=1), 'name': "Substituted Holiday", 'is_company_day': False, 'is_substitute': True, 'variable_date': True}   )


        # Variable lunar days
        # Hung King's commemoration day
        lunar_holidays.append({'date': Converter.Lunar2Solar(Lunar(at_year, 3, 10)).to_date(), 'name': "Hung King's commemoration day", 'is_company_day': False, 'is_substitute': False, 'variable_date': True})
        # eva, 1, 2, 3 Tet holiday
        lunar_holidays.append({'date': Converter.Lunar2Solar(Lunar(at_year, 1, 1)).to_date() - relativedelta(days=1), 'name': "Lunar New Year's Eva", 'is_company_day': False, 'is_substitute': False, 'variable_date': True})
        lunar_holidays.append({'date': Converter.Lunar2Solar(Lunar(at_year, 1, 1)).to_date(), 'name': "Lunar New Year", 'is_company_day': False, 'is_substitute': False, 'variable_date': True})
        lunar_holidays.append({'date': Converter.Lunar2Solar(Lunar(at_year, 1, 2)).to_date(), 'name': "Lunar New Year", 'is_company_day': False, 'is_substitute': False, 'variable_date': True})
        lunar_holidays.append({'date': Converter.Lunar2Solar(Lunar(at_year, 1, 3)).to_date(), 'name': "Lunar New Year", 'is_company_day': False, 'is_substitute': False, 'variable_date': True})

        for d in lunar_holidays:
            holidays.append(d)
            if d['date'] == Converter.Lunar2Solar(Lunar(at_year, 3, 10)).to_date() and d['date'].weekday() == 6:
                holidays.append({'date': d['date'] + relativedelta(days=1), 'name': "Substituted Holiday", 'is_company_day': False, 'is_substitute': True, 'variable_date': True})
        
        # Adding year_id
        for h in holidays:
            h['year_id'] = public_year.id

        self.env['hr.holidays.public.line'].create(holidays)


    def action_create_monthly_ot_holiday_records(self):
        """
            - Generate monthly OT Holiday records for the company
            - []: queue job
        """
        batch_size = 40  # How to determine this value?
        if not self.at_date:
            raise UserError(_(f'Please choose a date for determining at_year and at_month!'))
        else:
            if self.employee_ids:
                employee_ids = self.employee_ids  # For selected employees
            else:
                employee_ids = self.env['hr.employee'].search([('working', '=', True), ('ot_apply', '=', True)])  # For all working employees
            delay = len(employee_ids) >= batch_size
            batchs = [employee_ids] if not delay else [employee_ids[n:n + batch_size] for n in range(0, len(employee_ids), batch_size)]

            if delay and self.delayable:
                for batch_employee in batchs:
                    delayable = self.delayable()
                    delayable.set(description=_(f"Generate {len(batch_employee)} ot on holiday records for {self.at_month} - {self.at_year}"))
                    delayable.batch_action_create_monthly_ot_holiday_records(employee_ids=batch_employee)
                    delayable.delay()
                self.env.user.notify_danger(message=f"This action will be running in batch mode to ensure its success - Please wait for few minutes!")
            else:
                self.batch_action_create_monthly_ot_holiday_records(employee_ids=employee_ids)

    
    def batch_action_create_monthly_ot_holiday_records(self, employee_ids):
        """
            - Calling actual method to generate monthly record for ot on holiday
        """
        for e in employee_ids:
            self.env['hr.attendance.ot.holiday'].generate_monthly_record(employee_id=e, at_year=self.at_year, at_month=self.at_month)

    # def action_change_to_40_hours_working_week(self):
    #     """
    #     Docstring for action_change_to_40_hours_working_week
        
    #     !NOTE: apply from Dec. 21st, 2025
    #     """
    #     apply_date = datetime.date(2026, 12, 21)
    #     if not self.employee_ids:
    #         raise UserError(_(f'Please choose at least 01 employee to apply'))
    #     resource_calendar_id = self.env['resource.calendar'].search([('name', '=', 'KINDEN VIETNAM 40 Hours/Week')])
    #     if not resource_calendar_id:
    #         raise UserError(_(f'There is no 40-hour workin week calendar resource - Please ask IT for support!'))
    #     for e in self.employee_ids:
    #         e.resource_calendar_id = resource_calendar_id.id

    # def server_action_change_to_40_hours_working_week(self, employee_ids):
    #     """
    #     Docstring for action_change_to_40_hours_working_week
        
    #     :param employee_ids: List of employees will works as 40-hour per week

    #     !NOTE: apply from Dec. 21st, 2025
    #     """
    #     apply_date = datetime.date(2025, 12, 21)
    #     resource_calendar_id = self.env['resource.calendar'].search([('name', '=', 'KINDEN VIETNAM 40 Hours/Week')])
    #     if not resource_calendar_id:
    #         raise UserError(_(f'There is no 40-hour workin week calendar resource - Please ask IT for support!'))
    #     for e in employee_ids:
    #         e.resource_calendar_id = resource_calendar_id.id



class KderpAttendanceManagerRequest(models.Model):
    _name = 'hr.attendance.manager.request'
    _auto = False
    _description = 'Not yet approved requests by managers'

    manager_id = fields.Many2one('hr.employee', 'Manager', readonly=True)
    departments = fields.Text( readonly=True)
    total_requests = fields.Integer(readonly=True)
    ats = fields.Text(readonly=True)
    # state = fields.Char(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)

        self.env.cr.execute("""
            CREATE OR REPLACE view {} AS (
                SELECT ROW_NUMBER() OVER(ORDER BY atts.manager_id) as id, 
                    atts.manager_id manager_id, json_agg(DISTINCT atts.department_id)::text departments, count(DISTINCT atts.id) total_requests, json_agg(DISTINCT atts.id)::text ats
                FROM 
                    (SELECT att.id, att.code, att.state, att.department_id, 
                            CASE 
								WHEN att.state='waiting_fman' AND (att.approve_manager_id IS NULL) THEN sm.admin_manager_id
								WHEN att.state='waiting_fman' AND (att.approve_manager_id IS NOT NULL) THEN am.id
								ELSE gm.id END AS manager_id
                        FROM hr_attendance att
                        LEFT JOIN hr_employee sm ON att.employee_id = sm.id
					 	LEFT JOIN hr_employee gm ON sm.admin_gm_id = gm.id
						LEFT JOIN hr_employee am ON att.approve_manager_id = am.id
                    WHERE att.state IN ('waiting_fman', 'waiting_fman2')) atts
                GROUP BY atts.manager_id
                ORDER BY atts.manager_id
            )
        """.format(self._table))

    def action_open_records(self):
        for m in self:
            domain = [('id', 'in', json.loads(m.ats))]
            action = {
                "type": "ir.actions.act_window",
                "name": "Not Approve Yet - Manager {}".format(m.manager_id.name),
                "res_model": "hr.attendance",
                "views": [(False, "tree"), (False, "form")],
                "view_mode": "tree,form",
                "context": {"search_default_groupby_state": 1},
                "domain": domain
            }
            return action

    def action_send_noti_email(self):
        self.env['hr.attendance'].sudo()._send_noti_email(manager_ids=self.mapped('manager_id.id'), force_send=False)

    @api.model
    def get_waiting_request(self):
        """
            - Get managers' waiting request
        """
        uid = request.session.uid
        employee = self.env['hr.employee'].sudo().search([('user_id', '=', uid)], limit=1)
        waiting_requests = {}
        app_url = "#"
        user_groups = self.env['hr.mixin'].groups()
        if user_groups['section_manager'] or user_groups['gm']:
            if user_groups['section_manager']:
                app_url = self.env['hr.attendance'].get_full_url(model_name='hr.attendance', action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_action_for_manager').id)

            else:  # GM view
                app_url = self.env['hr.attendance'].get_full_url(model_name='hr.attendance', 
                                            action_id=self.env.ref('kdvn_hr_attendance.hr_attendance_action_for_manager_gm').id)
            man_request = self.sudo().search([('manager_id', '=', employee.id)], limit=1)
            effected_ats = self.env['hr.attendance'].sudo().browse(json.loads(man_request.ats)).filtered('on_current_month_at') if man_request.ats else []
            
            waiting_requests = {
                'app_url': app_url,
                'manager_id': employee.id,
                'ats': [{
                        'employee': d.employee_id.name, 
                        'section': d.department_id.name,
                        'date': d.at_date.strftime('%a %d-%m-%y'),
                        'state': 'Manager' if d.state_id.name == 'Manager Approve' else 'GM' if d.state_id.name == 'GM Approve' else d.state_id.name,
                        'at_status': d.status_codes,
                        'request_marks': d.request_description,
                        'action_approve': d._notify_get_action_link('controller', controller='/attendance/sm_approve' if d.state_id.name == 'Manager Approve' else '/attendance/gm_approve')
                    } for d in effected_ats]
            }
            
        return waiting_requests
    
    @api.model
    def get_user_waiting_request(self):
        """
            - Get user waiting requests (for current only)
        """
        uid = request.session.uid
        employee = self.env['hr.employee'].sudo().search([('user_id', '=', uid)], limit=1)
        app_url = "#"
        waiting_requests = {}
        effected_ats = self.env['hr.attendance'].sudo().search([('state_id.code', 'in', ['waiting_fman', 'waiting_fman2', 'refuse']), ('employee_id.user_id', '=', uid), ('on_current_month_at', '=', True)])

        waiting_requests = {
            'employee_id': employee.id,
            'app_url': app_url,
            'ats': [{
                # 'employee': d.employee_id.name, 
                # 'section': d.department_id.name,
                'date': d.at_date.strftime('%a %d-%m-%y'),
                'state': 'Manager' if d.state_id.name == 'Manager Approve' else 'GM' if d.state_id.name == 'GM Approve' else d.state_id.name,
                'at_status': d.status_codes,
                'request_marks': d.request_description,
            } for d in effected_ats]
        }

        return waiting_requests


class KderpWorkingRequestWizard(models.TransientModel):
    _name = 'hr.attendance.request.wizard'
    _description = 'Making Attendance WT and OT Requests'
    _inherit = ['hr.mixin']

    name = fields.Char('Description')
    request_date_from = fields.Date('From Date', required=True)
    request_date_to = fields.Date('To Date')
    sub_request_type_id = fields.Many2one('hr.attendance.request.type', domain="[('request_type', '=', 'working_time')]")
    department_id = fields.Many2one('hr.department')
    request_detail_ids = fields.One2many('hr.attendance.request.detail.wizard', 'request_id')
    need_description = fields.Boolean(related='sub_request_type_id.need_description', store=True)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        defaults['request_date_from'] = fields.Date.context_today(self)
        defaults['department_id'] = self.env.user.employee_id.department_id.id
        return defaults

    @api.onchange('request_date_from')
    def _onchange_date_from(self):
        for record in self:
            if record.request_date_from:
                record.request_date_to = record.request_date_from

    def _compute_dept(self):
        pass

    def save(self):
        # Save into hr.attendance.request for each employee
        request_type = 'working_time' if self.sub_request_type_id else 'over_time'
        AT = self.env['hr.attendance']
        Request = self.env['hr.attendance.request']
        new_request_ids = []
        at_dates = [self.request_date_from + relativedelta(days=d) for d in range((self.request_date_to - self.request_date_from).days + 1)] if self.request_date_to else [self.request_date_from]
        batch_id = str(uuid.uuid4()) if (len(self.request_detail_ids) > 1 or len(at_dates) > 1) else False
        for at_date in at_dates:
            for request in self.request_detail_ids:
                at_code = '-'.join(['AT', at_date.strftime('%y%m%d'), request.employee_id.code])
                at = AT.with_context(active_test=False).sudo().search([('code', '=', at_code)])
                r_obj = {
                    'employee_id': request.employee_id.id,
                    'request_type': request_type,
                    'sub_request_type_id': request.sub_request_type_id.id if request.sub_request_type_id else self.sub_request_type_id.id,
                    'name': request.name if request_type == 'over_time' else self.name,
                    'request_in': self.float_to_datetime(request.request_time_fr, at_date, employee_id=request.employee_id) if request.request_time_fr else False,
                    'request_out': self.float_to_datetime(request.request_time_to, at_date, employee_id=request.employee_id) if request.request_time_to else False,
                    'batch_id': batch_id
                    # 'request_in': datetime.datetime.combine(at_date, request.request_dt_fr.time()) if request.request_dt_fr else False,
                    # 'request_out': datetime.datetime.combine(at_date, request.request_dt_to.time()) if request.request_dt_to else False
                }
                if not at:
                    # create empty at
                    at = AT.create({
                        'code': at_code,
                        'employee_id': request.employee_id.id,
                    })
                r_obj['at_id'] = at.id
                wt_requests = Request.search([('at_id', '=', at.id), ('request_type', '=', 'working_time')])
                ot_request = Request.search([('at_id', '=', at.id), ('request_type', '=', 'over_time')])
                if ot_request and r_obj['request_type'] == 'over_time':
                    raise ValidationError(_('You already have 1 OT request!'))
                if len(wt_requests) == 2:
                    raise ValidationError(_('You alread have 2 WT requests'))
                elif wt_requests.sub_request_type_id.id == r_obj['sub_request_type_id']:
                    raise ValidationError(_('Can NOT have 2 WT requests of the same reason!'))
                new_request = Request.create(r_obj)
                new_request_ids.append(new_request.id)
                new_request.at_id._onchange_at_requests()
                # new_request.at_id._compute_at_status()
        return new_request_ids

    def submit(self):
        request_ids = self.save()
        requests = self.env['hr.attendance.request'].browse(request_ids)
        requests.action_submit()


class KderpRequestDetail(models.TransientModel):
    _name = 'hr.attendance.request.detail.wizard'
    _description = 'Detail request for each staff'

    name = fields.Char('Detail of OT Works')
    sub_request_type_id = fields.Many2one('hr.attendance.request.type', domain="[('request_type', '=', 'over_time')]")
    at_id = fields.Many2one('hr.attendance', string="AT record")
    employee_id = fields.Many2one('hr.employee', required=True)
    staff_no = fields.Char(related='employee_id.code')
    request_time_fr = fields.Float()
    request_time_to = fields.Float()
    request_id = fields.Many2one('hr.attendance.request.wizard')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        return defaults

    @api.onchange('request_id', 'employee_id', 'sub_request_type_id')
    def _onchange_ot_request(self):
        for r in self:
            if r.request_id.sub_request_type_id and r.request_id.sub_request_type_id.request_type == 'working_time':
                if r.request_id.sub_request_type_id.auto_in_out in ['in', 'both']:
                    if not r.request_time_fr:
                        r.request_time_fr = 8.0
                if r.request_id.sub_request_type_id.auto_in_out in ['out', 'both']:
                    if not r.request_time_to:
                        r.request_time_to = 17.0
            else:
                if r.sub_request_type_id.auto_in_out in ['in', 'both']:
                    if not r.request_time_fr:
                        r.request_time_fr = 8.0
                if r.sub_request_type_id.auto_in_out in ['out', 'both']:
                    if not r.request_time_to:
                        r.request_time_to = 17.0

    @api.onchange('request_id')
    def _onchange_request_id(self):
        # TODO []: domain for employee?
        for r in self:
            pass

    # CONSTRAINTS
    @api.constrains('employee_id', 'request_time_fr', 'request_time_to')
    def _validate_data(self):
        for record in self:
            if not record.employee_id:
                raise ValidationError(_('Please input employee data!'))
            # if not record.request_dt_fr or not record.request_dt_to:
            #     raise ValidationError(_('Please input both times!'))
            else:
                # compute_at_date = self.env['hr.attendance.raw'].date_by_start_hour
                pass
                # if not compute_at_date(record.request_dt_fr) == compute_at_date(record.request_dt_to):
                #     raise ValidationError(_('Times must be from the same date!'))


class KderpHrAttendanceOTHolidayManager(models.TransientModel):
    """
        Provide interface for Manager to manage and approve his/her staff ot holiday
        [TODO: ]: Loading data asynchronously at client side to avoid "too large" error
    """
    _name = 'hr.attendance.ot.holiday.manager'
    _description = 'Manager view OT Holiday'
    _inherit = ['hr.mixin']

    manager_id = fields.Many2one('hr.employee', domain=lambda self: self.get_manager_domain())
    managed_section_ids = fields.Many2many('hr.department', domain=lambda self: self.get_section_domain())
    at_year = fields.Char()
    at_month = fields.Integer()   # Odoo 12: Selection with int keys (not allowed in Odoo 19)
    # ot_holiday_summary = fields.Html(compute='compute_ot_holiday_summary')
    wait_for_approve = fields.Boolean('Only register employees', default=True)
    ot_holiday_ids = fields.Many2many('hr.attendance.ot.holiday', string='OT Holidays', compute='compute_ot_holiday_ids', store=False)
    header_dsp = fields.Html(compute='compute_header_footer_dsp')
    footer_dsp = fields.Html(compute='compute_header_footer_dsp')
    # For filter data
    employee_id = fields.Many2one('hr.employee', domain=lambda self: self.get_employee_domain(), default=False)
    waiting_for = fields.Selection([
        ('waiting_fman', 'SM Approve'),
        ('waiting_fman2', 'GM Approve'),
        ('waiting_fman;waiting_fman2', 'SM or GM Approve'),
        ('waiting_fhr','HR Validate')
    ], default=False)
    no_sat_working = fields.Boolean('Only no_SAT_working employees', default=False)

    # override this method in hr.mixin to avoid conflict (hr.mixin need employee_id as a field)
    def _compute_buttons_visible(self):
        return False
    
    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        manager_id = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)])
        defaults['manager_id'] = self.env.context.get('default_manager_id', None) or (manager_id.id if (manager_id and manager_id.id in self.env['hr.department'].search([]).mapped('manager_id.id')) else False)
        today = fields.Date.context_today(self)
        at_year, at_month = self.get_at_year_month(today)
        defaults['at_year'], defaults['at_month'] = str(at_year), at_month
        defaults['managed_section_ids'] = self.env['hr.department'].search(self.get_section_domain()).mapped('id')
        return defaults

    @api.onchange('manager_id', 'employee_id')
    def onchange_manager_emplolyee_id(self):
        section_domain = expression.AND([[('manager_id', '=', self.manager_id.id)] if self.manager_id else [], [('id', '=', self.employee_id.admin_dept_id.id)] if self.employee_id else []])
        section_ids = self.env['hr.department'].search(section_domain)
        self.managed_section_ids = [(6,False,section_ids.mapped('id'))]
        return {
            'domain': {
                'employee_id': ['|', ('admin_manager_id', '=', self.manager_id.id), ('admin_gm_id', '=', self.manager_id.id)] if self.manager_id else self.get_employee_domain()
            }
        }
    
    @api.model
    def get_manager_domain(self):
        user_groups = self.groups()
        is_admin = self.env.user.has_group('base.group_system')
        is_hr_admin = user_groups.get('hr_staff', False)
   
        if is_hr_admin or is_admin:
            # HR Admin can see all managers
            # sm_ids = self.env['hr.employee'].sudo().search([]).mapped('admin_manager_id.id')
            # gm_ids = self.env['hr.employee'].sudo().search([]).mapped('admin_gm_id.id')
            # return [('id', 'in', list(set(sm_ids + gm_ids)))]  # All managers
            return [('id', 'in', self.env['hr.department'].search([]).mapped('manager_id.id'))]
        elif user_groups.get('section_manager', False) or user_groups.get('gm', False):
            # SM/GM manager only
            return [('user_id', '=', self.env.uid)]
        else:
            return [('id', '<', 0)]
    
    @api.model
    def get_section_domain(self):
        user_groups = self.groups()
        is_admin = self.env.user.has_group('base.group_system')
        is_hr_admin = user_groups.get('hr_staff', False)
        if is_admin or is_hr_admin:
            # Admin or HR Admin can see all sections
            return []
        elif user_groups.get('section_manager', False) or user_groups.get('gm', False):
            # Section manager or GM can see only their managed sections
            return ['|', ('manager_id.user_id.id', '=', self.env.uid), ('parent_id.manager_id.user_id.id', '=', self.env.uid)]
        else:
            # Other users can see no sections
            return [('id', '<', 0)]
    
    @api.model
    def get_employee_domain(self):
        user_groups = self.groups()
        is_admin = self.env.user.has_group('base.group_system')
        is_hr_admin = user_groups.get('hr_staff', False)
        if is_admin or is_hr_admin:
            return [('ot_apply', '=', True)]
        elif user_groups.get('section_manager', False) or user_groups.get('gm', False):
            return ['|', ('admin_manager_id.user_id.id', '=', self.env.uid), ('admin_gm_id.user_id.id', '=', self.env.uid)]
        else:
            return [('id', '<', 0)]

    # @api.depends('manager_id', 'at_year', 'at_month', 'managed_section_ids', 'wait_for_approve')
    # def compute_ot_holiday_summary(self):

    #     view = self.env.ref('kdvn_hr_attendance.ot_holiday_summary')
    #     values = self.generate_ot_holiday_values(self.at_year, self.at_month)
    #     html = view.render(values, engine='ir.qweb')
    #     self.ot_holiday_summary = html
    
    @api.depends('manager_id', 'at_year', 'at_month', 'managed_section_ids', 'wait_for_approve', 'employee_id', 'waiting_for', 'no_sat_working')
    def compute_ot_holiday_ids(self):
        """
            Helper method to compute ot_holiday_ids
        """
        self.ot_holiday_ids = self.get_ot_holiday_records()
    
    def get_ot_holiday_records(self):
        user_groups = self.groups()
        is_admin = self.env.user.has_group('base.group_system')
        is_hr_admin = user_groups.get('hr_staff', False)
        is_admin_director = user_groups.get('director', False)
        ot_holidays = []
        if all([self.at_year, self.at_month]):
            ot_holiday_domain = [('at_year', '=', self.at_year), ('at_month', '=', self.at_month)]
            staff_domain = [('ot_apply', '=', True)]
            if is_admin or is_hr_admin or is_admin_director:
                # Admin or HR Admin can see all staff
                if self.manager_id:
                    # ot_holiday_domain += ['|', ('employee_id.admin_manager_id', '=', self.manager_id.id), ('employee_id.admin_gm_id', '=', self.manager_id.id)]
                    staff_domain = ['&','|', ('admin_gm_id', '=', self.manager_id.id), ('admin_manager_id', '=', self.manager_id.id), ('ot_apply', '=', True)]
            elif user_groups.get('section_manager', False) or user_groups.get('gm', False):
                # SM or GM can see only their managed sections
                staff_domain = ['&','|', ('admin_gm_id', '=', self.manager_id.id), ('admin_manager_id', '=', self.manager_id.id), ('ot_apply', '=', True)]
            else:
                # Other users himself/herself only
                staff_domain = [('id', '=', self.env.user.employee_id.id)]
            
            if self.employee_id:
                staff_domain.insert(0, '&')
                staff_domain.append(('id', '=', self.employee_id.id))

            staff = self.env['hr.employee'].search(staff_domain)
            ot_holiday_domain.append(('employee_id', 'in', staff.mapped('id')))
            ot_holidays = self.env['hr.attendance.ot.holiday'].search(ot_holiday_domain)
            
            if self.wait_for_approve:
                # !NOTE: performance maybe slow if too many records
                ot_holidays = ot_holidays.filtered(lambda r: any(r.ot_detail_ids.mapped(lambda d: d.ot_register and d.state != 'draft')))
            if self.waiting_for:
                ot_holidays = ot_holidays.filtered(lambda r: any(r.ot_detail_ids.mapped(lambda d: d.ot_register and d.state in self.waiting_for.split(';'))))
            
            if self.no_sat_working:
                # rc_id = self.env.company.resource_calendar_id.id
                # rc_name = 'KINDEN VIETNAM 40 Hours/Week'
                at_date = datetime.date(int(self.at_year), self.at_month, 1)
                at_rules = self.env['hr.attendance.rule'].search([('resource_calendar_id', '!=', False), ('valid_start', '<=', at_date)])
                no_sat_working_employees = at_rules.filtered(lambda r: len(r.resource_calendar_id.attendance_ids) == 2 * 5).mapped('employee_ids')
                # no_sat_working_employees = at_rules.filtered(lambda r: r.resource_calendar_id.name == rc_name).mapped('employee_ids') - at_rules.filtered(lambda r: r.resource_calendar_id.name != rc_name).mapped('employee_ids')
                if no_sat_working_employees:
                    ot_holidays = ot_holidays.filtered(lambda r: r.employee_id in no_sat_working_employees)
        return ot_holidays
    
    @api.depends('manager_id', 'at_year', 'at_month', 'managed_section_ids', 'wait_for_approve', 'employee_id', 'waiting_for', 'no_sat_working')
    def compute_header_footer_dsp(self):
        for r in self:
            r.header_dsp = f"""
                <div class="container p-0">
                    <div class="d-flex align-items-center rounded bg-transparent">
                        <div class="d-flex flex-grow-1 px-2">
                            <div class="text-block flex-fill text-danger">Showing data for {month_abbr[r.at_month]} - {r.at_year} | Manager: {r.manager_id.name or 'All'} | Employee: {r.employee_id.name or 'All'} ({len(r.ot_holiday_ids)})</div>
                        </div>
                    </div>
                </div>
            """
            # r.header_dsp = f"Showing data for {r.at_month} - {r.at_year} | Manager {r.manager_id.name or ''}"
            r.footer_dsp = 'World'

    
    def generate_ot_holiday_values(self, ot_holiday_ids=[]):
        """
            - Helper method to generate ot_holidays view for manager
            - ot_holiday_ids: list of hr.attendance.ot.holiday records => this is mostly used for client-side rendering
            - at_year: year of the ot_holiday records
            - at_month: month of the ot_holiday records
            - Returns a dict of values to be rendered in the view
            ! NOTE: this method is also called from frontend controller through _rpc method. However, in this case, self is not available
            ! NOTE: because the model is transient and the form is not saved yet.
            ! NOTE: so any access the record data through self will not work.
        """
        is_admin = self.env.user.has_group('base.group_system')
        is_hr_admin = self.groups().get('hr_staff', False)
        is_section_manager = self.groups().get('section_manager', False)
        is_gm = self.groups().get('gm', False)

        # Helper functions
        def show_approve_button(state, sm_role, gm_role):
            """
                - sm_role: Boolean, True if the user is a section manager
                - gm_role: Boolean, True if the user is a general manager
            """
            if state in ['draft', 'done', 'refuse']:
                return False
            elif state == 'waiting_fman' and ((is_admin or is_hr_admin) or (is_section_manager and sm_role)):
                return True
            elif state == 'waiting_fman2' and ((is_admin or is_hr_admin) or (is_gm and gm_role)):
                return True
            elif state == 'waiting_fhr' and (is_admin or is_hr_admin):
                return True
            else:
                return False
        def show_delete_button(state):
            """
                Only show delete button for admin, hr_admin when state is in ['refuse']
            """
            if state in ['refuse'] and (is_admin or is_hr_admin):
                return True
            else:
                return False
        def show_revise_button(state):
            """
                Only show revise button for admin, hr_admin when state is not in ['draft']
            """
            if state not in ['draft'] and (is_admin or is_hr_admin):
                return True
            else:
                return False

        values = {'ot_holiday': {}, 'headers': None, 'user': {}}
        if not ot_holiday_ids:
            ot_holiday_records = self.ot_holiday_ids
        else:
            ot_holiday_records = self.env['hr.attendance.ot.holiday'].browse(ot_holiday_ids)

        if ot_holiday_records:
            at_year, at_month = ot_holiday_records[0].at_year, ot_holiday_records[0].at_month
        else:
            return {'ot_holiday': None}  # for QWeb xml detecting as NO value

        ot_dates = self.get_ot_holidays(datetime.date(int(at_year), int(at_month), 1), no_sat_working=True)  # !NOTE: check values return must correct for the month
        ot_holiday_state = dict(self.env['hr.attendance.ot.holiday']._fields['state'].selection)
        ot_holiday_line_state = dict(self.env['hr.attendance.ot.holiday.line']._fields['state'].selection)
        
        # actual OT hours per line: one sudo recordset for all lines so the requests/attendances are prefetched together
        line_actual_hours = {l.id: (l.ot_request_id.at_id.ot_total if l.ot_request_id else 0)
                             for l in ot_holiday_records.mapped('ot_detail_ids').sudo()}
        for o in ot_holiday_records:
            action_refuse_url = '#'
            action_select_url = '/attendance/ot_holiday/select/' + str(o.id)
            info = {
                'name': o.employee_id.name, 
                'staff_no': o.employee_id.code,
                'position': o.employee_id.job_title or '',
                'section_code': o.employee_id.admin_dept_id.code,
                'section': o.employee_id.admin_dept_id.name,
                'project': o.employee_id.admin_dept_id.area_id.name or '',
                'dates': [{
                    'id': d.id,
                    'at_date': d.at_date,
                    'is_apply': d.is_apply,
                    'ot_register': d.ot_register, 
                    'ot_detail': d.ot_detail,
                    'ot_refuse': d.ot_refuse,
                    'ot_state': d.state,
                    'ot_state_name': ot_holiday_line_state[d.state],
                    'show_approve_button': show_approve_button(d.state, o.employee_id.admin_manager_id.id == self.env.user.employee_id.id, o.employee_id.admin_gm_id.id == self.env.user.employee_id.id),
                    'show_delete_button': show_delete_button(d.state),
                    'show_revise_button': show_revise_button(d.state),
                    'ot_date_actual_hours': line_actual_hours[d.id]
                    } for d in o.ot_detail_ids],
                'remark': '',
                'at_year': o.at_year,
                'at_month': o.at_month,
                'state': o.state, 'state_name': ot_holiday_state[o.state],
                # 'action_refuse': o._notify_get_action_link('controller', controller='/attendance/ot_holiday/refuse')
                # 'action_refuse': action_refuse_url,
                'action_select': action_select_url,
                'refuse_comment': ''
                }
            # Add boolean values for buttons
            info['show_approve_employee_button'] = any([d['show_approve_button'] for d in info['dates']])

            # Add employee actual hours
            info['ot_actual_hours'] = sum([d['ot_date_actual_hours'] for d in info['dates']])
            
            # Add dummy data if not enough dates
            # !NOTE: check performance
            for d in list(set(ot_dates) - set([o['at_date'] for o in info['dates']])):
                info['dates'].append({
                    'id': 0,  # dummy id
                    'at_date': d, 
                    'ot_register': False, 
                    'ot_detail': False,
                    'ot_refuse': False,
                    'ot_state': 'draft',
                    'ot_state_name': ot_holiday_line_state['draft'],
                    'show_approve_button': False,
                    'show_delete_button': False,
                    'show_revise_button': False,
                    'o_date_actual_hours': 0,
                })
            # Need to sort info['dates'] by at_date
            info['dates'].sort(key=lambda e: e['at_date'])
            
            # Headers
            if not values['headers']:
                values['headers'] = ['No.', 'Staff No.', 'Staff Name', 'Position', 'Project Name', {
                    'month': str(month_abbr[info['at_month']]) + ' - ' + info['at_year'], 'at_dates': [d['at_date'].strftime('%d-%m\n%a') for d in info['dates']]},
                    'Remark', 'Refuse', 'Actual Hours', 'Action']

            # Section
            if info['section_code'] in values['ot_holiday'].keys():
                values['ot_holiday'][info['section_code']]['section_ot'].append(info)
            else:
                values['ot_holiday'][info['section_code']] = {
                    'name': info['section'], 'code': info['section_code'], 'as_GM': o.employee_id.admin_gm_id.id == self.env.user.employee_id.id,
                    'section_ot': [info],
                }
            # Add other information for the section
            values['ot_holiday'][info['section_code']]['show_approve_section_button'] = any([r['show_approve_employee_button'] for r in values['ot_holiday'][info['section_code']]['section_ot']])
            values['ot_holiday'][info['section_code']]['section_ot_actual_hours'] = sum([r['ot_actual_hours'] for r in values['ot_holiday'][info['section_code']]['section_ot']])
            
        # User (same for every record, so built once)
        user_groups = self.groups()
        values['user'] = {
            'id': self.env.user.id,
            'name': self.env.user.name,
            'groups': user_groups,
            'is_admin': self.env.user.has_group('base.group_system'),
            'is_hr_admin': user_groups.get('hr_staff', False),
            'is_section_manager': user_groups.get('section_manager', False),
            'is_gm': user_groups.get('gm', False)
            }

        # section_lst = sorted(list({e['section'] for e in values['ot_holiday']}))
        # values['ot_holiday'].sort(key=lambda e: (e['section'], e['staff_no']))
        return values
    
    # @api.multi
    # def action_approve(self):
    #     self.ensure_one()
    #     user_groups = self.groups()
    #     ot_holidays = self.get_ot_holiday_records()
    #     # [] TODO: check SM, GM, HR
    #     # [] TODO: allow approve selected staff?
    #     for r in ot_holidays:
    #         if user_groups.get('section_manager', False):
    #             r.action_approve()
    #         elif user_groups.get('hr_staff', False):
    #             r.action_validate()
    
    #     return {
    #         'name': 'OT on holidays plan',
    #         'context': self.env.context,
    #         
    #         'view_mode': 'form',
    #         'res_model': 'hr.attendance.ot.holiday.manager',
    #         'res_id': self.id,
    #         'view_id': False,
    #         'type': 'ir.actions.act_window',
    #         'target': 'new',
    #     }
    
    def action_click_ok_button(self, staffCode, otDate):
        """
            backend action when user click OK button or Approve on frontend interface
            ot_holiday_line_id: id of model KderpAttendanceOTHolidayLine
            [X]: change to next state
            [X]: save data to model: KderpAttendanceOTHoliday
            [X]: create/update/unlink actual ot request for that date
        """
        ot_line = self.env['hr.attendance.ot.holiday.line'].search([('employee_id.code', '=', staffCode), ('at_date', '=', otDate)])
        is_admin_user = self.env.uid in [1, 2] or self.env.user.has_group('hr_attendance.group_hr_attendance_user')
        
        if ot_line and ot_line.state not in ['draft', 'done', 'refuse']:
            next_state = None
            if ot_line.state == 'waiting_fman' and (ot_line.employee_id.sudo().admin_manager_id.user_id == self.env.user or is_admin_user):
                next_state = 'waiting_fman2'
            if ot_line.state == 'waiting_fman2' and (ot_line.employee_id.sudo().admin_gm_id.user_id == self.env.user or is_admin_user):
                next_state = 'waiting_fhr'
            if ot_line.state == 'waiting_fhr' and is_admin_user:
                next_state = 'done'
            if next_state:
                ot_line.state = next_state
        
        # !NOTE: ot_line.write_ot_request() method will be called in ot_line model CRUD methods

        return {'otLine': ot_line.ot_detail, 'state': ot_line.state, 'otRequest': ot_line.ot_request_id}
    
    def action_click_ok_refuse_form(self, staffCode, otDate, refuse_comment):
        """
            backend action when user click OK button on the Refuse modal on frontend interface
            ot_holiday_line_id: id of model KderpAttendanceOTHolidayLine
            [X]: change to refuse state
            [X]: save data to model: KderpAttendanceOTHolidayLine
        """
        ot_line = self.env['hr.attendance.ot.holiday.line'].search([('employee_id.code', '=', staffCode), ('at_date', '=', otDate)])
        is_admin_user = self.env.uid in [1, 2] or 'HR Admin' in self.env.user.all_group_ids.mapped('name')
        
        if ot_line and ot_line.state not in ['draft']:
            if ot_line.state == 'waiting_fman' and (ot_line.employee_id.sudo().admin_manager_id.user_id == self.env.user or is_admin_user):
                ot_line.state = 'refuse'
            if ot_line.state == 'waiting_fman2' and (ot_line.employee_id.sudo().admin_gm_id.user_id == self.env.user or is_admin_user):
                ot_line.state = 'refuse'
            if ot_line.state == 'waiting_fhr' and is_admin_user:
                ot_line.state = 'refuse'
            if ot_line.state == 'refuse':
                ot_line.ot_refuse = refuse_comment
        
        # !NOTE: ot_line.write_ot_request() method will be called in ot_line model CRUD methods

        return {'otLine': ot_line.ot_detail, 'refuse':ot_line.ot_refuse, 'state': ot_line.state}
    
    def action_click_delete(self, staffCode, otDate):
        """
            backend action when user click Delete button on the frontend interface
            ot_holiday_line_id: id of model KderpAttendanceOTHolidayLine
            [X]: delete ot_request if exists
            [X]:!NOTE: consider between unlink and set ot_register to False
            !NOTE: same with revise
        """
        return self.action_click_revise(staffCode, otDate)
        # ot_line = self.env['hr.attendance.ot.holiday.line'].search([('employee_id.code', '=', staffCode), ('at_date', '=', otDate)])
        # is_admin_user = self.env.user.has_group('action_click_approve_employeease.group_system') or 'HR Admin' in self.env.user.all_group_ids.mapped('name')
        
        # if is_admin_user and ot_line and ot_line.state == 'refuse' and not ot_line.ot_register:
        #     ot_line.ot_register = False

        # return {'otLine': ot_line.ot_register, 'state': ot_line.state}
    
    def action_click_revise(self, staffCode, otDate):
        """
            backend action when user click Revise button on the frontend interface
            ot_holiday_line_id: id of model KderpAttendanceOTHolidayLine
            [X]: change ot_holiday_line state to draft
            [X]: save data to model: KderpAttendanceOTHolidayLine
        """
        ot_line = self.env['hr.attendance.ot.holiday.line'].search([('employee_id.code', '=', staffCode), ('at_date', '=', otDate)])
        is_admin_user = self.env.user.has_group('base.group_system') or 'HR Admin' in self.env.user.all_group_ids.mapped('name')
        
        if is_admin_user and ot_line and ot_line.state not in ['draft']:
            # Only admin or HR Admin can revise the ot line
            ot_line.update({
                'ot_register': False,
                'state': 'draft',
                'ot_refuse': ''
            })

        return {'otLine': ot_line.ot_detail, 'state': ot_line.state}
    
    def action_click_approve_employee(self, staffCode, atYear, atMonth):
        """
            - Approve all ot registers for an employee
        """
        ot_dates = self.env['hr.attendance.ot.holiday.line'].search([('state', 'not in', ['draft', 'refuse', 'done']), ('employee_id.code', '=', staffCode), ('at_year', '=', str(atYear)), ('at_month', '=', atMonth)]).mapped('at_date')
        result = []
        for otDate in ot_dates:
            result.append(self.action_click_ok_button(staffCode, otDate))
        return result
    
    def action_click_approve_section(self, sectionCode, atYear, atMonth):
        """
            - Approve all ot registers for a section
        """
        section = self.env['hr.department'].search([('code', '=', sectionCode)])
        employee_codes = section.admin_member_ids.mapped('code')
        result = []
        for staffCode in employee_codes:
            result += self.action_click_approve_employee(staffCode, atYear, atMonth)
        return result

    def action_click_info(self, atDate, staffCode):
        """
            - Return related attendance record
        """
        target_domain = [('at_date', '=', atDate), ('employee_id.code', '=', staffCode)]
        target_record = self.env['hr.attendance'].sudo().search(target_domain)

        if target_record:
            return {
                'recordId': target_record.id,
                'title': target_record.display_name
            }
        else:
            return False
    
    def action_click_at_info(self, staffCode, atYear, atMonth):
        """
            - Return related attendance summary for the month
        """
        target_domain = [('at_year', '=', atYear), ('at_month', '=', atMonth), ('employee_id.code', '=', staffCode)]
        target_record = self.env['hr.attendance.summary'].sudo().search(target_domain)
        if target_record:
            return {
                'id': target_record.id,
                'title': target_record.display_name
            }
        else:
            return False
    
    # @api.multi
    # def action_get_excel_file(self):
    #     """
    #         Return excel file of the table
    #     """
    #     datas = self.read()[0]
    #     datas['extra_data'] = self.generate_ot_holiday_values(self.at_year, self.at_month)
    #     report_name = 'kdvn_hr_attendance.ot_on_holiday_schedule_py3o'
    #     res = self.env.ref(report_name).with_context(wizard_report=True).report_action(self, data=datas)  # Odoo 19: the report needs the wizard as its record
    #     res["close_on_report_download"] = True
    #     return res
    

    def convert_html_to_pdf(self, html_content, paper_format, filename='report.pdf'):
        if not _has_weasyprint:
            raise Exception("WeasyPrint library is not installed on the server.")

        # Minimal HTML structure if the provided content is just a snippet
        full_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>{filename}</title>
                <style>
                    /* 1. Reset Box Model and Basic Margins/Padding */
                    * {{
                        box-sizing: border-box; /* Crucial for width:100% to include padding/border */
                    }}
                    html, body {{
                        margin: 0;
                        padding: 0;
                        font-family: Arial, sans-serif;
                        font-size: 10pt; /* Adjust base font size for A3 */
                    }}

                    /* 2. Page Setup for A3 Landscape */
                    @page {{
                        size: {paper_format}; /* e.g., 'A3 landscape' */
                        margin: 1cm; /* Consistent margins for the entire page */
                    }}

                    /* 3. Container for your content */
                    .report-container {{
                        width: 100%; /* Take up 100% of available page width (minus @page margins) */
                        margin: 0;
                        padding: 0; /* Ensure no extra padding pushing content out */
                    }}

                    /* 4. Table Styling for Fit-to-Width */
                    .data-table {{
                        width: 100%; /* The table itself takes 100% of its parent (.report-container) */
                        border-collapse: collapse;
                        table-layout: fixed; /* VERY IMPORTANT: Forces columns to respect defined widths */
                        margin-bottom: 1cm; /* Space after table */
                    }}

                    /* 5. Cell Styling & Content Wrapping */
                    .data-table th,
                    .data-table td {{
                        border: 1px solid #ccc;
                        /* padding: 8px;*/
                        /* text-align: left;*/
                        /*vertical-align: top;*/
                        word-wrap: break-word; /* Allows long words to break within cell */
                        overflow-wrap: break-word; /* Modern equivalent */
                    }}
                    .data-table th {{
                        background-color: #f2f2f2;
                        font-weight: bold;
                        white-space: normal; /* Allow headers to wrap */
                    }}

                    /* 6. Define Column Widths (REQUIRED with table-layout: fixed) */
                    /* Adjust these percentages so they sum up to 100% */
                    .data-table colgroup col:nth-child(1) {{ width: 10%; }} /* Example: first column 10% */
                    .data-table colgroup col:nth-child(2) {{ width: 30%; }} /* Example: second column 30% */
                    .data-table colgroup col:nth-child(3) {{ width: 20%; }}
                    .data-table colgroup col:nth-child(4) {{ width: 20%; }}
                    .data-table colgroup col:nth-child(5) {{ width: 20%; }} /* Sums to 100% */

                    /* Optional: Table Title Styling */
                    .report-title {{
                        text-align: center;
                        font-size: 16pt;
                        margin-bottom: 0.5cm;
                        padding: 0.5cm; /* Ensure padding here doesn't add to overall report-container width */
                    }}
                </style>
            </head>
            <body>
                {html_content}
            </body>
            </html>
        """
        
        pdf_bytes = io.BytesIO()
        try:
            HTML(string=full_html).write_pdf(pdf_bytes)
        except Exception as e:
            _logger.error(f"Error generating PDF with WeasyPrint: {e}")
            raise Exception(f"Error generating PDF: {e}")
        
        pdf_bytes.seek(0)
        
        # Return base64 encoded PDF and filename
        return {
            'pdf': base64.b64encode(pdf_bytes.read()).decode('utf-8'),
            'filename': filename,
        }
    
    def convert_data_to_xlsx(self, data, filename='report.xlsx', column_headers=None):
        """
        Converts a list of dictionaries (your table data) into an Excel .xlsx file.
        :param data: List of dictionaries, e.g., [{'id':1, 'name':'A'}, {'id':2, 'name':'B'}]
        :param filename: Desired name for the Excel file.
        :param column_headers: Optional list of tuples (header_text, data_key) to define column order and labels.
                               E.g., [('ID', 'id'), ('Product Name', 'product')]
                               If None, it will try to infer from the first data row.
        :return: Dict containing base64 encoded Excel data and filename.
        """
        if not _has_openpyxl:
            raise Exception("Openpyxl library is not installed on the server.")

        if not data:
            raise ValueError("No data provided for Excel conversion.")

        # Create a new workbook and select the active sheet
        wb = Workbook()
        ws = wb.active
        ws.title = "Report Data" # Set sheet title

        # Define column headers and order
        if column_headers is None:
            # Infer headers and order from the first dictionary's keys
            # This is less robust if dictionaries have varying keys
            first_row_keys = list(data[0].keys())
            column_headers = [(key.replace('_', ' ').title(), key) for key in first_row_keys]
        
        # Write headers
        header_texts = [header[0] for header in column_headers]
        ws.append(header_texts)

        # Example of basic header styling (uncomment if you need it)
        # header_font = Font(bold=True)
        # for cell in ws[1]: # First row
        #     cell.font = header_font

        # Write data rows
        for row_data in data:
            row_values = []
            for header_text, data_key in column_headers:
                value = row_data.get(data_key, '') # Get value, default to empty string if key missing
                # Add any specific type handling or formatting here if needed
                row_values.append(value)
            ws.append(row_values)

        # Auto-size columns (optional, can be performance intensive for large sheets)
        # for col in ws.columns:
        #     max_length = 0
        #     column = col[0].column_letter # Get the column name
        #     for cell in col:
        #         try: # Necessary to avoid error on empty cells
        #             if len(str(cell.value)) > max_length:
        #                 max_length = len(str(cell.value))
        #         except:
        #             pass
        #     adjusted_width = (max_length + 2)
        #     ws.column_dimensions[column].width = adjusted_width


        # Save the workbook to an in-memory byte stream
        excel_stream = io.BytesIO()
        wb.save(excel_stream)
        excel_stream.seek(0) # Rewind the stream to the beginning

        # Encode to base64 and return
        return {
            'file': base64.b64encode(excel_stream.read()).decode('utf-8'),
            'filename': filename,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
    
    
    def generate_complex_report_xlsx(self, report_title='OT Holidays', ot_holiday_ids=[]):
        """
        Generates a complex Excel report based on the provided hierarchical data.
        :param report_title: Report title.
        :param ot_holiday_ids: IDs of hr.attendance.ot.holiday model
        """
        
        if not ot_holiday_ids:
            ot_holiday_ids = self.ot_holiday_ids.mapped('id')

        if not ot_holiday_ids:
            raise UserError(_("No data provided to generate the Excel report."))
        
        ot_holiday_data, ot_headers, ot_user = self.generate_ot_holiday_values(ot_holiday_ids).values()
        # report_data = []
        # # Restructure ot_holiday_data for excel format
        # for section_code in ot_holiday_data:
        #     report_data.append({
        #         'group_title': ot_holiday_data[section_code]['name'],
        #         'members': [{
        #             'no': index + 1,
        #             'staff_no': member_ot['staff_no'],
        #             'staff_name': member_ot['name'],
        #             'position': member_ot['position'],
        #             'project_name': member_ot['project'],
        #             'daily_data': {d['at_date']: d['ot_refuse'] or d['ot_detail'] or '' for d in member_ot['dates']},
        #             'actual_hours': member_ot['ot_actual_hours']
        #         } for index, member_ot in enumerate(ot_holiday_data[section_code]['section_ot'])]
        #     })
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Data"  # Sheet name

        # Define styles
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="333366", end_color="333366", fill_type="solid") # Dark blue
        group_title_font = Font(bold=True, size=12, color="000000") # Black, slightly larger
        default_font = Font(size=10, color="000000")
        warning_font = Font(size=10, color="FF0000")
        border_style = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        align_center = Alignment(horizontal='center', vertical='center')
        align_left_wrap = Alignment(horizontal='left', vertical='center', wrapText=True)
        align_center_wrap = Alignment(horizontal='center', vertical='center', wrapText=True)
        align_middle_right = Alignment(horizontal='right', vertical='center', wrapText=False)

        # populate date_columns_raw
        # date_columns_raw = list(ot_holiday_data[0]['members'][0]['daily_data'].keys())
        # print('=====', [datetime.date(d['month'][-4:], d['at_dates'][3:4], d['at_dates'][:2]) for d in ot_headers[5]])
        # date_columns_raw = [datetime.date(d['month'][-4:], d['at_dates'][3:4], d['at_dates'][:2]) for d in ot_headers[5]]
        date_columns_raw = [datetime.date(int(ot_headers[5]['month'][-4:]), int(d[3:5]), int(d[:2])) for d in ot_headers[5]['at_dates']]

        # --- 1. Add Big Title at the beginning ---
        title_text = f'OT on Holidays schedule for {report_title}'
        title_cell_row = 1
        title_cell_col = 1
        
        # Calculate the total number of columns to merge for the title
        # Base columns: No, Staff No, Staff Name, Position, Project Name, Actual Hours, Action
        num_fixed_cols = 7 
        num_date_cols = len(date_columns_raw)
        total_cols_for_merge = num_fixed_cols + num_date_cols

        # Merge cells for the title
        # Merge from A1 to (total_cols_for_merge)1
        ws.merge_cells(start_row=title_cell_row, start_column=title_cell_col, 
                        end_row=title_cell_row, end_column=total_cols_for_merge)
        
        title_cell = ws.cell(row=title_cell_row, column=title_cell_col, value=title_text)
        title_cell.font = Font(bold=True, size=24, color="000000") # Large, bold, black font
        title_cell.alignment = Alignment(horizontal='center', vertical='center')
        
        # Set a taller row height for the title row
        ws.row_dimensions[title_cell_row].height = 40 # Adjust as needed (in points)
        
        current_row = title_cell_row + 2 # Start content 2 rows below the title

        # --- Setup Headers ---
        # Fixed Headers
        # headers = ['No.', 'Staff No.', 'Staff Name', 'Position', 'Project Name']
        headers = ot_headers[:5]

        formatted_date_headers = [d.strftime('%d-%m') for d in date_columns_raw]

        headers.extend(formatted_date_headers)
        headers.extend(ot_headers[-2:])  # No need Action column
        # Write Headers
        # Including 2 row of header, which a merge cell for grouping dates
        for col_idx, header_text in enumerate(headers, 1):
            if col_idx in list(range(1,len(ot_headers[:5]) + 1)) or col_idx in [(len(headers) - n) for n in [1,0]]:
                # 2 rows cell
                ws.merge_cells(start_row=current_row, start_column=col_idx, end_row=current_row+1, end_column=col_idx)
                cell = ws.cell(row=current_row, column=col_idx, value=header_text)
            else:  # col_idx in [6 + n in range(len(formatted_date_headers))]
                # Date group header
                if col_idx == 6:
                    total_cols_for_merge_date = col_idx + len(formatted_date_headers) - 1  # !NOTE: need -1
                    ws.merge_cells(start_row=current_row, start_column=col_idx, end_row=current_row, end_column=total_cols_for_merge_date)
                    date_title_cell = ws.cell(row=current_row, column=col_idx, value='DATES')
                    # format date_title_cell
                    date_title_cell.font = header_font
                    date_title_cell.fill = header_fill
                    date_title_cell.border = border_style
                    date_title_cell.alignment = align_center
                
                # Each date header
                cell = ws.cell(row=current_row+1, column=col_idx, value=header_text)

            # cell = ws.cell(row=current_row, column=col_idx, value=header_text)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = border_style
            cell.alignment = align_center_wrap # Center and wrap header text
            if col_idx in range(6, len(headers)-1, 1):
                ws.column_dimensions[get_column_letter(col_idx)].width = 20 # Set width for dates columns only

        # Set specific column widths for better readability
        ws.column_dimensions[get_column_letter(1)].width = 5 # No.
        ws.column_dimensions[get_column_letter(2)].width = 12 # Staff No.
        ws.column_dimensions[get_column_letter(3)].width = 25 # Staff Name
        ws.column_dimensions[get_column_letter(4)].width = 30 # Position
        ws.column_dimensions[get_column_letter(5)].width = 20 # Project Name
        # Date columns will use default 15
        ws.column_dimensions[get_column_letter(len(headers) - 1)].width = 10 # Actual Hours
        ws.column_dimensions[get_column_letter(len(headers))].width = 10 # Action (might need wrapping)

        # Set header row height and wrap text
        ws.row_dimensions[current_row].height = 30 # Set a specific height for header row
        # ws.row_dimensions[current_row].height = 45 # Set a specific height for header row

        current_row += 2 # Move to the next row for data: +2 for 2-row headers

        # --- Populate Data ---
        for section in ot_holiday_data:
        # for group in report_data:
            # Group Title Row
            ws.merge_cells(start_row=current_row, start_column=1,
                            end_row=current_row, end_column=total_cols_for_merge-2)
            group_title_cell = ws.cell(row=current_row, column=1, value=ot_holiday_data[section]['name'])
            group_title_cell.font = group_title_font
            group_title_cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid") # Light grey fill
            group_title_cell.border = border_style
            group_title_cell.alignment = align_left_wrap # Left align and wrap group title

            group_total_hours = ws.cell(row=current_row, column=total_cols_for_merge-1, value=ot_holiday_data[section]['section_ot_actual_hours'])
            group_action = ws.cell(row=current_row, column=total_cols_for_merge, value='')
            for group_cell in [group_title_cell,group_total_hours, group_action]:
                group_cell.font = group_title_font
                group_cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid") # Light grey fill
                group_cell.border = border_style
                group_cell.alignment = align_left_wrap
            
            group_total_hours.alignment = align_middle_right
            group_total_hours.number_format = '0;-0;;@'
            ws.row_dimensions[current_row].height = 20 # Group title row height
            current_row += 1

            for index, member in enumerate(ot_holiday_data[section]['section_ot'], 1):
                col_idx = 1
                # Write fixed member data
                fixed_data = [
                    index,
                    member.get('staff_no', ''),
                    member.get('name', ''),
                    member.get('position', ''),
                    member.get('project_name', '')
                ]
                for data_item in fixed_data:
                    cell = ws.cell(row=current_row, column=col_idx, value=data_item)
                    cell.font = default_font
                    cell.border = border_style
                    cell.alignment = align_left_wrap if col_idx in [3,4,5] else align_center # Align name/position/project left
                    col_idx += 1

                # Write daily data (dynamic columns)
                for d in member.get('dates', []):
                # for date_str in date_columns_raw: # Iterate through the sorted ALL dates
                    daily_str = d.get('ot_refuse', '') or d.get('ot_detail', '') # Get value or default to empty
                    cell = ws.cell(row=current_row, column=col_idx, value=daily_str)
                    cell.font = warning_font if d.get('ot_refuse', '') else default_font
                    cell.border = border_style
                    cell.alignment = align_left_wrap
                    col_idx += 1

                # Write Actual Hours and Action
                cell = ws.cell(row=current_row, column=col_idx, value=member.get('ot_actual_hours', 0))
                cell.number_format = '0;-0;;@'
                cell.font = default_font
                cell.border = border_style
                cell.alignment = align_middle_right
                col_idx += 1

                cell = ws.cell(row=current_row, column=col_idx, value='')
                cell.font = default_font
                cell.border = border_style
                cell.alignment = align_left_wrap # Wrap text for action column
                
                # --- Adjust row height dynamically for content rows ---
                # This ensures rows expand if text wraps
                ws.row_dimensions[current_row].auto_size = True # auto_size is not directly supported in openpyxl for *rows*Co
                # Instead, you need to estimate height based on content or set a minimum.
                # A common approach for wrapped text is to set a reasonable minimum,
                # and openpyxl will automatically adjust if text wraps more.
                ws.row_dimensions[current_row].height = 18 # Minimum height for data rows, adjust as needed

                current_row += 1

        excel_stream = io.BytesIO()
        wb.save(excel_stream)
        excel_stream.seek(0)

        if True or len(self):
            return {
                'file': base64.b64encode(excel_stream.read()).decode('utf-8'),
                'filename': f'{title_text}.xlsx',
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'download_excel_report', # This tag must be handled by JS
                'report_name': "Test",        # Filename for the download
                'data': base64.b64encode(excel_stream.read()).decode('utf-8'),       # Base64 encoded file content
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', # Optional, but good practice
            }
        
    def download_excel_file(self):
        self.env.user.notify_danger(message='Download Excel File for OT Holidays!')




class KderpHrAttendanceOTHoliday(models.Model):
    """
        Manage OT Registration on holidays of an at month
        Follow the company new regulations to control staff OT
        Requirement:
        - User can register for his/herself
        - Manager can register for all related staff
        - Link to hr.attendance.request to control OT register
    """
    _name = 'hr.attendance.ot.holiday'
    _description = 'OT on holidays registration'
    _inherit = ['mail.thread', 'hr.mixin']
    _order = 'employee_id, at_year desc, at_month desc'

    employee_id = fields.Many2one('hr.employee', required=True)
    at_year = fields.Char(required=True, readonly=True)
    at_month = fields.Integer(required=True, readonly=True)   # Odoo 12: Selection with int keys (not allowed in Odoo 19)
    ot_detail_ids = fields.One2many('hr.attendance.ot.holiday.line', 'ot_holiday_reg_id')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('completed', 'Completed'),
    ], default='draft')
    # ot_remark = fields.Text('Remark for the month')
    # ot_refuse = fields.Text('Refuse for the month')
    dynamic_status = fields.Text('Dynamic Status', compute='_compute_dynamic_status')
    department_id = fields.Many2one('hr.department', related='employee_id.admin_dept_id', store=True, readonly=True)
    is_locked = fields.Boolean('Locked', default=False, help="If checked, the record is locked and cannot be modified.", compute='_compute_is_locked')
    is_current = fields.Boolean(compute='_compute_is_current', search='_search_is_current')
    at_month_dsp = fields.Char(store=True, compute='_compute_is_current')

    _data_must_be_unique = models.Constraint('unique(employee_id, at_year, at_month)', 'Employee, at_year, at_month must be unique')

    def name_get(self):
        res = []
        for o in self:
            dsp_name = f'{o.employee_id.code} - OT Holiday Plan - {o.at_month}/{o.at_year}'
            res.append((o.id, dsp_name))
        return res

    def generate_monthly_record(self, employee_id=None, at_year=None, at_month=None):
        """
            Generate OT Holiday record for an employee for an at_month and at_year with sub records of OT Holiday Lines
            [X]: For history, link OT request with created OT Holiday Lines
               - If OT request in ['wating_fman', 'waiting_fman2', 'waiting_fhr', 'done'] => OT Holiday Line should be follow these states
               - If OT request in ['draft', 'refuse'] => OT Holiday Line should be in 'draft'
            [X]: Make it possible for running as scheduled action
            [X]: No SAT working employees case
        """
        today = fields.Date.context_today(self)
        if not employee_id:
            employee_id = self.employee_id or self.env.user.employee_id

        at_year_month = self.get_at_year_month(today)
        if not at_year:
            at_year = str(at_year_month[0])
        if not at_month:
            at_month = at_year_month[1]

        r = self.search([('employee_id', '=', employee_id.id), ('at_year', '=', at_year), ('at_month', '=', at_month)])
        if not r and employee_id.ot_apply:
            ot_holiday = self.create({
                'employee_id': employee_id.id,
                'at_year': at_year,
                'at_month': at_month
            })
            ot_holidays = self.get_ot_holidays(datetime.date(year=int(at_year), month=at_month, day=1), employee_id=employee_id)  # Day 1st always in the at_month, at_year
            # ot_holidays_all_sats = self.get_ot_holidays(datetime.date(year=int(at_year), month=at_month, day=1), no_sat_working=True)
            ot_holiday_lines = []
            at_domain = [('employee_id', '=', employee_id.id), ('at_date', 'in', ot_holidays)]
            at_ids = self.env['hr.attendance'].search(at_domain)
            for h in ot_holidays:
                h_is_apply = True
                ot_request = at_ids.filtered(lambda a: a.at_date == h and h_is_apply).at_request_ids.filtered(lambda req: req.request_type == 'over_time')
                h_state = 'draft'
                h_ot_request_id = False
                h_ot_detail = ''
                h_ot_refuse = ''
                h_ot_register = False
                if ot_request:
                    h_ot_detail = ot_request.name
                    h_ot_register = True
                    if ot_request.state not in ['refuse']:
                        h_ot_request_id = ot_request.id
                        h_state = 'done'
                    else:
                        h_state = 'refuse'
                        h_ot_refuse = ot_request.at_id.refuse_comment or 'Refuse'
                ot_holiday_lines.append((0, False, {
                    'ot_holiday_reg_id': ot_holiday.id,
                    'at_date': h,
                    'ot_detail': h_ot_detail,
                    'ot_request_id': h_ot_request_id,
                    'ot_refuse': h_ot_refuse,
                    'state': h_state,
                    'ot_register': h_ot_register,
                    'is_apply': h_is_apply
                }))

            ot_holiday['ot_detail_ids'] = ot_holiday_lines

    def action_submit(self):
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_attendance.group_hr_attendance_user')
        for r in self:
            if (not r.is_locked) or is_admin:
                for l in r.ot_detail_ids:
                    if l.ot_register and l.state == 'draft':
                        l.state = 'waiting_fman'

    def sync_ot_request(self):
        """
            Sync with ot requests
            - Also use for link history data
        """
        for r in self:
            for l in r.ot_detail_ids:
                l.write_ot_request()
        # for r in self:
        #     if r.state in ['waiting_fhr']:
        #         for d in r.ot_detail_ids:
        #             ot_request = self.env['hr.attendance.request'].search([('employee_id', '=', r.employee_id.id), ('at_id.at_date', '=', d.at_date), ('request_type', '=', 'over_time')])
                    
        #             if d.ot_register: 
        #                 if not ot_request:
        #                     at_id = self.env['hr.attendance'].search([('employee_id', '=', r.employee_id.id), ('at_date', '=', d.at_date)])
        #                     if not at_id:
        #                         at_code = '-'.join(['AT', d.at_date.strftime('%y%m%d'), r.employee_id.code])
        #                         at_id = self.env['hr.attendance'].sudo().create({
        #                             'employee_id': r.employee_id.id,
        #                             'code': at_code
        #                         })
        #                     sub_request_type_id = self.env['hr.attendance.request.type'].search([('request_type', '=', 'over_time'), ('code', '=', 'both')])
        #                     ot_request = self.env['hr.attendance.request'].sudo().create({
        #                         'at_id': at_id.id,
        #                         'name': d.ot_detail,
        #                         'request_type': 'over_time', 
        #                         'sub_request_type_id': sub_request_type_id.id,
        #                         'request_in': datetime.datetime.combine(d.at_date, datetime.time(1,0,0)),
        #                         'request_out': datetime.datetime.combine(d.at_date, datetime.time(10,0,0))
        #                     })
        #                     ot_request.action_revise()
        #             else:
        #                 if ot_request:
        #                     if ot_request.state in ['draft', 'waiting_fman']:
        #                         ot_request.action_revise()
        #                         ot_request.unlink()
        #                     else:
        #                         raise UserError(_(f'The OT Request for {ot_request.at_id.at_date} was already approved! Cannot change data!'))
        
    def set_ot_holiday_status(self, ot_holiday_ids):
        """
            ot_holiday_ids: list of ids number
        """
        ot_holidays = self.env['hr.attendance.ot.holiday'].search([]).browse(ot_holiday_ids)
        for ot_holiday in ot_holidays:
            if all(ot_holiday.ot_detail_ids.mapped(lambda l: l.state in ['draft', 'done'])):
                ot_holiday.state = 'completed'
            else:
                ot_holiday.state = 'draft'

    def _compute_dynamic_status(self):
        """
            Compute dynamic status for the ot holiday record
            This is used to display the status in the view
        """
        for r in self:
            if r.state == 'draft':
                r.dynamic_status = 'Draft'
            elif r.state == 'completed':
                r.dynamic_status = 'Completed'
            else:
                r.dynamic_status = 'Unknown'

    def _compute_is_locked(self):
        """
            locked for user if the record is not current (at_year and at_month is not current)
            - Locked for data in past
            - Loccked for data further more than 01 month in future
        """
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_attendance.group_hr_attendance_user')
        current_year, current_month = self.get_at_year_month(fields.Date.context_today(self))
        current_date = datetime.date(current_year, current_month, 1)
        for r in self:
            r_current_date = datetime.date(int(r.at_year), r.at_month, 1)
            # r.is_locked = not is_admin and (r.at_year != str(current_year) or r.at_month != current_month)
            r.is_locked = not is_admin and ((r_current_date < current_date) or (r_current_date - relativedelta(months=1) > current_date))
            # If any ot_detail_ids is not draft, then the record is locked
            # This prevents users from modifying the record after it has been submitted

    @api.depends('at_year', 'at_month')
    def _compute_is_current(self):
        today = fields.Date.context_today(self)
        for o in self:
            o.is_current = today < (datetime.date(int(o.at_year), int(o.at_month), 1) + relativedelta(months=1))
            o.at_month_dsp = month_abbr[o.at_month] + '-' + o.at_year
    
    @api.model
    def _search_is_current(self, operator, value):
        today = fields.Date.context_today(self)
        this_at_year, this_at_month = self.get_at_year_month(today)
        last_at_month = (this_at_month - 1) if this_at_month > 1 else 12
        last_at_year = this_at_year if last_at_month < 12 else (this_at_year - 1)
        this_month_domain = [('at_year', '=', str(this_at_year)), ('at_month', '=', this_at_month)]
        last_month_domain = [('at_year', '=', str(last_at_year)), ('at_month', '=', last_at_month)]
        if operator == '=' and value == True:
            return expression.OR([this_month_domain, last_month_domain])
        else:
            return []


    # ===== CRUD =====

    # ===== CONSTRAINTS =====


class KderpHrAttendanceOTHolidayLine(models.Model):
    """
        OT Holiday details
        [TODO: ]: Lock user to edit when done (only admin or HR Admin can edit)
        [TODO: ]: Actions: to submit, create/link related ot_request
    """
    _name = 'hr.attendance.ot.holiday.line'
    _inherit = ['mail.thread']
    _description = 'OT on holidays detail'
    _order = 'at_date'

    ot_holiday_reg_id = fields.Many2one('hr.attendance.ot.holiday', ondelete='cascade', required=True)
    employee_id = fields.Many2one(related='ot_holiday_reg_id.employee_id')
    at_year = fields.Char(related='ot_holiday_reg_id.at_year')
    at_month = fields.Integer(related='ot_holiday_reg_id.at_month')
    at_date = fields.Date(required=True)
    ot_register = fields.Boolean(default=False)
    ot_detail = fields.Text()
    ot_request_id = fields.Many2one('hr.attendance.request')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_fman', 'Manager Approve'),
        ('waiting_fman2', 'GM Approve'),
        ('waiting_fhr', 'HR Validate'),
        ('done', 'Done'),
        ('refuse', 'Refuse')
    ], default='draft')
    ot_remark = fields.Text('Remark')
    ot_refuse = fields.Text('Refuse')
    is_admin = fields.Boolean('Is Admin', compute='_compute_is_admin')
    holiday_type = fields.Selection([
        ('Sun', 'SUN'),
        ('Sat', 'SAT'),
        ('SH', 'SH'),
        ('OH', 'OH'),
        ('H', 'H')
    ], compute='_compute_holiday_type')
    # For no sat working employees
    is_apply = fields.Boolean(default=False, readonly=True)

    _ot_holiday_line_unique = models.Constraint('unique(ot_holiday_reg_id, at_date)', 'Employee, Month, Year, At Date')

    def _compute_is_admin(self):
        """
            Compute is_admin field to check if the user is admin or HR Admin
            This is used to control the access rights of the user
        """
        for r in self:
            r.is_admin = r.env.user.has_group('base.group_system') or r.env.user.has_group('hr_attendance.group_hr_attendance_user')
    

    def write_ot_request(self):
        """
            - Create or update ot request for this employee and this date
            - If ot_register is True, create ot request
            - If ot_register is False, unlink ot request if it is in draft or waiting_fman state
            - The ot_request will be in 'draft' state for avoiding conflict with ot_request constraints
        """
        def remove_ot_request(ot_request):
            """
                Helper function to remove ot request
                ot_request: hr.attendance.request record
            """
            if ot_request.state in ['draft', 'waiting_fman']:
                ot_request.action_revise()
                ot_request.sudo().unlink()  # !NOTE: need sudo
            else:
                raise UserError(_(f'The OT Request of {ot_request.employee_id.name} at {ot_request.at_id.at_date} was already approved! Cannot change data!'))

        at_policy = self.env.user.company_id.at_policy()
        ot_request_before = at_policy['ot_request_before']
        # today = fields.Date.context_today(self)
        for r in self:
            ot_request_id = self.env['hr.attendance.request'].search([('request_type', '=', 'over_time'), ('employee_id', '=', r.employee_id.id), ('at_id.at_date', '=', r.at_date)])
            ot_before = self.env['hr.mixin'].request_cutoff(ot_request_before, r.at_date)
            if not r.ot_register:
                if ot_request_id:
                    try:
                        remove_ot_request(ot_request_id)
                        r.ot_request_id = False
                    except UserError as e:
                        _logger.error(_(f'The OT Request of {r.employee_id.name} at {r.at_date} was already approved! Cannot change data!'))
                    except Exception as e:
                        raise e
                    
            elif r.state == 'done':
                if not ot_request_id:
                    at_id = self.env['hr.attendance'].search([('employee_id', '=', r.employee_id.id), ('at_date', '=', r.at_date)])
                    if not at_id:
                        at_code = '-'.join(['AT', r.at_date.strftime('%y%m%d'), r.employee_id.code])
                        at_id = self.env['hr.attendance'].sudo().create({
                            'employee_id': r.employee_id.id,
                            'code': at_code
                        })
                        at_id._compute_at_date()

                    # [X] TODO: check 'both' sub_request_type_id because some users may not have this type => cause contraint error
                    allow_morning_ot = self.env['hr.attendance']._at_rules(employee_id=r.employee_id.id, at_date=r.at_date).get('allow_morning_ot', False)
                    if allow_morning_ot:
                        sub_request_type_id = self.env['hr.attendance.request.type'].search([('request_type', '=', 'over_time'), ('code', '=', 'both')])
                    else:
                        sub_request_type_id = self.env['hr.attendance.request.type'].search([('request_type', '=', 'over_time'), ('code', '=', 'pm')])
                    
                    try:
                        set_draft = self.env.context.get('set_draft', True)
                        ot_request_id = self.env['hr.attendance.request'].sudo().with_context(set_draft=set_draft).create({
                            'at_id': at_id.id,
                            'name': r.ot_detail,
                            'request_type': 'over_time', 
                            'sub_request_type_id': sub_request_type_id.id,
                            'request_in': datetime.datetime.combine(r.at_date, datetime.time(1,0,0)) if allow_morning_ot else False,
                            'request_out': datetime.datetime.combine(r.at_date, datetime.time(10,0,0))
                        })
                        r.ot_request_id = ot_request_id.id
                    except Exception as e:
                        _logger.error(e)
                        raise e
                else:
                    r.ot_request_id = ot_request_id.id
                
                if ot_request_id and (ot_before and datetime.datetime.now().astimezone(vn_tz).replace(tzinfo=None) > ot_before):
                    # If ot_holiday request was approved too late => need allow_late_ot and submit
                    ot_request_id.at_id.allow_late_ot = True
                    ot_request_id.with_context(ot_holiday_auto_create=True).action_submit()

            elif r.state == 'refuse':
                # !NOTE: should remove only if in current attendance period
                # !NOTE: if in the past, just ignore
                if ot_request_id:
                    try:
                        if ot_request_id.state == 'refuse' and ot_request_id.create_date < r.create_date and ot_request_id.at_id.refuse_comment:
                            r.ot_refuse = ot_request_id.at_id.refuse_comment
                        remove_ot_request(ot_request_id)
                    except Exception as e:
                        _logger.error(e)
                        raise e
                    r.ot_request_id = False
            else:
                pass  # Do nothing if state is not in ['done', 'refuse']
        
            # Notification to UI
            approve_user_ids = [1, 2, r.employee_id.sudo().admin_manager_id.user_id.id, r.employee_id.sudo().admin_gm_id.user_id.id]
            # notify_users = self.env['res.users'].sudo().search([]).filtered(lambda u: u.id == r.employee_id.sudo().admin_manager_id.user_id.id or u.has_group('base.group_system') or u.has_group('hr_attendance.group_hr_attendance_user'))
            notify_users = self.env['res.users'].sudo().search([('id', 'in', approve_user_ids)])
            for u in notify_users:
                u.sudo().notify_danger(message='Please refresh UI for holiday!')
            self._notify_data_change(notify_users)
    
    def _notify_data_change(self, user_ids):
        """
        Helper method to send a notification to the Odoo Bus.
        :user_ids: List of IDs of related users
        """
        # Define a unique channel. A common pattern is (db_name, channel_name, user_id/None).
        # Using a global channel here so all sessions in the DB get it.
        channel = 'ot_holiday_manager_ui_refesh'   # Odoo 19 bus: a plain channel name (Odoo 12 used (dbname, name))

        message = {
            'type': 'ot_holiday_line_changed',
            'user_ids': user_ids,
            'message': _("OT Holidays Schedule has been updated by another session. You may want to refresh."),
            'timestamp': fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        # Send the message to the bus
        self.env['bus.bus'].sudo()._sendone(channel, 'ot_holiday_line_changed', message)
        _logger.warning(f"Bus notification sent for OT Holidays change: {message}")
    
    def _compute_holiday_type(self):
        # one search for all lines instead of one per line
        holiday_lines = {}
        for h in self.env['hr.holidays.public.line'].search([('date', 'in', self.mapped('at_date'))]):
            holiday_lines.setdefault(h.date, h)
            if holiday_lines[h.date] != h:
                holiday_lines[h.date] = h.browse()  # more than one holiday on that date: same as "not a single line" before
        for r in self:
            wd = r.at_date.weekday()
            holiday_date = holiday_lines.get(r.at_date, self.env['hr.holidays.public.line'])
            if holiday_date and len(holiday_date) == 1:
                if holiday_date.is_company_day:
                    r.holiday_type = 'OH'
                elif holiday_date.is_substitute:
                    r.holiday_type = 'H'
                else:
                    r.holiday_type = 'SH'
            else:
                if wd == 6:
                    r.holiday_type = 'Sun'
                elif wd == 5:
                    r.holiday_type = 'Sat'
                else:
                    r.holiday_type = None


    # ===== CONSTRAINTS =====
    @api.constrains('ot_register')
    def validate_actual_ot_request(self):
        for r in self:
            if r.ot_register == False:
                if r.ot_request_id:
                    if r.ot_request_id.state not in  ['draft', 'waiting_fman']:
                        raise ValidationError(_(f'You already registered OT Request for this day: {r.employee_id.code} {r.at_date}, please modify your OT Request first!'))
                    
    @api.constrains('at_date', 'ot_detail')
    def validate_at_date_is_holiday(self):
        for r in self:
            ot_holidays_all_sats = r.ot_holiday_reg_id.get_ot_holidays(r.at_date, no_sat_working=True)
            if r.at_date not in ot_holidays_all_sats:
                raise ValidationError(_(f'AT Date must be in the list of this month Holidays: {ot_holidays_all_sats}'))
            elif r.at_date not in r.ot_holiday_reg_id.get_ot_holidays(r.at_date, employee_id=r.employee_id) and r.is_apply:
                raise ValidationError(_(f'You are not allowed for OT Holiday on this day: {r.at_date}'))


    # ===== CRUD =====
    @api.model_create_multi
    def create(self, vals_list):
        """Odoo 19 passes a list of dicts; the Odoo 12 body below handles one dict at a time."""
        records = self.browse()
        for vals in vals_list:
            records |= self._legacy_create(vals)
        return records

    def _legacy_create(self, values):
        created_ids = super().create(values)
        for ot_line in created_ids:
            ot_line.write_ot_request()
        return created_ids   # Odoo 12 returned None here (not allowed by Odoo 19 create)

    def write(self, values):
        # [TODO: ]: any changes should trigger UI to refresh
        # TODO [X]: Manually post message to hr.attendance.ot.holiday about the change for better management
        _super = super().write(values)
        run_update_ot_request = False
        states = dict(self.env['hr.attendance.ot.holiday.line']._fields['state'].selection)
        if 'state' in values:
            if self.ot_holiday_reg_id:
                self.ot_holiday_reg_id.set_ot_holiday_status([self.ot_holiday_reg_id.id])
                self.ot_holiday_reg_id.message_post(body=f'OT register on {self.at_date} **state** changed to **{states[self.state]}** by **{self.write_uid.name}**')
                run_update_ot_request = True
        if 'ot_register' in values:
            if values.get('ot_register', False):
                if self.state == 'draft' and self.ot_detail:
                    self.state = 'waiting_fman'
                    run_update_ot_request = True
            else:
                if self.state == 'waiting_fman':
                    self.state = 'draft'
                    run_update_ot_request = True
        if run_update_ot_request:
            self.write_ot_request()

        return _super



class KderpAttendanceOTHolidayManagerRequest(models.Model):
    _name = 'hr.attendance.ot.holiday.manager.request'
    _auto = False
    _description = "Not yet approved OT Holiday requests group-by managers"

    manager_id = fields.Many2one('hr.employee', 'Manager', readonly=True)
    departments = fields.Text(readonly=True)
    total_requests = fields.Integer(readonly=True)
    othls = fields.Text('OT Holiday requests', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE view {} AS (
                SELECT ROW_NUMBER() OVER(ORDER BY oths.manager_id) as id, 
                oths.manager_id manager_id, json_agg(DISTINCT oths.admin_dept_id)::text departments, count(DISTINCT oths.id) total_requests, json_agg(DISTINCT oths.id)::text othls
                FROM
                (SELECT oth.id, oth.at_date, oth.employee_id, oth.admin_dept_id, oth.ot_detail, oth.ot_refuse, oth.state, 
                    CASE 
                        WHEN oth.state='waiting_fman' THEN sm.admin_manager_id
                        ELSE gm.id END AS manager_id
                    FROM (SELECT ohl.id, ohl.at_date, oh.employee_id, he.admin_dept_id, ohl.ot_detail, ohl.ot_refuse, ohl.state 
                            FROM hr_attendance_ot_holiday_line ohl
                            JOIN hr_attendance_ot_holiday oh ON ohl.ot_holiday_reg_id = oh.id
                            LEFT JOIN hr_employee he ON oh.employee_id = he.id) AS oth
                    LEFT JOIN hr_employee sm ON oth.employee_id = sm.id
                    LEFT JOIN hr_employee gm ON sm.admin_gm_id = gm.id
                    WHERE oth.state IN ('waiting_fman', 'waiting_fman2')) oths
                GROUP BY oths.manager_id
                ORDER BY oths.manager_id
            )
        """.format(self._table))

    def action_open_records(self):
        for m in self:
            ot_holiday_line_ids = self.env['hr.attendance.ot.holiday.line'].search([]).browse(json.loads(m.othls))
            waiting_for_states = list(set(ot_holiday_line_ids.mapped('state')))
            if len(waiting_for_states) == 1:
                waiting_for = waiting_for_states[0]
            elif len(waiting_for_states) > 1:
                waiting_for = 'waiting_fman;waiting_fman2'
            else:
                waiting_for = False
            action = {
                "type": "ir.actions.act_window",
                "name": "Not Approve Yet - Manager {}".format(m.manager_id.name),
                "res_model": "hr.attendance.ot.holiday.manager",
                # "views": [(False, "tree"), (False, "form")],
                "view_mode": "form",
                "target": "new",
                "context": {
                    'default_manager_id': m.manager_id.id,
                    'default_waiting_for': waiting_for
                }
            }
            return action
    
    def action_send_noti_email(self):
        self.env['hr.attendance'].sudo()._send_noti_email(manager_ids=self.mapped('manager_id.id'), force_send=False)