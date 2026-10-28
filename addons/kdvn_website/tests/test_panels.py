from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnHeaderPanels(HttpCase):

    def test_panels_rendered(self):
        html = self.url_open('/').text
        self.assertIn('id="kdvn_search_panel"', html)
        self.assertIn('data-kdvn-open="kdvn_search_panel"', html)
        self.assertIn('placeholder="Search name, categories,..."', html)
        self.assertIn('id="kdvn_lang_panel"', html)
        self.assertIn('js_change_lang', html)
        self.assertIn('>English<', html)

    def test_language_labels_and_order(self):
        website = self.env['website'].get_current_website()
        langs = self.env['res.lang']
        for code in ('vi_VN', 'ja_JP'):
            langs |= self.env['res.lang']._activate_lang(code)
        website.language_ids |= langs
        labels = [label for _lang, label in website._kdvn_language_choices()]
        self.assertEqual(labels[:3], ['Tiếng Việt', '日本語', 'English'])

    def test_view_details_link(self):
        menu = self.env.ref('kdvn_website.menu_kdvn_company_profile')
        self.assertIn('class="btn kdvn-btn-ghost" href="/company-profile">View details', self.url_open('/').text)
        menu.detail_url = '/company-profile/history'
        self.assertIn('class="btn kdvn-btn-ghost" href="/company-profile/history">View details', self.url_open('/').text)
