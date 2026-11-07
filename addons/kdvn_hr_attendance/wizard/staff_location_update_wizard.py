# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools import html_escape

STATES = [('machines', '1. Machines'), ('preview', '2. Preview'), ('confirm', '3. Confirm'), ('done', '4. Result')]


def machine_line_values(env, months, include_inactive=False):
    """Lines for step 1 of the staff location wizards: machines used in the last `months` attendance months
    (None = ever), machines still to complete first. Plain values for every column: the browser does not compute
    related/computed fields of unsaved lines."""
    usage = env['hr.attendance.location']._machines_in_use(months, include_inactive)
    machines = env['hr.attendance.location'].sudo().with_context(active_test=False).browse(list(usage))
    env.cr.execute('''SELECT l.id, max(a.at_date) FROM hr_attendance_location l
                      JOIN hr_attendance a ON a.check_in_location_id = l.id OR a.check_out_location_id = l.id
                      WHERE l.id IN %s GROUP BY l.id''', (tuple(usage) or (0,),))
    last_use = dict(env.cr.fetchall())
    rows = sorted(machines, key=lambda m: (m.ignore_location, not m.setup_missing, m.display_name.lower(), m.name))
    return [(0, 0, {'machine_id': m.id, 'machine_name': m.name, 'terminal_id': m.terminal_id or '',
                    'display_name_now': m.display_name, 'show_name': m.show_name or '',
                    'original_show_name': m.show_name or '', 'area_id': m.area_id.id,
                    'original_area_id': m.area_id.id, 'usage': usage[m.id],
                    'last_use': last_use.get(m.id), 'is_local': m.is_local, 'is_active': m.active,
                    'ignore_location': m.ignore_location, 'original_ignore': m.ignore_location}) for m in rows]


def save_machine_lines(lines):
    """Write the changed location name / area back to the machines."""
    for line in lines:
        vals = {}
        new_show = (line.show_name or '').strip()
        if new_show != (line.original_show_name or ''):
            vals['show_name'] = new_show
        if line.ignore_location != line.original_ignore:
            vals['ignore_location'] = line.ignore_location
        if line.area_id.id != line.original_area_id:
            vals['area_id'] = line.area_id.id
        if vals:
            line.machine_id.sudo().write(vals)


