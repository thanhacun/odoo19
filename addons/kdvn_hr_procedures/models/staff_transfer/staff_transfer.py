from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import html_escape
from odoo.tools.safe_eval import safe_eval
from datetime import datetime

class StaffTransfer(models.Model):
    _name = 'staff.transfer'
    _description = 'Staff Movement and Transfer Request'
    _inherit = ['kderp.e.approval.mixin', 'mail.thread']

    _state_from = ['draft', 'submitted']
    _state_to = ['approved']
    _cancel_state = 'rejected'

    # current_project_manual_id is frozen by the last approval, while the request is still under validation
    _allow_to_write_field_list = ['current_project_manual_id']

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

    transfer_employee_id = fields.Many2one(comodel_name='hr.employee',string='Transfer Employee', required=True, readonly=True, tracking=True)
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

    # Computations for historical snapshot extraction
    current_area_id = fields.Many2one(comodel_name='hr.department', compute='_compute_current_allocations', string='Current Area', readonly=True, store=False)
    current_department_id = fields.Many2one(comodel_name='hr.department', compute='_compute_current_allocations', string='Current Section', readonly=True, store=False)
    # Current project: read from the employee's Project history; while HR has no history for this
    # employee the applicant types it in (current_project_manual_id). Once approved, the value is frozen here
    # so the printed form keeps showing the "before" project after the history gets the new one.
    current_project_id = fields.Many2one(comodel_name='kderp.job.lookup', compute='_compute_current_allocations', string='Current Project', readonly=True, store=False)
    current_project_manual_id = fields.Many2one(
        comodel_name='kderp.job.lookup', string='Current Project', readonly=True, tracking=True,
        help="Typed in only when the employee has no Project history yet. Frozen when the request is approved.")
    project_from_history = fields.Boolean(compute='_compute_current_allocations', store=False,
                                          help="True when the current project comes from the Project history")

    allowance_matrix_html = fields.Html(
        string='Transfer Allowance Matrix', compute='_compute_allowance_matrix_html', sanitize=False)

    @api.depends('transfer_employee_id', 'transfer_from_date')
    def _compute_allowance_matrix_html(self):
        Matrix = self.env['transfer.allowance.matrix']
        for rec in self:
            grade = rec.transfer_employee_id.transfer_allowance_grade_id
            rec.allowance_matrix_html = Matrix.render_matrix_html(
                on_date=rec.transfer_from_date or None, highlight_grade=grade or None)

    def get_approval_digest_details(self):
        if self._name == 'staff.transfer':
            staff = getattr(self.employee_id, 'name', 'Unknown Staff')
            target_dept = getattr(self.transfer_department_id, 'name', 'Unknown Dept')
            eff_date = self.transfer_from_date or ''
            return """
                <strong>Staff:</strong> %s<br/>
                <strong>Target Dept:</strong> %s<br/>
                <strong>Effective:</strong> %s<br/>
                <strong>Justification:</strong> %s
            """ % (staff, target_dept, eff_date, self.reason)
        else:
            super(StaffTransfer, self).get_approval_digest_details()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('staff.transfer') or _('New')
        return super(StaffTransfer, self).create(vals_list)

    @api.constrains('transfer_area_id', 'transfer_department_id', 'transfer_project_id')
    def _check_destination_filled(self):
        for rec in self:
            if not any([rec.transfer_area_id, rec.transfer_department_id, rec.transfer_project_id]):
                raise ValidationError("Operational Lock: You must populate at least one target location metric (New Area, New Section, or New Project).")

    @api.depends('transfer_employee_id', 'transfer_from_date', 'state', 'current_project_manual_id')
    def _compute_current_allocations(self):
        """
        Calculates the active historical baseline parameters using effective dates.
        Falls back to current defaults if historic logs are missing.
        """
        for rec in self:
            if not rec.transfer_employee_id:
                rec.current_area_id = False
                rec.current_department_id = False
                rec.current_project_id = False
                rec.project_from_history = False
                continue

            target_date = rec.transfer_from_date or fields.Date.today()
            emp = rec.transfer_employee_id

            # History Lookups using historical log lines
            past_depts = emp.department_history_ids.filtered(lambda d: d.effective_date and d.effective_date <= target_date)
            if past_depts:
                sorted_depts = past_depts.sorted(key=lambda r: r.effective_date, reverse=True)
                active_dept = sorted_depts[0].department_id
            else:
                active_dept = emp.department_id

            rec.current_department_id = active_dept
            rec.current_area_id = active_dept.area_id if active_dept else False

            if rec.state == 'approved':
                # frozen snapshot (see _after_approved)
                rec.current_project_id = rec.current_project_manual_id
                rec.project_from_history = False
                continue
            hist = rec._project_history_before(emp, target_date)
            if hist and hist.project_code:
                rec.project_from_history = True
                rec.current_project_id = hist.project_code
            else:
                rec.project_from_history = False
                rec.current_project_id = rec.current_project_manual_id

    @api.model
    def _project_history_before(self, emp, target_date):
        """Latest Project history line of emp effective on or before target_date (empty recordset if none)."""
        past = emp.sudo().project_history_ids.filtered(lambda p: p.effective_date and p.effective_date <= target_date)
        return past.sorted(key=lambda r: r.effective_date, reverse=True)[:1]

    @api.onchange('transfer_employee_id')
    def _onchange_transfer_employee_id(self):
        # a manual value typed for another employee is meaningless
        self.current_project_manual_id = False

    # ------------------------------------------------------------------
    # After approval: freeze the "before" project, then record the new one in the Project history
    # ------------------------------------------------------------------
    def _universal_state_changer(self, target_state):
        if target_state == getattr(self, '_state_to', ['approved'])[-1]:
            # freeze before the state flips (the compute reads the history while not approved)
            for rec in self.filtered(lambda r: r.state != 'approved'):
                rec.sudo().write({'current_project_manual_id': rec.current_project_id.id or False})
        res = super(StaffTransfer, self)._universal_state_changer(target_state)
        if target_state == getattr(self, '_state_to', ['approved'])[-1]:
            self._update_project_history()
        return res

    def _update_project_history(self):
        """The employee is on the New Project from 'Transfer From'. Safe to call twice."""
        History = self.env['hr.employee.project.history'].sudo()
        for rec in self:
            if not (rec.transfer_project_id and rec.transfer_from_date):
                continue
            dup = History.search([('employee_id', '=', rec.transfer_employee_id.id),
                                  ('project_code', '=', rec.transfer_project_id.id),
                                  ('effective_date', '=', rec.transfer_from_date)], limit=1)
            if dup:
                continue
            History.create({
                'employee_id': rec.transfer_employee_id.id,
                'project_code': rec.transfer_project_id.id,
                'effective_date': rec.transfer_from_date,
                'project_description': _('Staff transfer %s') % rec.name,
            })
            rec.message_post(body=_('Project history of %s updated: %s from %s.') % (
                html_escape(rec.transfer_employee_id.name or ''),
                html_escape(rec.transfer_project_id.display_name or ''), rec.transfer_from_date))

    @api.constrains('transfer_from_date', 'transfer_to_date')
    def _check_transfer_dates(self):
        for rec in self:
            if rec.transfer_from_date and rec.transfer_to_date and rec.transfer_to_date < rec.transfer_from_date:
                raise ValidationError(_("'Transfer To' cannot be earlier than 'Transfer From'."))

    def _applicant_is_sm_or_pm(self):
        """Applicant is a Section Manager, a GM, or the PM of at least one project."""
        self.ensure_one()
        user = self.employee_id.user_id
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
        applicant = self.employee_id
        staff = self.transfer_employee_id
        if not applicant.user_id:
            raise ValidationError(_("The applicant must be linked to a user login."))
        if not is_admin and not self._applicant_is_sm_or_pm():
            raise ValidationError(_("Only a Section Manager (SM) or Project Manager (PM) can submit a personnel transfer request."))
        if staff == applicant:
            raise ValidationError(_("You cannot request a transfer for yourself."))
        # the staff must come from another section than the applicant's own
        own_sections = applicant.department_id | self.env['hr.department'].sudo().search([('manager_id', '=', applicant.id)])
        if self.current_department_id and self.current_department_id in own_sections:
            raise ValidationError(_(
                "%(staff)s already belongs to your section (%(dept)s). "
                "A request is for staff of another section.") % {
                    'staff': staff.name, 'dept': self.current_department_id.display_name})
        # something must really change
        unchanged = (
            (not self.transfer_area_id or self.transfer_area_id == self.current_area_id) and
            (not self.transfer_department_id or self.transfer_department_id == self.current_department_id) and
            (not self.transfer_project_id or self.transfer_project_id == self.current_project_id))
        if unchanged:
            raise ValidationError(_("The new area, section and project are the same as the current ones: nothing to transfer."))
        self._check_reviewers_exist()

    def _check_reviewers_exist(self):
        """Every approval step that will apply must find a reviewer (python-expression steps can come out empty)."""
        self.ensure_one()
        for td in self.env['tier.definition'].search([('model', '=', self._name)], order='sequence desc'):
            if td.review_type != 'expression' or not self.evaluate_tier(td):
                continue
            try:
                users = safe_eval(td.reviewer_expression, globals_dict={'rec': self})
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
        return super(StaffTransfer, self).write(vals)

    def _prepare_staff_transfer_report_data(self):
        """Data for reports/staff_transfer.odt (py3o), one dict per request."""
        self.ensure_one()

        def fmt_dt(value):
            return fields.Date.to_date(value).strftime('%d/%m/%Y') if value else ''

        def fmt_name(rec):
            return rec.display_name if rec else ''

        emp = self.transfer_employee_id
        grade = emp.transfer_allowance_grade_id
        Matrix = self.env['transfer.allowance.matrix']
        on_date = self.transfer_from_date or None
        layout = Matrix._matrix_layout(on_date)

        # Grade as printed in the matrix row (e.g. G01-G08 for the "G8" tag)
        grade_label = grade.code if grade else ''
        if grade and layout:
            grade_label = next((label for label, ids, _v in layout['groups'] if grade.id in ids), grade_label)

        reviews = self.review_ids.sorted(key=lambda r: r.sequence)
        approvers = [r.done_by.name for r in reviews if r.status == 'approved' and r.done_by]

        data = {
            'form_code': 'CR04-03-F01',
            'reference_no': self.name or '',
            'request_date': fmt_dt(self.create_date),
            'applicant': self.employee_id.name or '',
            'staff_code': emp.code or '',
            'staff_name': emp.name or '',
            'grade': grade_label or '-',
            'reason': self.reason or '',
            'src_area': fmt_name(self.current_area_id) or '-',
            'src_dept': fmt_name(self.current_department_id) or '-',
            'src_proj': fmt_name(self.current_project_id) or '-',
            'dest_area': fmt_name(self.transfer_area_id) or '-',
            'dest_dept': fmt_name(self.transfer_department_id) or '-',
            'dest_proj': fmt_name(self.transfer_project_id) or '-',
            'start_date': fmt_dt(self.transfer_from_date),
            'end_date': fmt_dt(self.transfer_to_date),
            'petrol_allowance': _('Yes') if self.petrol_allowance else _('No'),
            'matrix_png': Matrix.render_matrix_png(on_date, highlight_grade=grade or None),
            'matrix_note': ' '.join(Matrix._matrix_notes(layout, grade or None)) if layout else '',
            'approval_audit_trail': (_('Approved by: %s') % ' => '.join(approvers)) if approvers else '',
            'qr_code_base64': self.get_py3o_qr_base64(),
        }
        data.update(self._prepare_reviews_signatures())
        return data
