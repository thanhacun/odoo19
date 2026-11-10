import logging

from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import html_escape
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

class StaffTransfer(models.Model):
    _name = 'staff.transfer'
    _description = 'Staff Movement and Transfer Request'
    _inherit = ['kderp.e.approval.mixin', 'mail.thread']

    _state_from = ['draft', 'submitted']
    _state_to = ['approved']
    _cancel_state = 'rejected'

    # current_project_manual_id is frozen by the last approval, while the request is still under validation
    _allow_to_write_field_list = ['current_project_manual_id', 'current_project_frozen_ids']

    _default_approval_report_xml_id = 'kdvn_hr_procedures.action_report_staff_transfer_py3o'

    _approval_category = 'hr'
    _approval_procedure_title = 'Staff Transfer Request'
    _admin_groups = ['kdvn_hr_procedures.group_staff_transfer_functional_controller']

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string='Status', readonly=True, index=True, default='draft', tracking=True)

    # hr.employee.public (same table as the old single employee would have used): a plain user (SM / PM) cannot read hr.employee,
    # and a Many2many write checks read access on the comodel. Private fields are read through _staff() (sudo).
    transfer_employee_ids = fields.Many2many(
        comodel_name='hr.employee.public', relation='staff_transfer_employee_rel', column1='transfer_id', column2='employee_id',
        string='Staff to transfer', readonly=True, tracking=True,
        help="One or more staff moved together to the same new area / section / project.")
    reason = fields.Text(string='Reason of Transfer')

    # Target Destinations
    transfer_area_id = fields.Many2one(
        comodel_name='hr.department',
        string='New Area',
        readonly=True,
        tracking=True,
        domain=[('type_id.code', '=', 'area')]
    )
    transfer_department_id = fields.Many2one(
        comodel_name='hr.department',
        string='New Section',
        readonly=True,
        tracking=True
    )
    transfer_project_id = fields.Many2one(
        comodel_name='kderp.job.lookup',
        string='New Project',
        readonly=True,
        tracking=True
    )

    transfer_from_date = fields.Date(
        string='Transfer From',
        required=True,
        readonly=True,
        tracking=True
    )
    transfer_to_date = fields.Date(
        string='Transfer To',
        required=True,
        readonly=True,
        tracking=True
    )
    petrol_allowance = fields.Boolean(
        string='Petrol Allowance',
        default=False,
        readonly=True,
        tracking=True
    )

    # Computations for historical snapshot extraction (one value per selected staff, duplicates merged)
    current_area_ids = fields.Many2many(comodel_name='hr.department', compute='_compute_current_allocations', string='Current Area', readonly=True, store=False)
    current_department_ids = fields.Many2many(comodel_name='hr.department', compute='_compute_current_allocations', string='Current Section', readonly=True, store=False)
    # Current project: read from each employee's Project history; for staff without history the applicant types it
    # in (current_project_manual_id). Once approved, the values are frozen (current_project_frozen_ids) so the
    # printed form keeps showing the "before" project after the history gets the new one.
    current_project_ids = fields.Many2many(comodel_name='kderp.job.lookup', compute='_compute_current_allocations', string='Current Project', readonly=True, store=False)
    current_project_manual_id = fields.Many2one(
        comodel_name='kderp.job.lookup', string='Current Project', readonly=True, tracking=True,
        help="Typed in for the staff who have no Project history yet. Frozen when the request is approved.")
    current_project_frozen_ids = fields.Many2many(
        comodel_name='kderp.job.lookup', relation='staff_transfer_frozen_project_rel', column1='transfer_id', column2='job_id',
        string='Current Project (frozen)', readonly=True)
    project_from_history = fields.Boolean(compute='_compute_current_allocations', store=False,
                                          help="True when every selected staff has a Project history")
    no_history_employee_ids = fields.Many2many(comodel_name='hr.employee.public', compute='_compute_current_allocations', store=False,
                                               help="Selected staff without Project history (their current project is typed in)")

    # Distance by car (OpenStreetMap or Goong) from the main office of the staff to the address of the New Project
    transfer_project_address = fields.Text(related='transfer_project_id.project_address', string='Project Location', readonly=True)
    distance_ho_km = fields.Float(string='From Hanoi Head Office (km)', digits=(12, 1), readonly=True, copy=False)
    distance_hp_km = fields.Float(string='From Hai Phong Office (km)', digits=(12, 1), readonly=True, copy=False)
    distance_message = fields.Char(string='Distance note', readonly=True, copy=False)
    distance_text = fields.Char(string='Distance by car', compute='_compute_distance_text')

    allowance_matrix_html = fields.Html(
        string='Transfer Allowance Matrix', compute='_compute_allowance_matrix_html', sanitize=False)

    def _staff(self):
        """The staff to transfer as hr.employee records, read with sudo: department / project history, work location, grade and the
        user are private to HR in Odoo 19, and the applicant (SM / PM) or a reviewer is an ordinary user."""
        return self.env['hr.employee'].sudo().browse(self.transfer_employee_ids.ids)

    @api.depends('transfer_employee_ids', 'transfer_from_date')
    def _compute_allowance_matrix_html(self):
        Matrix = self.env['transfer.allowance.matrix']
        for rec in self:
            grades = rec._staff().mapped('transfer_allowance_grade_id')
            rec.allowance_matrix_html = Matrix.render_matrix_html(
                on_date=rec.transfer_from_date or None, highlight_grade=grades or None)

    # ------------------------------------------------------------------
    # Distance office -> project (by car)
    # ------------------------------------------------------------------
    OFFICE_LABELS = {'ho': 'Hanoi Head Office', 'hp': 'Hai Phong Office'}

    @api.model
    def _office_of(self, emp):
        """Main office of a staff from hr.employee.work_location (area of the administrative section): Hai Phong or else Head Office.
        Ho Chi Minh Branch Office comes later."""
        return 'hp' if 'PHONG' in (emp.work_location or '').upper() else 'ho'

    @api.model
    def _partner_address(self, partner):
        parts = [partner.street, partner.street2, partner.city, partner.state_id.name, partner.country_id.name]
        return ', '.join(p.strip() for p in parts if p and p.strip())

    @api.model
    def _office_address(self, office):
        """Head Office = address of the company. Hai Phong = the company's other address whose city (or name) is Hai Phong
        (a contact / address under the company partner; company form, tab Office Addresses). Empty when there is none."""
        company = self.env.company.sudo().partner_id
        if office == 'hp':
            for child in company.child_ids.filtered(lambda c: c.active):
                label = ('%s %s' % (child.city or '', child.name or '')).lower().replace(' ', '')
                if 'haiphong' in label and self._partner_address(child):
                    return self._partner_address(child)
            return ''
        return self._partner_address(company)

    def _update_distances(self, force=False):
        """Fill the distance fields (only the offices of the selected staff). Never raises: a problem goes to distance_message.
        After submit (not draft) a distance already found is never changed: only the missing ones are filled.
        force = explicit click on Recalculate: ignores the short memory of failed lookups."""
        Route = self.env['transfer.route.distance']
        for rec in self:
            keep = rec.state != 'draft'
            vals = {'distance_ho_km': rec.distance_ho_km if keep else 0.0,
                    'distance_hp_km': rec.distance_hp_km if keep else 0.0, 'distance_message': False}
            destination = rec.transfer_project_id.sudo().project_address
            staff = rec._staff()
            offices = sorted({self._office_of(e) for e in staff})
            problems = []
            if rec.transfer_project_id and offices:
                for office in offices:
                    if keep and vals['distance_%s_km' % office]:
                        continue
                    km, message = Route.get_km(self._office_address(office), destination, force=force)
                    if km is None:
                        problems.append('%s: %s' % (self.OFFICE_LABELS[office], message))
                    else:
                        vals['distance_%s_km' % office] = km
            vals['distance_message'] = '; '.join(problems) or False
            if any(rec[k] != v for k, v in vals.items()):
                # system values: allowed while the request is under validation (see _check_allow_write_under_validation)
                rec.sudo().with_context(skip_distance=True).write(vals)

    DISTANCE_FIELDS = ('distance_ho_km', 'distance_hp_km', 'distance_message')

    def _check_allow_write_under_validation(self, vals):
        """A submitted request has open reviews and the OCA module then refuses every write but a few fields. The distance fields are
        filled by _update_distances (context skip_distance), also by Recalculate after submit: allow exactly those fields then."""
        if self.env.context.get('skip_distance') and set(vals) <= set(self.DISTANCE_FIELDS):
            return True
        return super()._check_allow_write_under_validation(vals)

    def action_update_distances(self):
        self._update_distances(force=True)
        return True

    def _distance_lines(self):
        """[(office label, km)] for the offices of the selected staff that have a distance."""
        self.ensure_one()
        lines = []
        for office in sorted({self._office_of(e) for e in self._staff()}):
            km = self['distance_%s_km' % office]
            if km:
                lines.append((self.OFFICE_LABELS[office], km))
        return lines

    @api.depends('distance_ho_km', 'distance_hp_km', 'distance_message', 'transfer_employee_ids', 'transfer_project_id')
    def _compute_distance_text(self):
        for rec in self:
            lines = ['%s: %.1f km' % (label, km) for label, km in rec._distance_lines()]
            rec.distance_text = '; '.join(lines) or rec.distance_message or False

    def get_approval_digest_details(self):
        if self._name == 'staff.transfer':
            staff = ', '.join(self.transfer_employee_ids.mapped('name')) or 'Unknown Staff'
            target_dept = getattr(self.transfer_department_id, 'name', 'Unknown Dept')
            eff_date = self.transfer_from_date or ''
            return """
                <strong>Staff:</strong> %s<br/>
                <strong>Target Dept:</strong> %s<br/>
                <strong>Effective:</strong> %s<br/>
                <strong>Justification:</strong> %s
            """ % (html_escape(staff), html_escape(target_dept or ''), eff_date, html_escape(self.reason or ''))
        else:
            super(StaffTransfer, self).get_approval_digest_details()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('staff.transfer') or _('New')
        records = super(StaffTransfer, self).create(vals_list)
        if not self.env.context.get('skip_distance'):
            for rec in records:
                if rec.transfer_project_id and rec.transfer_employee_ids:
                    rec._update_distances()
        return records

    @api.constrains('transfer_area_id', 'transfer_department_id', 'transfer_project_id')
    def _check_destination_filled(self):
        for rec in self:
            if not any([rec.transfer_area_id, rec.transfer_department_id, rec.transfer_project_id]):
                raise ValidationError("Operational Lock: You must populate at least one target location metric (New Area, New Section, or New Project).")

    @api.depends('transfer_employee_ids', 'transfer_from_date', 'state', 'current_project_manual_id', 'current_project_frozen_ids')
    def _compute_current_allocations(self):
        """
        Calculates the active historical baseline parameters using effective dates, per selected staff.
        Falls back to current defaults if historic logs are missing.
        """
        for rec in self:
            target_date = rec.transfer_from_date or fields.Date.today()
            depts = self.env['hr.department']
            projects = self.env['kderp.job.lookup']
            no_history = self.env['hr.employee.public']
            # sudo: history lines and department are private to HR in Odoo 19 (managers only get the public profile)
            for emp in rec._staff():
                # History Lookups using historical log lines
                past_depts = emp.department_history_ids.filtered(lambda d: d.effective_date and d.effective_date <= target_date)
                if past_depts:
                    depts |= past_depts.sorted(key=lambda r: r.effective_date, reverse=True)[0].department_id
                else:
                    depts |= emp.department_id
                hist = rec._project_history_before(emp, target_date)
                if hist and hist.project_code:
                    projects |= hist.project_code
                else:
                    no_history |= no_history.browse(emp.id)
            rec.current_department_ids = depts
            rec.current_area_ids = depts.mapped('area_id')
            rec.no_history_employee_ids = no_history
            if rec.state == 'approved':
                # frozen snapshot (see _universal_state_changer); requests approved before the multi-staff
                # change only have the manual value
                rec.current_project_ids = rec.current_project_frozen_ids or rec.current_project_manual_id
                rec.project_from_history = False
                continue
            rec.project_from_history = bool(rec.transfer_employee_ids) and not no_history
            rec.current_project_ids = projects | (rec.current_project_manual_id if no_history else rec.env['kderp.job.lookup'])

    @api.model
    def _project_history_before(self, emp, target_date):
        """Latest Project history line of emp effective on or before target_date (empty recordset if none)."""
        past = emp.sudo().project_history_ids.filtered(lambda p: p.effective_date and p.effective_date <= target_date)
        return past.sorted(key=lambda r: r.effective_date, reverse=True)[:1]

    @api.onchange('transfer_employee_ids')
    def _onchange_transfer_employee_ids(self):
        # a manual value typed for other staff is meaningless
        if not self.no_history_employee_ids:
            self.current_project_manual_id = False

    # ------------------------------------------------------------------
    # After approval: freeze the "before" project, then record the new one in the Project history
    # ------------------------------------------------------------------
    def _universal_state_changer(self, target_state):
        if target_state == getattr(self, '_state_to', ['approved'])[-1]:
            # freeze before the state flips (the compute reads the history while not approved)
            for rec in self.filtered(lambda r: r.state != 'approved'):
                rec.sudo().write({'current_project_frozen_ids': [(6, 0, rec.current_project_ids.ids)]})
        res = super(StaffTransfer, self)._universal_state_changer(target_state)
        if target_state == getattr(self, '_state_to', ['approved'])[-1]:
            self._update_project_history()
            self._notify_transferred_staff()
        return res

    def _update_project_history(self):
        """Every staff is on the New Project from 'Transfer From'. Safe to call twice."""
        History = self.env['hr.employee.project.history'].sudo()
        for rec in self:
            if not (rec.transfer_project_id and rec.transfer_from_date):
                continue
            for emp in rec._staff():
                dup = History.search([('employee_id', '=', emp.id),
                                      ('project_code', '=', rec.transfer_project_id.id),
                                      ('effective_date', '=', rec.transfer_from_date)], limit=1)
                if dup:
                    continue
                History.create({
                    'employee_id': emp.id,
                    'project_code': rec.transfer_project_id.id,
                    'effective_date': rec.transfer_from_date,
                    'project_description': _('Staff transfer %s') % rec.name,
                })
                # Markup % escapes the names (message_post escapes a plain str: no double escaping)
                rec.message_post(body=Markup(_('Project history of %s updated: %s from %s.')) % (
                    emp.name or '', rec.transfer_project_id.display_name or '', rec.transfer_from_date))

    # ------------------------------------------------------------------
    # After approval: tell the transferred staff
    # ------------------------------------------------------------------
    def _notify_transferred_staff(self):
        """Email (and Talk when that is the person's choice) to every transferred staff once the request is approved.
        Follows the global switches of the e-approval settings; a staff without a work e-mail and without Talk gets nothing
        (noted in the chatter). Never raises: the approval must not fail because of a notification."""
        from odoo.addons.kdvn_e_approval.models import approval_notify_render as render
        for rec in self:
            try:
                with rec.env.cr.savepoint():
                    rec._notify_transferred_staff_one(render)
            except Exception as error:  # noqa: BLE001
                _logger.exception("Staff transfer %s: notifying the staff failed", rec.name)
                rec.sudo().message_post(body=Markup(_('Notifying the transferred staff failed: %s')) % str(error))

    def _notify_transferred_staff_one(self, render):
        self.ensure_one()
        cfg = self._notify_config()

        def fmt_date(value):
            return fields.Date.to_date(value).strftime('%d/%m/%Y') if value else '-'

        rows = [
            ('Request', self.name or ''),
            ('Transfer from', fmt_date(self.transfer_from_date)),
            ('Transfer to', fmt_date(self.transfer_to_date)),
            ('New area', self.transfer_area_id.display_name or '-'),
            ('New section', self.transfer_department_id.display_name or '-'),
            ('New project', self.transfer_project_id.display_name or '-'),
            ('Requested by', self.employee_id.sudo().name or ''),
        ]
        sent, missed = [], []
        for emp in self.transfer_employee_ids.sudo():
            user = emp.user_id
            email = emp.work_email or user.email
            if user:
                send_email, send_talk = self._notify_channels(user, cfg, 'result', email=email)
            else:
                send_email, send_talk = bool(cfg['email_on'] and email), False
            if not (send_email or send_talk):
                missed.append(emp.name)
                continue
            intro = _('Hello %s, your transfer request has been approved. The details are below.') % emp.name
            table = ''.join(
                '<tr><td style="padding:4px 12px 4px 0;font-size:13px;color:%s;white-space:nowrap;vertical-align:top;">%s</td>'
                '<td style="padding:4px 0;font-size:13px;color:%s;">%s</td></tr>' % (
                    render.MUTED, html_escape(k), render.TEXT, html_escape(v)) for k, v in rows if v)
            if send_email:
                body = ('<p style="margin:0 0 16px;color:%s;">%s</p>'
                        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;">%s</table>') % (
                    render.TEXT_SOFT, html_escape(intro), table)
                self._notify_send_email(
                    email, _('Transfer approved: %s') % self.name,
                    render.email_shell(_('Your transfer was approved'), body, accent=render.DONE, preheader=intro),
                    auto_delete=True)
            if send_talk:
                text = _('**Transfer approved** %(ref)s\n%(name)s: from %(frm)s to %(to)s, new section: %(dept)s, new project: %(proj)s.') % {
                    'ref': self.name, 'name': emp.name, 'frm': fmt_date(self.transfer_from_date),
                    'to': fmt_date(self.transfer_to_date), 'dept': self.transfer_department_id.display_name or '-',
                    'proj': self.transfer_project_id.display_name or '-'}
                self._notify_send_talk(user, text, cfg)
            sent.append(emp.name)
        note = []
        if sent:
            note.append(Markup(_('Staff notified: %s.')) % ', '.join(sent))
        if missed:
            note.append(Markup(_('Not notified (no work e-mail or notifications switched off): %s.')) % ', '.join(missed))
        if note:
            self.sudo().message_post(body=Markup(' ').join(note))

    @api.constrains('transfer_from_date', 'transfer_to_date')
    def _check_transfer_dates(self):
        for rec in self:
            if rec.transfer_from_date and rec.transfer_to_date and rec.transfer_to_date < rec.transfer_from_date:
                raise ValidationError(_("'Transfer To' cannot be earlier than 'Transfer From'."))

    def _applicant_is_sm_or_pm(self):
        """Applicant is a Section Manager, a GM, or the PM of at least one project."""
        self.ensure_one()
        user = self.employee_id.sudo().user_id
        if not user:
            return False
        if user.has_group('kdvn_hr_attendance.group_hr_attendance_section_manager') or \
                user.has_group('kdvn_hr_attendance.group_hr_attendance_gm'):
            return True
        return self.env['kderp.job.lookup'].sudo().search_count([('user_id', '=', user.id)]) > 0

    def _check_before_submit(self):
        """Business rules checked at Submit (drafts can always be saved)."""
        self.ensure_one()
        is_admin = self.env.user.has_group('base.group_system')
        applicant = self.employee_id.sudo()
        staff = self.transfer_employee_ids
        if not applicant.user_id:
            raise ValidationError(_("The applicant must be linked to a user login."))
        if not is_admin and not self._applicant_is_sm_or_pm():
            raise ValidationError(_("Only a Section Manager (SM) or Project Manager (PM) can submit a personnel transfer request."))
        if not staff:
            raise ValidationError(_("Select at least one staff to transfer."))
        if applicant.id in staff.ids:
            raise ValidationError(_("You cannot request a transfer for yourself."))
        # the staff must come from another section than the applicant's own
        own_sections = applicant.department_id | self.env['hr.department'].sudo().search([('manager_id', '=', applicant.id)])
        for emp in self._staff():
            dept = self._current_department_of(emp)
            if dept and dept in own_sections:
                raise ValidationError(_(
                    "%(staff)s already belongs to your section (%(dept)s). "
                    "A request is for staff of another section.") % {
                        'staff': emp.name, 'dept': dept.display_name})
        # something must really change (for at least one of the staff)
        if self._nothing_changes():
            raise ValidationError(_("The new area, section and project are the same as the current ones: nothing to transfer."))
        self._check_reviewers_exist()

    def _current_department_of(self, emp):
        """Section of one employee on 'Transfer From' (department history, else the employee's own)."""
        self.ensure_one()
        emp = self.env['hr.employee'].sudo().browse(emp.id)
        target_date = self.transfer_from_date or fields.Date.today()
        past = emp.department_history_ids.filtered(lambda d: d.effective_date and d.effective_date <= target_date)
        return past.sorted(key=lambda r: r.effective_date, reverse=True)[0].department_id if past else emp.department_id

    def _nothing_changes(self):
        """True when the destination equals the current place for every selected staff."""
        self.ensure_one()
        target_date = self.transfer_from_date or fields.Date.today()
        for emp in self._staff():
            dept = self._current_department_of(emp)
            hist = self._project_history_before(emp, target_date)
            project = hist.project_code if hist and hist.project_code else self.current_project_manual_id
            if ((self.transfer_area_id and self.transfer_area_id != dept.area_id) or
                    (self.transfer_department_id and self.transfer_department_id != dept) or
                    (self.transfer_project_id and self.transfer_project_id != project)):
                return False
        return True

    def _check_reviewers_exist(self):
        """Every approval step that will apply must find a reviewer (python-expression steps can come out empty)."""
        self.ensure_one()
        for td in self.env['tier.definition'].search([('model', '=', self._name)], order='sequence desc'):
            if td.review_type != 'expression' or not self.evaluate_tier(td):
                continue
            try:
                users = safe_eval(td.reviewer_expression, {'rec': self})
            except Exception as error:
                raise UserError(_("Approval step '%s' cannot be evaluated: %s") % (td.name, error))
            if not users:
                raise ValidationError(_(
                    "No approver found for the step '%s'. Check the manager / GM / area manager "
                    "of the employees concerned, or ask HR.") % (td.name,))

    def action_submit(self):
        """Pre-validation layer checking state locks before triggering workflows"""
        for record in self:
            if record.state != 'draft':
                raise ValidationError("Action Denied: Document is not in a draft state.")
            record._update_distances()
            record._check_before_submit()
        super(StaffTransfer, self).action_submit()

    def write(self, vals):
        """Admin fallback state synchronization engine safely handling stale workflow tables"""
        if vals.get('state') == 'draft':
            # Clean up active review records before performing the rollback operation
            self.env['tier.review'].sudo().search([
                ('model', '=', self._name),
                ('res_id', 'in', self.ids)
            ]).unlink()
        res = super(StaffTransfer, self).write(vals)
        if not self.env.context.get('skip_distance') and {'transfer_project_id', 'transfer_employee_ids'} & set(vals):
            self.filtered(lambda r: r.state == 'draft')._update_distances()
        return res

    def _prepare_staff_transfer_report_data(self):
        """Data for reports/staff_transfer.odt (py3o), one dict per request."""
        self.ensure_one()

        def fmt_dt(value):
            return fields.Date.to_date(value).strftime('%d/%m/%Y') if value else ''

        def fmt_name(rec):
            return rec.display_name if rec else ''

        staff = self._staff()
        grades = staff.mapped('transfer_allowance_grade_id')
        Matrix = self.env['transfer.allowance.matrix']
        on_date = self.transfer_from_date or None
        layout = Matrix._matrix_layout(on_date)

        # Grade as printed in the matrix row (e.g. G01-G08 for the "G8" tag), one per distinct label
        labels = []
        for grade in grades:
            label = grade.code
            if layout:
                label = next((l for l, ids, _v in layout['groups'] if grade.id in ids), label)
            if label not in labels:
                labels.append(label)
        grade_label = ', '.join(labels)

        reviews = self.review_ids.sorted(key=lambda r: r.sequence)
        approvers = [r.done_by.name for r in reviews if r.status == 'approved' and r.done_by]

        data = {
            'form_code': 'CR04-03-F01',
            'reference_no': self.name or '',
            'request_date': fmt_dt(self.create_date),
            'applicant': self.employee_id.name or '',
            'staff_code': ', '.join(c for c in staff.mapped('code') if c),
            'staff_name': ', '.join(n for n in staff.mapped('name') if n),
            'staff_list': [{'no': i + 1, 'code': e.code or '', 'name': e.name or '', 'grade': e.transfer_allowance_grade_id.code or '-'}
                           for i, e in enumerate(staff)],
            'grade': grade_label or '-',
            'reason': self.reason or '',
            'src_area': '; '.join(self.current_area_ids.mapped('display_name')) or '-',
            'src_dept': '; '.join(self.current_department_ids.mapped('display_name')) or '-',
            'src_proj': '; '.join(self.current_project_ids.mapped('display_name')) or '-',
            'dest_area': fmt_name(self.transfer_area_id) or '-',
            'dest_dept': fmt_name(self.transfer_department_id) or '-',
            'dest_proj': fmt_name(self.transfer_project_id) or '-',
            'start_date': fmt_dt(self.transfer_from_date),
            'end_date': fmt_dt(self.transfer_to_date),
            'petrol_allowance': _('Yes') if self.petrol_allowance else _('No'),
            'matrix_png': Matrix.render_matrix_png(on_date, highlight_grade=grades or None),
            'matrix_note': ' '.join((Matrix._matrix_notes(layout, grades or None) if layout else []) + (
                [_('Distance by car to the new project: %s.') % '; '.join('%s %.1f km' % l for l in self._distance_lines())]
                if self._distance_lines() else [])),
            'approval_audit_trail': (_('Approved by: %s') % ' => '.join(approvers)) if approvers else '',
            'qr_code_base64': self.get_py3o_qr_base64(),
        }
        data.update(self._prepare_reviews_signatures())
        return data
