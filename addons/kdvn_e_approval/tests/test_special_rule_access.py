# -*- coding: utf-8 -*-
"""Special case rules: a procedure's controllers read and edit only their own rows; the E-Approval Administrator sees all
(port of Odoo 12 kderp_e_approval 2acf3120)."""
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpecialRuleAccess(TransactionCase):

    def setUp(self):
        super().setUp()
        Rule = self.env['kderp.e.approval.special.rule']
        procedures = [value for value, label in Rule._selection_procedures()]
        if len(procedures) < 2:
            self.skipTest('needs two installed approval procedures')
        self.group_a = self.env['res.groups'].create({'name': 'Controllers of procedure A'})
        self.group_b = self.env['res.groups'].create({'name': 'Controllers of procedure B'})
        self.row_a = Rule.create({'procedure': procedures[0], 'code': 'tsr_a', 'name': 'Rule A', 'value': 3,
                                  'manager_group_id': self.group_a.id})
        self.row_b = Rule.create({'procedure': procedures[1], 'code': 'tsr_b', 'name': 'Rule B', 'value': 5,
                                  'manager_group_id': self.group_b.id})
        self.user_a = self._user('tsr_user_a', self.group_a)
        self.user_none = self._user('tsr_user_none', self.env['res.groups'])
        self.admin = self._user('tsr_admin', self.env.ref('kdvn_e_approval.group_e_approval_admin'))

    def _user(self, login, group):
        groups = self.env.ref('base.group_user') | group
        return self.env['res.users'].create({'name': login, 'login': login, 'email': login + '@example.test',
                                             'group_ids': [Command.set(groups.ids)]})

    def _visible(self, user):
        return self.env['kderp.e.approval.special.rule'].with_user(user).search(
            [('id', 'in', (self.row_a | self.row_b).ids)])

    def test_controller_reads_only_own_procedure_rows(self):
        self.assertEqual(self._visible(self.user_a), self.row_a)

    def test_user_without_the_group_reads_nothing(self):
        self.assertFalse(self._visible(self.user_none))

    def test_administrator_reads_all(self):
        self.assertEqual(self._visible(self.admin), self.row_a | self.row_b)

    def test_controller_edits_own_row_only(self):
        self.row_a.with_user(self.user_a).write({'value': 4})
        self.assertEqual(self.row_a.value, 4)
        with self.assertRaises(AccessError):
            self.row_b.with_user(self.user_a).write({'value': 9})

    def test_procedure_still_reads_the_rule_for_any_user(self):
        """get_rule reads with sudo: a submit by a plain applicant is not affected by the stricter read rule."""
        rule = self.env['kderp.e.approval.special.rule'].with_user(self.user_none).get_rule(self.row_b.procedure, 'tsr_b')
        self.assertEqual(rule, self.row_b)
        self.assertEqual(rule.value, 5)
