from odoo import api, fields, models

INTERVAL_PARAM = 'kdvn_website.hero_interval'
DEFAULT_INTERVAL_MS = 10000


class KdvnWebsiteHeroSlide(models.Model):
    """A slide of the homepage slideshow.

    Kept as data (not as page content), so editing a slide never makes the
    website store a copy of the homepage view, and later code updates still
    apply. Website > Site > Content > Hero Slides.
    """
    _name = 'kdvn.website.hero.slide'
    _description = 'KDVN Website Hero Slide'
    _order = 'sequence, id'

    name = fields.Char(
        'Title', required=True, translate=True,
        help="Large text of the slide.")
    image = fields.Image(max_width=2560, max_height=2560, required=True)
    link_url = fields.Char(
        'View Detail Link',
        help="Where the 'View detail' button goes, e.g. /company-profile or "
             "https://example.com. Empty: the slide has no button.")
    sequence = fields.Integer(default=10, help="Drag the rows in the list to change the order.")
    active = fields.Boolean(default=True)

    @api.model
    def _kdvn_interval_ms(self):
        """Time each slide stays, in milliseconds (Settings > Website > Hero Slides; default 10 s)."""
        try:
            seconds = float(self.env['ir.config_parameter'].sudo().get_param(INTERVAL_PARAM) or 0)
        except ValueError:
            seconds = 0
        return int(max(seconds, 1) * 1000) if seconds > 0 else DEFAULT_INTERVAL_MS

    @api.model
    def _kdvn_slides(self):
        """Active slides in order, for the homepage (read with sudo: visitors cannot read the model)."""
        return self.sudo().search([])


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kdvn_hero_interval = fields.Integer(
        'Hero Slide Time (seconds)', config_parameter=INTERVAL_PARAM, default=10,
        help="How long each homepage slide stays before the next one. Minimum 1.")
