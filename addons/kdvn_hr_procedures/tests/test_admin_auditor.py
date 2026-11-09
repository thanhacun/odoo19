"""E-Approval Administrator sees and edits every request, Read-Only Auditor sees every request and edits none."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from .test_procedures_flow import TestProceduresFlow


class TestAdminAuditor(TestProceduresFlow):

    def _user(self, login, group):
        groups = self.env.ref('base.group_user') | self.env.ref(group)
        return self.env['res.users'].create({'name': login, 'login': login, 'email': login + '@example.test', 'group_ids': [(6, 0, groups.ids)]})

    def test_every_request_model_has_admin_and_auditor_rules(self):
        admin, auditor = self.env.ref('kdvn_e_approval.group_e_approval_admin'), self.env.ref('kdvn_e_approval.group_e_approval_global_auditor')
        for model in ('staff.transfer', 'kderp.project.peak.time', 'entertainment.request', 'safety.tool.request'):
            if model not in self.env:
                continue
            rules = self.env['ir.rule'].search([('model_id.model', '=', model)])
            self.assertTrue(rules.filtered(lambda r: admin in r.groups and r.perm_write), '%s: no write rule for E-Approval Administrator' % model)
            self.assertTrue(rules.filtered(lambda r: auditor in r.groups and r.perm_read and not r.perm_write), '%s: no read rule for Auditor' % model)

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
