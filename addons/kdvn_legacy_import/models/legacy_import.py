"""Odoo 12 -> Odoo 19 data import (staff, organisation). Steps are small methods; later modules add their own steps.

Rules
- Read: the snapshot database `legacy12` (parameter kdvn_legacy.db), plain SQL, read-only session, same server and login as Odoo.
- Write: ORM only. Each imported record gets the external id legacy12.<table>_<id> (table = Odoo 12 table name).
- Re-runnable: a record with that external id is updated; else an existing record is adopted by its natural key
  (code, login, name) and tagged; else it is created.
- One bad record never stops the run: it is rolled back in a savepoint and listed in the log.
"""
import contextlib
import logging
import re
from collections import Counter

import psycopg2
import psycopg2.extras

from odoo import api, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TAG_MODULE = 'legacy12'
PARAM_DB = 'kdvn_legacy.db'

# Odoo 12 employee column -> Odoo 19 field (only where the field exists and the value fits)
EMPLOYEE_COLUMNS = {
    'name': 'name', 'code': 'code', 'working': 'working', 'active': 'active', 'birthday': 'birthday',
    'gender': 'sex', 'marital': 'marital', 'work_email': 'work_email', 'work_phone': 'work_phone',
    'mobile_phone': 'mobile_phone', 'personal_mobile': 'private_phone', 'job_title': 'job_title',
    'identification_id': 'identification_id', 'passport_id': 'passport_id', 'ssnid': 'ssnid',
    'place_of_birth': 'place_of_birth', 'children': 'children', 'study_field': 'study_field',
    'study_school': 'study_school', 'emergency_contact': 'emergency_contact', 'emergency_phone': 'emergency_phone',
    'permit_no': 'permit_no', 'visa_no': 'visa_no', 'visa_expire': 'visa_expire', 'barcode': 'barcode', 'pin': 'pin',
    'joining_date': 'joining_date', 'stop_working_date': 'stop_working_date',
    'official_working_date': 'official_working_date', 'resign_date': 'departure_date',
}
# second pass (all employees exist): legacy column -> field holding an hr.employee / hr.department
EMPLOYEE_LINKS = {'parent_id': ('parent_id', 'hr_employee'), 'admin_manager_id': ('admin_manager_id', 'hr_employee'),
                  'coach_id': ('coach_id', 'hr_employee'), 'department_id': ('department_id', 'hr_department'),
                  'admin_dept_id': ('admin_dept_id', 'hr_department'), 'working_area_id': ('working_area_id', 'hr_department')}


