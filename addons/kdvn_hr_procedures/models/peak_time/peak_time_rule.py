from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class KderpPeakTimeRule(models.Model):
    """Settings of the Project Peak Time procedure that are not special-case rules.

    One record (data/peak_time_rule_data.xml). Edited by the
    'Peak Time: Functional Controller / HR Manager' group; every change is
    tracked in the chatter. Read it with get_rules(), never by xml id.

    The special-case limits (registered late, long peak, registration no., block) moved to
    the shared E-Approval > Special Case Rules screen (kderp.e.approval.special.rule)."""
    _name = 'kderp.peak.time.rule'
    _inherit = ['mail.thread']
    _description = 'Project Peak Time Rules'

    name = fields.Char(required=True, default='Peak Time Rules', tracking=True)

    # Reminder to the PM
    reminder_days = fields.Integer(
        string='Remind PM before KOM peak (days)', default=14, required=True,
        tracking=True,
        help='Email the project PM this many days before KOM Peak From when the project has no '
             'peak time request yet. 0 = no reminders.')

    @api.constrains('reminder_days')
    def _check_values(self):
        if any(rule.reminder_days < 0 for rule in self):
            raise ValidationError(_('Peak time rules cannot be negative.'))

    @api.model
    def get_rules(self):
        """The rule record (sudo). If it was deleted, an unsaved record with the defaults."""
        rule = self.sudo().search([], limit=1)
        return rule or self.sudo().new({})
