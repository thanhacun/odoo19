import base64
import io

from PIL import Image

from odoo.tests import HttpCase, tagged


def _png():
    """Small valid PNG (generated, so it is never corrupt)."""
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), (0, 140, 60)).save(buf, format='PNG')
    return base64.b64encode(buf.getvalue())


PIXEL = _png()


@tagged('post_install', '-at_install')
class TestWebsiteProjects(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Job = cls.env['kderp.job.lookup']
        cls.job = Job.create({
            'external_id': 990001, 'job_no': 'HM11-25-0004', 'job_name': 'Pocari Sweat Factory',
            'actual_completion_date': '2025-06-30', 'state': 'done',
        })
        cls.factory = cls.env.ref('kdvn_website_project.category_factory')
        cls.building = cls.env.ref('kdvn_website_project.category_building')
        Project = cls.env['kdvn.website.project']
        cls.p2025 = Project.create({
            'name': 'KDVN Test Pocari', 'job_ids': [(6, 0, cls.job.ids)], 'area': 'Hung Yen, Vietnam',
            'project_type': 'me', 'category_id': cls.factory.id, 'is_published': True, 'image_1920': PIXEL,
            'tag_ids': [(6, 0, cls.env.ref('kdvn_website_project.tag_electrical').ids)],
        })
        cls.p2024 = Project.create({
            'name': 'KDVN Test Taisei', 'year': 2024, 'category_id': cls.building.id, 'is_published': True})
        cls.hidden = Project.create({'name': 'KDVN Test Hidden', 'year': 2024, 'is_published': False})
        cls.old = Project.create({'name': 'KDVN Test Old', 'year': 2012, 'is_published': True})

    def test_year_from_jobs(self):
        self.assertEqual(self.p2025.year, 2025)
        self.assertEqual(self.p2024.year, 2024, "year typed by hand is kept without jobs")

    def test_page_data(self):
        Project = self.env['kdvn.website.project']
        data = Project._kdvn_page_data()
        names = data['projects'].mapped('name')
        self.assertIn('KDVN Test Pocari', names)
        self.assertNotIn('KDVN Test Hidden', names)
        data = Project._kdvn_page_data(category=self.factory)
        self.assertIn(self.p2025, data['projects'])
        self.assertNotIn(self.p2024, data['projects'])
        data = Project._kdvn_page_data(year='2024')
        self.assertEqual(data['selected'], '2024')
        self.assertIn(self.p2024, data['projects'])
        self.assertNotIn(self.p2025, data['projects'])
        data = Project._kdvn_page_data(year='1900')
        self.assertEqual(data['selected'], 'all', "unknown year falls back to All")

    def test_page_grid_and_list(self):
        res = self.url_open('/prominent-projects')
        self.assertEqual(res.status_code, 200)
        self.assertIn('KDVN Test Pocari', res.text)
        self.assertIn('Electrical Work', res.text)
        self.assertIn('kdvn-proj-card', res.text)
        self.assertNotIn('KDVN Test Hidden', res.text)
        self.assertIn('/prominent-projects/image/%s/512' % self.p2025.id, res.text)

        res = self.url_open('/prominent-projects?view=list&category=factory')
        self.assertEqual(res.status_code, 200)
        self.assertIn('kdvn-proj-table', res.text)
        self.assertIn('KDVN Test Pocari', res.text)
        self.assertIn('Hung Yen, Vietnam', res.text)
        self.assertNotIn('KDVN Test Taisei', res.text)

    def test_image_route(self):
        res = self.url_open('/prominent-projects/image/%s/512' % self.p2025.id)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers.get('Content-Type', '').startswith('image/'))
        self.hidden.image_1920 = PIXEL
        res = self.url_open('/prominent-projects/image/%s/512' % self.hidden.id)
        self.assertEqual(res.status_code, 404)

    def test_linked_job_not_purged(self):
        """kdvn_remote_sync must keep a job that a website project uses."""
        self.env['kderp.job.lookup'].execute_master_sync_pipeline(jobs_data=[{
            'id': 990002, 'code': 'HM11-26-0001', 'name': 'Other job', 'state': 'doing'}])
        self.assertTrue(self.job.exists())

    def test_create_from_jobs(self):
        action = self.job.action_kdvn_create_website_project()
        project = self.env['kdvn.website.project'].browse(action['res_id'])
        self.assertEqual(project.name, 'Pocari Sweat Factory')
        self.assertEqual(project.year, 2025)
        self.assertFalse(project.is_published)
