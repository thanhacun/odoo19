from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestKdvnBase(TransactionCase):

    def setUp(self):
        super().setUp()
        self.model = self.env['ir.model']._get('res.partner')
        self.State = self.env['kderp.base.state']

    def _states(self):
        draft = self.State.create({'name': 'Draft', 'code': 'draft', 'model_id': self.model.id, 'default_code': True, 'sequence': 1})
        sub = self.State.create({'name': 'Submitted', 'code': 'sub', 'model_id': self.model.id, 'previous_id': draft.id, 'sequence': 2})
        done = self.State.create({'name': 'Done', 'code': 'done', 'model_id': self.model.id, 'previous_id': sub.id, 'sequence': 3, 'finalstate': True})
        return draft, sub, done

    def test_next_state_follows_the_chain(self):
        draft, sub, done = self._states()
        self.assertEqual(draft.get_next_id(), sub)
        self.assertEqual(sub.get_next_id(), done)
        self.assertFalse(done.get_next_id())
        self.assertEqual(draft.next_id, sub)

    def test_condition_picks_the_branch_and_ignore_skips_a_state(self):
        draft, sub, done = self._states()
        alt = self.State.create({'name': 'Alt', 'code': 'alt', 'model_id': self.model.id, 'previous_id': draft.id, 'sequence': 1, 'condition': 'record.name == "Special"'})
        partner = self.env['res.partner'].create({'name': 'Special'})
        self.assertEqual(draft.with_context(active_record_id=partner.id).get_next_id(), alt)
        other = self.env['res.partner'].create({'name': 'Plain'})
        self.assertEqual(draft.with_context(active_record_id=other.id).get_next_id(), sub)
        sub.ignore = 'record.name == "Plain"'
        self.assertEqual(draft.with_context(active_record_id=other.id).get_next_id(), done, 'sub is skipped for this record')

    def test_state_group_is_checked(self):
        draft, sub, done = self._states()
        sub.group_id = self.env.ref('base.group_system')
        user = self.env.ref('base.public_user')   # not in group_system (mail is not a dependency here, so no user is created)
        with self.assertRaises(AccessError):
            draft.with_user(user)._check_group(sub)
        draft._check_group(sub)   # OdooBot / superuser passes

    def test_code_is_unique_and_name_search_uses_code_first(self):
        Code = self.env['kderp.base.code']
        a = Code.create({'name': 'Worked', 'code': 'O', 'model_id': self.model.id, 'type_code': 'state', 'sequence': 1})
        b = Code.create({'name': 'Other', 'code': 'OH', 'model_id': self.model.id, 'type_code': 'state', 'sequence': 2})
        self.assertEqual(a.display_name, 'Worked', 'codes are name-only in lists (_name_only)')
        found = [r[0] for r in Code.name_search('OH')]
        self.assertIn(b.id, found)   # other modules' codes (e.g. attendance 'OH') may match too
        self.assertIn(a.id, [r[0] for r in Code.name_search('Worked')])
        with self.assertRaises(Exception):   # same (type_code, code, model) twice
            with self.cr.savepoint():
                Code.create({'name': 'Dup', 'code': 'O', 'model_id': self.model.id, 'type_code': 'state'})

    def test_only_one_default_state_per_model(self):
        self.State.create({'name': 'A', 'code': 'a', 'model_id': self.model.id, 'default_code': True})
        with self.assertRaises(ValidationError):
            self.State.create({'name': 'B', 'code': 'b', 'model_id': self.model.id, 'default_code': True})
