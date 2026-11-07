from odoo import fields, models


class HrEmployeePublic(models.Model):
    """Organisation and working flags of the staff: readable by every user (Odoo 12 behaviour; see kdvn_hr/models/hr_employee_public.py)."""
    _inherit = 'hr.employee.public'

    working = fields.Boolean(readonly=True)
    stop_working_date = fields.Date(readonly=True)
    official_working_date = fields.Date(readonly=True)
    admin_dept_id = fields.Many2one('hr.department', readonly=True)
    admin_manager_id = fields.Many2one('hr.employee', readonly=True)
    gm_id = fields.Many2one('hr.employee', readonly=True)
    admin_gm_id = fields.Many2one('hr.employee', readonly=True)
    parent_users_dsp = fields.Char(readonly=True)
    admin_manager_users_dsp = fields.Char(readonly=True)
