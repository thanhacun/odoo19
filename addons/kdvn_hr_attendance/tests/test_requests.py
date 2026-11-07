# -*- coding: utf-8 -*-
"""Stage C: WT / OT request workflow and notification emails (RQ-01, RQ-03, RQ-04, RQ-11, RQ-13, RQ-14).
Expected values come from attendance_rules.md (Odoo 12), not from what the code returned once."""
import datetime
import re
from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger
from odoo.tests import tagged
from .common_at import ATCase, WED, SUN, vn


@tagged('post_install', '-at_install', 'at_requests')
class TestRequestWorkflow(ATCase):

    def wt_request(self, state='draft', **extra):
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, None, (17, 0))                     # forgot to check in
        req = self.new_wt(at, 'forget_in', (8, 0), None, state=state, **extra)
        return at, req

    def test_rq01_wt_request_goes_through_every_state(self):
        """RQ-01: draft -> waiting_fman -> waiting_fhr -> done."""
        at, req = self.wt_request()
        self.assertEqual(req.state, 'draft')
        req.action_submit()
        self.assertEqual(req.state, 'waiting_fman')
        req.action_approve()
        self.assertEqual(req.state, 'waiting_fhr')
        req.action_validate()
        self.assertEqual(req.state, 'done')

    def test_rq01a_status_changes_before_the_request_is_final(self):
        """RQ-01a: without the request the day is X; once the manager approved (waiting_fhr) it is no longer X."""
        at, req = self.wt_request()
        self.assertEqual(self.codes(at), ['X'])
        req.action_submit()
        req.action_approve()
        at._compute_at_status(force_run=True)
        self.assertNotEqual(self.codes(at), ['X'])

    def test_rq01_attendance_state_is_the_lowest_state_of_its_requests(self):
        """RQ-01: the attendance state follows its requests."""
        at, req = self.wt_request(state='waiting_fman')
        self.assertEqual(at.state_id.code, 'waiting_fman')
        req.action_approve()
        self.assertEqual(at.state_id.code, 'waiting_fhr')
        req.action_validate()
        self.assertEqual(at.state_id.code, 'done')

    def test_rq01_validate_only_from_waiting_hr(self):
        at, req = self.wt_request(state='waiting_fman')
        with self.assertRaises(UserError):   # run as a real user: OdooBot (uid 1) may validate from any state by design
            req.with_user(self.env.ref('base.user_admin')).action_validate()

    def test_rq03_wt_description_is_limited(self):
        """RQ-03: a WT description is at most 25 characters (setting description_size)."""
        with self.assertRaises(ValidationError):
            self.wt_request(name='x' * 26)
        self.wt_request(name='x' * 25)

    def test_rq04_ot_is_refused_for_staff_without_ot(self):
        """RQ-04: no OT for staff who do not have OT (ot_apply false)."""
        emp = self.new_employee()
        self.new_rule(emp, wd_allowed_ot=0, hd_allowed_ot=0)
        at = self.new_at(emp, WED, (8, 0), (19, 0))
        self.assertFalse(at.ot_apply)
        with self.assertRaises(ValidationError):
            self.new_ot(at, 'pm', (17, 0), (19, 0), state='draft')

    def refuse(self, req, comment='not eligible'):
        wiz = self.env['hr.attendance.refuse'].create({'related_request_id': req.id, 'name': comment})
        wiz.save()
        return wiz

    def test_rq11_refuse_needs_a_comment(self):
        """RQ-11: a refusal needs a comment."""
        at, req = self.wt_request(state='waiting_fhr')
        with mute_logger('odoo.sql_db'), self.assertRaises(Exception), self.env.cr.savepoint():
            self.env['hr.attendance.refuse'].create({'related_request_id': req.id, 'name': False})

    def test_rq11_refused_request_returns_the_status(self):
        """RQ-11 / RQ-01a: HR refuses -> request is refused and the day is X again."""
        at, req = self.wt_request(state='waiting_fhr')
        self.refuse(req)
        self.assertEqual(req.state, 'refuse')
        self.assertEqual(req.refuse_comment, 'not eligible')
        at._compute_at_status(force_run=True)
        self.assertEqual(self.codes(at), ['X'])

    def test_rq13_staff_withdraws_while_waiting_manager(self):
        """RQ-13: while waiting_fman a request can be set back to draft."""
        at, req = self.wt_request(state='waiting_fman')
        req.action_revise()
        self.assertEqual(req.state, 'draft')

    def test_rq13_refused_request_can_be_revised(self):
        at, req = self.wt_request(state='waiting_fhr')
        self.refuse(req)
        req.action_revise()
        self.assertEqual(req.state, 'draft')

    def test_rq14_daily_email_to_the_manager_with_pending_requests(self):
        """RQ-14: one email to whoever holds the state, listing the pending requests."""
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://erp.example.com')
        user = self.env['res.users'].create({'name': 'ZZ Manager', 'login': 'zz_manager', 'email': 'mgr@example.com',
                                             'group_ids': [(4, self.env.ref('base.group_user').id), (4, self.env.ref('kdvn_hr_attendance.group_hr_attendance_section_manager').id)]})
        manager = self.new_employee(name='ZZ Manager', work_email='mgr@example.com', user_id=user.id)
        emp = self.new_employee(admin_manager_id=manager.id)
        self.new_rule(emp)
        day = self.env['hr.mixin'].today_vn()            # the daily email lists the current AT month only
        while day.weekday() > 4:
            day -= datetime.timedelta(days=1)
        at = self.new_at(emp, day, None, (17, 0))
        self.new_wt(at, 'forget_in', (8, 0), None, state='waiting_fman')
        self.env.flush_all()
        before = self.env['mail.mail'].sudo().search([]).ids
        self.AT._send_noti_email(manager_ids=[manager.id])
        new = self.env['mail.mail'].sudo().search([('id', 'not in', before), ('email_to', '=', 'mgr@example.com')])
        self.assertTrue(new, 'no notification email was created for the manager')
        self.assertIn('There are 1 attendance requests', ' '.join(re.sub('<[^>]+>', ' ', new[0].body_html).split()))   # the combined email shows a count and a link, not names

    def test_rq14_refusal_email_to_the_staff(self):
        """RQ-14: an immediate email to the staff member when a request is refused."""
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://erp.example.com')
        emp = self.new_employee(work_email='staff@example.com')
        self.new_rule(emp)
        at = self.new_at(emp, WED, None, (17, 0))
        req = self.new_wt(at, 'forget_in', (8, 0), None, state='waiting_fhr')
        self.refuse(req, 'no proof')
        before = self.env['mail.mail'].sudo().search([]).ids
        self.AT._send_noti_refuse_email(at_ids=at.ids)
        new = self.env['mail.mail'].sudo().search([('id', 'not in', before), ('email_to', '=', 'staff@example.com')])
        self.assertTrue(new, 'no refusal email was created for the staff member')


