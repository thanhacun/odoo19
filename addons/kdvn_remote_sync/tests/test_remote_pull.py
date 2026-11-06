"""Direct pull from the remote server (fake remote, no network)."""
from datetime import datetime
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

CLIENT = 'odoo.addons.kdvn_remote_integration.models.remote_client.KderpRemoteClient'


class FakeRemote(object):
    def __init__(self):
        self.calls = []
        self.partners = [
            {'id': 9510, 'name': 'Alpha Co', 'code': 'CC0010', 'email': 'a@x.vn', 'write_date': '2026-11-06 01:00:00'},
            {'id': 9511, 'name': 'Beta Co', 'code': False, 'email': False, 'write_date': '2026-11-06 02:00:00'},
        ]
        self.jobs = [{'id': 9500, 'name': 'Job one', 'code': 'TSTJOB-2026-01', 'general_expense': False,
                      'general_project_manager_id': False, 'area_manager_id': False, 'user_id': [7, 'PM'],
                      'manager_id': False, 'jp_advisor_id': False, 'acting_project_manager_id': False, 'project_manager_ref': False,
                      'partner_id': [9510, 'Alpha Co'], 'owner_id': [9511, 'Beta Co'], 'date_start': '2025-01-01',
                      'actual_completion_date': False, 'kickoff_meeting_date': False,
                      'est_peak_time_from': False, 'est_peak_time_to': False, 'state': 'doing'}]
        self.users = [{'id': 7, 'login': 'pm-login'}]
        self.budget_data = [{'id': 1, 'budget_code': 4082, 'display_name': 'TSTJOB-2026-01 - Entertainment', 'balance_amt': 100.0,
                             'account_analytic_id': [9500, 'Job one']}]
        self.fixed = [{'id': 2, 'account_analytic_id': [9500, 'Job one'], 'product_budget_id': [9, '7000 - Safety'], 'balance_amt': 50.0}]

    def __call__(self, model, method, args=None, kwargs=None, **kw):
        assert method == 'search_read', method
        assert kw.get('account') == 'reader'        # a pull only reads, with the Reader
        domain = args[0]
        self.calls.append((model, domain))
        if model == 'res.partner':
            rows = self.partners
            for cond in domain:
                if cond[0] == 'write_date':
                    rows = [r for r in rows if r['write_date'] >= cond[2]]
            return rows
        return {'account.analytic.account': self.jobs, 'res.users': self.users,
                'kderp.budget.data': self.budget_data, 'kderp.fixed.cost.data': self.fixed}[model]