class StaffLocationUpdateWizard(models.TransientModel):
    """HR Admin: rebuild the staff Location History from the face-id machines in four steps.
    1) location name and area of every machine, 2) preview of what would be created, 3) confirm, 4) result."""
    _name = 'kderp.staff.location.update.wizard'
    _description = 'Update staff locations from the face-id machines'

    state = fields.Selection(STATES, default='machines', required=True)
    machine_line_ids = fields.One2many('kderp.staff.location.update.machine', 'wizard_id',
                                       default=lambda self: machine_line_values(self.env, None, include_inactive=True))
    preview_html = fields.Html(readonly=True, sanitize=False)
    result_html = fields.Html(readonly=True, sanitize=False)

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'name': _('Update staff locations'),
                'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}

    @api.model
    def action_open(self):
        # Create the wizard (and its machine lines) now: buttons on the lines of an unsaved wizard have no record to act on
        return self.create({})._reopen()

    @staticmethod
    def _p(rows):
        return ''.join('<p>%s</p>' % html_escape(r) for r in rows)

    @staticmethod
    def _stats_html(stats, title):
        rows = ['<h4>%s</h4>' % html_escape(title),
                '<p>%s</p>' % html_escape(_('%s new location line(s) over %s finished attendance month(s).') % (stats['lines'], stats['months']))]
        if stats['codes']:
            rows.append('<p>%s</p><ul>%s</ul>' % (html_escape(_('New location names:')),
                        ''.join('<li>%s</li>' % html_escape(n) for n in sorted(stats['codes']))))
        if stats['by_location']:
            top = sorted(stats['by_location'].items(), key=lambda kv: (-kv[1], kv[0]))
            rows.append('<table class="table table-sm"><thead><tr><th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table>' % (
                html_escape(_('Location')), html_escape(_('New lines')),
                ''.join('<tr><td>%s</td><td>%s</td></tr>' % (html_escape(k), v) for k, v in top)))
        return ''.join(rows)

    @staticmethod
    def _area_warning_html(stats):
        """Machines without Area whose new lines get a main-office prefix although (almost) all their staff come from one
        area: probably an office machine whose Area was forgotten (Head Office staff would become 'HO Head Office')."""
        flagged = []
        for info in stats.get('by_machine', {}).values():
            if info['has_area'] or info['prefixed'] < 3:
                continue
            area, n = info['areas'].most_common(1)[0]
            if area and n >= 0.8 * info['lines']:
                flagged.append((info['prefixed'], info, area))
        if not flagged:
            return ''
        rows = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            html_escape(i['name']), html_escape(area), n, html_escape(i['example']))
            for n, i, area in sorted(flagged, key=lambda f: -f[0])[:15])
        return ('<div class="alert alert-warning"><b>%s</b> %s'
                '<table class="table table-sm"><thead><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table></div>') % (
            html_escape(_('Check these machines:')),
            html_escape(_('they have no Area, but almost all their staff come from one area, so the new lines get a main office in front. '
                          'If the machine stands in that main office, press Back, set its Area, and Next again.')),
            html_escape(_('Machine')), html_escape(_('Staff mostly from')), html_escape(_('Lines with prefix')), html_escape(_('Example')), rows)

    def action_fill_names(self):
        """Every empty Location name gets the name shown now."""
        self.ensure_one()
        self.machine_line_ids.action_use_shown_name()
        return self._reopen()

    def action_next_machines(self):
        """Save the machines, stop while one is still incomplete, then show what would happen (nothing is written)."""
        self.ensure_one()
        save_machine_lines(self.machine_line_ids)
        self.env['hr.attendance.location'].check_setup_complete(months=None)
        stats = self.env['kderp.hr.employee.location'].action_backfill_from_attendance(preview=True)
        self.preview_html = self._area_warning_html(stats) + self._stats_html(stats, _('Preview: nothing has been written yet')) + self._p([
            _('A staff whose main office is not the area of the machine gets "<main office> <location name>". '
              'A month in which the staff already has a line is not touched, and a staff who stays at the same location gets one line only.')])
        self.state = 'preview'
        return self._reopen()

    def action_next_preview(self):
        self.ensure_one()
        self.state = 'confirm'
        return self._reopen()

    def action_run(self):
        self.ensure_one()
        stats = self.env['kderp.hr.employee.location'].action_backfill_from_attendance()
        self.result_html = self._stats_html(stats, _('Done: staff locations updated'))
        self.state = 'done'
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.state = {'preview': 'machines', 'confirm': 'preview'}.get(self.state, self.state)
        return self._reopen()


class StaffLocationUpdateMachine(models.TransientModel):
    _name = 'kderp.staff.location.update.machine'
    _description = 'Update staff locations: machine line'

    wizard_id = fields.Many2one('kderp.staff.location.update.wizard', ondelete='cascade')
    machine_id = fields.Many2one('hr.attendance.location', 'Machine', readonly=True)
    machine_name = fields.Char('Machine name', readonly=True)
    terminal_id = fields.Char(readonly=True)
    usage = fields.Integer('Records', readonly=True)
    last_use = fields.Date('Last used', readonly=True)
    is_active = fields.Boolean('Active', readonly=True, help='Not ticked: the machine is archived (no longer used) but its old records still count for the history.')
    is_local = fields.Boolean('Local server', readonly=True, help='Ticked: the machine is managed by our own face server. Not ticked: its data comes from a REMOTE server (staff checking in there get a work-out request).')
    display_name_now = fields.Char('Shown now', readonly=True)
    show_name = fields.Char('Location name', help='Machines of one site get the same name.')
    original_show_name = fields.Char()
    area_id = fields.Many2one('hr.department', 'Area (main office)', domain=[('type_id.code', '=', 'area')],
                              help='Only for a machine standing in a main office. Empty for a customer site. Staff of another area get "<their main office> <location name>".')
    original_area_id = fields.Integer()
    ignore_location = fields.Boolean('Ignore', help='Tick for a test machine: its records are not used for staff locations and it is not asked to be completed.')
    original_ignore = fields.Boolean()

    def action_use_shown_name(self):
        """Copy the name shown now into Location name (no typing, no typo)."""
        for line in self:
            if not (line.show_name or '').strip():
                line.show_name = line.display_name_now
        # reload the wizard like the top button does: a plain True leaves the open list showing the old value
        return self[:1].wizard_id._reopen()
