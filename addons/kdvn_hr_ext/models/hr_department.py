import datetime
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

AREA_CODE = re.compile(r'^[A-Z][A-Z][0-9][0-9]$')
VISIBLE_MEMBERS = ['|', ('working', '=', True), '&', ('working', '=', False), ('code', 'ilike', 'S9')]


class HrDepartment(models.Model):
    """The 1st manager follows the manager history (latest line that is effective); members are functional or administrative."""
    _inherit = 'hr.department'

    manager_id = fields.Many2one(string='1st Manager', compute='_compute_1st_manager', store=True, readonly=True)
    manager_history_ids = fields.One2many('hr.manager.history', 'department_id')
    admin_member_ids = fields.One2many('hr.employee', 'admin_dept_id', string='Admin. Members', readonly=True, domain=VISIBLE_MEMBERS)
    member_ids = fields.One2many(domain=VISIBLE_MEMBERS)
    member_count = fields.Integer(compute='_compute_member_count')
    area_id = fields.Many2one('hr.department', compute='_compute_area', store=True)

    @api.depends('manager_history_ids.manager_id', 'manager_history_ids.effective_date')
    def _compute_1st_manager(self):
        today = fields.Date.context_today(self)
        for department in self:
            # newest effective line (sorted here: lines created in this transaction sit at the end of the cached list)
            current = department.manager_history_ids.filtered(lambda h: h.effective_date <= today).sorted('effective_date', reverse=True)[:1]
            department.manager_id = current.manager_id

    @api.depends('member_ids', 'admin_member_ids')
    def _compute_member_count(self):
        for department in self:
            department.member_count = len(department.member_ids | department.admin_member_ids)

    @api.constrains('manager_id', 'manager_2nd_id')
    def _check_manager_id(self):
        for department in self:
            if department.manager_id and department.manager_id == department.manager_2nd_id:
                raise ValidationError(self.env._('The 2nd manager must NOT be the same with the 1st one!'))

    @api.depends('parent_id', 'parent_id.code')
    def _compute_area(self):
        """Area = the department whose code is the first 4 letters of the parent code (pattern AA99)."""
        for department in self:
            area = self.browse()
            code = department.parent_id.code
            if code and AREA_CODE.match(code[:4]):
                found = self.search([('code', '=', code[:4])])
                area = found if len(found) == 1 else area
            department.area_id = area

    def _change_to_effective_manager(self):
        """A pending new manager becomes a manager history line; the 1st manager then follows the history."""
        today = datetime.date.today()
        for department in self:
            if department.new_manager and department.new_man_effective_date and department.new_man_effective_date <= today:
                self.env['hr.manager.history'].create({
                    'department_id': department.id,
                    'manager_id': department.new_manager.id,
                    'effective_date': department.new_man_effective_date,
                })
                department.write({'new_manager': False, 'new_man_effective_date': False})

    def compute_manager_by_date(self, ref_date):
        """Manager of the department around ref_date (the first manager if ref_date is before all history)."""
        self.ensure_one()
        History = self.env['hr.manager.history']
        line = History.search([('department_id', '=', self.id), ('effective_date', '<=', ref_date)], order='effective_date desc', limit=1)
        line = line or History.search([('department_id', '=', self.id)], order='effective_date asc', limit=1)
        return line.manager_id

    @api.model
    def _cron_refresh_manager(self):
        self.search([('manager_history_ids', '!=', False)])._compute_1st_manager()
