from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import json
import logging

class KderpPaymentSettlement(models.Model):
    _name = 'kderp.payment.settlement'
    _inherit = ['mail.thread', 'tier.validation']
    _description = 'Universal Financial Settlement & Reimbursement Portal'

    name = fields.Char(string='Settlement Reference', required=True, copy=False, readonly=True, default='New')
    
    # Polymorphic Origins: Tells us exactly which request type spawned this payment
    source_model = fields.Char(string='Source Model Document Type', readonly=True, index=True)
    source_res_id = fields.Integer(string='Source Record ID', readonly=True, index=True)
    source_document_ref = fields.Char(string='Origin Pre-Approval Reference', readonly=True)

    applicant_id = fields.Many2one('hr.employee', string='Payee / Claimant', required=True)
    date_settlement = fields.Date(string='Claim Date', default=fields.Date.context_today, required=True)
    
    # Financial Matrix Fields
    approved_budget = fields.Float(string='Authorized Pre-Approval Budget', readonly=True)
    actual_invoice_amount = fields.Float(string='Actual Spending (Invoice Total)', required=True)
    variance_amount = fields.Float(string='Budget Variance', compute='_compute_variance', store=True)

    payment_method = fields.Selection([
        ('cash_back', 'Reimburse Cash to Staff (Staff paid already)'),
        ('supplier_transfer', 'Direct Bank Transfer to Supplier/Seller')
    ], string='Payment Method Target', default='cash_back', required=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'GA Reviewing'),
        ('paid', 'Paid / Cleared'),
        ('rejected', 'Rejected')
    ], default='draft', tracking=True)

    invoice_attachment_ids = fields.Many2many('ir.attachment', string='Legal Invoices / Receipts')

    # Add a field to store the link to the generated local expense sheet
    hr_expense_sheet_id = fields.Many2one('hr.expense.sheet', string='Local Expense Sheet Record', readonly=True)

    @api.depends('approved_budget', 'actual_invoice_amount')
    def _compute_variance(self):
        for record in self:
            record.variance_amount = record.actual_invoice_amount - record.approved_budget

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('kderp.payment.settlement') or 'SET/'
        return super(KderpPaymentSettlement, self).create(vals)

    def action_post_and_clear_payment(self):
        """
        ACCOUNTING ACTION: Generates local hr.expense lines AND triggers an
        outbound n8n webhook payload to push analytic account lines to the external server.
        """
        self.ensure_one()
        
        if self.state == 'paid':
            raise UserError(_("This settlement has already been paid and posted."))

        # -----------------------------------------------------------------
        # PHASE 1: GENERATE LOCAL HR.EXPENSE RECORDS (For local auditing)
        # -----------------------------------------------------------------
        expense_obj = self.env['hr.expense'].sudo()
        sheet_obj = self.env['hr.expense.sheet'].sudo()

        # Find or create a generic product for entertainment/service mapping
        product = self.env['product.product'].search([('can_be_expensed', '=', True)], limit=1)
        if not product:
            raise UserError(_("Configuration Error: Please ensure at least one Product is marked as 'Can be Expensed' in your database."))

        # A. Create the individual raw expense line row
        local_expense = expense_obj.create({
            'name': self.source_document_ref or self.name,
            'employee_id': self.applicant_id.id,
            'product_id': product.id,
            'unit_amount': self.actual_invoice_amount,
            'quantity': 1.0,
            'date': self.date_settlement,
        })

        # B. Create the master Expense Sheet envelope container and link it
        local_sheet = sheet_obj.create({
            'name': _("Settlement Closeout: %s") % (self.name),
            'employee_id': self.applicant_id.id,
            'expense_line_ids': [(4, local_expense.id)],
        })
        
        # Approve and Post the local sheet internally so it locks down cleanly
        local_sheet.action_submit_sheet()
        local_sheet.approve_sheet()

        # -----------------------------------------------------------------
        # PHASE 2: TRIGGER DYNAMIC EXTERNAL ANALYTIC SERVER ACCOUNTING VIA N8N
        # -----------------------------------------------------------------
        # Fetch the original pre-approval document dynamically to extract its Job IDs & Codes
        source_record = self.env[self.source_model].browse(self.source_res_id)
        
        # Safely extract codes even if the fields don't exist on future request types
        job_code = getattr(source_record.job_id, 'job_no', 'GENERAL_OVERHEAD')
        budget_code = getattr(source_record, 'budget_code', 'NO_CODE')

        # 🚀 DYNAMIC LOOKUP: Fetch the n8n analytic URL straight from Odoo system parameters
        icp = self.env['ir.config_parameter'].sudo()
        n8n_analytic_webhook_url = icp.get_param('kderp_e_approval.n8n_analytic_webhook_url')

        if not n8n_analytic_webhook_url:
            raise UserError(_(
                "⚙️ Configuration Missing!\n\n"
                "The 'n8n Analytic Webhook URL' has not been defined yet.\n"
                "Please navigate to E-Approvals ➔ Configuration ➔ System Parameter Settings to initialize it."
            ))

        # Build the exact financial payload your external central accounting ledger demands
        financial_payload = {
            "settlement_reference": self.name,
            "origin_document": self.source_document_ref,
            "claimant_employee": self.applicant_id.name,
            "date_cleared": str(self.date_settlement),
            "amount_vnd": self.actual_invoice_amount,
            "target_analytic_account": job_code,       # Map Job No straight to central analytic account code!
            "budget_dimension_code": budget_code,      # Pass your dynamic budget code
            "source_application_model": self.source_model
        }

        try:
            # Dispatch the payload to n8n with a firm timeout safety gate
            response = requests.post(n8n_analytic_webhook_url, json=financial_payload, timeout=15)
            if response.status_code not in [200]:
                raise UserError(_("External analytic server rejected data. Code: %s") % response.status_code)
        except Exception as e:
            raise UserError(_("⚠️ Local records saved, but External Analytic Sync failed!\nLink to n8n timed out. Details: %s") % str(e))

        # -----------------------------------------------------------------
        # PHASE 3: FINAL WORKSPACE CLOSURE
        # -----------------------------------------------------------------
        # Write the state and update the lookup references
        self.write({
            'state': 'paid',
            'hr_expense_sheet_id': local_sheet.id
        })

        # Post an audit trace to the timeline chatter feed box
        self.message_post(body=_(
            "🔒 Financial Closeout Complete:\n"
            "- Local HR Expense Sheet generated reference: <b>%s</b>\n"
            "- Analytic dimensions pushed to central cloud server for Account Code: <b>%s</b>."
        ) % (local_sheet.name, job_code))

        return True