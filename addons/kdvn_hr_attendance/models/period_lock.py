# -*- coding: utf-8 -*-
"""Attendance period lock: after `res.company.lock_months` months (default 3, payroll has paid) the attendance days of a period are
locked. A locked day keeps its payroll values (status, OT, absence): nobody and nothing may change them, the requests, leave covers and
leaves on that day cannot be created, changed or cancelled, and automatic recomputes skip it. An HR Admin unlocks with a
`hr.attendance.period.unlock` record (employee or everybody, date range, reason, expires by itself).

How it is wired (see tests/test_period_lock.py):
- helpers on `hr.mixin` (`_period_lock_cutoff`, `_period_locked_dates`, `_check_period_lock`) used by hr.attendance, request, cover and leave;
- hr.attendance: `write` / `create` / `unlink` raise UserError on a locked day, `_write_multi` (the flush of stored computed fields) silently
  keeps the stored values of locked days, `skip_locked` decorates the recompute entry points;
- bypass: context key `kdvn_period_lock_off` (the legacy importer sets it). sudo() does NOT bypass.
"""
import functools
import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

LOCK_OFF = 'kdvn_period_lock_off'
UNLOCK_GROUP = 'hr_attendance.group_hr_attendance_user'      # "HR Admin" in Odoo 12 (renamed there): attendance officers; attendance managers imply it


def skip_locked(method):
    """Decorator for attendance recompute entry points: locked days are left as they are (stored values kept)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self or self.env.context.get(LOCK_OFF):
            return method(self, *args, **kwargs)
        locked = self._period_locked_ids()
        if locked:
            _logger.info('period lock: %s skips %d locked day(s)', method.__name__, len(locked))
            self = self - self.browse(list(locked))
            if not self:
                return None
        return method(self, *args, **kwargs)
    return wrapper


class HrMixinPeriodLock(models.AbstractModel):
    _inherit = 'hr.mixin'

    # ---- cutoff and unlock windows -----------------------------------------------------------------------------
    def _period_lock_cutoff(self):
        """First day of the oldest OPEN attendance period: days before it are locked. None = no lock."""
        if self.env.context.get(LOCK_OFF):
            return None
        months = self.env.user.company_id.lock_months
        if not months or months <= 0:
            return None
        today = fields.Date.context_today(self)
        return self.get_start_dt(today - relativedelta(months=months), for_month=True)

    def _period_unlock_windows(self):
        """[(employee id or False, date_from, date_to)] of the unlocks that are still running."""
        recs = self.env['hr.attendance.period.unlock'].sudo().search([('expires_at', '>', fields.Datetime.now())])
        return [(r.employee_id.id or False, r.date_from, r.date_to) for r in recs]

    @api.model
    def _period_is_unlocked(self, windows, employee_id, a_date):
        return any((emp is False or emp == employee_id) and d_from <= a_date <= d_to for emp, d_from, d_to in windows)

    # ---- questions ----------------------------------------------------------------------------------------------
    def _period_locked_dates(self, employee_id, date_from, date_to=None):
        """Sorted list of the locked dates of [date_from, date_to] for the employee (id or record)."""
        cutoff = self._period_lock_cutoff()
        if not cutoff or not date_from:
            return []
        employee_id = getattr(employee_id, 'id', employee_id) or False
        date_to = date_to or date_from
        if date_from >= cutoff:
            return []
        last = min(date_to, cutoff - relativedelta(days=1))
        days = [date_from + relativedelta(days=i) for i in range((last - date_from).days + 1)]
        windows = self._period_unlock_windows()
        return [d for d in days if not self._period_is_unlocked(windows, employee_id, d)]

    def _period_is_locked(self, employee_id, a_date):
        return bool(self._period_locked_dates(employee_id, a_date, a_date))

    def _check_period_lock(self, employee_id, date_from, date_to=None, what=None):
        dates = self._period_locked_dates(employee_id, date_from, date_to)
        if dates:
            shown = ', '.join(d.strftime('%d/%m/%Y') for d in dates[:5]) + (' ...' if len(dates) > 5 else '')
            raise UserError(_(
                "The attendance period is locked for: %(dates)s%(what)s.\n"
                "Payroll has already used it (older than %(months)s months). Ask an HR Admin to unlock it first "
                "(Attendances > Configuration > Period unlocks).",
                dates=shown, what=' (%s)' % what if what else '', months=self.env.user.company_id.lock_months))
        return True

    @staticmethod
    def _period_vn_date(value):
        """Date (Vietnam time) of a stored UTC datetime or of a date / ISO string; False when empty."""
        if not value:
            return False
        if isinstance(value, str):
            value = fields.Datetime.to_datetime(value) if len(value) > 10 else fields.Date.to_date(value)
        if hasattr(value, 'hour'):
            from datetime import timedelta
            return (value + timedelta(hours=7)).date()
        return value


class HrAttendancePeriodUnlock(models.Model):
    _name = 'hr.attendance.period.unlock'
    _description = 'Attendance period unlock'
    _inherit = ['mail.thread']
    _order = 'id desc'

    employee_id = fields.Many2one('hr.employee', string='Employee', help="Empty = every employee", tracking=True)
    date_from = fields.Date(required=True, tracking=True)
    date_to = fields.Date(required=True, tracking=True)
    reason = fields.Text(required=True)
    user_id = fields.Many2one('res.users', string='Unlocked by', default=lambda self: self.env.user, readonly=True)
    expires_at = fields.Datetime(required=True, tracking=True, default=lambda self: fields.Datetime.now() + relativedelta(days=1),
                                 help="The days lock again by themselves at this time (default one day).")
    state = fields.Selection([('active', 'Unlocked'), ('expired', 'Locked again')], compute='_compute_state')

    @api.depends('expires_at')
    def _compute_state(self):
        now = fields.Datetime.now()
        for r in self:
            r.state = 'active' if r.expires_at and r.expires_at > now else 'expired'

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for r in self:
            if r.date_to < r.date_from:
                raise UserError(_('The end date is before the start date.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group(UNLOCK_GROUP):
            raise AccessError(_('Only an HR Admin can unlock an attendance period.'))
        for vals in vals_list:
            vals['user_id'] = self.env.user.id   # not forgeable
        records = super().create(vals_list)
        for rec in records:
            rec._log_on_days()
        return records

    def write(self, values):
        if not self.env.user.has_group(UNLOCK_GROUP):
            raise AccessError(_('Only an HR Admin can change an attendance period unlock.'))
        if set(values) - {'expires_at'}:
            raise UserError(_('An unlock cannot be edited: revoke it (Lock again) and create a new one.'))
        return super().write(values)

    def unlink(self):
        raise UserError(_('Unlocks are kept as a record. Use "Lock again" to end one.'))

    def action_lock_again(self):
        self.write({'expires_at': fields.Datetime.now()})
        return True

    def _log_on_days(self):
        """A note on every attendance day that was unlocked (who, why, until when)."""
        self.ensure_one()
        domain = [('at_date', '>=', self.date_from), ('at_date', '<=', self.date_to)]
        if self.employee_id:
            domain.append(('employee_id', '=', self.employee_id.id))
        ats = self.env['hr.attendance'].sudo().with_context(active_test=False, **{LOCK_OFF: True}).search(domain)
        body = _('Period unlocked by %(user)s until %(until)s. Reason: %(reason)s',
                 user=self.env.user.name, until=fields.Datetime.to_string(self.expires_at), reason=self.reason)
        if ats:
            ats._message_log_batch(bodies={at.id: body for at in ats})
        self.message_post(body=_('%(n)d attendance day(s) unlocked.', n=len(ats)))
