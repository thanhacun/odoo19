from odoo import fields, models


class ResUsers(models.Model):
    """Odoo 12 kderp_base: the office a user belongs to (Ha Noi, Ho Chi Minh, Hai Phong, Nghe An, Global).
    Odoo 12 made it required; here it is not, so Odoo's own users (public, portal, OdooBot) keep working: the employee
    "Create users" action and the legacy import fill it. The Odoo 12 field general_director_id is not ported (no user used it)."""
    _inherit = 'res.users'

    location_user_id = fields.Many2one(
        'kderp.base.code', string='Location', ondelete='restrict',
        domain=lambda self: [('model_id.model', '=', 'res.users'), ('type_code', '=', 'user_location')])
