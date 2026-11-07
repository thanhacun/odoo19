from odoo import models, fields


class KderpJobLookup(models.Model):
    _inherit = 'kderp.job.lookup'

    # KOM Peak From date the peak time reminder was last sent for (a changed date sends again)
    peak_time_reminder_sent_for = fields.Date(readonly=True, copy=False)
