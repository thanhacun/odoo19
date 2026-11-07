"""The dashboard works with or without the e-approval module (HCMC runs the attendance part alone)."""
from unittest import mock

from odoo.tests.common import TransactionCase

DASH = 'odoo.addons.kdvn_dashboard.models.dashboard.KderpDashboard'


class TestWithoutEApproval(TransactionCase):

    def setUp(self):
        super(TestWithoutEApproval, self).setUp()
        self.Dash = self.env['kderp.dashboard']

    def test_flag_follows_the_installed_modules(self):
        self.assertEqual(self.Dash._has_eapproval(), 'kderp.e.approval.mixin' in self.env)
        self.assertEqual(self.Dash.get_dashboard_data()['has_eapproval'], self.Dash._has_eapproval())

    def test_without_eapproval_nothing_of_it_is_read(self):
        with mock.patch(DASH + '._has_eapproval', return_value=False):
            self.assertEqual(self.Dash._e_approval_models(), [])
            self.assertEqual(self.Dash._e_approval_inbox(), [])
            self.assertEqual(self.Dash._e_approval_mine(), [])
            data = self.Dash.get_dashboard_data()
        self.assertFalse(data['has_eapproval'])
        self.assertEqual(data['counts']['eapproval'], 0)
        self.assertFalse([r for r in data['inbox'] + data['mine'] if r.get('kind') == 'e_approval' or r.get('tab') == 'eapproval'])
        for key in ('user_name', 'today_card', 'inbox_lists', 'bulk_max'):          # the attendance part is all there
            self.assertIn(key, data)

    def test_with_eapproval_its_rows_are_still_there(self):
        if not self.Dash._has_eapproval():
            self.skipTest('e-approval is not installed in this database')
        self.assertIsInstance(self.Dash._e_approval_models(), list)
        data = self.Dash.get_dashboard_data()
        self.assertTrue(data['has_eapproval'])
