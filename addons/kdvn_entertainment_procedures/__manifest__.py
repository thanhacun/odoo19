{
    'name': 'KDERP Entertainment Fees Procedure Requests',
    'version': "19.0.0.1.0",
    'category': 'kderp',
    'depends': [
        'kdvn_e_approval',
        'kdvn_hr_attendance',
        'kdvn_remote_sync',
        'kdvn_remote_integration',
    ],
    'data': [
        'data/ir_sequence_data.xml',
        'security/ir.model.access.csv',
        'security/entertainment_request_security.xml',
        'data/entertainment_special_rules.xml',
        'views/entertainment_request_views.xml',
        'views/entertainment_request_menu.xml',
        'views/advance_wizard_views.xml',
        'reports/entertainment_reports.xml'
    ],
    'installable': False,   # port in progress (8 Nov): tests fail, see HANDOFF.md, step 5,
}
