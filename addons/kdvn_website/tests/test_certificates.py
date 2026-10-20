import base64
import io
from datetime import timedelta

from PIL import Image

from odoo import fields
from odoo.tests import HttpCase, tagged


def _png():
    buf = io.BytesIO()
    Image.new('RGB', (30, 42), (240, 240, 240)).save(buf, format='PNG')
    return base64.b64encode(buf.getvalue())


@tagged('post_install', '-at_install')
class TestKdvnCertificates(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Cert = cls.env['kdvn.website.certificate']
        Cert.search([]).write({'website_published': False})
        today = fields.Date.today()
        cls.valid = Cert.create({'name': 'KDVN Test ISO 9001', 'image_1920': _png(),
                                 'date_end': today + timedelta(days=400)})
        cls.no_expiry = Cert.create({'name': 'KDVN Test License', 'image_1920': _png()})
        cls.expiring = Cert.create({'name': 'KDVN Test ISO 14001', 'image_1920': _png(),
                                    'date_end': today + timedelta(days=10)})
        cls.expired = Cert.create({'name': 'KDVN Test ISO 45001', 'image_1920': _png(),
                                   'date_end': today - timedelta(days=1)})
        cls.hidden = Cert.create({'name': 'KDVN Test Hidden', 'image_1920': _png(),
                                  'website_published': False})

    def test_website_selection(self):
        shown = self.env['kdvn.website.certificate']._kdvn_website_certificates()
        self.assertEqual(shown, self.valid | self.no_expiry | self.expiring)
        self.assertEqual(self.expired.validity_state, 'expired')
        self.assertEqual(self.expiring.validity_state, 'expiring')
        self.assertEqual(self.valid.validity_state, 'valid')

    def test_page_and_images(self):
        res = self.url_open('/company-profile/licenses-certifications')
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn('kdvn-certs-track', html)
        self.assertIn('KDVN Test ISO 9001', html)
        self.assertNotIn('KDVN Test ISO 45001', html, "expired certificates are hidden")
        self.assertNotIn('KDVN Test Hidden', html)
        self.assertEqual(self.url_open(self.valid._kdvn_image_url(1024)).status_code, 200)
        self.assertEqual(self.url_open(self.expired._kdvn_image_url(1024)).status_code, 404)
        self.assertEqual(self.url_open(self.hidden._kdvn_image_url(1024)).status_code, 404)

    def test_renewal_reminder(self):
        Cert = self.env['kdvn.website.certificate']
        Cert._cron_renewal_reminders()
        Cert._cron_renewal_reminders()   # no duplicate to-do
        self.assertEqual(len(self.expiring.activity_ids), 1)
        self.assertEqual(self.expiring.activity_ids.date_deadline, self.expiring.date_end)
        self.assertFalse(self.valid.activity_ids)
        self.assertFalse(self.expired.activity_ids)

    def test_menu(self):
        menu = self.env.ref('kdvn_website.menu_kdvn_licenses_certifications')
        self.assertEqual(menu.url, '/company-profile/licenses-certifications')
