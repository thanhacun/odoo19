from odoo import api, fields, models


class KderpJobBudgetCache(models.Model):
    """Expense budget lines of a job on the KDERP server, with their remaining balance."""
    _name = 'kderp.job.budget.cache'
    _description = 'Remote Job Budget (KDERP cache)'
    _order = 'budget_code'
    _rec_names_search = ['budget_code', 'name']

    external_id = fields.Integer('Remote Budget ID', required=True, index=True, readonly=True,
                                 help="For tracing only: ids of the two remote budget models can collide.")
    budget_code = fields.Char(required=True, index=True, readonly=True)
    name = fields.Char('Budget Name', required=True, readonly=True)
    balance_amt = fields.Float('Remaining Balance', digits=(16, 0), readonly=True)
    job_id = fields.Many2one('kderp.job.lookup', 'Job', required=True, index=True, ondelete='cascade', readonly=True)

    # Budgets come from two remote models whose ids can collide: one row per job and code
    _job_code_unique = models.Constraint('unique(job_id, budget_code)', 'Budget code must be unique within a job.')

    @api.depends('budget_code', 'name', 'balance_amt')
    def _compute_display_name(self):
        # e.g. "B01 - Materials (45,000,000)"
        for record in self:
            record.display_name = "%s - %s (%s)" % (
                record.budget_code or '', record.name or '', "{:,.0f}".format(record.balance_amt or 0))
