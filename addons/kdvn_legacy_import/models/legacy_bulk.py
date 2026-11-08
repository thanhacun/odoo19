"""Bulk (SQL) loader for the big history tables of the Odoo 12 attendance data.

Why: the ORM path (one create per row, even with every computation off) takes minutes per month of attendance and reads a whole
legacy table into memory (480k attendance days: MemoryError). Here the legacy tables are STREAMED in chunks (server side cursor)
and written with plain SQL (execute_values), one statement per chunk.

What it does NOT change: which rows are imported, how many2one ids are mapped (the tags of the ORM steps), the values (the Odoo 12
stored values are copied as they are, the same rules as the ORM path: stored fields only, selection values that do not fit and empty
values of required fields fall back to the Odoo 19 default). Stored computed fields that Odoo 12 has no value for are
filled by their formula (expected_hours...), the same value the ORM path gets by computing them.

Switch: run(..., bulk=True) / tools/legacy_import.sh ... --bulk. Re-runnable: a row that already has the external id
legacy12.<table>_<id> is updated in place (INSERT .. ON CONFLICT (id) DO UPDATE), a new one gets the next id of the sequence.
"""
import logging
import time

import psycopg2
import psycopg2.extras

from odoo import models, tools
from odoo.exceptions import UserError

from .legacy_import import FINGERPRINT_TABLES, FINGERPRINT_VOLATILE, PARAM_DB, TAG_MODULE
from .legacy_import_attendance import SKIP_COLUMNS, _iso

_logger = logging.getLogger(__name__)

CHUNK = 5000


