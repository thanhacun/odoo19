from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestKnowledge(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Page = self.env['document.page']
        self.root = self.Page.kderp_page_by_key('user-guides')
        self.assertTrue(self.root, 'the guides root page is shipped by the module')
        self.env['kderp.knowledge.role'].create({'code': 'tester', 'name': 'Tester'})

    def _publish(self, key, html, **extra):
        payload = {'key': key, 'title': 'Test page', 'type': 'content', 'parent_key': 'user-guides', 'sequence': 10,
                   'roles': [], 'html': html, 'source_path': key + '.md', 'source_hash': 'h-' + str(hash(html))}
        payload.update(extra)
        return self.Page._kderp_import_page(payload)

    def test_publish_creates_a_pending_change_request_then_approve(self):
        res = self._publish('t/one', '<p>Hello</p>')
        self.assertEqual(res['status'], 'created')
        page = self.Page.browse(res['id'])
        self.assertEqual(page.kderp_key, 't/one')
        self.assertTrue(page.kderp_managed)
        pending = self.env['document.page.history'].search([('page_id', '=', page.id)])
        self.assertTrue(pending and all(h.state != 'approved' for h in pending))
        pending.action_approve()
        page.invalidate_recordset()
        self.assertIn('Hello', page.content)

    def test_same_source_is_unchanged_and_a_new_source_is_a_change_request(self):
        res = self._publish('t/two', '<p>A</p>', source_hash='same')
        self.assertEqual(self._publish('t/two', '<p>A</p>', source_hash='same')['status'], 'unchanged')
        res2 = self._publish('t/two', '<p>B</p>', source_hash='other')
        self.assertEqual((res2['status'], res2['id']), ('updated', res['id']))
        waiting = self.env['document.page.history'].search([('page_id', '=', res['id']), ('state', '=', 'to approve')])
        self.assertTrue(waiting)

    def test_role_blocks_are_removed_for_readers_without_the_role(self):
        html = '<p>for all</p><div class="kderp-role" data-roles="tester"><p>secret block</p></div>'
        out = self.Page._kderp_filter_roles(html, set())
        self.assertIn('for all', out)
        self.assertNotIn('secret block', out)
        self.assertIn('secret block', self.Page._kderp_filter_roles(html, {'tester'}))

    def test_key_is_unique_and_page_found_by_key(self):
        self._publish('t/three', '<p>x</p>')
        self.assertEqual(self.Page.kderp_page_by_key('t/three').kderp_key, 't/three')
        action = self.Page.kderp_page_by_key('t/three').kderp_action_open_reader()
        self.assertEqual(action['res_model'], 'document.page')
        url = self.Page._kderp_reader_url(self.Page.kderp_page_by_key('t/three'))
        self.assertIn('model=document.page', url)

    def test_only_knowledge_managers_publish_through_rpc(self):
        user = self.env['res.users'].create({'name': 'K plain', 'login': 'k_plain',
                                             'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(AccessError):
            self.Page.with_user(user).kderp_import_page({'key': 'x/y', 'title': 't', 'html': '<p>x</p>'})

    def test_plain_user_can_open_the_guide_root(self):
        """Odoo 19: plain users cannot read ir.actions.act_window; the reader action is read as superuser."""
        user = self.env['res.users'].create({'name': 'K reader', 'login': 'k_reader',
                                             'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        action = self.Page.with_user(user).kderp_action_open_guide('user-guides')
        self.assertEqual((action['type'], action['res_model']), ('ir.actions.act_window', 'document.page'))
        self.assertTrue(self.Page.with_user(user).browse(action['res_id']).kderp_content_view is not None)
