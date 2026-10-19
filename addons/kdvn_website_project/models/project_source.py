import http.client
import logging
import xmlrpc.client
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_MIN_AMOUNT = 'kdvn_website_project.min_amount_usd'
DEFAULT_MIN_AMOUNT = 1000000.0
RPC_TIMEOUT = 60      # seconds per call
BATCH_SIZE = 1000     # records per read (as in Odoo 12)

# Jobs that count as finished big projects on the KDERP/OpenERP servers
# (same filter as the Odoo 12 module kdvn_website_project)
JOB_DOMAIN = [('state', 'in', ['done', 'closed']), ('job_scale', '=', '00-big_job')]
JOB_FIELDS = ['name', 'code', 'state', 'job_type', 'date_start', 'completion_date',
              'city_province_id', 'contracted_amount_usd', 'write_date']


class _TimeoutTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = RPC_TIMEOUT
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = RPC_TIMEOUT
        return conn


def _project_key(name):
    """Jobs with the same name (case and spaces ignored) form one project."""
    return ' '.join((name or '').split()).upper()


def _project_type(job_types):
    """{'E'} -> electrical, {'M'} -> mechanical, E and M / 'M&E' -> me."""
    letters = set()
    for job_type in job_types:
        letters |= {c for c in (job_type or '').upper() if c in 'EM'}
    if letters == {'E'}:
        return 'electrical'
    if letters == {'M'}:
        return 'mechanical'
    if letters == {'E', 'M'}:
        return 'me'
    return 'other' if job_types else False


class KdvnWebsiteProjectSource(models.Model):
    """A KDERP/OpenERP server to import finished big jobs from (XML-RPC).

    Replaces the Odoo 12 setting `website.servers_json`. Reading needs a user
    on that server with read access to account.analytic.account."""
    _name = 'kdvn.website.project.source'
    _description = 'Website Project Import Source'
    _order = 'sequence, id'

    name = fields.Char(required=True, help="e.g. 'Hanoi OpenERP'.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    url = fields.Char('Server URL', required=True, help="e.g. https://erp-hn.kinden.com.vn (reachable from this Odoo server).")
    db = fields.Char('Database', required=True)
    login = fields.Char(required=True)
    password = fields.Char(groups='base.group_system', copy=False)
    last_import_date = fields.Datetime(
        'Imported Up To', readonly=True, copy=False,
        help="Jobs changed after this moment are read at the next import. Clear it to read everything again.")
    last_message = fields.Char('Last Result', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # XML-RPC
    # ------------------------------------------------------------------

    def _rpc(self, service):
        self.ensure_one()
        url = self.url.rstrip('/')
        transport = _TimeoutSafeTransport() if url.startswith('https') else _TimeoutTransport()
        return xmlrpc.client.ServerProxy('%s/xmlrpc/2/%s' % (url, service), transport=transport, allow_none=True)

    def _rpc_login(self):
        self.ensure_one()
        uid = self._rpc('common').authenticate(self.db, self.login, self.sudo().password or '', {})
        if not uid:
            raise UserError(_("%s: login refused (check database, login and password).", self.name))
        return uid

    def _rpc_search_read(self, domain, fields_to_read):
        """search + read in batches of 1000 (works on OpenERP 7 and later)."""
        self.ensure_one()
        uid = self._rpc_login()
        models_proxy = self._rpc('object')
        password = self.sudo().password or ''
        ids = models_proxy.execute_kw(self.db, uid, password, 'account.analytic.account', 'search', [domain])
        records = []
        for start in range(0, len(ids), BATCH_SIZE):
            records += models_proxy.execute_kw(
                self.db, uid, password, 'account.analytic.account', 'read',
                [ids[start:start + BATCH_SIZE]], {'fields': fields_to_read})
        return records

    def action_test_connection(self):
        self.ensure_one()
        try:
            count = len(self._rpc_search_read(JOB_DOMAIN, ['name']))
        except Exception as e:  # noqa: BLE001  (show any connection problem to the admin)
            raise UserError(_("Connection to %(name)s failed: %(error)s", name=self.name, error=e)) from e
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': _("Connection OK"),
                       'message': _("%s finished big jobs found.", count)},
        }

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def action_import_now(self):
        result = self.env['kdvn.website.project.source']._kdvn_import()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'warning' if result['errors'] else 'success', 'sticky': bool(result['errors']),
                       'title': _("Project import"),
                       'message': _("%(created)s new, %(updated)s updated. %(errors)s",
                                    created=result['created'], updated=result['updated'],
                                    errors='; '.join(result['errors']))},
        }

    @api.model
    def _kdvn_cron_import(self):
        self._kdvn_import()

    @api.model
    def _kdvn_import(self):
        """Import finished big jobs from all active sources (port of Odoo 12
        kdvn.publish.project.handle_data):

        1. per source, find jobs changed since its last import;
        2. read ALL finished big jobs with those names on every source, so a
           project made of several jobs is always computed from all of them;
        3. group by name, keep projects of at least the minimum amount (USD);
        4. create (unpublished) or refresh the kderp_* fields.
        """
        sources = self.search([])
        result = {'created': 0, 'updated': 0, 'errors': []}
        started = fields.Datetime.now()

        changed_names, ok_sources = set(), self.browse()
        for source in sources:
            domain = list(JOB_DOMAIN)
            if source.last_import_date:
                domain.append(('write_date', '>', fields.Datetime.to_string(source.last_import_date)))
            try:
                jobs = source._rpc_search_read(domain, ['name'])
            except Exception as e:  # noqa: BLE001  (one failing server must not stop the others)
                _logger.warning("Project import: %s failed: %s", source.name, e)
                source.last_message = _("Failed: %s", e)
                result['errors'].append('%s: %s' % (source.name, e))
                continue
            changed_names |= {job['name'].strip() for job in jobs if (job.get('name') or '').strip()}
            ok_sources |= source

        if changed_names:
            jobs_by_key = defaultdict(list)
            names = sorted(changed_names)
            for source in ok_sources:
                try:
                    # same-name jobs on every server (=ilike: case-insensitive)
                    for start in range(0, len(names), 200):
                        chunk = names[start:start + 200]
                        domain = list(JOB_DOMAIN) + ['|'] * (len(chunk) - 1) + [('name', '=ilike', n) for n in chunk]
                        for job in source._rpc_search_read(domain, JOB_FIELDS):
                            jobs_by_key[_project_key(job['name'])].append(job)
                except Exception as e:  # noqa: BLE001
                    _logger.warning("Project import: %s failed: %s", source.name, e)
                    source.last_message = _("Failed: %s", e)
                    result['errors'].append('%s: %s' % (source.name, e))
                    ok_sources -= source
            counts = self.env['kdvn.website.project']._kdvn_apply_import(jobs_by_key)
            result['created'], result['updated'] = counts

        for source in ok_sources:
            source.write({'last_import_date': started,
                          'last_message': _("OK: %(n)s changed job names", n=len(changed_names))})
        return result


