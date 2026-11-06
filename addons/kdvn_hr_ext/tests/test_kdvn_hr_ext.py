from datetime import date, timedelta

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestKdvnHrExt(TransactionCase):

    def setUp(self):
        super().setUp()
        Emp = self.env['hr.employee']
        self.today = date.today()
        self.boss = Emp.create({'name': 'Boss', 'code': 'E001', 'working': True})
        self.lead = Emp.create({'name': 'Lead', 'code': 'E002', 'working': True})
        self.staff = Emp.create({'name': 'Staff', 'code': 'E003', 'working': True})
        Dept = self.env['hr.department']
        self.top = Dept.create({'name': 'Top', 'code': 'AB12'})
        self.sec = Dept.create({'name': 'Section', 'code': 'AB1201', 'parent_id': self.top.id})
        self.admin = Dept.create({'name': 'Admin sec'})
        Hist = self.env['hr.manager.history']
        Hist.create({'department_id': self.top.id, 'manager_id': self.boss.id, 'effective_date': self.today - timedelta(days=100)})
        Hist.create({'department_id': self.sec.id, 'manager_id': self.lead.id, 'effective_date': self.today - timedelta(days=100)})

    def _history(self, employee, dept, admin=None, days=-10):
        d = self.today + timedelta(days=days)
        return self.env['hr.employee.department.history'].create({
            'employee_id': employee.id, 'department_id': dept.id, 'effective_date': d,
            'admin_dept_id': (admin or dept).id, 'admin_effv_date': d})

    def test_manager_follows_history(self):
        self.assertEqual(self.sec.manager_id, self.lead)
        self.env['hr.manager.history'].create({'department_id': self.sec.id, 'manager_id': self.boss.id, 'effective_date': self.today + timedelta(days=3)})
        self.sec.invalidate_recordset()
        self.sec._compute_1st_manager()
        self.assertEqual(self.sec.manager_id, self.lead, 'a future manager is not current')
        self.assertEqual(self.sec.compute_manager_by_date(self.today + timedelta(days=4)), self.boss)
        self.assertEqual(self.sec.compute_manager_by_date(self.today - timedelta(days=500)), self.lead, 'before all history = first manager')

    def test_history_sets_department_and_manager(self):
        self._history(self.staff, self.sec, self.admin)
        self.assertEqual(self.staff.department_id, self.sec)
        self.assertEqual(self.staff.parent_id, self.lead)
        self.assertEqual(self.staff.admin_dept_id, self.admin)

    def test_future_line_not_applied_and_newest_effective_wins(self):
        self._history(self.staff, self.sec, days=-30)
        self._history(self.staff, self.top, days=-5)
        self._history(self.staff, self.admin, days=+20)
        self.assertEqual(self.staff.department_id, self.top)
        self.assertEqual(self.staff.parent_id, self.boss)

    def test_section_manager_reports_to_parent_manager_not_to_self(self):
        self._history(self.lead, self.sec)
        self.assertEqual(self.lead.department_id, self.sec)
        self.assertEqual(self.lead.parent_id, self.boss)

    def test_no_history_keeps_department(self):
        self.staff.department_id = self.sec
        self.staff.compute_current_dept(force_update=True)
        self.assertEqual(self.staff.department_id, self.sec)

    def test_manager_change_refreshes_members(self):
        self._history(self.staff, self.sec)
        self.env['hr.manager.history'].create({'department_id': self.sec.id, 'manager_id': self.boss.id, 'effective_date': self.today})
        self.assertEqual(self.staff.parent_id, self.boss)

    def test_bulk_load_can_defer_the_refresh(self):
        self.staff.department_id = self.top
        self.env['hr.employee.department.history'].with_context(kdvn_defer_org_refresh=True).create({
            'employee_id': self.staff.id, 'department_id': self.sec.id, 'effective_date': self.today,
            'admin_dept_id': self.sec.id, 'admin_effv_date': self.today})
        self.assertEqual(self.staff.department_id, self.top, 'nothing recomputed while deferred')
        self.staff._refresh_organisation()
        self.assertEqual(self.staff.department_id, self.sec)

    def test_deleting_history_keeps_data_consistent(self):
        line = self._history(self.staff, self.sec)
        line.unlink()
        self.assertFalse(self.staff.department_history_ids)

    def test_chain_of_manager_users(self):
        Users = self.env['res.users']
        u_boss = Users.create({'name': 'U Boss', 'login': 'u_boss_x'})
        u_lead = Users.create({'name': 'U Lead', 'login': 'u_lead_x'})
        self.boss.user_id, self.lead.user_id = u_boss, u_lead
        self._history(self.lead, self.sec)      # the lead (section manager) reports to the top manager
        self._history(self.staff, self.sec)
        self.staff._compute_parent_users()
        self.assertEqual(self.staff.parent_user_ids, u_lead | u_boss)
        self.assertEqual(self.staff.parent_users_dsp, 'U Lead >> U Boss')
        self.assertFalse(self.staff.gm_id, 'no GM group installed yet: nobody is a GM')

    def test_chain_survives_a_manager_loop(self):
        self.boss.parent_id = self.lead
        self.lead.parent_id = self.boss
        self.staff.parent_id = self.lead
        self.staff._compute_parent_users()   # must end

    def test_admin_chain(self):
        self.admin.parent_id = self.top
        self._history(self.staff, self.sec, self.admin)
        self.assertEqual(self.staff.admin_manager_id, self.admin.manager_id)
        self.assertEqual(self.staff.compute_dept_by_date(self.today), self.admin)
        self.assertEqual(self.staff.compute_dept_by_date(self.today - timedelta(days=999)), self.admin, 'before history = first line')

    def test_new_manager_becomes_history_line(self):
        self.sec.write({'new_manager': self.boss.id, 'new_man_effective_date': self.today})
        self.sec._change_to_effective_manager()
        self.assertEqual(self.sec.manager_id, self.boss)
        self.assertFalse(self.sec.new_manager)

    def test_second_manager_must_differ(self):
        with self.assertRaises(ValidationError):
            self.sec.manager_2nd_id = self.lead

    def test_working_and_stop_date_rules(self):
        Emp = self.env['hr.employee']
        with self.assertRaises(ValidationError):
            Emp.create({'name': 'Leaver', 'code': 'E010', 'working': False})
        with self.assertRaises(ValidationError):
            Emp.create({'name': 'Odd', 'code': 'E011', 'working': True, 'stop_working_date': self.today})
        Emp.create({'name': 'Leaver ok', 'code': 'E012', 'working': False, 'stop_working_date': self.today})
        Emp.create({'name': 'Director', 'code': 'S9001', 'working': False})   # S9xxx exempt
        Emp.create({'name': 'No code'})                                        # no code: exempt

    def test_area_from_parent_code(self):
        self.assertEqual(self.sec.area_id, self.top)

    def test_project_history_unique(self):
        P = self.env['hr.employee.project.history']
        P.create({'employee_id': self.staff.id, 'project_name': 'P1', 'effective_date': self.today})
        self.assertEqual(len(self.staff.project_history_ids), 1)

    def test_cron_runs(self):
        self._history(self.staff, self.sec, days=0)
        self.env['hr.employee']._cron_sync_organisation()
        self.assertEqual(self.staff.department_id, self.sec)

    def test_org_repair_tree(self):
        fixed, issues = self.env['hr.employee']._org_repair_tree(
            {'A': '', 'B': 'A', 'C': 'C', 'D': 'X', 'E': 'F', 'F': 'E'}, ['A'])
        self.assertEqual([c for c, p in fixed.items() if not p], ['A'], 'exactly one root')
        self.assertIn('C', issues)
        self.assertIn('D', issues)
        self.assertTrue(any(k in issues for k in ('E', 'F')))
        self.assertEqual(self.env['hr.employee']._org_repair_tree({}, []), ({}, {}))

    def test_org_data_rows(self):
        self._history(self.boss, self.top)
        self._history(self.lead, self.sec)
        self._history(self.staff, self.sec)
        rows = self.env['hr.employee'].get_org_data()
        mine = [r for r in rows if r['id'] == 'E003']
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]['parentId'], 'E002')

    def test_views_load(self):
        for model, vtype in (('hr.employee', 'form'), ('hr.department', 'form'), ('hr.department', 'search')):
            self.env[model].get_view(view_type=vtype)
