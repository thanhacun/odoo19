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

    def test_entertainment_print(self):
        self._base()
        budget = self.env['kderp.job.budget.cache'].create({'external_id': 220, 'budget_code': 'PB', 'name': 'Budget', 'job_id': self.job.id})
        req = self.env['entertainment.request'].create({
            'budget_code_id': budget.id, 'guest_ids': [(6, 0, [self.client.id])], 'employee_id': self.emp.id, 'place': 'Place',
            'estimated_amount': 1000000, 'total_pax': 2, 'job_id': self.job.id, 'employee_ids': [(6, 0, [self.emp.id])]})
        self.env['ir.attachment'].create({'name': 'quote.pdf', 'res_model': 'entertainment.request', 'res_id': req.id, 'raw': b'x'})   # names are listed on the form
        self._render('kdvn_entertainment_procedures.entertainment_approved_report_py3o', req, 'prepare_detailed_entertainment_report')
