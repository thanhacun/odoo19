"""Who can continue the advance request on the remote server (the advance's "Input User").

Findings from the remote data (Nov 2026, 117 entertainment advances since 2025):
  * the Input User, not the applicant, creates the advance (116 of 117);
  * only 13% of the jobs have a Site Admin list, and even where it exists the Input User is one of
    its members in 74% of the advances;
  * the best predictor is history: who entered the previous advance on the same job (90% right on jobs without
    a site admin), who usually enters this applicant's advances (85%), then the job's project manager, then the office;
  * Input Users work in teams: the remote rule gives every member of a "Filter Advance Payment By Location - <team>"
    group the advances of the other members.

Who is eligible: active user + employee record + an office with a code letter ('Global' has none) + the "User Input" right on
advance requests. No group is required: the people come from the job's own list or from history, so they are proven input users
(site admins, team members, "Manage a Location" people in Hai Phong and the Advance Cash Admin / Submit people all qualify).

So the dialog lists, in this order, each person with the reason(s):
  1. the job's site admins (all of them),
  2. people who entered earlier advances on THIS job (most frequent first),
  3. people who usually enter THIS applicant's advances (last year),
  4. only if the list is still short: the job's project manager's usual input users, then the applicant's office's.
The first person who can really process it is suggested (preselected); the applicant can pick another one.
Everything here is a READ on the remote (read_group / read / search_read).
"""
import logging
from collections import OrderedDict
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# remote xml ids (module, name)
GROUP_USER_INPUT = ('kderp_advance_payment', 'group_kderp_advance_management_menu_user_input')
GROUP_SITE_ADMIN = ('kderp_rule', 'group_kderp_adv_site_admin')
GROUP_MANAGE_LOCATION = ('kderp_rule', 'group_rule_adv_manage_location')   # "Filter Advance Payment - Manage a Location"
GROUP_SUBMIT = ('kderp_advance_payment', 'group_kderp_advance_workflow')   # "KDERP - Advance Cash / Submit"
GROUP_ADMIN = ('kderp_advance_payment', 'group_kderp_advance_admin')       # "KDERP - Advance Cash / Admin" (implies Submit > User Input)
TEAM_GROUP_PREFIX = 'Filter Advance Payment By Location'                   # team groups: ... - TLIP 1 Input, ...
# Shown as "Remote role" in the list (information only, not a condition)
ROLE_LABELS = [('Site admin', GROUP_SITE_ADMIN), ('Manage a Location', GROUP_MANAGE_LOCATION), ('Advance Cash Admin', GROUP_ADMIN),
               ('Advance Cash Submit', GROUP_SUBMIT)]

HISTORY_DAYS = 365      # applicant / project manager / office history
PICK = 3                # people taken from each history
MIN_ROWS = 3            # project manager and office history are only read when the list is shorter than this
MAX_ROWS = 6            # history rows are added until the list has this many rows (all job admins are always shown)

SOURCE_ORDER = ('job', 'applicant', 'pm', 'office')


