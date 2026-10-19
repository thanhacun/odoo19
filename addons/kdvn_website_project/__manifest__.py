{
    'name': 'KDVN Website Projects',
    'summary': 'Past Prominent Projects page: website projects built on KDERP jobs.',
    'description': """
Website projects (name, photo, year, area, type, category, work scope tags),
linked to one or more synced KDERP jobs (kdvn_remote_sync). Published projects
are shown at /prominent-projects (grid by year or list, filters by year and
category). Odoo 19 successor of the Odoo 12 module kdvn_website_project
(kdvn.publish.project).
""",
    'version': '19.0.1.0.0',
    'category': 'Website',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['kdvn_website', 'kdvn_remote_sync'],
    'data': [
        'security/ir.model.access.csv',
        'data/project_data.xml',
        'views/website_project_views.xml',
        'views/kderp_job_views.xml',
        'views/project_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kdvn_website_project/static/src/scss/projects.scss',
        ],
    },
    'installable': True,
}
