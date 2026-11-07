{
    'name': 'KDERP Procurement & Logistics Approval Procedures',
    'summary': 'Procurement-category e-approval procedures. First one: Safety Tool Request with stock control.',
    'description': """
        Home of the procurement / logistics procedures built on kdvn_e_approval.
        Safety Tool Request: request new or replacement safety tools, stock ledger of the
        safety tool store (replaces the Excel control sheet), handover and receipt.
    """,
    'version': '19.0.0.1.0',
    'category': 'kderp',
    'author': 'Kinden Vietnam',
    'depends': [
        'base_tier_validation_formula',   # reviewer_expression (python reviewers), also used by the other procedures
        'kdvn_e_approval',
        'kdvn_hr', 'kdvn_hr_ext',
        'kdvn_remote_sync',      # kderp.job.lookup / kderp.job.budget.cache
    ],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/safety_tool_security.xml',
        'data/ir_sequence_data.xml',
        'data/safety_tool_tier_definitions.xml',
        'data/safety_tool_special_rules.xml',
        'data/cron.xml',
        'views/safety_tool_item_views.xml',
        'views/safety_tool_move_views.xml',
        'views/safety_tool_request_views.xml',
        'views/safety_tool_menu.xml',
        'views/safety_tool_import_views.xml',
        'views/safety_tool_report_views.xml',
        'reports/safety_tool_reports.xml',
    ],
    'installable': True,
    'application': False,
}
