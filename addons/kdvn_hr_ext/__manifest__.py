{
    'name': 'KDVN Human Resource Extension',
    'summary': 'Department, manager and project history; administrative section; manager chain of every employee.',
    'description': """
Odoo 19 version of the Odoo 12 module kderp_hr_ext (12.0.1.0.0).
Functional and administrative department history per employee, manager history per department,
project history, chains of manager users (functional and administrative) and their GM, org-chart data.
""",
    'version': '19.0.1.1.1',
    'category': 'Human Resources',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['kdvn_hr'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/kderp_hr_ext_views.xml',
    ],
    'installable': True,
    'application': False,
}
