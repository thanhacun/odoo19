import json

from markupsafe import Markup

from odoo import api, fields, models
from odoo.http import request


class WebsiteMenu(models.Model):
    _inherit = 'website.menu'

    description = fields.Text(
        translate=True,
        help="Short text shown in this menu's dropdown panel.",
    )
    overview_url = fields.Char(
        'Overview Page',
        help="Page shown by 'View details' and linked in breadcrumbs. Needed for menus "
             "with sub-items, because Odoo always sets their own URL to '#'.",
    )

    def _kdvn_link(self):
        """URL to link this menu to: overview page if set, else its own URL."""
        self.ensure_one()
        return self.overview_url or self.url

    @api.model
    def _kdvn_children_of(self, xmlid):
        """Visible sub-items of the menu `xmlid` (e.g. the Business Information
        items on the homepage), in menu order. Read with sudo: website
        visitors cannot read menus directly."""
        parent = self.env.ref(xmlid, raise_if_not_found=False)
        if not parent or parent._name != 'website.menu':
            return self.browse()
        return parent.sudo().child_id.filtered('is_visible').sorted(lambda m: (m.sequence, m.id))

    def _kdvn_media_key(self, prefix):
        """Site Media key for this menu item: `prefix` + the item's name in
        menus.csv, e.g. 'business_' + 'electrical_system' for
        kdvn_website.menu_kdvn_electrical_system. Items added in the website
        (no technical name) get 'prefix + menu_<id>'."""
        self.ensure_one()
        xmlid = self.sudo().get_external_id().get(self.id) or ''
        name = xmlid.split('.')[-1]
        if name.startswith('menu_kdvn_'):
            name = name[len('menu_kdvn_'):]
        return prefix + (name or 'menu_%s' % self.id)

    # ------------------------------------------------------------------
    # Breadcrumb helpers (used by kdvn_website.page_header / page_footer_nav)
    # ------------------------------------------------------------------

    @api.model
    def _kdvn_find_by_url(self, url, website):
        """Menu item of `website` pointing to `url`, only inside the menu the
        site actually shows (website.menu_id). Other menu trees, e.g. Odoo's
        old default menu with its own "Jobs" item, are ignored."""
        if not url or not website:
            return self.browse()
        domain = [('website_id', '=', website.id), ('url', '=', url)]
        if website.menu_id:
            domain.append(('id', 'child_of', website.menu_id.id))
        return self.sudo().search(domain, limit=1)

    def _kdvn_get_ancestors(self):
        """Parent menus, top level first, without the website's root menu."""
        self.ensure_one()
        ancestors = self.browse()
        menu = self.parent_id
        while menu.parent_id:
            ancestors = menu | ancestors
            menu = menu.parent_id
        return ancestors

    @api.model
    def _kdvn_breadcrumb(self, website, url=None, parent_url=None, title=None, extra=None):
        """Breadcrumb data for an inner page.

        - url: this page's URL; if it is in the menu, its parents form the
          trail and its name is the title.
        - parent_url: for pages that are not in the menu (e.g. one job): the
          menu item they belong under; that item and its parents form the trail.
        - title: overrides the last item's text.
        - extra: list of (name, url) added after the trail.

        Returns {'trail': [(name, url), ...], 'title': str}. The first item
        ("Kinden" -> /) is added by the template.
        """
        menu = self._kdvn_find_by_url(parent_url or url, website)
        trail = []
        if menu:
            chain = menu._kdvn_get_ancestors()
            if parent_url:
                chain = chain | menu
            trail = [(m.name, m._kdvn_link()) for m in chain]
            if not parent_url and not title:
                title = menu.name
        trail += [tuple(item) for item in (extra or [])]
        return {'trail': trail, 'title': title or ''}

    @api.model
    def _kdvn_breadcrumb_json_ld(self, website, breadcrumb, home_name='Kinden'):
        """schema.org BreadcrumbList for search engines, as a <script> body."""
        base_url = website.get_base_url().rstrip('/')
        # Language-aware URLs need a page request; outside one (tests, cron) use the plain URL
        url_for = self.env['ir.http']._url_for if request else (lambda url: url)
        items = [(home_name, '/')] + list(breadcrumb['trail'])
        elements = []
        for position, (name, url) in enumerate(items, start=1):
            element = {'@type': 'ListItem', 'position': position, 'name': name}
            if url and url != '#':
                element['item'] = base_url + url_for(url)
            elements.append(element)
        elements.append({
            '@type': 'ListItem',
            'position': len(items) + 1,
            'name': breadcrumb['title'],
        })
        data = {
            '@context': 'https://schema.org',
            '@type': 'BreadcrumbList',
            'itemListElement': elements,
        }
        # "</" must not appear inside a <script> element
        return Markup(json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
