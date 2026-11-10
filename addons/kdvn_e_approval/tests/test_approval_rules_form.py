# -*- coding: utf-8 -*-
"""The E-Approval Administrator opens the Approval Rules (tier.definition) form without the Administration: Settings right.
Odoo 12 let every internal user read ir.model / ir.model.fields; Odoo 19 core does not, and the form reads
`valid_reviewer_field_ids` (ir.model.fields) and `model_id` (ir.model)."""
from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestApprovalRulesForm(TransactionCase):

    def setUp(self):
        super().setUp()
        groups = self.env.ref('base.group_user') | self.env.ref('kdvn_e_approval.group_e_approval_admin')
        self.admin = self.env['res.users'].create({'name': 'ar_admin', 'login': 'ar_admin', 'email': 'ar_admin@example.test',
                                                   'group_ids': [Command.set(groups.ids)]})
        model = self.env['ir.model']._get('res.partner')
        tags = self.env['tier.definition']._get_dynamic_procedure_tags()
        if not tags:
            self.skipTest('needs an installed approval procedure')
        self.definition = self.env['tier.definition'].create({
            'name': 'Form test', 'procedure_tag': tags[0][0], 'model_id': model.id, 'review_type': 'field',
            'reviewer_field_id': self.env['ir.model.fields']._get('res.partner', 'user_id').id,
        })

    def test_form_of_a_definition_reads_for_the_e_approval_administrator(self):
        Definition = self.env['tier.definition'].with_user(self.admin)
        names = ['name', 'model_id', 'model', 'review_type', 'reviewer_field_id', 'valid_reviewer_field_ids', 'reviewer_group_id', 'reviewer_id']
        spec = {n: ({'fields': {'display_name': {}}} if Definition._fields[n].type in ('many2one', 'one2many', 'many2many') else {})
                for n in names}
        data = Definition.browse(self.definition.id).web_read(spec)[0]
        self.assertEqual(data['reviewer_field_id']['display_name'], self.definition.reviewer_field_id.display_name)
        self.assertTrue(data['valid_reviewer_field_ids'])

    def test_still_nothing_for_a_plain_user(self):
        plain = self.env['res.users'].create({'name': 'ar_plain', 'login': 'ar_plain', 'email': 'ar_plain@example.test',
                                              'group_ids': [Command.set(self.env.ref('base.group_user').ids)]})
        self.assertFalse(self.env['ir.model.fields'].with_user(plain).has_access('read'))
