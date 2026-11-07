from odoo import fields, models


class HrEmployeePublic(models.Model):
    """Odoo 19 only lets users without HR rights read the fields of hr.employee.public. Odoo 12 let every user read the staff code, the
    organisation and the working flags, and the attendance logic reads them as an ordinary user: they are part of the public profile.
    (hr.employee docstring: a field only on hr.employee must have groups="hr.group_hr_user", otherwise it is not available to non-HR users.)"""
    _inherit = 'hr.employee.public'

    code = fields.Char(readonly=True)
    category_ids = fields.Many2many('hr.employee.category', 'employee_category_rel', 'employee_id', 'category_id', string='Tags', readonly=True)
    working_area_id = fields.Many2one('hr.department', readonly=True)
    current_location_id = fields.Many2one('kderp.employee.location.code', readonly=True)
