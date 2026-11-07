# -*- coding: utf-8 -*-
"""Leave balance rules (LV-01 seniority, LV-04 OT over the limit -> compensation, LV-07 OT Compensation allocation) and
the waiting rule ST-05 (status is not decided too early). Expected values come from attendance_rules.md."""
import datetime
import unittest
from odoo.tests import tagged
from .common_at import ATCase, WED


@tagged('post_install', '-at_install', 'at_leave_balance')
class TestAnnualLeave(ATCase):
    """LV-01: annual leave of the AT year 2026 (21 Dec 2025 - 20 Dec 2026) by joining date."""

    def days(self, joining):
        emp = self.new_employee(joining_date=joining)
        return self.env['hr.leave.allocation'].employee_annual_leave(emp.id, 2026)

    def test_lv01_joined_this_year_is_prorated(self):
        """LV-01: joined 1 Jul 2026 -> days left in the year / 30, rounded to 0.5 (173 days -> 6.0)."""
        self.assertEqual(self.days(datetime.date(2026, 7, 1)), 6.0)

    def test_lv01_under_5_years_12_days(self):
        """LV-01: joined 1 Jan 2024 (2 years) -> 12 days."""
        self.assertEqual(self.days(datetime.date(2024, 1, 1)), 12)

    def test_lv01_5_to_10_years_14_days(self):
        """LV-01: joined 10 May 2018 (7 years) -> 14 days."""
        self.assertEqual(self.days(datetime.date(2018, 5, 10)), 14)

    def test_lv01_10_years_or_more_16_days(self):
        """LV-01: joined 1 Jan 2012 (14 years) -> 16 days (fixed 1 Nov 2026: 17 only from 25 completed years)."""
        self.assertEqual(self.days(datetime.date(2012, 1, 1)), 16)

    def test_lv01_24_years_still_16_days(self):
        """LV-01: joined 1 Jun 2001 (24 completed years at 21 Dec 2025, year 25, no bonus) -> 16 days."""
        self.assertEqual(self.days(datetime.date(2001, 6, 1)), 16)

    def test_lv01_over_25_years_17_days(self):
        """LV-01: joined 1 Jun 1997 (28 years, no bonus year) -> 17 days."""
        self.assertEqual(self.days(datetime.date(1997, 6, 1)), 17)

    def test_lv01_year_16_bonus_7_days(self):
        """LV-01: joined 1 Jun 2010 (year 16 of service) -> 16 + 7 bonus = 23 days."""
        self.assertEqual(self.days(datetime.date(2010, 6, 1)), 23)

    def test_lv01_year_26_is_17_plus_9(self):
        """LV-01: joined 1 Jun 2000 (year 26 of service) -> 17 + 9 bonus = 26 days."""
        self.assertEqual(self.days(datetime.date(2000, 6, 1)), 26)


@tagged('post_install', '-at_install', 'at_leave_balance')
class TestOTCompensation(ATCase):

    def compensation(self, emp):
        return self.env['hr.leave.allocation'].search(
            [('employee_id', '=', emp.id), ('name', '=', 'OT Compensation'), ('state', '=', 'validate')])

    def test_lv07_first_month_creates_the_allocation(self):
        """LV-07: adding 1.5 days of a month creates the 'OT Compensation' allocation of 1.5 days."""
        emp = self.new_employee()
        self.env['hr.leave.allocation'].add_ot_compensation(emp.id, datetime.date(2026, 3, 21), 1.5)
        self.assertEqual(self.compensation(emp).number_of_days, 1.5)

    def test_lv07_same_month_is_added_only_once(self):
        """LV-07: running the same attendance month twice does not add twice."""
        emp = self.new_employee()
        LA = self.env['hr.leave.allocation']
        LA.add_ot_compensation(emp.id, datetime.date(2026, 3, 21), 1.5)
        LA.add_ot_compensation(emp.id, datetime.date(2026, 3, 21), 1.5)
        self.assertEqual(self.compensation(emp).number_of_days, 1.5)

    def test_lv07_next_month_adds_up(self):
        """LV-07: the next attendance month adds to the same allocation (1.5 + 1.0 = 2.5)."""
        emp = self.new_employee()
        LA = self.env['hr.leave.allocation']
        LA.add_ot_compensation(emp.id, datetime.date(2026, 3, 21), 1.5)
        LA.add_ot_compensation(emp.id, datetime.date(2026, 4, 21), 1.0)
        self.assertEqual(self.compensation(emp).number_of_days, 2.5)

    def test_lv07_older_month_is_ignored_unless_forced(self):
        """LV-07: an older month than the last one added is ignored, HR can force it with allow_past_update."""
        emp = self.new_employee()
        LA = self.env['hr.leave.allocation']
        LA.add_ot_compensation(emp.id, datetime.date(2026, 4, 21), 1.0)
        LA.add_ot_compensation(emp.id, datetime.date(2026, 3, 21), 0.5)
        self.assertEqual(self.compensation(emp).number_of_days, 1.0)
        LA.add_ot_compensation(emp.id, datetime.date(2026, 3, 21), 0.5, allow_past_update=True)
        self.assertEqual(self.compensation(emp).number_of_days, 1.5)


