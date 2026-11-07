# -*- coding: utf-8 -*-
"""What the web client does for every window action of our modules (ordering, default filters and group-by, grouped reads, pivots,
new-record defaults, first record of a form) must work. The same check runs on a database with real data (see docs/odoo19_migration_checklist.md)."""
from odoo.addons.kdvn_base.tests.ui_calls import run
from odoo.tests import common, tagged


@tagged('post_install', '-at_install', 'at_ui_calls')
class TestUiCalls(common.TransactionCase):

    def test_every_action_like_the_ui(self):
        failures = run(self.env, prefixes=('kdvn_',))
        self.assertFalse(failures, '\n' + '\n'.join(failures))
