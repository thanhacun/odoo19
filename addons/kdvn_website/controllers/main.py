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


class KdvnInquiryController(http.Controller):
    """Website inquiry form (/contactus): store the message, email the
    recipients, then show the 'Got it!' popup (/contactus?sent=1)."""

    # Hidden field, left empty by people; spam bots tend to fill every field.
    HONEYPOT = 'kdvn_website_url'
    MAX_LEN = {'contact_name': 128, 'company_name': 256, 'email': 254, 'phone': 64, 'message': 5000}

    def _kdvn_form_url(self, query):
        return request.env['ir.http']._url_for('/contactus') + '?' + query

    @http.route('/contactus/send', type='http', auth='public', methods=['POST'], website=True,
                sitemap=False)
    def kdvn_inquiry_send(self, **post):
        if post.get(self.HONEYPOT):
            return request.redirect(self._kdvn_form_url('sent=1'))

        values = {}
        for name, max_len in self.MAX_LEN.items():
            values[name] = (post.get(name) or '').strip()[:max_len]

        Inquiry = request.env['kdvn.website.inquiry']
        email = Inquiry._kdvn_clean_email(values['email'])
        inquiry_type = False
        if post.get('inquiry_type_id', '').isdigit():
            inquiry_type = request.env['kdvn.website.inquiry.type'].sudo().search(
                [('id', '=', int(post['inquiry_type_id']))], limit=1)
        if not values['contact_name'] or not email or not values['message']:
            return request.redirect(self._kdvn_form_url('error=1'))

        values.update({
            'email': email,
            'inquiry_type_id': inquiry_type.id if inquiry_type else False,
            'website_id': request.website.id,
            'lang': request.lang.code,
        })
        Inquiry._kdvn_create_from_website(values)
        return request.redirect(self._kdvn_form_url('sent=1'))


class KdvnCertificateController(http.Controller):

    @http.route('/company-profile/licenses-certifications/image/<int:cert_id>/<int:size>', type='http',
                auth='public', website=True, sitemap=False, readonly=True)
    def kdvn_certificate_image(self, cert_id, size=1024, **kwargs):
        """Certificate scan, only for certificates shown on the website."""
        Cert = request.env['kdvn.website.certificate']
        cert = Cert.sudo().search(Cert._kdvn_website_domain() + [('id', '=', cert_id)], limit=1)
        if not cert or not cert.image_1920:
            raise request.not_found()
        field = {128: 'image_128', 256: 'image_256', 512: 'image_512', 1024: 'image_1024'}.get(size, 'image_1920')
        stream = request.env['ir.binary']._get_image_stream_from(cert, field)
        stream.max_age = 300
        return stream.get_response(immutable=False)
