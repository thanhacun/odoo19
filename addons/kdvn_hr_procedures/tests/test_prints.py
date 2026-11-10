"""The printed form renders (template + data). Rendered as odt: the PDF conversion needs LibreOffice in a prefork server."""
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestPrints(TransactionCase):

    def _render(self, xmlid, rec, method):
        report = self.env.ref(xmlid)
        report.py3o_filetype = 'odt'
        data, ext = self.env['ir.actions.report']._render(xmlid, rec.ids, data={'formatted_data': [getattr(rec, method)()]})
        self.assertEqual(ext, 'odt')
        self.assertEqual(data[:2], b'PK')                     # an odt is a zip file

    def _base(self):
        user = self.env['res.users'].create({'name': 'Print user', 'login': 'print_user', 'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.emp = self.env['hr.employee'].create({'name': 'Print applicant', 'code': 'TST9370', 'working': True, 'user_id': user.id})
        self.staff = self.env['hr.employee'].create({'name': 'Print staff', 'code': 'TST9371', 'working': True})
        self.job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-020', 'job_name': 'Print job', 'external_id': 4220, 'is_general_expense': True})
        self.client = self.env['kderp.customer.cache'].create({'external_id': 220, 'name': 'Print client'})
        self.today = fields.Date.context_today(self.env.user)

    def test_peak_time_and_transfer_print(self):
        self._base()
        peak = self.env['kderp.project.peak.time'].create({
            'job_id': self.job.id, 'client_id': self.client.id, 'employee_id': self.emp.id, 'reason': 't',
            'execution_from': self.today, 'execution_to': self.today + timedelta(days=200),
            'actual_peak_from': self.today, 'actual_peak_to': self.today + timedelta(days=30), 'employee_ids': [(6, 0, [self.staff.id])]})
        self._render('kdvn_hr_procedures.action_report_peak_time_py3o', peak, 'prepare_peak_time_report_data')
        dept = self.env['hr.department'].create({'name': 'Print dept'})
        transfer = self.env['staff.transfer'].create({
            'employee_id': self.emp.id, 'transfer_employee_ids': [(6, 0, [self.staff.id])], 'transfer_department_id': dept.id,
            'transfer_from_date': self.today, 'transfer_to_date': self.today + timedelta(days=90), 'reason': 't'})
        self._render('kdvn_hr_procedures.action_report_staff_transfer_py3o', transfer, '_prepare_staff_transfer_report_data')
