from odoo.tests import TransactionCase, tagged

from .common import sample_payload


@tagged('post_install', '-at_install')
class TestSyncPipeline(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pm = cls.env['res.users'].create({'name': 'Test PM', 'login': 'kdvn_test_pm'})
        cls.Job = cls.env['kderp.job.lookup']

    def _sync(self, jobs=None, budgets=None, customers=None):
        return self.Job.execute_master_sync_pipeline(jobs_data=jobs, budgets_data=budgets, customers_data=customers)

    def test_first_sync(self):
        jobs, budgets, customers = sample_payload()
        telemetry = self._sync(jobs, budgets, customers)
        self.assertEqual(telemetry, {'customers_synced': 2, 'jobs_synced': 2, 'budgets_synced': 2})

        job = self.Job.search([('external_id', '=', 9001)])
        self.assertEqual(job.job_no, 'HM11-26-0004')
        self.assertEqual(job.display_name, '[HM11-26-0004] Nippon Shokken New Factory')
        self.assertEqual(job.owner_id.code, 'C501')
        self.assertEqual(job.partner_id.code, 'C502')
        self.assertEqual(str(job.date_start), '2026-01-15')
        self.assertFalse(job.actual_completion_date)          # 'False' string = empty
        self.assertEqual(job.user_id, self.pm)                 # matched by login
        self.assertFalse(job.manager_id)                       # unknown login
        self.assertEqual(job.view_user_ids, self.pm)
        self.assertTrue(job.big_job)                           # 9th character is 0
        self.assertTrue(self.Job.new({'job_no': 'PM11-24-0001-F01'}).big_job)
        self.assertFalse(self.Job.new({'job_no': 'HM11'}).big_job)  # short number: no crash
        self.assertEqual(len(job.budget_ids), 2)
        self.assertEqual(job.budget_ids.filtered(lambda b: b.budget_code == 'B02').name, 'B02')

        job2 = self.Job.search([('external_id', '=', 9002)])
        self.assertTrue(job2.is_general_expense)
        self.assertFalse(job2.big_job)
        self.assertEqual(str(job2.kom_peak_to), '2026-04-30')

        # search by number or name
        self.assertIn(job, self.Job.search([('display_name', 'ilike', 'Shokken')]))
        self.assertTrue(self.Job.name_search('HM11-26-00'))

    def test_update_and_purge(self):
        jobs, budgets, customers = sample_payload()
        self._sync(jobs, budgets, customers)

        # second run: job 9002, budget 7002 and customer 501 are gone; job 9001 renamed
        jobs = [dict(jobs[0], name='Nippon Shokken New Factory (Phase 2)', owner_id=False)]
        budgets = [budgets[0]]
        customers = [customers[1]]
        self._sync(jobs, budgets, customers)

        self.assertEqual(self.Job.search([]).mapped('external_id'), [9001])
        job = self.Job.search([('external_id', '=', 9001)])
        self.assertEqual(job.job_name, 'Nippon Shokken New Factory (Phase 2)')
        self.assertEqual(job.budget_ids.mapped('external_id'), [7001])
        self.assertEqual(self.env['kderp.customer.cache'].search([]).mapped('external_id'), [502])

    def test_empty_list_keeps_cache(self):
        jobs, budgets, customers = sample_payload()
        self._sync(jobs, budgets, customers)
        self._sync(jobs=[], budgets=None, customers=[])
        self.assertEqual(self.Job.search_count([]), 2)
        self.assertEqual(self.env['kderp.customer.cache'].search_count([]), 2)

    def test_kom_dates_kept_when_not_sent(self):
        jobs, budgets, customers = sample_payload()
        self._sync(jobs, budgets, customers)
        job2 = dict(jobs[1])
        job2.pop('kom_peak_from')
        job2.pop('kom_peak_to')
        self._sync([jobs[0], job2])
        self.assertEqual(str(self.Job.search([('external_id', '=', 9002)]).kom_peak_to), '2026-04-30')

    def test_records_in_use_are_kept(self):
        jobs, budgets, customers = sample_payload()
        self._sync(jobs, budgets, customers)
        job2 = self.Job.search([('external_id', '=', 9002)])
        # Simulate another module pointing to the job: a stored many2one on a real model
        Field = self.env['ir.model.fields']
        holder = Field.search([('model', '=', 'res.partner'), ('name', '=', 'x_kdvn_test_job')])
        if not holder:
            Field.create({
                'name': 'x_kdvn_test_job', 'model_id': self.env.ref('base.model_res_partner').id,
                'ttype': 'many2one', 'relation': 'kderp.job.lookup', 'field_description': 'Test job',
            })
        self.env['res.partner'].create({'name': 'Holder', 'x_kdvn_test_job': job2.id})
        self._sync([jobs[0]])
        self.assertTrue(job2.exists(), "a job used by another document must not be deleted")
