import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Payload key (role_logins) -> user field on kderp.job.lookup. Same keys as Odoo 12.
ROLE_FIELDS = (
    'general_project_manager_id',
    'area_manager_id',
    'user_id',
    'manager_id',
    'jp_advisor_id',
    'acting_project_manager_id',
    'project_manager_ref',
)
DATE_FIELDS = ('date_start', 'actual_completion_date', 'kickoff_meeting_date')
# Only written when the payload contains the key (the remote server may not send them yet)
OPTIONAL_DATE_FIELDS = ('kom_peak_from', 'kom_peak_to')

SYNC_CACHE_MODELS = ('kderp.job.lookup', 'kderp.job.budget.cache', 'kderp.customer.cache')


def _as_id(value):
    """Remote ids may arrive as 12 or as [12, "Name"] (Odoo many2one read format)."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else False
    return value if isinstance(value, int) and not isinstance(value, bool) else False


def _as_date(value):
    """Odoo 12 sends False (or the string 'False') for empty dates."""
    return value if value and value != 'False' else False


class KderpJobLookup(models.Model):
    """Jobs (projects) of the KDERP server, kept in sync by n8n.

    Odoo 19 version of the Odoo 12 model with the same name (module
    kderp_remote_sync 12.0.1.1.0): same fields and same sync payload.
    """
    _name = 'kderp.job.lookup'
    _description = 'Remote Job (KDERP cache)'
    _order = 'job_no desc'
    _rec_names_search = ['job_no', 'job_name']

    job_no = fields.Char('Job Number', required=True, index=True, readonly=True)
    job_name = fields.Char('Job Name', required=True, readonly=True)
    external_id = fields.Integer('Remote Job ID', required=True, index=True, readonly=True)
    is_general_expense = fields.Boolean('General Expense', readonly=True)

    # Project roles: matched by login to users of this server (empty if the user does not exist here)
    general_project_manager_id = fields.Many2one('res.users', 'General Project Manager (G.M.)')
    area_manager_id = fields.Many2one('res.users', 'Area Manager')
    user_id = fields.Many2one('res.users', 'Project Manager (P.M.)')
    manager_id = fields.Many2one('res.users', 'Section Manager (S.M.)')
    jp_advisor_id = fields.Many2one('res.users', 'JP Advisor')
    acting_project_manager_id = fields.Many2one('res.users', 'Acting Project Manager (A.P.M.)')
    project_manager_ref = fields.Many2one('res.users', 'Sec. Man. / Others')
    view_user_ids = fields.Many2many(
        'res.users', compute='_compute_view_user_ids', store=True, string='All Authorized Viewers',
        help="Everyone in one of the project roles; for record rules of modules using jobs.")

    budget_ids = fields.One2many('kderp.job.budget.cache', 'job_id', 'Budgets', readonly=True)
    owner_id = fields.Many2one('kderp.customer.cache', 'Owner', readonly=True)
    partner_id = fields.Many2one('kderp.customer.cache', 'Client', readonly=True)
    date_start = fields.Date('Start Date', readonly=True)
    actual_completion_date = fields.Date(readonly=True)
    kickoff_meeting_date = fields.Date('K.O.M. Date', readonly=True)
    kom_peak_from = fields.Date('KOM Peak From', readonly=True)
    kom_peak_to = fields.Date('KOM Peak To', readonly=True)
    state = fields.Selection([
        ('doing', 'On-Going'),
        ('done', 'Completed'),
        ('close', 'Closed'),
        ('close_temp', 'Closed (Temp.)'),
        ('cancel', 'Cancelled'),
    ], readonly=True)
    big_job = fields.Boolean(compute='_compute_big_job', store=True,
                             help="9th character of the job number is 0.")

    _external_id_unique = models.Constraint('unique(external_id)', 'A remote job can only be cached once.')

    @api.depends('job_no', 'job_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = "[%s] %s" % (record.job_no or '', record.job_name or '')

    @api.depends(*ROLE_FIELDS)
    def _compute_view_user_ids(self):
        for record in self:
            user_ids = {record[name].id for name in ROLE_FIELDS if record[name]}
            record.view_user_ids = self.env['res.users'].browse(sorted(user_ids))

    @api.depends('job_no')
    def _compute_big_job(self):
        for record in self:
            job_no = record.job_no or ''
            record.big_job = len(job_no) > 8 and job_no[8] == '0'

    # ------------------------------------------------------------------
    # Sync pipeline (called by controllers/main.py)
    # ------------------------------------------------------------------

    @api.model
    def execute_master_sync_pipeline(self, jobs_data=None, budgets_data=None, customers_data=None):
        """Upsert + purge the three caches. Same order and rules as Odoo 12:
        customers, then jobs (they link to customers), then budgets (they link
        to jobs). A list that is empty or missing leaves that cache unchanged.
        Cached records still used by other documents are never purged.
        Returns {"jobs_synced", "budgets_synced", "customers_synced"}."""
        self = self.sudo()
        return {
            'customers_synced': self._sync_customers(customers_data or []),
            'jobs_synced': self._sync_jobs(jobs_data or []),
            'budgets_synced': self._sync_budgets(budgets_data or []),
        }

    @api.model
    def _sync_customers(self, customers_data):
        if not customers_data:
            return 0
        Customer = self.env['kderp.customer.cache'].sudo()
        incoming = {}
        for cust in customers_data:
            ext_id = _as_id(cust.get('partner_id'))
            if ext_id and cust.get('name'):
                incoming[ext_id] = {
                    'external_id': ext_id,
                    'name': cust['name'],
                    'code': cust.get('code') or False,
                    'email': cust.get('email') or False,
                }
        existing = {c.external_id: c for c in Customer.search([('external_id', 'in', list(incoming))])}
        to_create = []
        for ext_id, vals in incoming.items():
            if ext_id in existing:
                existing[ext_id].write(vals)
            else:
                to_create.append(vals)
        Customer.create(to_create)
        self._purge(Customer.search([('external_id', 'not in', list(incoming))]), 'name')
        return len(incoming)

    @api.model
    def _sync_jobs(self, jobs_data):
        if not jobs_data:
            return 0
        jobs = [j for j in jobs_data if j.get('code') and j.get('name') and _as_id(j.get('id'))]

        logins = {
            str(login).strip()
            for j in jobs for login in (j.get('role_logins') or {}).values()
            if login and isinstance(login, (str, int)) and not isinstance(login, bool)
        }
        users = self.env['res.users'].sudo().with_context(active_test=False).search([('login', 'in', list(logins))])
        user_by_login = {u.login: u.id for u in users}

        customer_ext_ids = {_as_id(j.get(key)) for j in jobs for key in ('owner_id', 'partner_id')} - {False}
        customers = self.env['kderp.customer.cache'].sudo().search([('external_id', 'in', list(customer_ext_ids))])
        customer_by_ext = {c.external_id: c.id for c in customers}

        # Match by remote id; fall back to the job number (Odoo 12 matched on the number)
        ext_ids = [_as_id(j['id']) for j in jobs]
        existing = self.search(['|', ('external_id', 'in', ext_ids), ('job_no', 'in', [j['code'] for j in jobs])])
        by_ext = {j.external_id: j for j in existing}
        by_code = {j.job_no: j for j in existing}

        to_create = []
        for job in jobs:
            ext_id = _as_id(job['id'])
            roles = job.get('role_logins') or {}
            vals = {
                'external_id': ext_id,
                'job_no': job['code'],
                'job_name': job['name'],
                'is_general_expense': bool(job.get('general_expense')),
                'owner_id': customer_by_ext.get(_as_id(job.get('owner_id')), False),
                'partner_id': customer_by_ext.get(_as_id(job.get('partner_id')), False),
                'state': job.get('state') or False,
            }
            for name in ROLE_FIELDS:
                login = roles.get(name)
                vals[name] = user_by_login.get(str(login).strip(), False) if login else False
            for name in DATE_FIELDS:
                vals[name] = _as_date(job.get(name))
            for name in OPTIONAL_DATE_FIELDS:
                if name in job:
                    vals[name] = _as_date(job[name])

            record = by_ext.get(ext_id) or by_code.get(job['code'])
            if record:
                record.write(vals)
            else:
                to_create.append(vals)
        self.create(to_create)

        stale = self.search([('external_id', 'not in', ext_ids)])
        # A job whose budget lines are used must stay too (deleting a job deletes its budgets)
        keep = self._records_in_use(stale.budget_ids).job_id & stale
        self._purge(stale, 'job_no', keep=keep)
        return len(jobs)

    @api.model
    def _sync_budgets(self, budgets_data):
        if not budgets_data:
            return 0
        Budget = self.env['kderp.job.budget.cache'].sudo()
        job_ext_ids = {_as_id(b.get('job_id')) for b in budgets_data} - {False}
        job_by_ext = {j.external_id: j.id for j in self.search([('external_id', 'in', list(job_ext_ids))])}

        incoming = {}
        for bgt in budgets_data:
            ext_id = _as_id(bgt.get('id'))
            job_id = job_by_ext.get(_as_id(bgt.get('job_id')))
            if not ext_id or not bgt.get('budget_code') or not job_id:
                continue
            incoming[ext_id] = {
                'external_id': ext_id,
                'budget_code': bgt['budget_code'],
                'name': bgt.get('name') or bgt['budget_code'],
                'balance_amt': bgt.get('balance_amt') or 0.0,
                'job_id': job_id,
            }
        existing = {b.external_id: b for b in Budget.search([('external_id', 'in', list(incoming))])}
        to_create = []
        for ext_id, vals in incoming.items():
            if ext_id in existing:
                existing[ext_id].write(vals)
            else:
                to_create.append(vals)
        Budget.create(to_create)

        # Odoo 12 kept every budget id present in the payload, even lines it skipped
        payload_ids = [i for i in (_as_id(b.get('id')) for b in budgets_data) if i]
        self._purge(Budget.search([('external_id', 'not in', payload_ids)]), 'budget_code')
        return len(incoming)

    @api.model
    def _purge(self, stale, label_field, keep=None):
        """Delete cached records no longer sent by the remote server, except
        those other documents still point to."""
        if not stale:
            return
        keep = (keep or stale.browse()) | self._records_in_use(stale)
        if keep:
            _logger.warning("Remote sync: keeping %s stale %s still in use: %s",
                            len(keep), stale._name, ', '.join(map(str, keep.mapped(label_field))))
        to_delete = stale - keep
        if to_delete:
            _logger.info("Remote sync: deleting %s stale %s", len(to_delete), stale._name)
            to_delete.unlink()

    @api.model
    def _records_in_use(self, records):
        """Part of `records` that any other model still points to (stored
        many2one / many2many fields of real models). Links between the cache
        models themselves are ignored. Covers modules added later without
        changing this code."""
        used = records.browse()
        if not records:
            return used
        model_fields = self.env['ir.model.fields'].sudo().search([
            ('relation', '=', records._name),
            ('ttype', 'in', ('many2one', 'many2many')),
            ('store', '=', True),
            ('model', 'not in', list(SYNC_CACHE_MODELS)),
        ])
        for model_field in model_fields:
            if model_field.model not in self.env:
                continue
            Holder = self.env[model_field.model]
            field = Holder._fields.get(model_field.name)
            if Holder._abstract or Holder._transient or not Holder._auto or not field or not field.store:
                continue
            holders = Holder.sudo().with_context(active_test=False).search([(model_field.name, 'in', records.ids)])
            used |= holders.mapped(model_field.name) & records
        return used
