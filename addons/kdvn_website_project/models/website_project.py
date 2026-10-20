from odoo import api, fields, models

PROJECT_TYPES = [
    ('electrical', 'Electrical'),
    ('mechanical', 'Mechanical'),
    ('me', 'M & E'),
    ('other', 'Other'),
]


class KdvnWebsiteProjectCategory(models.Model):
    """Factory, Data Center, Building, ... (menu sub-items link to
    /prominent-projects?category=<slug>)."""
    _name = 'kdvn.website.project.category'
    _description = 'Website Project Category'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    slug = fields.Char(required=True, help="Used in the page address: /prominent-projects?category=<slug>. "
                                            "Must match the website menu link.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    project_count = fields.Integer(compute='_compute_project_count')

    _slug_unique = models.Constraint('unique(slug)', 'The category slug must be unique.')

    def _compute_project_count(self):
        counts = dict(self.env['kdvn.website.project']._read_group(
            [('category_id', 'in', self.ids)], ['category_id'], ['__count']))
        for category in self:
            category.project_count = counts.get(category, 0)


class KdvnWebsiteProjectTag(models.Model):
    """Work scope chips on the project cards (Electrical Work, Communication, ...)."""
    _name = 'kdvn.website.project.tag'
    _description = 'Website Project Work Scope'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)

    _name_unique = models.Constraint('unique(name)', 'This work scope already exists.')


class KdvnWebsiteProject(models.Model):
    """A project shown on the website (Past Prominent Projects).

    Projects are imported from the old KDERP/OpenERP servers (done or closed
    big jobs, grouped by job name; see kdvn.website.project.source) or added
    by hand. Imported data lives in the read-only kderp_* fields; the website
    fields (name, year, area, type) are only pre-filled when a project is
    created, so editors' changes are never overwritten.
    """
    _name = 'kdvn.website.project'
    _description = 'Website Project'
    _inherit = ['website.published.mixin', 'website.searchable.mixin', 'image.mixin']
    _order = 'year desc, sequence, id desc'

    name = fields.Char('Project Name', required=True, translate=True)
    sequence = fields.Integer(default=10, help="Order inside the same year.")
    active = fields.Boolean(default=True)
    year = fields.Integer(help="Year shown on the website (pre-filled from the KDERP completion date).")
    area = fields.Char('Area', translate=True, help="e.g. 'Hanoi, Vietnam'.")
    project_type = fields.Selection(PROJECT_TYPES, 'Type')
    category_id = fields.Many2one('kdvn.website.project.category', 'Category', ondelete='restrict', index=True)
    tag_ids = fields.Many2many('kdvn.website.project.tag', string='Work Scope')
    description = fields.Html(translate=True, sanitize=True, help="Not shown yet (for a future project page).")
    show_on_homepage = fields.Boolean(
        'Show on Homepage',
        help="Shown in the homepage's Past Prominent Projects section (4 cards: these first, newest "
             "first, then the newest other published projects).")

    # --- Imported from KDERP (read-only; refreshed by every import) ---
    kderp_key = fields.Char('KDERP Key', index=True, readonly=True, copy=False,
                            help="Normalised job name used to match imported jobs to this project.")
    kderp_name = fields.Char('KDERP Name', readonly=True)
    kderp_job_codes = fields.Char('Job Numbers', readonly=True)
    kderp_type = fields.Char('KDERP Type', readonly=True, help="Job types of the jobs, e.g. 'E', 'M&E'.")
    kderp_location = fields.Char('KDERP Location', readonly=True)
    kderp_date_start = fields.Date('Start Date', readonly=True)
    kderp_completion_date = fields.Date('Completion Date', readonly=True)
    kderp_amount_usd = fields.Float('Contract Amount (USD)', digits=(16, 0), readonly=True)
    kderp_imported_on = fields.Datetime('Last Imported', readonly=True)

    _kderp_key_unique = models.Constraint('unique(kderp_key)', 'A KDERP project can only be imported once.')

    def _compute_website_url(self):
        for project in self:
            project.website_url = '/prominent-projects?year=%s' % project.year if project.year else '/prominent-projects'

    @api.model
    def _search_get_detail(self, website, order, options):
        """Website search (header Search panel > /website/search): published
        projects by name, area, category or work scope."""
        mapping = {
            'name': {'name': 'name', 'type': 'text', 'match': True},
            'website_url': {'name': 'website_url', 'type': 'text', 'truncate': False},
        }
        if options.get('displayDescription'):
            mapping['description'] = {'name': 'area', 'type': 'text', 'match': True}
        return {
            'model': 'kdvn.website.project',
            'base_domain': [[('is_published', '=', True)]],
            'requires_sudo': True,
            'search_fields': ['name', 'area', 'category_id.name', 'tag_ids.name'],
            'fetch_fields': ['id', 'name', 'website_url', 'area'],
            'mapping': mapping,
            'icon': 'fa-building-o',
        }

    def _kdvn_image_url(self, size=512):
        self.ensure_one()
        return '/prominent-projects/image/%s/%s' % (self.id, size) if self.image_128 else False

    def _kdvn_type_label(self):
        """Translated label of the project type, e.g. 'M & E'."""
        self.ensure_one()
        return dict(self._fields['project_type']._description_selection(self.env)).get(self.project_type, '')

    # ------------------------------------------------------------------
    # Website page data (controllers/main.py)
    # ------------------------------------------------------------------

    MAX_YEAR_TABS = 5
    HOMEPAGE_COUNT = 4

    @api.model
    def _kdvn_homepage_projects(self, limit=None):
        """Cards of the homepage section: published projects marked 'Show on
        Homepage' (newest first), topped up with the newest other published
        projects so the row is always full when there are enough projects."""
        limit = limit or self.HOMEPAGE_COUNT
        Project = self.sudo()
        featured = Project.search([('is_published', '=', True), ('show_on_homepage', '=', True)], limit=limit)
        if len(featured) < limit:
            featured |= Project.search([('is_published', '=', True), ('id', 'not in', featured.ids)],
                                       limit=limit - len(featured))
        return featured

    @api.model
    def _kdvn_page_data(self, category=None, year=None):
        """Published projects for /prominent-projects.

        Returns dict: projects (filtered), groups [(label, key, projects)] for
        the grid, year_tabs [(label, key)], selected key ('all', '2025' or
        'earlier'). The 5 most recent years get their own tab, older ones
        are grouped under 'Earlier'."""
        domain = [('is_published', '=', True)]
        if category:
            domain.append(('category_id', '=', category.id))
        projects = self.sudo().search(domain)

        years = sorted({p.year for p in projects if p.year}, reverse=True)
        recent = years[:self.MAX_YEAR_TABS]
        has_earlier = len(years) > len(recent) or any(not p.year for p in projects)

        def key_of(project):
            return str(project.year) if project.year in recent else 'earlier'

        year_tabs = [(str(y), str(y)) for y in recent]
        if has_earlier:
            year_tabs.append((self.env._("Earlier"), 'earlier'))

        selected = year if year in {k for _l, k in year_tabs} else 'all'
        if selected != 'all':
            projects = projects.filtered(lambda p: key_of(p) == selected)

        groups = []
        for label, key in year_tabs:
            group = projects.filtered(lambda p, k=key: key_of(p) == k)
            if group:
                groups.append((label, key, group))
        return {'projects': projects, 'groups': groups, 'year_tabs': year_tabs, 'selected': selected}
