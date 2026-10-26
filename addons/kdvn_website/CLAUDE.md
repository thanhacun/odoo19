# kdvn_website: Kinden Vietnam company website
Theme, pages, Site Media, inquiry form, certificates. Depends on website and website_hr_recruitment.
Other addons build on it: kdvn_website_project.
History: docs/kdvn_website_progress.md. Status and review findings: docs/progress.md. Release: docs/deploy.md.
Design input: design/kdvn_website/ (frames/, specs/, pages.md page list, designer-questions.md).
Three frames per page: desktop 1440, tablet 1280, mobile 390.

## Rules
- Code is the source of truth for page content. Do not rely on website-builder copies.
- Templates: QWeb/SCSS, no inline styles, no hand-set font sizes (h6-fs spans,
  style="font-size") because they break translations and code updates.
- SCSS: use the tokens in static/src/scss/primary_variables.scss (spacing, typography, colors);
  hardcode only what has no token. One section per page or block in theme.scss.
- Page layout: t-call kdvn_website.page_header at the top and page_footer_nav at the bottom of #wrap.
  Editable marketing text goes in `oe_structure`; data blocks stay outside it.
- Images: Site Media (kdvn.website.media), served at /kdvn/media/<key>?width=N. Starting images live in
  static/src/img/content/ and data/website_media.xml (noupdate), so backend replacements survive -u.
- Menus: data/menus.xml (noupdate="0" until go-live, then "1").
- Translations: i18n/vi.po and ja.po. Generate msgids with Odoo 19's xml_translate on the template and
  validate after (every term applies, result is valid XML). Loaded on every -u, no overwrite without --i18n-overwrite.
  Only Company History, header, footer and menus are translated so far.

## Module map
- models/: kdvn.website.media, kdvn.website.certificate, kdvn.website.inquiry (+ type),
  website.menu (breadcrumb helpers, dropdown text), res.company / res.partner (company facts, offices), website (language panel).
- controllers/main.py: media, inquiry POST (CSRF, honeypot, length limits), certificate images.
- views/: layout_header|footer, homepage, snippets, components/ (page header and footer nav, company info, home business),
  pages/ (company profile, business information, contact, recruitment, office locations), backend views.
- data/: menus.xml, website_media.xml, certificates and inquiry types (noupdate).
- static/src/scss/: primary_variables.scss (tokens), theme.scss, theme_utilities.scss. static/src/js/: small widgets.
- tests/: breadcrumb, business pages, certificates, company info, homepage, inquiry, panels, media.
  No tests yet for company profile, recruitment or contact pages.

## Pitfalls
- Beta has website-specific page copies from the builder that override code
  (Company History, General Director Message). Check there if a translation does not appear.
  Saving an edited oe_structure creates such a copy; later code changes to that content stop applying.
- Website copies generic translations to website-specific views only where the English term is identical.
- Language panel: languages show only after they are added in Settings > Website > Languages.
- views/pages.xml is not loaded (not in the manifest); do not add to it.
