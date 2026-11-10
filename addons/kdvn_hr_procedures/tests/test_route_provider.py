"""Route distance providers (OpenStreetMap, Goong) with the HTTP layer mocked: no network."""
from unittest import mock

from odoo.tests.common import TransactionCase

MOD = 'odoo.addons.kdvn_hr_procedures.models.staff_transfer.route_distance'


class FakeResponse(object):
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class TestRouteProvider(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Route = self.env['transfer.route.distance']
        self.param = self.env['ir.config_parameter'].sudo()
        self.calls = []
        patcher = mock.patch(MOD + '.time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def _get(self, answers):
        def fake(url, params=None, headers=None, timeout=None):
            self.calls.append((url, dict(params or {})))
            for part, answer in answers:
                if part in url:
                    return answer(params) if callable(answer) else answer
            raise AssertionError('unexpected url %s' % url)
        patcher = mock.patch(MOD + '.requests.get', fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_osm_default(self):
        self.param.set_param('kderp_hr_procedures.route_provider', '')
        self._get([('/search', FakeResponse([{'lat': '21.0', 'lon': '105.8'}])),
                   ('/route/v1/driving/105.8,21.0;105.8,21.0', FakeResponse({'code': 'Ok', 'routes': [{'distance': 12345.0, 'duration': 900}]}))])
        km, msg = self.Route.get_km('1 A street, Ha Noi', 'Lot K1, Thang Long IP, Ha Noi')
        self.assertEqual((km, msg), (12.3, ''))
        self.assertEqual(self.Route.search([('origin', '=', '1 A street, Ha Noi')]).duration_min, 15)
        count = len(self.calls)
        self.assertEqual(self.Route.get_km('1 A street, Ha Noi', 'Lot K1, Thang Long IP, Ha Noi'), (12.3, ''))
        self.assertEqual(len(self.calls), count, 'second call must come from the cache')

    def test_osm_retries_with_a_shorter_address(self):
        def search(params):
            return FakeResponse([{'lat': '21.0', 'lon': '105.8'}] if params['q'] in ('Tower, Ha Noi', 'Thang Long IP, Ha Noi') else [])
        self._get([('/search', search),
                   ('/route/v1', FakeResponse({'code': 'Ok', 'routes': [{'distance': 1000, 'duration': 60}]}))])
        km, msg = self.Route.get_km('Floor 3, Tower, Ha Noi', 'Lot K1, Thang Long IP, Ha Noi')
        self.assertEqual(km, 1.0, msg)

    def test_failure_is_remembered_for_an_hour_unless_forced(self):
        self._get([('/search', FakeResponse([]))])
        self.assertIsNone(self.Route.get_km('Nowhere, X', 'Nowhere else, Y')[0])
        count = len(self.calls)
        self.assertIsNone(self.Route.get_km('Nowhere, X', 'Nowhere else, Y')[0])
        self.assertEqual(len(self.calls), count, 'no new call while the failure is remembered')
        self.Route.get_km('Nowhere, X', 'Nowhere else, Y', force=True)
        self.assertGreater(len(self.calls), count)

    def test_osm_address_not_found_never_raises(self):
        self._get([('/search', FakeResponse([]))])
        km, msg = self.Route.get_km('Nowhere', 'Nowhere else')
        self.assertIsNone(km)
        self.assertIn('not found', msg)

    def test_goong_needs_key_and_hides_it(self):
        self.param.set_param('kderp_hr_procedures.route_provider', 'goong')
        self.param.set_param('kderp_hr_procedures.goong_api_key', '')
        km, msg = self.Route.get_km('A, Ha Noi', 'B, Ha Noi')
        self.assertIsNone(km)
        self.assertIn('Goong API key not set', msg)
        self.param.set_param('kderp_hr_procedures.goong_api_key', 'SECRETKEY')
        self._get([('/geocode', FakeResponse({'results': [{'geometry': {'location': {'lat': 21.0, 'lng': 105.8}}}]})),
                   ('/Direction', FakeResponse({'routes': [{'legs': [{'distance': {'value': 20500}, 'duration': {'value': 1500}}]}]}))])
        self.assertEqual(self.Route.get_km('A, Ha Noi', 'B, Ha Noi'), (20.5, ''))
        self._get([('/geocode', FakeResponse({'message': 'bad key'}, status=401))])
        km, msg = self.Route.get_km('C, Ha Noi', 'D, Ha Noi')
        self.assertIsNone(km)
        self.assertNotIn('SECRETKEY', msg)


class TestAddressVariants(TransactionCase):

    def test_wording_cleaned_and_industrial_park_in_vietnamese(self):
        R = self.env['transfer.route.distance']
        self.assertEqual(R._address_variants('15F, CMC Tower, Duy Tan street, X ward, Cau Giay district, Ha Noi, Vietnam')[0],
                         '15F, CMC Tower, Duy Tan street, X, Cau Giay, Ha Noi, Vietnam')
        variants = R._address_variants('Plot C6, Thang Long Industrial Park II, Nguyen Van Linh Commune, Hung Yen Province, Vietnam, Vietnam')
        self.assertIn('Khu cong nghiep Thang Long II', variants)
        self.assertTrue(all('Commune' not in v and 'Province' not in v for v in variants))
        self.assertLessEqual(len(variants), 5)


class TestOfficeAddresses(TransactionCase):

    def test_company_button_lists_only_office_addresses_and_creates_under_the_company(self):
        company = self.env.company
        action = company.action_open_office_addresses()
        self.assertEqual(action['domain'], [('parent_id', '=', company.partner_id.id), ('type', '!=', 'contact')])
        office = self.env['res.partner'].with_context(**action['context']).create(
            {'name': 'Hai Phong Office', 'street': '1 Le Hong Phong', 'city': 'Hai Phong'})
        self.assertEqual((office.parent_id, office.type), (company.partner_id, 'other'))
        self.assertIn(office, self.env['res.partner'].search(action['domain']))
        self.assertIn('Hai Phong', self.env['staff.transfer']._office_address('hp'))

    def test_company_form_has_the_office_addresses_tab(self):
        arch = self.env['res.company'].get_view(view_type='form')['arch']
        self.assertIn('name="office_addresses"', arch)
        self.assertIn('action_open_office_addresses', arch)
