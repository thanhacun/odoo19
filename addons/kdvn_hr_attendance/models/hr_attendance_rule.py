import datetime
# from xml import dom
import pytz
from dateutil.relativedelta import relativedelta
import logging

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
# from odoo.tools.mail import plaintext2html

utc = pytz.utc
# vn_timedelta = datetime.timedelta(hours=7)
vn_tz = pytz.timezone(' '.join(pytz.country_timezones('vn')))
# vn_tz = datetime.timezone(vn_timedelta, 'VNT')

_logger = logging.getLogger(__name__)


class HrAttendanceRule(models.Model):
    _name = "hr.attendance.rule"
    _description = "Rules for HR Attendance"
    _order = "sequence"

    name = fields.Char(string='Description', required=True)
    active = fields.Boolean(default=True)
    apply_mode = fields.Selection([
        ('by_employee', 'By employee'),
        ('by_section', 'By section/project'),
        ('by_company', 'By the company')],
        default='by_employee', string='Apply mode',
        help='\tBy employee: Apply for specific employee;'
             '\tBy section/project: apply for all employee in a section/project;'
             '\tBy the company: apply for the whole company;')
    employee_ids = fields.Many2many('hr.employee')
    # employee_id = fields.Many2one('hr.employee')
    # department_id = fields.Many2one('hr.department')
    department_ids = fields.Many2many('hr.department')
    company_id = fields.Many2one('res.company', default=False)
    date_start = fields.Integer('AT start date', compute="_compute_rules_from_policy", default=False, help="The date start attendance circle for a month")
    day_start = fields.Integer(compute="_compute_rules_from_policy", help='The hour that marks the begining of a working day')
    working_start = fields.Integer(compute="_compute_rules_from_policy", help='The hour that marks check_in time')
    late_in = fields.Integer(compute="_compute_rules_from_policy", help='Minutes late')
    early_out = fields.Integer(compute="_compute_rules_from_policy", help='Minutes early')
    absence = fields.Integer(compute="_compute_rules_from_policy", help='Minutes absence')
    special_ot_hour = fields.Char(compute="_compute_rules_from_policy")
    wd_allowed_ot = fields.Float(digits=(6, 2), string="Weekday allowed OT")
    hd_allowed_ot = fields.Float(digits=(6, 2), string="(Pub.) holiday allowed OT")
    ot_apply_rule = fields.Selection([
        ('actual', 'By actual'),
        ('register', 'By register'),
        # ('both', 'Whichever smaller'),  # switched off 1 Nov 2026 (RW-04): no code computes it; kept for reference
        ], string="OT Apply Rule", default=False)
    valid_start = fields.Date(default=fields.Date.today, required=True)
    valid_stop = fields.Date()
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Applying')
    ], string="State", readonly=True, copy=False, default="draft")
    is_active = fields.Boolean(compute='_compute_is_active', search='_search_is_active', readonly=True)
    # shown in the form only (not stored, not in the list)
    affected_employee_count = fields.Integer(compute='_compute_impact', string='Employees covered')
    done_attendance_count = fields.Integer(compute='_compute_impact', string='Done attendances in period')
    can_retire = fields.Boolean(compute='_compute_can_retire')
    sequence = fields.Integer('Priority', default=99)
    force_apply = fields.Boolean(default=False, help="If set, even empty rule also count.")
    child_care_period = fields.Boolean(default=False)
    # early_check_in = fields.Boolean(default=False, help="Enable if staff check_in early before 6:00 AM. Note: no later than 5:30 AM")
    early_offset = fields.Integer(default=0, help="Number of minutes check_in early")  # this will replace early_check_in
    # override rules for special checkin cases
    # Adding 2 more cases for day_start and working_start hour
    override_day_start = fields.Integer('Override Day Start', help="Hour")
    override_working_start = fields.Integer('Override Working Start', help="Hour")
    override_late_in = fields.Integer('Override Late In', help="Minutes late")
    override_early_out = fields.Integer('Override Early Out', help="Minutes early")
    override_absence = fields.Integer('Override Absence', help="Minutes absence")
    # allow morning OT
    allow_morning_ot = fields.Boolean('Allow Morning OT', default=True)
    # Working hours calendar
    resource_calendar_id = fields.Many2one('resource.calendar', default=None)
    # OT hours allow for a month by law
    ot_hour_allowed = fields.Float(digits=(6, 2), string="By Law OT Hours")
    # No need take checkin and checkout time into account
    no_need_check = fields.Boolean('No need to check', default=False, help="Not required to check in/out")
    no_checkin = fields.Boolean(default=False, help="No check in/out staff")


    def _compute_is_active(self):
        # [X] TODO: compute based on at_date
        at_date = fields.Date.to_date(self.env.context.get('at_date', fields.Date.context_today(self)))
        for rule in self:
            rule.is_active = rule.active and rule.state == 'done' and (at_date >= rule.valid_start and (not rule.valid_stop or at_date <= rule.valid_stop))

    def _search_is_active(self, operator, value):
        today = fields.Date.context_today(self)
        # Odoo 19 rewrites ('is_active', '=', True) into ('is_active', 'in', [True]): read every operator form
        wanted = (True in value) if operator in ('in', 'not in') else bool(value)
        if operator in ('!=', 'not in'):
            wanted = not wanted
        if wanted:
            return [('active', '=', True), ('state', '=', 'done'), '&', ('valid_start', '<=', today), '|', ('valid_stop', '=', False), ('valid_stop', '>=', today)]
        else:
            return ['|', '|', '|', ('active', '=', False), ('state', '!=', 'done'), ('valid_start', '>', today), ('valid_stop', '<', today)]
    
    def _compute_rules_from_policy(self):
        company = self.env.user.company_id
        if not company:
            policy = {
                'date_start': 21, 'day_start': 6, 'working_start': 8, 'late_in': 5,
                'early_out': 0, 'absence': 30, 'special_ot': [22, 6]
            }
        else:
            policy = company.at_policy()

        # Handling override rules
        if self.override_day_start:
            policy['day_start'] = self.override_day_start
        if self.override_working_start:
            policy['working_start'] = self.override_working_start
        if self.override_late_in:
            policy['late_in'] = self.override_late_in
        if self.override_early_out:
            policy['early_out'] = self.override_early_out
        if self.override_absence:
            policy['absence'] = self.override_absence

        for rule in self:
            rule.date_start = policy['date_start']
            rule.day_start = policy['day_start']
            rule.working_start = policy['working_start']
            rule.late_in = policy['late_in']
            rule.early_out = policy['early_out']
            rule.absence = policy['absence']
            rule.special_ot_hour = ':'.join(map(lambda e: "{:02d}".format(e), policy['special_ot']))

    def action_submit(self):
        for rule in self:
            if rule.state == 'draft':
                rule.state = 'done'

    @api.depends('state', 'apply_mode', 'employee_ids', 'department_ids', 'company_id', 'valid_start', 'valid_stop')
    def _compute_impact(self):
        today = fields.Date.context_today(self)
        Employee = self.env['hr.employee'].sudo()
        Attendance = self.env['hr.attendance'].sudo().with_context(active_test=False)
        for rule in self:
            employees = done = 0
            if rule.id and rule.state == 'done':
                emp_domain = [('working', '=', True)]
                at_domain = [('at_date', '>=', rule.valid_start), ('at_date', '<=', rule.valid_stop or today), ('state', '=', 'done')]
                if rule.apply_mode == 'by_employee':
                    employees = len(rule.employee_ids)
                    at_domain.append(('employee_id', 'in', rule.employee_ids.ids))
                elif rule.apply_mode == 'by_section':
                    employees = Employee.search_count(emp_domain + [('admin_dept_id', 'in', rule.department_ids.ids)])
                    at_domain.append(('department_id', 'in', rule.department_ids.ids))
                else:
                    if rule.company_id:
                        emp_domain.append(('company_id', '=', rule.company_id.id))
                        at_domain.append(('employee_id.company_id', '=', rule.company_id.id))
                    employees = Employee.search_count(emp_domain)
                done = Attendance.search_count(at_domain)
            rule.affected_employee_count = employees
            rule.done_attendance_count = done

    @api.model
    def _retire_date(self):
        """Last day of the current attendance month (the 20th with the default policy)."""
        start_dt = self.env['hr.mixin'].get_start_dt(a_date=fields.Date.context_today(self), for_month=True)
        return start_dt + relativedelta(months=1, days=-1)

    @api.depends('state', 'active', 'valid_start', 'valid_stop')
    def _compute_can_retire(self):
        retire_date = self._retire_date()
        for rule in self:
            rule.can_retire = bool(rule.state == 'done' and rule.active and rule.valid_start <= retire_date
                                   and (not rule.valid_stop or rule.valid_stop > retire_date))

    def action_retire(self):
        """End the rule at the end of the current attendance month. Past dates keep the rule; later dates do not get it."""
        retire_date = self._retire_date()
        for rule in self:
            if not rule.can_retire:
                raise UserError(_('Rule "%s" cannot be retired: it must be applied, started, and not already ending before %s.') % (rule.name, retire_date))
            rule.valid_stop = retire_date

    def action_cancel(self):
        # Cancelling an applied rule changes every later recompute of its period (OT limits, calendars, early offsets).
        # A rule in force now can only be cancelled by an HR attendance manager (the form asks for confirmation).
        can_cancel_active = self.env.uid in (1, 2) or self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        for rule in self:
            if rule.state == 'done':
                if rule.is_active and not can_cancel_active:
                    raise UserError(_('Rule "%s" is in force now, only an HR attendance manager can cancel it. '
                                      'To end the rule use [Retire].') % rule.name)
                rule.state = 'draft'

    def action_update_early_cases(self):
        """
            - Sync data for early case
            - TODO []: Remove raw_data of previous day if there is only 01 early_checkin exist
            - by unlink all related raw_data and sync again
        """
        for rule in self:
            if rule.early_offset:
                try:
                    employee_ids = rule.employee_ids.mapped('id')
                    at_date = rule.valid_start - relativedelta(days=1)  # need to update back one day to correct check out late
                    duration = (rule.valid_stop - at_date).days if rule.valid_stop else 0
                    
                    # Unlink all old raw_data
                    raw_ats = self.env['hr.attendance.raw'].search([('check_date', '>=', at_date), ('check_date', '<=', at_date + relativedelta(days=duration)), ('employee_id', 'in', employee_ids)])
                    raw_ats.sudo().unlink()

                    self.env['hr.attendance.raw']._get_raw_data(at_date=at_date, duration=duration, employee_ids=employee_ids)
                    self.env['hr.attendance.raw']._sync_attendance_record(at_date=at_date, duration=duration, employee_ids=employee_ids)
                except Exception as e:
                    _logger.error(_(f'Error happen during update attendance records: {e}'))

    def action_open_related_records(self):
        for rule in self:
            employee_ids = rule.employee_ids.mapped('id')
            # at_date = rule.valid_start
            # duration = (rule.valid_stop - rule.valid_start).days if rule.valid_stop else 0
            domain = [('employee_id', 'in', employee_ids), ('at_date', '>=', rule.valid_start)]
            if rule.valid_stop:
                domain.append(('at_date', '<=', rule.valid_stop))
            return {
                'type': 'ir.actions.act_window',
                'name': '{} related attendances'.format(rule.name),
                
                'view_mode': 'list,form',
                'res_model': 'hr.attendance',
                'target': 'current',
                'domain': domain
            }
    
    def action_update_resource_calendar_id(self):
        """
        Docstring for action_update_resource_calendar_id
        Update employee_id resource_calendar_id based on the one defined in attendance rules (for having apply date)
        :param self
        """
        for rule in self:
            # Avoid running for by_company mode because it is too wide and may be this is the default rule
            if rule.state == 'done' and rule.apply_mode in ['by_employee', 'by_section']:
                employee_ids = rule.employee_ids | rule.department_ids.admin_member_ids
                for e in employee_ids:
                    e.resource_calendar_id = rule.resource_calendar_id


    # ====== CRUD =====
    @api.model_create_multi
    def create(self, vals_list):
        """Odoo 19 passes a list of dicts; the Odoo 12 body below handles one dict at a time."""
        records = self.browse()
        for vals in vals_list:
            records |= self._legacy_create(vals)
        return records

    def _legacy_create(self, values):
        self.env['hr.attendance'].clear_at_rules_memo()
        return super().create(values)

    def write(self, values):
        self.env['hr.attendance'].clear_at_rules_memo()
        return super().write(values)

    def unlink(self):
        self.env['hr.attendance'].clear_at_rules_memo()
        for rule in self:
            if rule.state == 'done':
                raise UserError(_('Cannot delete rule in [Applying] mode! Please ask Admin for this matter.'))
        return super().unlink()

    # ===== CONSTRAINS =====
    @api.constrains('early_offset')
    def _check_early_offset_limit(self):
        limit = self.env.user.company_id.at_policy()['early_offset_max']
        for rule in self:
            if not 0 <= rule.early_offset <= limit:
                raise ValidationError(_('Early check-in must be between 0 and %s minutes (Settings > Attendance).') % limit)

    @api.constrains('resource_calendar_id', 'valid_start', 'valid_stop')
    def _check_rc_condition(self):
        """
        Make sure when resource_calendar_id is inputted, valid_start and valid_stop must be for the at_month
        """
        start_day = self.env['hr.mixin'].at_start_day()
        for rule in self.filtered('resource_calendar_id'):
            if rule.valid_start and rule.valid_start.day != start_day:
                raise ValidationError(_('[Valid Start] must be the attendance start day (day %s of the month)') % start_day)
            # last day of the attendance month = the day before the start day
            if rule.valid_stop and (rule.valid_stop + relativedelta(days=1)).day != start_day:
                raise ValidationError(_('[Valid Stop] must be the day before the attendance start day (day %s)') % start_day)