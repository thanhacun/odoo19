from odoo import fields, models


class ResCompany(models.Model):
    """Company facts shown on the website (Settings > Companies > Website Profile).

    The company address is the head office: it is always the first office on
    the website and always a main office. Other offices are contacts of the
    company marked "Website Office".
    """
    _inherit = 'res.company'

    kdvn_founding_date = fields.Date('Date of Establishment')
    kdvn_capital = fields.Char('Capital', help="As shown on the website, e.g. 'USD 1,210,000.00'.")
    kdvn_employee_count = fields.Integer('Employees')
    kdvn_employee_count_date = fields.Date('Employees as of')

    # Head office = the company's own address (stored on the company's contact)
    kdvn_head_office_name = fields.Char(
        related='partner_id.kdvn_office_name', readonly=False,
        string='Head Office Name on Website', help="e.g. 'Hanoi Head Office'.")
    kdvn_head_office_fax = fields.Char(related='partner_id.kdvn_fax', readonly=False, string='Fax')
    kdvn_head_office_latitude = fields.Float(
        related='partner_id.partner_latitude', readonly=False, string='Latitude')
    kdvn_head_office_longitude = fields.Float(
        related='partner_id.partner_longitude', readonly=False, string='Longitude')
    kdvn_head_office_map_url = fields.Char(
        related='partner_id.kdvn_map_url', readonly=False, string='Map Link')

    def _kdvn_website_offices(self, main_only=False):
        """Offices to show on the website: the company itself (head office)
        first, then its contacts marked 'Website Office' in 'Office Order'
        (only those marked 'Main Office' when main_only). Read with sudo
        because website visitors cannot read contacts."""
        self.ensure_one()
        head_office = self.sudo().partner_id
        domain = [
            ('kdvn_is_office', '=', True),
            ('parent_id', '=', head_office.id),
            ('id', '!=', head_office.id),
        ]
        if main_only:
            domain.append(('kdvn_office_main', '=', True))
        others = self.env['res.partner'].sudo().search(domain, order='kdvn_office_sequence, id')
        return head_office | others
