from odoo import models


class Website(models.Model):
    _inherit = 'website'

    def _search_get_details(self, search_type, order, options):
        """Add Past Prominent Projects to the website search ('all' or 'projects')."""
        result = super()._search_get_details(search_type, order, options)
        if search_type in ('projects', 'all'):
            result.append(self.env['kdvn.website.project']._search_get_detail(self, order, options))
        return result
