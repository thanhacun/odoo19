import re
from datetime import timedelta
from io import BytesIO

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnJobs(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vietnam = cls.env.ref('base.vn')
        cls.hanoi = cls.env['res.partner'].create({'name': 'Hanoi Office', 'city': 'Hanoi', 'country_id': cls.vietnam.id})
        cls.job = cls.env['hr.job'].create({
            'name': 'Safety Engineer KDVN',
            'is_published': True,
            'website_published': True,
            'address_id': cls.hanoi.id,
            'kdvn_salary': '15 ~ 20tr VND',
            'kdvn_job_level': 'Senior, Middle',
            'kdvn_apply_deadline': fields.Date.today() + timedelta(days=5),
        })

    def _csrf(self):
        html = self.url_open('/jobs/%s' % self.env['ir.http']._slug(self.job)).text
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def _apply(self, data=None, filename='cv.pdf', content=b'%PDF-1.4 test'):
        values = {
            'csrf_token': self._csrf(),
            'partner_name': 'Diep Quang Vinh',
            'email_from': 'Vinh123@gmail.com',
            'partner_phone': '0814233045',
            'address': 'Topaz Elite, Ho Chi Minh',
        }
        values.update(data or {})
        files = {'resume': (filename, BytesIO(content))} if filename else None
        res = self.url_open('/jobs/apply/%s/submit' % self.job.id, data=values, files=files)
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_labels(self):
        self.assertEqual(self.job._kdvn_deadline_label(), 'You have 5 days to apply')
        self.assertEqual(self.job._kdvn_location(), 'Hanoi, Vietnam')
        self.assertEqual(self.job._kdvn_work_mode_label(), 'On-site')
        self.job.kdvn_apply_deadline = fields.Date.today() - timedelta(days=1)
        self.assertEqual(self.job._kdvn_deadline_label(), '')
        self.assertEqual(self.job._kdvn_posted_label(), 'Today')
        self.assertEqual(self.job.address_id._kdvn_job_location(), 'Hanoi, Vietnam')

    def test_list_page(self):
        html = self.url_open('/jobs').text
        self.assertIn('kdvn-page-title', html)
        self.assertIn('class="kdvn-job-card"', html)
        self.assertIn('Safety Engineer KDVN', html)
        self.assertIn('Hanoi, Vietnam', html)
        self.assertIn('You have 5 days to apply', html)
        self.assertIn('15 ~ 20tr VND', html)
        self.assertIn('<option value="%s"' % self.hanoi.id, html)

    def test_list_filter_and_empty(self):
        html = self.url_open('/jobs?search=zzzznothing').text
        self.assertIn('No open positions right now', html)
        self.assertNotIn('class="kdvn-job-card"', html)
        html = self.url_open('/jobs?office_id=%s' % self.hanoi.id).text
        self.assertIn('Safety Engineer KDVN', html)

    def test_detail_page(self):
        res = self.url_open('/jobs/%s' % self.env['ir.http']._slug(self.job))
        self.assertEqual(res.status_code, 200)
        html = res.text
        for text in ('Job Overview', 'Senior, Middle', 'Are you ready to', 'id="kdvn_job_apply"',
                     'kdvn_apply_confirm', 'kdvn_apply_success', 'kdvn_apply_error'):
            self.assertIn(text, html)

    def test_apply_redirects_to_form(self):
        res = self.url_open('/jobs/apply/%s' % self.env['ir.http']._slug(self.job), allow_redirects=False)
        self.assertEqual(res.status_code, 303)
        self.assertTrue(res.headers['Location'].endswith('#apply'))

    def test_apply_ok(self):
        self.assertEqual(self._apply(), {'ok': True})
        applicant = self.env['hr.applicant'].search([('job_id', '=', self.job.id)])
        self.assertEqual(len(applicant), 1)
        self.assertEqual(applicant.partner_name, 'Diep Quang Vinh')
        self.assertEqual(applicant.email_from, 'vinh123@gmail.com')
        self.assertIn('Topaz Elite', applicant.applicant_notes)
        attachment = self.env['ir.attachment'].search([('res_model', '=', 'hr.applicant'), ('res_id', '=', applicant.id)])
        self.assertEqual(attachment.name, 'cv.pdf')

    def test_apply_errors(self):
        result = self._apply({'partner_name': '', 'email_from': 'nope', 'partner_phone': '12'}, filename=None)
        self.assertFalse(result['ok'])
        self.assertEqual(set(result['errors']), {'partner_name', 'email_from', 'partner_phone', 'resume'})
        result = self._apply(filename='virus.exe')
        self.assertEqual(set(result['errors']), {'resume'})
        self.assertFalse(self.env['hr.applicant'].search([('job_id', '=', self.job.id)]))

    def test_apply_honeypot(self):
        self.assertEqual(self._apply({'kdvn_website_url': 'http://spam'}), {'ok': True})
        self.assertFalse(self.env['hr.applicant'].search([('job_id', '=', self.job.id)]))

    def test_unpublished_job_cannot_be_applied_to(self):
        csrf = self._csrf()
        self.job.website_published = False
        res = self.url_open('/jobs/apply/%s/submit' % self.job.id, data={'csrf_token': csrf})
        self.assertEqual(res.status_code, 404)
