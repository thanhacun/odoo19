"""Data and quick actions for the KDERP dashboard (client action 'kdvn_dashboard').

The dashboard is an extra layer: it reads, and it calls the methods and actions that
kderp_hr_attendance and kderp_e_approval already offer to their own buttons. Both apps work the
same without it.

Sources:
  - e-approval: every model built on kderp.e.approval.mixin, through tier.review
  - attendance: hr.attendance.request (working time, overtime) and hr.leave.cover. The attendance
    day (hr.attendance) is never approved itself; it is shown only in the "Today" card.

Rules:
  - "Waiting for you" uses the approve buttons' own rules:
      e-approval: the user is a reviewer of the current (lowest pending) step;
      attendance: hr.mixin._compute_buttons_visible, mirrored as search domains in
                  _attendance_inbox_domains() and re-checked with next_button_visible.
  - Attendance lists cover the attendance-month window (_attendance_window()).
  - Read with the user's own access rights; sudo() only for names of linked records.
"""
import calendar
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

ATT_LIMIT = 300           # attendance rows loaded per model; "Show all" opens the full list
MINE_LIMIT = 20           # own requests shown per source
MINE_RECENT_DAYS = 30     # decided e-approvals stay in "My requests" this long
BULK_MAX = 50             # attendance approvals per click
ATT_WAITING = ('waiting_fman', 'waiting_fhr', 'waiting_fman2')
ATT_APPROVE_METHOD = {      # next_button_visible -> the attendance app's own method
    'approve': 'action_approve',
    'validate': 'action_validate',
    'approve2': 'action_approve_man2',
}
ATT_MODELS = ('hr.attendance.request', 'hr.leave.cover')
TARGET_DAY_PARAM = 'kdvn_dashboard.at_target_day'   # HR's "finish by" day, default 25