class KdvnLegacyBulk(models.AbstractModel):
    _inherit = 'kdvn.legacy.import'

    # ------------------------------------------------------------------ plumbing
    def _tags_get(self, table, legacy_id):
        """Tags of the bulk tables live in per-table dicts (ids only), the small tables in the common tags map."""
        bulk = self._state.get('bulk', {}).get(table)
        if bulk is not None:
            return bulk.get(legacy_id, False)
        return super()._tags_get(table, legacy_id)

    def _bulk_map(self, table, model):
        """{legacy id: res_id} of a bulk table (loaded from the external ids once; kept up to date by the loader)."""
        bulk = self._state.setdefault('bulk', {})
        if table not in bulk:
            prefix = table + '_'
            self.env.cr.execute("SELECT name, res_id FROM ir_model_data WHERE module = %s AND model = %s AND name LIKE %s",
                                (TAG_MODULE, model, prefix.replace('_', r'\_') + '%'))
            bulk[table] = {int(name[len(prefix):]): res_id for name, res_id in self.env.cr.fetchall() if name[len(prefix):].isdigit()}
        return bulk[table]

    def _legacy_connect(self):
        dbname = self.env['ir.config_parameter'].sudo().get_param(PARAM_DB, 'legacy12')
        try:
            conn = psycopg2.connect(dbname=dbname, host=tools.config['db_host'] or None, port=tools.config['db_port'] or None,
                                    user=tools.config['db_user'] or None, password=tools.config['db_password'] or None)
        except psycopg2.OperationalError as error:
            raise UserError("Cannot open the Odoo 12 snapshot database '%s': %s" % (dbname, str(error).strip()))
        conn.set_session(readonly=True, autocommit=False)
        return conn

    def _legacy_columns(self, table):
        conn = self._legacy_connect()
        try:
            with conn.cursor() as cr:
                cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
                return {r[0] for r in cr.fetchall()}
        finally:
            conn.close()

    def _legacy_stream(self, table, where=None, chunk=CHUNK, columns=None, order='id'):
        """Yield lists of rows (dicts) of an Odoo 12 table, `chunk` rows at a time, in id order (server side cursor: constant memory)."""
        conn = self._legacy_connect()
        try:
            with conn.cursor(name='kdvn_bulk_%s' % table[:40], cursor_factory=psycopg2.extras.RealDictCursor) as cr:
                cr.itersize = chunk
                cols = '*' if not columns else ', '.join('"%s"' % c for c in columns)
                cr.execute('SELECT %s FROM "%s"%s%s' % (cols, table, ' WHERE ' + where if where else '', ' ORDER BY ' + order if order else ''))
                while True:
                    rows = cr.fetchmany(chunk)
                    if not rows:
                        break
                    yield rows
        finally:
            conn.close()

    def _legacy_fingerprint(self):
        """md5 over the content of the Odoo 12 tables that the small ORM steps read (volatile columns left out). Same content = same result of those steps."""
        import hashlib
        conn = self._legacy_connect()
        digest = hashlib.md5()
        try:
            with conn.cursor() as cr:
                for table in FINGERPRINT_TABLES:
                    cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY 1", (table,))
                    cols = [c[0] for c in cr.fetchall() if c[0] not in FINGERPRINT_VOLATILE]
                    if not cols:
                        digest.update(('%s:none;' % table).encode())
                        continue
                    expr = " || '|' || ".join("coalesce(\"%s\"::text, '~')" % c for c in cols)
                    cr.execute("SELECT md5(coalesce(string_agg(x, E'\\n' ORDER BY x), '')) FROM (SELECT %s AS x FROM \"%s\") t" % (expr, table))
                    digest.update(('%s:%s;' % (table, cr.fetchone()[0])).encode())
        finally:
            conn.close()
        return digest.hexdigest()

    def _legacy_ids(self, table, columns, where=None):
        """Small helper for id lists: fetch (id, extra columns) tuples of a filtered table (ints only)."""
        out = []
        for rows in self._legacy_stream(table, where=where, columns=['id'] + list(columns)):
            out.extend(rows)
        return out

    @staticmethod
    def _bulk_json(field, value):
        if value is None or value is False:
            return None
        return psycopg2.extras.Json({'en_US': value} if field.translate else value)

    def _bulk_uid(self, legacy_uid):
        return self._tags_get('res_users', legacy_uid) or self.env.uid

    # ------------------------------------------------------------------ the engine
    def _bulk_load(self, table, model, where=None, keep=None, extra=None, skip=(), only=None, raw_simple=False, raw_fields=('state',), chunk=CHUNK):
        """Copy the rows of the Odoo 12 `table` into the Odoo 19 `model` table with SQL.
        keep(row) -> bool filters rows; extra(row, vals) -> dict adds / overrides values (stored computed fields with a known formula);
        only = the only legacy columns to copy; raw_simple = copy simple stored columns as they are (no selection check);
        raw_fields = selection columns copied as they are (the state of the Odoo 12 record, also when Odoo 19 has no such state)."""
        Model = self.env[model]
        fields_ = Model._fields
        sql_table = Model._table
        started = time.time()
        self.env.flush_all()
        legacy_cols = self._legacy_columns(table)
        if not legacy_cols:
            return 0
        use = []
        for column in sorted(legacy_cols):
            if column in SKIP_COLUMNS or column in skip or (only is not None and column not in only):
                continue
            field = fields_.get(column)
            if not field or not field.store or not field.column_type or field.type in ('one2many', 'many2many', 'binary', 'html'):
                continue
            use.append(field)
        names = {f.name for f in use}
        selections = {f.name: {s[0] for s in f._description_selection(self.env)} for f in use if f.type == 'selection'}
        # Odoo 19 defaults for the stored columns that get no legacy value
        default_names = [n for n, f in fields_.items() if f.store and f.column_type and n not in ('id', 'create_uid', 'create_date', 'write_uid', 'write_date')]
        defaults = {n: v for n, v in Model.default_get(default_names).items() if n in fields_ and fields_[n].column_type}
        for name in [n for n, v in defaults.items() if v is False and fields_[n].type != 'boolean']:
            defaults[name] = None   # an empty default of a text / date / selection column is NULL, not the word false
        json_of = {n: f for n, f in fields_.items() if f.store and f.column_type and f.column_type[0] == 'jsonb'}
        for name in [n for n in defaults if n in json_of]:   # translated text columns are jsonb: {'en_US': text}
            defaults[name] = self._bulk_json(json_of[name], defaults[name])
        ids_of = self._bulk_map(table, model)
        seq = '%s_id_seq' % sql_table
        cr = self.env.cr
        count = 0
        for rows in self._legacy_stream(table, where=where, chunk=chunk):
            vals_list, legacy_ids, dates = [], [], []
            for row in rows:
                if keep and not keep(row):
                    continue
                vals = {}
                for field in use:
                    name = field.name
                    value = row.get(name)
                    if value is None and field.required:
                        continue   # an empty Odoo 12 value must not blank a required Odoo 19 field
                    if value is None and not raw_simple and field.type in ('integer', 'float', 'monetary', 'boolean'):
                        value = False if field.type == 'boolean' else 0   # what the ORM writes for an empty number or flag
                    if field.type == 'many2one':
                        value = self._map_m2o(field.comodel_name, value) or None
                    elif value is not None:
                        if field.type == 'integer':
                            value = int(value)
                        elif field.type == 'float':
                            value = float(value)
                        elif field.type in ('char', 'text'):
                            value = value if isinstance(value, str) else str(value)
                        elif field.type == 'selection' and not raw_simple and name not in raw_fields:
                            if not value or value not in selections[name]:
                                continue   # unknown or empty: keep the Odoo 19 default
                    if field.type == 'selection' and not raw_simple and name not in raw_fields and value is None:
                        continue
                    if name in json_of:
                        value = self._bulk_json(field, value)
                    vals[name] = value
                if extra:
                    vals.update(extra(row, vals) or {})
                vals_list.append(vals)
                legacy_ids.append(row['id'])
                dates.append((row.get('create_date'), row.get('write_date'), row.get('create_uid'), row.get('write_uid')))
            if not vals_list:
                continue
            columns = sorted(set().union(*[v.keys() for v in vals_list]) | {n for n in defaults if n not in names})
            columns = [c for c in columns if c in fields_ and fields_[c].column_type]
            new_idx = [i for i, lid in enumerate(legacy_ids) if lid not in ids_of]
            new_ids = []
            if new_idx:
                cr.execute('SELECT nextval(%%s) FROM generate_series(1, %d)' % len(new_idx), [seq])
                new_ids = [r[0] for r in cr.fetchall()]
            new_of = dict(zip(new_idx, new_ids))
            utc_now = psycopg2.extensions.AsIs("now() at time zone 'UTC'")
            items = []   # (legacy id, is new, row tuple)
            for i, vals in enumerate(vals_list):
                res_id = new_of.get(i) or ids_of[legacy_ids[i]]
                created, written, cuid, wuid = dates[i]
                data = tuple([res_id] + [vals.get(c, defaults.get(c)) for c in columns] + [
                    self._bulk_uid(cuid), created or utc_now, self._bulk_uid(wuid), written or utc_now])
                items.append((legacy_ids[i], i in new_of, data))
            all_columns = ['id'] + columns + ['create_uid', 'create_date', 'write_uid', 'write_date']
            col_sql = ', '.join('"%s"' % c for c in all_columns)
            template = '(' + ', '.join(['%s'] * len(all_columns)) + ')'
            sets = ', '.join('"%s" = EXCLUDED."%s"' % (c, c) for c in all_columns if c not in ('id', 'create_uid', 'create_date'))
            insert_sql = 'INSERT INTO "%s" (%s) VALUES %%s' % (sql_table, col_sql)
            upsert_sql = insert_sql + ' ON CONFLICT (id) DO UPDATE SET ' + sets
            failed = set()
            try:
                with cr.savepoint():
                    fresh = [d for _l, is_new, d in items if is_new]
                    old = [d for _l, is_new, d in items if not is_new]
                    if fresh:
                        psycopg2.extras.execute_values(cr._obj, insert_sql, fresh, template=template, page_size=1000)
                    if old:
                        psycopg2.extras.execute_values(cr._obj, upsert_sql, old, template=template, page_size=1000)
            except Exception as error:   # noqa: BLE001 - find the bad rows one by one, the run goes on
                _logger.warning('legacy bulk %s: chunk failed (%s), retrying row by row', table, str(error).strip().splitlines()[0])
                for legacy_id, _is_new, data in items:
                    try:
                        with cr.savepoint():
                            psycopg2.extras.execute_values(cr._obj, upsert_sql, [data], template=template)
                    except Exception as row_error:   # noqa: BLE001
                        failed.add(legacy_id)
                        self._state['stats'][(table, 'failed')] += 1
                        message = '%s %s: %s' % (table, legacy_id, str(row_error).strip().splitlines()[0])
                        self._state['errors'].append(message)
                        _logger.warning('legacy bulk: %s', message)
            new_of = {i: rid for i, rid in new_of.items() if legacy_ids[i] not in failed}
            loaded = self._state.setdefault('bulk_loaded', {}).setdefault(table, {})   # legacy id -> res id of every row this run wrote (the window)
            loaded.update({lid: data[0] for lid, _n, data in items if lid not in failed})
            tags = [(TAG_MODULE, '%s_%s' % (table, legacy_ids[i]), model, rid) for i, rid in new_of.items()]
            if tags:
                uid = int(self.env.uid)
                psycopg2.extras.execute_values(
                    cr._obj, 'INSERT INTO ir_model_data (module, name, model, res_id, noupdate, create_uid, write_uid, create_date, write_date) VALUES %s '
                    'ON CONFLICT (module, name) DO UPDATE SET res_id = EXCLUDED.res_id',
                    tags, template="(%%s, %%s, %%s, %%s, true, %d, %d, now() at time zone 'UTC', now() at time zone 'UTC')" % (uid, uid), page_size=1000)
                for i, rid in new_of.items():
                    ids_of[legacy_ids[i]] = rid
            self._state['stats'][(table, 'created')] += len(new_of)
            self._state['stats'][(table, 'updated')] += len([1 for i in range(len(vals_list)) if i not in new_of and legacy_ids[i] in ids_of])
            self._state['stats'][(table, 'rows read')] += len(vals_list)
            count += len(vals_list)
        self.env.invalidate_all()
        _logger.info('legacy bulk %s -> %s: %d rows in %.1f s', table, sql_table, count, time.time() - started)
        return count

    def _bulk_window(self):
        """True when the run is limited to a date window (nightly delta): the side tables and the requests of the window are rewritten, not all of them."""
        return bool(self._state['options'].get('date_from'))

    def _bulk_loaded(self, table):
        """{legacy id: res id} of the rows of `table` written in this run."""
        return self._state.get('bulk_loaded', {}).get(table, {})

    def _bulk_relation(self, rel_table, column_a, column_b, map_a, map_b, target_rel, target_a, target_b, delete_ids=None, chunk=20000, limit_a=None):
        """Copy a many2many side table (streamed). map_a / map_b: legacy id -> res_id dicts (or callables); rows with an unmapped side are skipped.
        limit_a: set of res ids of the left side to copy (None = all); with it, delete_ids defaults to the same set."""
        cr = self.env.cr
        self.env.flush_all()
        if limit_a is not None and delete_ids is None:
            delete_ids = limit_a
        if delete_ids:
            ids = list(delete_ids)
            for i in range(0, len(ids), 100000):
                cr.execute('DELETE FROM "%s" WHERE "%s" = ANY(%%s)' % (target_rel, target_a), [ids[i:i + 100000]])
        total = skipped = 0
        for rows in self._legacy_stream(rel_table, chunk=chunk, columns=[column_a, column_b], order=None):
            data = []
            for r in rows:
                a = map_a(r[column_a]) if callable(map_a) else map_a.get(r[column_a])
                b = map_b(r[column_b]) if callable(map_b) else map_b.get(r[column_b])
                if a and b and (limit_a is None or a in limit_a):
                    data.append((a, b))
                elif a and b:
                    continue
                else:
                    skipped += 1
            if data:
                psycopg2.extras.execute_values(cr._obj, 'INSERT INTO "%s" ("%s", "%s") VALUES %%s ON CONFLICT DO NOTHING' % (target_rel, target_a, target_b), data, page_size=5000)
            total += len(data)
        self.env.invalidate_all()
        self._state['stats'][(rel_table, 'rows copied')] += total
        if skipped:
            self._state['stats'][(rel_table, 'rows skipped (side not imported)')] += skipped
        return total

    # ------------------------------------------------------------------ the bulk steps
    def _bulk_hr_attendance(self):
        self._ensure_codes()
        legacy_emp = set(self._state['legacy_employees'])
        from odoo.addons.kdvn_hr_attendance.models.hr_attendance_location import summary_key
        import datetime
        import pytz
        employees = self.env['hr.employee'].with_context(active_test=False).search([])
        tz_of = {emp.id: pytz.timezone(emp._get_tz() or 'UTC') for emp in employees}

        def extra(row, vals):
            worked = row.get('worked_hours') or 0.0
            out = {'expected_hours': worked, 'overtime_hours': 0.0, 'validated_overtime_hours': 0.0}   # core formulas: worked - overtime lines (none), validated lines (none)
            emp = vals.get('employee_id')
            if emp and row.get('at_year') and row.get('at_month'):
                out['summary_id'] = summary_key(emp, row['at_year'], row['at_month'])
            check_in = vals.get('check_in')   # core precompute: the local date of the check in (employee time zone)
            out['date'] = pytz.utc.localize(check_in).astimezone(tz_of.get(emp, pytz.utc)).date() if check_in else datetime.date.today()
            return out
        self._bulk_load('hr_attendance', 'hr.attendance', where=self._window_where('at_date'), raw_simple=True,
                        keep=lambda row: row['employee_id'] in legacy_emp, extra=extra)
        ats = self._bulk_map('hr_attendance', 'hr.attendance')
        limit = set(self._bulk_loaded('hr_attendance').values()) if self._bulk_window() else None
        # status marks (many2many) straight from the legacy relation
        field = self.env['hr.attendance']._fields['status_ids']
        self._bulk_relation('hr_attendance_kderp_base_code_rel', 'hr_attendance_id', 'kderp_base_code_id', ats,
                            lambda legacy_id: self._tags_get('kderp_base_code', legacy_id), field.relation, field.column1, field.column2,
                            delete_ids=ats.values() if limit is None else None, limit_a=limit)

    def _bulk_hr_attendance_raw(self):
        legacy_emp = set(self._state['legacy_employees'])
        self._bulk_load('hr_attendance_raw', 'hr.attendance.raw', where=self._window_where('check_date'), keep=lambda row: row['employee_id'] in legacy_emp)

    def _bulk_hr_attendance_request(self):
        self._ensure_codes()
        ats = self._bulk_map('hr_attendance', 'hr.attendance')
        if self._bulk_window():
            ats = self._bulk_loaded('hr_attendance')   # nightly delta: the requests of the attendance days of the window
        self._bulk_load('hr_attendance_request', 'hr.attendance.request', skip=('state_gm', 'state_no_gm'), keep=lambda row: row['at_id'] in ats)

    def _bulk_hr_attendance_ot_plans(self):
        months = self._window_months()
        legacy_emp = set(self._state['legacy_employees'])

        def wanted(row):
            return row['employee_id'] in legacy_emp and (months is None or (int(row['at_year']), int(row['at_month'])) in months)
        self._bulk_load('hr_attendance_ot_holiday', 'hr.attendance.ot.holiday', keep=wanted)
        plans = self._bulk_map('hr_attendance_ot_holiday', 'hr.attendance.ot.holiday')
        self._bulk_load('hr_attendance_ot_holiday_line', 'hr.attendance.ot.holiday.line', keep=lambda row: row['ot_holiday_reg_id'] in plans)

    def _bulk_employee_facts(self):
        """{employee id: (department id, resource calendar id)} of the Odoo 19 employees: what the ORM computes for leaves and allocations."""
        self.env.cr.execute("SELECT e.id, r.calendar_id FROM hr_employee e LEFT JOIN resource_resource r ON r.id = e.resource_id")
        calendar = dict(self.env.cr.fetchall())
        employees = self.env['hr.employee'].with_context(active_test=False).search([])   # department_id is not a column of hr_employee in Odoo 19
        return {emp.id: (emp.department_id.id or None, calendar.get(emp.id)) for emp in employees}

    def _bulk_hours_per_day(self):
        self.env.cr.execute("""SELECT e.id, c.hours_per_day FROM hr_employee e JOIN resource_resource r ON r.id = e.resource_id
                               LEFT JOIN resource_calendar c ON c.id = r.calendar_id""")
        return {emp: hours for emp, hours in self.env.cr.fetchall()}

    def _bulk_hr_leave_allocation(self):
        legacy_emp = set(self._state['legacy_employees'])
        hours = self._bulk_hours_per_day()
        self.env.cr.execute('SELECT id, validity_start, validity_stop FROM hr_leave_type')
        validity = {i: (start, stop) for i, start, stop in self.env.cr.fetchall()}

        facts = self._bulk_employee_facts()

        def extra(row, vals):
            per_day = hours.get(vals.get('employee_id'))
            out = {} if vals.get('department_id') else {'department_id': facts.get(vals.get('employee_id'), (None, None))[0]}
            out['number_of_hours_display'] = (vals.get('number_of_days') or 0.0) * (per_day if per_day is not None else 24)
            start, stop = validity.get(vals.get('holiday_status_id'), (None, None))
            if start and not vals.get('date_from'):   # create() of kdvn_hr_attendance: the validity of the leave type (Odoo 12 had no dates on allocations)
                out['date_from'] = start
            if stop and not vals.get('date_to'):
                out['date_to'] = stop
            return out
        self._bulk_load('hr_leave_allocation', 'hr.leave.allocation', skip=('holiday_type',), keep=lambda row: row['employee_id'] in legacy_emp, extra=extra)

    def _bulk_hr_leave(self):
        legacy_emp = set(self._state['legacy_employees'])
        opts = self._state['options']
        parts = []
        if opts.get('date_from'):
            parts.append("date(date_to) >= '%s'" % _iso(opts['date_from']))
        if opts.get('date_to'):
            parts.append("date(date_from) <= '%s'" % _iso(opts['date_to']))
        where = ' AND '.join(parts) or None
        leaves = {r['id']: r for r in self._legacy_ids('hr_leave', ['employee_id', 'leave_cover_id'], where=where) if r['employee_id'] in legacy_emp}
        covers = {r['leave_cover_id'] for r in leaves.values() if r.get('leave_cover_id')}
        # covers without any leave yet (drafts, requests waiting for approval) of the imported staff: they are pending requests, not leftovers
        cover_where = '(date_from IS NULL OR date_to IS NULL OR (%s))' % where if where else None   # incomplete drafts have no dates
        covers |= {r['id'] for r in self._legacy_ids('hr_leave_cover', ['employee_id'], where=cover_where) if r['employee_id'] in legacy_emp}
        self._bulk_load('hr_leave_cover', 'hr.leave.cover', skip=('leave_request_ids',), keep=lambda row: row['id'] in covers)
        self.env.cr.execute('SELECT id, request_unit FROM hr_leave_type')
        unit_of = dict(self.env.cr.fetchall())

        hours_of = self._bulk_hours_per_day()
        facts = self._bulk_employee_facts()

        def extra(row, vals):
            unit = unit_of.get(vals.get('holiday_status_id'))
            days = vals.get('number_of_days') or 0.0
            per_day = hours_of.get(vals.get('employee_id'))
            out_hours = {'request_unit_half': True}
            if not vals.get('resource_calendar_id'):   # computed from the employee by the ORM
                out_hours['resource_calendar_id'] = facts.get(vals.get('employee_id'), (None, None))[1]   # kdvn_hr_attendance: the compute of request_unit_half is True for every leave (Odoo 12 style half day periods)
            if not vals.get('number_of_hours'):
                out_hours['number_of_hours'] = days * (per_day if per_day is not None else 24)
            if unit == 'hour':
                hours, minutes = divmod(abs(vals.get('number_of_hours') or 0.0) * 60, 60)
                minutes = round(minutes)
                if minutes == 60:
                    minutes, hours = 0, hours + 1
                return dict(out_hours, duration_display='%d:%02d hours' % (hours, minutes))
            return dict(out_hours, duration_display='%g days' % round(days, 2))
        self._bulk_load('hr_leave', 'hr.leave', where=where, keep=lambda row: row['id'] in leaves, extra=extra)
        self._bulk_calendar_leaves()

    def _bulk_calendar_leaves(self):
        """Calendar entries of the validated leaves (the status computation reads them)."""
        legacy_conn = self._legacy_ids('hr_employee', ['resource_id'])
        resource_of = {r['id']: r['resource_id'] for r in legacy_conn}
        self.env.cr.execute('SELECT id, resource_id FROM hr_employee')
        target_resource = dict(self.env.cr.fetchall())
        emp_of_resource = {}
        for legacy_emp_id, resource in resource_of.items():
            emp = self._tags_get('hr_employee', legacy_emp_id)
            if emp:
                emp_of_resource[resource] = target_resource.get(emp)
        default_calendar = self.env.company.resource_calendar_id.id
        leaves = self._bulk_map('hr_leave', 'hr.leave')

        def extra(row, vals):
            return {'resource_id': emp_of_resource.get(row['resource_id'], None), 'time_type': row.get('time_type') or 'leave',
                    'calendar_id': self._tags_get('resource_calendar', row['calendar_id']) or default_calendar}
        self._bulk_load('resource_calendar_leaves', 'resource.calendar.leaves', where='holiday_id IS NOT NULL',
                        only=('name', 'date_from', 'date_to', 'holiday_id', 'resource_id', 'time_type', 'calendar_id'),
                        keep=lambda row: row['holiday_id'] in leaves, extra=extra)

    def _bulk_links(self):
        """hr.attendance.leave_cover_ids (which covers touch an attendance day) from the legacy relation."""
        field = self.env['hr.attendance']._fields['leave_cover_ids']
        ats = self._bulk_map('hr_attendance', 'hr.attendance')
        covers = self._bulk_map('hr_leave_cover', 'hr.leave.cover')
        limit = set(self._bulk_loaded('hr_attendance').values()) if self._bulk_window() else None
        if field.type == 'many2many':
            self._bulk_relation('hr_attendance_hr_leave_cover_rel', 'hr_attendance_id', 'hr_leave_cover_id', ats, covers,
                                field.relation, field.column1, field.column2, delete_ids=ats.values() if limit is None else None, limit_a=limit)
        # which leaves touch an attendance day (the status computation reads it; the ORM fills it when a leave is created)
        field = self.env['hr.attendance']._fields['leave_ids']
        if field.type == 'many2many':
            self._bulk_relation('hr_attendance_hr_leave_rel', 'hr_attendance_id', 'hr_leave_id', ats, self._bulk_map('hr_leave', 'hr.leave'),
                                field.relation, field.column1, field.column2, delete_ids=ats.values() if limit is None else None, limit_a=limit)

    def _bulk_view_users(self):
        users = {t[1]: v for t, v in self._state['tags'].items() if t[0] == 'res_users'}
        for table, model, rel, column in (('hr_attendance', 'hr.attendance', 'hr_attendance_res_users_rel', 'hr_attendance_id'),
                                          ('hr_attendance_request', 'hr.attendance.request', 'hr_attendance_request_res_users_rel', 'hr_attendance_request_id'),
                                          ('hr_leave_cover', 'hr.leave.cover', 'hr_leave_cover_res_users_rel', 'hr_leave_cover_id')):
            records = self._bulk_map(table, model)
            limit = set(self._bulk_loaded(table).values()) if self._bulk_window() else None
            if records and (limit is None or limit):
                self._bulk_relation(rel, column, 'res_users_id', records, users, rel, column, 'res_users_id',
                                    delete_ids=records.values() if limit is None else None, limit_a=limit)

    # ------------------------------------------------------------------ prune (hard deletes of Odoo 12)
    # children first: a request / OT line / calendar entry / leave must go before the record it points to
    _PRUNE_TABLES = (
        ('hr_attendance_request', 'hr.attendance.request', 'at_id IS NOT NULL'),   # a request whose day was deleted keeps its row in Odoo 12 with at_id NULL: the loader never imports those
        ('hr_attendance_ot_holiday_line', 'hr.attendance.ot.holiday.line', None),
        ('hr_attendance_ot_holiday', 'hr.attendance.ot.holiday', None),
        ('resource_calendar_leaves', 'resource.calendar.leaves', 'holiday_id IS NOT NULL'),   # the same filter the loader uses
        ('hr_leave', 'hr.leave', None),
        ('hr_leave_cover', 'hr.leave.cover', None),
        ('hr_leave_allocation', 'hr.leave.allocation', None),
        ('hr_attendance_raw', 'hr.attendance.raw', None),
        ('hr_attendance', 'hr.attendance', None),
    )
    PRUNE_LIMIT_RATIO = 0.02    # more than 2 % of a table (and more than PRUNE_LIMIT_MIN rows) gone from Odoo 12 looks like a bad snapshot, not real deletes
    PRUNE_LIMIT_MIN = 200

    def _step_prune(self):
        """Delete from Odoo 19 the imported records (external id legacy12.<table>_<id>) whose Odoo 12 row no longer exists.
        Never touches a record without that external id. Every table: count first and log it; a deletion bigger than the safety limit is NOT done
        (an empty or truncated snapshot must not wipe the history) unless prune_force. prune='dry' only counts."""
        mode = self._state['options'].get('prune')
        if not mode:
            return
        if not self._state['options'].get('bulk'):
            self._state['errors'].append('prune needs the bulk loader (--bulk): skipped')
            return
        cr = self.env.cr
        for table, model, where in self._PRUNE_TABLES:
            Model = self.env[model]
            exists = set()
            for rows in self._legacy_stream(table, where=where, columns=['id'], order=None):
                exists.update(r['id'] for r in rows)
            tagged = self._bulk_map(table, model)
            gone = {lid: rid for lid, rid in tagged.items() if lid not in exists}
            limit = max(self.PRUNE_LIMIT_MIN, int(len(tagged) * self.PRUNE_LIMIT_RATIO))
            line = 'prune %-32s legacy rows %7d, imported %7d, gone from Odoo 12 %5d' % (table, len(exists), len(tagged), len(gone))
            _logger.info(line)
            self._state['stats'][(table, 'prune candidates')] += len(gone)
            if not gone:
                continue
            if len(gone) > limit and not self._state['options'].get('prune_force'):
                msg = '%s: %d records are gone from Odoo 12 (limit %d): NOT deleted, check the snapshot (prune_force overrides)' % (table, len(gone), limit)
                self._state['errors'].append(msg)
                _logger.warning('legacy prune: %s', msg)
                continue
            if mode == 'dry':
                continue
            self.env.flush_all()
            deleted = failed = 0
            items = sorted(gone.items())
            for i in range(0, len(items), 1000):
                chunk = items[i:i + 1000]
                ids = [rid for _lid, rid in chunk]
                try:
                    with cr.savepoint():
                        cr.execute('DELETE FROM "%s" WHERE id = ANY(%%s)' % Model._table, [ids])
                        done = chunk
                except Exception:   # noqa: BLE001 - a dependent row blocks it: one by one, the blocked ones stay and are listed
                    done = []
                    for lid, rid in chunk:
                        try:
                            with cr.savepoint():
                                cr.execute('DELETE FROM "%s" WHERE id = %%s' % Model._table, [rid])
                            done.append((lid, rid))
                        except Exception as error:   # noqa: BLE001
                            failed += 1
                            message = 'prune %s %s (res id %s): %s' % (table, lid, rid, str(error).strip().splitlines()[0])
                            self._state['errors'].append(message)
                            _logger.warning('legacy prune: %s', message)
                if done:
                    cr.execute('DELETE FROM ir_model_data WHERE module = %s AND model = %s AND res_id = ANY(%s)', (TAG_MODULE, model, [rid for _l, rid in done]))
                    for lid, _rid in done:
                        tagged.pop(lid, None)
                    deleted += len(done)
            self.env.invalidate_all()
            self._state['stats'][(table, 'pruned')] += deleted
            _logger.info('legacy prune %s: %d deleted, %d blocked', table, deleted, failed)
