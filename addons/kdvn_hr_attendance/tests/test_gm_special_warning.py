# -*- coding: utf-8 -*-
"""GM approval step (RQ-01, RQ-07), ad hoc Special Leave expiry (LV-11, LV-12) and the OT warnings (AL-01, AL-02).
Dates of the special-leave tests are relative to today (expiry depends on today)."""
import datetime
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from .common_at import ATCase, WED, SUN


@tagged('post_install', '-at_install', 'at_gm')
class TestGMApproval(ATCase):
    """RQ-01 / RQ-07: HR can send a request that is waiting for HR to the GM (waiting_fman2); the GM approves -> done."""

    def ot_waiting_hr(self):
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, (8, 0), (19, 0))
        req = self.new_ot(at, 'pm', (17, 0), (19, 0), state='waiting_fhr')
        return at, req

    def test_rq07_hr_sends_request_to_gm(self):
        """RQ-07: HR 'needs director' on a request waiting for HR -> it waits for the GM, flagged 'Need GM approve'."""
        at, req = self.ot_waiting_hr()
        req.action_need_director()
        self.assertEqual((req.state, req.man2_approve), ('waiting_fman2', True))

    def test_rq07_gm_approves_to_done(self):
        """RQ-07: the GM approves -> the request is done."""
        at, req = self.ot_waiting_hr()
        req.action_need_director()
        req.action_approve_man2()
        self.assertEqual(req.state, 'done')

    def test_rq07_only_from_waiting_hr(self):
        """RQ-07: only a request waiting for HR can be sent to the GM (a draft cannot)."""
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, (8, 0), (19, 0))
        req = self.new_ot(at, 'pm', (17, 0), (19, 0), state='draft')
        with self.assertRaises(Exception) as ctx:
            req.action_need_director()
        self.assertIn('HR validate', str(ctx.exception))

    def test_rq07_gm_approval_cannot_skip_waiting_fman2(self):
        """RQ-07: the GM approve action does nothing for a request that is not waiting for the GM."""
        at, req = self.ot_waiting_hr()
        req.action_approve_man2()
        self.assertEqual(req.state, 'waiting_fhr')

    def test_rq01_attendance_follows_the_request_to_gm(self):
        """RQ-01: the attendance shows the lowest state of its requests: waiting for GM, then done."""
        at, req = self.ot_waiting_hr()
        at.action_need_director()
        at.invalidate_recordset()
        self.assertEqual(at.state_id.code, 'waiting_fman2')
        req.action_approve_man2()
        at.invalidate_recordset()
        self.assertEqual(at.state_id.code, 'done')

    def test_rq01_revise_clears_the_gm_flag(self):
        """RQ-01: revising a request back to draft clears 'Need GM approve'."""
        at, req = self.ot_waiting_hr()
        req.action_need_director()
        req.action_revise()
        self.assertEqual((req.state, req.man2_approve), ('draft', False))

    def test_rq07_leave_goes_to_gm_too(self):
        """RQ-07: the same for a leave request (e.g. 5 consecutive days): waiting_fhr -> GM -> done."""
        emp = self.new_employee()
        self.new_rule(emp)
        cover = self.new_leave(emp, WED, 'full', 'waiting_fhr')
        cover.action_need_director()
        self.assertEqual(cover.state, 'waiting_fman2')
        cover.action_approve_man2()
        self.assertEqual(cover.state, 'done')


