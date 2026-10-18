from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestKdvnCompanyInfo(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].get_current_website()
        cls.company = cls.website.company_id
        cls.company.write({
            'kdvn_capital': 'USD 1,210,000.00',
            'kdvn_employee_count': 442,
            # head office = company address
            'kdvn_head_office_name': 'KDVN Test Head Office',
            'street': '15F, CMC Tower, Duy Tan Street', 'street2': 'Cau Giay Ward', 'city': 'Ha Noi',
            'phone': '+84 24 3934 2535',
        })
        cls.ho = cls.company.partner_id
        Partner = cls.env['res.partner']
        cls.branch = Partner.create({
            'name': 'HCM', 'type': 'other', 'parent_id': cls.company.partner_id.id,
            'kdvn_is_office': True, 'kdvn_office_main': True, 'kdvn_office_sequence': 1,
            'kdvn_office_name': 'KDVN Test Branch', 'city': 'Ho Chi Minh',
        })
        cls.other = Partner.create({
            'name': 'Other', 'type': 'other', 'parent_id': cls.company.partner_id.id,
            'kdvn_is_office': True, 'kdvn_office_sequence': 5,
            'kdvn_office_name': 'KDVN Test Site Office', 'city': 'Hai Phong',
        })

    def test_offices_order_and_main(self):
        offices = self.company._kdvn_website_offices()
        # head office (company address) always first, without any flag
        self.assertEqual(offices[0], self.ho)
        self.assertEqual(list(offices[1:3]), [self.branch, self.other])
        main = self.company._kdvn_website_offices(main_only=True)
        self.assertEqual(list(main), [self.ho, self.branch])

    def test_company_address_change_updates_head_office(self):
        self.company.street = '20F, New Tower'
        self.assertTrue(self.company._kdvn_website_offices()[0]._kdvn_address_line().startswith('20F, New Tower'))

    def test_offices_menu_lists_head_office(self):
        action = self.env.ref('kdvn_website.kdvn_office_action')
        from odoo.tools.safe_eval import safe_eval
        found = self.env['res.partner'].search(safe_eval(action.domain))
        self.assertIn(self.ho, found)
        self.assertIn(self.branch, found)
        self.assertTrue(self.ho.kdvn_is_head_office)
        self.assertFalse(self.branch.kdvn_is_head_office)

    def test_address_and_map(self):
        self.assertEqual(self.ho._kdvn_address_line(), '15F, CMC Tower, Duy Tan Street, Cau Giay Ward, Ha Noi')
        self.assertIn('output=embed', self.ho._kdvn_map_embed_url())
        self.ho.kdvn_map_url = 'https://maps.app.goo.gl/x'
        self.assertEqual(self.ho._kdvn_map_link(), 'https://maps.app.goo.gl/x')

    def test_pages_show_company_data(self):
        res = self.url_open('/company-profile/group-companies')
        self.assertEqual(res.status_code, 200)
        self.assertIn('KDVN Test Head Office', res.text)
        self.assertIn('USD 1,210,000.00', res.text)
        res = self.url_open('/contact-us/office-locations')
        self.assertEqual(res.status_code, 200)
        self.assertIn('KDVN Test Site Office', res.text)
        self.assertIn('kdvn-office-card', res.text)
        self.assertIn('output=embed', res.text)
        # footer shows main offices only
        footer = res.text[res.text.find('kdvn-footer'):]
        self.assertIn('KDVN Test Head Office', footer)
        self.assertNotIn('KDVN Test Site Office', footer)
