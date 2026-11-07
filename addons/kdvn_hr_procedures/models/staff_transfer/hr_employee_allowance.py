from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    transfer_allowance_grade_id = fields.Many2one(
        'transfer.allowance.grade', string='Allowance Grade',
        compute='_compute_transfer_allowance_grade',
        help='From the employee tags: the grade whose tag (e.g. G8) is on the employee.')

    @api.depends('category_ids')
    def _compute_transfer_allowance_grade(self):
        grades = self.env['transfer.allowance.grade'].sudo().search([('category_id', '!=', False)])
        by_tag = {g.category_id.id: g for g in grades}
        for emp in self:
            match = [by_tag[t.id] for t in emp.category_ids if t.id in by_tag]
            # Several grade tags on one employee is a data error; take the lowest sequence.
            match.sort(key=lambda g: (g.sequence, g.code))
            emp.transfer_allowance_grade_id = match[0].id if match else False

    def get_transfer_allowance(self, band, on_date=None):
        """Rate line (transfer.allowance.matrix) for this employee's grade and the given
        band (record, id or code such as 'S04'); empty when not entitled or no grade tag."""
        self.ensure_one()
        Matrix = self.env['transfer.allowance.matrix']
        if not self.transfer_allowance_grade_id:
            return Matrix.browse()
        return Matrix.get_rate(self.transfer_allowance_grade_id, band, on_date)
