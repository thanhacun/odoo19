import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KderpEmployeeLocationCode(models.Model):
    """Employee location code (office, site...)."""
    _name = 'kderp.employee.location.code'
    _description = 'Employee Location Code Model'

    name = fields.Char(string='Location Name', required=True)

    _employee_location_unique = models.Constraint('unique (name)', 'Location must be unique!')

    @api.constrains('name')
    def _check_name_unique(self):
        for record in self:
            if self.search_count([('id', '!=', record.id), ('name', '=ilike', record.name.strip())]):
                raise ValidationError(self.env._("Location '%s' already exists !", record.name))

    @api.model
    def _search_display_name(self, operator, value):
        # tolerant on spaces: 'Site  A' finds 'Site A'
        if operator == '=' and isinstance(value, str):
            return [('name', '=ilike', value.strip())]
        return super()._search_display_name(operator, value)


class KderpHrEmployeeLocation(models.Model):
    """Where an employee works from a given date (monthly update)."""
    _name = 'kderp.hr.employee.location'
    _description = 'Employee Location Code Model for Monthly update location'
    _order = 'date desc'

    date = fields.Date(required=True)
    month = fields.Char(compute='_compute_month')
    employee_id = fields.Many2one('hr.employee', string='Staff', required=True, ondelete='cascade', index=True)
    location_id = fields.Many2one('kderp.employee.location.code', string='Location', required=True)

    _check_unique_employee_location = models.Constraint('unique(date, employee_id)', 'Staff and Date must be unique')

    @api.depends('date')
    def _compute_month(self):
        for record in self:
            record.month = record.date.strftime('%b-%Y') if record.date else ''

    @api.model
    def get_location_with_date(self, employee_id, date=None):
        """Latest location of an employee on or before date (default today); empty recordset if none."""
        date = date or fields.Date.context_today(self)
        return self.search([('employee_id', '=', employee_id), ('date', '<=', date)], order='date desc', limit=1)
