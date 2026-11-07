from odoo import api, fields, models


class HrEmployee(models.Model):
    """Staff code (unique, searched with the name and shown in front of it), working flag, location history."""
    _inherit = 'hr.employee'
    _rec_names_search = ['name', 'code', 'work_email']

    _code_unique = models.Constraint('unique(code)', 'The staff code must be unique.')

    code = fields.Char(string='Staff Code', index=True, copy=False)
    # Odoo 19 limits the tags to HR users; Odoo 12 let every user read them and the attendance logic reads them as an ordinary user
    # (G8, House Maid, Driver, Outsource, Testing decide OT and leave rules). The same relation is on hr.employee.public.
    category_ids = fields.Many2many(groups='base.group_user')
    working = fields.Boolean(string='Working', default=False)
    working_area_id = fields.Many2one('hr.department', domain=[('type_id.code', '=', 'area')])
    location_ids = fields.One2many('kderp.hr.employee.location', 'employee_id', string='Details')
    current_location_id = fields.Many2one(
        'kderp.employee.location.code', string='Current Location', compute='_compute_current_location', store=True)

    @api.depends('location_ids', 'location_ids.location_id', 'location_ids.date')
    def _compute_current_location(self):
        Location = self.env['kderp.hr.employee.location']
        for employee in self:
            record = Location.get_location_with_date(employee.id) if employee.id else Location
            employee.current_location_id = record.location_id

    @api.depends('code')
    def _compute_display_name(self):
        super()._compute_display_name()
        for employee in self:
            # hr.employee.public (used when the user may not read employees) has no code
            if employee.display_name and employee.sudo().code and not employee.display_name.startswith(employee.sudo().code + ' - '):
                employee.display_name = '%s - %s' % (employee.sudo().code, employee.display_name)
