"""The GM group was looked up under its Odoo 12 module name, so gm_id / admin_gm_id stayed empty. Recompute the chains
(safe to run again)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    employees = env['hr.employee'].with_context(active_test=False).search([])
    employees._compute_parent_users()
