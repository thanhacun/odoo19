{
    'name': 'KDVN Remote Sync',
    'summary': 'Receives jobs, budgets and customers from the KDERP (Odoo 12) server through n8n.',
    'description': """
Odoo 19 version of the Odoo 12 module kderp_remote_sync (12.0.1.1.0).

n8n reads jobs, budgets and customers on the KDERP server and posts them to
/api/v1/sync_jobs (same payload as Odoo 12, plus an API key header). The data is
kept in local cache models (kderp.job.lookup, kderp.job.budget.cache,
kderp.customer.cache) that other Odoo 19 modules can link to.
""",
    'version': '19.0.1.1.0',
    'category': 'Hidden',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.model.access.csv',
        'views/kderp_job_views.xml',
        'views/kderp_customer_cache_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
