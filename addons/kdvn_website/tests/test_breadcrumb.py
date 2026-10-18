import json

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnBreadcrumb(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].create({'name': 'KDVN test site'})
        Menu = cls.env['website.menu']
        # The menu tree the site shows (copied from Odoo's default when the website is created)
        cls.root = cls.website.menu_id or Menu.create({'name': 'Root', 'url': '/root', 'website_id': cls.website.id})
        # A same-URL item in another menu tree must be ignored
        cls.other_root = Menu.create({'name': 'Other root', 'url': '/other', 'website_id': cls.website.id, 'sequence': 999})
        Menu.create({'name': 'Wrong', 'url': '/kdvn-test-jobs', 'parent_id': cls.other_root.id, 'website_id': cls.website.id})
        # Odoo 19 forces the URL of menus with sub-items to '#'; overview_url is used instead
        cls.section = Menu.create({'name': 'Company profile', 'url': '/company-profile',
                                   'overview_url': '/company-profile',
                                   'parent_id': cls.root.id, 'website_id': cls.website.id})
        cls.page = Menu.create({'name': 'General Director Message', 'url': '/company-profile/general-director-message',
                                'parent_id': cls.section.id, 'website_id': cls.website.id})
        cls.recruitment = Menu.create({'name': 'Recruitment', 'url': '#',
                                       'parent_id': cls.root.id, 'website_id': cls.website.id})
        cls.jobs = Menu.create({'name': 'Open Positions', 'url': '/kdvn-test-jobs',
                                'parent_id': cls.recruitment.id, 'website_id': cls.website.id})

    def test_page_in_menu(self):
        bc = self.env['website.menu']._kdvn_breadcrumb(self.website, url='/company-profile/general-director-message')
        self.assertEqual(bc['trail'], [('Company profile', '/company-profile')])
        self.assertEqual(bc['title'], 'General Director Message')

    def test_parent_url_forced_but_overview_used(self):
        self.assertEqual(self.section.url, '#')
        self.assertEqual(self.section._kdvn_link(), '/company-profile')

    def test_page_not_in_menu(self):
        bc = self.env['website.menu']._kdvn_breadcrumb(
            self.website, url='/jobs/detail/x', parent_url='/kdvn-test-jobs', title='Engineer')
        self.assertEqual(bc['trail'], [('Recruitment', '#'), ('Open Positions', '/kdvn-test-jobs')])
        self.assertEqual(bc['title'], 'Engineer')

    def test_extra_crumbs(self):
        bc = self.env['website.menu']._kdvn_breadcrumb(
            self.website, parent_url='/kdvn-test-jobs', title='Form', extra=[('Engineer', '/jobs/detail/1')])
        self.assertEqual(bc['trail'][-1], ('Engineer', '/jobs/detail/1'))

    def test_unknown_url(self):
        bc = self.env['website.menu']._kdvn_breadcrumb(self.website, url='/nowhere', title='X')
        self.assertEqual(bc, {'trail': [], 'title': 'X'})

    def test_json_ld(self):
        bc = self.env['website.menu']._kdvn_breadcrumb(self.website, url='/jobs/detail/x', parent_url='/kdvn-test-jobs', title='Engineer')
        data = json.loads(str(self.env['website.menu']._kdvn_breadcrumb_json_ld(self.website, bc)))
        self.assertEqual(data['@type'], 'BreadcrumbList')
        names = [e['name'] for e in data['itemListElement']]
        self.assertEqual(names, ['Kinden', 'Recruitment', 'Open Positions', 'Engineer'])
        # '#' menu items have no link
        self.assertNotIn('item', data['itemListElement'][1])
        self.assertTrue(data['itemListElement'][2]['item'].endswith('/kdvn-test-jobs'))
