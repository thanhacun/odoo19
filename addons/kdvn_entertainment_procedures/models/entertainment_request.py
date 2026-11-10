import sys
from markupsafe import Markup
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
    # "Request Date" (technical name date_input). Editable only for a short window (until REQUEST_DATE_EDITABLE_UNTIL, System Parameter
    # kderp_entertainment_procedures.request_date_editable_until, default 1 Jan 2027); after it the date is always the day the request is created.
    date_input = fields.Date(string='Request Date', required=True, default=fields.Date.context_today, copy=False, readonly=True,)
    request_date_editable = fields.Boolean(compute='_compute_request_date_editable')
    request_date_note = fields.Char(compute='_compute_request_date_editable')
    # hr.employee.public (names only): plain staff cannot read hr.employee in Odoo 19. Same relation table and ids as hr.employee.
    employee_ids = fields.Many2many('hr.employee.public', 'entertainment_request_hr_employee_rel', 'entertainment_request_id', 'hr_employee_id',
                                    string='Attendees', required=True, readonly=True, 
                                    default=lambda self: self.env.user.employee_ids and [(6, 0, [self.env.user.employee_ids[0].id])] or False)
    guest_ids = fields.Many2many('kderp.customer.cache', string='Owner/Client', required=True, readonly=True,)
    # The client is new: the applicant picks the placeholder client (code NEW_CLIENT_CODE, "New Client", created on the remote server) and
    # describes the real client in Guests. The registrars are told by email; when the client is registered on the remote server with this
    # request number in its Notes, the pull replaces the placeholder (see models/customer_cache.py).
    has_new_client = fields.Boolean(compute='_compute_has_new_client', string='New client (placeholder)')
    # Not stored: a tick that acts at once (works on an unsaved form, where a button would first have to save a form that
    # cannot be saved without a client) and unticks itself.
    refresh_clients = fields.Boolean(string='New client not in the list? Tick to refresh', store=False,
                                     help='Reads the clients registered on the remote server since the last refresh (the list is also refreshed every few '
                                          'minutes). A new client must first be registered there by the responsible staff.')
    
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

    # copy=False: a duplicate of a refused (or approved) request starts again as a draft
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Awaiting Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string='Document State', default='draft', copy=False, tracking=True)

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

    NEW_CLIENT_CODE = 'CC0000'
    REQUEST_DATE_PARAM = 'kderp_entertainment_procedures.request_date_editable_until'
    REQUEST_DATE_DEFAULT_UNTIL = datetime.date(2027, 1, 1)

    @api.model
    def _request_date_deadline(self):
        """First day on which the Request Date is no longer editable."""
        raw = self.env['ir.config_parameter'].sudo().get_param(self.REQUEST_DATE_PARAM)
        try:
            return fields.Date.from_string(raw) if raw else self.REQUEST_DATE_DEFAULT_UNTIL
        except (ValueError, TypeError):
            return self.REQUEST_DATE_DEFAULT_UNTIL

    @api.model
    def _request_date_open(self):
        return fields.Date.context_today(self) < self._request_date_deadline()

    @api.depends('state')
    def _compute_request_date_editable(self):
        deadline = self._request_date_deadline()
        is_open = self._request_date_open()
        note = _('You can change the Request Date only for a short time, until %s. From then on it is always the day '
                 'the request is created.') % deadline.strftime('%d/%m/%Y')
        for rec in self:
            rec.request_date_editable = is_open
            rec.request_date_note = note if is_open else False

    @api.depends('guest_ids', 'guest_ids.code')
    def _compute_has_new_client(self):
        for rec in self:
            rec.has_new_client = any(c.code == self.NEW_CLIENT_CODE for c in rec.guest_ids)

    @api.constrains('guest_ids', 'guests')
    def _check_new_client_described(self):
        if self.env.context.get('kdvn_legacy_import'):
            return   # Odoo 12 history is copied as it is
        for rec in self:
            if rec.has_new_client and not (rec.guests or '').strip():
                raise ValidationError(_(
                    "You chose the client 'New Client' (%s): describe the real client in the Guests field "
                    "(company name, address, tax code if you have it, contact person).") % self.NEW_CLIENT_CODE)

    @api.model_create_multi
    def create(self, vals_list):
        # The legacy import copies Odoo 12 request dates as they are, whatever today is
        if not self._request_date_open() and not self.env.context.get('kdvn_legacy_import'):
            for vals in vals_list:
                vals.pop('date_input', None)       # the field default is today
        return super().create(vals_list)

    def write(self, vals):
        if 'date_input' in vals and not self._request_date_open() and not self.env.context.get('kdvn_legacy_import'):
            vals = {k: v for k, v in vals.items() if k != 'date_input'}
        return super().write(vals)

    def _check_allow_write_under_validation(self, vals):
        # The client sync replaces the placeholder client of a request that is under validation; nobody else may edit it then
        if self.env.context.get('kderp_new_client_update') and set(vals) <= {'guest_ids'}:
            return True
        return super()._check_allow_write_under_validation(vals)

    # ---- tell the registrars, and replace the placeholder when the client exists
    def _new_client_registrars(self):
        """Users who register new clients: group 'Entertainment: New Client Registrar', else the functional controllers."""
        group = self.env.ref('kdvn_entertainment_procedures.group_entertainment_new_client_registrar')
        users = group.sudo().user_ids.filtered('active')
        if not users:
            users = self.env.ref('kdvn_entertainment_procedures.group_entertainment_request_functional_manager').sudo().user_ids.filtered('active')
        return users

    def _notify_new_client_registrars(self):
        """Email asking to register the client on the remote server with this request number in the Notes. Never raises."""
        from odoo.addons.kdvn_e_approval.models import approval_notify_render as render
        cfg = self._notify_config()
        for rec in self.filtered('has_new_client'):
            try:
                emails = sorted({u.email or u.employee_ids[:1].work_email or '' for u in rec._new_client_registrars()} - {''})
                if not (cfg['email_on'] and emails):
                    rec.sudo().message_post(body=_('New client: nobody could be told by email (no registrar with an email, or email '
                                                   'switched off). Please ask the registrars to register the client.'))
                    continue
                data = rec.sudo()      # the applicant is a plain user: read the names as the system
                rows = [(_('Request'), data.name), (_('Requested by'), data.employee_id.name or ''),
                        (_('Date of entertainment'), data.date_entertainment.strftime('%d/%m/%Y') if data.date_entertainment else ''),
                        (_('Place'), data.place or ''), (_('Job'), data.job_id.display_name or ''),
                        (_('Client as described'), data.guests or '')]
                table = ''.join(
                    '<tr><td style="padding:4px 12px 4px 0;font-size:13px;color:%s;white-space:nowrap;vertical-align:top;">%s</td>'
                    '<td style="padding:4px 0;font-size:13px;color:%s;white-space:pre-wrap;">%s</td></tr>' % (
                        render.MUTED, html_escape(k), render.TEXT, html_escape(v)) for k, v in rows if v)
                intro = _('A new client is needed for an entertainment request. Please register it on the remote server and write the '
                          'request number %s in the Notes of the client.') % rec.name
                body = ('<p style="margin:0 0 16px;color:%s;">%s</p>'
                        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;">%s</table>'
                        '<p style="margin:0;color:%s;font-size:12px;">%s</p>') % (
                    render.TEXT_SOFT, html_escape(intro), table, render.MUTED,
                    html_escape(_('The request is updated automatically with the new client a few minutes after the client is saved there.')))
                subject = _('New client to register: %s') % rec.name
                html = render.email_shell(_('New client to register'), body, accent=render.CURRENT, preheader=intro)
                for email in emails:
                    rec._notify_send_email(email, subject, html, auto_delete=True)
                rec.sudo().message_post(body=Markup(_('New client: registrars told by email (%s).')) % ', '.join(emails))
            except Exception as error:  # noqa: BLE001
                _logger.exception("Entertainment %s: mail for the new client failed", rec.name)
                rec.sudo().message_post(body=Markup(_('The email for the new client could not be sent: %s')) % str(error))

    def action_submit(self):
        res = super().action_submit()
        self._notify_new_client_registrars()
        return res

    def _replace_new_client(self, client):
        """Put the registered client in place of the placeholder (system action, also while the request is under validation)."""
        for rec in self:
            placeholders = rec.guest_ids.filtered(lambda c: c.code == self.NEW_CLIENT_CODE)
            if not placeholders or client in placeholders:
                continue
            commands = [(3, c.id) for c in placeholders]
            if client not in rec.guest_ids:
                commands.append((4, client.id))
            rec.sudo().with_context(kderp_new_client_update=True).write({'guest_ids': commands})
            rec.sudo().message_post(body=Markup(_("The client 'New Client' was replaced by the registered client %s.")) % client.display_name)

    @api.onchange('refresh_clients')
    def _onchange_refresh_clients(self):
        if not self.refresh_clients:
            return
        self.refresh_clients = False
        title = _('Client list')
        try:
            result = self.env['kderp.remote.pull'].sudo().refresh_customers_now()
        except UserError as error:
            return {'warning': {'title': title, 'message': _('The remote server could not be read now, try again later.\n%s') % (str(error) or '')}}
        if result['skipped']:
            return {'warning': {'title': title, 'message': _('The list was refreshed a moment ago. Try the client field again, or tick again in a few seconds.')}}
        if result['new']:
            return {'warning': {'title': title, 'message': _('New clients now in the list:\n%s') % '\n'.join(result['new'][:20])}}
        return {'warning': {'title': title, 'message': _('No new client on the remote server yet. If the client is new, ask the responsible staff to '
                                                        'register it on the remote server first, then tick again.')}}

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

    # Jobs the applicant may pick. Odoo 12 returned this list as the domain of an onchange; Odoo 19 ignores a domain returned by an
    # onchange, so the list is a computed field and the form view uses it as the domain of job_id.
    allowed_job_ids = fields.Many2many('kderp.job.lookup', string='Jobs the applicant may pick', compute='_compute_allowed_job_ids')

    def _job_choice(self):
        """(jobs the applicant may pick, True when it is the yearly fallback job).
        A user with a role on jobs (PM, SM, JP advisor, GM, AM, acting PM, "Sec. Man. / Others") gets those jobs; everybody else gets the
        general job HG00-YY-1001 of the year of the Request Date. Private employee fields are read as the system (plain staff cannot read hr.employee)."""
        self.ensure_one()
        Job = self.env['kderp.job.lookup']
        employee = self.employee_id.sudo()
        if not employee:
            return Job.browse(), False
        target_user = employee.user_id
        if target_user:
            role_fields = ('user_id', 'manager_id', 'jp_advisor_id', 'general_project_manager_id',
                           'area_manager_id', 'acting_project_manager_id', 'project_manager_ref')
            assigned_jobs = Job.search(['|'] * (len(role_fields) - 1) + [(f, '=', target_user.id) for f in role_fields])
            if assigned_jobs:
                return assigned_jobs, False
        # Year digits come from the Request Date, else the date of entertainment, else today
        eval_date = self.date_input or self.date_entertainment or datetime.date.today()
        return Job.search([('job_no', '=', "HG00-%s-1001" % str(eval_date.year)[2:])], limit=1), True

    @api.depends('employee_id', 'date_input', 'date_entertainment')
    def _compute_allowed_job_ids(self):
        for record in self:
            record.allowed_job_ids = record._job_choice()[0]

    # Budget lines the applicant may pick (domain of budget_code_id; Odoo 19 ignores onchange domains). Odoo 12: the budgets of the job; a Japanese
    # applicant (employee code S9...) without a job role, on the general job of the year, may pick only the hospitality line 7000A21.
    JAPANESE_CODE_PREFIX = 'S9'
    JAPANESE_BUDGET_CODE = '7000A21'
    allowed_budget_ids = fields.Many2many('kderp.job.budget.cache', string='Budget codes the applicant may pick', compute='_compute_allowed_budget_ids')

    def _japanese_budget(self, job):
        """The hospitality budget line of `job` when this applicant is Japanese (code S9...) and `job` is the general job of the year, else empty."""
        self.ensure_one()
        Budget = self.env['kderp.job.budget.cache']
        jobs, is_fallback = self._job_choice()
        if not (is_fallback and job and job in jobs
                and str(self.employee_id.sudo().code or '').strip().startswith(self.JAPANESE_CODE_PREFIX)):
            return Budget.browse()
        return job.budget_ids.filtered(lambda b: b.budget_code == self.JAPANESE_BUDGET_CODE)[:1]

    @api.depends('employee_id', 'date_input', 'date_entertainment', 'job_id')
    def _compute_allowed_budget_ids(self):
        Budget = self.env['kderp.job.budget.cache']
        for record in self:
            if not record.job_id:
                record.allowed_budget_ids = Budget.browse()
                continue
            only = record._japanese_budget(record.job_id)
            record.allowed_budget_ids = only or Budget.search([('job_id', '=', record.job_id.id)])

    @api.onchange('employee_id', 'date_input')
    def _onchange_employee_id_routing(self):
        """
        Identity router: a user without a job role gets the general job of the year of the Request Date (HG00-YY-1001),
        and a Japanese applicant (code S9...) its entertainment budget line. The lists to pick from are allowed_job_ids and allowed_budget_ids.
        """
        for record in self:
            jobs, is_fallback = record._job_choice()
            if is_fallback and jobs:
                record.job_id = jobs.id
                target_budget = record._japanese_budget(jobs)
                if target_budget:
                    record.budget_code_id = target_budget.id

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
        attachment_names = [att.name for att in self.attachment_ids if att.name]
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
        if self.env.context.get('kdvn_legacy_import'):
            return   # Odoo 12 history from before this rule (approved requests with amount 0) is copied as it is
        for record in self:
            if record.estimated_amount <= 0:
                raise ValidationError(_("Estimated amount must be greater 0"))

