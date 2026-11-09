"""E-Approval Administrator sees and edits every request, Read-Only Auditor sees every request and edits none."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from .test_procedures_flow import TestProceduresFlow


class TestAdminAuditor(TestProceduresFlow):

    def _user(self, login, group):
        groups = self.env.ref('base.group_user') | self.env.ref(group)
        return self.env['res.users'].create({'name': login, 'login': login, 'email': login + '@example.test', 'group_ids': [(6, 0, groups.ids)]})

    def test_central_rules_cover_every_request_model(self):
        IrRule = self.env['ir.rule']
        for model in ('staff.transfer', 'kderp.project.peak.time', 'entertainment.request', 'safety.tool.request'):
            if model in self.env:
                self.assertTrue(IrRule._is_approval_model(model), model)
        self.assertFalse(IrRule._is_approval_model('res.partner'))

    def test_section_manager_sees_only_own_reviews(self):
        today = fields.Date.context_today(self.env.user)
        dept = self.env['hr.department'].create({'name': 'SM section'})
        transfer = self.env['staff.transfer'].sudo().create({
            'employee_id': self.applicant.id, 'transfer_employee_id': self.staff.id, 'transfer_department_id': dept.id,
            'transfer_from_date': today, 'transfer_to_date': today + timedelta(days=90), 'reason': 'Test'})
        manager = self._user('sm_user', 'kdvn_hr_attendance.group_hr_attendance_section_manager')
        self.assertFalse(transfer.with_user(manager).search([('id', '=', transfer.id)]))

    def test_see_and_edit(self):
        flow = self
        peak = flow._peak_time()
        dept = self.env['hr.department'].create({'name': 'AA section'})
        today = fields.Date.context_today(self.env.user)
        transfer = self.env['staff.transfer'].sudo().create({
            'employee_id': flow.applicant.id, 'transfer_employee_id': flow.staff.id, 'transfer_department_id': dept.id,
            'transfer_from_date': today, 'transfer_to_date': today + timedelta(days=90), 'reason': 'Test'})
        admin, auditor = self._user('aa_admin', 'kdvn_e_approval.group_e_approval_admin'), self._user('aa_auditor', 'kdvn_e_approval.group_e_approval_global_auditor')
        for rec in (peak, transfer):
            self.assertIn(rec, rec.with_user(admin).search([('id', '=', rec.id)]), '%s: Administrator cannot see it' % rec._name)
            self.assertIn(rec, rec.with_user(auditor).search([('id', '=', rec.id)]), '%s: Auditor cannot see it' % rec._name)
            rec.with_user(admin).check_access('write')
            with self.assertRaises(AccessError):
                rec.with_user(auditor).check_access('write')