@tagged('post_install', '-at_install')
class TestRemotePull(TransactionCase):

    def setUp(self):
        super().setUp()
        self.remote = FakeRemote()
        self.pull = self.env['kderp.remote.pull']
        self.user = self.env['res.users'].create({'name': 'PM user', 'login': 'pm-login'})
        self.env['ir.config_parameter'].sudo().set_param('kdvn_remote_sync.customer_since', '')

    def _run(self, fn):
        with mock.patch(CLIENT + '.execute', side_effect=self.remote):
            return fn()

    def test_full_pull_builds_cache(self):
        result = self._run(self.pull.run_full)
        self.assertEqual(result, {'jobs_synced': 1, 'budgets_synced': 2, 'customers_synced': 2})
        job = self.env['kderp.job.lookup'].search([('job_no', '=', 'TSTJOB-2026-01')])
        self.assertEqual(job.user_id, self.user)                      # role login matched to the local user
        self.assertEqual(job.partner_id.name, 'Alpha Co')
        self.assertEqual(job.owner_id.name, 'Beta Co')
        self.assertEqual(sorted(job.budget_ids.mapped('budget_code')), ['4082', '7000'])
        self.assertEqual(sorted(job.budget_ids.mapped('name')), ['Entertainment', 'Safety'])
        # the cursor is the newest customer write_date
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('kdvn_remote_sync.customer_since'), '2026-11-06 02:00:00')

    def test_full_pull_twice_is_harmless(self):
        self._run(self.pull.run_full)
        self._run(self.pull.run_full)
        self.assertEqual(self.env['kderp.customer.cache'].search_count([('external_id', 'in', [9510, 9511])]), 2)
        self.assertEqual(self.env['kderp.job.budget.cache'].search_count([('job_id.job_no', '=', 'TSTJOB-2026-01')]), 2)

    def test_customers_without_cursor_does_a_full_run(self):
        self._run(self.pull.run_customers)
        self.assertEqual(self.env['kderp.job.lookup'].search_count([('job_no', '=', 'TSTJOB-2026-01')]), 1)

    def test_customers_run_picks_up_changes_and_never_purges(self):
        self._run(self.pull.run_full)
        stay = self.env['kderp.customer.cache'].create({'external_id': 9599, 'name': 'Not in this partial read'})
        self.remote.calls[:] = []
        self.remote.partners = [dict(self.remote.partners[0], name='Alpha Renamed', write_date='2026-11-06 03:00:00'),
                                {'id': 9512, 'name': 'Gamma Co', 'code': 'CC0012', 'email': 'g@x.vn', 'write_date': '2026-11-06 03:05:00'},
                                self.remote.partners[1]]
        # Beta (02:00:00, the old cursor) is inside the 10 minute overlap, so it is read again: harmless
        result = self._run(self.pull.run_customers)
        cache = self.env['kderp.customer.cache']
        self.assertEqual(cache.search([('external_id', '=', 9510)]).name, 'Alpha Renamed')
        self.assertTrue(cache.search([('external_id', '=', 9512)]))
        self.assertTrue(stay.exists())                                    # no purge on a partial read
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('kdvn_remote_sync.customer_since'), '2026-11-06 03:05:00')
        # only the customer model was asked, with a write_date condition 10 minutes before the cursor
        self.assertEqual([c[0] for c in self.remote.calls], ['res.partner'])
        self.assertIn(['write_date', '>=', '2026-11-06 01:50:00'], self.remote.calls[0][1])
        self.assertEqual(result['customers_synced'], 3)

    def test_customers_run_with_nothing_new_writes_nothing(self):
        self._run(self.pull.run_full)
        self.remote.partners = []
        result = self._run(self.pull.run_customers)
        self.assertEqual(result['customers_synced'], 0)
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('kdvn_remote_sync.customer_since'), '2026-11-06 02:00:00')

    def test_full_run_purges_customer_gone_from_the_remote(self):
        self._run(self.pull.run_full)
        self.remote.partners = self.remote.partners[:1]
        self._run(self.pull.run_full)
        self.assertFalse(self.env['kderp.customer.cache'].search([('external_id', '=', 9511)]))

    def test_remote_down_changes_nothing_and_is_reported(self):
        self._run(self.pull.run_full)
        before = self.env['kderp.customer.cache'].search_count([])
        with mock.patch(CLIENT + '.execute', side_effect=UserError('Could not reach the remote server (ConnectionError).')):
            self.assertFalse(self.pull.cron_full())
        self.assertEqual(self.env['kderp.customer.cache'].search_count([]), before)
        self.assertIn('FAILED', self.env['ir.config_parameter'].sudo().get_param('kdvn_remote_sync.pull_status'))

    def test_failed_read_after_some_reads_writes_nothing(self):
        """Customers are read first; when the job read fails, nothing is applied (reads happen before any write)."""
        def broken(model, method, args=None, kwargs=None, **kw):
            if model == 'account.analytic.account':
                raise UserError('boom')
            return self.remote(model, method, args, kwargs, **kw)
        with mock.patch(CLIENT + '.execute', side_effect=broken):
            with self.assertRaises(UserError):
                self.pull.run_full()
        self.assertFalse(self.env['kderp.customer.cache'].search([('external_id', '=', 9510)]))
