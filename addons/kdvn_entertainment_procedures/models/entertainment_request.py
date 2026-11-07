import sys
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, html_escape
import datetime
import logging

_logger = logging.getLogger(__name__)

class EntertainmentRequest(models.Model):
    _name = 'entertainment.request'
    _inherit = ['mail.thread', 'kderp.e.approval.mixin']
    _description = 'Approval Request for Entertainment Fee'

    _state_from = ['draft', 'submitted']
    _state_to = ['approved']
    _cancel_state = 'rejected'

    _allow_to_write_field_list = []
    # Purpose is optional; a special case (e.g. registered late) needs it as the explanation
    _special_case_explain_field = 'reason'

    _default_approval_report_xml_id = 'kdvn_entertainment_procedures.entertainment_approved_report_py3o'

    _approval_category = 'entertainment'
    _approval_procedure_title = 'Entertainment Fee Request'
    _admin_groups = ['kdvn_entertainment_procedures.group_entertainment_request_functional_manager']

    # code = fields.Char(string="Request Number (n8n Alias)", compute='_compute_n8n_code_alias', inverse='_inverse_n8n_code_alias', store=False)
    reason = fields.Char(string='Purpose', required=False)
    date_entertainment = fields.Date(string='Date of Entertainment', required=True, default=fields.Date.context_today, readonly=True,)
    place = fields.Char(string='Place / Venue', required=True, readonly=True,)
    guests = fields.Text(string='Guests', placeholder="e.g., Mr. A (Director of ABC Corp), Ms. B...", readonly=True,)
    date_input = fields.Date(required=True, default=fields.Date.context_today, readonly=True,)
    employee_ids = fields.Many2many('hr.employee', string='Attendees', required=True, readonly=True, 
                                    default=lambda self: self.env.user.employee_ids and [(6, 0, [self.env.user.employee_ids[0].id])] or False)
    guest_ids = fields.Many2many('kderp.customer.cache', string='Owner/Client', required=True, readonly=True,)
    
    entertainment_type = fields.Selection([
        ('dinner', 'Business Lunch / Dinner'),
        ('gift', 'Client Seasonal Gifting'),
        ('golf', 'Sporting Hospitality (Golf, etc.)'),
        ('other', 'Other Corporate Hospitality')
    ], string='Entertainment Type', default='dinner', required=True, readonly=True,)
    
    estimated_amount = fields.Float(string='Estimated Total Spending (VND)', required=True, readonly=True, digits=[16,0], tracking=True)
    note = fields.Text(string='Supplementary Agenda Details', readonly=True,)

    job_id = fields.Many2one('kderp.job.lookup', string='Job Selection', required=True, readonly=True,)
    job_name_display = fields.Char(string='Job Name Reference', related='job_id.job_name', readonly=True)
    budget_code_id = fields.Many2one('kderp.job.budget.cache', store=True, string='Budget Code', required=True, readonly=True,)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Awaiting Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string='Document State', default='draft', tracking=True)

    total_pax = fields.Integer("Total people", required=True, default=0)
    per_pax_amount = fields.Float("Amount per person", readonly=True, compute='_compute_per_pax_amount', digits=[16,0])

    # expense_sheet_id = fields.Many2one('hr.expense.sheet', string='Linked Expense Report', readonly=True)
    # 🔄 THE DATABASE MIGRATION QUERY (Executes safely during server upgrade)
    def _auto_init_back(self):
        """
        AUTOMATED DATA MIGRATION:
        Runs once when you upgrade the module. It copies your historical 
        Reason data from 'name' to 'reason', and your Number data from 'code' to 'name'.
        """
        cr = self._cr
        # Check if the column 'reason' is being created for the first time
        cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name='entertainment_request' AND column_name='reason';")
        if not cr.fetchone():
            _logger.info("🚚 Migrating historical Entertainment database records to new native names format...")
            
            # Step A: Add the reason column safely
            cr.execute("ALTER TABLE entertainment_request ADD COLUMN reason varchar;")
            
            # Step B: Copy old 'name' values (Reasons) to the new 'reason' field
            cr.execute("UPDATE entertainment_request SET reason = name;")
            
            # Step C: Copy old 'code' values (Request Numbers) into the native 'name' field
            cr.execute("UPDATE entertainment_request SET name = code;")
            
        super(EntertainmentRequest, self)._auto_init()

    @api.depends('name')
    def _compute_n8n_code_alias(self):
        for record in self:
            record.code = record.name # Redirects n8n reads to the native 'name' sequence code

    def _inverse_n8n_code_alias(self):
        for record in self:
            record.name = record.code # Redirects n8n writes back to native 'name'

    @api.onchange('job_id')
    def _onchange_job_id_filter_budget(self):
        """
        💵 FINANCIAL SYNCHRONIZER:
        Filters budget code dropdown lists based on manual human project selections.
        """
        for record in self:
            if record.job_id:
                # Safeguard: If they change the job, old budget entries become invalid, so clear it!
                if record.budget_code_id and record.budget_code_id.job_id != record.job_id:
                    record.budget_code_id = False
                
                # Restrict budget dropdown choices strictly to this active project job
                return {'domain': {'budget_code_id': [('job_id', '=', record.job_id.id)]}}
            
            # If the job selection field is entirely cleared out, wipe the budget options list
            return {'domain': {'budget_code_id': [('id', '=', False)]}}
            
        return {}

    @api.onchange('employee_id')
    def _onchange_employee_id_routing(self):
        """
        👤 HIGH-PRECISION IDENTITY ROUTER:
        Controls Job and Budget view constraints based on granular manager/advisor roles.
        Dynamically handles chronological fallback tracking strings (HE00-YY-1001).
        """
        for record in self:
            job_domain = []
            budget_domain = []

            # Ensure an applicant employee profile is selected
            if record.employee_id:
                target_user = record.employee_id.user_id

                # Initialize lookup matches flag
                has_role_assignment = False
                allowed_jobs_ids = []

                if target_user:
                    # Search specifically against the 3 core high-level operational roles
                    assigned_jobs = self.env['kderp.job.lookup'].search([
                        '|', '|',
                        ('user_id', '=', target_user.id),
                        ('manager_id', '=', target_user.id),
                        ('jp_advisor_id', '=', target_user.id)
                    ])
                    if assigned_jobs:
                        has_role_assignment = True
                        allowed_jobs_ids = assigned_jobs.ids

                # =========================================================================
                # CONDITION A: EMPLOYEE BELONGS TO ACTIVE MANAGERIAL ROLES
                # =========================================================================
                if has_role_assignment:
                    job_domain = [('id', 'in', allowed_jobs_ids)]

                # =========================================================================
                # CONDITION B: GENERAL OPERATION FALLBACK (Dynamic Year Key Generation)
                # =========================================================================
                else:
                    # Extract year digits from 'date_input' field fallback to today's date context
                    eval_date = record.date_input or record.date_entertainment or datetime.date.today()
                    year_suffix = str(eval_date.year)[2:]  # Extracts '26' from 2026
                    
                    # Compile the exact targeted job number tracking variable string
                    fallback_job_no = "HG00-%s-1001" % year_suffix

                    # Execute lookup to retrieve the database row pointer
                    target_job = self.env['kderp.job.lookup'].search([
                        ('job_no', '=', fallback_job_no)
                    ], limit=1)

                    if target_job:
                        record.job_id = target_job.id
                        job_domain = [('id', '=', target_job.id)]
                        
                        # 🔗 FRAMEWORK BRIDGE: Force feed budget domain constraint instantly
                        budget_domain = [('job_id', '=', target_job.id)]

                        # =========================================================================
                        # JAPANESE EXTRA CRITERIA (S9 Code Hard-Coded Budget Auto-Selection)
                        # =========================================================================
                        if record.employee_id.code and str(record.employee_id.code).strip().startswith('S9'):
                            # Search for the explicit target corporate hospitality budget line inside our cache model
                            target_budget = target_job.budget_ids.filtered(lambda b: b.budget_code == '7000A21')
                            
                            if target_budget:
                                record.budget_code_id = target_budget.id
                                budget_domain = [('id', '=', target_budget.id)]
                    else:
                        job_domain = [('id', '=', False)]

                # Dispatch unified response matrix package back onto Odoo view lifecycle engine
                return {
                    'domain': {
                        'job_id': job_domain,
                        'budget_code_id': budget_domain
                    }
                }

            # Fallback cleanup behavior if employee field container is emptied out by hand
            return {
                'domain': {
                    'job_id': [('id', '=', False)],
                    'budget_code_id': [('id', '=', False)]
                }
            }

        return {}
    
    def get_approval_digest_details(self):
        if self._name == 'entertainment.request':
            purpose = '<strong>Purpose: </strong> %s<br/>' % html_escape(self.reason) if self.reason else ''
            return purpose + '<strong>Budget:</strong> %s' % '{:,.0f}'.format(self.estimated_amount or 0)
        else:
            return super(EntertainmentRequest, self).get_approval_digest_details()

    # -------------------------------------------------------------------------
    # Special cases (shared feature of kderp.e.approval.mixin). Limits and actions are rows
    # of kderp.e.approval.special.rule (data/entertainment_special_rules.xml).
    # -------------------------------------------------------------------------
    def _special_case_depends(self):
        return super(EntertainmentRequest, self)._special_case_depends() + [
            'date_entertainment', 'date_input', 'reason']

    def _get_special_case_reasons(self):
        self.ensure_one()
        reasons = []
        fmt = lambda d: d.strftime('%d/%m/%Y')
        # Registered after the entertainment took place
        rule = self._special_rule('late_input')
        if rule.is_on() and self.date_entertainment and self.date_input:
            days = (self.date_input - self.date_entertainment).days
            if days > rule.value:
                reasons.append((rule.action, _('Registered %s day(s) after the entertainment (%s, input date %s)') % (
                    days, fmt(self.date_entertainment), fmt(self.date_input))))
        # Input date set earlier than the day the request was actually created
        rule = self._special_rule('backdated_input')
        if rule.is_on() and self.date_input:
            created = fields.Datetime.context_timestamp(self, self.create_date or fields.Datetime.now()).date()
            days = (created - self.date_input).days
            if days > rule.value:
                reasons.append((rule.action, _('Input date %s is %s day(s) before the request was created (%s)') % (
                    fmt(self.date_input), days, fmt(created))))
        return reasons

    def action_reset_to_draft(self):
        """ Override to check expense_sheet_id"""
        # Prevent resetting if a final accounting document has already been generated
        for record in self:
            # 1. Financial guard-rail check
            if 'expense_sheet_id' in record and record.expense_sheet_id:
                raise UserError(_(
                    "🔒 Reset Blocked!\n\n"
                    "An official financial Expense Sheet (%s) has already been created for this request. "
                    "You must cancel or unlink that sheet before resetting this pre-approval."
                ) % record.expense_sheet_id.name)

        super(EntertainmentRequest, self).action_reset_to_draft()
    
    def action_generate_expense_sheet(self):
        """ 
        Downstream Action: Generates a pre-filled financial draft record 
        inside Odoo's core hr.expense.sheet ledger for reconciliation.
        """
        for record in self:
            if record.expense_sheet_id:
                continue

            # 1. Instantiate the target accounting envelope record
            sheet = self.env['hr.expense.sheet'].create({
                'name': _('Reconciliation: ') + record.name,
                'employee_id': record.employee_id.id,
                'accounting_date': fields.Date.context_today(self),
            })

            # 2. Inject an initial placeholder expense item row detailing the budget ceiling limit
            self.env['hr.expense'].create({
                'name': _('Hospitality Pre-Auth Limit: ') + (record.place or ''),
                'employee_id': record.employee_id.id,
                'product_id': self.env.ref('hr_expense.product_product_fixed_cost', raise_if_not_found=False) or False,
                'unit_amount': record.estimated_amount,
                'quantity': 1.0,
                'sheet_id': sheet.id
            })

            record.write({'expense_sheet_id': sheet.id})

        return {
            'name': _('Generated Expense Sheet'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.expense.sheet',
            'view_mode': 'form',
            'res_id': self.expense_sheet_id.id,
            'target': 'current',
        }

    def action_spawn_payment_settlement(self):
        """
        Temporary non-blocking UI placeholder for the upcoming Payment Request module.
        """
        self.ensure_one()
        title = _('System Notification')
        message = _('The "Create Payment Request" feature is currently under active deployment and will be fully operational in the next framework release.')
        sticky = False

        # Step 1: Detect gevent multi-worker presence
        is_gevent_active = config.get('workers', 0) > 0 or 'gevent' in sys.modules

        # Step 2: Attempt web_notify execution if system infrastructure allows it
        if is_gevent_active and hasattr(self.env.user, 'notify_info'):
            try:
                self.env.user.notify_info(message, title, sticky)
            except Exception:
                pass

        # Step 3: FAIL-SAFE FALLBACK (If gevent longpolling is off)
        return self.env['kderp.notification.wizard'].show_notification_wizard(title=title, message=message, show_cancel=False)
        raise UserError(_(
            "🚀 FUTURE MODULE NOTICE\n\n"
            "%s")
            % message)

    # -------------------------------------------------------------------------
    # Prepare report data
    # -------------------------------------------------------------------------
    def _get_common_report_primitives(self):
        """ Internal helper to inject our mandatory secure cryptographic QR code """
        return {
            'reference_no': self.name or '',
            'applicant': self.employee_id.name or '',
            'qr_code_base64': self.get_py3o_qr_base64(),
            'barcode_base64': self.get_py3o_barcode_base64()
        }

    # Attendee names on the printed form: up to _report_list_max one per line, up to
    # _report_compact_max as one smaller comma-separated paragraph, above that only the count.
    _report_list_max = 10
    _report_compact_max = 30

    @api.model
    def _report_people_block(self, names, unit):
        """ {'list': [...], 'compact': '...', 'total': '...'}: exactly one is filled. """
        names = [n for n in names if n]
        block = {'list': [], 'compact': '', 'total': ''}
        if len(names) <= self._report_list_max:
            block['list'] = names
        elif len(names) <= self._report_compact_max:
            block['compact'] = ', '.join(names)
        else:
            block['total'] = _('%s %s (list not printed)') % (len(names), unit)
        return block

    def prepare_detailed_entertainment_report(self):
        self.ensure_one()
        data = self._get_common_report_primitives()

        fmt_date = lambda d: fields.Date.from_string(d).strftime('%d - %b - %Y') if d else ""
        fmt_vnd = lambda v: "VND {:,.0f}".format(v or 0.0).replace(',', '.')

        # -------------------------------------------------------------------------
        # THE AUDIT TRAIL LOGIC: Compute "Approved by... on behalf of..."
        # -------------------------------------------------------------------------
        status_text = ""
        sorted_reviews = sorted(self.review_ids, key=lambda r: r.sequence)
        rejection_line = next((r for r in sorted_reviews if r.status == 'rejected'), None)
        if rejection_line:
            rejecter_name = rejection_line.done_by.name or _("Authorized Manager")
            status_text = _("Rejected by: %s") % rejecter_name
        else:
            approved_managers = []
            for review in sorted_reviews:
                if review.status == 'approved' and review.done_by:
                    approved_managers.append(review.done_by.name)
            if approved_managers:
                # Output format: Approved by: Manager 1 => Manager 2 => Manager 3
                status_text = _("Approved by: %s") % " => ".join(approved_managers)
            else:
                status_text = _("Status: Pending Initial Validation")

        # -------------------------------------------------------------------------
        # 2. SEMICOLON-SEPARATED ATTACHMENT LISTS
        # -------------------------------------------------------------------------
        attachment_names = [att.datas_fname for att in self.attachment_ids if att.datas_fname]
        formatted_attachments = "; ".join(attachment_names) if attachment_names else _("No files attached.")

        # -------------------------------------------------------------------------
        # 3. HEAD COUNTS: total people is the entered total_pax; our company = attendees listed
        # -------------------------------------------------------------------------
        employee_names = [e.name for e in self.employee_ids if e.name]
        guest_names = [g.name for g in self.guest_ids if g.name]
        emp_count = len(self.employee_ids)
        total_pax = self.total_pax or 0
        people = lambda n: (_('%s person') if n == 1 else _('%s people')) % n
        emp_block = self._report_people_block(employee_names, _('employees'))
        guest_block = self._report_people_block(guest_names, _('companies'))

        # Map requested explicit primitives cleanly
        data.update({
            'date_input': fmt_date(self.date_input),
            'date_entertainment': fmt_date(self.date_entertainment),
            'place': self.place or '',
            'name': self.name or '',
            'reason': self.reason or '-',
            'employee_names': employee_names,
            'guest_names': guest_names,
            'emp_list': emp_block['list'],
            'emp_compact': emp_block['compact'],
            'emp_total': emp_block['total'],
            'guest_list': guest_block['list'],
            'guest_compact': guest_block['compact'],
            'guest_total': guest_block['total'],
            'emp_count': people(emp_count),
            'total_pax': people(total_pax) if total_pax else '-',
            'entertainment_type': dict(self._fields['entertainment_type'].selection).get(self.entertainment_type, ''),
            'estimated_amount': fmt_vnd(self.estimated_amount),
            'per_pax_amount': fmt_vnd(self.per_pax_amount) if total_pax else '-',
            'job_display_name': self.job_id.display_name if self.job_id else '',
            'budget_code': self.budget_code_id.display_name if self.budget_code_id else '',
            'approval_audit_trail': status_text,
            'attachments': formatted_attachments,
        })
        data.update(self._prepare_reviews_signatures())
        return data

    @api.depends('estimated_amount', 'total_pax')
    def _compute_per_pax_amount(self):
        for record in self:
            record.per_pax_amount = (record.estimated_amount / record.total_pax) if record.total_pax else 0

    # @api.model
    # def create(self, vals):
    #     """
    #     OVERRIDE: Intercepts the record creation to fetch and apply 
    #     the automated chronological sequence reference number smoothly.
    #     """
    #     if vals.get('code', None) is None:
    #         # Fetches the next ID using the sequence code defined in our XML data file
    #         vals['code'] = self.env['ir.sequence'].next_by_code('entertainment.request') or None
            
    #     return super(EntertainmentRequest, self).create(vals)

    def unlink(self):
        """
        OVERRIDE: Hardens record deletion constraints.
        Restricts data deletion authorization strictly to members of the 
        E-Approval Administrator security group. Standard users get blocked.
        """
        # Security Guard: Check if the logged-in user belongs to the supervisor override role group
        if self.filtered(lambda record: record.state != 'draft' or record.review_ids):
            raise UserError(_(
                "🔒 Deletion Restricted!\n\n"
                "The record either not in staff state or still have reviews history"
                "Please contact the E-Approval Administrator "
            ))

        # If the user passes the group verification check, execute the standard deletion sequence
        return super(EntertainmentRequest, self).unlink()

    @api.constrains('estimated_amount')
    def _check_positive_amount(self):
        for record in self:
            if record.estimated_amount <= 0:
                raise ValidationError(_("Estimated amount must be greater 0"))

