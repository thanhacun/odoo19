# -*- coding: utf-8 -*-
"""Record rules ported from Odoo 12 (security/hr_attendance_record_rules.xml): who sees and who changes attendance records.
Odoo 12 behaviour: staff see their own days; section managers and GMs see the days whose view_user_ids lists them (read + write);
directors read everything and write nothing; attendance HR admins do everything. Also: the GM chain of the employee is filled
(the GM group is defined here, kdvn_hr_ext looks it up)."""
import datetime

from odoo.exceptions import AccessError
from odoo.tests import tagged
from .common_at import ATCase

DAY = datetime.date(2026, 10, 14)


@tagged('post_install', '-at_install', 'at_rules_security')
class TestRecordRules(ATCase):

    def _user(self, login, *group_xmlids):
        groups = [self.env.ref('base.group_user')] + [self.env.ref(x) for x in group_xmlids]
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'email': login + '@example.com', 'group_ids': [(6, 0, [g.id for g in groups])]})

    def setUp(self):
        super().setUp()
        self.staff_user = self._user('zz-rule-staff')
        self.other_user = self._user('zz-rule-other')
        self.sm = self._user('zz-rule-sm', 'kdvn_hr_attendance.group_hr_attendance_section_manager')
        self.sm_outsider = self._user('zz-rule-sm2', 'kdvn_hr_attendance.group_hr_attendance_section_manager')
        self.director = self._user('zz-rule-dir', 'kdvn_hr_attendance.group_hr_attendance_director')
        self.hr_admin = self._user('zz-rule-hr', 'hr_attendance.group_hr_attendance_user')
        self.staff = self.new_employee(user_id=self.staff_user.id)
        self.other = self.new_employee(user_id=self.other_user.id)
        self.at = self.new_at(self.staff, DAY, (8, 0), (17, 0))
        self.at_other = self.new_at(self.other, DAY, (8, 0), (17, 0))
        self.at.sudo().view_user_ids = [(6, 0, [self.sm.id])]
        self.at_other.sudo().view_user_ids = [(6, 0, [self.sm_outsider.id])]
        self.both = self.at | self.at_other

    def _visible(self, user, records=None):
        return (records or self.both).with_user(user).filtered_domain([]) and (records or self.both).with_user(user).search(
            [('id', 'in', (records or self.both).ids)])

    def test_staff_sees_only_own_days(self):
        self.assertEqual(self._visible(self.staff_user), self.at)
        self.assertEqual(self._visible(self.other_user), self.at_other)

    def test_section_manager_sees_the_days_that_list_him(self):
        self.assertEqual(self._visible(self.sm), self.at)
        self.assertEqual(self._visible(self.sm_outsider), self.at_other)

    def test_director_reads_all_and_writes_nothing(self):
        self.assertEqual(self._visible(self.director), self.both)
        self.assertFalse(self.at.with_user(self.director).has_access('write'))

    def test_hr_admin_reads_and_writes_all(self):
        self.assertEqual(self._visible(self.hr_admin), self.both)
        self.assertTrue(self.at.with_user(self.hr_admin).has_access('write'))

    def test_write_rights(self):
        self.assertTrue(self.at.with_user(self.staff_user).has_access('write'), 'staff change their own day')
        self.assertTrue(self.at.with_user(self.sm).has_access('write'), 'section manager changes a day that lists him')
        self.assertFalse(self.at_other.with_user(self.sm).has_access('write'))
        self.assertFalse(self.at.with_user(self.other_user).has_access('write'))
        self.assertFalse(self.at.with_user(self.staff_user).has_access('unlink'))
        with self.assertRaises(AccessError):
            self.at_other.with_user(self.sm).check_access('read')

    def test_leave_cover_and_summary_follow_the_same_lists(self):
        cover = self.env['hr.leave.cover'].search([('employee_id', 'in', self.both.employee_id.ids)])
        if cover:
            cover.sudo().view_user_ids = [(6, 0, [self.sm.id])]
            self.assertEqual(cover.with_user(self.sm).search([('id', 'in', cover.ids)]), cover)
            self.assertFalse(cover.with_user(self.sm_outsider).search([('id', 'in', cover.ids)]))
        summary = self.env['hr.attendance.summary'].with_user(self.other_user).search([])
        self.assertEqual(summary.employee_id, self.other, 'staff read only their own summary lines')

    def test_gm_chain_is_filled_when_a_manager_has_the_gm_group(self):
        gm_user = self._user('zz-rule-gm', 'kdvn_hr_attendance.group_hr_attendance_gm')
        gm = self.new_employee(user_id=gm_user.id)
        dept = self.env['hr.department'].create({'name': 'ZZ rules section', 'manager_id': gm.id})
        member = self.new_employee(parent_id=gm.id, admin_manager_id=gm.id, department_id=dept.id)
        member._compute_parent_users()
        self.assertEqual(member.gm_id, gm)
        self.assertEqual(member.admin_gm_id, gm)
