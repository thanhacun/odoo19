from odoo.tests.common import TransactionCase


class TestPublicManagerFields(TransactionCase):
    """Odoo 19 resolves employee_id.<field> on hr.employee.public for a user without HR rights. Attendance screens search
    employee_id.admin_manager_user_ids / parent_user_ids as that user: both must exist on the public model."""

    def test_plain_user_can_search_by_manager_users(self):
        user = self.env['res.users'].create({'name': 'Plain manager', 'login': 'plain_mgr',
                                             'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        for model in ('hr.attendance', 'hr.attendance.request', 'hr.leave'):
            if model not in self.env:            # attendance is not a dependency of this module
                continue
            Model = self.env[model].with_user(user)
            if Model.has_access('read'):
                Model.search_count(['|', ('employee_id.admin_manager_user_ids', '=', user.id),
                                    ('employee_id.parent_user_ids', '=', user.id)])
        public = self.env['hr.employee.public'].with_user(user)
        self.assertIn('admin_manager_user_ids', public._fields)
        public.search_count([('admin_manager_user_ids', 'in', [user.id])])
