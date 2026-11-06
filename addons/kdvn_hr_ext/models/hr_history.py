from odoo import api, fields, models


class HrEmployeeDepartmentHistory(models.Model):
    _name = 'hr.employee.department.history'
    _description = 'Manage employee department'
    _order = 'effective_date desc'

    employee_id = fields.Many2one('hr.employee', required=True, ondelete='cascade', index=True)
    department_id = fields.Many2one('hr.department', required=True, string='Functional Dept.')
    effective_date = fields.Date(required=True, string='Func. date')
    admin_dept_id = fields.Many2one('hr.department', required=True, string='Administrative Dept.')
    admin_effv_date = fields.Date(required=True, string='Admin. date')

    _unique_values = models.Constraint(
        'UNIQUE (employee_id, department_id, effective_date, admin_dept_id, admin_effv_date)', 'Record must be unique!')

    @api.onchange('department_id', 'effective_date')
    def _onchange_func_dept(self):
        if not self.admin_dept_id:
            self.admin_dept_id = self.department_id
        if not self.admin_effv_date:
            self.admin_effv_date = self.effective_date

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.employee_id._refresh_organisation()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.employee_id._refresh_organisation()
        return result

    def unlink(self):
        employees = self.employee_id
        result = super().unlink()
        employees._refresh_organisation()
        return result


class HrManagerHistory(models.Model):
    _name = 'hr.manager.history'
    _description = 'Deptment Managers history'
    _order = 'effective_date desc'

    manager_id = fields.Many2one('hr.employee', required=True)
    department_id = fields.Many2one('hr.department', required=True, ondelete='cascade', index=True)
    effective_date = fields.Date(required=True)

    def _members(self):
        return self.department_id.member_ids | self.department_id.admin_member_ids

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._members()._refresh_organisation()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._members()._refresh_organisation()
        return result

    def unlink(self):
        members = self._members()
        result = super().unlink()
        members._refresh_organisation()
        return result


class HrEmployeeProjectHistory(models.Model):
    _name = 'hr.employee.project.history'
    _description = 'Manage employee project'
    _order = 'effective_date desc'

    employee_id = fields.Many2one('hr.employee', required=True, ondelete='cascade', index=True)
    project_name = fields.Char(required=True)
    project_description = fields.Text()
    effective_date = fields.Date(required=True)

    _unique_values = models.Constraint(
        'UNIQUE (employee_id, project_name, effective_date)', 'Record must be unique!')
