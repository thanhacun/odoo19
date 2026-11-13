from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnHomepage(HttpCase):

    def test_homepage_hero(self):
        res = self.url_open('/')
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn('s_kdvn_hero', html)
        self.assertEqual(html.count('kdvn-hero-arrow'), 2, "one pair of arrows for the whole slider")
        self.assertEqual(html.count('class="carousel-item'), self.env['kdvn.website.hero.slide'].search_count([]))
        # autoplay on load ("true" would wait for the first click) and loop
        self.assertIn('data-bs-ride="carousel"', html)
        self.assertIn('data-bs-wrap="true"', html)
        self.assertIn('href="/company-profile"', html)

    def test_hero_interval_setting(self):
        """Seconds from Settings > Website > Hero Slides drive data-bs-interval (default 10 s)."""
        self.assertIn('data-bs-interval="10000"', self.url_open('/').text)
        self.env['ir.config_parameter'].sudo().set_param('kdvn_website.hero_interval', '4')
        self.assertIn('data-bs-interval="4000"', self.url_open('/').text)

    def test_hero_slides_are_data(self):
        """Link and order come from Hero Slides; editing never creates a homepage view copy."""
        Slide = self.env['kdvn.website.hero.slide']
        first, second = Slide.search([])[:2]
        views_before = self.env['ir.ui.view'].search_count([('website_id', '!=', False)])
        first.link_url = '/contactus'
        second.sequence = first.sequence - 1
        self.env.flush_all()
        html = self.url_open('/').text
        self.assertIn('href="/contactus"', html)
        self.assertLess(html.index('/kdvn/hero/%d/image' % second.id), html.index('/kdvn/hero/%d/image' % first.id))
        self.assertEqual(self.env['ir.ui.view'].search_count([('website_id', '!=', False)]), views_before)
        self.assertEqual(self.url_open('/kdvn/hero/%d/image' % first.id).status_code, 200)

    def test_hero_slide_without_link_or_archived(self):
        """No link: no button. Archived: not shown (and no arrows for a single slide)."""
        Slide = self.env['kdvn.website.hero.slide']
        first, second = Slide.search([])[:2]
        first.link_url = False
        second.active = False
        self.env.flush_all()
        html = self.url_open('/').text
        self.assertNotIn('kdvn-hero-link"', html)
        self.assertNotIn('/kdvn/hero/%d/image' % second.id, html)
        self.assertNotIn('kdvn-hero-arrow', html)

    def test_homepage_business_list(self):
        Menu = self.env['website.menu']
        areas = Menu._kdvn_children_of('kdvn_website.menu_kdvn_business_information')
        self.assertEqual(len(areas), 6)
        self.assertEqual(areas[0].name, 'Electrical Systems')
        self.assertEqual(areas[0]._kdvn_media_key('business_'), 'business_electrical_system')
        # every item has a Site Media image
        keys = [a._kdvn_media_key('business_') for a in areas]
        media = self.env['kdvn.website.media'].search([('key', 'in', keys)])
        self.assertEqual(len(media), 6)

        self.env.flush_all()
        html = self.url_open('/').text
        self.assertEqual(html.count('class="kdvn-biz-item'), 6)
        self.assertIn('kdvn-biz-item active', html)
        self.assertIn('/kdvn/media/business_electrical_system', html)
        self.assertIn('/business/electrical-system', html)

    def test_website_uses_kdvn_menu(self):
        """On a new database Odoo's own top menu must not win over ours."""
        website = self.env.ref('website.default_website')
        self.assertEqual(website.menu_id, self.env.ref('kdvn_website.menu_kdvn_master_root'))
