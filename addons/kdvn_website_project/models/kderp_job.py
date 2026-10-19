from odoo import fields, models


class KderpJobLookup(models.Model):
    _inherit = 'kderp.job.lookup'

    website_project_ids = fields.Many2many(
        'kdvn.website.project', 'kdvn_website_project_job_rel', 'job_id', 'project_id', string='Website Projects')

    def action_kdvn_create_website_project(self):
        """Create one (unpublished) website project from the selected jobs."""
        first = self.sorted(lambda j: j.actual_completion_date or j.date_start or fields.Date.today(), reverse=True)[:1]
        project = self.env['kdvn.website.project'].create({
            'name': first.job_name or first.job_no,
            'job_ids': [fields.Command.set(self.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'kdvn.website.project',
            'res_id': project.id,
            'view_mode': 'form',
            'target': 'current',
        }
