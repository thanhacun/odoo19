from .case_runner import build_ah_class
TestAHCases = build_ah_class('TestAHCases', 'ah_cases.csv', ('at_status', 'ah', 'post_install', '-at_install'))
TestAHCases.__module__ = __name__   # classes are built in case_runner; Odoo finds tests by module
