{
    'name': 'KDVN Website Projects',
    'summary': 'Past Prominent Projects page, with projects imported from KDERP.',
    'description': """
Website projects (name, photo, year, area, type, category, work scope tags).
Finished big jobs are imported daily over XML-RPC from the KDERP/OpenERP
servers (done/closed, job scale big job, grouped by name, >= 1,000,000 USD),
as the Odoo 12 module kdvn_website_project (kdvn.publish.project) did; projects
can also be added by hand. Published projects are shown at /prominent-projects
(grid by year or list, filters by year and category).
""",
    'version': '19.0.2.0.0',
    'category': 'Website',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['kdvn_website'],
    'data': [
        'security/ir.model.access.csv',
        'data/project_data.xml',
        'views/website_project_views.xml',
        'data/ir_cron.xml',
        'views/project_source_views.xml',
        'views/project_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kdvn_website_project/static/src/scss/projects.scss',
        ],
    },
    'installable': True,
}