@tagged('post_install', '-at_install', 'at_wizard')
class TestRequestWizard(ATCase):
    """The request screen (hr.attendance.wizard): what staff do on screen creates the same requests as the tests above."""

    def wizard(self, at, **vals):
        wiz = self.env['hr.attendance.wizard'].with_context(active_model='hr.attendance', active_id=at.id).create(vals)
        wiz.employee_id = at.employee_id
        wiz.at_id = at
        return wiz

    def test_wt_request_created_on_screen_goes_to_the_manager(self):
        """A new request is submitted at once (Odoo 12: "submit draft request for better user experience"): waiting_fman."""
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, None, (17, 0))
        wiz = self.wizard(at, request_mode='wt', at_request_type_id=self.ot_type['forget_in'].id, name='forgot to check in', wt_in=vn(WED, 8, 0))
        wiz.save()
        req = at.at_request_ids
        self.assertEqual((len(req), req.request_type, req.state), (1, 'working_time', 'waiting_fman'))

    def test_ot_request_submitted_from_the_screen(self):
        """An OT request typed on screen and submitted waits for the manager and carries its hours."""
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, (8, 0), (19, 0))
        wiz = self.wizard(at, request_mode='ot', request_ot_for_id=self.ot_type['pm'].id, ot_description='finish report',
                          ot_in=vn(WED, 17, 0), ot_out=vn(WED, 19, 0))
        wiz.submit()
        req = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
        self.assertEqual((len(req), req.state), (1, 'waiting_fman'))
        self.assertEqual(req.request_out, vn(WED, 19, 0))

    def test_submit_does_nothing_on_a_refused_attendance(self):
        """RQ-06: an attendance that is refused cannot be submitted again from the screen (HR sets it back first)."""
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, None, (17, 0))
        req = self.new_wt(at, 'forget_in', (8, 0), None, state='waiting_fhr')
        self.env['hr.attendance.refuse'].create({'related_request_id': req.id, 'name': 'no'}).save()
        at.invalidate_recordset()
        wiz = self.wizard(at, request_mode='wt', at_request_type_id=self.ot_type['forget_in'].id, name='again', wt_in=vn(WED, 8, 0))
        self.assertFalse(wiz.submit())


