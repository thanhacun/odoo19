import json

from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.kdvn_website_project.models.project_import import _job_amount_usd, _guess_category_slug, _job_em, _project_type

JOBS = [
    # one project made of two jobs (names differ only in case / spaces)
    {'id': 1, 'name': 'Pocari Sweat Factory', 'code': 'HM11-24-0004', 'state': 'closed', 'job_type': 'E',
     'date_start': '2023-02-01', 'completion_date': '2024-11-30', 'city_province_id': [5, 'Hung Yen'],
     'contracted_amount_usd': 900000.0},
    {'id': 2, 'name': 'POCARI  SWEAT FACTORY', 'code': 'HM11-24-0005', 'state': 'done', 'job_type': 'M',
     'date_start': '2023-04-01', 'actual_completion_date': '2025-01-15', 'city_province_id': [5, 'Hung Yen'],
     'contracted_amount_usd': 600000.0},
    # too small
    {'id': 3, 'name': 'Small Office Fit-out', 'code': 'HM11-25-0007', 'state': 'done', 'job_type': 'E',
     'date_start': '2025-01-01', 'completion_date': 'False', 'city_province_id': False,
     'contracted_amount_usd': 50000.0},
]


@tagged('post_install', '-at_install')
class TestProjectImport(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Project = self.env['kdvn.website.project']

    def test_import_groups_jobs_and_filters_amount(self):
        result = self.Project._kdvn_import_jobs(JOBS)
        self.assertEqual(result, {'created': 1, 'updated': 0, 'skipped': 1})
        project = self.Project.with_context(active_test=False).search([('kderp_key', '=', 'POCARI SWEAT FACTORY')])
        self.assertEqual(project.kderp_amount_usd, 1500000)
        self.assertEqual(project.kderp_job_codes, 'HM11-24-0004, HM11-24-0005')
        self.assertEqual(project.project_type, 'me')
        self.assertEqual(project.year, 2025, "latest of completion_date / actual_completion_date")
        self.assertEqual(str(project.kderp_date_start), '2023-02-01')
        self.assertEqual(project.area, 'Hung Yen, Vietnam')
        self.assertFalse(project.is_published, "new projects wait for an editor")
        self.assertFalse(self.Project.search([('kderp_name', '=', 'Small Office Fit-out')]))

    def test_reimport_keeps_website_edits(self):
        self.Project._kdvn_import_jobs(JOBS)
        project = self.Project.search([('kderp_key', '=', 'POCARI SWEAT FACTORY')])
        project.write({'name': 'Pocari Sweat Vietnam Factory', 'year': 2024, 'project_type': 'electrical'})
        result = self.Project._kdvn_import_jobs([dict(JOBS[0], contracted_amount_usd=1000000.0), JOBS[1]])
        self.assertEqual((result['created'], result['updated']), (0, 1))
        self.assertEqual(project.kderp_amount_usd, 1600000)
        self.assertEqual(project.name, 'Pocari Sweat Vietnam Factory')
        self.assertEqual((project.year, project.project_type), (2024, 'electrical'))

    def test_min_amount_setting(self):
        self.env['ir.config_parameter'].sudo().set_param('kdvn_website_project.min_amount_usd', '10000')
        self.assertEqual(self.Project._kdvn_import_jobs(JOBS)['created'], 2)

    def test_kderp_odoo12_jobs(self):
        """KDERP (Odoo 12): job_amount without VAT in the job currency, E/M in `em`,
        job_type = job scale."""
        self.env['ir.config_parameter'].sudo().set_param('kdvn_website_project.vnd_per_usd', '25000')
        jobs = [
            {'name': 'Daikin Plant', 'code': 'HE11-25-0001', 'state': 'closed', 'job_type': '00-big_job',
             'em': 'E', 'date_start': '2024-01-01', 'actual_completion_date': '2025-06-30',
             'city_province_id': [1, 'Hai Phong'], 'job_amount': 15000000000.0, 'currency_id': [23, 'VND'],
             'currency_rates': {'VND': 1.0, 'USD': 25000.0}},
            {'name': 'Daikin Plant', 'code': 'HM11-25-0002', 'state': 'done', 'job_type': '00-big_job',
             'em': 'M', 'date_start': '2024-02-01', 'completion_date': '2025-05-31',
             'city_province_id': [1, 'Hai Phong'], 'job_amount': 450000.0, 'currency_id': [2, 'USD']},
        ]
        result = self.Project._kdvn_import_jobs(jobs)
        self.assertEqual(result, {'created': 1, 'updated': 0, 'skipped': 0})
        project = self.Project.search([('kderp_key', '=', 'DAIKIN PLANT')])
        self.assertEqual(project.kderp_amount_usd, 1050000, "600,000 (VND / 25,000) + 450,000")
        self.assertEqual(project.project_type, 'me')
        self.assertEqual(project.kderp_type, 'E&M')

    def test_job_amount_usd(self):
        self.assertEqual(_job_amount_usd({'contracted_amount_usd': 10.0, 'job_amount': 99.0}, 25000), 10.0)
        self.assertEqual(_job_amount_usd({'job_amount': 50000.0, 'currency_id': [1, 'VND']}, 25000), 2.0)
        self.assertEqual(_job_amount_usd({'job_amount': 50000.0, 'currency_id': [1, 'VND'], 'usd_rate': 20000}, 25000), 2.5)
        self.assertEqual(_job_amount_usd({'job_amount': 7.0, 'currency_id': [1, 'USD']}, 25000), 7.0)
        self.assertEqual(_job_amount_usd({'job_amount': 7.0, 'currency_id': [1, 'JPY']}, 25000), 0.0)
        # the job's own KDERP rates (rate to the company currency, VND = 1)
        rates = {'VND': 1.0, 'USD': 24000.0, 'JPY': 160.0}
        self.assertEqual(_job_amount_usd({'job_amount': 48000.0, 'currency_id': [1, 'VND'],
                                          'currency_rates': rates}, 25000), 2.0)
        self.assertEqual(_job_amount_usd({'job_amount': 300.0, 'currency_id': [1, 'JPY'],
                                          'currency_rates': rates}, 25000), 2.0)
        self.assertEqual(_job_amount_usd({'job_amount': 5.0, 'currency_id': [1, 'USD'],
                                          'currency_rates': rates}, 25000), 5.0)
        self.assertEqual(_job_em({'job_type': '00-big_job', 'em': 'M'}), 'M')
        self.assertFalse(_job_em({'job_type': '00-big_job'}))

    def test_guess_category_slug(self):
        self.assertEqual(_guess_category_slug('TOYODA GOSEI THAI BINH NEW FACTORY'), 'factory')
        self.assertEqual(_guess_category_slug('Viettel IDC Data Center Phase 2'), 'data-center')
        self.assertEqual(_guess_category_slug('Sheraton Hotel Hanoi'), 'hotel')
        self.assertFalse(_guess_category_slug('Factory Office Building'))   # two categories: unclear
        self.assertFalse(_guess_category_slug('Mallory Project'))            # whole words only
        self.assertFalse(_guess_category_slug('Project ABC'))
        self.assertFalse(_guess_category_slug(False))

    def test_import_guesses_category(self):
        result = self.Project._kdvn_import_jobs(JOBS + [
            {'id': 4, 'name': 'Project ABC', 'code': 'X1', 'job_type': 'E', 'contracted_amount_usd': 2000000.0}])
        self.assertEqual(result['created'], 2)
        factory = self.Project.search([('kderp_key', '=', 'POCARI SWEAT FACTORY')])
        self.assertEqual(factory.category_id.slug, 'factory')
        self.assertFalse(self.Project.search([('kderp_key', '=', 'PROJECT ABC')]).category_id)

    def test_project_type(self):
        self.assertEqual(_project_type(['E']), 'electrical')
        self.assertEqual(_project_type(['M']), 'mechanical')
        self.assertEqual(_project_type(['M&E']), 'me')
        self.assertEqual(_project_type(['X']), 'other')
        self.assertFalse(_project_type([]))


@tagged('post_install', '-at_install')
class TestProjectImportEndpoint(HttpCase):
    URL = '/api/v1/website_projects'

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('kdvn_website_project.api_key', 'proj-key-123')

    def test_rejects_without_key(self):
        res = self.url_open(self.URL, data=json.dumps({'jobs': JOBS}), headers={'Content-Type': 'application/json'})
        self.assertEqual(res.status_code, 401)

    def test_json_body(self):
        res = self.url_open(self.URL, data=json.dumps({'jobs': JOBS}),
                            headers={'Content-Type': 'application/json', 'X-API-Key': 'proj-key-123'})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['result'], {'created': 1, 'updated': 0, 'skipped': 1})

    def test_form_field(self):
        res = self.url_open(self.URL, data={'jobs': json.dumps(JOBS)}, headers={'X-API-Key': 'proj-key-123'})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['jobs'], 3)

    def test_malformed(self):
        res = self.url_open(self.URL, data={'jobs': '[oops'}, headers={'X-API-Key': 'proj-key-123'})
        self.assertEqual(res.status_code, 400)
