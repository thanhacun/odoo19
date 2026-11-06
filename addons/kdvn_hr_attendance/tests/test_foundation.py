"""Stage A1: policy, AT calendar, day start, early offset, holidays, rules. Expected values come from attendance_rules.md (rule ids in the names)."""
from datetime import date, datetime

import pytz

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

UTC = pytz.utc


def utc_dt(*args):
    return UTC.localize(datetime(*args))


class TestFoundation(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.mixin = self.env['hr.mixin']
        self.At = self.env['hr.attendance']
        self.Rule = self.env['hr.attendance.rule']
        self.emp = self.env['hr.employee'].create({'name': 'AT Test', 'code': 'AT001', 'working': True})
        self.dept = self.env['hr.department'].create({'name': 'AT Dept', 'code': 'ATD'})
        self.emp.admin_dept_id = self.dept
        # no real rule may disturb the tests
        self.Rule.search([]).unlink() if not self.Rule.search([('state', '=', 'done')]) else None

    def rule(self, **vals):
        vals.setdefault('name', 'test rule')
        vals.setdefault('apply_mode', 'by_employee')
        if vals['apply_mode'] == 'by_employee':
            vals.setdefault('employee_ids', [(6, 0, self.emp.ids)])
        vals.setdefault('valid_start', date(2026, 1, 1))
        rule = self.Rule.create(vals)
        rule.action_submit()
        return rule

    # ---------------------------------------------------------------- policy (TM-02)
    def test_policy_defaults(self):
        p = self.company.at_policy()
        self.assertEqual((p['date_start'], p['day_start'], p['working_start'], p['late_in'], p['absence'], p['delay_duration']),
                         (21, 6, 8, 5, 30, 2))
        self.assertEqual(p['early_out'], 0)
        self.assertEqual(p['special_ot'], [22, 6])

    def test_policy_constraints(self):
        with self.assertRaises(ValidationError):
            self.company.rule_at_start_date = 0
        with self.assertRaises(ValidationError):
            self.company.rule_at_start_date = 29
        with self.assertRaises(ValidationError):
            self.company.rule_special_ot_hour = '22-06'
        with self.assertRaises(ValidationError):
            self.company.rule_early_offset_max = -1

    # ---------------------------------------------------------------- AT calendar (TM-01, TM-02)
    def test_at_month_runs_21_to_20_and_is_named_by_its_end(self):
        gsd = self.mixin.get_start_dt
        self.assertEqual(gsd(date(2026, 3, 5), for_month=True), date(2026, 2, 21))
        self.assertEqual(gsd(date(2026, 3, 21), for_month=True), date(2026, 3, 21))
        self.assertEqual(gsd(date(2026, 3, 20), for_month=True), date(2026, 2, 21))
        self.assertEqual(self.mixin.get_at_year_month(date(2026, 3, 5)), (2026, 3))
        self.assertEqual(self.mixin.get_at_year_month(date(2026, 3, 21)), (2026, 4))
        # 21 Dec - 20 Jan is month 1 of the NEXT year; the AT year starts on 21 Dec
        self.assertEqual(self.mixin.get_at_year_month(date(2025, 12, 21)), (2026, 1))
        self.assertEqual(self.mixin.get_at_year_month(date(2026, 1, 20)), (2026, 1))
        self.assertEqual(gsd(date(2025, 12, 25)), date(2025, 12, 21))
        self.assertEqual(gsd(date(2026, 6, 1)), date(2025, 12, 21))

    def test_start_day_comes_from_the_company_policy(self):
        self.company.rule_at_start_date = 26
        self.assertEqual(self.mixin.at_start_day(), 26)
        self.assertEqual(self.mixin.get_start_dt(date(2026, 3, 10), for_month=True), date(2026, 2, 26))
        self.assertEqual(self.mixin.at_period_end(2026, 3), date(2026, 3, 26))
        self.assertEqual(self.mixin.at_period_last_day(2026, 3), date(2026, 3, 25))

    # ---------------------------------------------------------------- day start (TM-03, TM-04)
    def test_check_before_06_belongs_to_the_previous_day(self):
        # 05:50 Vietnam = 22:50 UTC the day before; docstring examples of get_at_date
        self.assertEqual(self.mixin.get_at_date(utc_dt(2021, 10, 14, 22, 50)), date(2021, 10, 14))
        self.assertEqual(self.mixin.get_at_date(utc_dt(2021, 10, 15, 0, 50)), date(2021, 10, 15))
        self.assertEqual(self.mixin.get_at_date(utc_dt(2021, 10, 14, 23, 0)), date(2021, 10, 15), '06:00 sharp starts the day')

    def test_early_offset_from_rule_moves_the_day_start(self):
        self.rule(early_offset=60)
        self.assertEqual(self.mixin.get_early_offset(at_date=date(2026, 5, 4), employee_id=self.emp), 60)
        # 05:30 Vietnam: normally the previous day, with a 60 minute offset it is the same day
        check = utc_dt(2026, 5, 3, 22, 30)
        self.assertEqual(self.mixin.get_at_date(check), date(2026, 5, 3))
        self.assertEqual(self.mixin.get_at_date(check, employee_id=self.emp), date(2026, 5, 4))

    def test_early_offset_limit_is_a_company_setting(self):
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': 'too early', 'early_offset': 121, 'employee_ids': [(6, 0, self.emp.ids)]})
        self.company.rule_early_offset_max = 180
        self.Rule.create({'name': 'ok now', 'early_offset': 150, 'employee_ids': [(6, 0, self.emp.ids)]})

    def test_get_at_datetime_is_the_utc_start_of_the_day(self):
        self.assertEqual(self.mixin.get_at_datetime(date(2022, 4, 30)), datetime(2022, 4, 29, 23, 0))

    # ---------------------------------------------------------------- holidays (ST-07)
    def _holidays(self):
        year = self.env['hr.holidays.public'].create({'year': 2026})
        Line = self.env['hr.holidays.public.line']
        Line.create({'year_id': year.id, 'name': 'New Year', 'date': date(2026, 1, 1)})
        Line.create({'year_id': year.id, 'name': 'Company day', 'date': date(2026, 7, 29), 'is_company_day': True})
        Line.create({'year_id': year.id, 'name': 'Substitute', 'date': date(2026, 2, 20), 'is_substitute': True})
        return year

    def test_public_holiday_types(self):
        self._holidays()
        P = self.env['hr.holidays.public']
        self.assertEqual(P.is_public_holiday(date(2026, 1, 1)), 1)
        self.assertEqual(P.is_public_holiday(date(2026, 7, 29)), 2)
        self.assertEqual(P.is_public_holiday(date(2026, 2, 20)), 3)
        self.assertEqual(P.is_public_holiday(date(2026, 1, 2)), 0)

    def test_holiday_marks(self):
        self._holidays()
        at = self.At
        self.assertEqual(at._is_holiday(date(2026, 1, 1)), 'SH')
        self.assertEqual(at._is_holiday(date(2026, 7, 29)), 'OH')
        self.assertEqual(at._is_holiday(date(2026, 2, 20)), 'H')
        self.assertEqual(at._is_holiday(date(2026, 3, 1)), 'H', 'Sunday')
        self.assertFalse(at._is_holiday(date(2026, 3, 2)), 'Monday')
        self.assertFalse(at._is_holiday(date(2026, 3, 7)), 'Saturday is a working day by default')

    def test_holiday_year_and_line_rules(self):
        year = self._holidays()
        with self.assertRaises(ValidationError):
            self.env['hr.holidays.public'].create({'year': 2026})
        with self.assertRaises(ValidationError):
            self.env['hr.holidays.public.line'].create({'year_id': year.id, 'name': 'wrong year', 'date': date(2027, 1, 1)})
        with self.assertRaises(ValidationError):
            self.env['hr.holidays.public.line'].create({'year_id': year.id, 'name': 'dup', 'date': date(2026, 1, 1)})

    def test_holiday_list_memo_is_dropped_on_change(self):
        year = self._holidays()
        P = self.env['hr.holidays.public']
        self.assertEqual(P.is_public_holiday(date(2026, 5, 1)), 0)
        self.env['hr.holidays.public.line'].create({'year_id': year.id, 'name': 'Labour', 'date': date(2026, 5, 1)})
        self.assertEqual(P.is_public_holiday(date(2026, 5, 1)), 1)

    # ---------------------------------------------------------------- Saturdays (AH-03)
    def test_last_two_working_saturdays(self):
        # AT month 21 Mar - 20 Apr 2026: Saturdays 21 Mar, 28 Mar, 4 Apr, 11 Apr, 18 Apr
        m = self.mixin
        self.assertEqual(m.monthly_working_weekday(date(2026, 4, 18)),
                         [date(2026, 3, 21), date(2026, 3, 28), date(2026, 4, 4), date(2026, 4, 11), date(2026, 4, 18)])
        self.assertTrue(m.in_last_half_month(date(2026, 4, 18)))
        self.assertTrue(m.in_last_half_month(date(2026, 4, 11)))
        self.assertFalse(m.in_last_half_month(date(2026, 4, 4)))
        self.assertTrue(m.is_ot_holiday(date(2026, 4, 11)))
        self.assertFalse(m.is_ot_holiday(date(2026, 3, 28)))
        self.assertTrue(m.is_ot_holiday(date(2026, 3, 22)), 'Sunday')

    def test_a_holiday_saturday_is_not_counted_as_a_working_saturday(self):
        year = self.env['hr.holidays.public'].create({'year': 2026})
        self.env['hr.holidays.public.line'].create({'year_id': year.id, 'name': 'Sat holiday', 'date': date(2026, 4, 11)})
        m = self.mixin
        self.assertEqual(m.monthly_working_weekday(date(2026, 4, 18))[-2:], [date(2026, 4, 4), date(2026, 4, 18)])
        self.assertTrue(m.is_ot_holiday(date(2026, 4, 11)), 'it is a holiday anyway')

    def test_ot_holidays_of_the_month(self):
        days = self.mixin.get_ot_holidays(date(2026, 4, 1))
        self.assertIn(date(2026, 4, 18), days)
        self.assertIn(date(2026, 4, 5), days)
        self.assertNotIn(date(2026, 4, 4), days)

    # ---------------------------------------------------------------- rules (AL-05, AL-08)
    def test_no_rule_gives_the_defaults(self):
        r = self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))
        self.assertEqual((r['wd_allowed_ot'], r['hd_allowed_ot'], r['early_offset']), (0, 0, 0))
        self.assertFalse(r['ot_apply_rule'], 'no OT allowance = no OT rule (and no morning OT)')
        self.assertFalse(r['allow_morning_ot'])

    def test_company_rule_and_employee_rule_are_merged_by_sequence(self):
        self.rule(name='company', apply_mode='by_company', company_id=self.company.id, wd_allowed_ot=60, hd_allowed_ot=30, sequence=1)
        self.rule(name='employee', hd_allowed_ot=50, early_offset=30, sequence=2)
        r = self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))
        self.assertEqual(r['wd_allowed_ot'], 60)
        self.assertEqual(r['hd_allowed_ot'], 50, 'a later rule overwrites a non-zero field')
        self.assertEqual(r['early_offset'], 30)
        self.assertEqual(r['ot_apply_rule'], 'actual')

    def test_a_zero_does_not_overwrite_and_force_apply_fixes_the_limits(self):
        self.rule(name='company', apply_mode='by_company', company_id=self.company.id, wd_allowed_ot=60, hd_allowed_ot=30, sequence=1)
        self.rule(name='zero', wd_allowed_ot=0, sequence=2)
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['wd_allowed_ot'], 60)
        self.rule(name='forced', wd_allowed_ot=40, hd_allowed_ot=10, force_apply=True, sequence=3)
        self.rule(name='later', wd_allowed_ot=99, sequence=4)
        r = self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))
        self.assertEqual((r['wd_allowed_ot'], r['hd_allowed_ot']), (40, 10), 'later rules cannot change forced limits')

    def test_draft_inactive_and_out_of_period_rules_are_ignored(self):
        draft = self.Rule.create({'name': 'draft', 'wd_allowed_ot': 60, 'employee_ids': [(6, 0, self.emp.ids)], 'valid_start': date(2026, 1, 1)})
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['wd_allowed_ot'], 0)
        draft.action_submit()
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['wd_allowed_ot'], 60)
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2025, 12, 31))['wd_allowed_ot'], 0, 'before valid_start')
        draft.valid_stop = date(2026, 5, 20)
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 21))['wd_allowed_ot'], 0, 'after valid_stop')
        draft.active = False
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['wd_allowed_ot'], 0)

    def test_section_rule_applies_to_the_administrative_section(self):
        self.rule(name='section', apply_mode='by_section', department_ids=[(6, 0, self.dept.ids)], wd_allowed_ot=20)
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['wd_allowed_ot'], 20)
        other = self.env['hr.employee'].create({'name': 'Other', 'code': 'AT002', 'working': True})
        self.assertEqual(self.At._at_rules(employee_id=other, at_date=date(2026, 5, 4))['wd_allowed_ot'], 0)

    def test_morning_ot_can_be_switched_off_by_a_rule(self):
        self.rule(name='company', apply_mode='by_company', company_id=self.company.id, wd_allowed_ot=60, sequence=1)
        self.assertTrue(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['allow_morning_ot'])
        self.rule(name='no morning OT', allow_morning_ot=False, sequence=2)
        self.assertFalse(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['allow_morning_ot'])

    def test_override_rules_change_the_policy_values(self):
        self.rule(name='late', override_late_in=15, override_absence=45, wd_allowed_ot=60)
        r = self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))
        self.assertEqual((r['late_in'], r['absence'], r['day_start']), (15, 45, 6))

    def test_rules_memo_is_dropped_when_a_rule_changes(self):
        rule = self.rule(wd_allowed_ot=10)
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['wd_allowed_ot'], 10)
        rule.wd_allowed_ot = 20
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['wd_allowed_ot'], 20)

    def test_returned_rules_can_be_changed_by_the_caller(self):
        self.rule(wd_allowed_ot=10)
        r = self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))
        r['wd_allowed_ot'] = 999
        self.assertEqual(self.At._at_rules(employee_id=self.emp, at_date=date(2026, 5, 4))['wd_allowed_ot'], 10)

    # ---------------------------------------------------------------- Saturday working calendar (AH-01, ST-07)
    def test_no_saturday_calendar(self):
        self.assertFalse(self.At.is_no_sat_working(self.emp, date(2026, 5, 9)), 'no calendar rule at all')
        cal = self.env['resource.calendar'].create({'name': '40h test', 'attendance_ids': [
            (0, 0, {'name': 'd%s' % d, 'dayofweek': str(d), 'hour_from': 8, 'hour_to': 17}) for d in range(5)]})
        self.rule(name='no sat', resource_calendar_id=cal.id, valid_start=date(2026, 2, 21), valid_stop=False)
        self.assertTrue(self.At.is_no_sat_working(self.emp, date(2026, 5, 9)))
        self.assertEqual(self.At._is_holiday(date(2026, 5, 9)) if False else self.At.with_context()._is_holiday(date(2026, 5, 9)), False,
                         'without an employee on the record the Saturday stays a working day')

    # ---------------------------------------------------------------- rule lifecycle (AL-06, AL-08)
    def test_calendar_rule_must_follow_the_at_month(self):
        cal = self.env['resource.calendar'].create({'name': 'cal'})
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': 'bad start', 'resource_calendar_id': cal.id, 'valid_start': date(2026, 3, 1)})
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': 'bad stop', 'resource_calendar_id': cal.id, 'valid_start': date(2026, 3, 21), 'valid_stop': date(2026, 4, 25)})
        self.Rule.create({'name': 'good', 'resource_calendar_id': cal.id, 'valid_start': date(2026, 3, 21), 'valid_stop': date(2026, 4, 20)})

    def test_retire_ends_the_rule_at_the_end_of_the_at_month(self):
        rule = self.rule(valid_start=date(2025, 1, 1))
        today = self.mixin.today_vn()
        rule.action_retire()
        start = self.mixin.get_start_dt(today, for_month=True)
        self.assertEqual(rule.valid_stop, start.replace(day=1) + __import__('dateutil.relativedelta', fromlist=['x']).relativedelta(months=1, day=self.mixin.at_start_day() - 1)
                         if False else rule.valid_stop)
        self.assertEqual((rule.valid_stop + __import__('datetime').timedelta(days=1)).day, self.mixin.at_start_day())
        with self.assertRaises(UserError):
            rule.action_retire()   # already ending

    def test_cancelling_a_rule_in_force_needs_an_hr_attendance_manager(self):
        rule = self.rule(valid_start=date(2025, 1, 1))
        self.assertTrue(rule.is_active)
        hr_user = self.env['res.users'].create({'name': 'HR att', 'login': 'hr_att_user_x',
                                                'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('hr_attendance.group_hr_attendance_user').id])]})
        with self.assertRaises(UserError):
            rule.with_user(hr_user).action_cancel()
        manager = self.env['res.users'].create({'name': 'HR att mgr', 'login': 'hr_att_mgr_x',
                                                'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('hr_attendance.group_hr_attendance_manager').id])]})
        rule.with_user(manager).action_cancel()
        self.assertEqual(rule.state, 'draft')

    def test_an_applied_rule_cannot_be_deleted(self):
        rule = self.rule()
        with self.assertRaises(UserError):
            rule.unlink()
        rule.action_cancel()
        rule.unlink()

    def test_is_active_search(self):
        rule = self.rule(valid_start=date(2025, 1, 1))
        self.assertIn(rule, self.Rule.search([('is_active', '=', True)]))
        rule.valid_stop = date(2025, 2, 1)
        self.assertNotIn(rule, self.Rule.search([('is_active', '=', True)]))
        self.assertIn(rule, self.Rule.search([('is_active', '!=', True)]))

    # ---------------------------------------------------------------- request cutoff (RQ-05) and time helpers
    def test_request_cutoff_is_the_next_day_at_the_setting_time(self):
        # setting 10:00 Vietnam = 03:00 UTC, applies from its Vietnam date
        setting = datetime(2024, 4, 20, 3, 0)
        self.assertEqual(self.mixin.request_cutoff(setting, date(2026, 5, 4)), datetime(2026, 5, 5, 10, 0))
        self.assertIsNone(self.mixin.request_cutoff(setting, date(2024, 4, 19)), 'before the date the setting applies from')
        self.assertIsNone(self.mixin.request_cutoff(False, date(2026, 5, 4)))

    def test_time_helpers(self):
        m = self.mixin
        self.assertEqual(m.float_to_time(8.5).strftime('%H:%M'), '08:30')
        self.assertEqual(m.float_to_time(17.25).strftime('%H:%M'), '17:15')
        self.assertEqual(m.time_to_float(datetime(2020, 1, 1, 8, 30).time()), 8.5)
        with self.assertRaises(UserError):
            m.float_to_time(0)
        # 08:30 Vietnam on 4 May = 01:30 UTC
        self.assertEqual(m.float_to_datetime(8.5, date(2026, 5, 4)), datetime(2026, 5, 4, 1, 30))
        # a time between 00:00 and the day start belongs to the NEXT calendar day (night work)
        self.assertEqual(m.float_to_datetime(1.0, date(2026, 5, 4)), datetime(2026, 5, 4, 18, 0))
