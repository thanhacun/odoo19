# -*- coding: utf-8 -*-
"""Company settings added 1 Nov 2026: early check-in limit (TM-04), OT compensation tags (OT-07), switched-off ot_apply_rule
'both' (RW-04), and the summary id formula (no integer overflow)."""
import datetime
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from .common_at import ATCase
from ..models.hr_attendance_main import summary_key, summary_key_decode


@tagged('post_install', '-at_install', 'at_settings')
class TestSettings(ATCase):

    def test_tm04_early_limit_default_is_2_hours(self):
        self.assertEqual(self.env.user.company_id.at_policy()['early_offset_max'], 120)

    def test_tm04_rule_within_limit_ok_and_over_limit_refused(self):
        emp = self.new_employee()
        self.new_rule(emp, early_offset=120)
        with self.assertRaises(ValidationError):
            self.new_rule(emp, early_offset=135)

    def test_tm04_limit_is_a_setting(self):
        self.env.user.company_id.rule_early_offset_max = 180
        emp = self.new_employee()
        self.assertTrue(self.new_rule(emp, early_offset=135))
        with self.assertRaises(ValidationError):
            self.new_rule(emp, early_offset=195)

    def test_rw04_both_is_switched_off(self):
        values = [v for v, _l in self.Rule._fields['ot_apply_rule'].selection]
        self.assertEqual(values, ['actual', 'register'])

    def test_ot07_default_compensated_tag_is_g8(self):
        company = self.env.user.company_id
        company.ot_comp_category_ids = False
        g8 = self.env['hr.employee.category'].search([('name', '=', 'G8')]) or self.env['hr.employee.category'].create({'name': 'G8'})
        self.assertEqual(company.ot_comp_categories(), g8)

    def test_ot07_setting_adds_other_tags(self):
        company = self.env.user.company_id
        g6 = self.env['hr.employee.category'].create({'name': 'G6 test'})
        company.ot_comp_category_ids = [(4, g6.id)]
        self.assertIn(g6, company.ot_comp_categories())

    def test_summary_key_fits_integer_for_large_employee_ids(self):
        key = summary_key(200000, 2026, 11)
        self.assertLess(key, 2 ** 31)
        self.assertEqual(summary_key_decode(key), (200000, 2026, 11))
        self.assertEqual(summary_key_decode(summary_key(7, 2020, 12)), (7, 2020, 12))

    def test_summary_id_of_an_attendance_matches_the_view(self):
        emp = self.new_employee(joining_date=datetime.date(2020, 1, 1))
        at = self.new_at(emp, datetime.date(2026, 3, 2), (8, 0), (17, 0))
        self.assertEqual(at.summary_id.id, summary_key(emp.id, at.at_year, at.at_month))
        self.assertIn('ZZ Test', at.summary_id.name_get()[0][1])


