import re
from odoo import fields, models, api
from odoo.exceptions import ValidationError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'


    rule_at_start_date = fields.Integer('AT start date', related='company_id.rule_at_start_date', readonly=False)
    rule_day_start_hour = fields.Integer('AT day start at', related='company_id.rule_day_start_hour', readonly=False)
    rule_working_start_hour = fields.Integer('AT working start at', related='company_id.rule_working_start_hour', readonly=False)
    rule_late_in_early_out = fields.Integer('Late in | Early out', related='company_id.rule_late_in_early_out', readonly=False)
    rule_absence = fields.Integer('Absence', related='company_id.rule_absence', readonly=False)
    rule_special_ot_hour = fields.Char('Special OT hours', related='company_id.rule_special_ot_hour', readonly=False)
    rule_delay_duration = fields.Integer('Delay duration (days)', related='company_id.rule_delay_duration', readonly=False)
    rule_early_offset_max = fields.Integer('Early check-in limit (minutes)', related='company_id.rule_early_offset_max', readonly=False)
    gm_leave_days_limit = fields.Float(related='company_id.gm_leave_days_limit', readonly=False)
    gm_absence_days_limit = fields.Float(related='company_id.gm_absence_days_limit', readonly=False)
    gm_ot_over_hours_limit = fields.Float(related='company_id.gm_ot_over_hours_limit', readonly=False)
    gm_late_request = fields.Boolean(related='company_id.gm_late_request', readonly=False)
    ot_comp_category_ids = fields.Many2many(related='company_id.ot_comp_category_ids', readonly=False)
    app_start_date = fields.Date(related='company_id.app_start_date', readonly=False)
    # ot_request_before = fields.Char(related='company_id.ot_request_before', readonly=False)
    ot_request_before = fields.Datetime(related='company_id.ot_request_before', readonly=False)
    wt_request_before = fields.Datetime(related='company_id.wt_request_before', readonly=False)
    leave_request_before = fields.Datetime(related='company_id.leave_request_before', readonly=False)

    face_server = fields.Char('Face server url', related='company_id.face_server', readonly=False)
    face_login = fields.Char('Face server login email', related='company_id.face_login', readonly=False)
    face_password = fields.Char(related='company_id.face_password', readonly=False)

    description_size = fields.Integer(related='company_id.description_size', readonly=False)
    last_query_dt = fields.Datetime(related='company_id.last_query_dt', readonly=False)
    query_duration = fields.Integer(related='company_id.query_duration', readonly=False)
    att_help_urls = fields.Char(related='company_id.att_help_urls', readonly=False)
