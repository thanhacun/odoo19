from odoo import _, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def action_open_office_addresses(self):
        """List of the other addresses of the company (not the staff contacts), with Create."""
        self.ensure_one()
        partner = self.partner_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Office Addresses'),
            'res_model': 'res.partner',
            'view_mode': 'kanban,list,form',
            'domain': [('parent_id', '=', partner.id), ('type', '!=', 'contact')],
            'context': {'default_parent_id': partner.id, 'default_type': 'other', 'default_is_company': False,
                        'default_country_id': partner.country_id.id},
        }
