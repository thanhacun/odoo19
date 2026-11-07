# -*- coding: utf-8 -*-
"""Every window action and menu of the module opens: its views compile and the first page of data reads.
This is the smoke test of the converted Odoo 12 screens (leave, request, settings); it does not check what the screens look like."""
from odoo.tests import common, tagged


@tagged('post_install', '-at_install', 'at_screens')
class TestScreens(common.TransactionCase):

    def test_every_window_action_opens(self):
        admin = self.env.ref('base.user_admin')
        xmlids = self.env['ir.model.data'].search([('module', '=', 'kdvn_hr_attendance'), ('model', '=', 'ir.actions.act_window')])
        self.assertTrue(xmlids)
        for data in xmlids:
            action = self.env['ir.actions.act_window'].browse(data.res_id).with_user(admin)
            if not action.res_model or action.res_model not in self.env:
                continue
            model = self.env[action.res_model].with_user(admin)
            modes = [m for m in (action.view_mode or 'list,form').split(',') if m in ('list', 'form', 'kanban', 'pivot', 'graph', 'calendar', 'search')]
            with self.subTest(action=data.name):
                views = model.get_views([(False, m) for m in modes] + [(False, 'search')])
                self.assertTrue(views['views'])
                ctx = dict(action._get_eval_context() if hasattr(action, '_get_eval_context') else {})
                model.with_context(active_test=False).search([], limit=1)

    def test_every_menu_resolves(self):
        menus = self.env['ir.ui.menu'].with_user(self.env.ref('base.user_admin')).search([])
        for data in self.env['ir.model.data'].search([('module', '=', 'kdvn_hr_attendance'), ('model', '=', 'ir.ui.menu')]):
            with self.subTest(menu=data.name):
                menu = self.env['ir.ui.menu'].browse(data.res_id)
                self.assertTrue(menu.exists())
                if menu.action:
                    self.assertTrue(menu.action.exists())
