import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from .project_import import _as_name

_logger = logging.getLogger(__name__)

# Finished big jobs of KDERP (Odoo 12). many2one_show_all: KDERP hides closed jobs from searches otherwise.
JOB_DOMAIN = [('state', 'in', ['done', 'closed']), ('job_type', '=', '00-big_job')]
JOB_FIELDS = ['name', 'code', 'state', 'job_type', 'em', 'date_start', 'completion_date',
              'actual_completion_date', 'city_province_id', 'job_amount', 'currency_id']
CHUNK = 500


def _m2o_id(value):
    return value[0] if isinstance(value, (list, tuple)) else value


class KdvnWebsiteProjectPull(models.Model):
    """Read the finished big jobs from KDERP through kdvn_remote_integration (direct, or through the relay when
    this server cannot reach KDERP) and import them like the pushed ones. No n8n logic: which jobs, which fields
    and the exchange rates are all here."""
    _inherit = 'kdvn.website.project'

    @api.model
    def _kdvn_fetch_kderp_jobs(self):
        """Jobs as the import expects them, each with its own exchange rates (currency_rates)."""
        client = self.env['kderp.remote.client']
        jobs = client.execute('account.analytic.account', 'search_read', [JOB_DOMAIN],
                              {'fields': JOB_FIELDS, 'context': {'many2one_show_all': True}}) or []
        ids = [job['id'] for job in jobs]
        rates = {}
        for start in range(0, len(ids), CHUNK):
            lines = client.execute('kderp.job.currency', 'search_read',
                                   [[('account_analytic_id', 'in', ids[start:start + CHUNK])]],
                                   {'fields': ['account_analytic_id', 'currency_id', 'rate']}) or []
            for line in lines:
                currency = _as_name(line.get('currency_id'))
                if currency:
                    rates.setdefault(_m2o_id(line['account_analytic_id']), {})[currency] = line.get('rate')
        for job in jobs:
            job['currency_rates'] = rates.get(job['id'], {})
        return jobs

    @api.model
    def _kdvn_pull_from_kderp(self):
        """Read and import. Returns {'created', 'updated', 'skipped'} (plus 'jobs': how many were read)."""
        jobs = self._kdvn_fetch_kderp_jobs()
        result = self._kdvn_import_jobs(jobs)
        result['jobs'] = len(jobs)
        _logger.info("Project pull from KDERP: %s", result)
        return result

    @api.model
    def _cron_kdvn_pull_from_kderp(self):
        """Daily. Does nothing (no error) when this database has no remote server set up."""
        if not self.env['ir.config_parameter'].sudo().get_param('kderp_remote.url'):
            _logger.info("Project pull from KDERP skipped: no remote server in Settings > Remote Server Connection")
            return
        self._kdvn_pull_from_kderp()
