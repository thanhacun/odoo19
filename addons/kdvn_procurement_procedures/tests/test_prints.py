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

    def test_safety_tool_print(self):
        self._base()
        item = self.env['safety.tool.item'].create({'name': 'Print helmet', 'item_type': 'helmet'})
        req = self.env['safety.tool.request'].create({'reason': 't', 'job_id': self.job.id, 'employee_id': self.emp.id,
                                                      'line_ids': [(0, 0, {'item_id': item.id, 'qty': 1})]})
        self._render('kdvn_procurement_procedures.safety_tool_request_report_py3o', req, 'prepare_safety_tool_report')
