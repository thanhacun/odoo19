# -*- coding: utf-8 -*-
"""Staff locations sent to the remote server directly (no n8n): every remote call is faked, nothing leaves this database."""
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

CLIENT = 'odoo.addons.kderp_remote_integration.models.remote_client.KderpRemoteClient'
TODAY = '2026-11-06'


class FakeRemote(object):
    """The remote's staff, locations and location lines. Records the creates; `fail_for` = employee ids whose create fails."""

    def __init__(self, fail_for=()):
        self.fail_for = set(fail_for)
        self.created, self.calls = [], []
        self.employees = [dict(id=1, code='S1', working=True), dict(id=2, code='S2', working=True), dict(id=3, code='S3', working=True),
                          dict(id=4, code='S4', working=False), dict(id=44, code='S4', working=True)]     # S4 exists twice: the working one wins
        self.locations = [dict(id=10, name='Hai Phong'), dict(id=11, name='HO'), dict(id=12, name='Head Office'), dict(id=13, name='TLIP 1')]
        self.lines = [
            dict(employee_id=[1, 'S1'], location_id=[10, 'Hai Phong'], date='2026-10-01'),     # S1 is at Hai Phong
            dict(employee_id=[2, 'S2'], location_id=[11, 'HO'], date='2025-01-01'),            # S2 is at HO
            dict(employee_id=[3, 'S3'], location_id=[13, 'TLIP 1'], date=TODAY),               # S3 already has a line dated today
        ]

    def __call__(self, model, method, args=None, kwargs=None, **kw):
        args, kwargs = args or [], kwargs or {}
        self.calls.append((model, method))
        if model == 'hr.employee' and method == 'search_read':
            codes = args[0][0][2]
            assert kwargs.get('context', {}).get('active_test') is False, 'inactive staff must be included'
            return [dict(e) for e in self.employees if e['code'] in codes]
        if model == 'kderp.employee.location.code' and method == 'search_read':
            return [dict(l) for l in self.locations]
        if model == 'kderp.hr.employee.location' and method == 'search_read':
            ids, upto = args[0][0][2], args[0][1][2]
            return [dict(l) for l in self.lines if l['employee_id'][0] in ids and l['date'] <= upto]
        if model == 'kderp.hr.employee.location' and method == 'create':
            if args[0]['employee_id'] in self.fail_for:
                raise UserError('Unique (date, employee) violated')
            self.created.append(args[0])
            return 500 + len(self.created)
        raise AssertionError('unexpected remote call %s.%s' % (model, method))


def staff(code, location='Somewhere', remote='', name=None):
    return {'code': code, 'name': name or code, 'location': location, 'remote_location': remote, 'since': '2026-01-01', 'remote_code': ''}


