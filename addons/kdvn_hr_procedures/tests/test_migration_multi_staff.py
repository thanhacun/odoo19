"""Migration 19.0.0.2.0: one staff per request (transfer_employee_id) -> several (transfer_employee_ids), tier expressions rewritten."""
import importlib.util
import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase


def _migration():
    path = os.path.join(get_module_path('kdvn_hr_procedures'), 'migrations', '19.0.0.2.0', 'post-multi_staff.py')
    spec = importlib.util.spec_from_file_location('post_multi_staff', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationMultiStaff(TransactionCase):

    def test_expressions_are_rewritten_once(self):
        rewrite = _migration()._rewrite
        self.assertEqual(rewrite('rec.current_department_id.manager_id.user_id'), "rec.current_department_ids.mapped('manager_id.user_id')")
        self.assertEqual(rewrite('rec.transfer_employee_id.gm_id.user_id or rec.current_area_id.manager_id.user_id'),
                         "rec.transfer_employee_ids.mapped('gm_id.user_id') or rec.current_area_ids.mapped('manager_id.user_id')")
        done = "rec.transfer_employee_ids.mapped('gm_id.user_id')"
        self.assertEqual(rewrite(done), done, 'safe to run again')
        self.assertEqual(rewrite('rec.employee_id.gm_id.user_id'), 'rec.employee_id.gm_id.user_id', 'other fields are not touched')

    def test_old_rows_and_steps_are_converted(self):
        cr = self.env.cr
        staff = self.env['hr.employee'].create({'name': 'Mig staff', 'code': 'TST9391', 'working': True})
        applicant = self.env['hr.employee'].create({'name': 'Mig applicant', 'code': 'TST9392', 'working': True})
        job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-091', 'job_name': 'Mig job', 'external_id': 9191, 'is_general_expense': False})
        transfer = self.env['staff.transfer'].sudo().create({
            'employee_id': applicant.id, 'transfer_department_id': self.env['hr.department'].create({'name': 'Mig dept'}).id,
            'transfer_from_date': '2026-12-01', 'transfer_to_date': '2026-12-31'})
        self.env.flush_all()
        cr.execute("ALTER TABLE staff_transfer ADD COLUMN transfer_employee_id integer")      # the Odoo 19 column before this version
        cr.execute("UPDATE staff_transfer SET transfer_employee_id = %s, state = 'approved', current_project_manual_id = %s WHERE id = %s",
                   (staff.id, job.id, transfer.id))
        cr.execute("""UPDATE tier_definition SET reviewer_expression = 'rec.current_department_id.manager_id.user_id'
                      WHERE id = %s""", (self.env.ref('kdvn_hr_procedures.tier_st_current_sm').id,))
        for run in (1, 2):         # twice: safe to retry
            _migration().migrate(cr, '19.0.0.1.6')
        cr.execute("SELECT employee_id FROM staff_transfer_employee_rel WHERE transfer_id = %s", (transfer.id,))
        self.assertEqual(cr.fetchall(), [(staff.id,)])
        cr.execute("SELECT job_id FROM staff_transfer_frozen_project_rel WHERE transfer_id = %s", (transfer.id,))
        self.assertEqual(cr.fetchall(), [(job.id,)], 'the project from before is frozen for an approved request')
        cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'staff_transfer' AND column_name = 'transfer_employee_id'")
        self.assertFalse(cr.fetchall(), 'the old column (NOT NULL) is gone')
        cr.execute("SELECT reviewer_expression FROM tier_definition WHERE id = %s", (self.env.ref('kdvn_hr_procedures.tier_st_current_sm').id,))
        self.assertEqual(cr.fetchone()[0], "rec.current_department_ids.mapped('manager_id.user_id')")
