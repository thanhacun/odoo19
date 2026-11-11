"""Nightly read of the finished big jobs from KDERP (no call leaves this database)."""
from unittest import mock

from odoo.tests import TransactionCase, tagged

CLIENT = 'odoo.addons.kdvn_remote_integration.models.remote_client.KderpRemoteClient.execute'

JOBS = [
    {'id': 11, 'name': 'Toyoda Gosei Factory', 'code': 'HM11-24-0001', 'state': 'closed', 'job_type': '00-big_job',
     'em': 'E', 'date_start': '2023-01-01', 'completion_date': '2024-06-30', 'actual_completion_date': False,
     'city_province_id': [5, 'Hung Yen'], 'job_amount': 50000000000.0, 'currency_id': [2, 'VND']},
    {'id': 12, 'name': 'Tiny Job', 'code': 'HM11-24-0002', 'state': 'done', 'job_type': '00-big_job',
     'em': 'M', 'date_start': '2023-01-01', 'completion_date': False, 'actual_completion_date': False,
     'city_province_id': False, 'job_amount': 1000.0, 'currency_id': [1, 'USD']},
]
RATES = [
    {'account_analytic_id': [11, 'HM11-24-0001'], 'currency_id': [2, 'VND'], 'rate': 1.0},
    {'account_analytic_id': [11, 'HM11-24-0001'], 'currency_id': [1, 'USD'], 'rate': 25000.0},
]


@tagged('post_install', '-at_install')
class TestProjectPull(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Project = self.env['kdvn.website.project']
        self.calls = []

    def _execute(self, _self, model, method, args=None, kwargs=None, **kw):
        self.calls.append((model, method, args, kwargs))
        if model == 'account.analytic.account':
            return JOBS
        if model == 'kderp.job.currency':
            return RATES
        raise AssertionError(model)

    def test_pull_reads_jobs_and_their_rates_and_imports(self):
        with mock.patch(CLIENT, autospec=True, side_effect=self._execute):
            result = self.Project._kdvn_pull_from_kderp()
        self.assertEqual(result, {'created': 1, 'updated': 0, 'skipped': 1, 'jobs': 2})
        project = self.Project.with_context(active_test=False).search([('kderp_key', '=', 'TOYODA GOSEI FACTORY')])
        self.assertEqual(project.kderp_amount_usd, 2000000, "50bn VND at the job's own rate 25000")
        self.assertFalse(project.is_published)
        # what is asked of KDERP: finished big jobs incl. closed ones, then the rates of exactly those jobs
        model, method, args, kwargs = self.calls[0]
        self.assertEqual(args[0], [('state', 'in', ['done', 'closed']), ('job_type', '=', '00-big_job')])
        self.assertTrue(kwargs['context']['many2one_show_all'])
        self.assertEqual(self.calls[1][2], [[('account_analytic_id', 'in', [11, 12])]])

    def test_cron_does_nothing_without_a_remote_server(self):
        self.env['ir.config_parameter'].sudo().set_param('kderp_remote.url', '')
        with mock.patch(CLIENT, autospec=True, side_effect=self._execute):
            self.Project._cron_kdvn_pull_from_kderp()
        self.assertFalse(self.calls)

    def test_cron_pulls_when_a_remote_server_is_set_up(self):
        self.env['ir.config_parameter'].sudo().set_param('kderp_remote.url', 'http://remote.test')
        with mock.patch(CLIENT, autospec=True, side_effect=self._execute):
            self.Project._cron_kdvn_pull_from_kderp()
        self.assertEqual(self.Project.with_context(active_test=False).search_count([('kderp_key', '=', 'TOYODA GOSEI FACTORY')]), 1)

    def test_import_now_button(self):
        with mock.patch(CLIENT, autospec=True, side_effect=self._execute):
            action = self.env['res.config.settings'].create({}).action_kdvn_pull_projects_now()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn('2 jobs read: 1 created', action['params']['message'])
