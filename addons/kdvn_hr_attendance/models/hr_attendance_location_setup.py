# -*- coding: utf-8 -*-
"""Face-id machines are created automatically from the remote data, but HR must say where each one is:
a location name (show_name, the same for all machines of a site) and the area (main office) it stands in.
Without them the Location History of the staff is wrong, so the staff location wizards stop until it is done,
and HR Admin is reminded (e-mail + warning on the HR dashboard and in the top bar)."""
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

REMIND_EVERY_DAYS = 7
IN_USE_MONTHS = 3


class KderpHrAttendanceLocationSetup(models.Model):
    _inherit = 'hr.attendance.location'

    area_id = fields.Many2one('hr.department', 'Area (main office)', domain=[('type_id.code', '=', 'area')],
                              help='Only for a machine standing in a main office (HO, Hai Phong...). Leave empty for a machine at a customer site. '
                                   'A staff whose main office is not this area gets "<main office> <location name>" in the Location History.')
    ignore_location = fields.Boolean('Ignore for staff locations', help='Tick for a test machine or one that must not decide where a staff works: '
                                      'its records are not used for the Location History, and it is never asked to be completed.')
    setup_missing = fields.Boolean('To complete', compute='_compute_setup_missing', store=True,
                                   help='Location name is still empty (machines to ignore are never asked).')
    setup_reminded = fields.Date('Last reminder', readonly=True)

    @api.depends('show_name', 'area_id', 'active', 'ignore_location')
    def _compute_setup_missing(self):
        for l in self:
            l.setup_missing = bool(l.active and not l.ignore_location and not (l.show_name or '').strip())

    def action_use_shown_name(self):
        """Fill an empty Location name with the name shown now (machine name without 'Face'): no typing, no typo."""
        for l in self:
            if not (l.show_name or '').strip():
                l.show_name = l.name_get()[0][1]
        return True

    # ---- which machines count ---------------------------------------------
    @api.model
    def _machines_in_use(self, months=IN_USE_MONTHS, include_inactive=False):
        """{machine id: number of attendance records} of the active machines used in the last `months` attendance months
        (None = ever). include_inactive: archived machines too (the rebuild of all months still uses their records)."""
        mixin = self.env['hr.mixin']
        year, month = mixin.get_at_year_month(fields.Date.context_today(self))
        sql = """
            SELECT l.id, count(a.id) FROM hr_attendance_location l
            JOIN hr_attendance a ON (a.check_in_location_id = l.id OR a.check_out_location_id = l.id)
                                %s
            %s GROUP BY l.id"""
        where = '' if include_inactive else 'WHERE l.active'
        if months:
            self.env.cr.execute(sql % ('AND a.at_year * 12 + a.at_month >= %s', where), (year * 12 + month - (months - 1),))
        else:
            self.env.cr.execute(sql % ('', where))
        return dict(self.env.cr.fetchall())

    @api.model
    def _incomplete_in_use(self, months=IN_USE_MONTHS):
        ids = list(self._machines_in_use(months))
        # judged on the live values, not on the stored flag: a stale flag must never block HR
        return self.sudo().browse(ids).filtered(lambda m: m.active and not m.ignore_location and not (m.show_name or '').strip())

    @api.model
    def check_setup_complete(self, months=IN_USE_MONTHS):
        """Raise when a machine in use still has no location name or area (used by the staff location wizards)."""
        missing = self._incomplete_in_use(months)
        if missing:
            lines = ['- %s' % m.name for m in missing[:30]]
            raise UserError(_('%s machine(s) still need a Location name (the red rows). '
                              'Fill them here, or tick Ignore for a test machine, then press Next again. When many are missing it is easier in '
                              'Attendance > Configuration > HR Attendance Location.\n%s%s') % (
                len(missing), '\n'.join(lines), _('\n... and %s more') % (len(missing) - 30) if len(missing) > 30 else ''))

    # ---- name of a staff's location ---------------------------------------
    def staff_location_name(self, employee):
        """Location History name for `employee` when he/she used this machine: the machine's location name, with the
        staff's main office in front unless the machine stands in that same area (a Head Office staff at the Head Office
        machine = 'Head Office'; at the Kyocera machine = 'Head Office Kyocera')."""
        self.ensure_one()
        name = self.name_get()[0][1] or ''
        area = employee.admin_dept_id.area_id
        # machine without area = a customer site: always '<main office> <site>'. Not when the name already has the office
        # (avoids 'HO HO')
        if area and area != self.area_id and area.name.lower() not in name.lower():
            name = '%s %s' % (area.name, name)
        return name.strip()[:32]

    # ---- warnings -----------------------------------------------------------
    @api.model
    def get_setup_warning(self):
        """Number of machines in use to complete; 0 for anybody but HR Admin (dashboard + top bar)."""
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_user'):
            return 0
        return len(self._incomplete_in_use())

    @api.model
    def _cron_remind_setup(self):
        """Daily: e-mail HR Admin the machines to complete, each machine again only after REMIND_EVERY_DAYS days."""
        today = fields.Date.context_today(self)
        limit = today - relativedelta(days=REMIND_EVERY_DAYS)
        due = self._incomplete_in_use().filtered(lambda m: not m.setup_reminded or m.setup_reminded <= limit)
        if not due:
            return 0
        users = self.env.ref('hr_attendance.group_hr_attendance_user').sudo().users.filtered(lambda u: u.active and u.email)
        if not users:
            _logger.warning('Machines to complete (%s) but no HR Admin user has an e-mail', len(due))
            return 0
        rows = ''.join('<li>%s%s</li>' % (html_escape(m.name), html_escape(' (%s)' % m.terminal_id) if m.terminal_id else '') for m in due)
        body = ('<p>New or incomplete face-id machines need a <b>location name</b> (and an <b>area</b> when the machine stands in a main office). Without it the staff '
                'locations (Location History, and the report sent to the remote server) are wrong.</p><ul>%s</ul>'
                '<p>Open Attendance &gt; Configuration &gt; HR Attendance Location, or the warning on the HR dashboard.</p>') % rows
        self.env['mail.mail'].sudo().create({
            'subject': _('Face-id machines to complete (%s)') % len(due),
            'body_html': body,
            'email_to': ','.join(users.mapped('email')),
            'auto_delete': True,
        }).send()
        due.sudo().write({'setup_reminded': today})
        _logger.info('Reminded HR Admin about %s machine(s) to complete', len(due))
        return len(due)
