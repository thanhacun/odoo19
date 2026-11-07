{
    'name': 'KDVN Base',
    'summary': 'KDERP base models used by the ported modules: code/name abstract model, codes, states.',
    'description': """
Odoo 19 subset of the Odoo 12 module kderp_base: the abstract models kderp.base.model, kderp.base.state.model and the
tables kderp.base.code / kderp.base.state. Model names are unchanged so data and the other ported modules map 1:1.
Also res.company.report_date_format (used by the report templates) and res.users.location_user_id (the user's office).
Not ported: the Odoo 12 web client hacks (fields_view_get / fields_get editing of views), code suggestion, QR, partner and currency data.
""",
    'version': '19.0.1.2.0',
    'category': 'Hidden',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/kderp_base_state_code_view.xml',
        'views/res_company_view.xml',
        'views/res_users_views.xml',
    ],
    'installable': True,
    'application': False,
}
