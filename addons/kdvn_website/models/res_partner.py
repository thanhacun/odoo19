from urllib.parse import quote

from odoo import api, fields, models


class ResPartner(models.Model):
    """Company offices shown on the website are contacts of the company
    (Website > Site > Content > Offices, or Settings > Companies > contacts)."""
    _inherit = 'res.partner'

    kdvn_is_office = fields.Boolean(
        'Website Office', help="Show this address as an office on the website.")
    kdvn_office_name = fields.Char(
        'Office Name on Website', translate=True,
        help="e.g. 'Hanoi Head Office', 'Ho Chi Minh City Branch'.")
    kdvn_office_main = fields.Boolean(
        'Main Office', help="Also shown in the website footer and the company profile.")
    kdvn_office_sequence = fields.Integer('Office Order', default=10)
    # Reverse of res.company.partner_id: set on the company's own contact,
    # which is the head office (see res.company._kdvn_website_offices)
    kdvn_company_ids = fields.One2many('res.company', 'partner_id', string='Company of')
    kdvn_is_head_office = fields.Boolean('Head Office', compute='_compute_kdvn_is_head_office')

    def _compute_kdvn_is_head_office(self):
        for partner in self:
            partner.kdvn_is_head_office = bool(partner.sudo().kdvn_company_ids)
    kdvn_fax = fields.Char('Fax')
    kdvn_map_url = fields.Char(
        'Map Link', help="Optional Google Maps link. By default it is built from the address.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # New office from the Offices menu: attach it to the current company
        if self.env.context.get('kdvn_office_form') and 'parent_id' in fields_list and not res.get('parent_id'):
            res['parent_id'] = self.env.company.partner_id.id
        return res

    def _kdvn_office_label(self):
        self.ensure_one()
        return self.kdvn_office_name or self.name or ''

    def _kdvn_job_location(self):
        """City, country: how an office is shown on the Open Positions page."""
        self.ensure_one()
        return ', '.join(part for part in (self.city, self.country_id.name) if part)

    def _kdvn_address_line(self):
        """Street, street 2, city on one line (as used on the website)."""
        self.ensure_one()
        return ', '.join(part for part in (self.street, self.street2, self.city) if part)

    def _kdvn_map_query(self):
        """What Google Maps should show: exact coordinates (Geo Latitude /
        Longitude, standard contact fields) when filled in, else the address."""
        self.ensure_one()
        if self.partner_latitude or self.partner_longitude:
            return '%s,%s' % (self.partner_latitude, self.partner_longitude)
        return self._kdvn_address_line()

    def _kdvn_map_link(self):
        """Link that opens Google Maps: the pasted Map Link, else the coordinates/address."""
        self.ensure_one()
        return self.kdvn_map_url or 'https://www.google.com/maps/search/?api=1&query=' + quote(self._kdvn_map_query())

    def _kdvn_map_embed_url(self):
        """Map embedded in the page (no API key needed)."""
        self.ensure_one()
        return 'https://maps.google.com/maps?q=%s&z=16&output=embed' % quote(self._kdvn_map_query())
