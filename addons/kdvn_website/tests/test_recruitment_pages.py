from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnRecruitmentPages(HttpCase):

    def test_hr_development_page(self):
        res = self.url_open('/company-profile/human-resource-development')
        self.assertEqual(res.status_code, 200)
        self.assertIn('kdvn-page-title', res.text)
        self.assertEqual(res.text.count('/kdvn/media/hr_development_portrait_'), 6)
        keys = ['hr_development_hero_1', 'hr_development_hero_2']
        keys += ['hr_development_portrait_%d' % i for i in range(1, 7)]
        media = self.env['kdvn.website.media'].search([('key', 'in', keys)])
        self.assertEqual(sorted(media.mapped('key')), sorted(keys))
        self.assertTrue(all(media.mapped('image')))
        menu = self.env.ref('kdvn_website.menu_kdvn_hr_development')
        self.assertEqual(menu.url, '/company-profile/human-resource-development')

    def test_linkedin_menu(self):
        menu = self.env.ref('kdvn_website.menu_kdvn_linkedin')
        self.assertEqual(menu.url, 'https://vn.linkedin.com/company/kinden-vietnam')
        self.assertTrue(menu.new_window)
