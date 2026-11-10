from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import html_escape
from . import peak_time_notify_render as peak_render
import logging

_logger = logging.getLogger(__name__)

class KderpProjectPeakTime(models.Model):
    _name = 'kderp.project.peak.time'
    _inherit = ['kderp.e.approval.mixin', 'mail.thread']
    _description = 'Request of Approval For Project Peak Time'

    _state_from = ['draft', 'submitted']
    _state_to = ['approved']
    _cancel_state = 'rejected'

    _allow_to_write_field_list = ['proceed_flow_message', 'proceed_flow_type']

    _default_approval_report_xml_id = 'kdvn_hr_procedures.action_report_peak_time_py3o'

    _approval_category = 'hr'
    _approval_procedure_title = 'Project Peak Time Request'
    _admin_groups = ['kdvn_hr_procedures.group_peak_time_functional_manager']

    # 🏗️ Unique Relational Anchors (Extending the Mixin base)
    job_id = fields.Many2one('kderp.job.lookup', string='Project Job Code', required=True, tracking=True)
    job_name = fields.Char(string='Project Name', related='job_id.job_name', store=True, readonly=True)
    # Filled from the project (onchange) and read-only in the form
    client_id = fields.Many2one('kderp.customer.cache', string='Client Name', required=True, tracking=True)
    k_o_m_date = fields.Date('K.O.M Date', related='job_id.kickoff_meeting_date', store=True, readonly=True)

    # 📅 Category A: Total Execution Duration Period
    execution_from = fields.Date(string='Execution Period From', required=True, tracking=True)
    execution_to = fields.Date(string='Execution Period To', required=True, tracking=True)
    execution_months = fields.Float(string='Execution (Months)', compute='_compute_execution_months', store=True)

    # 📅 Category B: Peak Time as per Kick-Off Meeting (K.O.M)
    kom_peak_from = fields.Date(string='KOM Peak From', tracking=True)
    kom_peak_to = fields.Date(string='KOM Peak To', tracking=True)
    kom_peak_months = fields.Float(string='KOM Peak (Months)', compute='_compute_kom_months', store=True)

    # 📅 Category C: Actual Peak Time Requirement Window
    actual_peak_from = fields.Date(string='Actual Peak From', required=True, tracking=True)
    actual_peak_to = fields.Date(string='Actual Peak To', required=True, tracking=True)
    actual_peak_months = fields.Float(string='Actual Peak (Months)', compute='_compute_actual_months', store=True)

    # 📝 Descriptive Memos
    reason = fields.Text(string='Explanation', required=True, readonly=True)

    # 👥 Target Employee Impact Sub-Grid Matrix
    # hr.employee.public, same relation table as before: a plain SM / PM cannot read hr.employee (private to HR in Odoo 19) and a
    # Many2many write checks read access on the comodel. Odoo 12 has hr.employee here (no public model there).
    employee_ids = fields.Many2many(
        'hr.employee.public',
        'kderp_peak_time_employee_rel', 
        'peak_time_id', 
        'employee_id', 
        string='Staff List', 
        required=True
    )

    state = fields.Selection([
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('synced', 'ATT rule created'),
            ('rejected', 'Rejected')
        ], string='Status', readonly=True, index=True, default='draft', tracking=True)

    # 🔗 RELATIONAL LINK: Holds the reference ID of the auto-generated attendance rule
    attendance_rule_id = fields.Many2one(
        'hr.attendance.rule', 
        string='Linked Attendance Rule', 
        readonly=True, 
        tracking=True
    )

    past_related_request_ids = fields.One2many('kderp.project.peak.time', 'id', compute='_compute_past_related_request_ids', readonly=True)
    # Special cases
    proceed_flow_type = fields.Selection([
        ('normal', 'Normal'),
        ('special', 'Special')
    ], compute='_compute_proceed_flow_placehold', readonly=True)
    proceed_flow_message = fields.Html(compute='_compute_proceed_flow_placehold', readonly=True)

    @api.depends('name', 'actual_peak_months', 'job_id.job_no')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.name}: {record.actual_peak_months} months peak time for {record.job_id.job_no}'

    def get_approval_digest_details(self):
        if self._name == 'kderp.project.peak.time':
            return f"""
                <strong>Job: </strong> {html_escape(self.job_id.job_no or '')}-{html_escape(self.job_name or '')}<br/>
                <strong>Reason:</strong> {html_escape(self.reason or '')}<br/>
                <strong>Duration:</strong> {self.actual_peak_months} months</br>
                <strong>Staffs:</strong> {len(self.employee_ids)}
            """
        else:
            return super(KderpProjectPeakTime, self).get_approval_digest_details()
    
    def _calculate_months_between_dates(self, start, end, half_month_days=15):
        """Whole months between two dates, the end date counted as inclusive.
        21/01 -> 20/03 gives 2, 01/01 -> 31/01 gives 1.
        Leftover days: half_month_days or more count as one more month,
        fewer are dropped. Pass None to ignore leftover days entirely."""
        start = fields.Date.to_date(start)
        end = fields.Date.to_date(end)
        if not start or not end or start > end:
            return 0
        diff = relativedelta(end + relativedelta(days=1), start)
        months = diff.years * 12 + diff.months
        if half_month_days is not None and diff.days >= half_month_days:
            months += 1
        return months
    
    # 🔬 Duration Calculation Engine
    def _calculate_months_between_datetimes(self, start_dt, end_dt):
        # fields.Date.to_date accepts date, datetime and string; only the date part is kept
        start = fields.Date.to_date(start_dt)
        end = fields.Date.to_date(end_dt)
        if not start or not end or start > end:
            return 0.00
        # the end date counts as a full day (21/01 -> 20/03 is exactly 2 months)
        diff = relativedelta(end + relativedelta(days=1), start)
        months = diff.years * 12 + diff.months
        # leftover days become a fraction of a month (average month of 30.44 days)
        return round(months + diff.days / 30.44, 1)

    @api.depends('execution_from', 'execution_to')
    def _compute_execution_months(self):
        for record in self:
            record.execution_months = self._calculate_months_between_datetimes(record.execution_from, record.execution_to)

    @api.depends('kom_peak_from', 'kom_peak_to')
    def _compute_kom_months(self):
        for record in self:
            record.kom_peak_months = self._calculate_months_between_datetimes(record.kom_peak_from, record.kom_peak_to)

    @api.depends('actual_peak_from', 'actual_peak_to')
    def _compute_actual_months(self):
        for record in self:
            record.actual_peak_months = self._calculate_months_between_dates(record.actual_peak_from, record.actual_peak_to)

    def _peak_days_late(self):
        """Calendar days from Actual Peak From to the input date (today for a new request).
        Negative when the request is made before the peak starts. None without a date."""
        self.ensure_one()
        peak_from = fields.Date.to_date(self.actual_peak_from)
        if not peak_from:
            return None
        created = self.create_date or fields.Datetime.now()
        request_date = fields.Datetime.context_timestamp(self, created).date()
        return (request_date - peak_from).days

    # -------------------------------------------------------------------------
    # Special cases (shared feature of kderp.e.approval.mixin). Limits and actions are rows
    # of kderp.e.approval.special.rule (data/peak_time_special_rules.xml), edited by HR.
    # -------------------------------------------------------------------------
    def _special_case_depends(self):
        return super(KderpProjectPeakTime, self)._special_case_depends() + [
            'past_related_request_ids.actual_peak_months', 'past_related_request_ids.state',
            'actual_peak_months', 'actual_peak_from']

    def _get_special_case_reasons(self):
        self.ensure_one()
        reasons = []
        past = self.past_related_request_ids.filtered(lambda r: r.state != 'rejected')
        registration_no = len(past) + 1
        rule = self._special_rule('registration_no')
        if rule.is_on() and registration_no >= rule.value:
            if past:
                text = _('Registration no. %s for this project (already registered %s time(s), '
                         'total %s months)') % (registration_no, len(past), sum(past.mapped('actual_peak_months')))
            else:
                text = _('Registration no. %s for this project') % registration_no
            reasons.append((rule.action, text))

        rule = self._special_rule('long_peak')
        if rule.is_on() and (self.actual_peak_months or 0) > rule.value:
            reasons.append((rule.action, _('Peak time duration greater than %s months') % ('%g' % rule.value)))

        days_late = self._peak_days_late()
        if days_late is not None:
            block = self._special_rule('late_days_block')
            late = self._special_rule('late_days')
            if block.is_on() and days_late > block.value:
                reasons.append((block.action, _('Registered %s days after the actual peak start: more than %s days '
                                                'is not accepted') % (days_late, '%g' % block.value)))
            elif late.is_on() and days_late > late.value:
                reasons.append((late.action, _('Registered %s days after the actual peak start (more than %s days)')
                                % (days_late, '%g' % late.value)))
        return reasons

    @api.depends(lambda self: self._special_case_depends())
    def _compute_proceed_flow_placehold(self):
        """Old names kept for approval-rule conditions and the form:
        proceed_flow_type = 'special' for a special (or blocked) request, banner as message.
        Non-stored: in searches and domains use special_case instead."""
        for record in self:
            record.proceed_flow_type = 'special' if record.special_case_live in ('special', 'blocked') else 'normal'
            record.proceed_flow_message = record.special_case_banner

    @api.onchange('job_id')
    def _onchange_job_id_populate_client(self):
        """
        🚀 AUTO-POPULATING ONCHANGE:
        When a project code is selected, automatically fetch and pre-fill 
        the client data from the job record while keeping the field editable.
        """
        if self.job_id:
            # Client Name is read-only in the form: always take the project's client
            self.client_id = self.job_id.partner_id
            # KOM peak time comes from the project database (remote sync) and is
            # read-only in the form: always take the project's values, even empty
            self.kom_peak_from = self.job_id.kom_peak_from
            self.kom_peak_to = self.job_id.kom_peak_to
            if hasattr(self.job_id, 'date_start') and self.job_id.date_start:
                self.execution_from = self.job_id.date_start
            if hasattr(self.job_id, 'actual_completion_date') and self.job_id.actual_completion_date:
                self.execution_to = self.job_id.actual_completion_date

    @api.depends('job_id')
    def _compute_past_related_request_ids_back(self):
        for record in self:
            past = self.env['kderp.project.peak.time']
            if record.job_id:
                real_id = hasattr(record, 'id') and getattr(record, 'id')
                domain = [('job_id', '=', record.job_id.id)]
                if real_id:
                    domain.append(('id', '!=', real_id))
                    create_date = self.browse(real_id).create_date
                    if create_date:
                        domain.append(('create_date', '<', create_date))
                past = self.search(domain)
            record.past_related_request_ids = [(6, False, past.ids)]

    @api.depends('job_id')
    def _compute_past_related_request_ids(self):
        for record in self:
            past = self.browse()
            if record.job_id:
                domain = [('job_id', '=', record.job_id.id)]
                if record.id:  # NewId is falsy: a draft has nothing to exclude or compare
                    domain.append(('id', '<', record.id))
                past = self.search(domain)
            record.past_related_request_ids = past
    
    @api.constrains('execution_from', 'execution_to', 'kom_peak_from', 'kom_peak_to', 'actual_peak_from', 'actual_peak_to')
    def _check_peak_time_date_constraints(self):
        for record in self:
            if record.execution_from > record.execution_to:
                raise ValidationError("❌ Processing Error: Execution From date cannot sit after Execution To date!")
            if record.kom_peak_from and record.kom_peak_to and record.kom_peak_from > record.kom_peak_to:
                raise ValidationError("❌ Processing Error: KOM Peak From date cannot sit after KOM Peak To date!")
            if record.actual_peak_from > record.actual_peak_to:
                raise ValidationError("❌ Processing Error: Actual Peak From date cannot sit after Actual Peak To date!")

    # 'employee_id' is listed too: Odoo 12 only runs a constraint on create when one of its
    # fields is in the values, and an untouched Staff List isn't. employee_id always is
    # (it has a default), so this also catches a request saved without any staff.
    @api.constrains('employee_ids', 'employee_id')
    def _check_staff_list_not_empty(self):
        for record in self:
            if not record.employee_ids:
                raise ValidationError(_("Please add at least one staff member to the List of employees."))

    @api.constrains('employee_id')
    def _check_applicant_manager_role_tier(self):
        """
        🔒 HARD SECURITY GUARD:
        Ensures the applicant/creator belongs explicitly to the SM or PM group tiers.
        """
        for record in self:
            if record.employee_id:
                # 1. Fetch user record linked to the selected employee profile
                linked_user = record.employee_id.user_id
                
                if not linked_user:
                    raise ValidationError("❌ Registration Error: The selected employee record must be linked to an active system user login.")

                # 2. Check group membership tags (Using your framework's group XML IDs)
                is_sm = linked_user.has_group('kdvn_hr_attendance.group_hr_attendance_section_manager')
                # Assuming your PM group is named like this or similar:
                is_pm = linked_user.has_group('kdvn_hr_attendance.group_hr_attendance_gm') or \
                        self.env['kderp.job.lookup'].search_count([('user_id', '=', linked_user.id)]) > 0

                if not (is_sm or is_pm) and not self.env.user.has_group('base.group_system'):
                    raise ValidationError(
                        "🔒 Access Denied: Only Section Managers (SM) or Project Managers (PM) "
                        "are authorized to initialize or submit Project Peak Time requests."
                    )

    def write(self, vals):
        res = super(KderpProjectPeakTime, self).write(vals)
        
        # Check if the state was updated to 'approved' during this write execution transaction
        if 'state' in vals and vals.get('state') == 'approved':
            for record in self:
                # 🛡️ IDEMPOTENCY SAFETY GUARD: Only execute if rules have not been generated yet
                record._generate_hr_attendance_rules()
        return res

    def pre_reset_to_draft_cleanup(self):
        """
            Override to make an additional cleanup when resetting to draft
        """
        self.ensure_one()
        super(KderpProjectPeakTime, self).pre_reset_to_draft_cleanup()
        if self.attendance_rule_id:
            self.attendance_rule_id.action_cancel()
            self.attendance_rule_id = self.env['hr.attendance.rule']

    # -------------------------------------------------------------------------
    # Printed form CR03-03-F01 (reports/peak_time_approved.odt)
    # -------------------------------------------------------------------------
    _report_staff_min_rows = 9  # the paper form has 9 numbered rows

    @api.model
    def _report_attendance_month(self, date):
        """'MM/YYYY' of the attendance month a date belongs to (21st of last month to 20th)."""
        date = fields.Date.to_date(date)
        if not date:
            return ''
        if date.day >= 21:
            date += relativedelta(months=1)
        return date.strftime('%m/%Y')

    def prepare_peak_time_report_data(self):
        """Data of the printed form for one request (py3o: formatted_data = [this dict])."""
        self.ensure_one()
        fmt_date = lambda d: fields.Date.to_date(d).strftime('%d/%m/%Y') if d else ''
        fmt_months = lambda m: '%g' % m if m else ''
        created = fields.Datetime.context_timestamp(self, self.create_date).date() if self.create_date else False

        # All staff are listed (sorted by staff no.), padded with empty numbered rows up to 9
        staff = self.employee_ids.sorted(key=lambda e: (e.code or '', e.name or ''))
        staff_rows = [{'no': i, 'code': e.code or '', 'name': e.name or '', 'remark': ''}
                      for i, e in enumerate(staff, 1)]
        staff_rows += [{'no': i, 'code': '', 'name': '', 'remark': ''}
                       for i in range(len(staff_rows) + 1, self._report_staff_min_rows + 1)]

        data = {
            'reference_no': self.name or '',
            'date_input': fmt_date(created),
            'job_name': self.job_name or '',
            'client_name': self.client_id.name or '',
            'job_no': self.job_id.job_no or '',
            'exec_from': fmt_date(self.execution_from),
            'exec_to': fmt_date(self.execution_to),
            'exec_months': fmt_months(self.execution_months),
            # Peak time columns are attendance months (From 21/10 prints as 11/YYYY)
            'kom_from': self._report_attendance_month(self.kom_peak_from),
            'kom_to': self._report_attendance_month(self.kom_peak_to),
            'kom_months': fmt_months(self.kom_peak_months),
            'actual_from': self._report_attendance_month(self.actual_peak_from),
            'actual_to': self._report_attendance_month(self.actual_peak_to),
            'actual_months': fmt_months(self.actual_peak_months),
            'reason_lines': (self.reason or '').splitlines(),  # one paragraph per line
            'staff_rows': staff_rows,
        }
        data.update(self._prepare_reviews_signatures())
        return data

    def action_print_secure_authenticated_report(self):
        """Print button: allowed when approved and after the attendance rule was created (synced).
        The mixin version only allows 'approved', which is left a moment after approval here."""
        self.ensure_one()
        if self.state not in ('approved', 'synced'):
            return super(KderpProjectPeakTime, self).action_print_secure_authenticated_report()
        report = self.env.ref(self._default_approval_report_xml_id)
        return report.with_context(wizard_report=True).report_action(
            self.ids, data={'formatted_data': [self.prepare_peak_time_report_data()]})

    def _generate_hr_attendance_rules(self):
        """
        Create peak time attendance rules for all employees assigned to this request.
        Includes an explicit duplicate check guard matching the generated unique name criteria.
        """
        self.ensure_one()
        
        if not self.employee_ids:
            _logger.warning("⚠️ Peak Time Automation Skip: No employees were assigned to request %s", self.name)
            return

        # Reference the core attendance target table engine registry
        attendance_rule_pool = self.env['hr.attendance.rule'].sudo()
        
        # 🛡️ STEP 1: CONSTRUCT THE UNIQUE SPECIFIC TARGET STRING IDENTIFIER
        target_rule_name = f'Peak Time Adjustment for {self.job_id.job_no}. Ref.: {self.name}'
        
        # 🛡️ STEP 2: LOOKUP IN THE DATABASE IF THIS RULE NAME KEY ALREADY EXISTS
        existing_rule = attendance_rule_pool.search([('name', '=', target_rule_name)])

        if existing_rule:
            _logger.warning("🛑 Idempotency Guard: Attendance rule '%s' already exists in the registry. Advancing state to prevent double execution.", target_rule_name)
            self.write({
                'attendance_rule_id': existing_rule.id,
                'state': 'synced'
            })
            return

        _logger.info("⚡ Request %s Approved! Generating hr.attendance.rule line for %s staff rows...", self.name, len(self.employee_ids))
        
        peak_time_att_rule = {
            'name': target_rule_name,
            'apply_mode': 'by_employee',
            'employee_ids': [(6, False, self.employee_ids.ids)],
            'valid_start': self.actual_peak_from,
            'valid_stop': self.actual_peak_to,
            'allow_morning_ot': False,
            'wd_allowed_ot': 90,
            'hd_allowed_ot': 40
        }
        
        try:
            new_att_rule = attendance_rule_pool.create(peak_time_att_rule)
            # Fire the attendance app's internal workflow transition action method directly
            new_att_rule.action_submit()
            self.write({
                'attendance_rule_id': new_att_rule.id,
                'state': 'synced'
            })
            _logger.info("✅ State locked down into 'synced' status profile for record: %s", self.name)
            
        except Exception as e:
            _logger.error(f"❌ Failed to create attendance rule for request {self.name}: {e}")
            raise ValidationError(f"❌ Processing Error: Automation workflow failed while creating compliance attendance rules.\nDetails: {e}")

    # -------------------------------------------------------------------------
    # KOM peak time reminder (daily cron, data/peak_time_cron.xml)
    # -------------------------------------------------------------------------
    @api.model
    def cron_send_kom_peak_reminders(self):
        """Email each project's PM once, reminder_days before KOM Peak From, when the
        project has no peak time request (rejected ones don't count)."""
        rules = self.env['kderp.peak.time.rule'].get_rules()
        cfg = self._notify_config()
        if rules.reminder_days <= 0 or not cfg['email_on']:
            return
        today = fields.Date.context_today(self.with_context(tz=self.env.user.tz or 'Asia/Ho_Chi_Minh'))
        jobs = self.env['kderp.job.lookup'].sudo().search([
            ('kom_peak_from', '>=', today),
            ('kom_peak_from', '<=', today + relativedelta(days=rules.reminder_days)),
            ('user_id', '!=', False),
            ('big_job', '=', True),
            ('state', 'not in', ['done', 'close', 'cancel']),
        ]).filtered(lambda j: j.peak_time_reminder_sent_for != j.kom_peak_from)
        if not jobs:
            return
        late, block = self._special_rule('late_days'), self._special_rule('late_days_block')
        late_special_days = '%g' % late.value if late.is_on() else None
        late_block_days = '%g' % block.value if block.is_on() else None
        groups = self.sudo()._read_group(
            [('job_id', 'in', jobs.ids), ('state', '!=', 'rejected')], ['job_id'], ['__count'])
        registered = {g['job_id'][0] for g in groups if g.get('job_id')}
        action = self.env.ref('kdvn_hr_procedures.action_my_project_peak_times', raise_if_not_found=False)
        register_url = '%s/web#model=%s&view_type=form%s' % (
            cfg['base_url'], self._name, '&action=%s' % action.id if action else '')

        for job in jobs:
            if job.id in registered:
                continue
            pm = job.user_id
            if not pm.email:
                _logger.warning("Peak time reminder: PM %s of %s has no email", pm.login, job.job_no)
                continue
            subject, body = peak_render.kom_reminder_email(
                pm.name, '[%s] %s' % (job.job_no, job.job_name or ''), job.partner_id.name,
                job.kom_peak_from.strftime('%d/%m/%Y'),
                job.kom_peak_to.strftime('%d/%m/%Y') if job.kom_peak_to else '',
                (job.kom_peak_from - today).days, late_special_days, late_block_days,
                register_url)
            try:
                with self.env.cr.savepoint():
                    self._notify_send_email(pm.email, subject, body)
                    job.peak_time_reminder_sent_for = job.kom_peak_from
            except Exception:
                _logger.exception("Peak time reminder failed for %s", job.job_no)
