from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnHomepage(HttpCase):

    def test_homepage_hero(self):
        res = self.url_open('/')
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn('s_kdvn_hero', html)
        # builder needs these classes to add / remove slides
        for cls in ('s_carousel_wrapper', 's_carousel', 'carousel-item', 'carousel-indicators'):
            self.assertIn(cls, html)
        self.assertEqual(html.count('kdvn-hero-arrow'), 2, "one pair of arrows for the whole slider")
        self.assertIn('home-hero-1.jpg', html)

    def test_homepage_business_list(self):
        Menu = self.env['website.menu']
        areas = Menu._kdvn_children_of('kdvn_website.menu_kdvn_business_information')
        self.assertEqual(len(areas), 7)
        self.assertEqual(areas[0].name, 'Electrical Systems')
        self.assertEqual(areas[0]._kdvn_media_key('business_'), 'business_electrical_system')
        # every item has a Site Media image
        keys = [a._kdvn_media_key('business_') for a in areas]
        media = self.env['kdvn.website.media'].search([('key', 'in', keys)])
        self.assertEqual(len(media), 7)

        html = self.url_open('/').text
        self.assertEqual(html.count('class="kdvn-biz-item'), 7)
        self.assertIn('kdvn-biz-item active', html)
        self.assertIn('/kdvn/media/business_electrical_system', html)
        self.assertIn('/business/electrical-system', html)

    def test_website_uses_kdvn_menu(self):
        """On a new database Odoo's own top menu must not win over ours."""
        website = self.env.ref('website.default_website')
        self.assertEqual(website.menu_id, self.env.ref('kdvn_website.menu_kdvn_master_root'))
