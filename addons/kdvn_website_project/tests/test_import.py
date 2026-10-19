from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

SOURCE = 'odoo.addons.kdvn_website_project.models.project_source.KdvnWebsiteProjectSource'

JOBS = [
    # one project made of two jobs (names differ only in case / spaces)
    {'id': 1, 'name': 'Pocari Sweat Factory', 'code': 'HM11-24-0004', 'state': 'closed', 'job_type': 'E',
     'date_start': '2023-02-01', 'completion_date': '2024-11-30', 'city_province_id': [5, 'Hung Yen'],
     'contracted_amount_usd': 900000.0},
    {'id': 2, 'name': 'POCARI  SWEAT FACTORY', 'code': 'HM11-24-0005', 'state': 'done', 'job_type': 'M',
     'date_start': '2023-04-01', 'completion_date': '2025-01-15', 'city_province_id': [5, 'Hung Yen'],
     'contracted_amount_usd': 600000.0},
    # too small
    {'id': 3, 'name': 'Small Office Fit-out', 'code': 'HM11-25-0007', 'state': 'done', 'job_type': 'E',
     'date_start': '2025-01-01', 'completion_date': '2025-03-01', 'city_province_id': False,
     'contracted_amount_usd': 50000.0},
]


def fake_rpc(jobs):
    def _search_read(self, domain, fields_to_read):
        names = [leaf[2].upper() for leaf in domain if isinstance(leaf, tuple) and leaf[0] == 'name']
        found = [j for j in jobs if not names or ' '.join(j['name'].split()).upper() in
                 {' '.join(n.split()).upper() for n in names}]
        return [{k: v for k, v in j.items() if k in fields_to_read or k == 'id'} for j in found]
    return _search_read


@tagged('post_install', '-at_install')
class TestProjectImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env['kdvn.website.project.source']
        cls.Project = cls.env['kdvn.website.project']
        cls.source = cls.Source.create({'name': 'Test OE', 'url': 'http://oe.invalid', 'db': 'x', 'login': 'u', 'password': 'p'})

    def _import(self, jobs):
        with patch(SOURCE + '._rpc_search_read', fake_rpc(jobs)):
            return self.Source._kdvn_import()

    def test_import_groups_jobs_and_filters_amount(self):
        result = self._import(JOBS)
        self.assertEqual((result['created'], result['errors']), (1, []))
        project = self.Project.with_context(active_test=False).search([('kderp_key', '=', 'POCARI SWEAT FACTORY')])
        self.assertEqual(project.kderp_amount_usd, 1500000)
        self.assertEqual(project.kderp_job_codes, 'HM11-24-0004, HM11-24-0005')
        self.assertEqual(project.project_type, 'me')
        self.assertEqual(project.year, 2025)
        self.assertEqual(str(project.kderp_date_start), '2023-02-01')
        self.assertEqual(project.area, 'Hung Yen, Vietnam')
        self.assertFalse(project.is_published, "new projects wait for an editor")
        self.assertFalse(self.Project.search([('kderp_name', '=', 'Small Office Fit-out')]))
        self.assertTrue(self.source.last_import_date)

    def test_reimport_keeps_website_edits(self):
        self._import(JOBS)
        project = self.Project.search([('kderp_key', '=', 'POCARI SWEAT FACTORY')])
        project.write({'name': 'Pocari Sweat Vietnam Factory', 'year': 2024, 'project_type': 'electrical'})
        jobs = [dict(JOBS[0], contracted_amount_usd=1000000.0), JOBS[1]]
        result = self._import(jobs)
        self.assertEqual((result['created'], result['updated']), (0, 1))
        self.assertEqual(project.kderp_amount_usd, 1600000)
        self.assertEqual(project.name, 'Pocari Sweat Vietnam Factory')
        self.assertEqual((project.year, project.project_type), (2024, 'electrical'))

    def test_failing_source_reported(self):
        def boom(self, domain, fields_to_read):
            raise ConnectionError('unreachable')
        with patch(SOURCE + '._rpc_search_read', boom):
            result = self.Source._kdvn_import()
        self.assertEqual(len(result['errors']), 1)
        self.assertFalse(self.source.last_import_date)
        self.assertIn('unreachable', self.source.last_message)

    def test_project_type(self):
        from odoo.addons.kdvn_website_project.models.project_source import _project_type
        self.assertEqual(_project_type(['E']), 'electrical')
        self.assertEqual(_project_type(['M']), 'mechanical')
        self.assertEqual(_project_type(['M&E']), 'me')
        self.assertEqual(_project_type(['X']), 'other')
        self.assertFalse(_project_type([]))
