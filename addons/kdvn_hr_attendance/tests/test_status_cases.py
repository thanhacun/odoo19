from .case_runner import build_class
TestStatusCases = build_class('TestStatusCases', 'status_cases.csv', ('at_status', 'post_install', '-at_install'))
TestStatusCases.__module__ = __name__   # classes are built in case_runner; Odoo finds tests by module
