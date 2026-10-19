{
    'name': 'KDVN Website Projects',
    'summary': 'Past Prominent Projects page, with projects imported from KDERP.',
    'description': """
Website projects (name, photo, year, area, type, category, work scope tags).
Finished big jobs are pushed by n8n (which can reach the KDERP servers inside
the company network) to /api/v1/website_projects; Odoo groups them by name and
creates unpublished projects from 1,000,000 USD, as the Odoo 12 module
kdvn_website_project (kdvn.publish.project) did. Projects can also be added by hand. Published projects are shown at /prominent-projects
(grid by year or list, filters by year and category).
""",
    'version': '19.0.3.0.0',
    'category': 'Website',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['kdvn_website'],
    'data': [
        'security/ir.model.access.csv',
        'data/project_data.xml',
        'views/website_project_views.xml',
        'views/res_config_settings_views.xml',
        'views/project_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kdvn_website_project/static/src/scss/projects.scss',
        ],
    },
    'installable': True,
}
