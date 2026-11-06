{
    'name': 'KDVN Attendance',
    'summary': 'Daily attendance, status marks, overtime, requests and leave of KDVN staff (port of kderp_hr_attendance).',
    'description': """
Odoo 19 version of the Odoo 12 module kderp_hr_attendance (12.0.1.0.11), ported in stages.
Stage A1: company attendance policy, groups, attendance rules, public holidays, AT calendar helpers.
The computation code is ported literally: payroll depends on its results. See docs/porting_from_odoo12.md.
""",
    'version': '19.0.0.1.0',
    'category': 'Human Resources/Attendances',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['hr_attendance', 'hr_holidays', 'kdvn_hr_ext'],
    'data': [
        'security/hr_attendance_security.xml',
        'security/ir.model.access.csv',
        'views/hr_attendance_rule_view.xml',
        'views/hr_holidays_public_view.xml',
    ],
    'installable': True,
    'application': False,
}
