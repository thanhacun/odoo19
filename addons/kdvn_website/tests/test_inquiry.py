from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnInquiry(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('kdvn_website.inquiry_email', 'inquiry@example.com')
        cls.Inquiry = cls.env['kdvn.website.inquiry']
        cls.inquiry_type = cls.env.ref('kdvn_website.inquiry_type_quotation')

    def _csrf(self):
        # the page renders a fresh token for this session
        html = self.url_open('/contactus').text
        marker = 'name="csrf_token" value="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def _post(self, **values):
        data = {
            'csrf_token': self._csrf(),
            'contact_name': 'Jason Marcus',
            'company_name': 'Capital Crest Vietnam',
            'email': 'Jason@Company.com',
            'phone': '09123456789',
            'inquiry_type_id': str(self.inquiry_type.id),
            'message': 'Please send us a quotation.',
        }
        data.update(values)
        return self.url_open('/contactus/send', data=data, allow_redirects=False)

    def test_page(self):
        res = self.url_open('/contactus')
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn('kdvn-inquiry-form', html)
        self.assertIn('id="kdvn_inquiry_sent"', html)
        self.assertIn(self.inquiry_type.name, html)
        self.assertIn('Inquiry form', html, "breadcrumb from the menu")

    def test_send(self):
        mails_before = self.env['mail.mail'].sudo().search_count([])
        res = self._post()
        self.assertEqual(res.status_code, 303)
        self.assertTrue(res.headers['Location'].endswith('/contactus?sent=1'))
        inquiry = self.Inquiry.search([('contact_name', '=', 'Jason Marcus')])
        self.assertEqual(len(inquiry), 1)
        self.assertEqual(inquiry.email, 'jason@company.com')
        self.assertEqual(inquiry.inquiry_type_id, self.inquiry_type)
        self.assertEqual(inquiry.state, 'new')
        mail = self.env['mail.mail'].sudo().search([], order='id desc', limit=1)
        self.assertEqual(self.env['mail.mail'].sudo().search_count([]), mails_before + 1)
        self.assertEqual(mail.email_to, 'inquiry@example.com')
        self.assertIn('Jason Marcus', mail.subject)
        self.assertEqual(mail.reply_to, 'jason@company.com')

    def test_invalid(self):
        res = self._post(email='not-an-email')
        self.assertTrue(res.headers['Location'].endswith('/contactus?error=1'))
        res = self._post(message='  ')
        self.assertTrue(res.headers['Location'].endswith('/contactus?error=1'))
        self.assertFalse(self.Inquiry.search([]))

    def test_honeypot(self):
        res = self._post(kdvn_website_url='http://spam.example.com')
        self.assertTrue(res.headers['Location'].endswith('/contactus?sent=1'))
        self.assertFalse(self.Inquiry.search([]))

    def test_unknown_type_ignored(self):
        self._post(inquiry_type_id='999999')
        inquiry = self.Inquiry.search([])
        self.assertEqual(len(inquiry), 1)
        self.assertFalse(inquiry.inquiry_type_id)

    def test_csrf_required(self):
        res = self.url_open('/contactus/send', data={'contact_name': 'X', 'email': 'x@example.com',
                                                     'message': 'hi'}, allow_redirects=False)
        self.assertNotEqual(res.status_code, 303)
        self.assertFalse(self.Inquiry.search([]))
