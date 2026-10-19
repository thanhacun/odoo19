import json

from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.kdvn_website_project.models.project_import import _project_type

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
