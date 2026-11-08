"""The happy path of the platform: submit, approve (final state), on the reference procedure.
Regression: OCA 19 treats a write of the final state as 'validate now'; our own state change must not loop."""
from unittest import mock

from odoo.tests.common import TransactionCase


class TestApprovalFlow(TransactionCase):

    def test_submit_and_approve(self):
        emp = self.env['hr.employee'].create({'name': 'Flow applicant', 'code': 'TST9350', 'working': True})
        job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-003', 'job_name': 'Flow job', 'external_id': 4127, 'is_general_expense': False})
        budget = self.env['kderp.job.budget.cache'].create({'external_id': 3, 'budget_code': 'B3', 'name': 'Budget', 'job_id': job.id})
        client = self.env['kderp.customer.cache'].create({'external_id': 3, 'name': 'Flow client'})
        groups = self.env.ref('base.group_user') | self.env.ref('kdvn_e_approval.group_e_approval_admin')
        groups |= sum((self.env.ref(g) for g in self.env['entertainment.request']._admin_groups), self.env['res.groups'])
        reviewer = self.env['res.users'].create({'name': 'Flow reviewer', 'login': 'flow_reviewer', 'email': 'flow@example.test',
                                                 'group_ids': [(6, 0, groups.ids)]})
        # The shipped steps (data/entertainment_tier_definitions.xml) are off here: the test brings its own single step.
        self.env['tier.definition'].sudo().search([('model', '=', 'entertainment.request')]).write({'active': False})
        self.env['tier.definition'].sudo().create({
            'name': 'Flow step', 'frontend_name': 'Flow step', 'procedure_tag': 'entertainment.request',
            'model_id': self.env['ir.model']._get('entertainment.request').id, 'review_type': 'individual', 'reviewer_id': reviewer.id})
        Model = self.env['entertainment.request']
        for name in ('_notify_reviewers', '_notify_applicant'):
            patcher = mock.patch.object(type(Model), name, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        req = Model.sudo().create({
            'budget_code_id': budget.id, 'guest_ids': [(6, 0, [client.id])], 'employee_id': emp.id, 'place': 'Place',
            'estimated_amount': 1000000, 'total_pax': 2, 'job_id': job.id, 'employee_ids': [(6, 0, [emp.id])]})
        req.action_submit()
        self.assertEqual((req.state, req.review_ids.mapped('status')), ('submitted', ['pending']))
        req.with_user(reviewer).validate_tier()
        self.assertEqual((req.state, req.review_ids.mapped('status')), ('approved', ['approved']))
