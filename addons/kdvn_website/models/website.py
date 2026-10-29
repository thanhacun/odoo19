from odoo import models
from odoo.http import request

# Short native names shown in the language panel (frames/languages-*.png);
# other languages use the part of Odoo's name after "/" (e.g. "Français").
KDVN_LANG_LABELS = {
    'vi_VN': 'Tiếng Việt',
    'ja_JP': '日本語',
    'en_US': 'English',
    'en_GB': 'English',
    'zh_TW': '繁體',
    'zh_HK': '繁體',
    'zh_CN': '简体',
}
KDVN_LANG_ORDER = ['vi_VN', 'ja_JP', 'en_US', 'en_GB', 'zh_TW', 'zh_HK', 'zh_CN']


class Website(models.Model):
    _inherit = 'website'

    def _kdvn_language_choices(self):
        """[(res.lang, label)] of the website's languages, in the design's order
        (Vietnamese, Japanese, English, Chinese), others after."""
        self.ensure_one()

        def sort_key(lang):
            code = lang.code
            return (KDVN_LANG_ORDER.index(code) if code in KDVN_LANG_ORDER else len(KDVN_LANG_ORDER), lang.name)

        choices = []
        for lang in self.language_ids.sorted(sort_key):
            label = KDVN_LANG_LABELS.get(lang.code) or lang.name.split('/')[-1].strip()
            choices.append((lang, label))
        return choices

    def _kdvn_lang_url(self, lang):
        """The current page in `lang`, for the language panel. QWeb puts the
        current language in front of every href, so the link to the default
        language (English, no prefix) must carry its prefix: QWeb strips it
        again. A bare path stayed on /vi/..."""
        self.ensure_one()
        path = request.httprequest.path
        parts = path.split('/')
        if len(parts) > 1 and parts[1] in {lg.url_code for lg in self.language_ids}:
            path = '/'.join(parts[:1] + parts[2:]) or '/'
        qs = request.httprequest.query_string.decode()
        url = path + ('?' + qs if qs else '')
        if lang == self.default_lang_id:
            return '/%s%s' % (lang.url_code, url)
        return self.env['ir.http']._url_localized(url, lang.code)
