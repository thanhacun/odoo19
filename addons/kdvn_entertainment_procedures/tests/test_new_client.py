"""Duplicate, Request Date window, job list, and the placeholder client "New Client" (CC0000), with the client-list refresh tick
(mirror of Odoo 12 kderp_entertainment_procedures 12.0.2.8.0)."""
from unittest import mock

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import Form, TransactionCase


class TestNewClient(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user = self.env['res.users'].create({
            'name': 'Test applicant', 'login': 'tst_applicant', 'email': 'applicant@example.test',
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)]})
        self.emp = self.env['hr.employee'].create({'name': 'Test applicant', 'code': 'TST9350', 'working': True, 'user_id': self.user.id})
        self.job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-003', 'job_name': 'Test job', 'external_id': 4127, 'is_general_expense': False})
        budget = self.env['kderp.job.budget.cache'].create({'external_id': 3, 'budget_code': 'B3', 'name': 'Budget', 'job_id': self.job.id})
        Cache = self.env['kderp.customer.cache']
        self.placeholder = Cache.create({'external_id': 3000, 'name': 'NEW CLIENT', 'code': 'CC0000'})
        self.real = Cache.create({'external_id': 3001, 'name': 'Real Co', 'code': 'CC0900'})
        self.vals = {'budget_code_id': budget.id, 'employee_id': self.emp.id, 'place': 'Test Place', 'estimated_amount': 1500000,
                     'total_pax': 3, 'job_id': self.job.id, 'employee_ids': [(6, 0, [self.emp.id])]}
        self.Request = self.env['entertainment.request'].sudo()
        # One shipped-definition-free approval step of our own, so that a request can really be under validation
        self.env['tier.definition'].sudo().search([('model', '=', 'entertainment.request')]).write({'active': False})
        self.reviewer = self.env['res.users'].create({
            'name': 'Test reviewer', 'login': 'tst_reviewer', 'email': 'reviewer@example.test',
            'group_ids': [(6, 0, (self.env.ref('base.group_user') | self.env.ref('kdvn_e_approval.group_e_approval_admin')).ids)]})
        self.env['tier.definition'].sudo().create({
            'name': 'Step', 'frontend_name': 'Step', 'procedure_tag': 'entertainment.request',
            'model_id': self.env['ir.model']._get('entertainment.request').id, 'review_type': 'individual', 'reviewer_id': self.reviewer.id})
        Model = self.env['entertainment.request']
        for name in ('_notify_reviewers', '_notify_applicant'):
            patcher = mock.patch.object(type(Model), name, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _request(self, **extra):
        vals = dict(self.vals, guest_ids=[(6, 0, self.placeholder.ids)], guests='ACME Ltd, 1 Street')
        vals.update(extra)
        return self.Request.create(vals)

    # ---- placeholder client
    def test_placeholder_needs_a_description(self):
        with self.assertRaises(ValidationError):
            self._request(guests=False)
        self.assertTrue(self._request().has_new_client)

    def test_real_client_needs_no_description(self):
        req = self.Request.create(dict(self.vals, guest_ids=[(6, 0, self.real.ids)]))
        self.assertFalse(req.has_new_client)

    def test_sync_replaces_placeholder_even_under_validation(self):
        req = self._request()
        with mock.patch.object(type(req), '_notify_new_client_registrars', lambda self: None):
            req.action_submit()
        self.assertEqual((req.state, req.review_ids.mapped('status')), ('submitted', ['pending']))
        with self.assertRaises(ValidationError):                       # nobody edits the client by hand now
            req.write({'guest_ids': [(4, self.real.id)]})
        self.real.request_refs = req.name
        self.env['kderp.customer.cache']._clients_with_request_refs(self.real)
        self.assertEqual(req.guest_ids, self.real)
        self.assertEqual(req.guests, 'ACME Ltd, 1 Street')              # the description stays
        self.assertIn('was replaced by the registered client', req.message_ids[0].body)
        # a second client naming the same request changes nothing
        other = self.env['kderp.customer.cache'].create({'external_id': 3002, 'name': 'Other', 'code': 'CC0901', 'request_refs': req.name})
        self.env['kderp.customer.cache']._clients_with_request_refs(other)
        self.assertEqual(req.guest_ids, self.real)

    def test_sync_through_the_pull_pipeline(self):
        """The remote pull upserts the client with the request number in its Notes: the hook replaces the placeholder."""
        req = self._request()
        self.env['kderp.job.lookup'].execute_master_sync_pipeline(
            customers_data=[{'partner_id': 3050, 'name': 'Piped Co', 'code': 'CC0950', 'request_refs': req.name}], purge=False)
        self.assertEqual(req.guest_ids.mapped('code'), ['CC0950'])

    def test_registrars_get_the_request_number(self):
        req = self._request()
        sent = []
        self.env.user.email = 'registrar@example.com'
        with mock.patch.object(type(req), '_new_client_registrars', lambda self: self.env.user), \
                mock.patch.object(type(req), '_notify_send_email', lambda self, to, subject, body, **kw: sent.append((to, subject, body))):
            req._notify_new_client_registrars()
        self.assertEqual(len(sent), 1)
        self.assertIn(req.name, sent[0][1])
        self.assertIn(req.name, sent[0][2])
        self.assertIn('ACME Ltd', sent[0][2])

    def test_submit_tells_the_registrars_only_for_a_new_client(self):
        with mock.patch.object(type(self.Request), '_notify_new_client_registrars', autospec=True) as notify:
            req = self._request()
            req.action_submit()
            self.assertEqual(notify.call_count, 1)
        sent = []
        real_req = self.Request.create(dict(self.vals, guest_ids=[(6, 0, self.real.ids)]))
        with mock.patch.object(type(real_req), '_notify_send_email', lambda self, *a, **kw: sent.append(a)):
            real_req._notify_new_client_registrars()
        self.assertFalse(sent)

    def test_registrar_group_then_functional_controllers(self):
        req = self._request()
        controllers = self.env.ref('kdvn_entertainment_procedures.group_entertainment_request_functional_manager')
        registrars = self.env.ref('kdvn_entertainment_procedures.group_entertainment_new_client_registrar')
        registrars.sudo().user_ids = [(5, 0, 0)]
        controllers.sudo().user_ids = [(6, 0, self.reviewer.ids)]
        self.assertEqual(req._new_client_registrars(), self.reviewer)           # empty registrar group: the controllers
        registrars.sudo().user_ids = [(6, 0, self.user.ids)]
        self.assertEqual(req._new_client_registrars(), self.user)               # the registrar group wins

    def test_nobody_to_tell_is_said_in_the_chatter(self):
        req = self._request()
        with mock.patch.object(type(req), '_new_client_registrars', lambda self: self.env['res.users']):
            req._notify_new_client_registrars()
        self.assertIn('nobody could be told', req.message_ids[0].body)

    # ---- refresh the client list from the remote
    def test_refresh_tick(self):
        req = self.Request.new(dict(self.vals, refresh_clients=True))
        pull = type(self.env['kderp.remote.pull'])
        with mock.patch.object(pull, 'refresh_customers_now', return_value={'new': ['Beta Co'], 'skipped': False}):
            res = req._onchange_refresh_clients()
        self.assertFalse(req.refresh_clients)                           # unticks itself
        self.assertIn('Beta Co', res['warning']['message'])
        req.refresh_clients = True
        with mock.patch.object(pull, 'refresh_customers_now', return_value={'new': [], 'skipped': 'recent'}):
            self.assertIn('a moment ago', req._onchange_refresh_clients()['warning']['message'])
        req.refresh_clients = True
        with mock.patch.object(pull, 'refresh_customers_now', return_value={'new': [], 'skipped': False}):
            self.assertIn('No new client', req._onchange_refresh_clients()['warning']['message'])
        req.refresh_clients = True
        with mock.patch.object(pull, 'refresh_customers_now', side_effect=UserError('down')):
            self.assertIn('down', req._onchange_refresh_clients()['warning']['message'])
        req.refresh_clients = False
        self.assertIsNone(req._onchange_refresh_clients())

    # ---- Request Date
    def test_request_date_window(self):
        Request = self.Request
        with mock.patch.object(type(Request), '_request_date_open', lambda self: True):
            req = Request.create(dict(self.vals, guest_ids=[(6, 0, self.real.ids)], date_input='2026-03-01'))
            self.assertEqual(str(req.date_input), '2026-03-01')
            self.assertTrue(req.request_date_editable)
            self.assertIn('until 01/01/2027', req.request_date_note)
        with mock.patch.object(type(Request), '_request_date_open', lambda self: False):
            req2 = Request.create(dict(self.vals, guest_ids=[(6, 0, self.real.ids)], date_input='2026-03-01'))
            self.assertNotEqual(str(req2.date_input), '2026-03-01')
            before = req2.date_input
            req2.write({'date_input': '2026-01-01'})
            self.assertEqual(req2.date_input, before)
            self.assertFalse(req2.request_date_editable)
            self.assertFalse(req2.request_date_note)
            # the legacy import copies Odoo 12 dates as they are
            old = Request.with_context(kdvn_legacy_import=True).create(dict(self.vals, guest_ids=[(6, 0, self.real.ids)], date_input='2026-03-01'))
            self.assertEqual(str(old.date_input), '2026-03-01')
            old.with_context(kdvn_legacy_import=True).write({'date_input': '2026-03-05'})
            self.assertEqual(str(old.date_input), '2026-03-05')

    def test_request_date_deadline_parameter(self):
        Request = self.Request
        icp = self.env['ir.config_parameter'].sudo()
        self.assertEqual(str(Request._request_date_deadline()), '2027-01-01')           # default
        icp.set_param(Request.REQUEST_DATE_PARAM, '2020-01-01')
        self.assertEqual(str(Request._request_date_deadline()), '2020-01-01')
        self.assertFalse(Request._request_date_open())                                   # deadline passed: closed
        icp.set_param(Request.REQUEST_DATE_PARAM, '2999-12-31')
        self.assertTrue(Request._request_date_open())
        icp.set_param(Request.REQUEST_DATE_PARAM, 'nonsense')
        self.assertEqual(str(Request._request_date_deadline()), '2027-01-01')

    # ---- duplicate
    def test_duplicate_starts_as_a_fresh_draft(self):
        req = self._request()
        req.action_submit()
        req.write({'state': 'rejected'})
        self.assertTrue(req.review_ids)
        copy = req.copy()
        self.assertEqual(copy.state, 'draft')
        self.assertNotEqual(copy.name, req.name)
        self.assertEqual(copy.guest_ids, req.guest_ids)
        self.assertFalse(copy.review_ids)
        self.assertFalse(copy.remote_advance_code)

    def test_form_has_no_duplicate_false(self):
        arch = self.env['entertainment.request'].get_view(self.env.ref('kdvn_entertainment_procedures.view_entertainment_request_form').id)['arch']
        self.assertNotIn('duplicate="false"', arch)


class TestJobList(TransactionCase):
    """Jobs the applicant may pick: any role on a job, else the general job of the year of the Request Date."""

    def setUp(self):
        super().setUp()
        Job = self.env['kderp.job.lookup']
        self.fallback26 = Job.create({'job_no': 'HG00-26-1001', 'job_name': 'General 26', 'external_id': 9626, 'is_general_expense': True})
        self.fallback27 = Job.create({'job_no': 'HG00-27-1001', 'job_name': 'General 27', 'external_id': 9627, 'is_general_expense': True})
        self.user = self.env['res.users'].create({'name': 'Role user', 'login': 'tst_role', 'group_ids': [(6, 0, self.env.ref('base.group_user').ids)]})
        self.emp = self.env['hr.employee'].create({'name': 'Role user', 'code': 'TST9360', 'working': True, 'user_id': self.user.id})

    def _jobs(self, **vals):
        req = self.env['entertainment.request'].new(dict({'employee_id': self.emp.id, 'date_input': '2026-06-01'}, **vals))
        return req, req.allowed_job_ids._origin

    def test_no_role_gets_the_fallback_job_of_the_request_year(self):
        req, jobs = self._jobs()
        self.assertEqual(jobs, self.fallback26)
        req, jobs = self._jobs(date_input='2027-02-01')
        self.assertEqual(jobs, self.fallback27)
        req.date_input = '2028-02-01'                                  # no job of that year: nothing to pick
        self.assertFalse(req.allowed_job_ids._origin)

    def test_onchange_sets_the_fallback_job_and_follows_the_date(self):
        req = self.env['entertainment.request'].new({'employee_id': self.emp.id, 'date_input': '2026-06-01'})
        req._onchange_employee_id_routing()
        self.assertEqual(req.job_id, self.fallback26)
        req.date_input = '2027-03-01'
        req._onchange_employee_id_routing()
        self.assertEqual(req.job_id, self.fallback27)

    def test_every_role_opens_the_jobs_of_that_role(self):
        Job = self.env['kderp.job.lookup']
        roles = ('user_id', 'manager_id', 'jp_advisor_id', 'general_project_manager_id',
                 'area_manager_id', 'acting_project_manager_id', 'project_manager_ref')
        for i, role in enumerate(roles):
            job = Job.create({'job_no': 'TST-26-8%02d' % i, 'job_name': role, 'external_id': 9800 + i, role: self.user.id})
            req, jobs = self._jobs()
            self.assertIn(job, jobs, role)
            self.assertNotIn(self.fallback26, jobs, role)              # role jobs replace the fallback job (as in Odoo 12)
            job.unlink()

    def test_plain_user_reads_the_list(self):
        Job = self.env['kderp.job.lookup']
        job = Job.create({'job_no': 'TST-26-899', 'job_name': 'GM job', 'external_id': 9899, 'general_project_manager_id': self.user.id})
        M = self.env['entertainment.request'].with_user(self.user)
        req = M.new({'employee_id': self.emp.id, 'date_input': '2026-06-01'})
        self.assertEqual(req.allowed_job_ids._origin, job)
