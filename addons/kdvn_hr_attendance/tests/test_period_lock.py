# -*- coding: utf-8 -*-
"""Period lock: attendance periods older than `lock_months` (3) are closed for payroll (models/period_lock.py).
The data is built with the lock OFF (company.lock_months = 0, as ATCase does), then the lock is switched on, so the old days exist
exactly as they would after a payroll closing."""
import datetime

from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common_at import ATCase, vn


@tagged('post_install', '-at_install', 'at_period_lock')
class TestPeriodLock(ATCase):

    def setUp(self):
        super().setUp()
        today = fields.Date.context_today(self.AT)
        self.cutoff = self.AT.get_start_dt(today - relativedelta(months=3), for_month=True)
        self.old_day = self._weekday(self.cutoff - datetime.timedelta(days=40))        # a Wednesday, in a closed period
        self.open_day = self._weekday(self.cutoff + datetime.timedelta(days=30))       # a Wednesday, in an open period
        self.emp = self.new_employee()
        self.new_rule(self.emp)
        self.old_at = self.new_at(self.emp, self.old_day, (8, 0), (17, 0))
        self.open_at = self.new_at(self.emp, self.open_day, (8, 0), (17, 0))
        self.env.company.lock_months = 3        # lock ON from here

    @staticmethod
    def _weekday(day, weekday=2):
        return day + datetime.timedelta(days=(weekday - day.weekday()) % 7)

    def _user(self, login, hr_admin):
        existing = self.env['res.users'].search([('login', '=', login)])
        if existing:
            return existing
        groups = [self.env.ref('base.group_user').id]
        if hr_admin:
            groups.append(self.env.ref('hr_attendance.group_hr_attendance_user').id)
        return self.env['res.users'].with_context(no_reset_password=True).create({'name': login, 'login': login, 'group_ids': [(6, 0, groups)]})

    def _unlock(self, user=None, **extra):
        vals = {'employee_id': self.emp.id, 'date_from': self.old_day, 'date_to': self.old_day, 'reason': 'Payroll correction'}
        vals.update(extra)
        return self.env['hr.attendance.period.unlock'].with_user(user or self._user('zzhradmin', True)).create(vals)

    # ---- locked day: nothing changes ----------------------------------------------------------------------------------
    def test_pl01_locked_day_is_locked_open_day_is_not(self):
        self.assertTrue(self.old_at.period_locked)
        self.assertFalse(self.open_at.period_locked)
        self.assertIn(self.old_at, self.AT.search([('period_locked', '=', True)]))
        self.assertNotIn(self.open_at, self.AT.search([('period_locked', '=', True)]))
        self.assertIn(self.open_at, self.AT.search([('period_locked', '=', False)]))

    def test_pl02_write_on_a_locked_day_is_refused(self):
        with self.assertRaises(UserError):
            self.old_at.write({'check_in': vn(self.old_day, 9, 0)})
        with self.assertRaises(UserError):
            self.old_at.write({'allow_late_ot': False})
        with self.assertRaises(UserError):
            self.old_at.sudo().write({'check_out': vn(self.old_day, 18, 0)})          # sudo does not bypass

    def test_pl03_archive_and_org_fields_are_not_locked(self):
        self.old_at.write({'active': False})
        self.old_at.write({'active': True})

    def test_pl04_locked_day_cannot_be_deleted_or_created(self):
        with self.assertRaises(UserError):
            self.old_at.unlink()
        emp2 = self.new_employee()
        with self.assertRaises(UserError):
            self.AT.create({'employee_id': emp2.id, 'code': 'AT-%s-%s' % (self.old_day.strftime('%y%m%d'), emp2.code)})

    def test_pl05_recompute_keeps_the_stored_values(self):
        """A recompute of an old day (status, request marks, flush of stored computes) must not change what payroll read."""
        x_status = self.env.ref('kdvn_hr_attendance.at_status_absence')
        self.env.company.lock_months = 0
        self.old_at.write({'status_ids': [(6, 0, [x_status.id])]})     # stored value as payroll saw it
        self.old_at._compute_status_codes()
        self.env.flush_all()
        self.env.company.lock_months = 3
        before = (self.codes(self.old_at), self.old_at.status_codes, self.old_at.ot_total, self.old_at.absence, self.old_at.state)
        self.old_at._compute_at_status(force_run=True)
        self.old_at._compute_related_states()
        self.old_at._compute_ot_request()
        self.old_at._compute_request_description()
        self.old_at._compute_status_codes()
        self.env.flush_all()
        self.env.invalidate_all()
        after = (self.codes(self.old_at), self.old_at.status_codes, self.old_at.ot_total, self.old_at.absence, self.old_at.state)
        self.assertEqual(before, after)

    def test_pl06_open_day_still_recomputes_and_can_change(self):
        self.open_at.write({'check_out': vn(self.open_day, 18, 0)})
        self.open_at._compute_at_status(force_run=True)
        self.assertEqual(self.codes(self.open_at), ['O'])

    def test_pl07_raw_sync_leaves_a_locked_day_alone(self):
        check_in, check_out = self.old_at.check_in, self.old_at.check_out
        self.env['hr.attendance.raw']._sync_attendance_record(at_date=self.old_day, duration=1, employee_ids=[self.emp.id])
        self.env.invalidate_all()
        self.assertEqual((self.old_at.check_in, self.old_at.check_out), (check_in, check_out))     # without the lock the missing raw data empties them

    # ---- requests, leave covers, leaves --------------------------------------------------------------------------------
    def test_pl10_request_on_a_locked_day_is_refused(self):
        with self.assertRaises(UserError):
            self.new_wt(self.old_at, 'forget_in', (8, 0), None, state='draft')

    def test_pl11_existing_request_cannot_be_approved_on_a_locked_day(self):
        self.env.company.lock_months = 0
        req = self.new_wt(self.old_at, 'forget_in', (8, 0), (17, 0), state='waiting_fman')
        self.env.company.lock_months = 3
        with self.assertRaises(UserError):
            req.action_approve()
        with self.assertRaises(UserError):
            req.write({'state': 'refuse'})
        self.assertEqual(req.state, 'waiting_fman')

    def test_pl12_request_on_an_open_day_works(self):
        req = self.new_wt(self.open_at, 'forget_in', (8, 0), (17, 0), state='waiting_fman')
        req.action_approve()
        self.assertEqual(req.state, 'waiting_fhr')

    def test_pl13_leave_on_a_locked_day_is_refused(self):
        ltype = self.env['hr.leave.type'].search([('name', '=', 'Absence')], limit=1)
        reason = self.env['hr.leave.cover.reason'].search([], limit=1)
        with self.assertRaises(UserError):
            self.env['hr.leave.cover'].create_cover(reason.id, ltype.id, self.old_day, employee_id=self.emp.id)

    def test_pl14_leave_spanning_locked_and_open_days_is_refused_with_the_dates(self):
        ltype = self.env['hr.leave.type'].search([('name', '=', 'Absence')], limit=1)
        reason = self.env['hr.leave.cover.reason'].search([], limit=1)
        with self.assertRaises(UserError) as caught:
            self.env['hr.leave.cover'].create_cover(reason.id, ltype.id, self.cutoff - datetime.timedelta(days=2),
                                                    to_date=self.cutoff + datetime.timedelta(days=2), employee_id=self.emp.id)
        self.assertIn((self.cutoff - datetime.timedelta(days=1)).strftime('%d/%m/%Y'), str(caught.exception))
        self.assertNotIn((self.cutoff + datetime.timedelta(days=1)).strftime('%d/%m/%Y'), str(caught.exception))

    def test_pl15_existing_cover_cannot_change_state_on_a_locked_day(self):
        self.env.company.lock_months = 0
        cover = self.new_leave(self.emp, self.old_day, state='waiting_fman')
        self.env.company.lock_months = 3
        with self.assertRaises(UserError):
            cover.action_approve()

    def test_pl16_leave_on_an_open_day_works(self):
        cover = self.new_leave(self.emp, self.open_day, state='waiting_fman')
        cover.action_approve()
        self.assertEqual(cover.state, 'waiting_fhr')

    # ---- unlock --------------------------------------------------------------------------------------------------------
    def test_pl20_hr_admin_unlocks_and_the_day_is_noted(self):
        unlock = self._unlock()
        self.env.invalidate_all()
        self.assertFalse(self.old_at.period_locked)
        self.assertNotIn(self.old_at, self.AT.search([('period_locked', '=', True)]))
        self.old_at.write({'check_out': vn(self.old_day, 18, 0)})        # allowed now
        notes = self.old_at.message_ids.filtered(lambda m: 'unlocked' in (m.body or '') and 'Payroll correction' in (m.body or ''))
        self.assertTrue(notes, 'the unlocked day has a note with the reason')
        self.assertEqual(unlock.user_id.login, 'zzhradmin')

    def test_pl21_unlock_is_limited_to_its_employee_and_dates(self):
        self._unlock()
        other = self.new_employee()
        self.new_rule(other)
        self.assertFalse(self.AT._period_is_locked(self.emp.id, self.old_day))
        self.assertTrue(self.AT._period_is_locked(other.id, self.old_day))
        self.assertTrue(self.AT._period_is_locked(self.emp.id, self.old_day - datetime.timedelta(days=1)))

    def test_pl22_unlock_expires_and_can_be_ended(self):
        unlock = self._unlock()
        self.assertFalse(self.old_at.period_locked)
        unlock.sudo().write({'expires_at': fields.Datetime.now() - datetime.timedelta(seconds=1)})   # time passed
        self.env.invalidate_all()
        self.assertTrue(self.old_at.period_locked)
        with self.assertRaises(UserError):
            self.old_at.write({'check_in': vn(self.old_day, 9, 0)})
        unlock2 = self._unlock()
        self.env.invalidate_all()
        self.assertFalse(self.old_at.period_locked)
        unlock2.with_user(self.env['res.users'].search([('login', '=', 'zzhradmin')])).action_lock_again()
        self.env.invalidate_all()
        self.assertTrue(self.old_at.period_locked)

    def test_pl23_only_hr_admin_can_unlock(self):
        with self.assertRaises(AccessError):
            self._unlock(user=self._user('zzplain', False))
        self.assertTrue(self.old_at.period_locked)

    def test_pl24_an_unlock_cannot_be_edited_or_deleted(self):
        unlock = self._unlock()
        with self.assertRaises(UserError):
            unlock.write({'date_from': self.old_day - datetime.timedelta(days=30)})
        with self.assertRaises(UserError):
            unlock.sudo().unlink()

    def test_pl25_unlock_needs_a_reason(self):
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._unlock(reason=False)

    # ---- switches ------------------------------------------------------------------------------------------------------
    def test_pl30_importer_context_bypasses_the_lock(self):
        self.old_at.with_context(kdvn_period_lock_off=True).write({'check_in': vn(self.old_day, 9, 0)})
        self.assertEqual(self.old_at.check_in, vn(self.old_day, 9, 0))

    def test_pl31_zero_months_means_no_lock(self):
        self.env.company.lock_months = 0
        self.assertFalse(self.old_at.period_locked)
        self.old_at.write({'allow_late_ot': False})

    def test_pl32_the_cutoff_follows_the_attendance_period(self):
        """21st..20th periods: the cutoff is the first day of the period that holds (today - lock_months)."""
        self.assertEqual(self.cutoff.day, 21)
        self.assertTrue(self.AT._period_is_locked(self.emp.id, self.cutoff - datetime.timedelta(days=1)))
        self.assertFalse(self.AT._period_is_locked(self.emp.id, self.cutoff))
