import json

from odoo.tests import HttpCase, tagged

from .common import sample_payload

URL = '/api/v1/sync_jobs'


@tagged('post_install', '-at_install')
class TestSyncEndpoint(HttpCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('kdvn_remote_sync.api_key', 'test-key-123')

    def _form(self):
        jobs, budgets, customers = sample_payload()
        return {'jobs_data': json.dumps(jobs), 'budgets_data': json.dumps(budgets),
                'customers_data': json.dumps(customers)}

    def test_rejects_without_key(self):
        res = self.url_open(URL, data=self._form())
        self.assertEqual(res.status_code, 401)
        res = self.url_open(URL, data=self._form(), headers={'X-API-Key': 'wrong'})
        self.assertEqual(res.status_code, 401)
        self.assertFalse(self.env['kderp.job.lookup'].search_count([]))

    def test_rejects_when_no_key_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('kdvn_remote_sync.api_key', False)
        res = self.url_open(URL, data=self._form(), headers={'X-API-Key': ''})
        self.assertEqual(res.status_code, 401)

    def test_form_payload(self):
        res = self.url_open(URL, data=self._form(), headers={'X-API-Key': 'test-key-123'})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['telemetry'], {'customers_synced': 2, 'jobs_synced': 2, 'budgets_synced': 2})
        self.assertEqual(self.env['kderp.job.lookup'].search_count([]), 2)

    def test_json_body(self):
        jobs, budgets, customers = sample_payload()
        res = self.url_open(
            URL, data=json.dumps({'jobs_data': jobs, 'budgets_data': budgets, 'customers_data': customers}),
            headers={'X-API-Key': 'test-key-123', 'Content-Type': 'application/json'})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['telemetry']['jobs_synced'], 2)

    def test_malformed_payload(self):
        res = self.url_open(URL, data={'jobs_data': '[not json'}, headers={'X-API-Key': 'test-key-123'})
        self.assertEqual(res.status_code, 400)
