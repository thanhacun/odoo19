import datetime

from odoo import api, fields, models


class HrDepartment(models.Model):
    """Department / section / project: code, type, 2nd manager, new manager with effective date."""
    _inherit = 'hr.department'
    _rec_names_search = ['complete_name', 'code']

    _code_unique = models.Constraint('unique(code)', 'The department code must be unique.')

    code = fields.Char(string='Dept./Sect./Proj. Code', index=True, copy=False)
    manager_2nd_id = fields.Many2one('hr.employee', string='2nd Manager')
    new_manager = fields.Many2one('hr.employee', string='New manager')
    new_man_effective_date = fields.Date(string='Effective Date')
    type_id = fields.Many2one('hr.department.type', string='Type')

    @api.model
    def _cron_change_to_effective_manager(self):
        self.search([('new_manager', '!=', False), ('new_man_effective_date', '<=', fields.Date.today())])._change_to_effective_manager()

    def _change_to_effective_manager(self):
        today = datetime.date.today()
        for department in self:
            if department.new_manager and department.new_man_effective_date and department.new_man_effective_date <= today:
                department.manager_id = department.new_manager
                department.write({'new_manager': False, 'new_man_effective_date': False})


class HrDepartmentType(models.Model):
    # codes used by Odoo 12 data: section, department, area, project
    _name = 'hr.department.type'
    _description = 'HR department types'

    name = fields.Char(string='Dept./Sect./Proj. type')
    code = fields.Char(string='Dept./Sect./Proj. code', required=True)
    description = fields.Char()
