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

    Kept separate from the synced KDERP jobs: website text and photos stay even
    when a job is no longer sent by KDERP, and the link keeps those jobs from
    being purged by kdvn_remote_sync. One project can group several jobs.
    """
    _name = 'kdvn.website.project'
    _description = 'Website Project'
    _inherit = ['website.published.mixin', 'image.mixin']
    _order = 'year desc, sequence, id desc'

    name = fields.Char('Project Name', required=True, translate=True)
    sequence = fields.Integer(default=10, help="Order inside the same year.")
    active = fields.Boolean(default=True)
    job_ids = fields.Many2many(
        'kderp.job.lookup', 'kdvn_website_project_job_rel', 'project_id', 'job_id', string='KDERP Jobs',
        help="Jobs this project is made of. Used to fill the year; the jobs are kept in Odoo while linked.")
    year = fields.Integer(
        compute='_compute_year', store=True, readonly=False,
        help="Year shown on the website. Filled from the jobs' completion (or start) date; can be changed.")
    area = fields.Char('Area', translate=True, help="e.g. 'Hanoi, Vietnam'.")
    project_type = fields.Selection(PROJECT_TYPES, 'Type')
    category_id = fields.Many2one('kdvn.website.project.category', 'Category', ondelete='restrict', index=True)
    tag_ids = fields.Many2many('kdvn.website.project.tag', string='Work Scope')
    description = fields.Html(translate=True, sanitize=True, help="Not shown yet (for a future project page).")

    @api.depends('job_ids.actual_completion_date', 'job_ids.date_start')
    def _compute_year(self):
        for project in self:
            dates = [d for job in project.job_ids for d in (job.actual_completion_date or job.date_start,) if d]
            # no job dates: keep the year typed by hand
            project.year = max(dates).year if dates else project.year

    def _compute_website_url(self):
        for project in self:
            project.website_url = '/prominent-projects?year=%s' % project.year if project.year else '/prominent-projects'

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
