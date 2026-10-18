from odoo import fields, models


class KdvnWebsiteMedia(models.Model):
    """Images used on the website, addressed by a fixed key.

    Pages load them from /kdvn/media/<key>, so an image can be replaced here
    (Website > Site > Content > Site Media) without editing the page.
    """
    _name = 'kdvn.website.media'
    _description = 'KDVN Website Media'
    _order = 'sequence, key'

    name = fields.Char('Description', required=True, translate=True,
                       help="Where this image is used, e.g. 'Company History - intro photo'.")
    key = fields.Char(required=True, copy=False,
                      help="Fixed name used by the page code: /kdvn/media/<key>. Do not change.")
    image = fields.Image(max_width=2560, max_height=2560)
    note = fields.Text(help="Size or content hints for whoever replaces the image.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    url = fields.Char(compute='_compute_url', string='Image URL')

    _key_unique = models.Constraint('unique(key)', 'The media key must be unique.')

    def _compute_url(self):
        for media in self:
            media.url = f'/kdvn/media/{media.key}' if media.key else False