@tagged('post_install', '-at_install', 'at_leave_balance')
class TestOTOverLimit(ATCase):
    """LV-04: hours over the monthly weekday limit -> exceed hours / 8 rounded UP to 0.5 day (exceed_ot_subtitude)."""

    WEEKDAYS = [datetime.date(2026, 3, 11), datetime.date(2026, 3, 12), datetime.date(2026, 3, 13)]   # Wed Thu Fri

    def exceed(self, limit, ot_days):
        emp = self.new_employee()
        self.new_rule(emp, wd_allowed_ot=limit)
        for day in self.WEEKDAYS[:ot_days]:
            at = self.new_at(emp, day, (8, 0), (21, 0))      # 17:00-21:00 = 4 h weekday OT
            self.new_ot(at, 'pm', (17, 0), (21, 0))
            at._compute_at_status(force_run=True)
        summary = self.env['hr.attendance.summary'].search([('employee_id', '=', emp.id), ('at_year', '=', 2026), ('at_month', '=', 3)])
        summary.invalidate_recordset()
        return summary.exceed_wd_overtime, summary.exceed_ot_subtitude

    def test_lv04_below_limit_nothing(self):
        """LV-04: 4 h OT with a limit of 10 h -> no exceed, no compensation."""
        self.assertEqual(self.exceed(10, 1), (0, 0))

    def test_lv04_3_hours_over_is_half_day(self):
        """LV-04: 4 h OT, limit 1 h -> 3 h over = 0.375 day -> rounded up to 0.5 day."""
        self.assertEqual(self.exceed(1, 1), (3, 0.5))

    def test_lv04_7_hours_over_is_one_day(self):
        """LV-04: 8 h OT, limit 1 h -> 7 h over = 0.875 day -> 1.0 day."""
        self.assertEqual(self.exceed(1, 2), (7, 1.0))

    def test_lv04_11_hours_over_is_one_and_half(self):
        """LV-04: 12 h OT, limit 1 h -> 11 h over = 1.375 day -> 1.5 days."""
        self.assertEqual(self.exceed(1, 3), (11, 1.5))


@tagged('post_install', '-at_install', 'at_leave_balance')
class TestWaitBeforeDeciding(ATCase):
    """ST-05: the status is not decided too early. These tests use dates relative to today, so the clock does not matter."""

    def day_after_today(self, min_days, weekday=2):
        day = datetime.date.today() + datetime.timedelta(days=min_days)
        while day.weekday() != weekday:
            day += datetime.timedelta(days=1)
        return day

    def test_st05_future_day_without_data_has_no_status(self):
        """ST-05: a coming day with no check and no leave has no status yet (not 'X')."""
        emp = self.new_employee()
        self.new_rule(emp)
        day = self.day_after_today(5)
        at = self.AT.create({'employee_id': emp.id, 'code': 'AT-%s-%s' % (day.strftime('%y%m%d'), emp.code)})
        at._compute_at_status()
        self.assertEqual(self.codes(at), [])

    def test_st05_future_day_with_leave_shows_the_leave(self):
        """ST-05: a coming day that already has a full-day leave shows 'L' straight away."""
        emp = self.new_employee()
        self.new_rule(emp)
        day = self.day_after_today(5)
        self.new_leave(emp, day)
        at = self.AT.search([('employee_id', '=', emp.id), ('at_date', '=', day)])
        at._compute_at_status()
        self.assertEqual(self.codes(at), ['L'])

    def test_st05_old_day_without_data_is_absent(self):
        """ST-05: a day far in the past (over the 2-day delay) with no check and no leave is decided: 'X'."""
        emp = self.new_employee()
        self.new_rule(emp)
        day = self.day_after_today(-21)
        at = self.AT.create({'employee_id': emp.id, 'code': 'AT-%s-%s' % (day.strftime('%y%m%d'), emp.code)})
        at._compute_at_status()
        self.assertEqual(self.codes(at), ['X'])


@tagged('post_install', '-at_install', 'at_balance_counter')
class TestLeaveCounter(ATCase):
    """LV counter: employee.leaves_count = allocated days minus validated leave days (AH and special leave not counted)."""

    def test_counter_is_allocation_minus_validated_leave(self):
        emp = self.new_employee()
        self.new_rule(emp)
        self.new_leave(emp, WED, 'full', 'done')          # helper allocates 10 days of Annual Leave, then 1 day validated
        self.env.flush_all()
        emp.invalidate_recordset()
        self.assertEqual(emp.leaves_count, 9.0)

    def test_counter_ignores_a_leave_that_is_not_validated(self):
        emp = self.new_employee()
        self.new_rule(emp)
        self.new_leave(emp, WED, 'full', 'waiting_fman')
        self.env.flush_all()
        emp.invalidate_recordset()
        self.assertEqual(emp.leaves_count, 10.0)
