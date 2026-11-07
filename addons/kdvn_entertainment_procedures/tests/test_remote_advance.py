"""Advance request on the remote server: every remote call is faked, nothing leaves this database."""
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.kdvn_remote_integration.models.remote_client import RemoteNotLive

CLIENT = 'odoo.addons.kdvn_remote_integration.models.remote_client.KderpRemoteClient'
CANDIDATES = 'odoo.addons.kdvn_entertainment_procedures.models.remote_candidates'

G_INPUT, G_ADMIN, G_MANAGE, G_TEAM, G_SUBMIT, G_ADV_ADMIN = 70, 77, 78, 80, 71, 72


def user(uid, name, emp, groups, active=True, loc=(2, 'Ha Noi Office')):
    return dict(id=uid, name=name, login=name.lower().replace(' ', '-'), active=active, location_user_id=list(loc) if loc else False,
                employee_ids=list(emp), group_ids=list(groups))


class FakeRemote(object):
    """Answers the reads of the feature; records creates and which history reads were made.

    `live=False` raises RemoteNotLive on create like the real client."""

    def __init__(self, live=True, admin_ids=(11,), pm_user=(900, 'Project Manager'), users=None, employees=None, job_hist=(), app_hist=(), pm_hist=(), office_hist=(),
                 existing=None, taken=0):
        self.live, self.existing, self.taken = live, existing, taken
        self.created, self.calls, self.hist_calls = [], [], []
        self.admin_ids = list(admin_ids)
        self.pm_user = list(pm_user) if pm_user else False
        self.users = users if users is not None else {u['id']: u for u in (
            user(11, 'Admin A', [501], [G_INPUT, G_ADMIN]),
            user(21, 'Hist B', [601], [G_INPUT, G_TEAM]),
            user(22, 'Hist C', [602], [G_INPUT, G_ADMIN]),
            user(31, 'Applicant', [2], []))}
        self.employees = employees if employees is not None else {
            601: dict(id=601, name='Hist B', code='S0601', user_id=[21, 'Hist B']),
            602: dict(id=602, name='Hist C', code='S0602', user_id=[22, 'Hist C']),
            603: dict(id=603, name='No User', code='S0603', user_id=False)}
        self.hist = {'job': list(job_hist), 'applicant': list(app_hist), 'pm': list(pm_hist), 'office': list(office_hist)}

    def _history(self, domain):
        fields_ = [d[0] for d in domain]
        if 'account_analytic_id.user_id' in fields_:
            kind = 'pm'
        elif 'account_analytic_id' in fields_:
            kind = 'job'
        elif 'user_id' in fields_:
            kind = 'applicant'
        else:
            kind = 'office'
        self.hist_calls.append(kind)
        return [{'user_input': [e, 'x'], '__count': n} for e, n in self.hist[kind]]

    def __call__(self, model, method, args=None, kwargs=None):
        args, kwargs = args or [], kwargs or {}
        self.calls.append((model, method))
        if model == 'account.analytic.account':
            return [{'id': 4125, 'code': 'TST-26-001', 'site_admin_users': list(self.admin_ids), 'user_id': self.pm_user}]
        if model == 'ir.model.data':
            return [{'module': 'kderp_advance_payment', 'name': 'group_kderp_advance_management_menu_user_input', 'res_id': G_INPUT},
                    {'module': 'kderp_rule', 'name': 'group_kderp_adv_site_admin', 'res_id': G_ADMIN},
                    {'module': 'kderp_rule', 'name': 'group_rule_adv_manage_location', 'res_id': G_MANAGE},
                    {'module': 'kderp_advance_payment', 'name': 'group_kderp_advance_workflow', 'res_id': G_SUBMIT},
                    {'module': 'kderp_advance_payment', 'name': 'group_kderp_advance_admin', 'res_id': G_ADV_ADMIN}]
        if model == 'res.groups':
            return [{'id': G_TEAM, 'name': 'Filter Advance Payment By Location - TLIP 1 Input'}]
        if model == 'res.users':
            return [dict(self.users[i]) for i in args[0] if i in self.users]
        if model == 'kderp.base.code':
            return [{'id': 2, 'code': 'H'}, {'id': 9, 'code': 'all'}]
        if model == 'hr.employee' and method == 'search_read':
            return [{'id': 2, 'name': 'Applicant', 'bank_name': 'VCB', 'bank_account_number': '123', 'bank_account_name': 'APP',
                     'user_id': [31, 'Applicant']}]
        if model == 'hr.employee' and method == 'read':
            return [dict(self.employees[i]) for i in args[0] if i in self.employees]
        if model == 'res.currency':
            return [{'id': 23}]
        if model == 'ir.sequence':
            return [{'code_next': 'ADH26-1348-%02d' % (1 + self.taken)}]
        if model == 'kderp.advance.payment' and method == 'read_group':
            return self._history(args[0])
        if model == 'kderp.advance.payment' and method == 'search_read':
            return [self.existing] if self.existing else []
        if model == 'kderp.advance.payment' and method == 'create':
            if not self.live:
                raise RemoteNotLive('dry run')
            if self.taken:
                self.taken -= 1   # first attempt: number taken in between
                raise UserError('Advance Number must be unique !')
            self.created.append(args[0])
            return 900
        if model == 'kderp.advance.payment' and method == 'read':
            return [{'code': self.created[-1]['code']}]
        raise AssertionError('unexpected remote call %s.%s' % (model, method))


