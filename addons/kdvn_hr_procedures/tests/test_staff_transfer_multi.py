"""Staff transfer: several staff, distance by car, notification of the staff (no network, no mail)."""
from unittest import mock

from odoo.tests.common import TransactionCase

ROUTE = 'odoo.addons.kdvn_hr_procedures.models.staff_transfer.route_distance.TransferRouteDistance'


class TestStaffTransferMulti(TransactionCase):

    def setUp(self):
        super().setUp()
        Emp = self.env['hr.employee']
        self.applicant = Emp.create({'name': 'T Applicant', 'code': 'TST9360', 'working': True})
        self.ho = Emp.create({'name': 'T Staff HO', 'code': 'TST9361', 'working': True, 'work_email': 'ho@example.com'})
        self.hp = Emp.create({'name': 'T Staff HP', 'code': 'TST9362', 'working': True, 'work_email': 'hp@example.com'})
        self.ho.write({'work_location': 'HO'})
        self.hp.write({'work_location': 'HAI PHONG'})
        self.job = self.env['kderp.job.lookup'].create({
            'job_no': 'TST-26-004', 'job_name': 'Test job', 'external_id': 4128, 'is_general_expense': False,
            'project_address': 'Lot K1, Thang Long Industrial Park, Hanoi City, Vietnam'})
        self.env.company.partner_id.write({'street': '5 Duy Tan', 'city': 'Hanoi'})
        self.hp_office = self.env['res.partner'].create({
            'name': 'Hai Phong Office', 'parent_id': self.env.company.partner_id.id, 'type': 'other', 'street': '1 Le Hong Phong', 'city': 'Hai Phong'})
        self.fake_calls = []

        def fake_fetch(model, origin, destination, key):
            self.fake_calls.append((origin, destination))
            return (23400 if 'Hai Phong' in origin else 31200), 1800
        for name, new in (('_fetch', fake_fetch), ('_api_key', lambda model: 'K')):
            patcher = mock.patch(ROUTE + '.' + name, new)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _transfer(self, staff):
        return self.env['staff.transfer'].sudo().create({
            'employee_id': self.applicant.id, 'transfer_employee_ids': [(6, 0, staff.ids)],
            'transfer_from_date': '2026-12-01', 'transfer_to_date': '2026-12-31', 'transfer_project_id': self.job.id})

    def test_several_staff_and_distance_per_office(self):
        t = self._transfer(self.ho | self.hp)
        self.assertEqual(len(t.transfer_employee_ids), 2)
        self.assertEqual(t.distance_ho_km, 31.2)
        self.assertEqual(t.distance_hp_km, 23.4)
        self.assertIn('Hanoi Head Office: 31.2 km', t.distance_text)
        data = t._prepare_staff_transfer_report_data()
        self.assertEqual(data['staff_name'], 'T Staff HO, T Staff HP')
        self.assertIn('23.4 km', data['matrix_note'])

    def test_hai_phong_office_is_the_company_address_in_that_city(self):
        self.assertEqual(self.env['staff.transfer']._office_address('hp'), '1 Le Hong Phong, Hai Phong')
        self.assertTrue(self._transfer(self.hp).distance_hp_km)
        self.hp_office.write({'street': '2 Le Loi'})
        self.assertEqual(self.env['staff.transfer']._office_address('hp'), '2 Le Loi, Hai Phong')

    def test_the_old_office_parameter_is_ignored(self):
        self.hp_office.unlink()
        self.env['ir.config_parameter'].sudo().set_param('kderp_hr_procedures.office_address_hp', '9 Old Street, Hai Phong')
        self.assertEqual(self.env['staff.transfer']._office_address('hp'), '')

    def test_distance_is_cached_and_a_missing_office_is_reported(self):
        self.hp_office.unlink()      # no Hai Phong address on the company
        t = self._transfer(self.hp)
        self.assertFalse(t.distance_hp_km)
        self.assertIn('Office address not set', t.distance_message)
        t2 = self._transfer(self.ho)
        t2.action_update_distances()
        self.assertEqual(len([c for c in self.fake_calls if c[1] == self.job.project_address]), 1)   # second one came from the cache

    def test_staff_without_email_is_named_in_the_chatter(self):
        self.hp.work_email = False
        self.env.flush_all()
        t = self._transfer(self.ho | self.hp)
        sent = []
        with mock.patch.object(type(t), '_notify_send_email', lambda self, to, subject, body, **kw: sent.append(to)):
            t._notify_transferred_staff()
        self.assertEqual(sent, ['ho@example.com'])
        self.assertIn('T Staff HP', t.message_ids[0].body)

    def test_project_history_for_every_staff(self):
        t = self._transfer(self.ho | self.hp)
        t._update_project_history()
        for emp in (self.ho, self.hp):
            self.assertEqual(emp.project_history_ids.mapped('project_code'), self.job)

    def test_after_submit_only_a_missing_distance_is_recalculated(self):
        t = self._transfer(self.ho | self.hp)
        self.assertEqual((t.distance_ho_km, t.distance_hp_km), (31.2, 23.4))
        self.env.flush_all()
        self.env.cr.execute("UPDATE staff_transfer SET state='approved', distance_hp_km=0, distance_message='x' WHERE id=%s", (t.id,))
        t.invalidate_recordset()
        self.env['transfer.route.distance'].search([]).unlink()
        self.fake_calls[:] = []
        t.action_update_distances()
        self.assertEqual(t.distance_hp_km, 23.4)
        self.assertEqual(t.distance_ho_km, 31.2)
        self.assertEqual(len(self.fake_calls), 1, 'only the missing office (Hai Phong) is asked')

    def test_approved_distance_is_never_changed(self):
        t = self._transfer(self.ho)
        self.env.flush_all()
        self.env.cr.execute("UPDATE staff_transfer SET state='approved' WHERE id=%s", (t.id,))
        t.invalidate_recordset()
        self.fake_calls[:] = []
        t.action_update_distances()
        self.assertEqual((t.distance_ho_km, self.fake_calls), (31.2, []))