class KdvnLegacyImport(models.AbstractModel):
    _name = 'kdvn.legacy.import'
    _description = 'Odoo 12 data import'

    # ------------------------------------------------------------------ reading the snapshot
    @api.model
    def _legacy_rows(self, table, columns, where=None):
        """Rows of an Odoo 12 table as dicts (read-only). Columns missing in the snapshot are returned as None."""
        dbname = self.env['ir.config_parameter'].sudo().get_param(PARAM_DB, 'legacy12')
        try:
            conn = psycopg2.connect(dbname=dbname, host=tools.config['db_host'] or None, port=tools.config['db_port'] or None,
                                    user=tools.config['db_user'] or None, password=tools.config['db_password'] or None)
        except psycopg2.OperationalError as error:
            raise UserError(self.env._("Cannot open the Odoo 12 snapshot database '%(db)s': %(error)s. Run tools/legacy12_snapshot.sh first.",
                                       db=dbname, error=str(error).strip()))
        try:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cr:
                cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
                existing = {r['column_name'] for r in cr.fetchall()}
                if not existing:
                    return []
                if columns is None:
                    columns = sorted(existing)
                wanted = [c for c in columns if c in existing]
                cr.execute('SELECT %s FROM "%s"%s' % (', '.join('"%s"' % c for c in wanted), table, ' WHERE ' + where if where else ''
                ) + (' ORDER BY id' if 'id' in existing else ''))
                rows = cr.fetchall()
        finally:
            conn.close()
        missing = [c for c in columns if c not in wanted]
        return [dict(r, **{c: None for c in missing}) for r in rows]

    @property
    def _state(self):
        """Run state (tags, stats, errors, options): a plain dict shared through the context, since recordsets cannot hold attributes."""
        return self.env.context['kdvn_import_state']

    # ------------------------------------------------------------------ tagging helpers
    def _tag_map(self):
        """{'<table>_<id>': res_id} of everything already imported (the table name in the tag tells the model)."""
        self.env.cr.execute("SELECT name, res_id FROM ir_model_data WHERE module = %s", (TAG_MODULE,))
        return dict(self.env.cr.fetchall())

    def _tag(self, record, table, legacy_id):
        self.env['ir.model.data'].create({'module': TAG_MODULE, 'name': '%s_%s' % (table, legacy_id),
                                          'model': record._name, 'res_id': record.id, 'noupdate': True})
        self._state['tags'][(table, legacy_id)] = record.id

    def _record(self, model, table, legacy_id):
        res_id = self._state['tags'].get((table, legacy_id))
        return self.env[model].browse(res_id).exists() if res_id else self.env[model]

    def _clean(self, model, vals):
        """Keep only values that fit the Odoo 19 model: field exists, selection value is valid."""
        fields_ = self.env[model]._fields
        out = {}
        for name, value in vals.items():
            field = fields_.get(name)
            if not field:
                continue
            if field.type == 'selection':
                selection = field._description_selection(self.env)
                if not value or value not in {s[0] for s in selection}:
                    continue   # unknown or empty: keep the Odoo 19 default (some selections are NOT NULL)
            if value is None and field.type in ('char', 'text'):
                value = False
            out[name] = value
        return out

    def _upsert(self, model, table, legacy_id, vals, natural=None):
        """Create, update or adopt a record for an Odoo 12 row. natural = domain finding an existing Odoo 19 record."""
        vals = self._clean(model, vals)
        record = self._record(model, table, legacy_id)
        with self.env.cr.savepoint():
            if record:
                record.write(vals)
                self._state['stats'][(table, 'updated')] += 1
                return record
            existing = self.env[model].with_context(active_test=False).search(natural, limit=1) if natural else self.env[model]
            if existing:
                existing.write(vals)
                self._tag(existing, table, legacy_id)
                self._state['stats'][(table, 'adopted')] += 1
                return existing
            record = self.env[model].create(vals)
            self._tag(record, table, legacy_id)
            self._state['stats'][(table, 'created')] += 1
            return record

    def _safe(self, table, legacy_id, label, func):
        """Run func for one legacy row; a failure is logged and rolled back, the run goes on."""
        try:
            return func()
        except Exception as error:   # noqa: BLE001 - one bad row must not stop the import
            self._state['stats'][(table, 'failed')] += 1
            message = '%s %s (%s): %s' % (table, legacy_id, label, str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__)
            self._state['errors'].append(message)
            _logger.warning('legacy import: %s', message)
            return None

    # ------------------------------------------------------------------ run
    @api.model
    def run(self, employee_codes=None, working_only=False, password=None, dry_run=False, steps=None, date_from=None, date_to=None):
        """Import the selected employees with everything they need. Returns {'stats': {...}, 'errors': [...], 'log': text}.
        employee_codes: list of staff codes (None / empty = everybody); their managers are always added.
        working_only: skip leavers. password: set on every imported user (dev only; None = no password).
        dry_run: do everything, then roll back."""
        self = self.sudo().with_context(tracking_disable=True, mail_notrack=True, mail_create_nolog=True, no_reset_password=True,
                                 kdvn_defer_org_refresh=True, kdvn_skip_working_check=True)
        state = {'tags': {}, 'stats': Counter(), 'errors': [], 'options': {'password': password, 'date_from': date_from, 'date_to': date_to}, 'legacy_employees': {}, 'department_rows': []}
        self = self.with_context(kdvn_import_state=state)
        state['tags'] = {(name.rsplit('_', 1)[0], int(name.rsplit('_', 1)[1])): res_id for name, res_id in self._tag_map().items()}
        self._select_employees(employee_codes, working_only)
        with contextlib.ExitStack() as stack:
            savepoint = stack.enter_context(self.env.cr.savepoint(flush=False)) if dry_run else None
            for name, method in self._import_steps():
                if steps and name not in steps:
                    continue
                method()
                self.env.flush_all()
            if dry_run:
                self.env.flush_all()
                savepoint.rollback()
                self.env.invalidate_all()
        return {'stats': dict(self._state['stats']), 'errors': list(self._state['errors']), 'log': self._format_log(dry_run)}

    def _import_steps(self):
        """(name, method) in run order. Other modules extend this with their own steps (attendance, requests...)."""
        return [
            ('department_types', self._step_department_types),
            ('locations', self._step_locations),
            ('departments', self._step_departments),
            ('users', self._step_users),
            ('employees', self._step_employees),
            ('employee_links', self._step_employee_links),
            ('histories', self._step_histories),
            ('organisation', self._step_organisation),
        ]

    def _format_log(self, dry_run):
        lines = ['DRY RUN (rolled back)' if dry_run else 'Import done']
        for (table, what), count in sorted(self._state['stats'].items()):
            lines.append('%-40s %-8s %d' % (table, what, count))
        if self._state['errors']:
            lines.append('')
            lines.append('%d problem(s):' % len(self._state['errors']))
            lines += self._state['errors'][:100]
            if len(self._state['errors']) > 100:
                lines.append('... and %d more' % (len(self._state['errors']) - 100))
        return '\n'.join(lines)

    # ------------------------------------------------------------------ which employees
    def _select_employees(self, codes, working_only):
        """Employees to import = the asked ones + everybody they depend on (managers, department managers)."""
        rows = self._legacy_rows('hr_employee', ['id', 'code', 'working', 'active', 'user_id', 'parent_id', 'admin_manager_id', 'coach_id'])
        by_id = {r['id']: r for r in rows}
        codes = {c.strip().upper() for c in (codes or []) if c and c.strip()}
        asked = {r['id'] for r in rows
                 if (not codes or (r['code'] or '').upper() in codes) and (not working_only or r['working'])}
        history = self._legacy_rows('hr_employee_department_history', ['employee_id', 'department_id', 'admin_dept_id'])
        departments = self._legacy_rows('hr_department', ['id', 'manager_id', 'manager_2nd_id', 'new_manager'])
        dept_manager = {d['id']: {d[k] for k in ('manager_id', 'manager_2nd_id', 'new_manager') if d[k]} for d in departments}
        manager_hist = self._legacy_rows('hr_manager_history', ['department_id', 'manager_id'])
        for line in manager_hist:
            dept_manager.setdefault(line['department_id'], set()).add(line['manager_id'])
        dept_of = {}
        for line in history:
            dept_of.setdefault(line['employee_id'], set()).update(d for d in (line['department_id'], line['admin_dept_id']) if d)
        selected, todo = set(), set(asked)
        while todo:
            emp = todo.pop()
            if emp in selected or emp not in by_id:
                continue
            selected.add(emp)
            row = by_id[emp]
            todo.update(x for x in (row['parent_id'], row['admin_manager_id']) if x)
            for dept in dept_of.get(emp, ()):
                todo.update(dept_manager.get(dept, ()))
        self._state['legacy_employees'] = {i: by_id[i] for i in selected}
        self._state['stats'][('hr_employee', 'selected')] = len(selected)
        self._state['stats'][('hr_employee', 'asked')] = len(asked)

    # ------------------------------------------------------------------ steps
    def _step_department_types(self):
        for row in self._legacy_rows('hr_department_type', ['id', 'name', 'code', 'description']):
            self._safe('hr_department_type', row['id'], row['code'], lambda row=row: self._upsert(
                'hr.department.type', 'hr_department_type', row['id'],
                {'name': row['name'], 'code': row['code'], 'description': row['description']},
                natural=[('code', '=', row['code'])]))

    def _step_locations(self):
        for row in self._legacy_rows('kderp_employee_location_code', ['id', 'name']):
            name = (row['name'] or '').strip()
            self._safe('kderp_employee_location_code', row['id'], name, lambda row=row, name=name: self._upsert(
                'kderp.employee.location.code', 'kderp_employee_location_code', row['id'], {'name': name},
                natural=[('name', '=ilike', name.replace('_', r'\_').replace('%', r'\%'))]))

    def _step_departments(self):
        rows = self._legacy_rows('hr_department', ['id', 'name', 'code', 'active', 'type_id', 'parent_id', 'manager_2nd_id', 'new_manager',
                                                    'new_man_effective_date'])
        for row in rows:     # pass 1: the departments themselves
            vals = {'name': row['name'], 'code': row['code'], 'active': bool(row['active']),
                    'type_id': self._record('hr.department.type', 'hr_department_type', row['type_id']).id or False}
            self._safe('hr_department', row['id'], row['code'], lambda row=row, vals=vals: self._upsert(
                'hr.department', 'hr_department', row['id'], vals, natural=[('code', '=', row['code'])] if row['code'] else None))
        for row in rows:     # pass 2: parents
            dept = self._record('hr.department', 'hr_department', row['id'])
            parent = self._record('hr.department', 'hr_department', row['parent_id'])
            if dept and dept.parent_id != parent:
                self._safe('hr_department', row['id'], 'parent', lambda dept=dept, parent=parent: dept.write({'parent_id': parent.id}))
        self._state['department_rows'] = rows

    def _step_users(self):
        wanted = {r['user_id'] for r in self._state['legacy_employees'].values() if r['user_id']}
        users = {u['id']: u for u in self._legacy_rows('res_users', ['id', 'login', 'active', 'partner_id']) if u['id'] in wanted}
        partners = {p['id']: p for p in self._legacy_rows('res_partner', ['id', 'name', 'email'])}
        groups = self._user_groups()
        password = self._state['options'].get('password')
        for user_id, row in users.items():
            if user_id in (1, 2):   # OdooBot and the Administrator: map to the existing Odoo 19 ones, never rewrite them
                target = self.env.ref('base.user_root' if user_id == 1 else 'base.user_admin')
                if not self._record('res.users', 'res_users', user_id):
                    self._tag(target, 'res_users', user_id)
                continue
            partner = partners.get(row['partner_id'], {})
            vals = {'login': row['login'], 'name': partner.get('name') or row['login'], 'email': partner.get('email'),
                    'active': bool(row['active'])}
            if password:
                vals['password'] = password

            self._safe('res_users', user_id, row['login'], lambda row=row, vals=vals: self._upsert(
                'res.users', 'res_users', user_id, vals, natural=[('login', '=ilike', (row['login'] or '').replace('_', r'\_'))]))
            user = self._record('res.users', 'res_users', user_id)
            if user and groups.get(user_id):
                self._safe('res_users', user_id, 'groups', lambda user=user, ids=groups[user_id]: user.write({'group_ids': [(4, g) for g in ids]}))

    def _user_groups(self):
        """{legacy user id: [Odoo 19 group ids]}. A legacy group maps to the group with the same external id, with the
        module renamed kderp_x -> kdvn_x. base.* groups are never copied (user type and admin rights stay as Odoo 19 sets them).
        Legacy groups without a counterpart are counted, so the module that needs them can map them later."""
        names = {}
        for row in self._legacy_rows('ir_model_data', ['module', 'name', 'model', 'res_id'], where="model = 'res.groups'"):
            names[row['res_id']] = (row['module'], row['name'])
        result, unmapped = {}, Counter()
        for row in self._legacy_rows('res_groups_users_rel', ['gid', 'uid']):
            module, name = names.get(row['gid'], (None, None))
            if not module or module == 'base':
                continue
            group = self.env.ref('%s.%s' % (re.sub(r'^kderp_', 'kdvn_', module), name), raise_if_not_found=False)
            if group and group._name == 'res.groups':
                result.setdefault(row['uid'], []).append(group.id)
            else:
                unmapped['%s.%s' % (module, name)] += 1
        for xmlid, count in unmapped.items():
            self._state['stats'][('legacy group not mapped', xmlid)] = count
        return result

    def _step_employees(self):
        columns = list(EMPLOYEE_COLUMNS) + ['id', 'user_id']
        for row in self._legacy_rows('hr_employee', columns):
            if row['id'] not in self._state['legacy_employees']:
                continue
            vals = {new: row[old] for old, new in EMPLOYEE_COLUMNS.items() if old in row}
            user = self._record('res.users', 'res_users', row['user_id'])
            vals['user_id'] = user.id or False
            natural = []
            if row['code']:
                natural.append(('code', '=', row['code']))
            if user:
                natural.append(('user_id', '=', user.id))
            natural = ['|'] * (len(natural) - 1) + natural if natural else None
            self._safe('hr_employee', row['id'], row['code'], lambda row=row, vals=vals, natural=natural: self._upsert(
                'hr.employee', 'hr_employee', row['id'], vals, natural=natural))

    def _step_employee_links(self):
        """Managers, coach and sections as they are in Odoo 12 (copied as they are, not recomputed from history)."""
        for row in self._legacy_rows('hr_employee', ['id'] + list(EMPLOYEE_LINKS)):
            employee = self._record('hr.employee', 'hr_employee', row['id'])
            if not employee or row['id'] not in self._state['legacy_employees']:
                continue
            vals = {}
            for column, (field, table) in EMPLOYEE_LINKS.items():
                model = 'hr.employee' if table == 'hr_employee' else 'hr.department'
                vals[field] = self._record(model, table, row[column]).id or False
            self._safe('hr_employee', row['id'], 'links', lambda employee=employee, vals=vals: employee.write(self._clean('hr.employee', vals)))

    def _step_histories(self):
        for row in self._legacy_rows('kderp_hr_employee_location', ['id', 'employee_id', 'location_id', 'date']):
            employee = self._record('hr.employee', 'hr_employee', row['employee_id'])
            location = self._record('kderp.employee.location.code', 'kderp_employee_location_code', row['location_id'])
            if employee and location:
                self._safe('kderp_hr_employee_location', row['id'], '', lambda row=row, employee=employee, location=location: self._upsert(
                    'kderp.hr.employee.location', 'kderp_hr_employee_location', row['id'],
                    {'employee_id': employee.id, 'location_id': location.id, 'date': row['date']},
                    natural=[('employee_id', '=', employee.id), ('date', '=', row['date'])]))
        for row in self._legacy_rows('hr_employee_department_history', ['id', 'employee_id', 'department_id', 'effective_date', 'admin_dept_id', 'admin_effv_date']):
            employee = self._record('hr.employee', 'hr_employee', row['employee_id'])
            if employee:
                vals = {'employee_id': employee.id, 'effective_date': row['effective_date'], 'admin_effv_date': row['admin_effv_date'],
                        'department_id': self._record('hr.department', 'hr_department', row['department_id']).id,
                        'admin_dept_id': self._record('hr.department', 'hr_department', row['admin_dept_id']).id}
                self._safe('hr_employee_department_history', row['id'], '', lambda row=row, vals=vals: self._upsert(
                    'hr.employee.department.history', 'hr_employee_department_history', row['id'], vals))
        for row in self._legacy_rows('hr_manager_history', ['id', 'department_id', 'manager_id', 'effective_date']):
            department = self._record('hr.department', 'hr_department', row['department_id'])
            manager = self._record('hr.employee', 'hr_employee', row['manager_id'])
            if department and manager:
                self._safe('hr_manager_history', row['id'], '', lambda row=row, department=department, manager=manager: self._upsert(
                    'hr.manager.history', 'hr_manager_history', row['id'],
                    {'department_id': department.id, 'manager_id': manager.id, 'effective_date': row['effective_date']}))
        for row in self._legacy_rows('hr_employee_project_history', ['id', 'employee_id', 'project_name', 'project_description', 'effective_date']):
            employee = self._record('hr.employee', 'hr_employee', row['employee_id'])
            if employee:
                self._safe('hr_employee_project_history', row['id'], '', lambda row=row, employee=employee: self._upsert(
                    'hr.employee.project.history', 'hr_employee_project_history', row['id'],
                    {'employee_id': employee.id, 'project_name': row['project_name'], 'project_description': row['project_description'],
                     'effective_date': row['effective_date']}))

    def _step_organisation(self):
        """Second manager and pending new manager of the departments, then the manager-user chains once for everybody."""
        for row in self._state['department_rows'] or self._legacy_rows(
                'hr_department', ['id', 'manager_2nd_id', 'new_manager', 'new_man_effective_date']):
            department = self._record('hr.department', 'hr_department', row['id'])
            if department:
                vals = {'manager_2nd_id': self._record('hr.employee', 'hr_employee', row['manager_2nd_id']).id or False,
                        'new_manager': self._record('hr.employee', 'hr_employee', row['new_manager']).id or False,
                        'new_man_effective_date': row['new_man_effective_date']}
                self._safe('hr_department', row['id'], 'managers', lambda department=department, vals=vals: department.write(vals))
        employees = self.env['hr.employee'].browse([self._state['tags'][('hr_employee', i)] for i in self._state['legacy_employees'] if ('hr_employee', i) in self._state['tags']])
        employees._compute_parent_users()
        self.env['hr.department'].browse([v for (t, _i), v in self._state['tags'].items() if t == 'hr_department'])._compute_1st_manager()
