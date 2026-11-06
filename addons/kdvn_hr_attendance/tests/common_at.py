# -*- coding: utf-8 -*-
"""Shared fixtures for the attendance tests.

Every test builds its own employee, rule and attendance, so no production staff or data is needed. Expected values
come from `attendance_rules.md` (rule ids in the test names), NOT from what the code returned once.
Times are written in Vietnam time (VN) and stored in UTC like the module does (utc_diff = 7).
Dates are fixed in the past: with the delay policy the attendance is already 'old', so status is decided.
"""
import datetime
from odoo.tests import common

UTC_DIFF = 7
WED = datetime.date(2026, 3, 11)        # normal weekday (not a public holiday)
SUN = datetime.date(2026, 3, 15)        # Sunday = H
MON_PH = datetime.date(2026, 3, 16)     # made a public holiday by the tests that need it
MON_CD = datetime.date(2026, 3, 17)     # made a company day (OH) by the tests that need it


def vn(day, hour, minute=0):
    """Vietnam local time -> naive UTC datetime as stored in the database."""
    return datetime.datetime(day.year, day.month, day.day, hour, minute) - datetime.timedelta(hours=UTC_DIFF)


class ATCase(common.TransactionCase):

    def setUp(self):
        super().setUp()
        self.AT = self.env['hr.attendance']
        self.Req = self.env['hr.attendance.request']
        self.Rule = self.env['hr.attendance.rule']
        self._n = 0
        self.ot_type = {t.code: t for t in self.env['hr.attendance.request.type'].search([])}
        self.AT.clear_at_rules_memo()
        # production calendars use the Vietnam timezone: the attendance code reads working hours from the calendar in its timezone
        self.env.company.resource_calendar_id.tz = 'Asia/Ho_Chi_Minh'
        # Sequences are not rolled back, so every test run burns employee ids. The summary index on hr_attendance is
        # (employee_id * 1000000 + year * 100 + month)::integer and overflows above employee id 2147 ("integer out of
        # range" on any attendance write). Put the sequence back to the real maximum before each test (test databases only).
        self.env.cr.execute("SELECT setval('hr_employee_id_seq', (SELECT max(id) FROM hr_employee))")

    # ---- fixtures -------------------------------------------------------------------------------------------------
    def new_employee(self, **extra):
        self._n += 1
        vals = {'name': 'ZZ Test %02d' % self._n, 'code': 'ZZT%02d' % self._n, 'working': True,
                'company_id': self.env.user.company_id.id}
        vals.update(extra)
        return self.env['hr.employee'].create(vals)

    def new_rule(self, emp, **vals):
        """Rule for one employee, applied after every company rule (sequence 1000) so the production rules of the
        copy used for testing cannot change the result. Defaults: OT allowed (60/30 h), morning OT allowed."""
        v = {'name': 'ZZ test rule', 'apply_mode': 'by_employee', 'employee_ids': [(4, emp.id)],
             'valid_start': datetime.date(2026, 1, 1), 'sequence': 1000,
             'wd_allowed_ot': 60, 'hd_allowed_ot': 30, 'allow_morning_ot': True}
        v.update(vals)
        rule = self.Rule.create(v)
        rule.action_submit()
        self.AT.clear_at_rules_memo()
        return rule

    def new_at(self, emp, day, check_in=None, check_out=None, **extra):
        """check_in / check_out are (hour, minute) in Vietnam time."""
        code = 'AT-%s-%s' % (day.strftime('%y%m%d'), emp.code)
        vals = {'employee_id': emp.id, 'code': code, 'allow_late_ot': True}
        if check_in:
            vals['check_in'] = vn(day, *check_in)
        if check_out:
            vals['check_out'] = vn(day, *check_out)
        vals.update(extra)
        at = self.AT.search([('code', '=', code)])      # a leave request creates the attendance of its day
        if at:
            at.write({k: v for k, v in vals.items() if k not in ('employee_id', 'code')})
        else:
            at = self.AT.create(vals)
        at._compute_at_status(force_run=True)
        return at

    def new_leave(self, emp, day, part='full', state='done', leave_type='Annual Leave'):
        """Leave of one day. part: full | am (morning off) | pm (afternoon off).
        state: waiting_fman (just submitted) | waiting_fhr (manager approved) | done (HR validated)."""
        ltype = self.env['hr.leave.type'].search([('name', '=', leave_type)], limit=1)
        self.env['hr.leave.allocation'].create({'name': 'zz test', 'holiday_status_id': ltype.id, 'employee_id': emp.id, 'number_of_days': 10})
        alloc = self.env['hr.leave.allocation'].search([('employee_id', '=', emp.id)])
        for step in ('action_confirm', 'action_approve', 'action_validate'):
            try:
                getattr(alloc, step)()
            except Exception:
                pass
        reason = self.env['hr.leave.cover.reason'].search([], limit=1)
        cover = self.env['hr.leave.cover'].create_cover(
            reason.id, ltype.id, day, fr_date_pm=(part == 'pm'), to_date_am=(part == 'am'), employee_id=emp.id)
        if state in ('waiting_fhr', 'done'):
            cover.action_approve()
        if state == 'done':
            cover.action_validate()
        return cover

    def _create_request(self, vals):
        """Create the request in draft, then move it to its state with write(): that is what the screens do, and the
        write is what recomputes the compute times and the status of the attendance."""
        state = vals.pop('state', 'draft')
        if state == 'draft':
            return self.Req.with_context(set_draft=True).create(dict(vals, state='draft'))
        req = self.Req.create(dict(vals, state='draft'))      # as on screen: created in draft, submitted at once, so all checks run
        if req.state != state:
            req.write({'state': state})
        return req

    def new_ot(self, at, sub, req_in, req_out, state='done', **extra):
        vals = {'at_id': at.id, 'request_type': 'over_time', 'sub_request_type_id': self.ot_type[sub].id, 'name': 'ot',
                'request_in': vn(at.at_date, *req_in) if req_in else False, 'request_out': vn(at.at_date, *req_out),
                'state': state}
        vals.update(extra)
        # An OT Holidays Plan line makes the system create the OT request of that day itself: complete that one
        existing = at.at_request_ids.filtered(lambda r: r.request_type == 'over_time')
        if len(existing) == 1:
            state = vals.pop('state', 'draft')
            vals.pop('at_id'), vals.pop('request_type')
            existing.write(vals)
            if existing.state != state:
                existing.write({'state': state})
            return existing
        return self._create_request(vals)

    def new_wt(self, at, sub, req_in, req_out, state='done', **extra):
        vals = {'at_id': at.id, 'request_type': 'working_time', 'sub_request_type_id': self.ot_type[sub].id, 'name': 'zz wt',
                'request_in': vn(at.at_date, *req_in) if req_in else False,
                'request_out': vn(at.at_date, *req_out) if req_out else False, 'state': state}
        vals.update(extra)
        return self._create_request(vals)

    def new_sub_leave(self, emp, day, worked_at, part='full', state='done'):
        """Substitute leave on `day` for a holiday that the staff worked (`worked_at`). part: full | am | pm."""
        ltype = self.env['hr.leave.type'].search([('category', '=', 'sub_holiday')], limit=1)
        reason = self.env['hr.leave.cover.reason'].search([], limit=1)
        pm, am = part == 'pm', part == 'am'
        holiday = {
            'name': 'zz sub', 'holiday_status_id': ltype.id, 'employee_id': emp.id,
            'request_date_from': day, 'date_from': datetime.datetime.combine(day, datetime.time.min),
            'request_date_to': day, 'date_to': datetime.datetime.combine(day, datetime.time.max),
            'request_date_from_pm': pm, 'request_date_to_am': am,
            'substitute_for_at_id': worked_at.id, 'substitute_for_date': worked_at.at_date,
            'substitute_period': 'pm' if pm else ('am' if am else False),
        }
        cover = self.env['hr.leave.cover'].with_context(run_holiday_onchange=True).create(
            {'reason_id': reason.id, 'name': 'zz sub', 'employee_id': emp.id, 'leave_request_ids': [(0, False, holiday)]})
        if state in ('waiting_fhr', 'done'):
            cover.action_approve()
        if state == 'done':
            cover.action_validate()
        return cover

    def new_ot_plan(self, emp, day, state='done'):
        """OT Holidays Plan line (OT on a holiday must be registered in advance), ticked for OT and approved."""
        at_month = day.month + 1 if day.day >= 21 else day.month
        at_year = day.year + 1 if at_month == 13 else day.year
        at_month = 1 if at_month == 13 else at_month
        plan = self.env['hr.attendance.ot.holiday'].search([('employee_id', '=', emp.id), ('at_year', '=', str(at_year)), ('at_month', '=', at_month)])
        if not plan:
            plan = self.env['hr.attendance.ot.holiday'].create({'employee_id': emp.id, 'at_year': str(at_year), 'at_month': at_month})
        return self.env['hr.attendance.ot.holiday.line'].create(
            {'ot_holiday_reg_id': plan.id, 'at_date': day, 'ot_register': True, 'state': state})

    def make_holiday(self, day, **line_vals):
        """Public-holiday line on `day` for the default calendar (the test is rolled back)."""
        year = self.env['hr.holidays.public'].search([('year', '=', day.year), ('country_id', '=', False)], limit=1)
        if not year:
            year = self.env['hr.holidays.public'].create({'year': day.year})
        vals = {'year_id': year.id, 'name': 'ZZ test holiday', 'date': day}
        vals.update(line_vals)
        return self.env['hr.holidays.public.line'].create(vals)

    # ---- readers ---------------------------------------------------------------------------------------------------
    def codes(self, at):
        return sorted(at.status_ids.mapped('code'))

    def ot(self, at, estimate=False):
        """OT hours of the attendance as _compute_ot_hour returns them (only non-zero values), after a fresh read."""
        at.invalidate_recordset()
        return {k: v for k, v in at._compute_ot_hour(estimate=estimate).items() if v}

    def assertOT(self, at, expected, estimate=False, am_pm=True):
        """am_pm=False: ot_am / ot_pm are ignored (on holidays the code puts everything in ot_am; the rules do not say)."""
        got = self.ot(at, estimate=estimate)
        if not am_pm:
            got = {k: v for k, v in got.items() if k not in ('ot_am', 'ot_pm')}
        self.assertEqual(got, expected, 'OT hours of %s: expected %s, got %s' % (at.code, expected, got))
