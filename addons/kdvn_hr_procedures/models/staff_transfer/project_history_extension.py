from odoo import models, fields, api

class ProjectHistory(models.Model):
    _inherit = 'hr.employee.project.history'

    project_code = fields.Many2one(
        comodel_name='kderp.job.lookup',
        string='Project Code',
        index=True,
        help="Remote synchronized project job database identifier"
    )
    project_name = fields.Char(
        compute='_compute_project_name',
        string='Project Name',
        store=True,
        required=False,
        help="Derived job name from remote lookup tracking tables"
    )

    @api.depends('project_code', 'project_code.job_name')
    def _compute_project_name(self):
        for rec in self:
            if rec.project_code:
                rec.project_name = rec.project_code.job_name
            else:
                rec.project_name = False

    @api.model_create_multi
    def create(self, vals_list):
        # The base column is NOT NULL but a stored compute only fills it after the INSERT
        fixed = []
        for vals in vals_list:
            if not vals.get('project_name') and vals.get('project_code'):
                vals = dict(vals, project_name=self.env['kderp.job.lookup'].browse(vals['project_code']).job_name or '-')
            fixed.append(vals)
        return super(ProjectHistory, self).create(fixed)
