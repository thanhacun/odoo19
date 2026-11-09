{
    'name': "KDERP Centralized E-Approval Workspace",
    'summary': """Unified paperless workspace portal utilizing native model tier validation architecture.""",
    'description': """Streamlined virtual view mapping for corporate approvals.""",
    'author': "Kinden Vietnam",
    'website': "https://www.kinden.com.vn",
    'category': "kderp",
    'version': "19.0.0.2.4",
    'depends': [
        'base',
        'base_tier_validation',
        'kdvn_base',
        'kdvn_web',
        'kdvn_hr',
        'kdvn_remote_sync'
    ],
    'data': [
        'data/cron.xml',
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/special_rule_security.xml',
        'views/tier_definition_views.xml',
        'views/tier_review_views.xml',
        'views/res_users_views.xml',
        'views/settings_views.xml',
        'views/menu.xml',
        'views/approval_refusal_views.xml',
        'views/special_rule_views.xml',
        # 'reports/entertainment_reports.xml'
    ],
    'assets': {
        'web.assets_backend': [
            'kdvn_e_approval/static/src/scss/review_colors.css',
            'kdvn_e_approval/static/src/scss/approval_ribbon.scss',
            'kdvn_e_approval/static/src/review_table/review_table.js',
            'kdvn_e_approval/static/src/review_table/review_table.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
