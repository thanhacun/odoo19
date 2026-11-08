"""The import with a small fake Odoo 12 snapshot (no database `legacy12` needed)."""
from copy import deepcopy
from unittest import mock

from odoo.tests.common import TransactionCase

D = '2026-01-05'

FIXTURE = {
    'hr_department_type': [{'id': 1, 'name': 'Department', 'code': 'department', 'description': None},
                           {'id': 2, 'name': 'Section', 'code': 'section', 'description': None}],
    'kderp_employee_location_code': [{'id': 1, 'name': 'HO'}, {'id': 2, 'name': 'Site X'}],
    'hr_department': [
        {'id': 12, 'name': 'HO', 'code': 'CA00', 'active': True, 'type_id': 1, 'parent_id': None, 'manager_2nd_id': None, 'new_manager': None, 'new_man_effective_date': None},
        {'id': 13, 'name': 'ADM-HO', 'code': 'CA00-03', 'active': True, 'type_id': 2, 'parent_id': 12, 'manager_2nd_id': 21, 'new_manager': None, 'new_man_effective_date': None},
    ],
    'res_users': [{'id': 2, 'login': 'admin', 'active': True, 'partner_id': 100},
                  {'id': 10, 'login': 'imp_boss', 'active': True, 'partner_id': 101},
                  {'id': 11, 'login': 'imp_staff', 'active': True, 'partner_id': 102},
                  {'id': 12, 'login': 'imp_leaver', 'active': False, 'partner_id': 103}],
    'res_partner': [{'id': 100, 'name': 'Administrator', 'email': None}, {'id': 101, 'name': 'Boss One', 'email': 'boss@x.test'},
                    {'id': 102, 'name': 'Staff One', 'email': 'staff@x.test'}, {'id': 103, 'name': 'Leaver One', 'email': None}],
    'ir_model_data': [{'module': 'kderp_hr', 'name': 'group_kderp_hr_user_input', 'model': 'res.groups', 'res_id': 501},
                      {'module': 'base', 'name': 'group_system', 'model': 'res.groups', 'res_id': 502},
                      {'module': 'kderp_asset_management', 'name': 'group_not_ported_yet', 'model': 'res.groups', 'res_id': 503}],
    'res_groups_users_rel': [{'gid': 501, 'uid': 11}, {'gid': 502, 'uid': 11}, {'gid': 503, 'uid': 10}],
    'hr_employee': [
        {'id': 20, 'code': 'IB001', 'name': 'Boss One', 'working': True, 'active': True, 'user_id': 10, 'parent_id': None, 'admin_manager_id': None, 'coach_id': None,
         'department_id': 12, 'admin_dept_id': 12, 'working_area_id': None, 'gender': 'male', 'marital': 'married', 'work_email': 'boss@x.test',
         'birthday': '1980-02-03', 'stop_working_date': None, 'job_title': 'Manager', 'children': 2},
        {'id': 21, 'code': 'IA001', 'name': 'Staff One', 'working': True, 'active': True, 'user_id': 11, 'parent_id': 20, 'admin_manager_id': 20, 'coach_id': None,
         'department_id': 13, 'admin_dept_id': 13, 'working_area_id': None, 'gender': 'weird', 'marital': 'single', 'work_email': 'staff@x.test',
         'birthday': None, 'stop_working_date': None, 'job_title': None, 'children': 0},
        {'id': 22, 'code': 'IL001', 'name': 'Leaver One', 'working': False, 'active': True, 'user_id': 12, 'parent_id': 20, 'admin_manager_id': 20, 'coach_id': None,
         'department_id': 13, 'admin_dept_id': 13, 'working_area_id': None, 'gender': 'female', 'marital': None, 'work_email': None,
         'birthday': None, 'stop_working_date': '2025-12-31', 'job_title': None, 'children': 0},
    ],
    'kderp_hr_employee_location': [{'id': 1, 'employee_id': 21, 'location_id': 1, 'date': '2025-01-01'},
                                   {'id': 2, 'employee_id': 21, 'location_id': 2, 'date': '2025-06-01'}],
    'hr_employee_department_history': [{'id': 1, 'employee_id': 21, 'department_id': 13, 'effective_date': '2024-01-01', 'admin_dept_id': 13, 'admin_effv_date': '2024-01-01'}],
    'hr_manager_history': [{'id': 1, 'department_id': 13, 'manager_id': 20, 'effective_date': '2024-01-01'}],
    'hr_employee_project_history': [{'id': 1, 'employee_id': 21, 'project_name': 'Tower', 'project_description': None, 'effective_date': '2025-03-01'}],
}


