from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnBusinessPages(HttpCase):

    def _check_page(self, url, media_prefix, n_features, n_items):
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn('kdvn-page-title', html)
        self.assertIn('/kdvn/media/%s_hero' % media_prefix, html)
        self.assertEqual(html.count('class="kdvn-bizpage-feature"'), n_features)
        self.assertEqual(html.count('class="kdvn-bizpage-item"'), n_items)
        self.assertIn('(%02d)' % n_items, html)
        # every image of the page has a Site Media record
        keys = ['%s_hero' % media_prefix]
        keys += ['%s_feature_%d' % (media_prefix, i) for i in range(1, n_features + 1)]
        keys += ['%s_item_%d' % (media_prefix, i) for i in range(1, n_items + 1)]
        media = self.env['kdvn.website.media'].search([('key', 'in', keys)])
        self.assertEqual(sorted(media.mapped('key')), sorted(keys))
        self.assertTrue(all(media.mapped('image')))

    def test_electrical_system_page(self):
        self._check_page('/business/electrical-system', 'electrical', 3, 6)

    def test_ac_sanitary_page(self):
        self._check_page('/business/air-conditioning-sanitary-system', 'ac_sanitary', 2, 4)
        menu = self.env.ref('kdvn_website.menu_kdvn_hvac_sanitary_systems')
        self.assertEqual(menu.url, '/business/air-conditioning-sanitary-system')
