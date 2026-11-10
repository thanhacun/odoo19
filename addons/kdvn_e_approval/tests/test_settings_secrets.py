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


class TestRouteSettings(TransactionCase):
    """Staff transfer distance provider and Goong key on the E-Approval settings screen (Odoo 12 kderp_hr_procedures 7b420678)."""

    def test_settings_screen_saves_provider_and_keeps_the_key(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('kderp_hr_procedures.route_provider', False)
        icp.set_param('kderp_hr_procedures.goong_api_key', False)
        Settings = self.env['res.config.settings']
        self.assertEqual(Settings.get_values()['transfer_route_provider'], 'osm')
        Settings.create({'transfer_route_provider': 'goong', 'transfer_goong_key': ' KEY1 '}).set_values()
        self.assertEqual(icp.get_param('kderp_hr_procedures.route_provider'), 'goong')
        self.assertEqual(icp.get_param('kderp_hr_procedures.goong_api_key'), 'KEY1')
        vals = Settings.get_values()
        self.assertEqual((vals['transfer_goong_key'], vals['transfer_goong_key_saved']), ('', True))
        self.assertNotIn('KEY1', str(vals))
        Settings.create({'transfer_route_provider': 'osm'}).set_values()      # empty key field keeps the saved key
        self.assertEqual(icp.get_param('kderp_hr_procedures.goong_api_key'), 'KEY1')
        self.assertEqual(icp.get_param('kderp_hr_procedures.route_provider'), 'osm')

    def test_unknown_provider_value_falls_back_to_osm(self):
        self.env['ir.config_parameter'].sudo().set_param('kderp_hr_procedures.route_provider', 'google')
        self.assertEqual(self.env['res.config.settings'].get_values()['transfer_route_provider'], 'osm')