class TestLegacyImport(TransactionCase):

    def setUp(self):
        super().setUp()
        self.data = deepcopy(FIXTURE)
        data = self.data

        def fake(model, table, columns, where=None):
            if columns is None:
                return [dict(row) for row in data.get(table, [])]
            return [dict({c: None for c in columns}, **{k: v for k, v in row.items() if k in columns}) for row in data.get(table, [])]
        patcher = mock.patch.object(type(self.env['kdvn.legacy.import']), '_legacy_rows', fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.imp = self.env['kdvn.legacy.import']

    def _emp(self, code):
        return self.env['hr.employee'].with_context(active_test=False).search([('code', '=', code)])

    def test_full_run(self):
        out = self.imp.run()
        self.assertEqual(out['errors'], [], out['log'])
        staff, boss = self._emp('IA001'), self._emp('IB001')
        self.assertEqual(len(staff), 1)
        self.assertEqual(staff.name, 'Staff One')
        self.assertTrue(staff.working)
        self.assertFalse(staff.sex, 'a value Odoo 19 does not know is dropped, not an error')
        self.assertEqual(boss.sex, 'male')
        self.assertEqual(boss.children, 2)
        self.assertEqual(staff.parent_id, boss)
        self.assertEqual(staff.admin_manager_id, boss)
        self.assertEqual(staff.department_id.code, 'CA00-03')
        self.assertEqual(staff.department_id.parent_id.code, 'CA00')
        self.assertEqual(staff.department_id.type_id.code, 'section')
        self.assertEqual(staff.department_id.manager_2nd_id, staff)
        self.assertEqual(staff.user_id.login, 'imp_staff')
        self.assertEqual(staff.user_id.partner_id.email, 'staff@x.test')
        self.assertEqual(self._emp('IL001').stop_working_date.isoformat(), '2025-12-31')
        self.assertFalse(self._emp('IL001').user_id.active)

    def test_histories_and_chains(self):
        self.imp.run()
        staff, boss = self._emp('IA001'), self._emp('IB001')
        self.assertEqual(len(staff.location_ids), 2)
        self.assertEqual(staff.current_location_id.name, 'Site X')
        self.assertEqual(len(staff.department_history_ids), 1)
        self.assertEqual(staff.department_id.manager_id, boss, 'manager follows the imported manager history')
        self.assertEqual(staff.project_history_ids.project_name, 'Tower')
        self.assertEqual(staff.parent_user_ids, boss.user_id)
        self.assertEqual(staff.parent_users_dsp, 'Boss One')

    def test_second_run_updates_and_never_duplicates(self):
        first = self.imp.run()
        count = lambda m: self.env[m].with_context(active_test=False).search_count([])   # noqa: E731
        before = {m: count(m) for m in ('hr.employee', 'res.users', 'hr.department', 'kderp.hr.employee.location',
                                         'hr.employee.department.history', 'hr.manager.history')}
        self.data['hr_employee'][1]['job_title'] = 'Senior'
        second = self.imp.run()
        self.assertEqual(before, {m: count(m) for m in before})
        self.assertEqual(self._emp('IA001').job_title, 'Senior')
        self.assertEqual(second['errors'], [], second['log'])
        self.assertFalse([k for k, v in second['stats'].items() if k[1] in ('created', 'adopted') and v], second['log'])
        self.assertTrue(any(k[1] == 'created' for k in first['stats']))

    def test_filter_by_code_brings_the_managers(self):
        out = self.imp.run(employee_codes=['ia001'])
        self.assertTrue(self._emp('IA001'))
        self.assertTrue(self._emp('IB001'), 'the manager is needed for the chain')
        self.assertFalse(self._emp('IL001'))
        self.assertEqual(out['stats'][('hr_employee', 'asked')], 1)
        self.assertEqual(out['stats'][('hr_employee', 'selected')], 2)

    def test_working_only_skips_leavers(self):
        self.imp.run(working_only=True)
        self.assertTrue(self._emp('IA001'))
        self.assertFalse(self._emp('IL001'))

    def test_dry_run_changes_nothing(self):
        out = self.imp.run(dry_run=True)
        self.assertIn('DRY RUN', out['log'])
        self.assertFalse(self._emp('IA001'))
        self.assertFalse(self.env['hr.department'].search([('code', '=', 'CA00-03')]))
        self.assertFalse(self.env['ir.model.data'].search([('module', '=', 'legacy12')]))

    def test_existing_records_are_adopted(self):
        old = self.env['hr.employee'].create({'name': 'Old record', 'code': 'IA001', 'working': True})
        self.imp.run()
        self.assertEqual(self._emp('IA001'), old)
        self.assertEqual(old.name, 'Staff One')
        self.assertEqual(self.env['ir.model.data'].search_count([('module', '=', 'legacy12'), ('model', '=', 'hr.employee'), ('res_id', '=', old.id)]), 1)

    def test_a_bad_row_is_listed_and_the_rest_goes_on(self):
        self.data['hr_employee'][2]['name'] = None   # no name: Odoo 19 refuses it
        out = self.imp.run()
        self.assertEqual(len(out['errors']), 1, out['log'])
        self.assertIn('IL001', out['errors'][0])
        self.assertFalse(self._emp('IL001'))
        self.assertTrue(self._emp('IA001'))

    def test_leaver_without_stop_date_is_copied_as_it_is(self):
        self.data['hr_employee'][2]['stop_working_date'] = None
        out = self.imp.run()
        self.assertEqual(out['errors'], [], out['log'])
        self.assertTrue(self._emp('IL001'))

    def test_groups_are_mapped_by_renamed_external_id(self):
        out = self.imp.run()
        user = self.env['res.users'].search([('login', '=', 'imp_staff')])
        self.assertIn(self.env.ref('kdvn_hr.group_kderp_hr_user_input'), user.group_ids)
        self.assertFalse(user.has_group('base.group_system'), 'base groups are never copied')
        self.assertEqual(out['stats'][('legacy group not mapped', 'kderp_asset_management.group_not_ported_yet')], 1)

    def test_password_option(self):
        self.imp.run(password='dev-pass-1')
        user = self.env['res.users'].search([('login', '=', 'imp_staff')])
        self.env.cr.execute('SELECT password FROM res_users WHERE id = %s', (user.id,))
        stored = self.env.cr.fetchone()[0]
        self.assertTrue(stored and stored != 'dev-pass-1', 'a hashed password is stored')

    def test_admin_is_never_rewritten(self):
        admin = self.env.ref('base.user_admin')
        login, name = admin.login, admin.name
        self.data['hr_employee'].append(dict(FIXTURE['hr_employee'][0], id=23, code='S0000', name='Administrator', user_id=2, parent_id=None, admin_manager_id=None))
        self.imp.run()
        self.assertEqual((admin.login, admin.name), (login, name))

    def test_wizard_runs(self):
        wiz = self.env['kdvn.legacy.import.wizard'].create({'employee_codes': 'IA001, IB001', 'dry_run': False, 'working_only': True})
        wiz.action_run()
        self.assertIn('Import done', wiz.result)
        self.assertTrue(self._emp('IA001'))
