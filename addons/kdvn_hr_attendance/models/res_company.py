import datetime
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Company attendance policy or at_rules for everyone
    rule_at_start_date = fields.Integer('AT first day', default=21)
    rule_day_start_hour = fields.Integer('AT day start at', default=6)
    rule_working_start_hour = fields.Integer('AT working start at', default=8)
    rule_late_in_early_out = fields.Integer('Late in', default=5)
    rule_absence = fields.Integer('Absence', default=30)
    rule_special_ot_hour = fields.Char('Special OT hours', default='22:06', help="Pleaes use the format 'HH:HH'")
    rule_delay_duration = fields.Integer('Delay duration (days)', default=2, help="Number of days the system waiting before concluding AT status")
    rule_early_offset_max = fields.Integer('Early check-in limit (minutes)', default=120, help="Maximum minutes before the day start that a rule or an early_in request may allow (TM-04). Default 120 = 2 hours.")
    # GM approval limits (RQ-12): a limit with a value is applied automatically at the HR step, empty (0) = HR decides by hand
    gm_leave_days_limit = fields.Float('GM: leave days over', digits=(4, 1), help="A leave request longer than this many days goes to the GM after the HR step. 0 = off.")
    gm_absence_days_limit = fields.Float('GM: Absence days over', digits=(4, 1), help="A leave request with more than this many Absence (unpaid) days goes to the GM. 0 = off.")
    gm_ot_over_hours_limit = fields.Float('GM: OT hours over the limit', digits=(4, 1), help="An OT request goes to the GM when the staff's OT of the month is more than this many hours over the allowed OT. 0 = off.")
    gm_late_request = fields.Boolean('GM: late requests', help="An OT or working time request registered after the cutoff (allowed by HR) goes to the GM.")
    ot_comp_category_ids = fields.Many2many('hr.employee.category', 'kderp_company_ot_comp_category_rel', 'company_id', 'category_id',
                                            string='OT compensated by leave (tags)',
                                            help="Staff with one of these tags have no OT payment: their OT is computed and compensated by leave (OT-07). Empty = tag G8 (the value used before this setting existed).")
    app_start_date = fields.Date(default=datetime.date(2022, 2, 21), help="The date attendance app started to use officially.")
    lock_months = fields.Integer('Period lock (months)', default=3, help="Attendance periods that ended more than this many months ago are locked: their payroll values (status, OT, absence) and the requests and leaves on those days cannot change unless an HR Admin unlocks them. 0 = no lock.")
    # ot_request_before = fields.Char(default=False, help="Duration (in hour) from 17:00 OT Request has to be submitted HH:MM dd-mm-yyyy")
    ot_request_before = fields.Datetime(default=False, help="Duration (in hour) from 17:00 OT Request has to be submitted")
    wt_request_before = fields.Datetime(default=False, help="Duration (in hour) from 17:00 WT Request has to be submitted")
    leave_request_before = fields.Datetime(default=False, help="Duration (in hour) from 17:00 Leave Request has to be submitted")

    # CMC Face Server information
    face_server = fields.Char('Face server url')
    face_login = fields.Char('Face server login email')
    face_password = fields.Char('Face server password')

    # Other settings
    description_size = fields.Integer(help="Maximum size user can input in the field Description of his/her request", default=25)
    last_query_dt = fields.Datetime(help="Store last query datetime for use in schedule action with continuous mode", default=False)
    query_duration = fields.Integer(help="Duration for each query in minutes", default=5)
    att_help_urls = fields.Char("Instruction URLs for ATT app", help="Separate URLs by comma.", default=False)

    def write(self, values):
        self.env['hr.attendance'].clear_at_rules_memo()
        return super().write(values)

    def ot_comp_categories(self):
        """Employee tags whose OT is compensated by leave (setting, default G8)."""
        self.ensure_one()
        return self.ot_comp_category_ids or self.env['hr.employee.category'].search([('name', '=', 'G8')])

    def at_policy(self):
        self.ensure_one()
        policy = {
            'date_start': self.rule_at_start_date,
            'day_start': self.rule_day_start_hour,
            'working_start': self.rule_working_start_hour,
            'late_in': self.rule_late_in_early_out,
            'early_out': 0,  # no more early out policy
            'absence': self.rule_absence,
            'delay_duration': self.rule_delay_duration,
            'early_offset_max': self.rule_early_offset_max,
            'app_start_date': self.app_start_date,
            # relativedelta(**{'hours': 10, 'minutes': 30})
            # 'ot_request_before': relativedelta(**dict(zip(['hours', 'minutes'], list(map(lambda e: int(e), self.ot_request_before.split(':')))))) if self.ot_request_before else None,
            'ot_request_before': self.ot_request_before,
            'wt_request_before': self.wt_request_before,
            'leave_request_before': self.leave_request_before
        }
        policy['special_ot'] = list(map(lambda e: int(e), self.rule_special_ot_hour.split(':')))
        return policy

    @api.constrains('rule_early_offset_max')
    def _check_early_offset_max(self):
        for c in self:
            if c.rule_early_offset_max < 0:
                raise ValidationError(_('Early check-in limit cannot be negative.'))

    @api.constrains('rule_at_start_date')
    def _check_at_start_date(self):
        for c in self:
            if not 1 <= c.rule_at_start_date <= 28:
                raise ValidationError(_('AT first day must be between 1 and 28.'))

    @api.constrains('rule_special_ot_hour', 'ot_request_before', 'wt_request_before', 'leave_request_before')
    def validate_special_ot_format(self):
        pattern = r'([01]\d|2[0-4]):([01]\d|2[0-4])'
        # request_before_pattern = '^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$'
        # print('=====', request_before_pattern, self.ot_request_before, re.match(request_before_pattern, self.ot_request_before))
        for r in self:
            if not re.match(pattern, r.rule_special_ot_hour):
                raise ValidationError(_('You should use format "HH:MM" as in "22:06"'))
            # if r.ot_request_before and not re.match(request_before_pattern, r.ot_request_before):
            #     raise ValidationError(_('Please use format "HH:MM" as in "05:30"'))


