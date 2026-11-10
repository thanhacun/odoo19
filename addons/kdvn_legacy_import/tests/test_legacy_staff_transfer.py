"""Staff transfer import: Odoo 12 before 12.0.1.7.0 (one staff in the column transfer_employee_id) and after (relation table, several staff)."""
from copy import deepcopy
from unittest import mock

from odoo.tests.common import TransactionCase

from .test_legacy_import import FIXTURE

STEPS = ['lang_formats', 'department_types', 'locations', 'user_locations', 'departments', 'users', 'employees', 'employee_categories',
         'employee_links', 'histories', 'organisation', 'ea_requests']

TRANSFER = {'id': 1, 'name': 'ST-T-0001', 'state': 'draft', 'employee_id': 20, 'reason': 'Test', 'transfer_department_id': 13,
            'transfer_from_date': '2026-12-01', 'transfer_to_date': '2026-12-31', 'petrol_allowance': False,
            'distance_ho_km': 12.3, 'distance_hp_km': 0, 'distance_message': None,
            'create_uid': 11, 'create_date': '2026-11-02 03:00:00', 'write_uid': 11, 'write_date': '2026-11-03 04:00:00'}


class TestLegacyStaffTransfer(TransactionCase):

    def setUp(self):
        super().setUp()
        if 'staff.transfer' not in self.env or 'tier.review' not in self.env:
            self.skipTest('kdvn_hr_procedures is not installed')
        self.data = deepcopy(FIXTURE)
        self.columns = {}
        data = self.data

        def fake(model, table, columns, where=None):
            if columns is None:
                return [dict(row) for row in data.get(table, [])]
            return [dict({c: None for c in columns}, **{k: v for k, v in row.items() if k in columns}) for row in data.get(table, [])]
        cls = type(self.env['kdvn.legacy.import'])
        for name, replacement in (('_legacy_rows', fake), ('_legacy_columns', lambda self_, table: self.columns.get(table, set()))):
            patcher = mock.patch.object(cls, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.imp = self.env['kdvn.legacy.import']

    def _run(self):
        out = self.imp.run(steps=STEPS)
        self.assertEqual(out['errors'], [], out['log'])

    def _transfer(self):
        return self.env['staff.transfer'].with_context(active_test=False).search([('name', '=', 'ST-T-0001')])

    def _employee(self, code):
        return self.env['hr.employee'].search([('code', '=', code)])

    def test_old_odoo_12_one_staff_column(self):
        self.data['staff_transfer'] = [dict(TRANSFER, transfer_employee_id=21)]
        self._run()
        transfer = self._transfer()
        self.assertEqual(len(transfer), 1)
        self.assertEqual(transfer.transfer_employee_ids.ids, self._employee('IA001').ids)
        self.assertEqual(transfer.distance_ho_km, 12.3, 'the distance of Odoo 12 is copied, the map service is not called')
        self.assertEqual(transfer.state, 'draft')

    def test_new_odoo_12_several_staff_relation(self):
        self.columns['staff_transfer_employee_rel'] = {'transfer_id', 'employee_id'}
        self.columns['staff_transfer_frozen_project_rel'] = {'transfer_id', 'job_id'}
        self.data['staff_transfer'] = [dict(TRANSFER)]
        self.data['staff_transfer_employee_rel'] = [{'transfer_id': 1, 'employee_id': 21}, {'transfer_id': 1, 'employee_id': 22}]
        self._run()
        transfer = self._transfer()
        self.assertEqual(sorted(transfer.transfer_employee_ids.mapped('code')), ['IA001', 'IL001'])

    def test_no_map_call_and_second_run_does_not_duplicate(self):
        self.data['staff_transfer'] = [dict(TRANSFER, transfer_employee_id=21)]
        with mock.patch('odoo.addons.kdvn_hr_procedures.models.staff_transfer.route_distance.requests.get',
                        side_effect=AssertionError('the import must not call a map service')):
            self._run()
            self.data['staff_transfer'][0]['reason'] = 'Changed in Odoo 12'
            self._run()
        transfer = self._transfer()
        self.assertEqual((len(transfer), transfer.reason), (1, 'Changed in Odoo 12'))
        self.assertEqual(len(transfer.transfer_employee_ids), 1)