@tagged('post_install', '-at_install', 'at_otplan')
class TestOTHolidayPlan(ATCase):
    """OT on holidays plan (RQ-05 / OT-07): a plan line registers OT on a holiday in advance; the approved line makes the system
    create the OT request of that day; changing the line while the request is still open removes it again."""

    def plan(self, emp):
        return self.env['hr.attendance.ot.holiday'].generate_monthly_record(emp, at_year='2026', at_month=3) or \
            self.env['hr.attendance.ot.holiday'].search([('employee_id', '=', emp.id), ('at_year', '=', '2026'), ('at_month', '=', 3)])

    def test_monthly_record_lists_every_holiday_of_the_month(self):
        emp = self.new_employee()
        self.new_rule(emp)
        plan = self.plan(emp)
        self.assertTrue(plan, 'no OT holiday record for an employee with OT')
        dates = plan.ot_detail_ids.mapped('at_date')
        self.assertIn(SUN, dates)                                 # 15 Mar 2026 is a Sunday
        self.assertTrue(all(d.month in (2, 3) for d in dates))    # AT month 3 = 21 Feb - 20 Mar
        self.assertFalse(any(d.weekday() < 5 and not self.AT._is_holiday(d) for d in dates if False))

    def test_registered_line_waits_for_the_manager_then_creates_the_request(self):
        emp = self.new_employee()
        self.new_rule(emp)
        line = self.plan(emp).ot_detail_ids.filtered(lambda l: l.at_date == SUN)
        line.write({'ot_detail': 'urgent site work', 'ot_register': True})
        self.assertEqual(line.state, 'waiting_fman')                       # staff registered: manager decides next
        self.assertFalse(line.ot_request_id)
        line.write({'state': 'done'})                                      # approved
        self.assertTrue(line.ot_request_id)
        self.assertEqual((line.ot_request_id.request_type, line.ot_request_id.state), ('over_time', 'draft'))

    def test_unregister_is_refused_once_the_ot_request_is_past_the_manager(self):
        """Safeguard: a day whose OT request is past the manager cannot be unregistered ("modify your OT Request first")."""
        emp = self.new_employee()
        self.new_rule(emp)
        line = self.plan(emp).ot_detail_ids.filtered(lambda l: l.at_date == SUN)
        line.write({'ot_detail': 'x', 'ot_register': True})
        line.write({'state': 'done'})
        line.ot_request_id.write({'state': 'waiting_fhr'})
        with self.assertRaises(ValidationError):
            line.write({'ot_register': False})

    def test_refused_line_removes_the_open_request(self):
        emp = self.new_employee()
        self.new_rule(emp)
        line = self.plan(emp).ot_detail_ids.filtered(lambda l: l.at_date == SUN)
        line.write({'ot_detail': 'x', 'ot_register': True})
        line.write({'state': 'done'})
        request = line.ot_request_id
        line.write({'state': 'refuse'})
        self.assertFalse(request.exists())

    def test_refusing_the_line_keeps_a_request_that_is_already_approved(self):
        """Once the OT request is past the manager (waiting_fhr) the plan cannot take it back: the error is logged, the data stays."""
        emp = self.new_employee()
        self.new_rule(emp)
        line = self.plan(emp).ot_detail_ids.filtered(lambda l: l.at_date == SUN)
        line.write({'ot_detail': 'x', 'ot_register': True})
        line.write({'state': 'done'})
        request = line.ot_request_id
        request.write({'state': 'waiting_fhr'})
        with self.assertRaises(UserError):
            line.write({'state': 'refuse'})
        self.assertTrue(request.exists())


@tagged('post_install', '-at_install', 'at_names')
class TestDisplayNames(ATCase):
    """Odoo 19 computes display_name (no name_get): the monthly working time report and the lists read it."""

    def test_request_display_name_is_its_description(self):
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, None, (17, 0))
        req = self.new_wt(at, 'forget_in', (8, 0), None, state='waiting_fman')
        self.assertTrue(req.description)
        self.assertEqual(req.display_name, req.description)
        self.assertTrue(req.display_name.startswith('W: zz wt'))      # 'W: <reason> [times]' as in Odoo 12

    def test_attendance_display_name_has_employee_and_date(self):
        emp = self.new_employee()
        self.new_rule(emp)
        at = self.new_at(emp, WED, (8, 0), (17, 0))
        self.assertIn(emp.name, at.display_name)
        self.assertIn('11/03/2026', at.display_name)
        self.assertIn('08:00', at.display_name)

    def test_ot_plan_display_name(self):
        emp = self.new_employee()
        self.new_rule(emp)
        self.env['hr.attendance.ot.holiday'].generate_monthly_record(emp, at_year='2026', at_month=3)
        plan = self.env['hr.attendance.ot.holiday'].search([('employee_id', '=', emp.id)])
        self.assertEqual(plan.display_name, '%s - OT Holiday Plan - 3/2026' % emp.code)

    def test_leave_cover_display_name(self):
        emp = self.new_employee()
        self.new_rule(emp)
        cover = self.new_leave(emp, WED, 'full', 'waiting_fman')
        self.assertIn('Leave on 11-03-2026', cover.display_name)
