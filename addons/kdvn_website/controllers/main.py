from odoo import http
from odoo.http import request


class KdvnWebsiteMediaController(http.Controller):

    @http.route('/kdvn/media/<string:key>', type='http', auth='public', website=True,
                sitemap=False, readonly=True)
    def kdvn_media(self, key, width=0, height=0, **kwargs):
        """Serve the image stored under `key` (optionally resized: ?width=800)."""
        try:
            width, height = int(width or 0), int(height or 0)
        except ValueError:
            width = height = 0
        ir_binary = request.env['ir.binary']
        media = request.env['kdvn.website.media'].sudo().search([('key', '=', key)], limit=1)
        if media and media.image:
            stream = ir_binary._get_image_stream_from(media, 'image', width=width, height=height)
        else:
            stream = ir_binary._get_placeholder_stream('web/static/img/placeholder.png')
        # Same URL, changing content: let browsers re-check after 5 minutes
        stream.max_age = 300
        return stream.get_response(immutable=False)