class EntertainmentRequest(models.Model):
    _inherit = 'entertainment.request'

    # ------------------------------------------------------------------ small remote reads
    def _remote_history(self, domain):
        """{remote employee id: number of advance requests} for `domain`, counted per Input User."""
        groups = self._remote('kderp.advance.payment', 'read_group',
                              [list(domain) + [('user_input', '!=', False)], ['user_input'], ['user_input']], {'lazy': False})
        res = {}
        for g in groups:
            if g.get('user_input'):
                res[g['user_input'][0]] = g.get('__count') or 0
        return res

    @staticmethod
    def _top(hist, k=PICK):
        return sorted(hist.items(), key=lambda x: (-x[1], x[0]))[:k]

    def _remote_group_ids(self):
        """{(module, name): remote group id} for the groups the rules use, and {id: team label} for the team groups."""
        wanted = [GROUP_USER_INPUT] + [g for label, g in ROLE_LABELS]
        rows = self._remote('ir.model.data', 'search_read',
                            [[('module', 'in', sorted({m for m, n in wanted})), ('name', 'in', sorted({n for m, n in wanted}))]],
                            {'fields': ['module', 'name', 'res_id']})
        ids = {(r['module'], r['name']): r['res_id'] for r in rows if (r['module'], r['name']) in wanted}
        teams = self._remote('res.groups', 'search_read', [[('name', 'ilike', TEAM_GROUP_PREFIX)]], {'fields': ['name']})
        labels = {t['id']: (t['name'] or '').split(' - ', 1)[-1].strip() for t in teams}
        return ids, labels

    # ------------------------------------------------------------------ the candidates
    def _remote_input_candidates(self, meta=None):
        """Ordered list of dicts (one per person), each with `ok`, `reason`, `why`, `team`, `roles`, `suggested`, `is_admin`.

        `meta` (optional dict) is filled with what was read, for the explanation shown in the dialog."""
        self.ensure_one()
        meta = {} if meta is None else meta
        job = self.job_id
        rj = self._remote('account.analytic.account', 'read', [[job.external_id], ['code', 'site_admin_users', 'user_id']],
                          {'context': {'import_ge_nofilter': True}})
        if not rj or (rj[0].get('code') or '') != job.job_no:
            raise UserError(_("Job %s was not found on the remote server under the same number. "
                              "Refresh the job list (Force Sync) and try again.") % job.job_no)
        admin_user_ids = list(rj[0].get('site_admin_users') or [])
        pm_user = rj[0].get('user_id') and rj[0]['user_id'][0] or False
        applicant = self._remote_applicant()
        meta.update({'job_no': job.job_no, 'applicant': applicant.get('name') or '', 'n_admins': len(admin_user_ids), 'days': HISTORY_DAYS,
                     'pm_name': rj[0].get('user_id') and rj[0]['user_id'][1] or ''})
        since = fields.Date.to_string(fields.Date.context_today(self) - timedelta(days=HISTORY_DAYS))

        # --- histories (employee id -> count)
        job_hist = self._remote_history([('account_analytic_id', '=', job.external_id)])
        app_hist = self._remote_history([('user_id', '=', applicant['id']), ('date', '>=', since)])
        meta['job'] = (len(job_hist), sum(job_hist.values()))
        meta['applicant_hist'] = (len(app_hist), sum(app_hist.values()))
        picks = OrderedDict([('job', self._top(job_hist)), ('applicant', self._top(app_hist)), ('pm', []), ('office', [])])
        known = {e for src in ('job', 'applicant') for e, n in picks[src]}
        meta['pm'] = meta['office'] = None            # None = not read
        meta['pm_state'] = meta['office_state'] = 'skipped'   # skipped: enough people already; no_pm / no_office: nothing to read
        if len(admin_user_ids) + len(known) < MIN_ROWS:
            if pm_user:
                pm_hist = self._remote_history([('account_analytic_id.user_id', '=', pm_user), ('date', '>=', since)])
                picks['pm'] = self._top(pm_hist)
                meta['pm'] = (len(pm_hist), sum(pm_hist.values()))
                meta['pm_state'] = 'read'
            else:
                meta['pm_state'] = 'no_pm'
            known |= {e for e, n in picks['pm']}
        if len(admin_user_ids) + len(known) < MIN_ROWS:
            loc = False
            if applicant.get('user_id'):
                au = self._remote('res.users', 'read', [[applicant['user_id'][0]], ['location_user_id']])
                loc = au and au[0].get('location_user_id')
            if loc:
                office_hist = self._remote_history([('location_id', '=', loc[0]), ('date', '>=', since)])
                picks['office'] = self._top(office_hist)
                meta['office'] = (len(office_hist), sum(office_hist.values()), loc[1])
                meta['office_state'] = 'read'
            else:
                meta['office_state'] = 'no_office'

        # --- who are these people (one read each)
        hist_emp_ids = sorted({e for src in SOURCE_ORDER for e, n in picks[src]})
        emps = {e['id']: e for e in self._remote('hr.employee', 'read', [hist_emp_ids, ['name', 'code', 'user_id']])} if hist_emp_ids else {}
        user_ids = sorted(set(admin_user_ids) | {e['user_id'][0] for e in emps.values() if e.get('user_id')})
        users = {u['id']: u for u in self._remote(
            'res.users', 'read', [user_ids, ['name', 'login', 'active', 'location_user_id', 'employee_ids', 'group_ids']])} if user_ids else {}
        loc_ids = sorted({u['location_user_id'][0] for u in users.values() if u.get('location_user_id')})
        loc_codes = {r['id']: r['code'] for r in self._remote('kderp.base.code', 'read', [loc_ids, ['code']])} if loc_ids else {}
        group_ids, team_labels = self._remote_group_ids()

        # --- merge, in rank order
        rows = OrderedDict()

        def row_for(key, name):
            return rows.setdefault(key, {'key': key, 'name': name, 'tags': OrderedDict(), 'is_admin': False})

        def emp_count(user, hist):
            return max([hist.get(e, 0) for e in (user.get('employee_ids') or [])] or [0])

        admins = [users[i] for i in admin_user_ids if i in users]
        admins.sort(key=lambda u: (-emp_count(u, job_hist), -emp_count(u, app_hist), u['id']))
        for u in admins:
            r = row_for(u['id'], u.get('name') or '')
            r['is_admin'] = True
            r['tags']['admin'] = 0
        by_emp = {e: u['id'] for u in users.values() for e in (u.get('employee_ids') or [])}   # employee -> user, from the users we read
        for src in SOURCE_ORDER:
            for emp_id, n in picks[src]:
                emp = emps.get(emp_id) or {}
                uid = (emp.get('user_id') and emp['user_id'][0]) or by_emp.get(emp_id) or False
                key = uid if uid in users else ('e', emp_id)
                if key not in rows and len(rows) >= MAX_ROWS:
                    continue
                r = row_for(key, (users.get(uid) or {}).get('name') or emp.get('name') or '')
                r['tags'][src] = n
                r.setdefault('employee_hint', emp_id)

        # --- eligibility, text, team
        res = []
        for r in rows.values():
            u = users.get(r['key']) if not isinstance(r['key'], tuple) else None
            loc = u and u.get('location_user_id') or False
            code = loc and loc_codes.get(loc[0]) or ''
            groups = set(u.get('group_ids') or []) if u else set()
            team = ', '.join(sorted(team_labels[g] for g in groups if g in team_labels))
            roles = ['Team ' + team_labels[g] for g in sorted(groups & set(team_labels), key=lambda g: team_labels[g])]
            for label, xmlid in ROLE_LABELS:
                if group_ids.get(xmlid) in groups and not (xmlid == GROUP_SUBMIT and group_ids.get(GROUP_ADMIN) in groups):
                    roles.append(label)
            reason = ''
            if not u:
                reason = _("the employee has no user on the remote server")
            elif not u.get('active'):
                reason = _("user is inactive")
            elif not u.get('employee_ids'):
                reason = _("no employee record")
            elif not loc:
                reason = _("no location")
            elif code in ('', 'all'):
                reason = _("location has no code letter")
            elif group_ids.get(GROUP_USER_INPUT) not in groups:
                reason = _("no 'User Input' right on advance requests")
            employee_id = 0
            if u and u.get('employee_ids'):
                hint = r.get('employee_hint')
                employee_id = hint if hint in u['employee_ids'] else u['employee_ids'][0]
            res.append({
                'remote_user_id': u['id'] if u else 0, 'employee_id': employee_id, 'name': r['name'], 'login': u.get('login') if u else '',
                'location_id': loc and loc[0] or 0, 'location_code': code, 'location_name': loc and loc[1] or '',
                'team': team, 'roles': ', '.join(roles), 'is_admin': r['is_admin'], 'ok': not reason, 'reason': reason, 'suggested': False,
                'why': self._remote_why(r['tags']),
            })
        first = next((c for c in res if c['ok']), None)
        if first:
            first['suggested'] = True
        meta['n_ineligible'] = len([c for c in res if not c['ok']])
        return res

    @api.model
    def _remote_why(self, tags):
        """Readable reasons, in rank order."""
        parts = []
        for src, n in tags.items():
            if src == 'admin':
                parts.append(_("Site admin of this job"))
            elif src == 'job':
                parts.append(_("entered %d advance request(s) on this job") % n)
            elif src == 'applicant':
                parts.append(_("usually enters this applicant's requests (%d in the last year)") % n)
            elif src == 'pm':
                parts.append(_("usually enters for this job's project manager (%d in the last year)") % n)
            elif src == 'office':
                parts.append(_("often enters for the applicant's office (%d in the last year)") % n)
        text = '; '.join(parts)
        return text[:1].upper() + text[1:]
