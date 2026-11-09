{
    'name': 'KDERP Human Resources Approval Procedures',
    'summary': 'Unified module for all corporate HR-related multi-tier workflows.',
    'description': """
        Consolidates all HR approval operations built on top of the kderp_e_approval engine.
        Includes: Staff Movements/Transfers, Leave Encashments, and Performance Sign-offs.
    """,
    'version': "19.0.0.1.6",
    'category': 'Human Resources',
    'author': 'Corporate Engineering Team',
    'depends': [
        'kdvn_hr', 'kdvn_hr_ext',
        'kdvn_e_approval',       # Core approval abstract layer
        'base_tier_validation_formula',   # reviewer by Python expression (staff transfer rules)
        'kdvn_hr_attendance',    # Employee historic tracking logs
        'kdvn_remote_sync',      # kderp.job.lookup (KOM peak dates)
    ],
    'data': [
        'security/staff_transfer_security.xml',
        'security/peak_time_security.xml',
        'security/ir.model.access.csv',
        'data/staff_transfer_sequence.xml',
        'data/staff_transfer_tier_definitions.xml',
        'data/peak_time_tier_definitions.xml',
        'data/peak_time_sequence.xml',
        'data/peak_time_rule_data.xml',
        'data/peak_time_special_rules.xml',
        'data/transfer_allowance_data.xml',
        'views/transfer_allowance_matrix_views.xml',
        'views/staff_transfer_views.xml',
        'views/employee_project_history_views.xml',
        'views/staff_transfer_menus.xml',
        'views/project_peak_time_views.xml',
        'views/peak_time_rule_views.xml',
        'views/peak_time_menus.xml',
        'reports/staff_transfer_reports.xml',
        'reports/peak_time_reports.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
