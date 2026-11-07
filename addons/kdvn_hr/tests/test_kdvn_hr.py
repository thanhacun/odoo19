from datetime import date, timedelta

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class TestKdvnHr(TransactionCase):

    def setUp(self):
        super().setUp()
        self.emp = self.env['hr.employee'].create({'name': 'Nguyen Van An', 'code': 'T001', 'working': True})
        self.site_a = self.env['kderp.employee.location.code'].create({'name': 'Site A'})
        self.site_b = self.env['kderp.employee.location.code'].create({'name': 'Site B'})

    def test_code_in_display_name_and_search(self):
        self.assertTrue(self.emp.display_name.startswith('T001 - '))
        self.assertIn(self.emp, self.env['hr.employee'].name_search('T001') and self.env['hr.employee'].search([('display_name', 'ilike', 'T001')]))
        self.assertIn(self.emp.id, [r[0] for r in self.env['hr.employee'].name_search('t001')])
        self.assertIn(self.emp.id, [r[0] for r in self.env['hr.employee'].name_search('Van An')])

    def test_code_unique(self):
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.cr.savepoint():
            self.env['hr.employee'].create({'name': 'Other', 'code': 'T001', 'working': True})

    def test_current_location_follows_dates(self):
        today = date.today()
        Loc = self.env['kderp.hr.employee.location']
        Loc.create({'employee_id': self.emp.id, 'location_id': self.site_a.id, 'date': today - timedelta(days=30)})
        self.assertEqual(self.emp.current_location_id, self.site_a)
        Loc.create({'employee_id': self.emp.id, 'location_id': self.site_b.id, 'date': today - timedelta(days=1)})
        self.assertEqual(self.emp.current_location_id, self.site_b)
        # a future move does not count yet
        Loc.create({'employee_id': self.emp.id, 'location_id': self.site_a.id, 'date': today + timedelta(days=5)})
        self.assertEqual(self.emp.current_location_id, self.site_b)
        self.assertEqual(Loc.get_location_with_date(self.emp.id, today + timedelta(days=5)).location_id, self.site_a)

    def test_location_unique_per_employee_and_date(self):
        Loc = self.env['kderp.hr.employee.location']
        Loc.create({'employee_id': self.emp.id, 'location_id': self.site_a.id, 'date': date(2026, 1, 1)})
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.cr.savepoint():
            Loc.create({'employee_id': self.emp.id, 'location_id': self.site_b.id, 'date': date(2026, 1, 1)})

    def test_location_name_unique_ignoring_case(self):
        with self.assertRaises(ValidationError):
            self.env['kderp.employee.location.code'].create({'name': 'site a'})

    def test_department_code_type_and_new_manager(self):
        dtype = self.env['hr.department.type'].create({'name': 'Section', 'code': 'section'})
        boss = self.env['hr.employee'].create({'name': 'Boss', 'code': 'T002', 'working': True})
        dept = self.env['hr.department'].create({'name': 'Design', 'code': 'DSG', 'type_id': dtype.id, 'manager_id': self.emp.id})
        dept.write({'new_manager': boss.id, 'new_man_effective_date': date.today() + timedelta(days=3)})
        dept._change_to_effective_manager()
        self.assertEqual(dept.manager_id, self.emp, 'not yet effective')
        dept.new_man_effective_date = date.today()
        dept._change_to_effective_manager()
        self.assertEqual(dept.manager_id, boss)
        self.assertFalse(dept.new_manager, 'the pending change is cleared once applied')
        self.assertIn(dept, self.env['hr.department'].search([('display_name', 'ilike', 'DSG')]))

    def test_department_code_unique(self):
        self.env['hr.department'].create({'name': 'A', 'code': 'X1'})
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.cr.savepoint():
            self.env['hr.department'].create({'name': 'B', 'code': 'X1'})

    def test_forms_and_lists_load(self):
        for model, vtype in (('hr.employee', 'form'), ('hr.employee', 'list'), ('hr.employee', 'search'),
                             ('hr.department', 'form'), ('hr.department', 'list')):
            self.env[model].get_view(view_type=vtype)


class TestDepartmentDisplayName(TransactionCase):

    def test_department_shows_its_own_name(self):
        """Odoo 12 _name_only: fields show "GA Section", not the whole path (the path is complete_name)."""
        top = self.env['hr.department'].create({'name': 'ZZ Top', 'code': 'ZZ00'})
        child = self.env['hr.department'].create({'name': 'ZZ GA Section', 'code': 'ZZ00-01', 'parent_id': top.id})
        self.assertEqual(child.display_name, 'ZZ GA Section')
        self.assertIn('ZZ Top', child.complete_name)
        self.assertEqual(dict(child.name_get())[child.id] if hasattr(child, 'name_get') else child.display_name, 'ZZ GA Section')
