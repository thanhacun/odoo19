from urllib.parse import urlencode

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request

PAGE_URL = '/prominent-projects'
IMAGE_FIELDS = {128: 'image_128', 256: 'image_256', 512: 'image_512', 1024: 'image_1024'}


class KdvnWebsiteProjectController(http.Controller):

    @http.route(PAGE_URL, type='http', auth='public', website=True, sitemap=True, readonly=True)
    def prominent_projects(self, category=None, year=None, view=None, **kwargs):
        """Past Prominent Projects. Query: ?category=<slug>&year=<2025|earlier>&view=<grid|list>."""
        Category = request.env['kdvn.website.project.category'].sudo()
        category_rec = Category.search([('slug', '=', category)], limit=1) if category else Category
        view = 'list' if view == 'list' else 'grid'
        data = request.env['kdvn.website.project']._kdvn_page_data(category=category_rec or None, year=year)

        def proj_url(**changes):
            params = {'category': category_rec.slug or None, 'year': data['selected'], 'view': view}
            params.update(changes)
            params = {k: v for k, v in params.items() if v and not (k == 'year' and v == 'all')
                      and not (k == 'view' and v == 'grid')}
            return PAGE_URL + ('?' + urlencode(params) if params else '')

        values = dict(
            data,
            category=category_rec,
            view=view,
            proj_url=proj_url,
            # Breadcrumb: a category page sits under its menu item; the overview
            # shows "Kinden > Past Prominent Projects" (frames/projects-*.png)
            kdvn_page_url='%s?category=%s' % (PAGE_URL, category_rec.slug) if category_rec else '%s#overview' % PAGE_URL,
            kdvn_page_title=category_rec.name if category_rec else request.env._("Past Prominent Projects"),
        )
        return request.render('kdvn_website_project.projects_page', values)

    @http.route('/prominent-projects/image/<int:project_id>/<int:size>', type='http', auth='public',
                website=True, sitemap=False, readonly=True)
    def project_image(self, project_id, size=512, **kwargs):
        project = request.env['kdvn.website.project'].sudo().browse(project_id).exists()
        if not project or not (project.is_published or request.env.user.has_group('website.group_website_designer')):
            raise NotFound()
        stream = request.env['ir.binary']._get_image_stream_from(project, IMAGE_FIELDS.get(size, 'image_512'))
        stream.max_age = 3600
        return stream.get_response(immutable=False)
