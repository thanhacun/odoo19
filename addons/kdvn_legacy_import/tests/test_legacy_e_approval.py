"""E-approval import with a small fake Odoo 12 snapshot: requests with their tier reviews, chatter, no side effects, re-runnable."""
from copy import deepcopy
from unittest import mock

from odoo.tests.common import TransactionCase

from .test_legacy_import import FIXTURE

STEPS = ['lang_formats', 'department_types', 'locations', 'user_locations', 'departments', 'users', 'employees', 'employee_categories',
         'employee_links', 'histories', 'organisation', 'ea_requests', 'ea_reviews', 'ea_chatter', 'ea_attachments', 'ea_check']

EA = {
    'ir_model': [{'id': 7, 'model': 'entertainment.request'}],
    'tier_definition': [{'id': 1, 'name': '[ENT] 1st Approval', 'model_id': 7}, {'id': 2, 'name': '[ENT] 2nd Approval', 'model_id': 7}],
    'entertainment_request': [{
        'id': 1, 'name': 'EF-T-0001', 'state': 'submitted', 'employee_id': 21, 'date_entertainment': '2026-11-01', 'place': 'Hanoi', 'guests': 'Mr A',
        'date_input': '2026-11-02', 'entertainment_type': 'domestic', 'estimated_amount': 1500000, 'job_id': None, 'budget_code_id': None, 'is_gm': False,
        'is_emergency': False, 'reason': 'Test', 'total_pax': 3, 'approval_progress': '1/2', 'create_uid': 11, 'create_date': '2026-11-02 03:00:00',
        'write_uid': 11, 'write_date': '2026-11-03 04:00:00'}],
    'tier_review': [
        {'id': 1, 'status': 'approved', 'model': 'entertainment.request', 'res_id': 1, 'definition_id': 1, 'sequence': 1, 'todo_by': 'IB001 - Boss One',
         'done_by': 10, 'requested_by': 11, 'reviewed_date': '2026-11-03 04:00:00', 'can_review': False, 'comment': None, 'create_uid': 11,
         'create_date': '2026-11-02 03:01:00', 'write_uid': 10, 'write_date': '2026-11-03 04:00:00'},
        {'id': 2, 'status': 'pending', 'model': 'entertainment.request', 'res_id': 1, 'definition_id': 2, 'sequence': 2, 'todo_by': 'IB001 - Boss One',
         'done_by': None, 'requested_by': 11, 'reviewed_date': None, 'can_review': True, 'comment': None, 'create_uid': 11,
         'create_date': '2026-11-02 03:01:00', 'write_uid': 11, 'write_date': '2026-11-02 03:01:00'}],
    'res_users_tier_review_rel': [{'tier_review_id': 1, 'res_users_id': 10}, {'tier_review_id': 2, 'res_users_id': 10}],
    'mail_message': [{'id': 1, 'model': 'entertainment.request', 'res_id': 1, 'message_type': 'notification', 'subtype_id': None, 'body': '<p>created</p>',
                      'subject': None, 'author_id': 102, 'email_from': None, 'date': '2026-11-02 03:00:00', 'record_name': 'EF-T-0001', 'create_uid': 11,
                      'create_date': '2026-11-02 03:00:00', 'write_uid': 11, 'write_date': '2026-11-02 03:00:00'}],
    'mail_tracking_value': [{'id': 1, 'mail_message_id': 1, 'field': 'state', 'old_value_char': 'Draft', 'new_value_char': 'Submitted'}],
    'mail_followers': [{'res_id': 1, 'partner_id': 101}],
}


