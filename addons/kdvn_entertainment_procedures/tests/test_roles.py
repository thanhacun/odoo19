"""The request form and its actions as the roles that use them: plain staff, a PM, a GM and a New Client Registrar
(what the web client runs: get_views, onchange of a new record, read of the form, copy, submit)."""
from unittest import mock

from odoo.addons.kdvn_base.tests.ui_calls import run
from odoo.tests.common import TransactionCase


class TestRoles(TransactionCase):

    def setUp(self):
        super().setUp()
        user_group = self.env.ref('base.group_user')
        Users = self.env['res.users']
        self.users = {}
        for index, (key, extra) in enumerate((('plain', self.env['res.groups']), ('pm', self.env['res.groups']), ('gm', self.env['res.groups']),
                           ('registrar', self.env.ref('kdvn_entertainment_procedures.group_entertainment_new_client_registrar')))):
            user = Users.create({'name': 'Role %s' % key, 'login': 'tst_ent_%s' % key, 'email': '%s@example.test' % key,
                                 'group_ids': [(6, 0, (user_group | extra).ids)]})
            emp = self.env['hr.employee'].create({'name': 'Role %s' % key, 'code': 'TST94%02d' % index, 'working': True, 'user_id': user.id})
            self.users[key] = (user, emp)
        Job = self.env['kderp.job.lookup']
        self.hg = Job.create({'job_no': 'HG00-26-1001', 'job_name': 'General', 'external_id': 9101, 'is_general_expense': True})
        self.pm_job = Job.create({'job_no': 'TST-26-901', 'job_name': 'PM job', 'external_id': 9102, 'user_id': self.users['pm'][0].id})
        self.gm_job = Job.create({'job_no': 'TST-26-902', 'job_name': 'GM job', 'external_id': 9103, 'general_project_manager_id': self.users['gm'][0].id})
        Budget = self.env['kderp.job.budget.cache']
        self.budgets = {job: Budget.create({'external_id': 9100 + i, 'budget_code': 'B%s' % i, 'name': 'B', 'job_id': job.id})
                        for i, job in enumerate((self.hg, self.pm_job, self.gm_job))}
        Cache = self.env['kderp.customer.cache']
        self.placeholder = Cache.create({'external_id': 9200, 'name': 'NEW CLIENT', 'code': 'CC0000'})
        self.real = Cache.create({'external_id': 9201, 'name': 'Real Co', 'code': 'CC0901'})
        self.env['tier.definition'].sudo().search([('model', '=', 'entertainment.request')]).write({'active': False})
        self.reviewer = Users.create({'name': 'Role reviewer', 'login': 'tst_ent_rev', 'email': 'rev@example.test', 'group_ids': [(6, 0, user_group.ids)]})
        self.env['tier.definition'].sudo().create({
            'name': 'Step', 'frontend_name': 'Step', 'procedure_tag': 'entertainment.request',
            'model_id': self.env['ir.model']._get('entertainment.request').id, 'review_type': 'individual', 'reviewer_id': self.reviewer.id})
        Model = self.env['entertainment.request']
        for name in ('_notify_reviewers', '_notify_applicant'):
            patcher = mock.patch.object(type(Model), name, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _form_spec(self, M):
        """Every field of the form view, as the client reads it."""
        from lxml import etree
        arch = M.get_view(self.env.ref('kdvn_entertainment_procedures.view_entertainment_request_form').id)['arch']
        names = {n.get('name') for n in etree.fromstring(arch).iter('field') if n.get('name') in M._fields}
        return {n: ({'fields': {'display_name': {}}} if M._fields[n].type in ('many2one', 'many2many', 'one2many') else {}) for n in names}

    def _vals(self, key, job, client, **extra):
        user, emp = self.users[key]
        vals = {'employee_id': emp.id, 'job_id': job.id, 'budget_code_id': self.budgets[job].id, 'place': 'Place', 'estimated_amount': 1000000,
                'total_pax': 2, 'employee_ids': [(6, 0, [emp.id])], 'guest_ids': [(6, 0, client.ids)]}
        vals.update(extra)
        return vals

    def test_screens_open_for_every_role(self):
        for key in self.users:
            M = self.env['entertainment.request'].with_user(self.users[key][0])
            M.create(self._vals(key, self.hg if key in ('plain', 'registrar') else (self.pm_job if key == 'pm' else self.gm_job), self.real))
            failures = run(self.env, prefixes=('kdvn_entertainment_procedures',), login='tst_ent_%s' % key)
            self.assertEqual(failures, [], key)

    def test_new_form_and_job_list_per_role(self):
        expected = {'plain': self.hg, 'registrar': self.hg, 'pm': self.pm_job, 'gm': self.gm_job}
        for key, jobs in expected.items():
            user = self.users[key][0]
            M = self.env['entertainment.request'].with_user(user)
            spec = self._form_spec(M)
            res = M.onchange({}, [], spec)                          # the new form, as the client opens it
            allowed = res['value'].get('allowed_job_ids')
            self.assertTrue(allowed is not None, key)
            self.assertEqual(M.default_get(['employee_id'])['employee_id'], self.users[key][1].id)
            req = M.new({'employee_id': self.users[key][1].id})
            self.assertEqual(req.allowed_job_ids._origin, jobs, key)
            # the Request Date field and its note are readable and say the window is open until the date
            self.assertTrue(req.request_date_editable)
            self.assertIn('01/01/2027', req.request_date_note)

    def test_plain_user_request_lifecycle(self):
        user, emp = self.users['plain']
        M = self.env['entertainment.request'].with_user(user)
        req = M.create(self._vals('plain', self.hg, self.real))
        data = req.web_read(self._form_spec(M))[0]
        self.assertEqual(data['state'], 'draft')
        self.assertTrue(data['request_date_editable'])
        self.assertEqual(data['allowed_job_ids'][0]['display_name'], self.hg.display_name)
        # duplicate (the Action menu of the form)
        copy = req.copy()
        self.assertEqual((copy.state, copy.create_uid), ('draft', user))
        self.assertNotEqual(copy.name, req.name)
        # the Request Date can be changed in the window, and the job follows the year
        req.write({'date_input': '2026-03-02'})
        self.assertEqual(str(req.date_input), '2026-03-02')
        # a new client: the placeholder needs a description; the applicant's submit tells the registrars
        new = M.create(self._vals('plain', self.hg, self.placeholder, guests='ACME Ltd, 1 Street'))
        sent = []
        with mock.patch.object(type(new), '_notify_send_email', lambda self, to, subject, body, **kw: sent.append((to, subject))):
            new.action_submit()
        self.assertEqual(new.state, 'submitted')
        self.assertTrue(new.has_new_client)
        # nobody in the registrar group but the registrar user: it is the one told
        self.assertEqual(sent, [('registrar@example.test', 'New client to register: %s' % new.name)])
        # a plain applicant still reads the submitted request (the replaced client comes from the system)
        self.real.sudo().request_refs = new.name
        self.env['kderp.customer.cache']._clients_with_request_refs(self.real)
        new.invalidate_recordset()
        self.assertEqual(new.guest_ids, self.real)
        new.web_read(self._form_spec(M))
        # the tick to refresh the client list, as the applicant
        form = M.new({'employee_id': emp.id, 'refresh_clients': True})
        with mock.patch.object(type(self.env['kderp.remote.pull']), 'refresh_customers_now', return_value={'new': ['Beta Co'], 'skipped': False}):
            res = form._onchange_refresh_clients()
        self.assertIn('Beta Co', res['warning']['message'])
        # and through the onchange call the web client makes when the box is ticked
        spec = self._form_spec(M)
        with mock.patch.object(type(self.env['kderp.remote.pull']), 'refresh_customers_now', return_value={'new': [], 'skipped': False}):
            out = M.onchange({'employee_id': emp.id, 'refresh_clients': True}, ['refresh_clients'], spec)
        self.assertIn('No new client', out['warning']['message'])
        self.assertIs(out['value'].get('refresh_clients'), False)           # the box unticks itself

    def test_pm_and_gm_pick_their_jobs_and_submit(self):
        for key, job in (('pm', self.pm_job), ('gm', self.gm_job)):
            user = self.users[key][0]
            M = self.env['entertainment.request'].with_user(user)
            req = M.create(self._vals(key, job, self.real))
            req.action_submit()
            self.assertEqual(req.state, 'submitted', key)
            copy = req.copy()
            self.assertEqual(copy.state, 'draft')
            self.assertFalse(copy.review_ids)

    def test_registrar_is_told_and_replaced_request_stays_the_applicants(self):
        user, emp = self.users['registrar']
        M = self.env['entertainment.request'].with_user(user)
        req = M.create(self._vals('registrar', self.hg, self.placeholder, guests='Client as described'))
        sent = []
        with mock.patch.object(type(req), '_notify_send_email', lambda self, to, subject, body, **kw: sent.append((to, body))):
            req.action_submit()
        self.assertEqual(len(sent), 1)
        self.assertIn('Client as described', sent[0][1])
        self.assertIn(req.name, sent[0][1])
