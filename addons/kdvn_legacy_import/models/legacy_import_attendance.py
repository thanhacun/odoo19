"""Attendance data of the Odoo 12 module kderp_hr_attendance (stored values are copied as they are; nothing is recomputed).

Steps (added only when kdvn_hr_attendance is installed): company policy, calendars, public holidays, face machines (locations), rules,
attendance days of the date window (+ their status marks), raw checks, requests, OT holiday plans.
Time off (leave covers, leaves, allocations) is stage B of the port and not imported yet.
"""
import datetime
import logging
import re

from odoo import api, models

_logger = logging.getLogger(__name__)

SKIP_COLUMNS = {'id', 'create_uid', 'write_uid', 'create_date', 'write_date', 'message_main_attachment_id', 'summary_id'}
POLICY_COLUMNS = ['rule_at_start_date', 'rule_day_start_hour', 'rule_working_start_hour', 'rule_late_in_early_out', 'rule_absence',
                  'rule_special_ot_hour', 'rule_delay_duration', 'rule_early_offset_max', 'description_size', 'app_start_date',
                  'ot_request_before', 'wt_request_before', 'leave_request_before', 'gm_leave_days_limit', 'gm_absence_days_limit',
                  'gm_ot_over_hours_limit', 'gm_late_request']


def _iso(value):
    """Only ISO dates go into the SQL where clause."""
    text = str(value)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        raise ValueError('bad date %r' % text)
    return text


