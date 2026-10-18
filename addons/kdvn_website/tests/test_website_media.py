from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnWebsiteMedia(HttpCase):

    def test_media_served_by_key(self):
        res = self.url_open('/kdvn/media/company_history_intro')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers['Content-Type'].startswith('image/'))

    def test_unknown_key_gives_placeholder(self):
        res = self.url_open('/kdvn/media/does_not_exist')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers['Content-Type'], 'image/png')

    def test_resize(self):
        res = self.url_open('/kdvn/media/company_history_intro?width=200')
        self.assertEqual(res.status_code, 200)

    def test_pages_use_media(self):
        res = self.url_open('/company-profile/company-history')
        self.assertEqual(res.status_code, 200)
        self.assertIn('/kdvn/media/company_history_intro', res.text)
        self.assertIn('1997', res.text)
        self.assertIn('/kdvn/media/logo_white', res.text)
        self.assertIn('/kdvn/media/footer_background', res.text)

    def test_group_companies_page(self):
        res = self.url_open('/company-profile/group-companies')
        self.assertEqual(res.status_code, 200)
        self.assertIn('/kdvn/media/management_creed', res.text)
        self.assertIn('kdvn-profile-table', res.text)
