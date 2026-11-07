# -*- coding: utf-8 -*-
import logging
from collections import Counter
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class KderpHrEmployeeLocationFromAttendance(models.Model):
    _inherit = 'kderp.hr.employee.location'

    @api.model
    def _cron_update_from_attendance(self, today=None, force=False):
        """Monthly: record each working staff's location (kderp_hr, "Location History") as the face-id
        machine he/she used most in the attendance month that just ended (same rule as the AT Location Report).

        Cron runs every day; it acts only on the first day of an attendance month (default 21st), or with force=True.
        The line is dated the first day of the measured month ("from this date") and added only when the location
        differs from the one already in effect, like the HR import does. Safe to run twice.
        Returns the number of lines created."""
        today = today or fields.Date.context_today(self)
        mixin = self.env['hr.mixin']
        if not force and today.day != mixin.at_start_day():
            return 0
        at_year, at_month = mixin.get_at_year_month(today - relativedelta(days=1))
        return self._update_from_attendance_month(at_year, at_month)

    @api.model
    def action_backfill_from_attendance(self, today=None, preview=False):
        """One-off: replay every finished attendance month, oldest first, with the same rule as the cron.
        Because each month is compared with the location already in effect, a staff who stays at the same
        machine gets one line only (when he/she first appears or moves). Safe to run again.
        preview=True runs everything, then rolls it back: nothing is kept.
        Returns a dict: lines (new lines), codes (names of new location codes), by_location {name: new lines}, months."""
        today = today or fields.Date.context_today(self)
        mixin = self.env['hr.mixin']
        self.env.cr.execute("SELECT DISTINCT at_year, at_month FROM hr_attendance "
                         "WHERE at_year IS NOT NULL AND at_month IS NOT NULL ORDER BY at_year, at_month")
        months = self.env.cr.fetchall()     # before the SAVEPOINT statement, which replaces the cursor's result
        stats = {'lines': 0, 'codes': [], 'by_location': {}, 'by_machine': {}, 'months': 0}
        if preview:
            self.env.cr.execute('SAVEPOINT staff_location_preview')
        try:
            for at_year, at_month in months:
                if mixin.at_period_end(at_year, at_month) > today:   # month not finished yet
                    continue
                stats['months'] += 1
                self._update_from_attendance_month(at_year, at_month, stats=stats)
        finally:
            if preview:
                self.env.cr.execute('ROLLBACK TO SAVEPOINT staff_location_preview')
                self.env.invalidate_all()
        return stats

    @api.model
    def _update_from_attendance_month(self, at_year, at_month, stats=None):
        mixin = self.env['hr.mixin']
        month_start = mixin.at_period_end(at_year, at_month) - relativedelta(months=1)

        self.env.cr.execute("""
            SELECT att.employee_id, att.check_in_location_id, att.check_out_location_id
            FROM hr_attendance att
            JOIN hr_employee emp ON emp.id = att.employee_id AND emp.working
            WHERE att.at_year = %s AND att.at_month = %s
              AND (att.check_in_location_id IS NOT NULL OR att.check_out_location_id IS NOT NULL)
        """, (at_year, at_month))
        rows = self.env.cr.fetchall()    # before any other query: it would replace the cursor's result
        # machines ticked 'Ignore for staff locations' (tests...) do not decide where a staff works
        ignored = set(self.env['hr.attendance.location'].sudo().with_context(active_test=False)
                      .search([('ignore_location', '=', True)]).ids)
        counts = {}
        for emp_id, loc_in, loc_out in rows:
            used = [l for l in (loc_in, loc_out) if l and l not in ignored]
            if used:
                counts.setdefault(emp_id, Counter()).update(used)

        Machine = self.env['hr.attendance.location'].sudo().with_context(active_test=False)
        Employee = self.env['hr.employee'].sudo()
        Code = self.env['kderp.employee.location.code'].sudo()
        code_of = {}   # (machine id, staff area id) -> location code id
        created = 0
        for emp_id, counter in counts.items():
            # most frequent machine; a tie goes to the lower id so a re-run gives the same answer
            machine_id = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            employee = Employee.browse(emp_id)
            key = (machine_id, employee.admin_dept_id.area_id.id)
            if key not in code_of:
                name = Machine.browse(machine_id).staff_location_name(employee)
                # same matching as kderp_hr's uniqueness check (spaces are wildcards), so near-duplicates reuse one code
                code = Code.search([('name', '=ilike', name.replace(' ', '%'))], limit=1)
                if not code:
                    code = Code.create({'name': name})
                    if stats is not None:
                        stats['codes'].append(name)
                code_of[key] = code.id
            if self.search_count([('employee_id', '=', emp_id), ('date', '=', month_start)]):
                continue
            current = self.get_location_with_date(emp_id, month_start)
            if current and current.location_id.id == code_of[key]:
                continue
            self.sudo().create({'employee_id': emp_id, 'date': month_start, 'location_id': code_of[key]})
            created += 1
            if stats is not None:
                label = Code.browse(code_of[key]).name
                stats['by_location'][label] = stats['by_location'].get(label, 0) + 1
                machine = Machine.browse(machine_id)
                info = stats['by_machine'].setdefault(machine_id, {
                    'name': machine.name, 'show': machine.display_name, 'has_area': bool(machine.area_id),
                    'lines': 0, 'prefixed': 0, 'areas': Counter(), 'example': label})
                info['lines'] += 1
                info['areas'][employee.admin_dept_id.area_id.name or ''] += 1
                if label != info['show'][:32]:
                    info['prefixed'] += 1
                    info['example'] = label
        if stats is not None:
            stats['lines'] += created
        _logger.info('Staff locations from attendance %s/%s: %s new lines for %s staff', at_month, at_year, created, len(counts))
        return created

    # ------------------------------------------------------------------
    # Send to the remote server (asset report): Odoo -> remote directly (kdvn_remote_integration), dry run by default.
    # Before 12.0.1.0.11 this went through an n8n webhook; the planning rules below are the ones of that workflow.
    # ------------------------------------------------------------------
    TASK = 'staff_location'
    # Names that mean the SAME place on the remote: staff already on any of them count as "unchanged" (no new line).
    # A new line is always written with the name HR chose in the wizard.
    SAME_PLACE = [('head office', 'ho')]

    @api.model
    def _prepare_remote_payload(self):
        """Current location only (the remote keeps its own history and its own location names):
        staff = current location of every working staff that has one, with the date it started here and the
        remote location HR chose for it in the sync wizard (kderp.staff.location.map; empty = not mapped, skipped)."""
        staff = self.env['hr.employee'].sudo().search([('working', '=', True), ('current_location_id', '!=', False)])
        lines = self.sudo().search([('employee_id', 'in', staff.ids)], order='date asc, id asc')
        latest = {}
        for l in lines:
            if l.date <= fields.Date.today():
                latest[l.employee_id.id] = l
        remote_of = {m.location_id.id: m.remote_id.name for m in self.env['kderp.staff.location.map'].sudo().search([])}
        return {
            'source': 'odoo',
            'sent_by': self.env.user.name,
            'sent_at': fields.Datetime.to_string(fields.Datetime.now()),
            'staff': [{
                'code': e.code, 'remote_code': e.remote_code or '', 'name': e.name,
                'location': e.current_location_id.name,
                'remote_location': remote_of.get(e.current_location_id.id, ''),
                'since': str(latest[e.id].date) if e.id in latest else '',
            } for e in staff],
        }

    @api.model
    def _remote(self, model, method, args=None, kwargs=None):
        """Reads use the Reader (or the Writer when no Reader is set up); a write needs the 'staff_location' live switch."""
        return self.env['kderp.remote.client'].execute(model, method, args, kwargs, task=self.TASK)

    @api.model
    def _vietnam_today(self):
        return (datetime.utcnow() + timedelta(hours=7)).date().isoformat()

    @classmethod
    def _norm_name(cls, value):
        return str(value or '').strip().lower()

    @classmethod
    def _canon_name(cls, value):
        n = cls._norm_name(value)
        for group in cls.SAME_PLACE:
            if n in group:
                return group[0]
        return n

    @api.model
    def _plan_remote_push(self, staff, today=None):
        """READS the remote and plans the lines to create. Writes nothing.

        For each staff: the local wizard already chose the existing remote location (`remote_location`); look at the location in effect
        on the remote today and plan ONE new line (dated today) only when it differs. Nothing is created for unmapped names.
        Returns {'lines': [...], 'summary': {...}} (summary keys as the old n8n answer)."""
        today = today or self._vietnam_today()
        norm, canon = self._norm_name, self._canon_name
        codes = sorted({(s.get('code') or '').strip() for s in staff if (s.get('code') or '').strip()})
        emp_by_code = {}
        for i in range(0, len(codes), 500):
            for e in self._remote('hr.employee', 'search_read', [[('code', 'in', codes[i:i + 500])]],
                                  {'fields': ['code', 'working'], 'context': {'active_test': False}}):
                key = (e.get('code') or '').strip()
                if key and (key not in emp_by_code or (e.get('working') and not emp_by_code[key].get('working'))):
                    emp_by_code[key] = e
        loc_id, loc_name = {}, {}
        for l in self._remote('kderp.employee.location.code', 'search_read', [[]], {'fields': ['name']}):
            loc_id[norm(l.get('name'))] = l['id']
            loc_name[l['id']] = (l.get('name') or '').strip()
        lines_of = {}
        emp_ids = sorted(e['id'] for e in emp_by_code.values())
        for i in range(0, len(emp_ids), 500):
            for r in self._remote('kderp.hr.employee.location', 'search_read',
                                  [[('employee_id', 'in', emp_ids[i:i + 500]), ('date', '<=', today)]],
                                  {'fields': ['employee_id', 'location_id', 'date']}):
                emp, loc = r.get('employee_id') and r['employee_id'][0], r.get('location_id') and r['location_id'][0]
                if emp and r.get('date') and loc:
                    lines_of.setdefault(emp, []).append({'date': r['date'], 'loc': loc})

        lines, unmapped, target_missing, unknown, conflicts = [], {}, set(), [], []
        unchanged = no_location = 0
        for s in staff:
            code, name = (s.get('code') or '').strip(), (s.get('location') or '').strip()
            if not code or not name:
                no_location += 1
                continue
            target = (s.get('remote_location') or '').strip()          # chosen by HR in the local wizard
            if not target:
                unmapped[name] = unmapped.get(name, 0) + 1
                continue
            target_id = loc_id.get(norm(target))
            if not target_id:
                target_missing.add(target)
                continue
            emp = emp_by_code.get(code)
            if not emp:
                unknown.append(code)
                continue
            mine = lines_of.get(emp['id'], [])
            current = None
            for l in mine:
                if l['date'] <= today and (current is None or l['date'] > current['date']):
                    current = l
            if current and (current['loc'] == target_id or canon(loc_name.get(current['loc'])) == canon(target)):
                unchanged += 1
                continue
            if any(l['date'] == today for l in mine):
                conflicts.append(code)
                continue
            lines.append({'employee_id': emp['id'], 'code': code, 'date': today, 'location_id': target_id,
                          'from': current and loc_name.get(current['loc'], '') or '', 'to': loc_name[target_id]})
        return {'lines': lines, 'summary': {
            'received': len(staff), 'to_update': len(lines), 'unchanged': unchanged, 'no_location': no_location, 'unmapped': unmapped,
            'target_missing': sorted(target_missing), 'unknown_staff': unknown, 'conflicts_today': conflicts}}

    @api.model
    def action_push_to_remote(self):
        """Send the staff locations to the remote server (wizard step 3, cron). Returns (staff count, result dict).

        Dry run unless the 'Staff locations' live switch of Settings > Remote Server Connection is ON (production only):
        the remote is never written from dev or from a database copy."""
        payload = self._prepare_remote_payload()
        plan = self._plan_remote_push(payload['staff'])
        result = dict(plan['summary'])
        if not self.env['kderp.remote.client'].is_live(self.TASK):
            result.update(status='dry_run', created=0, failed=[], preview=plan['lines'][:20])
        else:
            created, failed = 0, []
            for l in plan['lines']:
                try:
                    self._remote('kderp.hr.employee.location', 'create',
                                 [{'employee_id': l['employee_id'], 'date': l['date'], 'location_id': l['location_id']}])
                    created += 1
                except UserError as e:
                    failed.append({'code': l['code'], 'date': l['date'], 'error': str(e)})
            result.update(status='partial' if failed else 'ok', created=created, failed=failed)
        _logger.info('Staff locations: %s staff checked; remote result: %s', len(payload['staff']), {k: v for k, v in result.items() if k != 'preview'})
        return len(payload['staff']), result

    @api.model
    def _format_push_result(self, staff, result):
        """(title, [plain text rows]) describing the result of the send, for the wizard."""
        rows = [_('Checked the current location of %s staff against the remote server.') % staff]
        status = result.get('status')
        if status in ('dry_run', 'ok', 'partial'):
            dry = status == 'dry_run'
            title = _('DRY RUN: nothing was written on the remote server') if dry else _('Staff locations sent to the remote server')
            rows.append(_('%s staff %s on the remote, %s already correct.') % (
                result.get('to_update', 0), _('would be updated') if dry else _('to update'), result.get('unchanged', 0)))
            if not dry:
                rows.append(_('Updated: %s. Failed: %s.') % (result.get('created', 0), len(result.get('failed') or [])))
            unmapped = result.get('unmapped') or {}
            if unmapped:
                rows.append(_('Without a remote location (skipped; go Back and choose one): %s') % ', '.join(
                    '%s (%s)' % (k, v) for k, v in sorted(unmapped.items(), key=lambda kv: -kv[1])))
            for key, label in (('target_missing', _('Chosen remote location no longer exists on the remote')),
                               ('unknown_staff', _('Staff codes not found on the remote')),
                               ('conflicts_today', _('Staff already having a different line dated today on the remote (not touched)'))):
                values = result.get(key) or []
                if values:
                    rows.append('%s: %s' % (label, ', '.join(values)))
            if result.get('no_location'):
                rows.append(_('Without a location: %s') % result['no_location'])
            for f in (result.get('failed') or [])[:10]:
                rows.append(_('Failed: %s') % ' '.join(str(v) for v in f.values()))
            if dry and result.get('preview'):
                rows.append(_('First changes: %s') % '; '.join(
                    '%s %s -> %s' % (p.get('code'), p.get('from') or '-', p.get('to')) for p in result['preview'][:10]))
        else:
            title = _('Staff locations')
            rows.append(_('The remote server answer was not recognised: %s') % (result.get('raw_answer') or _('(empty)')))
        return title, rows

    @api.model
    def _cron_push_to_remote(self, today=None, force=False):
        """Cron (shipped INACTIVE, a person must check the machine names and the mapping first): runs every day but
        acts only on the first day of the attendance month, after the 04:30 update. Errors are logged, the cron does not crash."""
        today = today or fields.Date.context_today(self)
        if not force and today.day != self.env['hr.mixin'].at_start_day():
            return False
        try:
            self.action_push_to_remote()
        except UserError as e:
            _logger.error('Staff locations: scheduled send failed: %s', e)
        return True
