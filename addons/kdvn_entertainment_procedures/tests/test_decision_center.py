"""Approve / Reject pages served by Odoo (/ea/<code>), tested on the reference procedure."""
from unittest import mock

from odoo.tests.common import HttpCase, tagged

SECRET = 'kderp_e_approval.e_approval_secret_key'


@tagged('post_install', '-at_install')
class TestDecisionCenter(HttpCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(SECRET, 'TEST-SIGNING-KEY')
        emp = self.env['hr.employee'].create({'name': 'DC applicant', 'code': 'TST9360', 'working': True})
        job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-360', 'job_name': 'Test job', 'external_id': 4360, 'is_general_expense': False})
        budget = self.env['kderp.job.budget.cache'].create({'external_id': 360, 'budget_code': 'B360', 'name': 'Budget', 'job_id': job.id})
        client = self.env['kderp.customer.cache'].create({'external_id': 360, 'name': 'Test client'})
        self.req = self.env['entertainment.request'].sudo().create({
            'budget_code_id': budget.id, 'guest_ids': [(6, 0, [client.id])], 'employee_id': emp.id, 'place': 'Test Place',
            'estimated_amount': 1500000, 'total_pax': 3, 'job_id': job.id, 'employee_ids': [(6, 0, [emp.id])]})
        for name in ('_notify_reviewers', '_notify_applicant'):
            patcher = mock.patch.object(type(self.req), name, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env['tier.definition'].sudo().search([('model', '=', 'entertainment.request')]).write({'active': False})
        self.env['tier.definition'].sudo().create({
            'name': 'DC step', 'frontend_name': 'DC step', 'procedure_tag': 'entertainment.request',
            'model_id': self.env['ir.model']._get('entertainment.request').id,
            'review_type': 'group', 'notify_on_rejected': True,
            'reviewer_group_id': self.env.ref('kdvn_e_approval.group_e_approval_admin').id})
        self.req.action_submit()
        self.review = self.req.review_ids.filtered(lambda r: r.status == 'pending')[:1]
        self.assertTrue(self.review, "no approval rule matched the test request")
        self.reviewer = self.env['res.users'].create({
            'name': 'DC reviewer', 'login': 'dc_test_reviewer', 'email': 'dc.reviewer@example.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('kdvn_e_approval.group_e_approval_admin').id]
                         + [self.env.ref(g).id for g in self.req._admin_groups])]})
        self.review.sudo().write({'reviewer_ids': [(6, 0, [self.reviewer.id])]})

    def _code(self, action):
        return self.env['kderp.e.approval.mixin']._short_link_code(
            self.review.id, self.reviewer.id, action, 'TEST-SIGNING-KEY')

    def _status(self):
        self.review.invalidate_recordset()
        return self.review.status

    def test_opening_a_link_never_decides(self):
        for action in ('approve', 'reject'):
            res = self.url_open('/ea/' + self._code(action))
            self.assertEqual(res.status_code, 200)
            self.assertIn('Approve this request?' if action == 'approve' else 'Reject this request?', res.text)
            self.assertEqual(self._status(), 'pending')

    def test_pages_cannot_be_framed_or_cached(self):
        res = self.url_open('/ea/' + self._code('approve'))
        self.assertEqual(res.headers.get('X-Frame-Options'), 'DENY')
        self.assertIn("frame-ancestors 'none'", res.headers.get('Content-Security-Policy', ''))
        self.assertEqual(res.headers.get('Cache-Control'), 'no-store')

    def test_bad_link_shows_nothing_about_the_request(self):
        res = self.url_open('/ea/%s-%s-a-%s' % (self.review.id, self.reviewer.id, 'f' * 24))
        self.assertIn('invalid', res.text)
        self.assertNotIn(self.req.name, res.text)

    def test_reject_needs_a_reason_and_escapes_it(self):
        url = '/ea/' + self._code('reject')
        res = self.url_open(url, data={'comment': '  '})
        self.assertIn('Please write a reason', res.text)
        self.assertEqual(self._status(), 'pending')
        res = self.url_open(url, data={'comment': 'too <b>expensive</b>'})
        self.assertIn('Rejected', res.text)
        self.assertIn('too &lt;b&gt;expensive&lt;/b&gt;', res.text)
        self.assertEqual(self._status(), 'rejected')
        # a second click only reports what happened
        res = self.url_open(url, data={'comment': 'again'})
        self.assertIn('Already decided', res.text)

    def test_approve_by_post(self):
        res = self.url_open('/ea/' + self._code('approve'), data={'comment': 'ok'})
        self.assertIn('Approved', res.text)
        self.assertEqual(self._status(), 'approved')

    def test_archived_user_cannot_use_the_link(self):
        self.reviewer.sudo().active = False
        for data in (None, {'comment': 'x'}):
            res = self.url_open('/ea/' + self._code('reject'), data=data)
            self.assertIn('no longer active', res.text)
        self.assertEqual(self._status(), 'pending')

    def test_links_point_to_odoo_when_the_setting_is_on(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('web.base.url', 'https://erp.example.test')
        mixin = self.env['kderp.e.approval.mixin']
        icp.set_param('kderp_e_approval.decision_in_odoo', 'True')
        item = self.req._notify_item(self.review, self.reviewer, mixin._notify_config())
        self.assertTrue(item['approve_url'].startswith('https://erp.example.test/ea/'))
        self.assertTrue(item['reject_url'].startswith('https://erp.example.test/ea/'))
        icp.set_param('kderp_e_approval.decision_in_odoo', 'False')
        item = self.req._notify_item(self.review, self.reviewer, mixin._notify_config())
        self.assertNotIn('/ea/', item['approve_url'].split('?')[0].replace('/webhook/ea', ''))