@tagged('post_install', '-at_install', 'at_special')
class TestSpecialLeave(ATCase):
    """LV-11 / LV-12: ad hoc 'Special Leave' grants last one month and expire."""

    def setUp(self):
        super().setUp()
        self.today = datetime.date.today()
        self.stype = self.env['hr.leave.type'].search([('is_special', '=', True), ('category', '=', 'other')], limit=1)

    def grant(self, emp, start_offset, end_offset, days=2):
        alloc = self.env['hr.leave.allocation'].create({
            'name': 'zz special', 'holiday_status_id': self.stype.id, 'employee_id': emp.id, 'number_of_days': days,
            'valid_from': self.today + datetime.timedelta(days=start_offset),
            'valid_to': self.today + datetime.timedelta(days=end_offset)})
        for step in ('action_confirm', 'action_approve', 'action_validate'):
            try:
                getattr(alloc, step)()
            except Exception:
                pass
        return alloc

    def balance(self, emp):
        return self.stype.get_days(emp.id)[self.stype.id]['remaining_leaves']

    def test_lv11_valid_grant_counts(self):
        """LV-11: a grant of 2 days that is still valid gives a balance of 2."""
        emp = self.new_employee()
        alloc = self.grant(emp, -5, 20)
        self.assertEqual((alloc.is_expired, self.balance(emp)), (False, 2))

    def test_lv11_expired_grant_is_ignored(self):
        """LV-11: after valid_to the grant is 'expired', stays approved, and no longer counts (balance 0)."""
        emp = self.new_employee()
        alloc = self.grant(emp, -60, -35)
        self.assertEqual((alloc.state, alloc.is_expired, self.balance(emp)), ('validate', True, 0))

    def test_lv11_expired_search(self):
        """LV-11: the 'Expired' filter finds the expired grant and not the valid one."""
        emp = self.new_employee()
        old = self.grant(emp, -60, -35)
        new = self.grant(emp, -5, 20)
        Alloc = self.env['hr.leave.allocation']
        self.assertIn(old, Alloc.search([('employee_id', '=', emp.id), ('is_expired', '=', True)]))
        self.assertNotIn(new, Alloc.search([('employee_id', '=', emp.id), ('is_expired', '=', True)]))

    def test_lv11_only_the_valid_grant_counts_when_both_exist(self):
        """LV-11: an expired grant (2 days) and a valid one (3 days): balance is 3, not 5."""
        emp = self.new_employee()
        self.grant(emp, -60, -35, days=2)
        self.grant(emp, -5, 20, days=3)
        self.assertEqual(self.balance(emp), 3)

    def test_lv12_overlapping_grant_is_blocked(self):
        """LV-12: a second grant whose window overlaps an existing one is blocked."""
        emp = self.new_employee()
        self.grant(emp, -5, 20)
        with self.assertRaises(ValidationError) as ctx:
            self.grant(emp, 10, 30)
        self.assertIn('already has a special leave', str(ctx.exception))

    def test_lv11_leave_must_fall_inside_the_window(self):
        """LV-11: a special leave on a day after the grant window is refused."""
        emp = self.new_employee()
        self.new_rule(emp)
        self.grant(emp, -5, 20)
        day = self.today + datetime.timedelta(days=60)
        while day.weekday() > 3:
            day += datetime.timedelta(days=1)
        reason = self.env['hr.leave.cover.reason'].search([], limit=1)
        with self.assertRaises(Exception) as ctx:      # the screen wraps the message in "Cannot create leave..."
            self.env['hr.leave.cover'].create_cover(reason.id, self.stype.id, day, employee_id=emp.id)
        self.assertIn('only allowed to register special leave between', str(ctx.exception))


@tagged('post_install', '-at_install', 'at_ot_warning')
class TestOTWarning(ATCase):
    """AL-02: daily warning: weekday OT above 4 hours, holiday OT above 12 hours. AL-01/AL-02: monthly and weekly limits."""

    def warning(self, at):
        at._compute_ot_warning()
        return at.ot_warning or ''

    def weekday_ot(self, hours, **rule):
        emp = self.new_employee()
        self.new_rule(emp, **rule)
        end = 17 + hours
        at = self.new_at(emp, WED, (8, 0), (end, 0))
        self.new_ot(at, 'pm', (17, 0), (end, 0))
        at._compute_at_status(force_run=True)
        return at

    def test_al02_weekday_4_hours_no_warning(self):
        """AL-02: 4 h weekday OT -> no daily warning."""
        self.assertNotIn('weekday limit of 4', self.warning(self.weekday_ot(4)))

    def test_al02_weekday_5_hours_warns(self):
        """AL-02: 5 h weekday OT -> 'Over weekday limit of 4 hours.'"""
        self.assertIn('Over weekday limit of 4 hours', self.warning(self.weekday_ot(5)))

    def holiday_ot(self, hours):
        emp = self.new_employee()
        self.new_rule(emp)
        self.new_ot_plan(emp, SUN)
        end = 8 + hours + 1          # + 1 h lunch that is deducted
        at = self.new_at(emp, SUN, (8, 0), (end, 0))
        self.new_ot(at, 'both', (8, 0), (end, 0))
        at._compute_at_status(force_run=True)
        return at

    def test_al02_holiday_12_hours_no_warning(self):
        """AL-02: 12 h holiday OT -> no daily warning."""
        self.assertNotIn('holiday limit of 12', self.warning(self.holiday_ot(12)))

    def test_al02_holiday_13_hours_warns(self):
        """AL-02: 13 h holiday OT -> 'Over holiday limit of 12 hours.'"""
        self.assertIn('Over holiday limit of 12 hours', self.warning(self.holiday_ot(13)))

    def test_al01_monthly_weekday_limit_warns(self):
        """AL-01: 4 h OT with a monthly weekday limit of 1 h -> 'Over monthly weekday limit.'"""
        at = self.weekday_ot(4, wd_allowed_ot=1)
        self.AT._compute_ot_allow()
        at.invalidate_recordset()
        self.assertIn('Over monthly weekday limit', self.warning(at))
