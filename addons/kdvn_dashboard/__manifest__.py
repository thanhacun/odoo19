{
    'name': 'KDVN Dashboard',
    'summary': 'Home screen: what needs your attention (attendance, and e-approval where it is installed).',
    'version': '19.0.0.1.0',
    'category': 'KDERP Module',
    'author': 'KINDEN VIETNAM',
    'website': 'www.kinden.com.vn',
    'license': 'LGPL-3',
    'depends': ['web', 'kdvn_hr_attendance'],     # e-approval is optional: its tab and rows appear only where it is installed
    'data': [
        'views/dashboard_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kdvn_dashboard/static/src/scss/dashboard.scss',
            'kdvn_dashboard/static/src/dashboard/dashboard.js',
            'kdvn_dashboard/static/src/dashboard/dashboard.xml',
        ],
    },
    'post_init_hook': 'post_init_set_home_action',
    'installable': True,
    'application': False,
}
