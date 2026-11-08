{
    'name': 'KDVN Web',
    'summary': 'KDVN web client customizations shared by all KDVN modules: chatter layout and toggle, time-only field, graph measures.',
    'description': """
Generic web client behaviour of KDVN (Odoo 12 kept it inside kderp_hr_attendance and kderp_web_theme):
- chatter: on the right only on very wide screens (KDVN_CHATTER_ASIDE_MIN_WIDTH in static/src/chatter/chatter_layout.js), at the bottom otherwise;
  "Show Chatter / Hide Chatter" button in its top bar, messages collapsed when a form opens;
- field widget `kdvn_time_only`: a datetime shown as HH:mm (Odoo 12 option format HH:mm); dates and datetimes numeric by default (21/04/2024);
- context key `graph_measures` of an action: limits, names and orders the measures of its graph views.
One small model: kderp.notification.wizard (centred message dialog used by e-approval). Attendance-specific JS stays in kdvn_hr_attendance.
""",
    'version': '19.0.1.3.0',
    'category': 'Hidden',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/notification_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kdvn_web/static/src/chatter/chatter_layout.js',
            'kdvn_web/static/src/chatter/chatter_toggle.js',
            'kdvn_web/static/src/chatter/chatter_toggle.xml',
            'kdvn_web/static/src/chatter/chatter_toggle.scss',
            'kdvn_web/static/src/fields/time_only_field.js',
            'kdvn_web/static/src/fields/time_only_field.xml',
            'kdvn_web/static/src/fields/numeric_dates.js',
            'kdvn_web/static/src/fields/month_date_field.js',
            'kdvn_web/static/src/fields/month_date_field.xml',
        ],
        # the graph code is in the lazy bundle: patch it there (in the main bundle it logged an unmet dependency on every page)
        'web.assets_backend_lazy': [
            'kdvn_web/static/src/graph/graph_measures.js',
        ],
    },
    'installable': True,
    'application': False,
}
