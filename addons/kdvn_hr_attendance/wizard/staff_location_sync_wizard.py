# -*- coding: utf-8 -*-
from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

from ..models.staff_location_sync import normalize_location_name
from .staff_location_update_wizard import machine_line_values, save_machine_lines

STATES = [('machines', '1. Machine names'), ('mapping', '2. Remote locations'), ('confirm', '3. Confirm'), ('done', 'Result')]


class StaffLocationSyncWizard(models.TransientModel):
    """HR Admin: send the staff's current location to the remote server in three steps.
    1) check the location name of every face-id machine, 2) choose the remote location for each of our locations,
    3) confirm and send (a dry run unless the 'send for real' setting is on)."""
    _name = 'kderp.staff.location.sync.wizard'
    _description = 'Send staff locations to the remote server'

    state = fields.Selection(STATES, default='machines', required=True)
    machine_line_ids = fields.One2many('kderp.staff.location.sync.machine', 'wizard_id', default=lambda self: self._default_machine_lines())
    map_line_ids = fields.One2many('kderp.staff.location.sync.map', 'wizard_id')
    confirm_html = fields.Html(readonly=True, sanitize=False)
    result_html = fields.Html(readonly=True, sanitize=False)
    live = fields.Boolean(compute='_compute_live')

    def _compute_live(self):
        live = self.env['kderp.remote.client'].is_live('staff_location')
        for w in self:
            w.live = live

    # ---- helpers -------------------------------------------------------
    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'name': _('Send staff locations to the remote server'),
                'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}

    @api.model
    def action_open(self):
        # Create the wizard (and its machine lines) now: buttons on the lines of an unsaved wizard have no record to act on
        return self.create({})._reopen()

    @staticmethod
    def _p(rows):
        return ''.join('<p>%s</p>' % html_escape(r) for r in rows)

    # ---- step 1: machines ---------------------------------------------
    @api.model
    def _default_machine_lines(self):
        """Active machines that recorded something in the last 3 attendance months."""
        return machine_line_values(self.env, 3)

    def action_fill_names(self):
        """Every empty Location name gets the name shown now."""
        self.ensure_one()
        self.machine_line_ids.action_use_shown_name()
        return self._reopen()

    def action_next_machines(self):
        """Save the changed machine names and areas; stop while a machine in use is incomplete. Only NEW months use the
        new names: existing Location History lines are never renamed or merged (history is history)."""
        self.ensure_one()
        save_machine_lines(self.machine_line_ids)
        self.env['hr.attendance.location'].check_setup_complete(months=3)
        self._fill_map_lines()
        self.state = 'mapping'
        return self._reopen()

    # ---- step 2: mapping ----------------------------------------------
    def _fill_map_lines(self):
        self.env['kderp.staff.location.remote'].refresh_from_remote()
        groups = self.env['hr.employee'].sudo().read_group(
            [('working', '=', True), ('current_location_id', '!=', False)], ['current_location_id'], ['current_location_id'])
        counts = {g['current_location_id'][0]: g['current_location_id_count'] for g in groups}
        codes = self.env['kderp.employee.location.code'].sudo().browse(list(counts))
        saved = {m.location_id.id: m.remote_id for m in self.env['kderp.staff.location.map'].sudo().search([])}
        remote = self.env['kderp.staff.location.remote'].search([])
        by_key = {}
        for r in remote:
            by_key.setdefault(normalize_location_name(r.name), r)
        # main office (area) of the staff at each location: HR names a remote location "<main office> <machine name>"
        area_count = {}
        for emp in self.env['hr.employee'].sudo().search([('working', '=', True), ('current_location_id', 'in', codes.ids)]):
            area_count.setdefault(emp.current_location_id.id, Counter())[emp.work_location or ''] += 1
        cmds = [(5, 0, 0)]
        for code in sorted(codes, key=lambda c: -counts[c.id]):
            chosen = saved.get(code.id)
            suggested = False
            if not chosen or not chosen.active:
                areas = [a for a, n in area_count.get(code.id, Counter()).most_common() if a]
                chosen = self._suggest_remote(code.name, areas, by_key)
                suggested = bool(chosen)
            cmds.append((0, 0, {'location_id': code.id, 'staff_count': counts[code.id],
                                'remote_id': chosen.id if chosen else False, 'suggested': suggested}))
        self.write({'map_line_ids': cmds})

    @staticmethod
    def _suggest_remote(code_name, areas, by_key):
        """Remote location for a local one. HR names remote locations '<main office> <machine>' (Hung Yen Kyocera C),
        so try, for the main offices of the staff here (most staff first): 1) exactly office+machine, 2) a name that starts
        with the office and ends with the machine (TLIP -> 'Tlip 1 Phuc Son', only if one fits); last 3) the machine name alone."""
        code_key = normalize_location_name(code_name)
        if code_key in by_key:     # the location name already carries the main office when it differs ('Hung Yen Kyocera')
            return by_key[code_key]
        for area in areas:
            area_key = normalize_location_name(area)
            if (area_key + code_key) in by_key:
                return by_key[area_key + code_key]
            fits = [k for k in by_key if k.startswith(area_key) and k.endswith(code_key) and len(k) >= len(area_key) + len(code_key)]
            if len(fits) == 1:
                return by_key[fits[0]]
        return by_key.get(code_key)

    def action_next_mapping(self):
        """Keep the choices for next month, then show what will be sent."""
        self.ensure_one()
        Map = self.env['kderp.staff.location.map'].sudo()
        for line in self.map_line_ids:
            rec = Map.search([('location_id', '=', line.location_id.id)])
            if line.remote_id:
                if rec:
                    rec.write({'remote_id': line.remote_id.id})
                else:
                    Map.create({'location_id': line.location_id.id, 'remote_id': line.remote_id.id})
            elif rec:
                rec.unlink()
        sent = sum(l.staff_count for l in self.map_line_ids if l.remote_id)
        total = sum(l.staff_count for l in self.map_line_ids)
        skipped = [l for l in self.map_line_ids if not l.remote_id]
        rows = [_('%s of %s staff have a remote location and will be sent.') % (sent, total)]
        if skipped:
            rows.append(_('Not sent (no remote location chosen): %s') % ', '.join(
                '%s (%s)' % (l.location_id.name, l.staff_count) for l in skipped))
        rows.append(_('Mode: send for real (the remote server will be updated).') if self.live else
                    _('Mode: DRY RUN. The remote server is not changed, you will only see what would change. '
                      '(Settings > Remote Server Connection > Staff locations is off.)'))
        self.confirm_html = self._p(rows)
        self.state = 'confirm'
        return self._reopen()

    # ---- step 3: send --------------------------------------------------
    def action_send(self):
        self.ensure_one()
        Location = self.env['kderp.hr.employee.location']
        staff, result = Location.action_push_to_remote()
        title, rows = Location._format_push_result(staff, result)
        self.result_html = '<h4>%s</h4>%s' % (html_escape(title), self._p(rows))
        self.state = 'done'
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.state = {'mapping': 'machines', 'confirm': 'mapping', 'done': 'confirm'}.get(self.state, self.state)
        return self._reopen()


