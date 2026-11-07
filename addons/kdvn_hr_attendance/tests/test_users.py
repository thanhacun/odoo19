# -*- coding: utf-8 -*-
"""The employee "Create users" action (Odoo 12 create_users): a user is made from the template user a-kdvn-user, gets its location and the attendance groups.
Odoo 19 needed: location_user_id on res.users (kdvn_base), group_ids instead of groups_id."""
from odoo.tests import tagged
from .common_at import ATCase


@tagged('post_install', '-at_install', 'at_users')
class TestCreateUsers(ATCase):

    def test_create_users_from_template(self):
        model = self.env['ir.model']._get('res.users')
        office = self.env['kderp.base.code'].create({'code': 'ZZ', 'name': 'ZZ Office', 'type_code': 'user_location', 'model_id': model.id})
        self.env['res.users'].create({'name': 'KDVN template', 'login': 'a-kdvn-user', 'location_user_id': office.id})
        employee = self.new_employee(working=True, work_email='zz.create.users@example.com')
        employee.create_users()
        user = employee.user_id
        self.assertTrue(user)
        self.assertEqual(user.login, 'zz.create.users')
        self.assertEqual(user.location_user_id, office)
        self.assertIn(self.env.ref('kdvn_hr_attendance.group_hr_attendance_menu_staff'), user.group_ids)

    def test_location_domain_only_user_locations(self):
        model = self.env['ir.model']._get('res.users')
        office = self.env['kderp.base.code'].create({'code': 'ZY', 'name': 'ZY Office', 'type_code': 'user_location', 'model_id': model.id})
        domain = self.env['res.users']._fields['location_user_id'].domain(self.env['res.users'])
        self.assertIn(office, self.env['kderp.base.code'].search(domain))
