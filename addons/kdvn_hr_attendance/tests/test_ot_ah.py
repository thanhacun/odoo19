# -*- coding: utf-8 -*-
"""OT on a Saturday that is an AH day (AH-03): only the LAST TWO working Saturdays of the AT month are "OT holidays"
and need a done OT Holidays Plan line. Month used: 21 Jun - 20 Jul 2026, Saturdays 27 Jun, 4, 11, 18 Jul
(11 and 18 Jul are the last two)."""
import datetime
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from .common_at import ATCase

AH_TYPE = 'AH for Jul. 2026'
SAT_FIRST_HALF = datetime.date(2026, 7, 4)
SAT_LAST_HALF = datetime.date(2026, 7, 11)


@tagged('post_install', '-at_install', 'at_ot_ah')
class TestOTOnAHDay(ATCase):

    def worked_ah_day(self, day, plan):
        emp = self.new_employee()
        self.new_rule(emp)
        if plan:
            self.new_ot_plan(emp, day)
        self.new_leave(emp, day, 'full', 'done', leave_type=AH_TYPE)
        at = self.new_at(emp, day, (8, 0), (17, 0))
        return emp, at

    def hours(self, at):
        got = self.ot(at)
        return {k: v for k, v in got.items() if k in ('wd_ot', 'hd_ot', 'wd_st', 'hd_st', 'ph_ot', 'ph_st')}

    def test_ot_09_01_last_half_with_plan_is_holiday_ot(self):
        """OT-09-01: AH day among the last two Saturdays, worked 08:00-17:00 with a done plan line -> 8 h holiday OT (9 h minus lunch)."""
        emp, at = self.worked_ah_day(SAT_LAST_HALF, plan=True)
        self.new_ot(at, 'both', (8, 0), (17, 0))
        at._compute_at_status(force_run=True)
        self.assertEqual(self.hours(at), {'hd_ot': 8.0})

    def test_ot_09_02_last_half_without_plan_is_paid_as_weekday_ot(self):
        """OT-09-02 (rule OT-05, confirmed by Thanh 1 Nov 2026): same day WITHOUT a plan line. Not registered in advance =
        the 8 h count as WEEKDAY OT (no refusal; only an error line in the server log). A last Saturday that is not an AH day
        is refused (OT-08-01)."""
        emp, at = self.worked_ah_day(SAT_LAST_HALF, plan=False)
        self.new_ot(at, 'both', (8, 0), (17, 0))
        at._compute_at_status(force_run=True)
        self.assertEqual(self.hours(at), {'wd_ot': 8.0})
