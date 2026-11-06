# -*- coding: utf-8 -*-
"""Runs the case sheets in tests/cases/*.csv: one CSV row = one test, readable by HR (open the CSV in Excel).

Columns (see cases/README.md):
  id, rule, basis, title, profile, day, check_in, check_out, leave, request, expect_status, expect_status_worked_day, expect_ot, expect_error, known_gap

Every row becomes its own test method named after the case id, so the run lists each case with PASS / FAIL and a
message in plain words: what the case was, what was expected and what the system produced.
"""
import csv
import datetime
import os
import unittest

from odoo.exceptions import ValidationError
from .common_at import ATCase, WED, SUN, MON_PH, MON_CD, vn

CASES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cases')

# day name -> (date, how the test prepares it)
SAT_NORMAL = datetime.date(2026, 2, 28)    # working Saturday, NOT one of the last 2 of the attendance month
SAT_LAST = datetime.date(2026, 3, 14)      # one of the last 2 working Saturdays of the month 21 Feb - 20 Mar
DAYS = {
    'weekday': WED, 'sunday': SUN, 'public_holiday': MON_PH, 'company_day': MON_CD,
    'saturday': SAT_NORMAL, 'last_saturday': SAT_LAST,
}
OT_KEYS = ['wd_ot', 'wd_st', 'hd_ot', 'hd_st', 'ph_ot', 'ph_st']
PROFILES = {
    'normal': {},
    'child_care': {'child_care_period': True},
    'no_need_check': {'no_need_check': True},
    'early_45': {'early_offset': 45},
    'no_morning_ot': {'allow_morning_ot': False},
    'no_ot': {'force_apply': True, 'wd_allowed_ot': 0, 'hd_allowed_ot': 0},   # rule without OT allowance
    'g8': {},                                                                 # employee tagged G8 (no OT, compensated by leave)
}


def hm(text):
    h, m = text.strip().split(':')
    return int(h), int(m)


def read_cases(filename):
    with open(os.path.join(CASES_DIR, filename), newline='', encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if (r.get('id') or '').strip() and not r['id'].startswith('#')]
    return rows


