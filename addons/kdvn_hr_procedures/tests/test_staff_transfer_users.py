"""Staff transfer as the people who really use it (no admin rights): requester (SM), section manager, GM, plain staff.
hr.employee is private to HR in Odoo 19: the form, the submit and the approval must work with hr.employee.public + sudo reads.
The real tier definitions (not a simplified step) are used, so the org chart decides who reviews. No network, no mail."""
from datetime import date, timedelta
from unittest import mock

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.addons.kdvn_base.tests.ui_calls import run

ROUTE = 'odoo.addons.kdvn_hr_procedures.models.staff_transfer.route_distance.TransferRouteDistance'
FORM_FIELDS = ['name', 'state', 'employee_id', 'transfer_employee_ids', 'transfer_area_id', 'transfer_department_id', 'transfer_project_id',
               'transfer_from_date', 'transfer_to_date', 'current_area_ids', 'current_department_ids', 'current_project_ids',
               'current_project_manual_id', 'project_from_history', 'no_history_employee_ids', 'transfer_project_address', 'distance_text',
               'distance_message', 'allowance_matrix_html', 'approval_workflow_ribbon', 'review_ids', 'can_review', 'is_current_applicant']


class TestStaffTransferUsers(TransactionCase):

    def _user(self, login, *xmlids):
        groups = self.env.ref('base.group_user')
        for xmlid in xmlids:
            groups |= self.env.ref(xmlid)
        user = self.env['res.users'].create({'name': login, 'login': login, 'email': login + '@example.test', 'group_ids': [(6, 0, groups.ids)]})
        return user, self.env['hr.employee'].create({'name': login.title(), 'code': 'TU' + str(abs(hash(login)) % 9000 + 1000), 'working': True,
                                                      'user_id': user.id, 'work_email': login + '@work.test'})

    def setUp(self):
        super().setUp()
        self.today = date.today()
        old = self.today - timedelta(days=200)
        SM = 'kdvn_hr_attendance.group_hr_attendance_section_manager'
        GM = 'kdvn_hr_attendance.group_hr_attendance_gm'
        self.gm_user, self.gm = self._user('tu_gm', SM, GM)
        self.sm_user, self.sm = self._user('tu_sm', SM)            # manager of the staff's current section
        self.req_user, self.req = self._user('tu_req', SM)         # applicant: SM of another section
        self.hr_user, self.hr = self._user('tu_hr', 'hr.group_hr_manager')
        self.staff1 = self.env['hr.employee'].create({'name': 'TU Staff 1', 'code': 'TU9001', 'working': True, 'work_email': 'tu1@work.test'})
        self.staff2 = self.env['hr.employee'].create({'name': 'TU Staff 2 & Co', 'code': 'TU9002', 'working': True})
        Dept = self.env['hr.department']
        self.area = Dept.create({'name': 'TU Area', 'code': 'TU12'})
        self.sec_a = Dept.create({'name': 'TU Section A', 'code': 'TU1201', 'parent_id': self.area.id})
        self.sec_b = Dept.create({'name': 'TU Section B', 'code': 'TU1202', 'parent_id': self.area.id})
        self.sec_c = Dept.create({'name': 'TU Section C', 'code': 'TU1203', 'parent_id': self.area.id})
        Manager = self.env['hr.manager.history']
        for dept, emp in ((self.area, self.gm), (self.sec_a, self.sm), (self.sec_b, self.req)):
            Manager.create({'department_id': dept.id, 'manager_id': emp.id, 'effective_date': old})
        History = self.env['hr.employee.department.history']
        for emp, dept in ((self.staff1, self.sec_a), (self.staff2, self.sec_a), (self.sm, self.sec_a), (self.req, self.sec_b)):
            History.create({'employee_id': emp.id, 'department_id': dept.id, 'effective_date': old, 'admin_dept_id': dept.id, 'admin_effv_date': old})
        (self.staff1 | self.staff2 | self.sm | self.req | self.gm).flush_recordset()
        for emp in (self.staff1, self.staff2, self.sm, self.req):
            emp._compute_parent_users()
        self.job = self.env['kderp.job.lookup'].create({
            'job_no': 'TU-26-001', 'job_name': 'TU job', 'external_id': 9101, 'is_general_expense': False,
            'project_address': 'Lot K1, Thang Long Industrial Park, Hanoi City, Vietnam'})
        self.env.company.partner_id.write({'street': '5 Duy Tan', 'city': 'Hanoi'})
        self.mails = []
        patchers = [
            mock.patch(ROUTE + '._fetch', lambda model, origin, destination, key: (31200, 1800)),
            mock.patch(ROUTE + '._api_key', lambda model: 'K'),
            mock.patch('odoo.addons.kdvn_e_approval.models.kderp_approval_mixin.KderpApprovalMixin._notify_send_email',
                       lambda model, to, subject, body, **kw: self.mails.append((to, subject))),
            mock.patch('odoo.addons.kdvn_e_approval.models.kderp_approval_mixin.KderpApprovalMixin._notify_send_talk', lambda *a, **k: True),
        ]
        for model in ('staff.transfer',):
            for name in ('_notify_reviewers', '_notify_applicant'):
                patchers.append(mock.patch.object(type(self.env[model]), name, return_value=True))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _request(self, staff=None):
        """Created as the applicant (an SM without HR rights)."""
        staff = staff or (self.staff1 | self.staff2)
        return self.env['staff.transfer'].with_user(self.req_user).create({
            'transfer_employee_ids': [(6, 0, staff.ids)], 'transfer_department_id': self.sec_c.id, 'transfer_project_id': self.job.id,
            'transfer_from_date': self.today + timedelta(days=5), 'transfer_to_date': self.today + timedelta(days=95), 'reason': 'Needed'})

    def test_applicant_creates_reads_and_submits(self):
        req = self._request()
        self.assertEqual(req.employee_id, self.req)
        data = req.web_read({name: {'fields': {'display_name': {}}} if self.env['staff.transfer']._fields[name].relational else {}
                             for name in FORM_FIELDS})[0]
        self.assertEqual(sorted(e['display_name'] for e in data['transfer_employee_ids']), ['TU Staff 1', 'TU Staff 2 & Co'])
        self.assertEqual([d['display_name'] for d in data['current_department_ids']], ['TU Section A'])
        self.assertEqual(data['project_from_history'], False)
        self.assertEqual(len(data['no_history_employee_ids']), 2)
        self.assertIn('Hanoi Head Office: 31.2 km', data['distance_text'])
        self.assertIn('Unit: 1,000 VND', req.allowance_matrix_html)   # renders for a plain user
        req.action_submit()
        self.assertEqual(req.state, 'submitted')
        # the real steps resolved to real people (SM of the staff, GMs)
        reviewers = req.review_ids.sorted('sequence').mapped('reviewer_ids')
        self.assertIn(self.sm_user, reviewers)
        self.assertIn(self.hr_user, reviewers)

    def test_submit_checks(self):
        req = self._request(self.staff1)
        req.sudo().transfer_employee_ids = [(6, 0, [self.req.id])]
        with self.assertRaisesRegex(ValidationError, 'yourself'):
            req.action_submit()
        req.sudo().transfer_employee_ids = [(5, 0, 0)]
        with self.assertRaisesRegex(ValidationError, 'at least one staff'):
            req.action_submit()
        mine = self.env['hr.employee'].create({'name': 'TU Mine', 'code': 'TU9003', 'working': True})
        self.env['hr.employee.department.history'].create({
            'employee_id': mine.id, 'department_id': self.sec_b.id, 'effective_date': self.today - timedelta(days=9),
            'admin_dept_id': self.sec_b.id, 'admin_effv_date': self.today - timedelta(days=9)})
        req.sudo().transfer_employee_ids = [(6, 0, mine.ids)]
        with self.assertRaisesRegex(ValidationError, 'already belongs to your section'):
            req.action_submit()

    def test_recalculate_after_submit_works_while_under_validation(self):
        req = self._request(self.staff1)
        req.action_submit()
        self.assertEqual(req.state, 'submitted')
        self.assertEqual(req.distance_ho_km, 31.2)
        req.sudo().with_context(skip_validation_check=True).write({'distance_ho_km': 0, 'distance_message': 'x'})   # a distance that was never found
        req.with_user(self.req_user).action_update_distances()
        self.assertEqual(req.distance_ho_km, 31.2)

    def test_section_manager_sees_the_request_in_review_and_everything_reads(self):
        req = self._request()
        req.action_submit()
        as_sm = req.with_user(self.sm_user)
        self.assertTrue(as_sm.search([('id', '=', req.id)]), 'the SM of the staff reviews it, so the strict rule lets him see it')
        data = as_sm.web_read({name: {'fields': {'display_name': {}}} if self.env['staff.transfer']._fields[name].relational else {}
                               for name in FORM_FIELDS})[0]
        self.assertEqual(len(data['transfer_employee_ids']), 2)
        self.assertTrue(data['current_department_ids'])
        stranger = self.env['hr.employee'].create({'name': 'TU Stranger'})
        stranger_user = self._user('tu_other', 'kdvn_hr_attendance.group_hr_attendance_section_manager')[0]
        self.assertFalse(req.with_user(stranger_user).search([('id', '=', req.id)]))
        self.assertTrue(stranger)

    def test_approval_by_the_real_chain_updates_history_notifies_staff_and_freezes(self):
        req = self._request()
        req.action_submit()
        for _step in range(10):
            pending = req.review_ids.filtered(lambda r: r.status == 'pending').sorted('sequence')
            if not pending:
                break
            reviewer = pending[0].reviewer_ids[:1]
            self.assertTrue(reviewer, 'step %s has a reviewer' % pending[0].definition_id.name)
            req.with_user(reviewer).validate_tier()
        self.assertEqual(req.state, 'approved')
        for emp in (self.staff1, self.staff2):
            self.assertEqual(emp.sudo().project_history_ids.mapped('project_code'), self.job)
        self.assertEqual(self.mails, [('tu1@work.test', 'Transfer approved: %s' % req.name)], 'staff 2 has no work e-mail: only staff 1 is mailed')
        body = ' '.join(req.sudo().message_ids.mapped('body'))
        self.assertIn('Staff notified: TU Staff 1', body)
        self.assertIn('Not notified (no work e-mail or notifications switched off): TU Staff 2 &amp; Co', body)
        self.assertIn('TU Staff 2 &amp; Co', body, 'names are escaped once in the chatter (no &amp;amp;)')
        self.assertNotIn('&amp;amp;', body)
        # the history now has the new project, the request still shows the project from before (frozen)
        self.assertFalse(req.current_project_frozen_ids)   # nobody had a project history: nothing to freeze
        self.assertEqual(req.state, 'approved')

    def test_frozen_project_survives_the_new_history(self):
        old = self.env['kderp.job.lookup'].create({'job_no': 'TU-26-000', 'job_name': 'Old job', 'external_id': 9100, 'is_general_expense': False})
        self.env['hr.employee.project.history'].create({'employee_id': self.staff1.id, 'project_code': old.id, 'effective_date': self.today - timedelta(days=60)})
        req = self._request(self.staff1)
        self.assertEqual(req.current_project_ids, old)
        self.assertTrue(req.project_from_history)
        req.action_submit()
        for _step in range(10):
            pending = req.review_ids.filtered(lambda r: r.status == 'pending').sorted('sequence')
            if not pending:
                break
            req.with_user(pending[0].reviewer_ids[:1]).validate_tier()
        self.assertEqual(req.state, 'approved')
        self.assertEqual(req.current_project_frozen_ids, old)
        self.assertEqual(req.current_project_ids, old, 'the printed form keeps the project from before')

    def test_screens_open_for_each_role(self):
        req = self._request()
        req.action_submit()
        for login in ('tu_req', 'tu_sm', 'tu_gm', 'tu_hr'):
            problems = run(self.env, prefixes=('kdvn_hr_procedures',), login=login)
            self.assertEqual(problems, [], login)
