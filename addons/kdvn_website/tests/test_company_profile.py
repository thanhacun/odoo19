from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnCompanyProfile(HttpCase):

    def test_company_profile_page(self):
        res = self.url_open('/company-profile')
        self.assertEqual(res.status_code, 200)
        html = res.text
        # Business Areas has no page yet, so its row is hidden
        self.assertIn('<h1 class="kdvn-page-title">Company profile</h1>', html)
        self.assertEqual(html.count('class="kdvn-profile-row"'), 5)
        self.assertNotIn('Kinden Business Areas</h2>', html)
        for url in ('/company-profile/general-director-message', '/company-profile/group-companies',
                    '/company-profile/licenses-certifications', '/company-profile/human-resource-development',
                    '/company-profile/company-history'):
            self.assertIn('href="%s"' % url, html)

    def test_footer_links(self):
        html = self.url_open('/company-profile').text
        footer = html[html.index('kdvn-footer-links'):]
        footer = footer[:footer.index('kdvn-footer-bottom')]
        self.assertIn('href="/contactus"', footer)
        self.assertNotIn('/business-information', footer)
