# -*- coding: utf-8 -*-
"""Every window action and menu of the module opens: its views compile and the first page of data reads.
This is the smoke test of the converted Odoo 12 screens (leave, request, settings); it does not check what the screens look like."""
import datetime
from odoo.tests import common, tagged
from .common_at import ATCase


@tagged('post_install', '-at_install', 'at_screens')
class TestScreens(common.TransactionCase):

    def test_every_window_action_opens(self):
        admin = self.env.ref('base.user_admin')
        xmlids = self.env['ir.model.data'].search([('module', '=', 'kdvn_hr_attendance'), ('model', '=', 'ir.actions.act_window')])
        self.assertTrue(xmlids)
        for data in xmlids:
            action = self.env['ir.actions.act_window'].browse(data.res_id).with_user(admin)
            if not action.res_model or action.res_model not in self.env:
                continue
            model = self.env[action.res_model].with_user(admin)
            modes = [m for m in (action.view_mode or 'list,form').split(',') if m in ('list', 'form', 'kanban', 'pivot', 'graph', 'calendar', 'search')]
            with self.subTest(action=data.name):
                views = model.get_views([(False, m) for m in modes] + [(False, 'search')])
                self.assertTrue(views['views'])
                ctx = dict(action._get_eval_context() if hasattr(action, '_get_eval_context') else {})
                model.with_context(active_test=False).search([], limit=1)

    def test_every_menu_resolves(self):
        menus = self.env['ir.ui.menu'].with_user(self.env.ref('base.user_admin')).search([])
        for data in self.env['ir.model.data'].search([('module', '=', 'kdvn_hr_attendance'), ('model', '=', 'ir.ui.menu')]):
            with self.subTest(menu=data.name):
                menu = self.env['ir.ui.menu'].browse(data.res_id)
                self.assertTrue(menu.exists())
                if menu.action:
                    self.assertTrue(menu.action.exists())


@tagged('post_install', '-at_install', 'at_screens')
class TestEmptyRecords(common.TransactionCase):
    """Opening a form creates an empty virtual record and reads its computed fields (onchange). Odoo 12 let a compute method
    skip a field; Odoo 19 raises "Compute method failed to assign". Every model of the module is tried with an empty record."""

    def test_computed_fields_of_an_empty_record(self):
        admin = self.env.ref('base.user_admin')
        names = self.env['ir.model.data'].search([('module', '=', 'kdvn_hr_attendance'), ('model', '=', 'ir.model')]).mapped('res_id')
        models = self.env['ir.model'].browse(names).mapped('model')
        self.assertTrue(models)
        for name in models:
            if name not in self.env or self.env[name]._abstract:
                continue
            Model = self.env[name].with_user(admin)
            record = Model.new({})
            for fname, field in Model._fields.items():
                if not field.compute:
                    continue
                with self.subTest(model=name, field=fname):
                    try:
                        record[fname]
                    except ValueError as e:
                        if 'failed to assign' in str(e):
                            self.fail('%s.%s: %s' % (name, fname, e))
                    except Exception:
                        pass  # other errors come from reading an empty record (no employee, no date): not the Odoo 19 issue


@tagged('post_install', '-at_install', 'at_screens')
class TestRealisticRows(ATCase):
    """Records are read the way the list view reads them. An attendance day without any check (absence) must read."""

    def test_attendance_day_without_check_reads(self):
        at = self.new_at(self.new_employee(), datetime.date(2026, 3, 11))
        self.assertFalse(at.check_in)
        self.assertEqual(at.color, 0)
        self.assertTrue(at.read(['color', 'display_name', 'worked_hours']))

    def test_computed_fields_of_many_records(self):
        """A list view computes many records at once: no ensure_one in compute methods, every field assigned."""
        emp = self.new_employee()
        emp2 = self.new_employee()
        self.new_rule(emp, early_offset=60)
        self.new_rule(emp2, early_offset=30)
        rules = self.env['hr.attendance.rule'].search([])
        self.assertTrue(len(rules) >= 2)
        self.assertTrue(rules.read(['date_start', 'day_start', 'working_start', 'late_in', 'early_out', 'absence', 'special_ot_hour']))
        ats = self.new_at(emp, datetime.date(2026, 3, 11)) | self.new_at(emp2, datetime.date(2026, 3, 11))
        self.assertTrue(ats.read(['ah_leaves_count', 'at_rules', 'color']))
        self.assertTrue((emp | emp2).read(['hours_last_month', 'hours_last_month_display', 'hours_last_month_overtime']))

    def test_allocations_read_together(self):
        emp = self.new_employee()
        self.new_leave(emp, datetime.date(2026, 3, 11))
        allocations = self.env['hr.leave.allocation'].search([('employee_id', '=', emp.id)])
        self.assertTrue(allocations)
        self.assertTrue(allocations.read(['max_leaves', 'virtual_remaining_leaves', 'leaves_taken']))

    def test_ot_holiday_manager_defaults_are_commands(self):
        """The onchange of a new form chokes on a bare id list for a many2many default (Odoo 19 wants commands)."""
        defaults = self.env['hr.attendance.ot.holiday.manager'].default_get(['managed_section_ids'])
        for command in defaults.get('managed_section_ids', []):
            self.assertIsInstance(command, (tuple, list))