class CaseMixin(object):
    """Turns one CSV row into fixtures, runs it and compares with the expectation."""

    def run_case(self, row):
        profile = (row.get('profile') or 'normal').strip()
        self.assertIn(profile, PROFILES, 'unknown profile %r' % profile)
        day_name = (row.get('day') or 'weekday').strip()
        self.assertIn(day_name, DAYS, 'unknown day %r' % day_name)
        day = DAYS[day_name]
        emp = self.new_employee()
        self.new_rule(emp, **PROFILES[profile])
        if profile == 'g8':
            cat = self.env['hr.employee.category'].search([('name', '=', 'G8')], limit=1) or \
                self.env['hr.employee.category'].create({'name': 'G8'})
            emp.category_ids = [(4, cat.id)]
        if day_name == 'public_holiday':
            self.make_holiday(day)
        if day_name == 'company_day':
            self.make_holiday(day, is_company_day=True)
        request_text = (row.get('request') or '')
        if day_name in ('sunday', 'public_holiday', 'company_day', 'last_saturday') and 'over' not in request_text and \
                request_text.split()[:1] in (['am'], ['pm'], ['both']) and 'no_plan' not in request_text:
            self.new_ot_plan(emp, day)      # OT on a holiday must be registered in the OT Holidays Plan first
        check_in = hm(row['check_in']) if (row.get('check_in') or '').strip() else None
        check_out = hm(row['check_out']) if (row.get('check_out') or '').strip() else None
        expect_error = (row.get('expect_error') or '').strip()
        try:
            worked_day_at = self.apply_leave(emp, day, (row.get('leave') or '').strip())
            at = self.new_at(emp, day, check_in, check_out)
            self.apply_requests(at, (row.get('request') or '').strip())
            at._compute_at_status(force_run=True)
        except ValidationError as e:
            if not expect_error:
                raise
            self.assertIn(expect_error.lower(), str(e).lower(), 'Expected the message "%s" but got "%s"' % (expect_error, e))
            return
        if expect_error:
            self.fail('Expected the system to refuse with "%s", but it accepted the request.' % expect_error)
        self.check_status(at, (row.get('expect_status') or '').strip())
        if (row.get('expect_status_worked_day') or '').strip():
            worked_day_at._compute_at_status(force_run=True)
            self.check_status(worked_day_at, row['expect_status_worked_day'].strip(), what='worked holiday')
        self.check_ot(at, (row.get('expect_ot') or '').strip(), estimate='estimate' in (row.get('request') or ''))

    def apply_leave(self, emp, day, text):
        """leave cell: `full done`, `am waiting_fman`, `pm done` (part, then state; default state done).
        Substitute leave for a holiday the staff worked: `sub full done worked=sunday 08:00-17:00`."""
        if not text:
            return None
        words = text.split()
        if words[0] == 'sub':
            part, state = words[1], words[2]
            worked_day = DAYS[words[3].split('=')[1]]
            span = words[4].split('-')
            worked = self.new_at(emp, worked_day, hm(span[0]), hm(span[1]))
            self.new_sub_leave(emp, day, worked, part=part, state=state)
            return worked
        self.new_leave(emp, day, part=words[0], state=words[1] if len(words) > 1 else 'done')
        return None

    def apply_requests(self, at, text):
        """request cell: several requests separated by `|`. Each one: `<type> <from>-<to> [state] [out_by_reg] [estimate]`.
        Types: am pm both (overtime), or a working-time type: biz_trip meet_out work_out forget_in forget_out wfh early_in others.
        From or to may be empty (`forget_out -17:00`). States: draft waiting_fman waiting_fhr done refuse (default done).
        `no_plan` = do NOT create the OT Holidays Plan line that holiday OT needs. `estimate` = compare the estimated OT (what the staff sees before approval) instead of the final OT."""
        if not text:
            return
        for item in text.split('|'):
            words = item.split()
            sub, span = words[0], words[1]
            req_in, req_out = span.split('-')
            state = next((w for w in words[2:] if w in ('draft', 'waiting_fman', 'waiting_fhr', 'done', 'refuse')), 'done')
            extra = {'out_by_reg': True} if 'out_by_reg' in words else {}
            if sub in ('am', 'pm', 'both'):
                self.new_ot(at, sub, hm(req_in) if req_in else None, hm(req_out), state=state, **extra)
            else:
                self.new_wt(at, sub, hm(req_in) if req_in else None, hm(req_out) if req_out else None, state=state)

    def check_status(self, at, expected, what='day'):
        if not expected:
            return
        parts = [p.strip() for p in expected.split(';')]
        marks = sorted(m.strip() for m in parts[0].split('+')) if parts[0] else []
        flags = set(p for p in parts[1:] if p)
        got_flags = set(f for f in ('late_in', 'early_out') if at[f])
        self.assertEqual(self.codes(at), marks, 'Status marks of the %s: expected %s, system gave %s' % (what, ' + '.join(marks) or 'none', ' + '.join(self.codes(at)) or 'none'))
        self.assertEqual(got_flags, flags, 'Flags of the %s: expected %s, system gave %s' % (what, sorted(flags) or 'none', sorted(got_flags) or 'none'))

    def check_ot(self, at, expected, estimate=False):
        if expected == '':
            return          # no OT expectation for this case
        want = {k: 0.0 for k in OT_KEYS}
        for token in expected.split():
            if token == 'none':
                continue
            key, value = token.split('=')
            self.assertIn(key, OT_KEYS, 'unknown OT key %r' % key)
            want[key] = float(value)
        got = self.ot(at, estimate=estimate)
        got = {k: float(got.get(k, 0)) for k in OT_KEYS}
        show = lambda d: ' '.join('%s=%g' % (k, v) for k, v in d.items() if v) or 'none'
        self.assertEqual(got, want, 'OT hours: expected %s, system gave %s' % (show(want), show(got)))


