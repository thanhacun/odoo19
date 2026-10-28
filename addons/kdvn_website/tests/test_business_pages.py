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

    def test_instrumentation_page(self):
        self._check_page('/business/instrumentation-system', 'instrumentation', 2, 3)

    def test_interior_page(self):
        res = self.url_open('/business/interior-system')
        self.assertEqual(res.status_code, 200)
        for key in ('interior_hero', 'interior_feature_1', 'interior_item_1'):
            self.assertIn('/kdvn/media/%s' % key, res.text)
            self.assertTrue(self.env['kdvn.website.media'].search([('key', '=', key)]).image)

    def test_ict_page(self):
        res = self.url_open('/business/information-communication-system')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text.count('class="kdvn-bizpage-tile"'), 6)
        self.assertEqual(res.text.count('class="kdvn-bizpage-item"'), 2)
        keys = ['ict_hero'] + ['ict_tile_%d' % i for i in range(1, 7)] + ['ict_item_1', 'ict_item_2']
        media = self.env['kdvn.website.media'].search([('key', 'in', keys)])
        self.assertEqual(sorted(media.mapped('key')), sorted(keys))

    def test_energy_saving_page(self):
        res = self.url_open('/business/energy-saving-renewal')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text.count('class="kdvn-bizpage-item"'), 5)
        keys = ['energy_hero', 'energy_approach_1', 'energy_approach_2', 'energy_banner', 'energy_renewal',
                'energy_renewable_hero', 'energy_solar', 'energy_ac_item_1', 'energy_ac_item_2',
                'energy_ac_item_3', 'energy_elec_item_1', 'energy_elec_item_2']
        media = self.env['kdvn.website.media'].search([('key', 'in', keys)])
        self.assertEqual(sorted(media.mapped('key')), sorted(keys))

    def test_menu_links(self):
        for xmlid, url in (
            ('menu_kdvn_instrumentation_systems', '/business/instrumentation-system'),
            ('menu_kdvn_ict_systems', '/business/information-communication-system'),
            ('menu_kdvn_interior_systems', '/business/interior-system'),
            ('menu_kdvn_energy_saving_renewal', '/business/energy-saving-renewal'),
        ):
            self.assertEqual(self.env.ref('kdvn_website.' + xmlid).url, url)
