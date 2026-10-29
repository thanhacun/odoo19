import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnLangSwitch(HttpCase):

    def _hrefs(self, path):
        html = self.url_open(path).text
        return {code: href for href, code in re.findall(r'href="([^"]*)" data-url_code="([^"]*)"', html)}

    def test_english_link_leaves_the_language_prefix(self):
        website = self.env['website'].get_current_website()
        langs = self.env['res.lang']
        for code in ('vi_VN', 'ja_JP'):
            langs |= self.env['res.lang']._activate_lang(code)
        website.language_ids |= langs
        for path, expected in (('/vi', '/'), ('/ja/company-profile', '/company-profile')):
            hrefs = self._hrefs(path)
            self.assertEqual(hrefs.get('en'), expected, (hrefs, website.default_lang_id.code, [(l.code, l.url_code) for l in website.language_ids]))
            self.assertEqual(hrefs.get('vi'), '/vi' + ('' if path == '/vi' else '/company-profile'), hrefs)
