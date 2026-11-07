"""A refusal comment stays after the request is reset to draft (mixin kderp.e.approval.mixin, tested on the reference procedure)."""
from unittest import mock

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestRefusalLog(TransactionCase):

    def setUp(self):
        super(TestRefusalLog, self).setUp()
        emp = self.env['hr.employee'].create({'name': 'Test applicant', 'code': 'TST9349', 'working': True})
        job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-002', 'job_name': 'Test job', 'external_id': 4126, 'is_general_expense': False})
        budget = self.env['kderp.job.budget.cache'].create({'external_id': 2, 'budget_code': 'B2', 'name': 'Budget', 'job_id': job.id})
        client = self.env['kderp.customer.cache'].create({'external_id': 2, 'name': 'Test client'})
        self.req = self.env['entertainment.request'].sudo().create({
            'budget_code_id': budget.id, 'guest_ids': [(6, 0, [client.id])], 'employee_id': emp.id, 'place': 'Test Place',
            'estimated_amount': 1500000, 'total_pax': 3, 'job_id': job.id, 'employee_ids': [(6, 0, [emp.id])]})
        # The root user may reset a request only through the admin group of the approval module
        self.env.ref('kdvn_e_approval.group_e_approval_admin').write({'user_ids': [(4, self.env.uid)]})
        # no message to anybody (Talk, email) from a test
        for name in ('_notify_reviewers', '_notify_applicant'):
            patcher = mock.patch.object(type(self.req), name, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.Log = self.env['kderp.approval.refusal']

    # ---- helpers
    def _submit(self):
        self.req.action_submit()
        reviews = self.req.review_ids
        self.assertTrue(reviews, "no approval rule matched this request: the tier definitions of the entertainment procedure are missing")
        return reviews

    def _reviewer(self):
        """A user who is the reviewer of the pending step (the test applicant has no manager chain, so the rules found nobody)."""
        user = self.env['res.users'].search([('login', '=', 'refusal_test_reviewer')])
        groups = [self.env.ref('base.group_user'), self.env.ref('kdvn_e_approval.group_e_approval_admin')]
        groups += [self.env.ref(g) for g in self.req._admin_groups]          # sees the request like a real approver
        return user or self.env['res.users'].create({
            'name': 'Refusal test reviewer', 'login': 'refusal_test_reviewer', 'email': 'refusal.reviewer@example.test', 'group_ids': [(6, 0, [g.id for g in groups])]})

    def _refuse(self, comment):
        pending = self.req.review_ids.filtered(lambda r: r.status == 'pending').sorted(lambda r: r.sequence)
        reviewer = self._reviewer()
        pending[0].sudo().write({'reviewer_ids': [(6, 0, [reviewer.id])]})
        self.req.with_user(reviewer.id).with_context(remote_rejection_comment=comment).reject_tier()
        self.assertEqual(self.req.state, 'rejected')
        return reviewer

    def _rows(self):
        return self.Log.sudo().search([('res_model', '=', 'entertainment.request'), ('res_id', '=', self.req.id)])

    def _last_note(self):
        return ' '.join(self.req.message_ids.mapped('body'))

    # ---- the life of a refusal
    def test_refusal_is_logged_when_it_happens(self):
        self._submit()
        reviewer = self._refuse('Too early, please wait for December')
        row = self._rows()
        self.assertEqual(len(row), 1)
        self.assertEqual((row.state, row.comment, row.refused_by_id), ('refused', 'Too early, please wait for December', reviewer))
        self.assertEqual(row.record_name, self.req.name)
        self.assertTrue(row.step and row.refused_date)
        self.assertNotIn('Refused earlier', self.req.approval_workflow_ribbon)           # now it shows the normal refusal note
        self.assertIn('Too early', self.req.approval_workflow_ribbon)

    def test_comment_survives_the_reset_to_draft_and_is_shown_on_the_request(self):
        self._submit()
        reviewer = self._refuse('Too early, please wait for December')
        self.req.action_reset_to_draft()
        self.assertEqual(self.req.state, 'draft')
        self.assertFalse(self.req.review_ids)                                            # the reviews are gone (as before)
        row = self._rows()
        self.assertEqual((row.state, row.reset_by_id.id, row.reset_to), ('reset', self.env.uid, 'Draft'))
        self.assertTrue(row.reset_date)
        self.assertEqual(row.comment, 'Too early, please wait for December')             # ... the comment is not
        # the request itself says it
        ribbon = self.req.approval_workflow_ribbon
        self.assertIn('Refused earlier', ribbon)
        self.assertIn('Too early, please wait for December', ribbon)
        self.assertIn(reviewer.name, ribbon)
        self.assertIn('Reset to Draft by', ribbon)
        # and the chatter has ONE short line (not the generic "unlocked" message)
        body = self._last_note()
        self.assertIn('Reset to <b>Draft</b> from <b>', body)
        self.assertIn('Refused by', body)
        self.assertIn(reviewer.name, body)
        self.assertIn('Too early, please wait for December', body)
        self.assertNotIn('unlocked and reset', body)

    def test_comment_text_is_escaped(self):
        self._submit()
        self._refuse('<script>alert(1)</script> & more')
        self.req.action_reset_to_draft()
        self.assertNotIn('<script>', self.req.approval_workflow_ribbon)
        self.assertNotIn('<script>', self._last_note())

    def test_note_disappears_when_the_request_is_approved(self):
        self._submit()
        self._refuse('Not yet')
        self.req.action_reset_to_draft()
        self.assertIn('Refused earlier', self.req.approval_workflow_ribbon)
        self.env.cr.execute("UPDATE entertainment_request SET state='approved' WHERE id=%s", (self.req.id,))
        self.req.invalidate_recordset(['state', 'approval_workflow_ribbon'])
        self.assertNotIn('Refused earlier', self.req.approval_workflow_ribbon)

    def test_second_refusal_keeps_the_history(self):
        self._submit()
        self._refuse('First reason')
        self.req.action_reset_to_draft()
        self._submit()
        self._refuse('Second reason')
        self.assertNotIn('Refused earlier', self.req.approval_workflow_ribbon)           # refused right now
        self.req.action_reset_to_draft()
        rows = self._rows()
        self.assertEqual(sorted(rows.mapped('comment')), ['First reason', 'Second reason'])
        self.assertEqual(set(rows.mapped('state')), {'reset'})
        ribbon = self.req.approval_workflow_ribbon
        self.assertIn('Second reason', ribbon)                                           # the latest one
        self.assertIn('(+1 more)', ribbon)

    def test_reset_of_a_request_that_was_not_refused_logs_nothing(self):
        self._submit()
        self.req.action_reset_to_draft()
        self.assertEqual(self.req.state, 'draft')
        self.assertFalse(self._rows())
        self.assertIn('unlocked and reset', self._last_note())                           # the old generic message
        self.assertNotIn('Refused earlier', self.req.approval_workflow_ribbon)

    def test_a_refusal_made_before_the_log_existed_is_still_kept_at_reset(self):
        self._submit()
        self._refuse('Old refusal')
        self._rows().unlink()                                                            # as if the log did not exist then
        self.req.action_reset_to_draft()
        row = self._rows()
        self.assertEqual((row.comment, row.state), ('Old refusal', 'reset'))

    def test_a_refusal_is_logged_once(self):
        self._submit()
        self._refuse('Once')
        self.req._refusal_log()
        self.req._refusal_log()
        self.assertEqual(len(self._rows()), 1)

    def test_deleting_the_request_deletes_its_log(self):
        self._submit()
        self._refuse('Gone with it')
        self.req.action_reset_to_draft()                       # the procedure only lets a draft without reviews be deleted
        self.assertTrue(self._rows())
        rid = self.req.id
        self.req.sudo().unlink()
        self.assertFalse(self.Log.sudo().search([('res_model', '=', 'entertainment.request'), ('res_id', '=', rid)]))

    # ---- who can read the list
    def test_only_approval_admins_read_the_list(self):
        self._submit()
        self._refuse('Private list')
        plain = self.env['res.users'].create({'name': 'Plain user', 'login': 'plain_refusal_user', 'email': 'plain.refusal@example.test', 'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(AccessError):
            self.Log.with_user(plain.id).search([])
        admin = self.env['res.users'].create({'name': 'Approval admin', 'login': 'admin_refusal_user', 'email': 'admin.refusal@example.test', 'group_ids': [(6, 0, [
            self.env.ref('base.group_user').id, self.env.ref('kdvn_e_approval.group_e_approval_admin').id])]})
        self.assertEqual(len(self.Log.with_user(admin.id).search([('res_id', '=', self.req.id)])), 1)

    # ---- old refusals rebuilt from the chatter (made before the log existed)
    def _old_refusal(self, who, comment=None, reset_by=None):
        """Post what OCA base_tier_validation (and our reset action) used to write in the chatter."""
        text = 'A review was rejected by %s.' % who + (' (%s)' % comment if comment else '')
        self.req.message_post(body='<p>%s</p>' % text)
        if reset_by is not None:
            self.req.message_post(body='<p>⚠️ Document unlocked and reset to Draft status by system administrator.</p>', author_id=reset_by.partner_id.id)

    def _old_world(self):
        """Three old refusals: reset, reset, and the last one still refused."""
        self.reviewer = self.env['res.users'].create({'name': 'Backfill Reviewer', 'login': 'backfill_reviewer', 'email': 'bf.reviewer@example.test'})
        self.resetter = self.env['res.users'].create({'name': 'Backfill Resetter', 'login': 'backfill_resetter', 'email': 'bf.resetter@example.test'})
        self._old_refusal('Backfill Reviewer', 'First reason\nsecond line (with brackets)', reset_by=self.resetter)
        self._old_refusal('Backfill Reviewer', None, reset_by=self.resetter)
        self._old_refusal('Unknown Person', 'Third reason')
        self.env.cr.execute("UPDATE entertainment_request SET state='rejected' WHERE id=%s", (self.req.id,))
        self.req.invalidate_recordset(['state'])

    def test_backfill_preview_writes_nothing(self):
        self._old_world()
        rep = self.Log.backfill_from_chatter(dry_run=True, records=self.req)
        self.assertEqual((rep['messages'], rep['created'], rep['reset'], rep['still_refused']), (3, 3, 2, 1))
        self.assertFalse(self._rows())
        self.assertEqual(len(rep['lines']), 3)

    def test_backfill_apply_rebuilds_the_rows(self):
        self._old_world()
        rep = self.Log.backfill_from_chatter(dry_run=False, records=self.req)
        self.assertEqual(rep['created'], 3)
        rows = self._rows().sorted('id')
        first, second, third = rows.sorted(lambda r: r.review_id, reverse=True)      # review_id = -message id: oldest first
        self.assertEqual(first.comment, 'First reason\nsecond line (with brackets)')   # comment with a newline and brackets kept whole
        self.assertEqual((first.state, first.reset_to, first.reset_by_id), ('reset', 'Draft', self.resetter))
        self.assertTrue(first.reset_date and first.refused_date)
        self.assertEqual((first.refused_by_name, first.refused_by_id), ('Backfill Reviewer', self.reviewer))
        self.assertFalse(second.comment)
        self.assertEqual(second.state, 'reset')
        self.assertEqual((third.state, third.refused_by_name, third.refused_by_id.id, third.reset_date), ('refused', 'Unknown Person', False, False))
        self.assertTrue(all(r.record_name == self.req.name for r in rows))

    def test_backfill_twice_adds_nothing(self):
        self._old_world()
        self.Log.backfill_from_chatter(dry_run=False, records=self.req)
        rep = self.Log.backfill_from_chatter(dry_run=False, records=self.req)
        self.assertEqual((rep['created'], rep['already_logged']), (0, 3))
        self.assertEqual(len(self._rows()), 3)

    def test_backfill_does_not_duplicate_a_refusal_already_logged(self):
        self._submit()
        self._refuse('Real refusal')                       # logged now AND posted in the chatter by OCA
        self.assertEqual(len(self._rows()), 1)
        rep = self.Log.backfill_from_chatter(dry_run=True, records=self.req)
        self.assertEqual((rep['created'], rep['already_logged']), (0, 1))
        self.Log.backfill_from_chatter(dry_run=False, records=self.req)
        self.assertEqual(len(self._rows()), 1)

    def test_backfill_preview_counts_a_live_refusal_as_known(self):
        self._submit()
        self._refuse('Live')
        self._rows().unlink()                              # a request refused before the log existed, reviews still there
        rep = self.Log.backfill_from_chatter(dry_run=True, records=self.req)
        self.assertEqual(rep['created'], 0)                # its exact row comes from the live review, not from the chatter text
        self.assertFalse(self._rows())
        self.Log.backfill_from_chatter(dry_run=False, records=self.req)
        row = self._rows()
        self.assertEqual((len(row), row.comment, row.state), (1, 'Live', 'refused'))

    def test_backfill_ignores_texts_that_are_not_refusals(self):
        self.req.message_post(body='<p>A review was rejected by </p>')
        rep = self.Log.backfill_from_chatter(dry_run=False, records=self.req)
        self.assertEqual((rep['messages'], rep['not_a_refusal'], rep['created']), (1, 1, 0))

    def test_old_refusal_without_a_reset_message_still_gives_a_note(self):
        self._old_refusal('Backfill Reviewer', 'Old reason')          # no reset message, the request is draft now
        self.Log.backfill_from_chatter(dry_run=False, records=self.req)
        row = self._rows()
        self.assertEqual((row.state, row.reset_by_id.id, row.reset_date), ('reset', False, False))
        ribbon = self.req.approval_workflow_ribbon
        self.assertIn('Old reason', ribbon)
        self.assertIn('Reset to Draft.', ribbon)                       # we do not know who or when: not invented
        self.assertNotIn('Reset to Draft by', ribbon)

    def test_backfill_menu_actions_report(self):
        self._old_world()
        before = self.Log.sudo().search_count([])
        preview = self.Log.action_backfill(apply=False)                 # the whole database (real data too)
        self.assertIn('preview', preview['context']['default_title'].lower())
        self.assertIn('Nothing was written', preview['context']['default_message'])
        self.assertIn('Would be added', preview['context']['default_message'])
        self.assertEqual(self.Log.sudo().search_count([]), before)
        done = self.Log.action_backfill(apply=True)
        self.assertIn('Added:', done['context']['default_message'])
        self.assertEqual(len(self._rows()), 3)                          # the three old refusals of this request were imported

    def test_backfill_finds_the_user_even_when_it_is_inactive(self):
        """The old reset notes were written by OdooBot, whose user is inactive."""
        bot = self.env['res.users'].create({'name': 'Inactive Resetter', 'login': 'inactive_resetter', 'email': 'inactive.resetter@example.test'})
        self._old_refusal('Backfill Reviewer', 'Reason', reset_by=bot)
        bot.write({'active': False})                          # like OdooBot: the user is archived, the old message stays
        self.Log.backfill_from_chatter(dry_run=False, records=self.req)
        row = self._rows()
        self.assertEqual((row.state, row.reset_by_id.id), ('reset', bot.id))
        self.assertIn('Reset to Draft by', self.req.approval_workflow_ribbon)
