import secrets
from collections import defaultdict

from odoo import _, api, fields, models

PARAM_API_KEY = 'kdvn_website_project.api_key'
PARAM_MIN_AMOUNT = 'kdvn_website_project.min_amount_usd'
DEFAULT_MIN_AMOUNT = 1000000.0


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


def _as_date(value):
    return fields.Date.to_date(value) if value and value != 'False' else False


def _as_name(value):
    """Many2one as sent by Odoo ([id, "Name"]) or a plain string."""
    if isinstance(value, (list, tuple)):
        return value[1] if len(value) > 1 else False
    return value or False


class KdvnWebsiteProjectImport(models.Model):
    """Projects pushed by n8n (finished big jobs read on the KDERP servers).

    n8n posts the jobs to /api/v1/website_projects (controllers/main.py).
    Jobs are grouped by name; projects of at least the minimum amount (USD)
    are created unpublished, existing ones only get their kderp_* fields
    refreshed, so website edits are kept. Odoo 12 module kdvn_website_project
    did the same over XML-RPC; the KDERP servers are only reachable inside
    the company network, hence n8n."""
    _inherit = 'kdvn.website.project'

    @api.model
    def _kdvn_import_jobs(self, jobs):
        """jobs: list of dicts with name, code, state, job_type, date_start,
        completion_date (or actual_completion_date), city_province_id,
        contracted_amount_usd. Returns {'created', 'updated', 'skipped'}."""
        jobs_by_key = defaultdict(list)
        for job in jobs or []:
            if isinstance(job, dict) and (job.get('name') or '').strip():
                jobs_by_key[_project_key(job['name'])].append(job)

        min_amount = float(self.env['ir.config_parameter'].sudo().get_param(PARAM_MIN_AMOUNT) or DEFAULT_MIN_AMOUNT)
        Project = self.sudo().with_context(active_test=False)
        existing = {p.kderp_key: p for p in Project.search([('kderp_key', 'in', list(jobs_by_key))])}
        result = {'created': 0, 'updated': 0, 'skipped': 0}
        now = fields.Datetime.now()
        for key, group in jobs_by_key.items():
            amount = sum(float(job.get('contracted_amount_usd') or 0.0) for job in group)
            starts = [d for d in (_as_date(j.get('date_start')) for j in group) if d]
            ends = [d for d in (_as_date(j.get('completion_date') or j.get('actual_completion_date')) for j in group) if d]
            job_types = sorted({j['job_type'] for j in group if j.get('job_type')})
            cities = [c for c in (_as_name(j.get('city_province_id')) for j in group) if c]
            vals = {
                'kderp_name': ' '.join(group[0]['name'].split()),
                'kderp_job_codes': ', '.join(sorted({j['code'] for j in group if j.get('code')})),
                'kderp_type': '&'.join(job_types),
                'kderp_location': cities[0] if cities else False,
                'kderp_date_start': min(starts) if starts else False,
                'kderp_completion_date': max(ends) if ends else False,
                'kderp_amount_usd': amount,
                'kderp_imported_on': now,
            }
            project = existing.get(key)
            if project:
                project.write(vals)            # website fields untouched
                if not project.year and vals['kderp_completion_date']:
                    project.year = vals['kderp_completion_date'].year
                result['updated'] += 1
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
                result['created'] += 1
            else:
                result['skipped'] += 1
        return result


class ResConfigSettings(models.TransientModel):
    """Settings > Website Projects: API key for n8n, minimum amount."""
    _inherit = 'res.config.settings'

    kdvn_project_api_key = fields.Char('Project Import API Key', config_parameter=PARAM_API_KEY)
    kdvn_project_min_amount = fields.Float(
        'Minimum Contract Amount (USD)', config_parameter=PARAM_MIN_AMOUNT, default=DEFAULT_MIN_AMOUNT,
        help="Imported jobs of the same project are added up; smaller projects are not created.")

    def action_kdvn_generate_project_api_key(self):
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param(PARAM_API_KEY, secrets.token_urlsafe(32))
        return {'type': 'ir.actions.client', 'tag': 'reload'}