class TestLegacyEApproval(TransactionCase):

    def setUp(self):
        super().setUp()
        if 'entertainment.request' not in self.env or 'tier.review' not in self.env:
            self.skipTest('kdvn_entertainment_procedures is not installed')
        self.data = deepcopy(FIXTURE)
        self.data.update(deepcopy(EA))
        data = self.data

        def fake(model, table, columns, where=None):
            if columns is None:
                return [dict(row) for row in data.get(table, [])]
            return [dict({c: None for c in columns}, **{k: v for k, v in row.items() if k in columns}) for row in data.get(table, [])]
        cls = type(self.env['kdvn.legacy.import'])
        for name, replacement in (('_legacy_rows', fake), ('_legacy_columns', lambda self_, table: set())):
            patcher = mock.patch.object(cls, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.imp = self.env['kdvn.legacy.import']

    def _run(self):
        out = self.imp.run(steps=STEPS)
        self.assertEqual(out['errors'], [], out['log'])
        return out

    def _request(self):
        return self.env['entertainment.request'].with_context(active_test=False).search([('name', '=', 'EF-T-0001')])

    def test_request_reviews_and_chatter_come_over_as_they_are(self):
        mails = self.env['mail.mail'].search_count([])
        activities = self.env['mail.activity'].search_count([])
        self._run()
        request = self._request()
        self.assertEqual(len(request), 1)
        self.assertEqual(request.state, 'submitted')
        self.assertEqual(request.employee_id.code, 'IA001')
        self.assertEqual(request.approval_progress, '1/2')
        self.assertEqual(request.create_date.strftime('%Y-%m-%d %H:%M'), '2026-11-02 03:00')
        self.assertEqual(request.create_uid.login, 'imp_staff')
        reviews = request.review_ids.sorted('sequence')
        self.assertEqual(reviews.mapped('status'), ['approved', 'pending'])
        self.assertEqual(reviews.mapped('definition_id.frontend_name'), ['1st Approval', '2nd Approval'], 'matched to the Odoo 19 definitions by model and name')
        self.assertTrue(reviews[1].can_review)
        self.assertEqual(reviews[1].reviewer_ids.mapped('login'), ['imp_boss'])
        self.assertEqual(reviews[0].done_by.login, 'imp_boss')
        self.assertEqual(request.validation_status, 'pending')
        message = self.env['mail.message'].search([('model', '=', 'entertainment.request'), ('res_id', '=', request.id), ('body', 'ilike', 'created')])
        self.assertEqual(len(message), 1)
        self.assertEqual(message.author_id.name, 'Staff One')
        self.assertEqual(message.tracking_value_ids.mapped('new_value_char'), ['Submitted'])
        self.assertIn(self.env['res.users'].search([('login', '=', 'imp_boss')]).partner_id, request.message_partner_ids)
        self.assertEqual(self.env['mail.mail'].search_count([]), mails, 'nobody is mailed')
        self.assertEqual(self.env['mail.activity'].search_count([]), activities, 'no activity is created')

    def test_the_boss_can_approve_the_imported_pending_step(self):
        self._run()
        request = self._request().with_user(self.env['res.users'].search([('login', '=', 'imp_boss')]))
        self.assertTrue(request.can_review)

    def test_second_run_does_not_duplicate(self):
        self._run()
        request = self._request()
        counts = (self.env['tier.review'].search_count([]), self.env['mail.message'].search_count([('model', '=', 'entertainment.request')]))
        self._run()
        self.assertEqual(self._request(), request)
        self.assertEqual((self.env['tier.review'].search_count([]), self.env['mail.message'].search_count([('model', '=', 'entertainment.request')])), counts)

    def test_a_change_in_odoo_12_reaches_odoo_19_without_reopening_the_reviews(self):
        self._run()
        self.data['entertainment_request'][0].update(state='approved', approval_progress='2/2')
        self.data['tier_review'][1].update(status='approved', can_review=False, done_by=10, reviewed_date='2026-11-04 05:00:00')
        self._run()
        request = self._request()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.review_ids.mapped('status'), ['approved', 'approved'])
        self.assertEqual(request.validation_status, 'validated')
        self.assertEqual(len(request.review_ids), 2, 'the engine did not open new reviews when the state changed')

    def test_old_request_with_amount_zero_is_copied(self):
        self.data['entertainment_request'][0].update(estimated_amount=0, state='approved')
        self._run()
        self.assertEqual(self._request().estimated_amount, 0)

    def test_a_review_without_a_matching_definition_is_listed(self):
        self.data['tier_definition'][1]['name'] = 'a step Odoo 19 does not have'
        out = self.imp.run(steps=STEPS)
        self.assertTrue(any('no Odoo 19 tier definition' in e for e in out['errors']), out['log'])
        self.assertEqual(len(self._request().review_ids), 1, 'the other review still came over')

    def test_check_step_reports_a_difference(self):
        self._run()
        self.data['entertainment_request'][0]['state'] = 'rejected'   # Odoo 12 moved on after the import
        out = self.imp.run(steps=['ea_check'])
        self.assertTrue(any('e-approval check' in e for e in out['errors']), out['log'])
