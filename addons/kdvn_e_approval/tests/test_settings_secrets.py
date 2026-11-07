# -*- coding: utf-8 -*-
"""The two secrets of the E-Approval settings (signing key, Nextcloud bot password) never go to the browser."""
from odoo.tests.common import TransactionCase

SECRET = 'kderp_e_approval.e_approval_secret_key'
BOT = 'kderp_e_approval.nc_bot_password'


class TestSettingsSecrets(TransactionCase):

    def setUp(self):
        super(TestSettingsSecrets, self).setUp()
        self.icp = self.env['ir.config_parameter'].sudo()
        self.icp.set_param(SECRET, 'TOP-SECRET-KEY')
        self.icp.set_param(BOT, 'BOT-PASSWORD')
        self.Settings = self.env['res.config.settings']

    def test_values_sent_to_the_browser_hold_no_secret(self):
        vals = self.Settings.get_values()
        self.assertEqual(vals['e_approval_secret_key'], '')
        self.assertEqual(vals['nc_bot_password'], '')
        self.assertNotIn('TOP-SECRET-KEY', str(vals))
        self.assertNotIn('BOT-PASSWORD', str(vals))
        self.assertIn('saved', vals['e_approval_secret_key_status'])
        self.assertIn('saved', vals['nc_bot_password_status'])

    def test_status_says_when_nothing_is_saved(self):
        self.icp.set_param(SECRET, '')
        self.icp.set_param(BOT, False)
        vals = self.Settings.get_values()
        self.assertIn('No key saved', vals['e_approval_secret_key_status'])
        self.assertIn('No password saved', vals['nc_bot_password_status'])

    def test_saving_with_empty_fields_keeps_the_secrets(self):
        self.Settings.create({'n8n_analytic_webhook_url': 'https://example.test/hook'}).set_values()
        self.assertEqual(self.icp.get_param(SECRET), 'TOP-SECRET-KEY')
        self.assertEqual(self.icp.get_param(BOT), 'BOT-PASSWORD')

    def test_typing_a_new_value_replaces_it(self):
        self.Settings.create({'e_approval_secret_key': '  NEW-KEY  ', 'nc_bot_password': 'NEW-PASSWORD'}).set_values()
        self.assertEqual(self.icp.get_param(SECRET), 'NEW-KEY')
        self.assertEqual(self.icp.get_param(BOT), 'NEW-PASSWORD')

    def test_other_settings_still_saved(self):
        self.Settings.create({'nc_base_url': 'https://nc.example.test/', 'nc_bot_username': 'bot'}).set_values()
        self.assertEqual(self.icp.get_param('kderp_e_approval.nc_base_url'), 'https://nc.example.test')
        self.assertEqual(self.icp.get_param('kderp_e_approval.nc_bot_username'), 'bot')