class KdvnLegacyImportAttendance(models.AbstractModel):
    _inherit = 'kdvn.legacy.import'

    def _import_steps(self):
        steps = super()._import_steps()
        if 'hr.attendance.rule' in self.env and 'at_date' in self.env['hr.attendance']._fields and 'hr.attendance.request' in self.env:
            steps += [
                ('at_policy', self._step_at_policy),
                ('at_calendars', self._step_at_calendars),
                ('at_holidays', self._step_at_holidays),
                ('at_locations', self._step_at_locations),
                ('at_codes', self._step_at_codes),
                ('at_rules', self._step_at_rules),
                ('at_attendance', self._step_at_attendance),
                ('at_raw', self._step_at_raw),
                ('at_requests', self._step_at_requests),
                ('at_ot_plans', self._step_at_ot_plans),
                ('lv_reasons', self._step_lv_reasons),
                ('lv_types', self._step_lv_types),
                ('lv_allocations', self._step_lv_allocations),
                ('lv_leaves', self._step_lv_leaves),
                ('lv_links', self._step_lv_links),
                ('at_refuse', self._step_at_refuse),
                ('at_view_users', self._step_at_view_users),
                ('at_restore', self._step_at_restore),
            ]
        return steps

    # ------------------------------------------------------------------ helpers
    def _window_where(self, column):
        opts = self._state['options']
        parts = []
        if opts.get('date_from'):
            parts.append("%s >= '%s'" % (column, _iso(opts['date_from'])))
        if opts.get('date_to'):
            parts.append("%s <= '%s'" % (column, _iso(opts['date_to'])))
        return ' AND '.join(parts) or None

    def _window_months(self):
        """[(year, month)] of the attendance months touched by the date window (None = no limit)."""
        opts = self._state['options']
        if not (opts.get('date_from') and opts.get('date_to')):
            return None
        mixin = self.env['hr.mixin']
        start = datetime.date.fromisoformat(_iso(opts['date_from']))
        end = datetime.date.fromisoformat(_iso(opts['date_to']))
        out, day = set(), start
        while day <= end:
            out.add(mixin.get_at_year_month(day))
            day += datetime.timedelta(days=7)
        out.add(mixin.get_at_year_month(end))
        return out

    def _table_of(self, comodel):
        return comodel.replace('.', '_')

    def _map_m2o(self, comodel, legacy_id):
        if not legacy_id:
            return False
        if comodel == 'res.company':
            return self.env.company.id
        if comodel == 'res.country':
            return self._state.setdefault('country_map', {}).get(legacy_id, False)
        return self._tags_get(self._table_of(comodel), legacy_id)

    def _tags_get(self, table, legacy_id):
        return self._state['tags'].get((table, legacy_id), False)

    def _convert_row(self, model, row, skip=()):
        """Odoo 12 row -> create values: stored fields with the same name; many2one through the tags; x2many ignored."""
        fields_ = self.env[model]._fields
        vals = {}
        for column, value in row.items():
            if column in SKIP_COLUMNS or column in skip:
                continue
            field = fields_.get(column)
            if not field or not field.store or field.type in ('one2many', 'many2many', 'binary', 'html') or field.compute and not field.store:
                continue
            if value is None and field.required:
                continue   # an empty Odoo 12 value must not blank a required Odoo 19 field (dates of allocations...)
            if field.type == 'many2one':
                value = self._map_m2o(field.comodel_name, value)
            elif value is not None and field.type == 'integer':
                value = int(value)
            vals[column] = value
        return vals

    def _copy_table(self, table, model, where=None, natural=None, skip=(), filter_row=None, extra=None, context=None):
        """Copy every row of an Odoo 12 table (re-runnable). natural(row, vals) -> domain of an existing record to adopt."""
        Model = self.with_context(**(context or {}))
        count = 0
        for row in self._legacy_rows(table, None, where=where):
            if filter_row and not filter_row(row):
                continue
            vals = self._convert_row(model, row, skip)
            if extra:
                vals.update(extra(row, vals) or {})
            domain = natural(row, vals) if natural else None
            Model._safe(table, row['id'], str(row.get('code') or row.get('name') or ''), lambda row=row, vals=vals, domain=domain: Model._upsert(
                model, table, row['id'], vals, natural=domain))
            count += 1
        self._state['stats'][(table, 'rows read')] += count

    # ------------------------------------------------------------------ steps
    def _step_at_policy(self):
        rows = self._legacy_rows('res_company', ['id'] + POLICY_COLUMNS + ['resource_calendar_id'])
        if not rows:
            return
        row = rows[0]
        vals = {c: row[c] for c in POLICY_COLUMNS if row.get(c) is not None and c in self.env.company._fields}
        self._state['policy_calendar'] = row.get('resource_calendar_id')
        self._safe('res_company', row['id'], 'policy', lambda: self.env.company.write(vals))

    def _step_at_calendars(self):
        for row in self._legacy_rows('resource_calendar', ['id', 'name', 'tz']):
            vals = {'name': row['name'], 'tz': row['tz'] or 'Asia/Ho_Chi_Minh'}
            cal = self._safe('resource_calendar', row['id'], row['name'], lambda row=row, vals=vals: self._upsert(
                'resource.calendar', 'resource_calendar', row['id'], vals, natural=[('name', '=', row['name'])]))
            if not cal:
                continue
            lines = [r for r in self._legacy_rows('resource_calendar_attendance', ['id', 'name', 'dayofweek', 'hour_from', 'hour_to', 'day_period', 'calendar_id'])
                     if r['calendar_id'] == row['id']]
            if lines:
                cal.attendance_ids.unlink()
                cal.write({'attendance_ids': [(0, 0, {'name': l['name'] or 'line', 'dayofweek': str(l['dayofweek']), 'hour_from': l['hour_from'], 'hour_to': l['hour_to'],
                                                      'day_period': l['day_period'] or ('morning' if l['hour_from'] < 12 else 'afternoon')}) for l in lines]})
                for l in lines:
                    self._state['tags'][('resource_calendar_attendance', l['id'])] = cal.attendance_ids[:1].id
        default = self._state.get('policy_calendar')
        if default and self._tags_get('resource_calendar', default):
            self.env.company.resource_calendar_id = self._tags_get('resource_calendar', default)
        # employees keep the working calendar and time zone they had in Odoo 12. Otherwise an adopted employee stays on Odoo 19's
        # default calendar / UTC, working hours are read as UTC and leaves created on the company calendar never reduce them.
        resources = {r['id']: r for r in self._legacy_rows('resource_resource', ['id', 'calendar_id', 'tz'])}
        for row in self._legacy_rows('hr_employee', ['id', 'resource_id']):
            employee = self._record('hr.employee', 'hr_employee', row['id'])
            res = resources.get(row['resource_id']) or {}
            calendar_id = self._tags_get('resource_calendar', res.get('calendar_id'))
            vals = {}
            if calendar_id and employee and employee.resource_calendar_id.id != calendar_id:
                vals['resource_calendar_id'] = calendar_id
            if res.get('tz') and employee and employee.resource_id.tz != res['tz']:
                vals['tz'] = res['tz']
            if vals:
                self._safe('hr_employee', row['id'], 'calendar', lambda employee=employee, vals=vals: employee.write(vals))

    def _step_at_holidays(self):
        self._load_countries()
        for c in self._legacy_rows('res_country', ['id', 'code']):
            country = self.env['res.country'].search([('code', '=', c['code'])], limit=1)
            if country:
                self._state.setdefault('country_map', {})[c['id']] = country.id
        self._copy_table('hr_holidays_public', 'hr.holidays.public',
                         natural=lambda row, vals: [('year', '=', row['year']), ('country_id', '=', vals.get('country_id') or False)])
        self._copy_table('hr_holidays_public_line', 'hr.holidays.public.line',
                         natural=lambda row, vals: [('year_id', '=', vals.get('year_id')), ('date', '=', row['date']), ('name', '=', row['name'])],
                         extra=lambda row, vals: {'resource_calendar_id': self._tags_get('resource_calendar', row.get('resource_calendar_id')) or self.env.company.resource_calendar_id.id})

    def _step_at_locations(self):
        self._copy_table('hr_attendance_location', 'hr.attendance.location', natural=lambda row, vals: [('code', '=', row['code'])])

    def _load_countries(self):
        pass

    def _ensure_codes(self):
        if not self._state.get('codes_ready'):
            self._step_at_codes()
            self._state['codes_ready'] = True

    def _step_at_codes(self):
        """Status marks (O, X, L...) and states of hr.attendance exist in Odoo 19 from the module data: map the Odoo 12 rows to them by code."""
        models_ = {r['id']: r['model'] for r in self._legacy_rows('ir_model', ['id', 'model'])}
        for table, model in (('kderp_base_code', 'kderp.base.code'), ('kderp_base_state', 'kderp.base.state')):
            for row in self._legacy_rows(table, ['id', 'code', 'model_id', 'type_code']):
                domain = [('code', '=', row['code']), ('model_id.model', '=', models_.get(row['model_id'], 'hr.attendance'))]
                target = self.env[model].with_context(active_test=False).search(domain, limit=1)
                if target:
                    self._state['tags'][(table, row['id'])] = target.id

    def _step_at_rules(self):
        self._copy_table('hr_attendance_rule', 'hr.attendance.rule')
        employees = {}
        for r in self._legacy_rows('hr_attendance_rule_hr_employee_rel', None):
            emp = self._tags_get('hr_employee', r['hr_employee_id'])
            if emp:
                employees.setdefault(r['hr_attendance_rule_id'], []).append(emp)
        depts = {}
        for r in self._legacy_rows('hr_attendance_rule_hr_department_rel', None):
            dep = self._tags_get('hr_department', r['hr_department_id'])
            if dep:
                depts.setdefault(r['hr_attendance_rule_id'], []).append(dep)
        for rule_id in {t[1] for t in self._state['tags'] if t[0] == 'hr_attendance_rule'}:
            rule = self.env['hr.attendance.rule'].browse(self._state['tags'][('hr_attendance_rule', rule_id)]).exists()
            if rule:
                self._safe('hr_attendance_rule', rule_id, 'members', lambda rule=rule, rule_id=rule_id: rule.write(
                    {'employee_ids': [(6, 0, employees.get(rule_id, []))], 'department_ids': [(6, 0, depts.get(rule_id, []))]}))
        self.env['hr.attendance'].clear_at_rules_memo()

    def _step_at_attendance(self):
        self._ensure_codes()
        legacy_emp = set(self._state['legacy_employees'])
        where = self._window_where('at_date')
        self._copy_table('hr_attendance', 'hr.attendance', where=where,
                         filter_row=lambda row: row['employee_id'] in legacy_emp,
                         natural=lambda row, vals: [('code', '=', row['code'])],
                         context={'do_not_run_at_status': True, 'kdvn_no_compute': True, 'kdvn_skip_checkin_check': True},
                         skip=('state', 'status_codes', 'request_leave', 'leave_cover_ids', 'related_leaves_count'))
        self._write_status_marks()

    def _write_status_marks(self):
        """Status marks (O, X, L, AH... many2many) of the imported days, as Odoo 12 had them."""
        self._ensure_codes()
        ats = {t[1]: v for t, v in self._state['tags'].items() if t[0] == 'hr_attendance'}
        if not ats:
            return
        marks = {}
        for r in self._legacy_rows('hr_attendance_kderp_base_code_rel', None):
            if r['hr_attendance_id'] in ats:
                code = self._tags_get('kderp_base_code', r['kderp_base_code_id'])
                if code:
                    marks.setdefault(r['hr_attendance_id'], []).append(code)
        # straight SQL on the relation table: writing the many2many through the ORM makes Odoo 19 recompute the status
        # fields of every day (minutes per month); the Odoo 12 values are restored as they are anyway
        field = self.env['hr.attendance']._fields['status_ids']
        self.env.flush_all()
        ids = [ats[i] for i in marks]
        self.env.cr.execute('DELETE FROM "%s" WHERE "%s" = ANY(%%s)' % (field.relation, field.column1), [ids])
        rows = [(ats[legacy_id], code) for legacy_id, codes in marks.items() for code in sorted(set(codes))]
        if rows:
            self.env.cr.executemany('INSERT INTO "%s" ("%s", "%s") VALUES (%%s, %%s) ON CONFLICT DO NOTHING' % (field.relation, field.column1, field.column2), rows)
        self.env.invalidate_all()

    def _step_at_raw(self):
        legacy_emp = set(self._state['legacy_employees'])
        self._copy_table('hr_attendance_raw', 'hr.attendance.raw', where=self._window_where('check_date'),
                         filter_row=lambda row: row['employee_id'] in legacy_emp,
                         natural=lambda row, vals: [('at_code', '=', row['at_code'])] if row['at_code'] else None)

    def _step_at_requests(self):
        self._ensure_codes()
        ats = {t[1] for t in self._state['tags'] if t[0] == 'hr_attendance'}
        self._copy_table('hr_attendance_request_type', 'hr.attendance.request.type', natural=lambda row, vals: [('code', '=', row['code'])])
        self._copy_table('hr_attendance_request', 'hr.attendance.request', filter_row=lambda row: row['at_id'] in ats,
                         context={'do_not_run_at_status': True, 'kdvn_no_compute': True, 'kdvn_skip_checkin_check': True},
                         skip=('state_gm', 'state_no_gm'))

    def _step_at_refuse(self):
        """Refusal comments of the imported requests and leave covers (a comment whose request or cover is outside the window is skipped)."""
        tags = self._state['tags']

        def wanted(row):
            return ((row['related_request_id'] and ('hr_attendance_request', row['related_request_id']) in tags)
                    or (row['related_leave_cover_id'] and ('hr_leave_cover', row['related_leave_cover_id']) in tags))
        self._copy_table('hr_attendance_refuse', 'hr.attendance.refuse', filter_row=wanted,
                         context={'do_not_run_at_status': True, 'kdvn_no_compute': True})

    def _step_at_view_users(self):
        """Who may see each imported attendance, request and leave cover (view_user_ids): the Odoo 12 lists, copied as they are.
        The record rules of the managers and GMs read them. Recomputing gives different lists (Odoo 12 also keeps past and
        functional managers), so the import never recomputes them. A user outside the imported staff is skipped (counted)."""
        users = {t[1]: v for t, v in self._state['tags'].items() if t[0] == 'res_users'}
        cr = self.env.cr
        for table, rel, column in (('hr_attendance', 'hr_attendance_res_users_rel', 'hr_attendance_id'),
                                   ('hr_attendance_request', 'hr_attendance_request_res_users_rel', 'hr_attendance_request_id'),
                                   ('hr_leave_cover', 'hr_leave_cover_res_users_rel', 'hr_leave_cover_id')):
            records = {t[1]: v for t, v in self._state['tags'].items() if t[0] == table}
            if not records:
                continue
            wanted = {}
            for row in self._legacy_rows(rel, [column, 'res_users_id']):
                if row[column] not in records:
                    continue
                user = users.get(row['res_users_id'])
                if user:
                    wanted.setdefault(records[row[column]], set()).add(user)
                else:
                    self._state['stats'][(table, 'viewers skipped (user not imported)')] += 1
            self.env.flush_all()
            ids = list(records.values())
            cr.execute('DELETE FROM %s WHERE %s = ANY(%%s)' % (rel, column), [ids])
            rows = [(rid, uid) for rid, uids in wanted.items() for uid in sorted(uids)]
            if rows:
                cr.executemany('INSERT INTO %s (%s, res_users_id) VALUES (%%s, %%s) ON CONFLICT DO NOTHING' % (rel, column), rows)
            self._state['stats'][(table, 'viewer lists restored')] += len(wanted)
        self.env.invalidate_all()

    def _step_at_restore(self):
        """LAST attendance step: write the Odoo 12 values of the stored computed columns back, straight in SQL.
        While the later steps run (raw checks, requests, leaves) Odoo 19 recomputes stored fields of the imported days (absence,
        compute_out, OT hours...) before the requests they depend on exist, and the result differs from what Odoo 12 computed
        (payroll reads these). The import never recomputes: Odoo 12's values are the truth until the parity run says otherwise."""
        ats = {t[1]: v for t, v in self._state['tags'].items() if t[0] == 'hr_attendance'}
        if not ats:
            return
        self._write_status_marks()   # the marks are recomputed by later steps too; write them first, then the SQL values on top
        self.env.flush_all()
        fields_ = self.env['hr.attendance']._fields
        simple = ('char', 'text', 'selection', 'float', 'integer', 'boolean', 'datetime', 'date')
        columns = [name for name, f in fields_.items() if f.store and f.column_type and f.type in simple
                   and name not in ('id', 'create_date', 'write_date', 'code')]
        rows = [r for r in self._legacy_rows('hr_attendance', None, where=self._window_where('at_date')) if r['id'] in ats]   # None = the columns that exist in Odoo 12 only
        if not rows:
            return
        legacy_columns = [c for c in columns if c in rows[0]]
        sql = 'UPDATE hr_attendance SET %s WHERE id = %%s' % ', '.join('"%s" = %%s' % c for c in legacy_columns)
        # stored computed many2one columns the same way (face machine locations), mapped through the import tags
        m2o = [c for c in ('check_in_location_id', 'check_out_location_id') if c in rows[0]]
        sql_m2o = ('UPDATE hr_attendance SET %s WHERE id = %%s' % ', '.join('"%s" = %%s' % c for c in m2o)) if m2o else None
        for row in rows:
            self.env.cr.execute(sql, [row[c] for c in legacy_columns] + [ats[row['id']]])
            if sql_m2o:
                self.env.cr.execute(sql_m2o, [self._tags_get('hr_attendance_location', row[c]) or None for c in m2o] + [ats[row['id']]])
        self.env.invalidate_all()
        self._state['stats'][('hr_attendance', 'values restored')] += len(rows)

    def _step_at_ot_plans(self):
        months = self._window_months()
        legacy_emp = set(self._state['legacy_employees'])

        def wanted(row):
            return row['employee_id'] in legacy_emp and (months is None or (int(row['at_year']), int(row['at_month'])) in months)
        self._copy_table('hr_attendance_ot_holiday', 'hr.attendance.ot.holiday', filter_row=wanted,
                         natural=lambda row, vals: [('employee_id', '=', vals.get('employee_id')), ('at_year', '=', str(row['at_year'])), ('at_month', '=', int(row['at_month']))],
                         context={'kdvn_no_ot_plan_sync': True, 'kdvn_no_compute': True})
        plans = {t[1] for t in self._state['tags'] if t[0] == 'hr_attendance_ot_holiday'}
        self._copy_table('hr_attendance_ot_holiday_line', 'hr.attendance.ot.holiday.line', filter_row=lambda row: row['ot_holiday_reg_id'] in plans,
                         natural=lambda row, vals: [('ot_holiday_reg_id', '=', vals.get('ot_holiday_reg_id')), ('at_date', '=', row['at_date'])],
                         context={'kdvn_no_ot_plan_sync': True, 'kdvn_no_compute': True})

    # ------------------------------------------------------------------ time off
    def _set_state(self, record, state):
        """Copy the Odoo 12 state without running the Odoo 19 approval flow (no mails, no balance checks, no calendar entries)."""
        if state and record.state != state:
            record._write({'state': state})

    def _step_lv_reasons(self):
        self._copy_table('hr_leave_cover_reason', 'hr.leave.cover.reason', natural=lambda row, vals: [('code', '=', row['code'])] if row.get('code') else [('name', '=', row['name'])])

    def _step_lv_types(self):
        def extra(row, vals):
            res = {'leave_validation_type': row.get('validation_type') if row.get('validation_type') in ('no_validation', 'hr', 'manager', 'both') else 'hr',
                    'allocation_validation_type': 'hr',
                    'request_unit': row.get('request_unit') if row.get('request_unit') in ('day', 'half_day', 'hour') else 'half_day'}
            if not self._tags_get('hr_leave_type', row['id']):   # Odoo 19 refuses to change it once leaves exist
                res['requires_allocation'] = row.get('allocation_type') != 'no'
            return res
        self._copy_table('hr_leave_type', 'hr.leave.type', extra=extra, skip=('validation_type', 'request_unit'),
                         natural=lambda row, vals: [('name', '=', row['name']), ('validity_start', '=', row.get('validity_start') or False)],
                         context={'no_filter_leave_type': True})

    def _step_lv_allocations(self):
        legacy_emp = set(self._state['legacy_employees'])
        self._copy_table('hr_leave_allocation', 'hr.leave.allocation', filter_row=lambda row: row['employee_id'] in legacy_emp,
                         natural=lambda row, vals: None, skip=('state', 'holiday_type'), context={'no_filter_leave_type': True, 'leave_skip_state_check': True, 'kdvn_no_compute': True})
        states = {r['id']: r['state'] for r in self._legacy_rows('hr_leave_allocation', ['id', 'state'])}
        for legacy_id, state in states.items():
            res_id = self._tags_get('hr_leave_allocation', legacy_id)
            if res_id:
                self._set_state(self.env['hr.leave.allocation'].browse(res_id), state)

    def _step_lv_leaves(self):
        legacy_emp = set(self._state['legacy_employees'])
        where = None
        opts = self._state['options']
        parts = []
        if opts.get('date_from'):
            parts.append("date(date_to) >= '%s'" % _iso(opts['date_from']))
        if opts.get('date_to'):
            parts.append("date(date_from) <= '%s'" % _iso(opts['date_to']))
        where = ' AND '.join(parts) or None
        leaves = [r for r in self._legacy_rows('hr_leave', None, where=where) if r['employee_id'] in legacy_emp]
        covers = {r['leave_cover_id'] for r in leaves if r.get('leave_cover_id')}
        ctx = {'kdvn_legacy_import': True, 'kdvn_no_compute': True, 'do_not_run_at_status': True, 'leave_skip_state_check': True, 'leave_skip_date_check': True, 'do_not_update_at_leave_ids': True,
               'no_filter_leave_type': True}
        self._copy_table('hr_leave_cover', 'hr.leave.cover', filter_row=lambda row: row['id'] in covers, skip=('state', 'leave_request_ids'), context=ctx)
        leave_ids = {r['id'] for r in leaves}
        self._copy_table('hr_leave', 'hr.leave', where=where, filter_row=lambda row: row['id'] in leave_ids, skip=('state',), context=ctx)
        for row in leaves:
            res_id = self._tags_get('hr_leave', row['id'])
            if res_id:
                self._set_state(self.env['hr.leave'].browse(res_id), row['state'])
        cover_states = {r['id']: r['state'] for r in self._legacy_rows('hr_leave_cover', ['id', 'state']) if r['id'] in covers}
        for legacy_id, state in cover_states.items():
            res_id = self._tags_get('hr_leave_cover', legacy_id)
            if res_id:
                cover = self.env['hr.leave.cover'].browse(res_id)
                if cover.state != state:
                    cover._write({'state': state})
        # calendar entries of the validated leaves (the status computation reads them)
        resource_of = {r['id']: r['resource_id'] for r in self._legacy_rows('hr_employee', ['id', 'resource_id'])}
        emp_of_resource = {}
        for legacy_emp_id, resource in resource_of.items():
            emp = self._tags_get('hr_employee', legacy_emp_id)
            if emp:
                emp_of_resource[resource] = self.env['hr.employee'].browse(emp).resource_id.id
        done = 0
        for row in self._legacy_rows('resource_calendar_leaves', None, where="holiday_id IS NOT NULL"):
            leave = self._tags_get('hr_leave', row['holiday_id'])
            if not leave:
                continue
            vals = {'name': row['name'], 'date_from': row['date_from'], 'date_to': row['date_to'], 'holiday_id': leave,
                    'resource_id': emp_of_resource.get(row['resource_id'], False), 'time_type': row.get('time_type') or 'leave',
                    'calendar_id': self._tags_get('resource_calendar', row['calendar_id']) or self.env.company.resource_calendar_id.id}
            self._safe('resource_calendar_leaves', row['id'], '', lambda row=row, vals=vals: self._upsert(
                'resource.calendar.leaves', 'resource_calendar_leaves', row['id'], vals))
            done += 1
        self._state['stats'][('resource_calendar_leaves', 'rows read')] += done

    def _step_lv_links(self):
        """hr.attendance.leave_cover_ids (which covers touch an attendance day)."""
        ats = {t[1]: v for t, v in self._state['tags'].items() if t[0] == 'hr_attendance'}
        covers = {t[1]: v for t, v in self._state['tags'].items() if t[0] == 'hr_leave_cover'}
        links = {}
        for r in self._legacy_rows('hr_attendance_hr_leave_cover_rel', None):
            if r['hr_attendance_id'] in ats and r['hr_leave_cover_id'] in covers:
                links.setdefault(ats[r['hr_attendance_id']], []).append(covers[r['hr_leave_cover_id']])
        for at_id, cover_ids in links.items():
            self._safe('hr_attendance', at_id, 'leave covers', lambda at_id=at_id, cover_ids=cover_ids: self.env['hr.attendance'].browse(at_id).with_context(
                do_not_run_at_status=True).write({'leave_cover_ids': [(6, 0, cover_ids)]}))
