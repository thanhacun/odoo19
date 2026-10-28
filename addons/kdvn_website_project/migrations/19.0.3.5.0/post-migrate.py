"""Fill the empty category of existing projects from the project name
(same guess as a new import; unclear names stay empty)."""
from odoo import SUPERUSER_ID, api

from odoo.addons.kdvn_website_project.models.project_import import _guess_category_slug


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    categories = {c.slug: c for c in env['kdvn.website.project.category'].search([])}
    for project in env['kdvn.website.project'].with_context(active_test=False).search([('category_id', '=', False)]):
        category = categories.get(_guess_category_slug(project.kderp_name or project.name))
        if category:
            project.category_id = category