def build_class(name, filename, tags):
    """Create a TestCase class with one test method per CSV row."""
    from odoo.tests import tagged
    attrs = {}
    for row in read_cases(filename):
        def make(r):
            def test(self):
                gap = (r.get('known_gap') or '').strip()
                if not gap:
                    return self.run_case(r)
                # a known gap: the sheet records what the code does differently from the rule; the case stays visible
                try:
                    self.run_case(r)
                except AssertionError:
                    raise unittest.SkipTest('KNOWN GAP - ' + gap)
                self.fail('The known gap seems fixed: remove the known_gap text of this case in the sheet.')
            test.__doc__ = '%s  %s' % (r['id'], r['title'])
            return test
        attrs['test_' + row['id'].replace('-', '_').lower()] = make(row)
    cls = type(name, (CaseMixin, ATCase), attrs)
    return tagged(*tags)(cls)


# ---------------------------------------------------------------------------------------------------------------------------
# AH sheet: one attendance month with 4 working Saturdays (27 Jun, 4, 11, 18 Jul 2026; AT month Jul = 21 Jun - 20 Jul).
# The last two (11 and 18 Jul) are the "OT holidays". The staff has an AH allocation of 2 days for the month.
# Saturday plans: w = worked 08:00-17:00, x = absent (no check), am = only 08:00-12:00, pm = only 13:00-17:00.
# ---------------------------------------------------------------------------------------------------------------------------
AH_SATS = [datetime.date(2026, 6, 27), datetime.date(2026, 7, 4), datetime.date(2026, 7, 11), datetime.date(2026, 7, 18)]
SAT_PLANS = {'w': ((8, 0), (17, 0)), 'x': (None, None), 'am': ((8, 0), (12, 0)), 'pm': ((13, 0), (17, 0))}


class AHCaseMixin(object):

    def run_ah_case(self, row):
        emp = self.new_employee()
        self.new_rule(emp)
        if (row.get('allocation') or 'yes').strip() == 'yes':
            ltype = self.env['hr.leave.type'].search([('name', '=', 'AH for Jul. 2026')], limit=1)
            alloc = self.env['hr.leave.allocation'].create({'name': 'zz ah', 'holiday_status_id': ltype.id, 'employee_id': emp.id, 'number_of_days': 2})
            for step in ('action_confirm', 'action_approve', 'action_validate'):
                try:
                    getattr(alloc, step)()
                except Exception:
                    pass
        plans = [p.strip() for p in row['saturdays'].split(',')]
        ats = [self.new_at(emp, d, *SAT_PLANS[p]) for d, p in zip(AH_SATS, plans)]
        for _round in (1, 2):                       # the nightly job meets each Saturday in date order, the 2nd round settles it
            for at in ats:
                at._compute_at_status(force_run=True)
        got = ['+'.join(self.codes(at)) for at in ats]
        want = [w.strip() for w in row['expect_marks'].split('|')]
        label = lambda marks: ' | '.join('Sat %d: %s' % (i + 1, m or '-') for i, m in enumerate(marks))
        self.assertEqual(got, want, 'Marks per Saturday: expected [%s], system gave [%s]' % (label(want), label(got)))


def build_ah_class(name, filename, tags):
    from odoo.tests import tagged
    attrs = {}
    for row in read_cases(filename):
        def make(r):
            def test(self):
                gap = (r.get('known_gap') or '').strip()
                if not gap:
                    return self.run_ah_case(r)
                try:
                    self.run_ah_case(r)
                except AssertionError:
                    raise unittest.SkipTest('KNOWN GAP - ' + gap)
                self.fail('The known gap seems fixed: remove the known_gap text of this case in the sheet.')
            test.__doc__ = '%s  %s' % (r['id'], r['title'])
            return test
        attrs['test_' + row['id'].replace('-', '_').lower()] = make(row)
    return tagged(*tags)(type(name, (AHCaseMixin, ATCase), attrs))
