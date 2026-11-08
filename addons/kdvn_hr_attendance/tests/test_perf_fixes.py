# -*- coding: utf-8 -*-
"""Fixes found on real imported data (Nov 2026): the refuse list read and the attendance summary speed."""
from odoo.tests import tagged
from .common_at import ATCase, WED


@tagged('post_install', '-at_install', 'at_perf')
class TestRefuseRead(ATCase):

    def test_refuse_at_ids_is_readable(self):
        """hr.attendance.refuse.at_ids (list and form of the Attendance refuse screen) used to raise ProgrammingError: can't adapt type 'hr.attendance'."""
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, None, (17, 0))
        req = self.new_wt(at, 'forget_in', (8, 0), None, state='waiting_fhr')
        refuse = self.env['hr.attendance.refuse'].create({'related_request_id': req.id, 'name': 'not eligible'})
        refuse.invalidate_recordset()
        self.assertEqual(refuse.at_ids, at)
        data = refuse.web_read({'at_ids': {'fields': {'at_date': {}}}, 'employee_id': {}, 'name': {}})
        self.assertEqual(data[0]['at_ids'][0]['id'], at.id)
        # the list read of the action (every stored field, as the web client asks it)
        listed = self.env['hr.attendance.refuse'].with_user(self.env.user).web_search_read([('id', '=', refuse.id)], {'name': {}, 'employee_id': {}, 'at_ids': {}})
        self.assertEqual(listed['length'], 1)


@tagged('post_install', '-at_install', 'at_perf')
class TestSummaryCurrentFilter(ATCase):
    """The AT Summary filters show_current / is_current are rewritten into year/month conditions (PostgreSQL pushes those into the SQL view,
    the aggregates were 5 s): they must give the same rows as the view columns."""

    def test_current_filters_match_the_view_columns(self):
        import datetime
        emp = self.new_employee()
        self.new_rule(emp)
        today = datetime.date.today()
        for back in (0, 1, 3, 5, 20, 33, 40, 70):          # days in the current period, the previous ones and older ones
            day = today - datetime.timedelta(days=back)
            self.new_at(emp, day, (8, 0), (17, 0))
        self.env.flush_all()
        Summary = self.env['hr.attendance.summary'].with_context(active_test=False)
        for field in ('show_current', 'is_current'):
            self.env.cr.execute('SELECT id FROM hr_attendance_summary WHERE employee_id = %%s AND %s' % field, [emp.id])
            expected = {r[0] for r in self.env.cr.fetchall()}
            self.env.cr.execute('SELECT id FROM hr_attendance_summary WHERE employee_id = %%s AND NOT %s' % field, [emp.id])
            expected_not = {r[0] for r in self.env.cr.fetchall()}
            for operator, value, wanted in (('=', True, expected), ('!=', True, expected_not), ('=', False, expected_not), ('!=', False, expected)):
                found = set(Summary.search([('employee_id', '=', emp.id), (field, operator, value)]).ids)
                self.assertEqual(found, wanted, '%s %s %s' % (field, operator, value))
            self.assertTrue(expected, '%s: the current period must exist in the test data' % field)
            self.assertTrue(expected_not, '%s: older periods must exist in the test data' % field)