class StaffLocationSyncMachine(models.TransientModel):
    _name = 'kderp.staff.location.sync.machine'
    _description = 'Staff location sync: machine line'

    wizard_id = fields.Many2one('kderp.staff.location.sync.wizard', ondelete='cascade')
    machine_id = fields.Many2one('hr.attendance.location', 'Machine', readonly=True)
    machine_name = fields.Char('Machine name', readonly=True)
    terminal_id = fields.Char(readonly=True)
    show_name = fields.Char('Location name', help='Machines of one site get the same name.')
    original_show_name = fields.Char()
    area_id = fields.Many2one('hr.department', 'Area (main office)', domain=[('type_id.code', '=', 'area')],
                              help='Only for a machine standing in a main office. Empty for a customer site. Staff of another area get "<their main office> <location name>".')
    original_area_id = fields.Integer()
    ignore_location = fields.Boolean('Ignore', help='Tick for a test machine: its records are not used for staff locations and it is not asked to be completed.')
    original_ignore = fields.Boolean()
    usage = fields.Integer('Records (3 months)', readonly=True)
    last_use = fields.Date('Last used', readonly=True)
    is_active = fields.Boolean('Active', readonly=True, help='Not ticked: the machine is archived (no longer used) but its old records still count for the history.')
    is_local = fields.Boolean('Local server', readonly=True, help='Ticked: the machine is managed by our own face server. Not ticked: its data comes from a REMOTE server (staff checking in there get a work-out request).')
    display_name_now = fields.Char('Shown now', readonly=True)

    def action_use_shown_name(self):
        """Copy the name shown now into Location name (no typing, no typo)."""
        for line in self:
            if not (line.show_name or '').strip():
                line.show_name = line.display_name_now
        # reload the wizard like the top button does: a plain True leaves the open list showing the old value
        return self[:1].wizard_id._reopen()


class StaffLocationSyncMap(models.TransientModel):
    _name = 'kderp.staff.location.sync.map'
    _description = 'Staff location sync: mapping line'

    wizard_id = fields.Many2one('kderp.staff.location.sync.wizard', ondelete='cascade')
    location_id = fields.Many2one('kderp.employee.location.code', 'Our location', readonly=True)
    staff_count = fields.Integer('Staff', readonly=True)
    remote_id = fields.Many2one('kderp.staff.location.remote', 'Remote location', domain=[('active', '=', True)])
    suggested = fields.Boolean('Suggested', readonly=True, help='Chosen automatically because the names look the same. Check it.')