class KdvnWebsiteProjectImport(models.Model):
    _inherit = 'kdvn.website.project'

    @api.model
    def _kdvn_apply_import(self, jobs_by_key):
        """jobs_by_key: {project key: [job dicts]} -> (created, updated)."""
        min_amount = float(self.env['ir.config_parameter'].sudo().get_param(PARAM_MIN_AMOUNT, DEFAULT_MIN_AMOUNT))
        Project = self.sudo().with_context(active_test=False)
        existing = {p.kderp_key: p for p in Project.search([('kderp_key', 'in', list(jobs_by_key))])}
        created = updated = 0
        now = fields.Datetime.now()
        for key, jobs in jobs_by_key.items():
            if not key or not jobs:
                continue
            amount = sum(job.get('contracted_amount_usd') or 0.0 for job in jobs)
            starts = [fields.Date.to_date(j['date_start']) for j in jobs if j.get('date_start')]
            ends = [fields.Date.to_date(j['completion_date']) for j in jobs if j.get('completion_date')]
            job_types = sorted({j['job_type'] for j in jobs if j.get('job_type')})
            cities = [j['city_province_id'][1] for j in jobs
                      if isinstance(j.get('city_province_id'), (list, tuple)) and len(j['city_province_id']) > 1]
            vals = {
                'kderp_name': ' '.join(jobs[0]['name'].split()),
                'kderp_job_codes': ', '.join(sorted({j['code'] for j in jobs if j.get('code')})),
                'kderp_type': '&'.join(job_types),
                'kderp_location': cities[0] if cities else False,
                'kderp_date_start': min(starts) if starts else False,
                'kderp_completion_date': max(ends) if ends else False,
                'kderp_amount_usd': amount,
                'kderp_imported_on': now,
            }
            project = existing.get(key)
            if project:
                project.write(vals)        # website fields untouched
                if not project.year and vals['kderp_completion_date']:
                    project.year = vals['kderp_completion_date'].year
                updated += 1
            elif amount >= min_amount:
                Project.create(dict(
                    vals,
                    kderp_key=key,
                    name=vals['kderp_name'],
                    year=vals['kderp_completion_date'].year if vals['kderp_completion_date'] else False,
                    area='%s, Vietnam' % vals['kderp_location'] if vals['kderp_location'] else False,
                    project_type=_project_type(job_types),
                    is_published=False,
                ))
                created += 1
        return created, updated
