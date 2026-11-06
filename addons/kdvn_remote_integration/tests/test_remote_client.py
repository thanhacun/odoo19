"""The remote server client: which login does what, dry run, live switches, settings. No call leaves this database."""
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.kdvn_remote_integration.models.remote_client import RemoteNotLive

CLIENT = 'odoo.addons.kdvn_remote_integration.models.remote_client.KderpRemoteClient'
UIDS = {'rd': 11, 'wr': 22}


class TestRemoteClient(TransactionCase):

    def setUp(self):
        super().setUp()
        self.icp = self.env['ir.config_parameter'].sudo()
        for k, v in (('url', 'http://remote.test:8169/'), ('db', 'db1'), ('reader_login', 'rd'), ('reader_password', 'rdpw'),
                     ('writer_login', 'wr'), ('writer_password', 'wrpw')):
            self.icp.set_param('kderp_remote.' + k, v)
        for task in ('advance', 'staff_location'):
            self.icp.set_param('kderp_remote.live.' + task, 'False')
        self.client = self.env['kderp.remote.client']
        self.client._uids.clear()
        self.calls = []

    def _fake_rpc(self, _self, cfg, service, method, args):
        self.calls.append({'login': cfg['login'], 'service': service, 'method': method, 'args': args})
        if method == 'login':
            return UIDS.get(args[1], 0)
        if method == 'version':
            return {'server_version': '12.0'}
        if method == 'execute_kw':
            model, meth = args[3], args[4]
            if meth == 'read':
                return [{'id': args[1], 'login': cfg['login'], 'location_user_id': [2, 'Ha Noi Office']}]
            if meth == 'check_access_rights':
                op = args[5][0]
                # the Reader is a bit too strong on purpose (can write staff locations), the Writer can do everything
                return cfg['login'] == 'wr' or op == 'read' or (model == 'kderp.hr.employee.location')
            return 'result of %s.%s' % (model, meth)
        raise AssertionError('unexpected rpc %s' % method)

    def _run(self, fn):
        with mock.patch(CLIENT + '._rpc', autospec=True, side_effect=self._fake_rpc):
            return fn()

    def _logins_used_by_execute(self):
        return [c['login'] for c in self.calls if c['method'] == 'execute_kw']

    # ------------------------------------------------------------------ who logs in
    def test_plain_reads_use_the_reader_and_the_url_is_cleaned(self):
        res = self._run(lambda: self.client.execute('hr.employee', 'search_read', [[]], {}))
        self.assertEqual(res, 'result of hr.employee.search_read')
        self.assertEqual(self._logins_used_by_execute(), ['rd'])

    def test_a_task_can_ask_for_the_writer_even_to_read(self):
        self._run(lambda: self.client.execute('kderp.advance.payment', 'read_group', [[]], {}, account='writer'))
        self.assertEqual(self._logins_used_by_execute(), ['wr'])

    def test_without_a_reader_reads_use_the_writer(self):
        self.icp.set_param('kderp_remote.reader_login', '')
        self._run(lambda: self.client.execute('hr.employee', 'search_read', [[]], {}))
        self.assertEqual(self._logins_used_by_execute(), ['wr'])

    # ------------------------------------------------------------------ writes: task, dry run, live switches
    def test_a_write_must_name_its_task(self):
        with self.assertRaises(UserError) as cm:
            self._run(lambda: self.client.execute('kderp.advance.payment', 'create', [{}]))
        self.assertNotIsInstance(cm.exception, RemoteNotLive)
        self.assertFalse(self.calls)

    def test_dry_run_is_the_default_and_calls_nothing(self):
        with self.assertRaises(RemoteNotLive):
            self._run(lambda: self.client.execute('kderp.advance.payment', 'create', [{}], task='advance'))
        self.assertFalse(self.calls)                        # not even a login

    def test_live_switch_is_per_task(self):
        self.icp.set_param('kderp_remote.live.advance', 'True')
        self._run(lambda: self.client.execute('kderp.advance.payment', 'create', [{}], task='advance'))
        with self.assertRaises(RemoteNotLive):              # advance is live, staff locations are not
            self._run(lambda: self.client.execute('kderp.hr.employee.location', 'create', [{}], task='staff_location'))
        self.assertTrue(self.client.is_live('advance'))
        self.assertFalse(self.client.is_live('staff_location'))

    def test_a_write_never_uses_the_reader(self):
        self.icp.set_param('kderp_remote.live.staff_location', 'True')
        self._run(lambda: self.client.execute('kderp.hr.employee.location', 'create', [{}], account='reader', task='staff_location'))
        self.assertEqual(self._logins_used_by_execute(), ['wr'])

    # ------------------------------------------------------------------ configuration and transport
    def test_incomplete_settings_say_where_to_fix_them(self):
        self.icp.set_param('kderp_remote.url', '')
        with self.assertRaises(UserError) as cm:
            self._run(lambda: self.client.execute('hr.employee', 'search_read', [[]]))
        self.assertIn('Settings > Remote Server Connection', str(cm.exception))
        self.assertIn('url', str(cm.exception))

    def test_login_is_done_once_per_login(self):
        for i in range(3):
            self._run(lambda: self.client.execute('hr.employee', 'search_read', [[]]))
        self.assertEqual(len([c for c in self.calls if c['method'] == 'login']), 1)
        self.assertEqual(len(self._logins_used_by_execute()), 3)

    def test_url_has_no_trailing_slash(self):
        self.assertEqual(self.client._get_config('writer')['url'], 'http://remote.test:8169')

    # ------------------------------------------------------------------ the test button
    def test_test_connection_tells_when_the_reader_can_write(self):
        info = self._run(self.client.test_connection)
        self.assertEqual(info['version'], '12.0')
        self.assertEqual(info['accounts']['writer']['rights']['kderp.advance.payment'], 'rcwu')
        reader = info['accounts']['reader']['rights']
        self.assertEqual(reader['kderp.advance.payment'], 'r---')
        self.assertIn('c', reader['kderp.hr.employee.location'])
        self.assertEqual(info['live'], {'advance': False, 'staff_location': False})

    def test_test_connection_uses_what_is_typed(self):
        self.icp.set_param('kderp_remote.writer_login', '')           # nothing saved for the writer ...
        info = self._run(lambda: self.client.test_connection(override={'writer_login': 'wr', 'writer_password': 'wrpw'}))
        self.assertEqual(info['accounts']['writer']['login'], 'wr')   # ... but the typed one is tested

    def test_test_connection_without_a_reader(self):
        self.icp.set_param('kderp_remote.reader_login', '')
        info = self._run(self.client.test_connection)
        self.assertEqual(info['accounts']['reader'], {'same_as_writer': True})

    def test_test_connection_needs_a_writer(self):
        self.icp.set_param('kderp_remote.writer_login', '')
        with self.assertRaises(UserError):
            self._run(self.client.test_connection)

    # ------------------------------------------------------------------ settings page
    def test_settings_never_send_a_password_to_the_browser(self):
        vals = self.env['res.config.settings'].get_values()
        self.assertEqual((vals['kderp_remote_reader_password'], vals['kderp_remote_writer_password']), ('', ''))
        self.assertNotIn('rdpw', str(vals))
        self.assertNotIn('wrpw', str(vals))
        self.assertTrue(vals['kderp_remote_writer_password_saved'])
        self.assertEqual(vals['kderp_remote_writer_login'], 'wr')

    def test_settings_empty_password_keeps_it_and_typed_one_replaces_it(self):
        S = self.env['res.config.settings']
        S.create({'kderp_remote_url': 'http://x', 'kderp_remote_db': 'db1', 'kderp_remote_reader_login': 'rd',
                  'kderp_remote_writer_login': 'wr'}).set_values()
        self.assertEqual(self.icp.get_param('kderp_remote.writer_password'), 'wrpw')
        self.assertEqual(self.icp.get_param('kderp_remote.reader_password'), 'rdpw')
        S.create({'kderp_remote_writer_password': 'new-pw'}).set_values()
        self.assertEqual(self.icp.get_param('kderp_remote.writer_password'), 'new-pw')

    def test_settings_save_one_live_switch_per_task(self):
        S = self.env['res.config.settings']
        S.create({'kderp_remote_live_advance': True, 'kderp_remote_live_staff_location': False}).set_values()
        self.assertTrue(self.client.is_live('advance'))
        self.assertFalse(self.client.is_live('staff_location'))

    def test_test_button_shows_the_result_in_a_dialog(self):
        settings = self.env['res.config.settings'].create({})
        action = self._run(settings.action_kderp_remote_test_connection)
        self.assertEqual(action['res_model'], 'kderp.remote.test.result')
        text = self.env['kderp.remote.test.result'].browse(action['res_id']).message
        self.assertIn('Connected to the remote server (version 12.0)', text)
        self.assertIn('Writer: wr', text)
        self.assertIn('Real writes: Advance requests dry run', text)
