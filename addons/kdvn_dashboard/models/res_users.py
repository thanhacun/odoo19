from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _default_dashboard_action(self):
        return self.env.ref('kdvn_dashboard.action_kderp_dashboard', raise_if_not_found=False)

    # New users open the dashboard after login (they can change it in Preferences)
    action_id = fields.Many2one(default=_default_dashboard_action)
