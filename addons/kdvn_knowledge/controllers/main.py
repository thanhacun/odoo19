import werkzeug
from odoo import http
from odoo.http import request
from odoo.tools import html_escape


class KderpGuide(http.Controller):

    @http.route('/kderp/guide/<path:key>', type='http', auth='user')
    def open_guide(self, key, **kwargs):
        """Fixed address of a guide page: menus link here, the page can move or be renamed."""
        Page = request.env['document.page']
        page = Page.kderp_page_by_key(key)
        if not page:
            return werkzeug.wrappers.Response(
                '<html><body style="font-family:sans-serif;padding:40px">'
                '<h3>Guide not found</h3><p>No guide page "%s" (yet). '
                '<a href="/web">Back to Odoo</a></p></body></html>' % html_escape(key),
                status=404,
                mimetype='text/html',
            )
        return werkzeug.utils.redirect(Page._kderp_reader_url(page))
