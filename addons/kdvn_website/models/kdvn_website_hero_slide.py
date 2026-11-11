from odoo import api, fields, models


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
    def _kdvn_slides(self):
        """Active slides in order, for the homepage (read with sudo: visitors cannot read the model)."""
        return self.sudo().search([])
