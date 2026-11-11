{
    'name': 'KDVN Remote Server Connection',
    'summary': 'Direct connection from Odoo to the KDERP (Odoo 12) server: one Reader and one Writer login, '
               'dry run by default, one live switch per task.',
    'description': """
Odoo 19 version of the Odoo 12 module kderp_remote_integration (12.0.1.0.1).

The one place that knows how Odoo talks to the KDERP server directly (JSON-RPC /jsonrpc, execute_kw).
Two logins: the Writer is the only one that writes (and reads what needs wide visibility), the Reader does plain reads.
A write needs a task name and is refused unless that task's live switch is on (dry run is the default).
Settings: Settings > Remote Server Connection.
Transport: direct, or through a relay (one plain n8n webhook that forwards the JSON-RPC body) for a server that cannot reach KDERP.
""",
    'version': '19.0.1.1.0',
    'category': 'Hidden',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['base'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}
