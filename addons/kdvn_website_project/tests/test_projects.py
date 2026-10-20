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
        cls.factory = cls.env.ref('kdvn_website_project.category_factory')
        cls.building = cls.env.ref('kdvn_website_project.category_building')
        Project = cls.env['kdvn.website.project']
        cls.p2025 = Project.create({
            'name': 'KDVN Test Pocari', 'year': 2025, 'area': 'Hung Yen, Vietnam',
            'project_type': 'me', 'category_id': cls.factory.id, 'is_published': True, 'image_1920': PIXEL,
            'tag_ids': [(6, 0, cls.env.ref('kdvn_website_project.tag_electrical').ids)],
        })
        cls.p2024 = Project.create({
            'name': 'KDVN Test Taisei', 'year': 2024, 'category_id': cls.building.id, 'is_published': True})
        cls.hidden = Project.create({'name': 'KDVN Test Hidden', 'year': 2024, 'is_published': False})
        cls.old = Project.create({'name': 'KDVN Test Old', 'year': 2012, 'is_published': True})

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


@tagged('post_install', '-at_install')
class TestHomepageProjects(HttpCase):

    def test_homepage_section(self):
        Project = self.env['kdvn.website.project']
        Project.search([]).write({'show_on_homepage': False})
        old_featured = Project.create({'name': 'KDVN Home Featured', 'year': 2001, 'is_published': True,
                                       'show_on_homepage': True})
        newest = Project.create({'name': 'KDVN Home Newest', 'year': 2099, 'is_published': True})
        hidden = Project.create({'name': 'KDVN Home Hidden', 'year': 2099, 'is_published': False,
                                 'show_on_homepage': True})
        cards = Project._kdvn_homepage_projects()
        self.assertEqual(cards[0], old_featured, "'Show on Homepage' projects come first")
        self.assertIn(newest, cards, "topped up with the newest published projects")
        self.assertNotIn(hidden, cards)
        self.assertLessEqual(len(cards), 4)

        html = self.url_open('/').text
        self.assertIn('kdvn-home-projects', html)
        self.assertIn('KDVN Home Featured', html)
        self.assertNotIn('KDVN Home Hidden', html)
        self.assertIn('href="/prominent-projects"', html)


@tagged('post_install', '-at_install')
class TestProjectSearch(HttpCase):

    def test_website_search_finds_projects(self):
        Project = self.env['kdvn.website.project']
        Project.create({'name': 'KDVN Searchable Zeppelin Plant', 'year': 2020, 'is_published': True})
        Project.create({'name': 'KDVN Searchable Zeppelin Hidden', 'year': 2020, 'is_published': False})
        html = self.url_open('/website/search?search=Zeppelin').text
        self.assertIn('KDVN Searchable Zeppelin Plant', html)
        self.assertNotIn('KDVN Searchable Zeppelin Hidden', html)
