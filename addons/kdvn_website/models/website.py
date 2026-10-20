from odoo import models

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
