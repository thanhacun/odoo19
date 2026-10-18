from odoo import api, fields, models


class KderpCustomerCache(models.Model):
    """Customers (partners) of the KDERP server, kept in sync by n8n."""
    _name = 'kderp.customer.cache'
    _description = 'Remote Customer (KDERP cache)'
    _order = 'name'
    _rec_names_search = ['code', 'name']

    external_id = fields.Integer('Remote Partner ID', required=True, index=True, readonly=True)
    name = fields.Char('Customer Name', required=True, index=True, readonly=True)
    code = fields.Char('Customer Code', index=True, readonly=True)
    email = fields.Char(readonly=True)

    _external_id_unique = models.Constraint('unique(external_id)', 'A remote customer can only be cached once.')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}" if record.code else record.name
