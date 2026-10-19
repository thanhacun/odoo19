import hmac
import json
import logging
from urllib.parse import urlencode

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

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

    @http.route('/api/v1/website_projects', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_projects(self, **kwargs):
        """n8n posts finished big jobs read on the KDERP servers.

        Header X-API-Key (Settings > Website Projects). Body: JSON
        {"jobs": [...]} or a form field "jobs" holding the JSON list."""
        expected = request.env['ir.config_parameter'].sudo().get_param('kdvn_website_project.api_key') or ''
        given = request.httprequest.headers.get('X-API-Key', '')
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            _logger.warning("Project import: rejected request from %s (missing or wrong API key)",
                            request.httprequest.remote_addr)
            return request.make_json_response({'status': 'error', 'message': 'Missing or invalid API key'}, status=401)
        try:
            if request.httprequest.mimetype == 'application/json':
                body = json.loads(request.httprequest.get_data(as_text=True) or '{}')
                jobs = body.get('jobs') if isinstance(body, dict) else body
            else:
                jobs = json.loads(kwargs.get('jobs') or '[]')
            if isinstance(jobs, str):
                jobs = json.loads(jobs)
            if not isinstance(jobs, list):
                raise ValueError("jobs must be a list")
        except (ValueError, TypeError) as e:
            _logger.warning("Project import: malformed payload: %s", e)
            return request.make_json_response({'status': 'error', 'message': 'Malformed payload: %s' % e}, status=400)
        try:
            result = request.env['kdvn.website.project'].sudo()._kdvn_import_jobs(jobs)
        except Exception as e:
            _logger.exception("Project import failed")
            request.env.cr.rollback()
            return request.make_json_response({'status': 'error', 'message': str(e)}, status=500)
        _logger.info("Project import: %s jobs -> %s", len(jobs), result)
        return request.make_json_response({'status': 'success', 'jobs': len(jobs), 'result': result})
