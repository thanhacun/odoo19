import os
import re

from odoo import _, http
from odoo.addons.website_hr_recruitment.controllers.main import WebsiteHrRecruitment
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools import email_normalize, html_escape


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


class KdvnJobsController(WebsiteHrRecruitment):
    """Open Positions (/jobs): Odoo's routes and search, our templates, and an
    application form on the job page that answers with JSON (popups in job_apply.js)."""

    HONEYPOT = 'kdvn_website_url'
    MAX_LEN = {'partner_name': 128, 'email_from': 254, 'partner_phone': 64, 'address': 256}
    RESUME_EXTENSIONS = ('.pdf', '.doc', '.docx')
    RESUME_MAX_SIZE = 10 * 1024 * 1024
    # Sources offered in the form (utm.source names; the ones missing in the database are left out)
    SOURCE_NAMES = ('LinkedIn', 'Facebook', 'Search engine', 'Referral', 'Glassdoor', 'Monster')

    @http.route()
    def jobs(self, *args, **kwargs):
        # Always all offices: the location list in the page is the filter
        kwargs.setdefault('all_countries', True)
        response = super().jobs(*args, **kwargs)
        response.template = 'kdvn_website.jobs_index'
        # Offices of the jobs found (the counter also has 'all' and None keys)
        response.qcontext['kdvn_offices'] = [
            office for office in response.qcontext['count_per_office'] if hasattr(office, '_name')]
        return response

    @http.route()
    def job(self, job, **kwargs):
        response = super().job(job, **kwargs)
        response.template = 'kdvn_website.jobs_detail'
        response.qcontext['kdvn_sources'] = request.env['utm.source'].sudo().search(
            [('name', 'in', list(self.SOURCE_NAMES))])
        return response

    @http.route()
    def jobs_apply(self, job, **kwargs):
        # The form is on the job page
        return request.redirect('/jobs/%s#apply' % request.env['ir.http']._slug(job))

    @http.route('/jobs/apply/<model("hr.job"):job>/submit', type='http', auth='public',
                methods=['POST'], website=True, sitemap=False)
    def kdvn_job_apply_submit(self, job, **post):
        """Create the applicant. Answers {"ok": true} or {"ok": false, "errors": {field: message}}."""
        job = job.sudo()
        if not job.website_published:
            raise request.not_found()
        if post.get(self.HONEYPOT):
            return request.make_json_response({'ok': True})

        values = {name: (post.get(name) or '').strip()[:max_len] for name, max_len in self.MAX_LEN.items()}
        errors = {}
        if not values['partner_name']:
            errors['partner_name'] = _('This field is required')
        email = email_normalize(values['email_from'])
        if not email:
            errors['email_from'] = _('This field is required') if not values['email_from'] \
                else _('Please enter a valid email')
        digits = re.sub(r'\D', '', values['partner_phone'])
        if not values['partner_phone']:
            errors['partner_phone'] = _('This field is required')
        elif not 8 <= len(digits) <= 15:
            errors['partner_phone'] = _('Please enter a valid phone number')

        resume = post.get('resume')
        content = resume.read(self.RESUME_MAX_SIZE + 1) if resume and resume.filename else b''
        if not content:
            errors['resume'] = _('This field is required')
        elif len(content) > self.RESUME_MAX_SIZE \
                or os.path.splitext(resume.filename)[1].lower() not in self.RESUME_EXTENSIONS:
            errors['resume'] = _('Please upload a PDF, DOC or DOCX file up to 10 MB')
        if errors:
            return request.make_json_response({'ok': False, 'errors': errors})

        source = request.env['utm.source']
        if (post.get('source_id') or '').isdigit():
            source = source.sudo().search(
                [('id', '=', int(post['source_id'])), ('name', 'in', list(self.SOURCE_NAMES))], limit=1)
        applicant_values = {
            'job_id': job.id,
            'department_id': job.department_id.id,
            'company_id': job.company_id.id or request.env.company.id,
            'partner_name': values['partner_name'],
            'email_from': email,
            'partner_phone': values['partner_phone'],
            'source_id': source.id,
        }
        if values['address']:
            applicant_values['applicant_notes'] = '<p>%s: %s</p>' % (
                _('Current address'), html_escape(values['address']))
        try:
            applicant = request.env['hr.applicant'].sudo().create(applicant_values)
        except AccessError:
            raise request.not_found()
        request.env['ir.attachment'].sudo().create({
            'name': os.path.basename(resume.filename),
            'raw': content,
            'res_model': 'hr.applicant',
            'res_id': applicant.id,
        })
        return request.make_json_response({'ok': True})