@tagged('post_install', '-at_install', 'at_gm_limits')
class TestGMLimitsAndCutoff(ATCase):
    """(HR validates as admin user 2: OdooBot, uid 1, always validates alone.) RQ-12 GM approval limits (value = automatic, 0 = HR decides by hand) and RQ-05 cutoff (D+1 at the setting's Vietnam time)."""

    def test_rq05_cutoff_is_next_day_at_vietnam_time_of_setting(self):
        # 03:00 UTC = 10:00 Vietnam: a request for 20 Oct closes 21 Oct 10:00; before the date the setting starts, no cutoff
        setting = datetime.datetime(2024, 4, 20, 3, 0)
        mixin = self.env['hr.mixin']
        self.assertEqual(mixin.request_cutoff(setting, datetime.date(2026, 10, 20)), datetime.datetime(2026, 10, 21, 10, 0))
        self.assertIsNone(mixin.request_cutoff(setting, datetime.date(2024, 4, 19)))
        self.assertIsNone(mixin.request_cutoff(False, datetime.date(2026, 10, 20)))

    def test_rq12_default_all_limits_off_hr_validates_alone(self):
        emp = self.new_employee()
        cover = self.new_leave(emp, datetime.date(2026, 3, 11), state='waiting_fhr')
        cover.sudo(2).action_validate()
        self.assertEqual((cover.state, cover.man2_approve), ('done', False))

    def test_rq12_leave_days_over_limit_goes_to_gm(self):
        self.env.user.company_id.gm_leave_days_limit = 0.5
        emp = self.new_employee()
        cover = self.new_leave(emp, datetime.date(2026, 3, 11), state='waiting_fhr')   # 1 day > 0.5
        cover.sudo(2).action_validate()
        self.assertEqual((cover.state, cover.man2_approve), ('waiting_fman2', True))

    def test_rq12_leave_within_limit_stays_with_hr(self):
        self.env.user.company_id.gm_leave_days_limit = 5
        emp = self.new_employee()
        cover = self.new_leave(emp, datetime.date(2026, 3, 11), state='waiting_fhr')
        cover.sudo(2).action_validate()
        self.assertEqual(cover.state, 'done')

    def test_rq12_late_request_goes_to_gm(self):
        # the OT of 11 Mar 2026 was registered today, long after the cutoff (12 Mar 10:00)
        company = self.env.user.company_id
        company.ot_request_before = datetime.datetime(2024, 4, 20, 3, 0)
        company.gm_late_request = True
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, datetime.date(2026, 3, 11), (8, 0), (19, 0))
        req = self.new_ot(at, 'pm', (17, 0), (19, 0), state='waiting_fhr')
        req.sudo(2).action_validate()
        self.assertEqual((req.state, req.man2_approve), ('waiting_fman2', True))

    def test_rq12_late_request_flag_off_hr_validates_alone(self):
        company = self.env.user.company_id
        company.ot_request_before = datetime.datetime(2024, 4, 20, 3, 0)
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, datetime.date(2026, 3, 11), (8, 0), (19, 0))
        req = self.new_ot(at, 'pm', (17, 0), (19, 0), state='waiting_fhr')
        req.sudo(2).action_validate()
        self.assertEqual(req.state, 'done')

    def test_rq12_ot_over_monthly_limit_goes_to_gm(self):
        # allowed weekday OT 1 h per month, 2 h worked -> 1 h over; limit 0.5 h
        self.env.user.company_id.gm_ot_over_hours_limit = 0.5
        emp = self.new_employee()
        self.new_rule(emp, wd_allowed_ot=1)
        at = self.new_at(emp, datetime.date(2026, 3, 11), (8, 0), (19, 0))
        req = self.new_ot(at, 'pm', (17, 0), (19, 0), state='waiting_fhr')
        at._compute_at_status(force_run=True)
        req.sudo(2).action_validate()
        self.assertEqual((req.state, req.man2_approve), ('waiting_fman2', True))

    def test_rq12_ot_within_monthly_limit_stays_with_hr(self):
        self.env.user.company_id.gm_ot_over_hours_limit = 0.5
        emp = self.new_employee()
        self.new_rule(emp, wd_allowed_ot=60)
        at = self.new_at(emp, datetime.date(2026, 3, 11), (8, 0), (19, 0))
        req = self.new_ot(at, 'pm', (17, 0), (19, 0), state='waiting_fhr')
        at._compute_at_status(force_run=True)
        req.sudo(2).action_validate()
        self.assertEqual(req.state, 'done')


@tagged('post_install', '-at_install', 'at_timezone')
class TestVietnamTime(ATCase):
    """The Odoo process runs in UTC; Vietnam days and times must not depend on it (pytz gives +07:07 with replace(tzinfo=))."""

    def test_today_vn_is_the_vietnam_date(self):
        from ..models.hr_mixin import vn_tz
        self.assertEqual(self.env['hr.mixin'].today_vn(), datetime.datetime.now(vn_tz).date())

    def test_get_at_date_time_is_exactly_plus_7(self):
        emp = self.new_employee()
        res = self.env['hr.mixin'].get_at_date(datetime.datetime(2026, 3, 11, 1, 0), employee_id=emp, get_time=True)
        self.assertEqual(res.utcoffset(), datetime.timedelta(hours=7))
        self.assertEqual((res.hour, res.minute), (6, 0))

    def test_summary_view_uses_the_vietnam_date_not_the_database_timezone(self):
        self.env.cr.execute("SELECT pg_get_viewdef('hr_attendance_summary'::regclass)")
        definition = self.env.cr.fetchone()[0]
        self.assertNotIn('CURRENT_DATE', definition.upper())
        self.assertIn('Asia/Ho_Chi_Minh', definition)
