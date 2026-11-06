# -*- coding: utf-8 -*-
"""Raw machine checks -> attendance check-in / check-out (rules RW-01, RW-02, TM-03, TM-04).

The face-ID API is replaced by a list of fake rows (test_mode), so no server and no real staff are needed.
Row format: (staff code, 'YYYY/MM/DD HH:MM' Vietnam time, device name).
"""
import datetime
from odoo.tests import tagged
from .common_at import ATCase, WED, vn


@tagged('post_install', '-at_install', 'at_raw')
class TestRawChecks(ATCase):

    def new_employee(self, **extra):
        # the sync only creates attendance for days after the joining date (otherwise the day of creation = today)
        extra.setdefault('joining_date', datetime.date(2026, 1, 1))
        return super().new_employee(**extra)

    def feed(self, emp, day, times, days_back=0):
        """Push fake checks for `emp` (list of 'HH:MM' on `day`) through the same path as the real synchronisation."""
        rows = [(emp.code, '%s %s' % (day.strftime('%Y/%m/%d'), t), 'HO 01') for t in times]
        self.env['hr.attendance.raw']._get_raw_data(at_date=day, duration=0, test_mode=rows)
        self.env['hr.attendance.raw']._sync_attendance_record(at_date=day, duration=0, employee_ids=[emp.id], test_mode=True)
        return self.AT.search([('at_date', '=', day), ('employee_id', '=', emp.id)])

    def hm_of(self, dt):
        if not dt:
            return None
        local = dt + datetime.timedelta(hours=7)
        return local.strftime('%H:%M')

    def check(self, at, expected_in, expected_out):
        got = (self.hm_of(at.check_in), self.hm_of(at.check_out))
        self.assertEqual(got, (expected_in, expected_out),
                         'Expected check-in/out %s/%s, got %s/%s' % (expected_in, expected_out, got[0], got[1]))

    def test_rw01_first_check_in_last_check_out(self):
        """RW-01: many checks in the day -> first is check-in, last is check-out."""
        emp = self.new_employee()
        at = self.feed(emp, WED, ['07:55', '12:03', '12:58', '17:22'])
        self.check(at, '07:55', '17:22')

    def test_rw01_two_checks(self):
        """RW-01: two checks -> in and out."""
        emp = self.new_employee()
        at = self.feed(emp, WED, ['08:05', '17:10'])
        self.check(at, '08:05', '17:10')

    def test_rw02_single_check_morning_is_check_in(self):
        """RW-02: one check at 08:00 (before noon) -> check-in only."""
        emp = self.new_employee()
        at = self.feed(emp, WED, ['08:00'])
        self.check(at, '08:00', None)

    def test_rw02_single_check_12_10_is_check_out(self):
        """RW-02: one check at 12:10 (12:00-12:30) -> check-OUT (forgot the morning check-in)."""
        emp = self.new_employee()
        at = self.feed(emp, WED, ['12:10'])
        self.check(at, None, '12:10')

    def test_rw02_single_check_12_40_is_check_in(self):
        """RW-02: one check at 12:40 (after 12:30) -> check-IN of the afternoon."""
        emp = self.new_employee()
        at = self.feed(emp, WED, ['12:40'])
        self.check(at, '12:40', None)

    def test_tm03_check_before_6_belongs_to_previous_day(self):
        """TM-03: a check at 05:30 without any early rule belongs to the previous attendance day."""
        emp = self.new_employee()
        self.feed(emp, WED, ['05:30'])
        prev = WED - datetime.timedelta(days=1)
        today = self.AT.search([('at_date', '=', WED), ('employee_id', '=', emp.id)])
        self.assertFalse(today.check_in or today.check_out, 'Check at 05:30 must not be used by the same day')
        raw = self.env['hr.attendance.raw'].with_context(active_test=False).search(
            [('at_code', '=', 'AT-%s-%s' % (prev.strftime('%y%m%d'), emp.code))])
        self.assertTrue(raw, 'Check at 05:30 must be stored under the previous day')

    def test_tm04_early_rule_moves_day_start(self):
        """TM-04: rule early_offset 45 for this staff -> a check at 05:30 counts as check-in of the same day."""
        emp = self.new_employee()
        self.new_rule(emp, early_offset=45, valid_start=WED, valid_stop=WED)
        at = self.feed(emp, WED, ['05:30', '17:10'])
        self.check(at, '05:30', '17:10')
