"""Pull jobs, budgets and customers from the KDERP server straight into the cache tables (alternative to the n8n push).

Port of kderp_remote_sync 12.0.1.5.0 `models/remote_pull.py` (same reads, same payload).

Same reads and the same payload as the n8n workflow `n8n/oe_hanoi_active_job_list.json`; the payload goes to the unchanged
`kderp.job.lookup.execute_master_sync_pipeline` (upsert + safe purge). Reads only, with the Reader login of `kdvn_remote_integration`,
so there is no live switch; the two crons ship INACTIVE and are switched on by hand. A restored copy of the database is safe: the
neutralize script blanks the remote settings and switches every cron off.

Two runs:
  * full run (hourly, like n8n): customers + jobs + budgets, with purge.
  * customer run (every 5 minutes): only customers changed since the last run (`write_date`), upsert only, no purge, so the
    customer list follows the remote within minutes. It reads a handful of rows, so the load on the remote is negligible.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_SINCE = 'kdvn_remote_sync.customer_since'     # newest customer write_date seen on the remote (UTC)
PARAM_STATUS = 'kdvn_remote_sync.pull_status'       # last result, shown on the settings page
LOCK_KEY = 4710231                                   # advisory lock: one pull at a time
OVERLAP = timedelta(minutes=10)                      # a long transaction on the remote can commit late with an old write_date
ROLE_FIELDS = ['general_project_manager_id', 'area_manager_id', 'user_id', 'manager_id', 'jp_advisor_id',
               'acting_project_manager_id', 'project_manager_ref']
BUDGET_CODES = [4082, 8000, 7000]
FIXED_COST_PRODUCTS = ['8100A21', '4082', '7000A21']


def _m2o_id(value):
    """Remote many2one ([id, name] or False) -> id or None."""
    return value[0] if isinstance(value, (list, tuple)) and value else None


def _split(label):
    """'4082 - Entertainment' -> ('4082', 'Entertainment'); no ' - ' -> (label, label)."""
    parts = (label or '').split(' - ')
    return parts[0].strip(), (parts[1] if len(parts) > 1 else parts[0]).strip()


class KderpRemotePull(models.AbstractModel):
    _name = 'kderp.remote.pull'
    _description = 'Pull of jobs, budgets and customers from the remote server'

    # ------------------------------------------------------------------ reads (Reader login)
    @api.model
    def _read(self, model, domain, fields_, context=None):
        return self.env['kderp.remote.client'].execute(
            model, 'search_read', [domain], {'fields': fields_, 'context': context or {}}, account='reader') or []

    @api.model
    def read_customers(self, since=None):
        """Customers as the pipeline expects them, plus the newest write_date seen (None when nothing came)."""
        domain = [['customer', '=', True], ['active', '=', True]]
        if since:
            domain.append(['write_date', '>=', fields.Datetime.to_string(since)])
        rows = self._read('res.partner', domain, ['id', 'name', 'code', 'email', 'write_date'])
        newest = max([r['write_date'] for r in rows if r.get('write_date')] or [None])
        customers = [{'partner_id': r['id'], 'name': r['name'], 'code': r.get('code') or '', 'email': r.get('email') or ''}
                     for r in rows]
        return customers, newest

    @api.model
    def read_jobs(self):
        jobs = self._read('account.analytic.account', [['state', 'in', ['doing', 'done']]],
                          ['id', 'name', 'code', 'general_expense'] + ROLE_FIELDS +
                          ['partner_id', 'owner_id', 'date_start', 'actual_completion_date', 'kickoff_meeting_date',
                           'est_peak_time_from', 'est_peak_time_to', 'state'],
                          {'import_ge_nofilter': True})
        user_ids = sorted({_m2o_id(j.get(f)) for j in jobs for f in ROLE_FIELDS if _m2o_id(j.get(f))})
        logins = {}
        if user_ids:
            logins = {u['id']: u['login'] for u in self._read('res.users', [['id', 'in', user_ids]], ['login']) if u.get('login')}
        result = []
        for j in jobs:
            result.append({
                'id': j['id'], 'name': j['name'], 'code': j['code'],
                'general_expense': j.get('general_expense') or False,
                'role_logins': {f: logins[_m2o_id(j.get(f))] for f in ROLE_FIELDS if _m2o_id(j.get(f)) in logins},
                'owner_id': _m2o_id(j.get('owner_id')), 'partner_id': _m2o_id(j.get('partner_id')),
                'date_start': j.get('date_start'), 'actual_completion_date': j.get('actual_completion_date'),
                'kickoff_meeting_date': j.get('kickoff_meeting_date'),
                'kom_peak_from': j.get('est_peak_time_from'), 'kom_peak_to': j.get('est_peak_time_to'),
                'state': j.get('state'),
            })
        return result

    @api.model
    def read_budgets(self):
        budgets = []
        for row in self._read('kderp.budget.data', [['account_analytic_id', '!=', False], ['budget_code', 'in', BUDGET_CODES]],
                              ['budget_code', 'display_name', 'balance_amt', 'account_analytic_id']):
            # display_name looks like '<job> - <budget name>': the name is the second part
            parts = (row.get('display_name') or '').split(' - ')
            name = (parts[1] if len(parts) > 1 else (row.get('display_name') or '')).strip()
            budgets.append({'id': row['id'], 'budget_code': str(row['budget_code']), 'name': name,
                            'balance_amt': row.get('balance_amt'), 'job_id': row['account_analytic_id']})
        for row in self._read('kderp.fixed.cost.data', [['product_budget_id.default_code', 'in', FIXED_COST_PRODUCTS]],
                              ['account_analytic_id', 'product_budget_id', 'balance_amt']):
            if not row.get('product_budget_id'):
                continue
            code, name = _split(row['product_budget_id'][1])
            budgets.append({'id': row['id'], 'budget_code': code, 'name': name,
                            'balance_amt': row.get('balance_amt'), 'job_id': row.get('account_analytic_id')})
        return budgets

    # ------------------------------------------------------------------ runs
    @api.model
    def _lock(self):
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_KEY,))
        return self.env.cr.fetchone()[0]

    @api.model
    def _set_cursor(self, newest):
        """Remember the newest remote write_date; never move backwards."""
        if not newest:
            return
        icp = self.env['ir.config_parameter'].sudo()
        old = icp.get_param(PARAM_SINCE) or ''
        if newest > old:
            icp.set_param(PARAM_SINCE, newest)

    @api.model
    def run_full(self):
        """Customers + jobs + budgets with purge. All three are read BEFORE anything is written, so a failed read changes nothing."""
        if not self._lock():
            return {'skipped': 'another pull is running'}
        customers, newest = self.read_customers()
        jobs = self.read_jobs()
        budgets = self.read_budgets()
        result = self.env['kderp.job.lookup'].sudo().execute_master_sync_pipeline(
            jobs_data=jobs, budgets_data=budgets, customers_data=customers)
        self._set_cursor(newest)
        return result

    @api.model
    def run_customers(self):
        """Customers changed on the remote since the last run: upsert only (a customer that was archived or lost its customer flag
        is removed by the next full run). With no cursor yet (first run) a full run sets it."""
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_SINCE)
        if not raw:
            return self.run_full()
        if not self._lock():
            return {'skipped': 'another pull is running'}
        customers, newest = self.read_customers(since=fields.Datetime.from_string(raw) - OVERLAP)
        result = {'jobs_synced': 0, 'budgets_synced': 0, 'customers_synced': 0}
        if customers:
            result = self.env['kderp.job.lookup'].sudo().execute_master_sync_pipeline(customers_data=customers, purge=False)
        self._set_cursor(newest)
        return result

    # ------------------------------------------------------------------ cron entry points
    @api.model
    def _guarded(self, run):
        """A remote that is down is normal now and then: log it, keep the cache as it is, show it on the settings page."""
        icp = self.env['ir.config_parameter'].sudo()
        stamp = fields.Datetime.to_string(fields.Datetime.now())
        try:
            with self.env.cr.savepoint():           # a failure undoes whatever the run had written
                result = run()
        except UserError as e:
            message = str(e)
            _logger.warning("Remote pull failed, cache left as it was: %s", message)
            icp.set_param(PARAM_STATUS, '%s UTC - FAILED: %s' % (stamp, message))
            return False
        icp.set_param(PARAM_STATUS, '%s UTC - ok: %s' % (stamp, result))
        return result

    @api.model
    def cron_full(self):
        return self._guarded(self.run_full)

    @api.model
    def cron_customers(self):
        return self._guarded(self.run_customers)
