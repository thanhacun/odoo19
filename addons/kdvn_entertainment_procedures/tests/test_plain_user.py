"""A plain staff user (no HR group) must create, read and submit a request with employees (hr.employee is HR-only in Odoo 19)."""
from unittest import mock

from odoo.tests.common import TransactionCase


class TestPlainUser(TransactionCase):

    def test_plain_user_creates_and_reads(self):
        job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-004', 'job_name': 'Plain job', 'external_id': 4128, 'is_general_expense': False})
        budget = self.env['kderp.job.budget.cache'].create({'external_id': 4, 'budget_code': 'B4', 'name': 'Budget', 'job_id': job.id})
        client = self.env['kderp.customer.cache'].create({'external_id': 4, 'name': 'Plain client'})
        user = self.env['res.users'].create({'name': 'Plain staff', 'login': 'plain_staff', 'email': 'plain@example.test',
                                             'group_ids': [(6, 0, self.env.ref('base.group_user').ids)]})
        emp = self.env['hr.employee'].create({'name': 'Plain staff', 'code': 'TST9380', 'working': True, 'user_id': user.id})
        Model = self.env['entertainment.request']
        for name in ('_notify_reviewers', '_notify_applicant'):
            patcher = mock.patch.object(type(Model), name, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        M = Model.with_user(user)
        defaults = M.default_get(['employee_ids', 'employee_id'])
        self.assertTrue(defaults.get('employee_ids'))
        req = M.create({
            'budget_code_id': budget.id, 'guest_ids': [(6, 0, [client.id])], 'employee_id': emp.id, 'place': 'Place',
            'estimated_amount': 1000000, 'total_pax': 2, 'job_id': job.id, 'employee_ids': [(6, 0, [emp.id])]})
        data = req.web_read({'employee_ids': {'fields': {'display_name': {}}}, 'employee_id': {'fields': {'display_name': {}}}})
        self.assertEqual(data[0]['employee_ids'][0]['display_name'], 'Plain staff')
        self.assertTrue(M.search([('id', '=', req.id)]))