class TestStaffLocationPush(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Loc = self.env['kderp.hr.employee.location']
        self.icp = self.env['ir.config_parameter'].sudo()
        self.icp.set_param('kderp_remote.live.staff_location', 'False')
        patcher = mock.patch.object(type(self.Loc), '_vietnam_today', return_value=TODAY)     # fixed date: the fake data is dated
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, remote, fn):
        with mock.patch(CLIENT + '.execute', side_effect=lambda model, method, args=None, kwargs=None, **kw: remote(model, method, args, kwargs, **kw)):
            return fn()

    def _payload(self, rows):
        return {'staff': rows}

    def _push(self, remote, rows):
        with mock.patch.object(type(self.Loc), '_prepare_remote_payload', return_value=self._payload(rows)):
            return self._run(remote, self.Loc.action_push_to_remote)

    # ------------------------------------------------------------------ the plan (the rules of the old n8n workflow)
    def test_plan_covers_every_case(self):
        rows = [staff('S1', 'Bambi', 'TLIP 1'),            # at Hai Phong -> TLIP 1: update
                staff('S2', 'Head', 'Head Office'),        # at HO, chosen "Head Office": same place, unchanged
                staff('S3', 'Nippo', 'Hai Phong'),         # has a different line dated today: left alone
                staff('S4', 'Dai', 'Hai Phong'),           # no line yet (two employees with that code: the working one)
                staff('S5', 'Lost', 'Hai Phong'),          # code not on the remote
                staff('S6', 'Unmapped', ''),               # HR chose nothing
                staff('S7', 'Odd', 'Nowhere'),             # chosen name no longer on the remote
                staff('', 'No code', 'Hai Phong')]         # no code
        plan = self._run(FakeRemote(), lambda: self.Loc._plan_remote_push(rows, today=TODAY))
        s = plan['summary']
        self.assertEqual((s['received'], s['to_update'], s['unchanged'], s['no_location']), (8, 2, 1, 1))
        self.assertEqual(s['conflicts_today'], ['S3'])
        self.assertEqual(s['unknown_staff'], ['S5'])
        self.assertEqual(s['unmapped'], {'Unmapped': 1})
        self.assertEqual(s['target_missing'], ['Nowhere'])
        by_code = {l['code']: l for l in plan['lines']}
        self.assertEqual(sorted(by_code), ['S1', 'S4'])
        self.assertEqual((by_code['S1']['employee_id'], by_code['S1']['location_id'], by_code['S1']['date']), (1, 13, TODAY))
        self.assertEqual((by_code['S1']['from'], by_code['S1']['to']), ('Hai Phong', 'TLIP 1'))
        self.assertEqual((by_code['S4']['employee_id'], by_code['S4']['from']), (44, ''))        # the working S4

    def test_same_location_name_in_other_case_is_unchanged(self):
        plan = self._run(FakeRemote(), lambda: self.Loc._plan_remote_push([staff('S1', 'Bambi', ' hai phong ')], today=TODAY))
        self.assertEqual((plan['summary']['unchanged'], plan['summary']['to_update']), (1, 0))

    def test_planning_reads_only(self):
        remote = FakeRemote()
        self._run(remote, lambda: self.Loc._plan_remote_push([staff('S1', 'Bambi', 'TLIP 1')], today=TODAY))
        self.assertNotIn(('kderp.hr.employee.location', 'create'), remote.calls)

    # ------------------------------------------------------------------ dry run is the default
    def test_dry_run_writes_nothing_and_previews(self):
        remote = FakeRemote()
        count, result = self._push(remote, [staff('S1', 'Bambi', 'TLIP 1')])
        self.assertEqual((count, result['status'], result['created'], result['to_update']), (1, 'dry_run', 0, 1))
        self.assertEqual(result['preview'][0]['code'], 'S1')
        self.assertFalse(remote.created)
        title, rows = self.Loc._format_push_result(count, result)
        self.assertIn('DRY RUN', title)
        self.assertNotIn('n8n', ' '.join(rows))

    def test_the_advance_switch_does_not_make_staff_locations_live(self):
        self.icp.set_param('kderp_remote.live.advance', 'True')
        remote = FakeRemote()
        _count, result = self._push(remote, [staff('S1', 'Bambi', 'TLIP 1')])
        self.assertEqual(result['status'], 'dry_run')
        self.assertFalse(remote.created)

    # ------------------------------------------------------------------ live
    def test_live_creates_one_line_dated_today_and_a_second_run_changes_nothing(self):
        self.icp.set_param('kderp_remote.live.staff_location', 'True')
        remote = FakeRemote()
        rows = [staff('S1', 'Bambi', 'TLIP 1'), staff('S2', 'Head', 'Head Office')]
        _count, result = self._push(remote, rows)
        self.assertEqual((result['status'], result['created'], result['failed']), ('ok', 1, []))
        self.assertEqual(remote.created, [{'employee_id': 1, 'date': TODAY, 'location_id': 13}])
        remote.lines.append(dict(employee_id=[1, 'S1'], location_id=[13, 'TLIP 1'], date=TODAY))     # what the first run wrote
        _count, again = self._push(remote, rows)
        self.assertEqual((again['created'], again['to_update'], again['unchanged']), (0, 0, 2))

    def test_live_one_failure_does_not_stop_the_others(self):
        self.icp.set_param('kderp_remote.live.staff_location', 'True')
        remote = FakeRemote(fail_for=[1])
        _count, result = self._push(remote, [staff('S1', 'Bambi', 'TLIP 1'), staff('S4', 'Dai', 'Hai Phong')])
        self.assertEqual((result['status'], result['created']), ('partial', 1))
        self.assertEqual([f['code'] for f in result['failed']], ['S1'])
        self.assertIn('Unique', result['failed'][0]['error'])
        title, rows = self.Loc._format_push_result(2, result)
        self.assertIn('Failed', ' '.join(rows))

    # ------------------------------------------------------------------ the remote location list (wizard step 2)
    def test_remote_location_names_are_read_and_kept(self):
        Remote = self.env['kderp.staff.location.remote']
        n = self._run(FakeRemote(), Remote.refresh_from_remote)
        self.assertEqual(n, 4)
        active = lambda: set(Remote.search([]).mapped('name'))          # (the table may already hold names from a real database)
        self.assertEqual(active(), {'HO', 'Hai Phong', 'Head Office', 'TLIP 1'})
        remote = FakeRemote()
        remote.locations = [dict(id=10, name='Hai Phong'), dict(id=14, name='New site')]
        self._run(remote, Remote.refresh_from_remote)
        self.assertEqual(active(), {'Hai Phong', 'New site'})            # the others are no longer offered ...
        gone = set(Remote.with_context(active_test=False).search([('active', '=', False)]).mapped('name'))
        self.assertTrue({'HO', 'Head Office', 'TLIP 1'} <= gone)         # ... but kept (a mapping may point to them)

    def test_empty_remote_location_list_is_an_error(self):
        remote = FakeRemote()
        remote.locations = []
        with self.assertRaises(UserError):
            self._run(remote, self.env['kderp.staff.location.remote'].refresh_from_remote)
