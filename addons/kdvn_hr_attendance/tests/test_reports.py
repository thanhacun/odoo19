# -*- coding: utf-8 -*-
"""Stage D: every py3o report of the module renders (template + LibreOffice conversion) with a small real month of data.
It proves the templates and the data code run in Odoo 19; it does NOT compare the numbers (that is the parity run
against Odoo 12 on the same month)."""
import datetime
from odoo.tests import tagged
from .common_at import ATCase, WED

MONTHLY = ['overtime', 'estimate_overtime', 'workingtime', 'leave', 'attendance', 'ot_compensation', 'at_performance',
           'leave_remain', 'attendance_location']
REPORT_XMLID = {
    'overtime': 'at_monthly_overtime_report_py3o', 'estimate_overtime': 'at_monthly_estimate_overtime_report_py3o',
    'workingtime': 'at_monthly_workingtime_report_py3o', 'leave': 'at_monthly_leave_report_py3o',
    'attendance': 'at_monthly_attendance_report_py3o', 'ot_compensation': 'at_yearly_ot_compensation_report_py3o',
    'at_performance': 'at_yearly_performance_report_py3o', 'leave_remain': 'at_leave_allocation_remain_py3o',
    'attendance_location': 'at_location_report_py3o'}


@tagged('post_install', '-at_install', 'at_reports')
class TestReports(ATCase):

    def setUp(self):
        super().setUp()
        self.emp = self.new_employee()
        self.new_rule(self.emp)
        # the monthly templates read a whole AT month per employee (21 Feb - 20 Mar 2026): one attendance row for every day
        day = datetime.date(2026, 2, 21)
        while day <= datetime.date(2026, 3, 20):
            row = self.new_at(self.emp, day, (8, 0), (17, 0)) if day.weekday() < 6 else self.new_at(self.emp, day)
            if day == WED:
                self.at = self.new_at(self.emp, WED, (8, 0), (19, 0))
            day += datetime.timedelta(days=1)
        self.new_ot(self.at, 'pm', (17, 0), (19, 0), state='done')
        self.Report = self.env['ir.actions.report']

    def render(self, xmlid, res_ids, data=None):
        content, filetype = self.Report._render('kdvn_hr_attendance.%s' % xmlid, res_ids, data=data)
        self.assertTrue(content, '%s: empty output' % xmlid)
        return content, filetype

    def test_every_admin_report_renders(self):
        for key in MONTHLY:
            with self.subTest(report=key):
                wiz = self.env['hr.attendance.admin.control.wizard'].create({'at_date': WED, 'monthly_report': key})
                datas = wiz.read()[0]
                if key == 'at_performance':
                    report_data, total_works = wiz.report_at_performance(at_year=wiz.at_year)
                    datas['extra_data'] = [report_data, total_works]
                content, filetype = self.render(REPORT_XMLID[key], wiz.ids, datas)
                self.assertIn(filetype, ('xlsx', 'xls'))
                self.assertEqual(content[:2], b'PK', 'not a zip based xlsx file')

    def test_request_pdfs_render(self):
        for xmlid, records in (('attendance_requests_report_py3o', self.at),
                               ('request_of_approval_attendance_report_py3o', self.at)):
            with self.subTest(report=xmlid):
                content, filetype = self.render(xmlid, records.ids)
                self.assertEqual((filetype, content[:4]), ('pdf', b'%PDF'))

    def test_summary_pdfs_render(self):
        """The approved attendance sheets of a staff member's AT month (summary = SQL view, one row per employee and month)."""
        self.env.flush_all()
        summary = self.env['hr.attendance.summary'].search([('employee_id', '=', self.emp.id)], limit=1)
        self.assertTrue(summary, 'no monthly summary row for the test employee')
        for xmlid in ('attendance_approved_report_py3o', 'compact_att_approved_report_py3o'):
            with self.subTest(report=xmlid):
                content, filetype = self.render(xmlid, summary.ids)
                self.assertEqual((filetype, content[:4]), ('pdf', b'%PDF'))

    def test_leave_request_pdf_renders(self):
        cover = self.new_leave(self.emp, datetime.date(2026, 3, 12), 'full', 'waiting_fman')
        content, filetype = self.render('request_of_approval_leaves_report_py3o', cover.ids)
        self.assertEqual((filetype, content[:4]), ('pdf', b'%PDF'))

    def test_print_button_hands_the_wizard_to_the_report(self):
        """The Print button action must carry the wizard record, or the report has nothing to render in Odoo 19."""
        wiz = self.env['hr.attendance.admin.control.wizard'].create({'at_date': WED, 'monthly_report': 'leave'})
        action = wiz.with_context(discard_logo_check=True).action_print_monthly_reports()   # core asks admins to configure the document layout first
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['context'].get('active_ids'), wiz.ids)
        self.assertEqual(action['report_type'], 'py3o')
