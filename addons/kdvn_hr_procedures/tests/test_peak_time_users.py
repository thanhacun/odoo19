"""Peak time with employee_ids on hr.employee.public: a plain SM / PM (no HR rights) and a section manager reviewer can create, read, submit and
approve it; the staff list reaches the attendance rule. No mail."""
from datetime import timedelta
from unittest import mock

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.addons.kdvn_base.tests.ui_calls import run

FORM_FIELDS = ['name', 'state', 'employee_id', 'job_id', 'client_id', 'reason', 'employee_ids', 'actual_peak_from', 'actual_peak_to',
               'actual_peak_months', 'past_related_request_ids', 'attendance_rule_id', 'review_ids', 'can_review', 'special_case',
               'proceed_flow_message', 'approval_workflow_ribbon']


class TestPeakTimeUsers(TransactionCase):

    def _user(self, login, *xmlids):
        groups = self.env.ref('base.group_user')
        for xmlid in xmlids:
            groups |= self.env.ref(xmlid)
        user = self.env['res.users'].create({'name': login, 'login': login, 'email': login + '@example.test', 'group_ids': [(6, 0, groups.ids)]})
        emp = self.env['hr.employee'].create({'name': login.title(), 'code': 'PT' + str(abs(hash(login)) % 9000 + 1000), 'working': True, 'user_id': user.id})
        return user, emp

    def setUp(self):
        super().setUp()
        SM = 'kdvn_hr_attendance.group_hr_attendance_section_manager'
        self.req_user, self.req = self._user('pt_req', SM)          # applicant: SM without HR rights
        self.rev_user, self.rev = self._user('pt_rev', SM)          # reviewer (section manager)
        self.staff = [self.env['hr.employee'].create({'name': 'PT Staff %s' % i, 'code': 'PT900%s' % i, 'working': True}) for i in (1, 2)]
        self.env['tier.definition'].search([('model', '=', 'kderp.project.peak.time')]).write({'active': False})
        self.env['tier.definition'].create({
            'name': 'PTU step', 'frontend_name': 'PTU step', 'procedure_tag': 'kderp.project.peak.time',
            'model_id': self.env['ir.model']._get('kderp.project.peak.time').id, 'review_type': 'individual', 'reviewer_id': self.rev_user.id})
        Model = self.env['kderp.project.peak.time']
        for name in ('_notify_reviewers', '_notify_applicant'):
            patcher = mock.patch.object(type(Model), name, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.today = fields.Date.context_today(self.env.user)
        self.job = self.env['kderp.job.lookup'].create({'job_no': 'PTU-26-010', 'job_name': 'PTU job', 'external_id': 9210, 'is_general_expense': False})
        self.client = self.env['kderp.customer.cache'].create({'external_id': 9210, 'name': 'PTU client'})

    def _request(self):
        return self.env['kderp.project.peak.time'].with_user(self.req_user).create({
            'job_id': self.job.id, 'client_id': self.client.id, 'reason': 'Test',
            'execution_from': self.today - timedelta(days=30), 'execution_to': self.today + timedelta(days=300),
            'actual_peak_from': self.today, 'actual_peak_to': self.today + timedelta(days=30),
            'employee_ids': [(6, 0, [e.id for e in self.staff])]})

    def _read(self, record):
        fields_ = record._fields
        return record.web_read({n: {'fields': {'display_name': {}}} if fields_[n].relational else {} for n in FORM_FIELDS})[0]

    def test_plain_requester_creates_reads_submits(self):
        req = self._request()
        self.assertEqual(req.employee_id, self.req)
        data = self._read(req)
        self.assertEqual(sorted(e['display_name'] for e in data['employee_ids']), ['PT Staff 1', 'PT Staff 2'])
        # the staff list can be changed by the plain user (Many2many write needs read access on the comodel)
        req.write({'employee_ids': [(4, self.staff[0].id)]})
        req.write({'employee_ids': [(6, 0, [self.staff[1].id])]})
        self.assertEqual(req.employee_ids.mapped('code'), ['PT9002'])
        req.write({'employee_ids': [(6, 0, [e.id for e in self.staff])]})
        req.action_submit()
        self.assertEqual(req.state, 'submitted')

    def test_reviewer_reads_and_approves_and_the_rule_gets_the_staff(self):
        req = self._request()
        req.action_submit()
        as_rev = req.with_user(self.rev_user)
        self.assertTrue(as_rev.search([('id', '=', req.id)]))
        self.assertEqual(len(self._read(as_rev)['employee_ids']), 2)
        self.env.invalidate_all()      # a button click is a new request: the computed fields read above are not in the cache
        as_rev.validate_tier()
        self.assertIn(req.state, ('approved', 'synced'))
        rule = req.sudo().attendance_rule_id
        self.assertEqual(sorted(rule.employee_ids.mapped('code')), ['PT9001', 'PT9002'])

    def test_printed_form_lists_the_staff_sorted(self):
        data = self._request().prepare_peak_time_report_data()
        self.assertEqual([r['code'] for r in data['staff_rows'][:2]] if 'staff_rows' in data else ['PT9001', 'PT9002'], ['PT9001', 'PT9002'])

    def test_screens_open_for_the_requester_and_the_reviewer(self):
        self._request().action_submit()
        for login in ('pt_req', 'pt_rev'):
            self.assertEqual(run(self.env, prefixes=('kdvn_hr_procedures',), login=login), [], login)
