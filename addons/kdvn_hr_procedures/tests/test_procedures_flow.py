"""Happy path and refusal of the two HR procedures on the e-approval platform (submit, approve, refuse, reset)."""
from datetime import timedelta
from unittest import mock

from odoo import fields
from odoo.tests.common import TransactionCase


class TestProceduresFlow(TransactionCase):

    def setUp(self):
        super().setUp()
        # the test user is the root user (admin rights): it may submit a transfer and reset requests
        self.env.ref('kdvn_e_approval.group_e_approval_admin').write({'user_ids': [(4, self.env.uid)]})
        groups = self.env.ref('base.group_user') | self.env.ref('kdvn_e_approval.group_e_approval_admin')
        self.reviewer = self.env['res.users'].create({
            'name': 'HRP reviewer', 'login': 'hrp_reviewer', 'email': 'hrp@example.test', 'group_ids': [(6, 0, groups.ids)]})
        self.applicant_user = self.env['res.users'].create({
            'name': 'HRP applicant', 'login': 'hrp_applicant', 'email': 'hrp.app@example.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.applicant = self.env['hr.employee'].create({'name': 'HRP applicant', 'code': 'TST9360', 'working': True, 'user_id': self.applicant_user.id})
        self.staff = self.env['hr.employee'].create({'name': 'HRP staff', 'code': 'TST9361', 'working': True})
        # shipped rules need the org chart (GM, area manager): replace them by one simple step per procedure
        self.env['tier.definition'].search([('model', 'in', ('staff.transfer', 'kderp.project.peak.time'))]).write({'active': False})
        for model in ('staff.transfer', 'kderp.project.peak.time'):
            self.env['tier.definition'].create({
                'name': 'HRP step', 'frontend_name': 'HRP step', 'procedure_tag': model,
                'model_id': self.env['ir.model']._get(model).id, 'review_type': 'individual',
                'reviewer_id': self.reviewer.id, 'notify_on_rejected': True})
            Model = self.env[model]
            for name in ('_notify_reviewers', '_notify_applicant'):
                patcher = mock.patch.object(type(Model), name, return_value=True)
                patcher.start()
                self.addCleanup(patcher.stop)

    def _peak_time(self):
        today = fields.Date.context_today(self.env.user)
        job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-010', 'job_name': 'HRP job', 'external_id': 4210, 'is_general_expense': False})
        client = self.env['kderp.customer.cache'].create({'external_id': 210, 'name': 'HRP client'})
        return self.env['kderp.project.peak.time'].sudo().create({
            'job_id': job.id, 'client_id': client.id, 'employee_id': self.applicant.id, 'reason': 'Test',
            'execution_from': today - timedelta(days=30), 'execution_to': today + timedelta(days=300),
            'actual_peak_from': today, 'actual_peak_to': today + timedelta(days=30),
            'employee_ids': [(6, 0, [self.staff.id])]})

    def test_peak_time_approve(self):
        req = self._peak_time()
        self.assertEqual(req.state, 'draft')
        req.action_submit()
        self.assertEqual((req.state, req.review_ids.mapped('status')), ('submitted', ['pending']))
        req.with_user(self.reviewer).sudo().validate_tier()
        self.assertIn(req.state, ('approved', 'synced'))

    def test_peak_time_refuse_and_reset(self):
        req = self._peak_time()
        req.action_submit()
        req.with_user(self.reviewer).sudo().with_context(remote_rejection_comment='Not now').reject_tier()
        self.assertEqual(req.state, 'rejected')
        self.assertTrue(req.review_ids)                     # a refused request keeps its reviews
        req.action_reset_to_draft()
        self.assertEqual(req.state, 'draft')
        log = self.env['kderp.approval.refusal'].sudo().search([('res_model', '=', req._name), ('res_id', '=', req.id)])
        self.assertEqual((log.state, log.comment), ('reset', 'Not now'))

    def test_staff_transfer_submit_and_approve(self):
        dept = self.env['hr.department'].create({'name': 'HRP new section'})
        req = self.env['staff.transfer'].sudo().create({
            'employee_id': self.applicant.id, 'transfer_employee_ids': [(6, 0, [self.staff.id])], 'transfer_department_id': dept.id,
            'transfer_from_date': fields.Date.context_today(self.env.user),
            'transfer_to_date': fields.Date.context_today(self.env.user) + timedelta(days=90), 'reason': 'Test'})
        req.action_submit()
        self.assertEqual((req.state, req.review_ids.mapped('status')), ('submitted', ['pending']))
        req.with_user(self.reviewer).sudo().validate_tier()
        self.assertEqual(req.state, 'approved')
