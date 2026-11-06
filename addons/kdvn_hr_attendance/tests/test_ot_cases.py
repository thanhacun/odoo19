from .case_runner import build_class
TestOTCases = build_class('TestOTCases', 'ot_cases.csv', ('ot_hours', 'post_install', '-at_install'))
TestOTCases.__module__ = __name__   # classes are built in case_runner; Odoo finds tests by module