class KderpDashboard(models.AbstractModel):
    _name = 'kderp.dashboard'
    _description = 'KDERP Dashboard data'

    # ------------------------------------------------------------------ helpers
    @api.model
    def _fmt_date(self, value):
        if not value:
            return ''
        if hasattr(value, 'hour'):
            value = fields.Datetime.context_timestamp(self, value)
        return value.strftime('%d/%m/%Y')

    @api.model
    def _fmt_time(self, value):
        return fields.Datetime.context_timestamp(self, value).strftime('%H:%M') if value else '—'

    @api.model
    def _days_since(self, value):
        if not value:
            return 0
        today = fields.Date.context_today(self)
        if hasattr(value, 'hour'):
            value = fields.Datetime.context_timestamp(self, value).date()
        return max((today - value).days, 0)

    @api.model
    def _selection_label(self, record, field_name):
        value = record[field_name]
        selection = record._fields[field_name]._description_selection(self.env)
        return dict(selection).get(value, value or '')

    @api.model
    def _has_eapproval(self):
        """True when the e-approval module is installed here. The dashboard does not depend on it (a site can run the
        attendance part alone, e.g. HCMC): every e-approval read below is skipped when this is False."""
        return 'kderp.e.approval.mixin' in self.env and 'tier.review' in self.env

    @api.model
    def _e_approval_models(self):
        """Concrete models built on kderp.e.approval.mixin that the user may read."""
        if not self._has_eapproval():
            return []
        names = []
        for name, model in self.env.items():
            if (name != 'kderp.e.approval.mixin' and not model._abstract and not model._transient
                    and hasattr(model, '_universal_state_changer')
                    and model.has_access('read')):
                names.append(name)
        return sorted(names)

    @api.model
    def _action_id(self, xml_id):
        action = self.env.ref(xml_id, raise_if_not_found=False)
        return action.id if action else False

    # ------------------------------------------------------- attendance window
    @api.model
    def _attendance_window(self):
        """Attendance month = start day (company policy, 21) to the day before it next month.
        A month stays open until the last day of the calendar month it ends in; HR asks everyone
        to finish by the target day (25). From the start day to that month end, two attendance
        months are shown."""
        today = fields.Date.context_today(self)
        company = self.env.company
        policy = company.at_policy() if hasattr(company, 'at_policy') else {}
        start_day = int(policy.get('date_start') or 21)
        target_day = int(self.env['ir.config_parameter'].sudo().get_param(TARGET_DAY_PARAM, 25) or 25)

        def month_of(day):
            if day.day >= start_day:
                start = day.replace(day=start_day)
            else:
                start = (day - relativedelta(months=1)).replace(day=start_day)
            end = start + relativedelta(months=1) - timedelta(days=1)
            last = calendar.monthrange(end.year, end.month)[1]
            return {'start': start, 'end': end, 'closes': end.replace(day=last),
                    'target': end.replace(day=min(target_day, last))}

        current = month_of(today)
        previous = month_of(current['start'] - timedelta(days=1))
        show_previous = today <= previous['closes']
        months = []
        if show_previous:
            months.append({
                'label': '%s – %s' % (self._fmt_date(previous['start']), self._fmt_date(previous['end'])),
                'closing': True,
                'target': self._fmt_date(previous['target']),
                'closes': self._fmt_date(previous['closes']),
                'late': today > previous['target'],
            })
        months.append({
            'label': '%s – %s' % (self._fmt_date(current['start']), self._fmt_date(current['end'])),
            'closing': False, 'target': '', 'closes': '', 'late': False,
        })
        return {'start': previous['start'] if show_previous else current['start'],
                'end': current['end'], 'months': months}

    # --------------------------------------------------------------- today card
    @api.model
    def _needs_check_in_out(self, employee):
        """False for staff who do not check in/out: employees with 'working' off (e.g. Japanese
        staff), and employees on a valid attendance rule flagged no_checkin / no_need_check."""
        if not employee.sudo().working:
            return False
        today = fields.Date.context_today(self)
        rules = self.env['hr.attendance.rule'].sudo().search([
            ('active', '=', True), ('state', '=', 'done'),
            '|', ('no_checkin', '=', True), ('no_need_check', '=', True),
            ('valid_start', '<=', today), '|', ('valid_stop', '=', False), ('valid_stop', '>=', today),
            ('employee_ids', 'in', employee.ids)])
        return not rules

    @api.model
    def _today_card(self):
        employee = self.env.user.employee_ids[:1]
        if not employee or not self._needs_check_in_out(employee):
            return False
        today = fields.Date.context_today(self)
        Att = self.env['hr.attendance']
        card = {
            'has_record': False,
            'links': {
                'ot': self._action_id('kdvn_hr_attendance.hr_attendance_wizard_multi_mode_ot'),
                'wt': self._action_id('kdvn_hr_attendance.hr_attendance_wizard_multi_mode_wt'),
                'leave': self._action_id('kdvn_hr_attendance.action_hr_leave_cover_request'),
            },
        }
        if not Att.has_access('read'):
            return card
        at = Att.search([('employee_id', '=', employee.id), ('at_date', '=', today)], limit=1)
        if at:
            card.update({
                'has_record': True,
                'id': at.id,
                'date': self._fmt_date(at.at_date),
                'at_date': fields.Date.to_string(at.at_date),
                'check_in': self._fmt_time(at.check_in),
                'check_out': self._fmt_time(at.check_out),
                'marks': at.status_codes or '',
                'absence': self._selection_label(at, 'absence') if at.absence else '',
                'can_ot': bool(at.can_request_ot),
                'can_wt': bool(at.can_request_wt),
                'can_leave': bool(at.can_request_leave),
            })
        # Same check as the old HR dashboard: only one of in/out, or absent although both exist
        yesterday = Att.search([('employee_id', '=', employee.id),
                                ('at_date', '=', today - timedelta(days=1))], limit=1)
        if yesterday:
            only_one = (bool(yesterday.compute_in) + bool(yesterday.compute_out)) == 1
            absent_with_both = (yesterday.absence == 'absence' and bool(yesterday.compute_in)
                                and bool(yesterday.compute_out))
            if only_one or absent_with_both:
                card['yesterday'] = {
                    'id': yesterday.id,
                    'date': self._fmt_date(yesterday.at_date),
                    'at_date': fields.Date.to_string(yesterday.at_date),
                    'check_in': self._fmt_time(yesterday.check_in),
                    'check_out': self._fmt_time(yesterday.check_out),
                    'can_wt': bool(yesterday.can_request_wt),
                    'can_leave': bool(yesterday.can_request_leave),
                }
        return card

    # --------------------------------------------------------------- e-approval
    @api.model
    def _procedure_title(self, record):
        """The procedure's current title (class attribute). The stored field approval_procedure_title is
        copied at create time, so records made under an older default (e.g. 'Generic Approval Request')
        would keep a stale label."""
        return (getattr(record, '_approval_procedure_title', None) or record.approval_procedure_title
                or record._description)

    @api.model
    def _e_approval_current_step(self, record):
        pending = record.sudo().review_ids.filtered(lambda r: r.status == 'pending' and not r.done_by)
        if not pending:
            return self.env['tier.review']
        lowest = min(pending.mapped('sequence'))
        return pending.filtered(lambda r: r.sequence == lowest)

    @api.model
    def _e_approval_inbox(self):
        if not self._has_eapproval():
            return []
        Review = self.env['tier.review'].sudo()
        reviews = Review.search([('status', '=', 'pending'), ('done_by', '=', False),
                                 ('reviewer_ids', 'in', self.env.uid)])
        front = self.env['kderp.e.approval.mixin']._notify_front_reviews(reviews)
        front = front.filtered(lambda r: self.env.user in r.reviewer_ids)
        rows, seen = [], set()
        for review in front:
            key = (review.model, review.res_id)
            if key in seen or review.model not in self.env:
                continue
            seen.add(key)
            record = self.env[review.model].sudo().browse(review.res_id)
            if not record.exists() or record.state != 'submitted':
                continue
            earlier = record.review_ids.filtered(lambda r: r.sequence < review.sequence and r.reviewed_date)
            since = max(earlier.mapped('reviewed_date')) if earlier else review.create_date
            rows.append({
                'tab': 'eapproval',
                'kind': 'e_approval',
                'type_label': self._procedure_title(record),
                'model': review.model,
                'res_id': review.res_id,
                'ref': record.name or '',
                'subject': record.reason or '',
                'applicant': record.employee_id.name or record.create_uid.name or '',
                'employee_id': record.employee_id.id,
                'section': record.employee_id.department_id.name or '',
                'step': review.definition_id.frontend_name or review.name or '',
                'special': getattr(record, 'special_case', 'normal') == 'special',
                'can_approve': True,
                'can_refuse': True,
                'date': self._fmt_date(since),
                'days': self._days_since(since),
                'sort_key': fields.Datetime.to_string(since) if since else '',
            })
        return rows

    @api.model
    def _e_approval_mine(self):
        if not self._has_eapproval():
            return []
        uid = self.env.uid
        recent = fields.Datetime.now() - timedelta(days=MINE_RECENT_DAYS)
        rows = []
        for name in self._e_approval_models():
            domain = ['|', ('create_uid', '=', uid), ('employee_id.user_id', '=', uid),
                      '|', ('state', 'in', ('draft', 'submitted')), ('write_date', '>=', recent)]
            for record in self.env[name].search(domain, order='write_date desc', limit=MINE_LIMIT):
                # a model may show its own date (e.g. imported history shows the date of the paper record)
                when = record._dashboard_date() if hasattr(record, '_dashboard_date') else record.write_date
                step = self._e_approval_current_step(record) if record.state == 'submitted' else False
                rows.append({
                    'kind': 'e_approval',
                    'type_label': self._procedure_title(record),
                    'model': name,
                    'res_id': record.id,
                    'ref': record.name or '',
                    'subject': record.reason or '',
                    'state': record.state,
                    'state_label': self._selection_label(record, 'state'),
                    'step': ', '.join(s.definition_id.frontend_name or s.name or '' for s in step) if step else '',
                    'progress': record.approval_progress or '',
                    'special': getattr(record, 'special_case', 'normal') == 'special',
                    'date': self._fmt_date(when),
                    'sort_key': fields.Datetime.to_string(when),
                })
        return rows

    # --------------------------------------------------------------- attendance
    @api.model
    def _attendance_inbox_domains(self, model_name):
        """Records the user can approve now. Mirrors hr.mixin._compute_buttons_visible:
          waiting_fman : section manager; the employee's admin manager or the record's approving
                         manager is the user; not the user's own record
          waiting_fhr  : HR staff / HR manager (or the superuser)
          waiting_fman2: GM whose user is in the employee's admin_manager_user_ids
        """
        uid = self.env.uid
        groups = self.env['hr.mixin'].groups()
        domains = []
        # Odoo 19: employee_id.<our custom field> is searched on hr.employee.public for users without HR rights, which
        # lacks our fields. Find the employees first (superuser, ids only), then filter on employee_id in ids.
        Employee = self.env['hr.employee'].sudo()
        if groups['section_manager']:
            managed = Employee._search([('admin_manager_id.user_id', '=', uid)])
            domains.append([('state', '=', 'waiting_fman'), ('employee_id.user_id', '!=', uid),
                            '|', ('employee_id', 'in', managed),
                            ('approve_manager_id.user_id', '=', uid)])
        if groups['hr_staff'] or groups['hr_manager'] or uid == 1:
            domains.append([('state', '=', 'waiting_fhr')])
        if groups['gm']:
            gm_staff = Employee._search([('admin_manager_user_ids', 'in', [uid])])
            domains.append([('state', '=', 'waiting_fman2'), ('employee_id', 'in', gm_staff)])
        if not domains:
            return False
        return Domain.OR(domains)   # each role's domain has several terms: join them as a whole

    @api.model
    def _window_domain(self, model_name, window, older=False):
        start, end = window['start'], window['end']
        if model_name == 'hr.attendance.request':
            if older:
                return [('at_id.at_date', '<', start)]
            return [('at_id.at_date', '>=', start), ('at_id.at_date', '<=', end)]
        if older:
            return [('dt_to', '<', start)]
        return [('dt_to', '>=', start), ('dt_from', '<=', end)]

    @api.model
    def _filter_window(self, records, window, older=False):
        """Window test for hr.attendance.request done in Python. The same test as _window_domain, but
        searching on at_id.at_date costs 1-2.5 s per search for a manager (record rules on the big
        hr.attendance table), while reading the date of the few records already found takes ~10 ms."""
        start, end = window['start'], window['end']

        def keep(record):
            day = record.sudo().at_id.at_date
            if not day:
                return False
            return day < start if older else start <= day <= end
        return records.filtered(keep)

    @api.model
    def _attendance_row(self, record):
        """One row for an attendance request (working time / overtime) or a leave cover."""
        if record._name == 'hr.attendance.request':
            day = record.sudo().at_id.at_date
            is_ot = record.request_type == 'over_time'
            tab, kind = ('ot' if is_ot else 'wt'), 'attendance'
            type_label = self._selection_label(record, 'request_type') or _('Request')
            ref = '%s %s' % (type_label, self._fmt_date(day))
            subject = ' '.join(filter(None, [record.sub_request_type_id.name or '', record.name or '',
                                             record.estimate_ot_dsp or '']))
        else:
            day = record.dt_from
            tab, kind, type_label = 'leave', 'leave', _('Leave')
            period = self._fmt_date(record.dt_from)
            if record.dt_to and record.dt_to != record.dt_from:
                period = '%s - %s' % (period, self._fmt_date(record.dt_to))
            ref = '%s %s' % (type_label, period)
            subject = ' '.join(filter(None, [record.reason_id.name or '', record.name or '']))
        state_label = self._selection_label(record, 'state')
        employee = record.sudo().employee_id
        return {
            'tab': tab,
            'kind': kind,
            'type_label': type_label,
            'model': record._name,
            'res_id': record.id,
            'ref': ref,
            'subject': subject.strip(),
            'applicant': employee.name or '',
            'employee_id': employee.id,
            'section': record.sudo().department_id.name or '',
            'step': state_label,
            'state': record.state,
            'state_label': state_label,
            'can_approve': record.next_button_visible in ATT_APPROVE_METHOD,
            'can_refuse': bool(record.refuse_button_visible),
            'date': self._fmt_date(day),
            'days': self._days_since(day),
            'sort_key': fields.Date.to_string(day) if day else '',
        }

    @api.model
    def _attendance_inbox(self, window):
        rows, lists = [], []
        for model_name in ATT_MODELS:
            Model = self.env[model_name]
            if not Model.has_access('read'):
                continue
            domain = self._attendance_inbox_domains(model_name)
            if not domain:
                continue
            in_window = domain + self._window_domain(model_name, window)
            older_domain = domain + self._window_domain(model_name, window, older=True)
            if model_name == 'hr.attendance.request':
                found = Model.search(domain, order='id asc')
                in_records = self._filter_window(found, window)
                count = len(in_records)
                older = len(self._filter_window(found, window, older=True))
                records = in_records[:ATT_LIMIT]
            else:
                count = Model.search_count(in_window)
                older = Model.search_count(older_domain)
                records = Model.search(in_window, order='id asc', limit=ATT_LIMIT) if count else Model
            if count:
                ok = records.filtered(lambda r: r.next_button_visible in ATT_APPROVE_METHOD)
                if len(ok) != len(records):
                    _logger.warning("Dashboard: %s %s match the inbox domain but have no approve button",
                                    model_name, (records - ok).ids)
                rows += [self._attendance_row(r) for r in ok]
            if count or older:
                lists.append({
                    'model': model_name,
                    'name': _('Attendance requests to approve') if model_name == 'hr.attendance.request'
                    else _('Leave to approve'),
                    'count': count, 'domain': in_window,
                    'older': older, 'older_domain': older_domain,
                    'truncated': count > ATT_LIMIT,
                })
        return rows, lists

    @api.model
    def _attendance_mine(self, window):
        uid = self.env.uid
        rows = []
        for model_name, order in (('hr.attendance.request', 'id desc'), ('hr.leave.cover', 'dt_from desc')):
            Model = self.env[model_name]
            if not Model.has_access('read'):
                continue
            domain = [('employee_id.user_id', '=', uid), ('state', 'in', ('draft', 'refuse') + ATT_WAITING)]
            if model_name == 'hr.attendance.request':
                records = self._filter_window(Model.search(domain, order=order), window)[:MINE_LIMIT]
            else:
                records = Model.search(domain + self._window_domain(model_name, window), order=order, limit=MINE_LIMIT)
            rows += [self._attendance_row(r) for r in records]
        return rows

    # -------------------------------------------------------------------- entry
    @api.model
    def get_dashboard_data(self):
        user = self.env.user
        window = self._attendance_window()
        e_inbox = self._e_approval_inbox()
        att_inbox, att_lists = self._attendance_inbox(window)
        inbox = sorted(e_inbox + att_inbox, key=lambda r: r['sort_key'])    # oldest first
        mine = self._e_approval_mine() + self._attendance_mine(window)
        mine.sort(key=lambda r: r['sort_key'], reverse=True)
        counts = {tab: len([r for r in inbox if r['tab'] == tab]) for tab in ('wt', 'ot', 'leave', 'eapproval')}
        return {
            'user_name': user.name,
            'employee_name': user.employee_ids[:1].name or user.name,
            'today': self._fmt_date(fields.Date.context_today(self)),
            'today_card': self._today_card(),
            'window': {'months': window['months']},
            'inbox': inbox,
            'counts': counts,
            'inbox_count': len(e_inbox) + sum(l['count'] for l in att_lists),
            'inbox_lists': att_lists,
            'mine': mine,
            'mine_open': len([r for r in mine if r.get('state') not in ('approved', 'rejected', 'done', 'refuse')]),
            'bulk_max': BULK_MAX,
            'has_eapproval': self._has_eapproval(),     # False: no E-approval tab
        }

    # ------------------------------------------------------------ quick actions
    @api.model
    def approve_attendance(self, items):
        """Approve attendance requests / leave covers with the attendance app's own methods.
        items: [{'model': ..., 'id': ...}], at most BULK_MAX. Each record is checked with
        next_button_visible first (the request-level methods don't check who calls them) and
        approved in its own savepoint, so one failure doesn't undo the others."""
        items = items or []
        if len(items) > BULK_MAX:
            raise UserError(_('Please approve at most %s requests at a time.') % BULK_MAX)
        done, skipped = 0, []
        for item in items:
            model_name = item.get('model')
            if model_name not in ATT_MODELS:
                continue
            record = self.env[model_name].browse(int(item.get('id') or 0)).exists()
            if not record:
                skipped.append({'ref': '#%s' % item.get('id'), 'reason': _('Not found')})
                continue
            row = self._attendance_row(record)
            label = '%s · %s' % (row['ref'], row['applicant'])
            method = ATT_APPROVE_METHOD.get(record.next_button_visible)
            if not method:
                skipped.append({'ref': label, 'reason': _('Not waiting for your approval')})
                continue
            try:
                with self.env.cr.savepoint():
                    getattr(record, method)()
                done += 1
            except Exception as e:
                skipped.append({'ref': label, 'reason': getattr(e, 'name', None) or str(e)})
        return {'done': done, 'skipped': skipped}
