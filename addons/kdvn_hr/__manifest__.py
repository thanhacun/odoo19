{
    'name': 'KDVN Human Resource',
    'summary': 'Staff code, working flag, location history, department code and types, second manager.',
    'description': """
Odoo 19 version of the Odoo 12 module kderp_hr (11.0.0).
Adds to hr.employee: staff code (searchable, shown in the name), working flag, location history.
Adds to hr.department: code, type, second manager, new manager with effective date.
Model names are unchanged so legacy data maps 1:1.
""",
    'version': '19.0.1.2.0',
    'category': 'Human Resources',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['hr'],
    'data': [
        'security/kderp_hr_group_security.xml',
        'security/ir.model.access.csv',
        'views/kderp_hr_views.xml',
        'views/kderp_hr_location_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