class TestRemoteAdvance(TransactionCase):

    def setUp(self):
        super(TestRemoteAdvance, self).setUp()
        emp = self.env['hr.employee'].create({'name': 'Test applicant', 'code': 'TST9348', 'working': True})
        self.job = self.env['kderp.job.lookup'].create({'job_no': 'TST-26-001', 'job_name': 'Test job', 'external_id': 4125, 'is_general_expense': False})
        budget = self.env['kderp.job.budget.cache'].create({'external_id': 1, 'budget_code': 'B1', 'name': 'Budget', 'job_id': self.job.id})
        client = self.env['kderp.customer.cache'].create({'external_id': 1, 'name': 'Test client'})
        self.req = self.env['entertainment.request'].sudo().create({
            'budget_code_id': budget.id, 'guest_ids': [(6, 0, [client.id])],
            'employee_id': emp.id, 'place': 'Test Place', 'estimated_amount': 1500000, 'total_pax': 3,
            'job_id': self.job.id, 'employee_ids': [(6, 0, [emp.id])]})
        self._set_state('approved')
        self.admin = {'remote_user_id': 11, 'employee_id': 501, 'location_id': 2, 'location_code': 'H', 'name': 'Admin A', 'login': 'admin-a',
                      'team': '', 'why': 'Site admin of this job', 'ok': True, 'reason': ''}

    def _set_state(self, state):
        # The approval workflow locks the state field: set it directly, this test is not about approving
        self.env.cr.execute("UPDATE entertainment_request SET state=%s WHERE id=%s", (state, self.req.id))
        self.req.invalidate_recordset(['state'])

    def _run(self, remote, fn):
        with mock.patch(CLIENT + '.execute', side_effect=lambda model, method, args=None, kwargs=None, **kw: remote(model, method, args, kwargs)):
            return fn()

    def _candidates(self, remote):
        return self._run(remote, self.req._remote_input_candidates)

    def _wizard(self, remote):
        wiz = self.env['entertainment.advance.wizard'].create({'request_id': self.req.id})
        self._run(remote, wiz._load_candidates)
        return wiz

    # ------------------------------------------------------------------ eligibility
    def test_eligibility_user_input_is_enough(self):
        users = {u['id']: u for u in (
            user(11, 'Site admin', [501], [G_INPUT, G_ADMIN]),
            user(12, 'Team', [502], [G_INPUT, G_TEAM]),
            user(13, 'Manage a location', [503], [G_INPUT, G_MANAGE]),
            user(14, 'Advance admin', [504], [G_INPUT, G_SUBMIT, G_ADV_ADMIN]),
            user(15, 'Only user input', [505], [G_INPUT]),
            user(31, 'Applicant', [2], []))}
        res = {c['name']: c for c in self._candidates(FakeRemote(admin_ids=[11, 12, 13, 14, 15], users=users))}
        for name in ('Site admin', 'Team', 'Manage a location', 'Advance admin', 'Only user input'):
            self.assertTrue(res[name]['ok'], name)
            self.assertFalse(res[name]['reason'], name)
        # the role is shown for the discussion (information only)
        self.assertEqual(res['Site admin']['roles'], 'Site admin')
        self.assertEqual(res['Team']['roles'], 'Team TLIP 1 Input')
        self.assertEqual(res['Manage a location']['roles'], 'Manage a Location')
        self.assertEqual(res['Advance admin']['roles'], 'Advance Cash Admin')          # Submit is implied, not repeated
        self.assertEqual(res['Only user input']['roles'], '')

    def test_eligibility_what_still_blocks(self):
        users = {u['id']: u for u in (
            user(13, 'No input right', [503], [G_ADMIN]),
            user(15, 'No employee', [], [G_INPUT, G_ADMIN]),
            user(16, 'Global', [506], [G_INPUT, G_ADMIN], loc=(9, 'Global')),
            user(17, 'Inactive', [507], [G_INPUT, G_ADMIN], active=False),
            user(18, 'No location', [508], [G_INPUT, G_ADMIN], loc=None),
            user(31, 'Applicant', [2], []))}
        res = {c['name']: c for c in self._candidates(FakeRemote(admin_ids=[13, 15, 16, 17, 18], users=users))}
        self.assertEqual(len(res), 5)
        for name in res:
            self.assertFalse(res[name]['ok'], name)
            self.assertTrue(res[name]['reason'], name)
        self.assertIn("'User Input'", res['No input right']['reason'])
        self.assertIn('code letter', res['Global']['reason'])                         # Global (letter 'all') stays out for now

    # ------------------------------------------------------------------ ranking
    def test_site_admins_first_then_history_each_with_its_reason(self):
        remote = FakeRemote(admin_ids=[11], job_hist=[(601, 5)], app_hist=[(601, 2), (602, 1)])
        res = self._candidates(remote)
        self.assertEqual([c['name'] for c in res], ['Admin A', 'Hist B', 'Hist C'])
        self.assertTrue(res[0]['is_admin'])
        self.assertEqual([c['suggested'] for c in res], [True, False, False])      # first person who can process it
        b = res[1]
        self.assertIn('Entered 5 advance request(s) on this job', b['why'])
        self.assertIn("usually enters this applicant's requests (2", b['why'])
        self.assertEqual(b['team'], 'TLIP 1 Input')
        self.assertEqual((b['location_code'], b['employee_id']), ('H', 601))
        self.assertEqual(res[0]['why'], 'Site admin of this job')
        self.assertEqual(remote.hist_calls, ['job', 'applicant'])                  # enough people: PM and office are not read

    def test_most_frequent_first_and_same_person_merged(self):
        res = self._candidates(FakeRemote(admin_ids=[], job_hist=[(602, 1), (601, 7)], app_hist=[(602, 4)]))
        self.assertEqual([c['name'] for c in res], ['Hist B', 'Hist C'])           # job history by count, then the applicant's
        self.assertIn('this job', res[1]['why'])
        self.assertIn("applicant's", res[1]['why'])                                # Hist C appears once with both reasons

    def test_job_admins_are_ranked_by_history(self):
        users = {u['id']: u for u in (user(11, 'Admin A', [501], [G_INPUT, G_ADMIN]), user(12, 'Admin Z', [502], [G_INPUT, G_ADMIN]),
                                      user(31, 'Applicant', [2], []))}
        res = self._candidates(FakeRemote(admin_ids=[11, 12], users=users, job_hist=[(502, 3)]))
        self.assertEqual([c['name'] for c in res], ['Admin Z', 'Admin A'])
        self.assertTrue(res[0]['suggested'])

    def test_pm_and_office_history_only_when_the_list_is_short(self):
        remote = FakeRemote(admin_ids=[], office_hist=[(601, 9)])
        res = self._candidates(remote)
        self.assertEqual(remote.hist_calls, ['job', 'applicant', 'pm', 'office'])
        self.assertEqual([c['name'] for c in res], ['Hist B'])
        self.assertIn("applicant's office", res[0]['why'])

    def test_first_row_that_cannot_process_is_not_suggested(self):
        users = {u['id']: u for u in (user(21, 'Hist B', [601], [G_INPUT, G_TEAM], active=False), user(22, 'Hist C', [602], [G_INPUT, G_ADMIN]),
                                      user(31, 'Applicant', [2], []))}
        res = self._candidates(FakeRemote(admin_ids=[], users=users, job_hist=[(601, 9), (602, 1)]))
        self.assertEqual([(c['name'], c['ok'], c['suggested']) for c in res], [('Hist B', False, False), ('Hist C', True, True)])
        self.assertEqual(res[0]['reason'], 'user is inactive')

    def test_employee_without_user_is_listed_but_not_offered(self):
        res = self._candidates(FakeRemote(admin_ids=[], job_hist=[(603, 4)]))
        self.assertEqual((res[0]['name'], res[0]['ok'], res[0]['suggested']), ('No User', False, False))
        self.assertIn('no user', res[0]['reason'])

    def test_history_rows_are_capped_but_job_admins_never(self):
        extra = [user(200 + i, 'H%d' % i, [800 + i], [G_INPUT, G_ADMIN]) for i in range(6)]
        users = {u['id']: u for u in [user(11, 'Admin A', [501], [G_INPUT, G_ADMIN]), user(12, 'Admin B', [502], [G_INPUT, G_ADMIN]),
                                      user(31, 'Applicant', [2], [])] + extra}
        emps = {800 + i: dict(id=800 + i, name='H%d' % i, code='S08%02d' % i, user_id=[200 + i, 'H%d' % i]) for i in range(6)}
        res = self._candidates(FakeRemote(admin_ids=[11, 12], users=users, employees=emps,
                                          job_hist=[(800, 9), (801, 8), (802, 7)], app_hist=[(803, 9), (804, 8), (805, 7)]))
        self.assertEqual(len(res), 6)                                              # 2 admins + 4 history rows
        self.assertEqual([c['name'] for c in res[:2]], ['Admin A', 'Admin B'])
        many = {u['id']: u for u in [user(100 + i, 'U%d' % i, [700 + i], [G_INPUT, G_ADMIN]) for i in range(9)] + [user(31, 'Applicant', [2], [])]}
        self.assertEqual(len(self._candidates(FakeRemote(admin_ids=list(range(100, 109)), users=many))), 9)

    # ------------------------------------------------------------------ the dialog
    def test_job_without_site_admin_is_not_an_error_any_more(self):
        wiz = self._wizard(FakeRemote(admin_ids=[], job_hist=[(601, 4)], app_hist=[(602, 2)]))
        self.assertEqual(len(wiz.line_ids), 2)
        self.assertEqual(wiz.admin_line_id.name, 'Hist B')                         # suggested = preselected
        self.assertIn('no site admin', wiz.hint)
        self.assertIn('TST-26-001', wiz.hint)
        self.assertNotIn('setup mistake', wiz.hint)
        self.assertIn('Why this person', wiz.preview)
        self.assertIn('Entered 4 advance request(s) on this job', wiz.preview)

    def test_note_explains_how_people_were_suggested(self):
        wiz = self._wizard(FakeRemote(admin_ids=[], job_hist=[(601, 4)], app_hist=[(602, 2)]))
        how = wiz.how
        self.assertIn('How these people were suggested', how)
        self.assertIn('none', how)                                                   # no job site admin
        self.assertIn('4 advance request(s) entered by 1 person(s)', how)                 # this job
        self.assertIn('2 advance request(s) entered by 1 person(s)', how)                 # this applicant
        self.assertIn('Applicant', how)
        self.assertIn('Project Manager', how)                                        # fewer than 3 people: PM was read ...
        self.assertIn('Ha Noi Office', how)                                          # ... and the office too
        self.assertIn('User Input', how)

    def test_note_says_when_pm_and_office_were_not_needed(self):
        wiz = self._wizard(FakeRemote(admin_ids=[11], job_hist=[(601, 5)], app_hist=[(602, 1)]))
        self.assertEqual(wiz.how.count('not read (enough people were already found)'), 2)
        self.assertIn('1 found, all are listed', wiz.how)

    def test_note_says_when_the_job_has_no_project_manager(self):
        wiz = self._wizard(FakeRemote(admin_ids=[], pm_user=False, job_hist=[(601, 1)]))
        self.assertIn('the job has none on the remote server', wiz.how)

    def test_job_with_site_admin_has_no_hint(self):
        wiz = self._wizard(FakeRemote(admin_ids=[11]))
        self.assertEqual(wiz.admin_line_id.name, 'Admin A')
        self.assertFalse(wiz.hint)

    def test_nobody_found_blocks_and_informs(self):
        wiz = self._wizard(FakeRemote(admin_ids=[]))
        self.assertFalse(wiz.line_ids)
        self.assertFalse(wiz.admin_line_id)
        self.assertIn('Nobody could be suggested', wiz.hint)
        self.assertIn('TST-26-001', wiz.hint)
        with self.assertRaises(UserError):       # nothing chosen -> no create
            wiz.action_create()

    def test_nobody_can_process_blocks_and_informs(self):
        users = {u['id']: u for u in (user(13, 'No input right', [503], [G_ADMIN]), user(31, 'Applicant', [2], []))}
        wiz = self._wizard(FakeRemote(admin_ids=[13], users=users))
        self.assertEqual(len(wiz.line_ids), 1)
        self.assertFalse(wiz.admin_line_id)
        self.assertIn('None of the people found', wiz.hint)

    def test_wrong_job_number_blocked(self):
        self.job.write({'job_no': 'OTHER-26-999'})
        with self.assertRaises(UserError):
            self._candidates(FakeRemote())

    # ------------------------------------------------------------------ preparing and creating
    def test_prepare_values(self):
        prep = self._run(FakeRemote(), lambda: self.req._remote_prepare_advance(self.admin))
        v = prep['vals']
        self.assertEqual((v['user_id'], v['user_input'], v['location_id'], v['account_analytic_id']), (2, 501, 2, 4125))
        self.assertEqual(v['code'], 'ADH26-1348-01')
        self.assertIsInstance(v['date'], str)
        self.assertIn('EF-', v['name'])
        self.assertEqual(v['advance_line'][0][2]['amount'], 1500000)
        self.assertEqual(v['bank_name'], 'VCB')

    def test_dry_run_writes_nothing(self):
        remote = FakeRemote(live=False)
        with self.assertRaises(RemoteNotLive):
            self._run(remote, lambda: self.req._remote_create_advance(self.admin))
        self.assertFalse(self.req.remote_advance_code)
        self.assertFalse(remote.created)

    def test_create_stores_result_once_and_says_why(self):
        remote = FakeRemote()
        admin = dict(self.admin, team='TLIP 1 Input', why='Entered 5 advance request(s) on this job')
        code, adopted = self._run(remote, lambda: self.req._remote_create_advance(admin))
        self.assertEqual((code, adopted, len(remote.created)), ('ADH26-1348-01', False, 1))
        self.assertEqual((self.req.remote_advance_id, self.req.remote_advance_code), (900, code))
        body = self.req.message_ids[:1].body
        self.assertIn('Input user to continue', body)
        self.assertIn('TLIP 1 Input', body)
        self.assertIn('Chosen because: Entered 5 advance request(s) on this job', body)
        with self.assertRaises(UserError):     # second click is blocked
            self._run(remote, lambda: self.req._remote_create_advance(self.admin))

    def test_existing_advance_is_adopted_not_duplicated(self):
        remote = FakeRemote(existing={'id': 321, 'code': 'ADH26-1348-07'})
        code, adopted = self._run(remote, lambda: self.req._remote_create_advance(self.admin))
        self.assertEqual((code, adopted, remote.created), ('ADH26-1348-07', True, []))
        self.assertEqual(self.req.remote_advance_id, 321)

    def test_number_taken_in_between_is_reread_once(self):
        remote = FakeRemote(taken=1)
        code, adopted = self._run(remote, lambda: self.req._remote_create_advance(self.admin))
        self.assertEqual(code, 'ADH26-1348-01')      # fake sequence moved to 01 after the retry (taken -> 0)
        self.assertEqual(len(remote.created), 1)

    def test_only_approved_and_not_twice(self):
        self._set_state('submitted')
        with self.assertRaises(UserError):
            self.req._check_can_create_remote_advance()
