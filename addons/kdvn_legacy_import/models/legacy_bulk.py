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

from .legacy_import import PARAM_DB, TAG_MODULE
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

    def _bulk_relation(self, rel_table, column_a, column_b, map_a, map_b, target_rel, target_a, target_b, delete_ids=None, chunk=20000):
        """Copy a many2many side table (streamed). map_a / map_b: legacy id -> res_id dicts (or callables); rows with an unmapped side are skipped."""
        cr = self.env.cr
        self.env.flush_all()
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
                if a and b:
                    data.append((a, b))
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
        # status marks (many2many) straight from the legacy relation
        field = self.env['hr.attendance']._fields['status_ids']
        self._bulk_relation('hr_attendance_kderp_base_code_rel', 'hr_attendance_id', 'kderp_base_code_id', ats,
                            lambda legacy_id: self._tags_get('kderp_base_code', legacy_id), field.relation, field.column1, field.column2,
                            delete_ids=ats.values())

    def _bulk_hr_attendance_raw(self):
        legacy_emp = set(self._state['legacy_employees'])
        self._bulk_load('hr_attendance_raw', 'hr.attendance.raw', where=self._window_where('check_date'), keep=lambda row: row['employee_id'] in legacy_emp)

    def _bulk_hr_attendance_request(self):
        self._ensure_codes()
        ats = self._bulk_map('hr_attendance', 'hr.attendance')
        self._bulk_load('hr_attendance_request', 'hr.attendance.request', skip=('state_gm', 'state_no_gm'), keep=lambda row: row['at_id'] in ats)

    def _bulk_hr_attendance_ot_plans(self):
        months = self._window_months()
        legacy_emp = set(self._state['legacy_employees'])

        def wanted(row):
            return row['employee_id'] in legacy_emp and (months is None or (int(row['at_year']), int(row['at_month'])) in months)
        self._bulk_load('hr_attendance_ot_holiday', 'hr.attendance.ot.holiday', keep=wanted)
        plans = self._bulk_map('hr_attendance_ot_holiday', 'hr.attendance.ot.holiday')
        self._bulk_load('hr_attendance_ot_holiday_line', 'hr.attendance.ot.holiday.line', keep=lambda row: row['ot_holiday_reg_id'] in plans)

    def _bulk_hours_per_day(self):
        self.env.cr.execute("""SELECT e.id, c.hours_per_day FROM hr_employee e JOIN resource_resource r ON r.id = e.resource_id
                               LEFT JOIN resource_calendar c ON c.id = r.calendar_id""")
        return {emp: hours for emp, hours in self.env.cr.fetchall()}

    def _bulk_hr_leave_allocation(self):
        legacy_emp = set(self._state['legacy_employees'])
        hours = self._bulk_hours_per_day()
        self.env.cr.execute('SELECT id, validity_start, validity_stop FROM hr_leave_type')
        validity = {i: (start, stop) for i, start, stop in self.env.cr.fetchall()}

        def extra(row, vals):
            per_day = hours.get(vals.get('employee_id'))
            out = {'number_of_hours_display': (vals.get('number_of_days') or 0.0) * (per_day if per_day is not None else 24)}
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
        self._bulk_load('hr_leave_cover', 'hr.leave.cover', skip=('leave_request_ids',), keep=lambda row: row['id'] in covers)
        self.env.cr.execute('SELECT id, request_unit FROM hr_leave_type')
        unit_of = dict(self.env.cr.fetchall())

        hours_of = self._bulk_hours_per_day()

        def extra(row, vals):
            unit = unit_of.get(vals.get('holiday_status_id'))
            days = vals.get('number_of_days') or 0.0
            per_day = hours_of.get(vals.get('employee_id'))
            out_hours = {'request_unit_half': True}   # kdvn_hr_attendance: the compute of request_unit_half is True for every leave (Odoo 12 style half day periods)
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
        if field.type == 'many2many':
            self._bulk_relation('hr_attendance_hr_leave_cover_rel', 'hr_attendance_id', 'hr_leave_cover_id', ats, covers,
                                field.relation, field.column1, field.column2, delete_ids=ats.values())

    def _bulk_view_users(self):
        users = {t[1]: v for t, v in self._state['tags'].items() if t[0] == 'res_users'}
        for table, model, rel, column in (('hr_attendance', 'hr.attendance', 'hr_attendance_res_users_rel', 'hr_attendance_id'),
                                          ('hr_attendance_request', 'hr.attendance.request', 'hr_attendance_request_res_users_rel', 'hr_attendance_request_id'),
                                          ('hr_leave_cover', 'hr.leave.cover', 'hr_leave_cover_res_users_rel', 'hr_leave_cover_id')):
            records = self._bulk_map(table, model)
            if records:
                self._bulk_relation(rel, column, 'res_users_id', records, users, rel, column, 'res_users_id', delete_ids=records.values())
