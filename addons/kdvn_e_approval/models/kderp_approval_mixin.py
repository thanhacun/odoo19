from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html_escape, html2plaintext

from . import approval_notify_render as render

import base64
import hmac
import hashlib
import io
from urllib.parse import urlencode as url_encode
import requests
import logging
import re
from PIL import Image, ImageDraw, ImageFont

_logger = logging.getLogger(__name__)

SPECIAL_CASE_LEVELS = [
    ('normal', 'Normal'),
    ('special', 'Special case'),
    ('blocked', 'Blocked'),
]

# Fallback check for report image compilation requirements
try:
    import qrcode
except ImportError:
    qrcode = False

try:
    import barcode
    from barcode.writer import ImageWriter
except ImportError:
    barcode = False
    ImageWriter = False

class IrSequence(models.Model):
    _inherit = 'ir.sequence'

    @api.model
    def search(self, domain, offset=0, limit=None, order=None, **kwargs):   # Odoo 19: no `count` argument any more (search_count)
        """
        🚀 DYNAMIC SEQUENCE INJECTION:
        Intercepts the search window request if our custom context flag is passed,
        ensuring every model using our mixin is dynamically loaded.
        """
        if self.env.context.get('search_mixin_sequences_only'):
            mixin_models = []
            for model_name, model_instance in self.env.items():
                # If the model inherits our custom universal state changer method, track it!
                if hasattr(model_instance, '_universal_state_changer'):
                    mixin_models.append(model_name)

            if not mixin_models:
                mixin_models = ['entertainment.request']

            domain = list(domain) + [('code', 'in', mixin_models)]
            
        return super(IrSequence, self).search(domain, offset=offset, limit=limit, order=order, **kwargs)



class KderpApprovalMixin(models.AbstractModel):
    _name = "kderp.e.approval.mixin"
    _inherit = ['tier.validation']
    _description = "Universal Shared E-Approval Workflow Engine"

    # OCA tier.validation state attributes. tier.validation defines its own defaults
    # (['draft'], ['confirmed'], 'cancel'), so they must be set here for the mixin's
    # state names. Override in a model only if it uses different states.
    _state_from = ['submitted']
    _state_to = ['approved']
    _cancel_state = 'rejected'
    _submitted_state = 'submitted'
    _default_approval_report_xml_id = False
    # List of fields allow to write during the locked-out phase of reviewing. Override to add more fields to this value
    _allow_to_write_field_list = ['attachment_ids', 'approval_progress', 'approval_workflow_ribbon', 'is_gm', 'validate_comments', 'refuse_comments',
                                  'special_case', 'special_reasons']
    # THE STATIC CONFIGURATION LAYERS (Override to fit with the model)
    _approval_category = 'other'
    _approval_procedure_title = 'Other Request'
    # Override to add more categories
    _APPROVAL_CATEGORY_MAP = {
        'entertainment': 'Entertainment & Expense',
        'attendance': 'Attendance & Leave',
        'hr': 'Human Resources & Transfers',
        'procurement': 'Procurement & Logistics',
        'it': 'IT Systems & Access',
        'finance': 'Finance & Accounting Operations',
        'other': 'Other Procedures'
    }
    # list of groups allowing to super admin the request model (in addition to the global admin)
    _admin_groups = []
    # Field the applicant must fill in when the request is a special case (e.g. 'reason'),
    # checked at submit. False = no explanation needed.
    _special_case_explain_field = False
    # The real number is taken in create(). A default would consume a number every
    # time someone opens a new form, even if they discard it.
    name = fields.Char("Request Number", size=16, readonly=True, required=True, states={'draft': [('readonly', False)]},
                           default=lambda self: _('New'), copy=False)
    reason = fields.Char(string="Reason / Core Purpose", required=True, states={'draft': [('readonly', False)]}, readonly=True)
    # Centralized Matrix Group Configuration Category Target Labels
    approval_category = fields.Selection([(key, value) for key, value in _APPROVAL_CATEGORY_MAP.items()], string="Approval Category Group", store=True,
                        default=lambda self: getattr(self, '_approval_category', 'other'), required=True)
    approval_procedure_title = fields.Char(string="Procedure Action Title", default=lambda self: self._approval_procedure_title)
    # The applicant is always the employee of the user who creates the request: read-only,
    # filled from the default (form) and again in create() (readonly fields aren't sent).
    # Odoo 12 OCA tier.validation had the booleans `validated` and `rejected`; OCA 19.0 only has `validation_status`. Same meaning, kept for our code and views.
    validated = fields.Boolean(compute='_compute_validated_rejected')
    rejected = fields.Boolean(compute='_compute_validated_rejected')

    @api.depends('validation_status')
    def _compute_validated_rejected(self):
        for record in self:
            record.validated = record.validation_status == 'validated'
            record.rejected = record.validation_status == 'rejected'

    employee_id = fields.Many2one('hr.employee', string='Applicant', required=True, readonly=True,
                                  default=lambda self: self._default_applicant())
    # Native attachment counter link (relational shortcut)
    # No relation/column names here: Odoo builds one table per model
    # (e.g. staff_transfer_ir_attachment_rel). A model that already has data in an
    # older table redefines this field with that table name (see entertainment.request).
    attachment_ids = fields.Many2many('ir.attachment', string="Supporting Attachments")

    # Simplified Text-Only Progress field (For List View tracking columns)
    approval_progress = fields.Char(compute='_compute_approval_progress', string='Approval Progress', store=True)
    # The visual HTML tracking block definition field
    approval_workflow_ribbon = fields.Html(compute='_compute_approval_workflow_ribbon', string='Workflow Progress Ribbon', sanitize=False)

    verification_token = fields.Char(compute='_compute_verification_url', string='HMAC Verification Token')
    verification_url = fields.Char(compute='_compute_verification_url', string='Secure Verification URL')
    is_emergency = fields.Boolean(default=False, tracking=True)
    is_gm = fields.Boolean(string='Is GM', readonly=True, compute='_compute_is_gm', store=True)
    is_current_applicant = fields.Boolean(compute='_compute_is_current_applicant', string="Is Current Logged-in User the Applicant?")

    state = fields.Selection([
            ('draft', 'Draft'),
            ('submitted', 'Awaiting Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected')
        ], string='Document State', default='draft', tracking=True)

    validate_comments = fields.Text(compute='_compute_validate_refuse_comments', store=True)
    refuse_comments = fields.Text(compute='_compute_validate_refuse_comments', store=True)

    # Special cases. A procedure implements _get_special_case_reasons(); thresholds come from
    # kderp.e.approval.special.rule. Checked live while the request is a draft (banner) and
    # frozen at each submit in special_case / special_reasons, which approval-rule conditions
    # can use, e.g. rec.special_case == 'special'.
    special_case = fields.Selection(SPECIAL_CASE_LEVELS, string='Special Case', default='normal', readonly=True,
                                    copy=False, index=True, tracking=True)
    special_reasons = fields.Text(string='Special Case Reasons', readonly=True, copy=False)
    special_case_live = fields.Selection(SPECIAL_CASE_LEVELS, string='Special Case (live)',
                                         compute='_compute_special_case_live')
    special_case_banner = fields.Html(string='Special Case Banner', compute='_compute_special_case_live',
                                      sanitize=False)

    @api.depends('name', 'reason')
    def _compute_display_name(self):
        """
            General display name of a request: "name - reason".
            Override if needed (Odoo 12: name_get)
        """
        for record in self:
            elements = [record.name, record.reason]
            record.display_name = ' - '.join(str(el).strip() for el in elements if el)

    @api.model
    def _get_dynamic_next_sequence(self):
        return self.env['ir.sequence'].next_by_code(self._name) or None

    def _adopt_attachments(self):
        """Make files uploaded through the many2many widget belong to their request
        (res_model/res_id), so the request's access rules protect them and they
        also show in the chatter."""
        for rec in self:
            orphans = rec.attachment_ids.filtered(lambda a: not a.res_id)
            if orphans:
                orphans.sudo().write({'res_model': rec._name, 'res_id': rec.id})

    @api.model
    def _default_applicant(self):
        """Employee of the current user (active employees only), or an empty recordset."""
        return self.env.user.employee_ids[:1]

    @api.model_create_multi
    def create(self, vals_list):
        placeholders = (False, None, '', '/', 'New', _('New'))
        for vals in vals_list:
            if not vals.get('employee_id'):
                applicant = self._default_applicant()
                if not applicant:
                    raise UserError(_("Your user %s is not linked to an employee, so you cannot create "
                                      "this request. Please ask HR to link your user to your employee "
                                      "record.") % self.env.user.name)
                vals['employee_id'] = applicant.id
            if vals.get('name') in placeholders:
                vals['name'] = self._get_dynamic_next_sequence() or _('New')
        records = super(KderpApprovalMixin, self).create(vals_list)
        records._adopt_attachments()
        return records

    def write(self, vals):
        state_field = getattr(self, '_state_field', 'state')
        if vals.get(state_field) in self._state_from:
            # Going back to draft (or to a state that restarts the validation) deletes the reviews, and with them the refusal
            # comments: keep them first. Only a request that is refused now is concerned.
            reject_state = self._get_validation_target_states()[1]
            self.filtered(lambda r: r[state_field] == reject_state)._refusal_mark_reset(vals[state_field])
        res = super(KderpApprovalMixin, self).write(vals)
        if 'attachment_ids' in vals:
            self._adopt_attachments()         # here self already is the recordset
        return res

    def unlink(self):
        ids = self.ids
        res = super(KderpApprovalMixin, self).unlink()
        self.env['kderp.approval.refusal'].sudo().search([('res_model', '=', self._name), ('res_id', 'in', ids)]).unlink()
        return res

    # -------------------------------------------------------------------------
    # REFUSAL LOG: the refusal comment stays as a reminder after the reset to draft
    # -------------------------------------------------------------------------
    def _refusal_vals(self, review):
        self.ensure_one()
        return {
            'res_model': self._name, 'res_id': self.id, 'record_name': self.display_name, 'procedure': self._description or self._name,
            'review_id': review.id, 'step': review.definition_id.frontend_name or review.name or '',
            'refused_by_id': review.done_by.id, 'refused_by_name': review.done_by.name or False, 'refused_date': review.reviewed_date or fields.Datetime.now(),
            'comment': review.comment or False,
        }

    def _refusal_log(self, reviews=None):
        """Copy the refused reviews of each request to the refusal log (once per review)."""
        Log = self.env['kderp.approval.refusal'].sudo()
        for record in self:
            refused = (reviews or record.review_ids).filtered(lambda r: r.status == 'rejected' and r.res_id == record.id)
            known = set(Log.search([('res_model', '=', record._name), ('res_id', '=', record.id)]).mapped('review_id'))
            for review in refused:
                if review.id not in known:
                    Log.create(record._refusal_vals(review))

    def _refusal_mark_reset(self, target_state):
        """The request leaves the refused state: complete the log, and say it in the chatter (short)."""
        Log = self.env['kderp.approval.refusal'].sudo()
        labels = dict(self._fields[getattr(self, '_state_field', 'state')]._description_selection(self.env))
        reject_state = self._get_validation_target_states()[1]
        for record in self:
            record._refusal_log()                # a refusal made before this log existed is still captured here
            rows = Log.search([('res_model', '=', record._name), ('res_id', '=', record.id), ('state', '=', 'refused')])
            if not rows:
                continue
            rows.write({'state': 'reset', 'reset_by_id': self.env.uid, 'reset_date': fields.Datetime.now(), 'reset_to': labels.get(target_state, target_state)})
            who = '; '.join('<b>%s</b>: &ldquo;%s&rdquo;' % (html_escape(r.refused_by_id.name or r.refused_by_name or '?'), html_escape(r.comment or _('no comment'))) for r in rows)
            record.message_post(body=_("Reset to <b>%(to)s</b> from <b>%(frm)s</b>. Refused by %(who)s") % {
                'to': html_escape(labels.get(target_state, target_state)), 'frm': html_escape(labels.get(reject_state, reject_state)), 'who': who})

    def _refusal_ribbon_note(self):
        """Note under the ribbon after a reset: who refused, the comment, who reset it. Empty when it does not apply."""
        self.ensure_one()
        if not isinstance(self.id, int):
            return ''
        approve_state = self._get_validation_target_states()[0]
        if self[getattr(self, '_state_field', 'state')] == approve_state:
            return ''
        rows = self.env['kderp.approval.refusal'].sudo().search([('res_model', '=', self._name), ('res_id', '=', self.id)])
        last = rows[:1]
        if not last or last.state != 'reset':
            return ''
        short = lambda v: self._ribbon_format_date(v)[1]
        who = last.refused_by_id.name or last.refused_by_name or '?'
        text = _('Refused by %(who)s on %(when)s.') % {'who': who, 'when': short(last.refused_date)}
        text += ' ' + (_('Reset to %(to)s by %(by)s on %(rwhen)s.') % {
            'to': last.reset_to or _('Draft'), 'by': last.reset_by_id.name or '?', 'rwhen': short(last.reset_date)}
            if last.reset_by_id and last.reset_date else _('Reset to %s.') % (last.reset_to or _('Draft')))
        more = _(' (+%d more)') % (len(rows) - 1) if len(rows) > 1 else ''
        return ('<div class="o_kderp_flow_note o_kderp_flow_note--history"><strong>%s %s%s</strong><span>%s</span></div>' % (
            self._ribbon_icon('fa-history'), html_escape(_('Refused earlier')), html_escape(more),
            html_escape(last.comment or _('No comment provided.')) + '<br/><small>%s</small>' % html_escape(text)))

    def _get_validation_target_states(self):
        """
        📋 HELPER METHOD:
        Extracts and returns the exact approved and rejected string names 
        for the current model configuration at runtime.
        """
        # 1. Resolve Reject/Cancel State string
        reject_state = getattr(self, '_cancel_state', 'rejected')

        # 2. Resolve Approve/Terminal State string from _state_to
        approve_state = getattr(self, '_state_to', ['approved'])[-1]

        return approve_state, reject_state

    def get_approval_digest_details(self):
        """
        Every request model overrides this method to return context-rich HTML detail blocks.
        """
        self.ensure_one()
        return html_escape(self.reason) if self.reason else "No explicit detail layout defined."

    @api.depends('review_ids','review_ids.status', 'employee_id')
    def _compute_is_gm(self):
        for record in self:
            applicant = record.employee_id.user_id or record.create_uid
            record.is_gm = applicant.has_group('kderp_hr_attendance.group_hr_attendance_gm')

    def _compute_is_current_applicant(self):
        for record in self:
            # Assuming employee_id points to an 'hr.employee' record which has a 'user_id' field
            if record.employee_id and record.employee_id.user_id:
                record.is_current_applicant = (record.employee_id.user_id.id == self.env.uid)
            else:
                # Fallback to create_uid if no employee user link exists
                record.is_current_applicant = (record.create_uid.id == self.env.uid)

    @api.depends('review_ids', 'review_ids.status', 'review_ids.comment')
    def _compute_validate_refuse_comments(self):
        """
            Generate reviewers validate/refuse comments
        """
        for record in self:
            validate_comments = False
            refuse_comments = False
            if record.review_ids:
                validate_comments = '\n'.join([f'{validate_review.done_by.name}: {validate_review.comment}' for validate_review in record.review_ids.filtered(lambda r: r.status == 'approved' and r.comment)])
                refuse_comments = '\n'.join([f'{refuse_review.done_by.name}: {refuse_review.comment}' for refuse_review in record.review_ids.filtered(lambda r: r.status == 'rejected' and r.comment)])
            record.validate_comments = validate_comments
            record.refuse_comments = refuse_comments
    
    @api.model
    def _get_under_validation_exceptions(self):
        """Override to add allow to write fields during validation"""
        res = super(KderpApprovalMixin, self)._get_under_validation_exceptions()
        # 1. Loop through all classes in the model's Method Resolution Order (inheritance tree)
        # Using AI to get these lines of code
        combined_custom_fields = []
        for cls in self.__class__.__mro__:
            # 2. Safely get the list from each specific class level (preventing inheritance duplication)
            class_list = cls.__dict__.get('_allow_to_write_field_list', [])
            if isinstance(class_list, list):
                combined_custom_fields.extend(class_list)
        res += [f for f in combined_custom_fields if f not in res]
        return res

    def _validate_tier(self, tiers=False):
        """
        HOOK: Runs when ANY manager approves.
        - Executes native base validation.
        - Look-Ahead Engine: Automatically bypasses consecutive steps assigned 
          exclusively to the same approving user.
        - Handles universal state changes and notifications.
        """
        approved_before = {rec.id: set(rec.review_ids.filtered(lambda r: r.status == 'approved').ids) for rec in self}
        super(KderpApprovalMixin, self)._validate_tier(tiers=tiers)
        current_user = self.env.user

        for record in self:
            _logger.info("🔄 Approval step processed. Evaluating next sequence step for %s", record.name)

            # -------------------------------------------------------------------------
            # CONSECUTIVE LOOK-AHEAD BYPASS ENGINE (Workflow Progression Safe)
            # -------------------------------------------------------------------------
            while True:
                # Force-clear the record's relation cache memory to see live database statuses
                # record.invalidate_cache(['review_ids', 'validated'], [record.id])
                # If the entire document is fully validated, stop the bypass loop immediately
                if record.validated:
                    break
                # Gather remaining reviews that are not approved yet
                remaining_reviews = record.review_ids.filtered(lambda r: r.status != 'approved')
                if not remaining_reviews:
                    break
                # Identify the absolute next sequential tier layer
                next_sequence = min(remaining_reviews.mapped('sequence'))
                next_active_tiers = remaining_reviews.filtered(lambda r: r.sequence == next_sequence)

                tiers_to_bypass = self.env['tier.review']
                for tier in next_active_tiers:
                    # Condition: Current user is the sole, explicit reviewer assigned to this next tier step
                    if tier.reviewer_ids and len(tier.reviewer_ids) == 1 and tier.reviewer_ids.id == current_user.id:
                        tiers_to_bypass |= tier

                if tiers_to_bypass:
                    _logger.info(
                        "🚀 CONSECUTIVE BYPASS: Auto-validating steps %s (Seq: %s) for user '%s' on %s",
                        tiers_to_bypass.mapped('name'), next_sequence, current_user.name, record.name
                    )
                    
                    # 1. Update the bypass tier rows to 'approved' using native logic
                    super(KderpApprovalMixin, record)._validate_tier(tiers=tiers_to_bypass)
                    
                    # 2. CRITICAL CORE FIX: Force the base framework to calculate the NEXT sequential step.
                    # This moves the next manager's review line from 'draft' to 'pending' in the database,
                    # recalculates security visibility fields, and fires native Odoo notifications to them.
                    if hasattr(record, '_update_tier_validation_history'):
                        record._update_tier_validation_history()
                else:
                    # Next sequence layer belongs to a different manager; hand over execution control
                    break

            # -------------------------------------------------------------------------
            # FINAL WORKFLOW STATE EVALUATION & NEXT REVIEWER EVALUATION
            # -------------------------------------------------------------------------
            # Re-verify live validation status now that the bypass loops have completed
            record.invalidate_recordset(['validated'])
            approve_state_name, reject_state_name = self._get_validation_target_states()

            if record.validated:
                # Document has finalized all signatures! Move state to approved.
                _logger.info("🎯 E-Approval Complete: All tiers approved for %s. Changing state.", record.name)
                record._universal_state_changer(approve_state_name)
                record._notify_applicant('approved')
            else:
                # The document is still under active review. Find and notify the next reviewer.
                pending_lines = record.review_ids.filtered(lambda r: r.status == 'pending' and not r.done_by)
                if pending_lines:
                    next_sequence = min(pending_lines.mapped('sequence'))
                    _logger.info("🚀 Advancing sequence order: Task handed to Sequence Layer %s", next_sequence)
                    
                    # Tell the next reviewers (Talk instantly, or email for email-only users)
                    record._notify_reviewers(pending_lines, event='arrived')
                # Tell the applicant which step(s) were just approved (Talk only)
                newly_approved = record.review_ids.filtered(
                    lambda r: r.status == 'approved' and r.id not in approved_before.get(record.id, set()))
                if newly_approved:
                    record._notify_applicant('step', newly_approved)

    def reject_tier(self):
        """
        Signature-safe rejection route handler.
        Always forces comment validation: 
        - Natively writes comment if passed through remote context string.
        - Falls back to the standard UI popup modal if triggered in-app.
        """
        self.ensure_one()
        
        # 1. Replicate native sequence target lookup logic
        sequences = self._get_sequences_to_approve(self.env.user)
        reviews = self.review_ids.filtered(lambda l: l.sequence in sequences)
        
        if not reviews:
            raise UserError(_("No pending validation tier found for your user identity session."))

        # 2. Extract remote context string passed down from your n8n workflow route
        remote_comment = self.env.context.get('remote_rejection_comment')

        # -------------------------------------------------------------------------
        # PATH A: Headless API Entry Point (n8n Form Submission)
        # -------------------------------------------------------------------------
        if remote_comment is not None:
            # Replicate the core internal operations of 'CommentWizard.add_comment()' exactly:
            reviews.write({"comment": remote_comment})
            self._rejected_tier(reviews)
            self._update_counter()
            return True

        # -------------------------------------------------------------------------
        # PATH B: Standard Odoo UI Desktop Entry Point
        # -------------------------------------------------------------------------
        # We completely bypass the original 'if self.has_comment' condition tracking block.
        # This makes the validation wizard absolute and strictly mandatory for ANY desktop UI rejection!
        return self._add_comment("reject", reviews)

    def _rejected_tier(self, tiers=False):
        """
        HOOK: Runs when any manager rejects a step.
        Halts the system state immediately.
        """
        super(KderpApprovalMixin, self)._rejected_tier(tiers=tiers)
        for record in self:
            if record.rejected:
                _logger.warning("❌ Rejection triggered on document model. Halting workflow for %s", record.name)
                approve_state_name, reject_state_name = self._get_validation_target_states()
                record._universal_state_changer(reject_state_name)
                record._refusal_log(tiers)
                record._notify_applicant('rejected', tiers or record.review_ids.filtered(lambda r: r.status == 'rejected'))

    def _universal_state_changer(self, target_state):
        for record in self:
            state_field = getattr(self, '_state_field', 'state')
            if hasattr(record, state_field) and getattr(record, state_field) != target_state:
                record.write({state_field: target_state})

    def action_view_tier_reviews_modal(self):
        """
        Pops open a clean utility modal subview window isolating 
        the target approval metrics and timestamps instantly.
        """
        self.ensure_one()
        return {
            'name': _('Approval Execution History Track'),
            'type': 'ir.actions.act_window',
            'res_model': 'tier.review',
            'view_mode': 'list',
            'domain': [('res_id', '=', self.id), ('model', '=', self._name)],
            'target': 'new', # Spawns gracefully inside a modal viewport overlay
            'context': self.env.context,
        }

    # -------------------------------------------------------------------------
    # NOTIFICATIONS
    #   Nextcloud Talk = instant: one short message per event.
    #   Email          = daily digest, plus the final result of your own request.
    #   People who chose "Email" only also get an email the moment a request
    #   reaches their step. "Both" = instant Talk + daily email (no duplicates).
    #   Look and wording: approval_notify_render.py
    # -------------------------------------------------------------------------
    _NOTIFY_MAX_ATTACH_BYTES = 15 * 1024 * 1024

    @api.model
    def _notify_config(self):
        get = self.env['ir.config_parameter'].sudo().get_param
        return {
            'base_url': (get('web.base.url') or '').rstrip('/'),
            'n8n_domain': (get('kderp_e_approval.n8n_server_url', 'https://kinden.com.vn') or '').rstrip('/'),
            'webhook_path': get('kderp_e_approval.e_approval_email_webhook_path', '') or '',
            'short_path': (get('kderp_e_approval.short_link_webhook_path', '') or '').strip('/'),
            'secret': get('kderp_e_approval.e_approval_secret_key', False),
            'email_on': get('kderp_e_approval.global_notify_email', 'True') == 'True',
            'talk_on': get('kderp_e_approval.global_notify_talk', 'False') == 'True',
            'nc_url': (get('kderp_e_approval.nc_base_url', '') or '').rstrip('/'),
            'nc_user': get('kderp_e_approval.nc_bot_username', '') or '',
            'nc_pass': get('kderp_e_approval.nc_bot_password', '') or '',
            'rooms': {},  # Talk room tokens already looked up in this run
        }

    @api.model
    def _notify_channels(self, user, cfg, event, email=None):
        """Return (send_email, send_talk) for one person and one event.
        event: 'arrived' (a request reached their step), 'digest' (daily list),
               'step' (their own request moved on), 'result' (final outcome)."""
        email = user.email if email is None else email
        pref = user.approval_notify_type or 'email'
        can_talk = bool(cfg['talk_on'] and cfg['nc_url'] and cfg['nc_user'] and cfg['nc_pass'] and user.login)
        can_email = bool(cfg['email_on'] and email)
        # If the chosen channel is switched off, use the one that works
        if pref in ('talk', 'both') and not can_talk:
            pref = 'email'
        if pref == 'email' and not can_email and can_talk:
            pref = 'talk'
        talk = can_talk and pref in ('talk', 'both')
        if event == 'arrived':
            # No instant email: email-only reviewers get the daily digest instead
            return False, talk
        if event == 'digest':
            return can_email and pref in ('email', 'both'), can_talk and pref == 'talk'
        if event == 'step':
            return False, talk
        return can_email and pref in ('email', 'both'), talk  # 'result'

    @api.model
    def _notify_front_reviews(self, reviews):
        """Keep only the lowest pending tier of each request that is still in review."""
        result = self.env['tier.review'].sudo()
        by_record = {}
        for review in reviews.sudo():
            key = (review.model, review.res_id)
            by_record[key] = by_record.get(key, result.browse()) | review
        for (model, res_id), lines in by_record.items():
            record = self.env[model].sudo().browse(res_id)
            if not record.exists() or record.state == getattr(record, '_cancel_state', 'rejected'):
                continue
            pending = lines.filtered(lambda r: r.status == 'pending' and not r.done_by)
            if pending:
                lowest = min(pending.mapped('sequence'))
                result |= pending.filtered(lambda r: r.sequence == lowest)
        return result

    def _notify_item(self, review, user, cfg, attach_budget=None):
        """What the templates need to show one request to one reviewer.
        attach_budget: {'left': bytes, 'ids': []} shared by one email, or None."""
        self.ensure_one()
        token_source = "%s-%s-%s-%s" % (self._name, self.id, review.id, user.id)
        token = hmac.new(cfg['secret'].encode('utf-8'), token_source.encode('utf-8'), hashlib.sha256).hexdigest()
        query = "res_model=%s&res_id=%s&review_id=%s&user_id=%s&token=%s" % (
            self._name, self.id, review.id, user.id, token)
        hook = "%s/webhook/%s?" % (cfg['n8n_domain'], cfg['webhook_path'])
        if cfg['short_path']:
            # Short links: https://n8n/webhook/<short_path>?c=<review>-<user>-<a|r>-<signature>
            short = "%s/webhook/%s?c=" % (cfg['n8n_domain'], cfg['short_path'])
            approve_url = short + self._short_link_code(review.id, user.id, 'approve', cfg['secret'])
            reject_url = short + self._short_link_code(review.id, user.id, 'reject', cfg['secret'])
        else:
            approve_url = hook + 'action=approve&' + query
            reject_url = hook + 'action=reject&' + query

        attached, linked = [], []
        for att in self.attachment_ids:
            size = att.file_size or 0
            if attach_budget is not None and size <= attach_budget['left']:
                attach_budget['left'] -= size
                attach_budget['ids'].append(att.id)
                attached.append(att.name or '')
            else:
                linked.append((att.name or '', "%s/web/content/%s?download=true" % (cfg['base_url'], att.id)))

        details_html = self.get_approval_digest_details() or ''
        category_map = getattr(self, '_APPROVAL_CATEGORY_MAP', {})
        return {
            'ref': self.name or '',
            'title': self.approval_procedure_title or getattr(self, '_approval_procedure_title', '') or self._description,
            'category': category_map.get(self.approval_category, 'Other'),
            'applicant': self.employee_id.name or self.create_uid.name or '',
            'step_label': review.definition_id.frontend_name or review.name or '',
            'step_no': review.sequence,
            'step_total': max(self.review_ids.mapped('sequence') or [0]),
            'details_html': str(details_html),
            'details_text': html2plaintext(str(details_html)) if details_html else '',
            'emergency': bool(self.is_emergency),
            'special': [line for line in (self.special_reasons or '').splitlines() if line.strip()]
                       if self.special_case == 'special' else [],
            'odoo_url': "%s/web#id=%s&model=%s&view_type=form" % (cfg['base_url'], self.id, self._name),
            'approve_url': approve_url,
            'reject_url': reject_url,
            'files_attached': attached,
            'files_linked': linked,
        }

    # Short approve/reject links -------------------------------------------
    # Code format: <review_id>-<user_id>-<a|r>-<24 hex chars of HMAC-SHA256>.
    # Self-contained: nothing is stored; the signature is checked again in
    # /api/v1/mobile_review_action, which finds model and record from the review.
    _SHORT_SIG_LEN = 24

    @api.model
    def _short_link_code(self, review_id, user_id, action, secret):
        act = 'a' if action == 'approve' else 'r'
        payload = "short:%s-%s-%s" % (review_id, user_id, act)
        sig = hmac.new(secret.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
        return "%s-%s-%s-%s" % (review_id, user_id, act, sig[:self._SHORT_SIG_LEN])

    @api.model
    def _short_link_parse(self, code):
        """Return {'review': tier.review, 'user_id': int, 'action': str}, or None if the code is invalid."""
        secret = self.env['ir.config_parameter'].sudo().get_param('kderp_e_approval.e_approval_secret_key')
        try:
            review_id, user_id, act, sig = (code or '').strip().split('-')
            review_id, user_id = int(review_id), int(user_id)
        except ValueError:
            return None
        if not secret or act not in ('a', 'r'):
            return None
        expected = self._short_link_code(review_id, user_id, 'approve' if act == 'a' else 'reject', secret)
        if not hmac.compare_digest(expected, code.strip()):
            return None
        review = self.env['tier.review'].sudo().browse(review_id)
        if not review.exists():
            return None
        return {'review': review, 'user_id': user_id, 'action': 'approve' if act == 'a' else 'reject'}

    @api.model
    def _notify_reviewers(self, reviews, event='arrived'):
        """Tell the reviewers of the lowest pending tier.
        event 'arrived': right after submit or after the previous tier approved (Talk only, no email).
        event 'digest': the daily cron."""
        cfg = self._notify_config()
        if not cfg['secret']:
            # Never sign approve/reject links with a missing key
            _logger.error("E-Approval notifications not sent: 'e_approval_secret_key' is not configured.")
            return False
        front = self._notify_front_reviews(reviews)
        for user in front.mapped('reviewer_ids'):
            try:
                with self.env.cr.savepoint():
                    self._notify_one_reviewer(user, front, cfg, event)
            except Exception:
                # One bad user or record must not stop everybody else's notification
                _logger.exception("E-Approval notification to %s failed (event %s)", user.login, event)
        return True

    def _notify_one_reviewer(self, user, front, cfg, event):
        send_email, send_talk = self._notify_channels(user, cfg, event)
        if not (send_email or send_talk):
            return
        budget = {'left': self._NOTIFY_MAX_ATTACH_BYTES, 'ids': []} if send_email else None
        items = []
        for review in front.filtered(lambda r: user in r.reviewer_ids).sorted(lambda r: (r.model, r.res_id)):
            record = self.env[review.model].sudo().browse(review.res_id)
            items.append(record._notify_item(review, user, cfg, budget))
        if not items:
            return
        if send_email:
            subject, body = render.reviewer_email(user.name, items, digest=(event == 'digest'))
            self._notify_send_email(user.email, subject, body, budget['ids'])
        if send_talk:
            if event == 'digest':
                self._notify_send_talk(user, render.talk_reminder(items), cfg)
            else:
                for item in items:
                    self._notify_send_talk(user, render.talk_request(item), cfg)

    def _notify_applicant(self, event, reviews=None):
        """Tell the applicant about their own request.
        event: 'step' (some steps approved, more to go), 'approved' or 'rejected'."""
        self.ensure_one()
        cfg = self._notify_config()
        user = self.employee_id.user_id or self.create_uid
        email = self.employee_id.work_email or self.create_uid.email
        send_email, send_talk = self._notify_channels(
            user, cfg, 'step' if event == 'step' else 'result', email=email)
        if not (send_email or send_talk):
            return False

        reviews = reviews or self.env['tier.review']
        ref = self.name or ''
        odoo_url = "%s/web#id=%s&model=%s&view_type=form" % (cfg['base_url'], self.id, self._name)
        title = self.approval_procedure_title or self._description
        subject_text = self.reason or ''
        total = max(self.review_ids.mapped('sequence') or [0])

        if event == 'step':
            done = reviews.sorted(key=lambda r: r.sequence)
            steps = ' + '.join(r.definition_id.frontend_name or r.name or '' for r in done)
            approvers = ', '.join(sorted(set(n for n in done.mapped('done_by.name') if n)))
            nxt = self.review_ids.filtered(lambda r: r.status == 'pending').sorted(key=lambda r: r.sequence)[:1]
            message = render.talk_applicant_step(
                ref, steps, approvers,
                (nxt.definition_id.frontend_name or nxt.name) if nxt else '',
                nxt.sequence if nxt else '', total, odoo_url)
            return self._notify_send_talk(user, message, cfg)

        comment = ''
        if event == 'rejected':
            decisive = (reviews.filtered(lambda r: r.status == 'rejected')
                        or self.review_ids.filtered(lambda r: r.status == 'rejected'))[:1]
            comment = decisive.comment or ''
        else:
            decisive = self.review_ids.filtered(lambda r: r.status == 'approved').sorted(key=lambda r: r.sequence)[-1:]
        decided_by = decisive.done_by.name or ''

        if send_email:
            amount = ''
            if 'estimated_amount' in self._fields and self.estimated_amount:
                amount = '{:,.0f} VND'.format(self.estimated_amount)
            subject, body = render.applicant_email(
                self.employee_id.name or self.create_uid.name, event, ref, title, subject_text,
                odoo_url, amount, decided_by, comment)
            self._notify_send_email(email, subject, body, auto_delete=True)
        if send_talk:
            self._notify_send_talk(
                user, render.talk_applicant_result(ref, event, subject_text, odoo_url, decided_by, comment), cfg)
        return True

    @api.model
    def _notify_send_email(self, email_to, subject, body_html, attachment_ids=None, auto_delete=False):
        # Drop default_* keys: a wizard's context would otherwise set fields on the mail
        context = {k: v for k, v in self.env.context.items()
                   if not k.startswith('default_') and k not in ('active_id', 'active_ids', 'active_model')}
        values = {'subject': subject, 'body_html': body_html, 'email_to': email_to, 'auto_delete': auto_delete}
        if attachment_ids:
            values['attachment_ids'] = [(6, 0, list(set(attachment_ids)))]
        self.env['mail.mail'].sudo().with_context(context).create(values).send()

    @api.model
    def _notify_send_talk(self, user, message, cfg):
        login = (user.login or '').split('@')[0]
        if not login:
            return False
        if login not in cfg['rooms']:
            cfg['rooms'][login] = self._get_or_create_nextcloud_room_token(
                cfg['nc_url'], cfg['nc_user'], cfg['nc_pass'], login)
        token = cfg['rooms'][login]
        if not token:
            return False
        try:
            requests.post(
                "%s/ocs/v1.php/apps/spreed/api/v1/chat/%s" % (cfg['nc_url'], token),
                auth=(cfg['nc_user'], cfg['nc_pass']),
                headers={"OCS-APIRequest": "true", "Accept": "application/json"},
                data={"message": message},
                timeout=10,
            )
            return True
        except Exception as e:
            _logger.error("Nextcloud Talk message to %s failed: %s", login, e)
            return False

    # Old names, kept so existing callers keep working
    @api.model
    def _send_consolidated_manager_digest_email(self, active_reviews, emergency_record=False):
        return self._notify_reviewers(active_reviews, event='digest')

    def _send_applicant_final_notice_email(self, status_type):
        approve_state_name, reject_state_name = self._get_validation_target_states()
        return self._notify_applicant('approved' if status_type == approve_state_name else 'rejected')

    def _send_mobile_approval_email(self, review):
        """Deliberately does nothing (no per-change emails)."""
        pass

    # -------------------------------------------------------------------------
    # APPROVAL PROGRESS (tree views) AND WORKFLOW RIBBON (form view)
    # -------------------------------------------------------------------------
    # Icons for approval steps. 'current' and 'waiting' have none: they show the
    # tier number (review.sequence), so parallel reviews in one tier share a number.
    _RIBBON_ICONS = {
        'done': 'fa-check',
        'rejected': 'fa-times',
        'skipped': 'fa-minus',
        'current': False,
        'waiting': False,
    }
    # The first and last nodes always keep their own icon and never show a number.
    _RIBBON_DRAFT_ICON = 'fa-pencil'
    _RIBBON_SUBMIT_ICON = 'fa-paper-plane'
    _RIBBON_FINAL_ICON = 'fa-flag-checkered'

    @api.depends('review_ids', 'review_ids.status')
    def _compute_approval_progress(self):
        """Short text for list views, e.g. '2/3' or 'Rejected'. Stored, so lists
        don't rebuild anything when they load."""
        for record in self:
            statuses = record.review_ids.mapped('status')
            if not statuses:
                record.approval_progress = False
            elif 'rejected' in statuses:
                record.approval_progress = _('Rejected')
            else:
                record.approval_progress = '%s/%s' % (statuses.count('approved'), len(statuses))

    def _compute_approval_workflow_ribbon(self):
        variant = self._get_ribbon_variant()
        # Warm the cache in a few batched queries instead of one query per record/review.
        all_reviews = self.mapped('review_ids')
        all_reviews.mapped('definition_id.frontend_name')
        all_reviews.mapped('done_by.name')
        all_reviews.mapped('requested_by.name')
        self.mapped('attachment_ids.name')
        for record in self:
            record.approval_workflow_ribbon = record._render_approval_ribbon(variant)

    def _ribbon_icon(self, name):
        """Font Awesome 4.7 icon. Deliberately no aria-hidden="true": a global
        stylesheet in this database hides every [aria-hidden="true"] element."""
        if not name:
            return ''
        return '<i class="fa %s o_kderp_icon" role="presentation"></i>' % name

    @api.model
    def _get_ribbon_variant(self):
        """Which ribbon layout to render: 'statusbar', 'stepper' or 'compact'.
        The user's own preference wins; 'Company default' falls back to the setting."""
        style = getattr(self.env.user, 'approval_ribbon_style', 'default')
        if not style or style == 'default':
            style = self.env['ir.config_parameter'].sudo().get_param('kderp_e_approval.ribbon_style', default='statusbar')
        return {'statusbar': 'statusbar', 'stepper': 'stepper', 'badge': 'compact'}.get(style, 'statusbar')

    def _ribbon_statusbar_html(self, nodes):
        """Odoo 12 statusbar look: arrow-shaped segments, like the state bar in a
        form header. Like Odoo, items are written in reverse and shown with
        row-reverse, so the arrows overlap correctly."""
        items = []
        for node in reversed(nodes):
            state = node['state']
            icon = self._RIBBON_ICONS.get(state) or node.get('icon')
            if icon:
                prefix = self._ribbon_icon(icon)
            elif node.get('number'):
                prefix = '<span class="o_kderp_sb_num">%s</span>' % html_escape(node['number'])
            else:
                prefix = ''
            when = node.get('when', ('', ''))[1]
            title = ' — '.join(x for x in (node['label'], node.get('who', ''), when) if x)
            items.append('<span class="o_kderp_sb_step is-%s" title="%s"%s>%s%s</span>' % (
                state, html_escape(title), ' aria-current="step"' if state == 'current' else '',
                prefix, html_escape(node['label'])))
        return '<div class="o_kderp_sb">%s</div>' % ''.join(items)

    def _compute_approval_visual_metrics(self):
        """Kept for backward compatibility with any code that still calls it."""
        self._compute_approval_progress()
        self._compute_approval_workflow_ribbon()

    def _ribbon_format_date(self, value):
        """Return (short, full) date text in the user's timezone: the short one fits
        under the step, the full one goes in the tooltip."""
        if not value:
            return ('', '')
        local_dt = fields.Datetime.context_timestamp(self, fields.Datetime.to_datetime(value))
        return (local_dt.strftime('%d/%m/%y'), local_dt.strftime('%d/%m/%Y %H:%M'))

    def _ribbon_step_html(self, state, label, number=None, who='', when=('', ''), line_done=False, icon=None):
        """One step of the ribbon. Every value is escaped here.
        `icon` forces an icon (first/last node); otherwise the state decides,
        and steps without a state icon show `number`."""
        icon = icon or self._RIBBON_ICONS.get(state)
        dot = self._ribbon_icon(icon) if icon else html_escape(number or '')
        meta = ' · '.join(x for x in (who, when[0]) if x)
        title = ' — '.join(x for x in (label, who, when[1]) if x)
        classes = 'o_kderp_step is-%s%s' % (state, ' has-done-line' if line_done else '')
        return (
            '<li class="%s" title="%s">'
            '<span class="o_kderp_step_dot">%s</span>'
            '<span class="o_kderp_step_label">%s</span>'
            '<span class="o_kderp_step_meta">%s</span>'
            '</li>'
        ) % (classes, html_escape(title), dot, html_escape(label), html_escape(meta))

    def _render_approval_ribbon(self, variant='stepper'):
        self.ensure_one()
        reviews = self.review_ids.sorted(key=lambda r: (r.sequence, r.id))
        rejected = reviews.filtered(lambda r: r.status == 'rejected')
        pending = reviews.filtered(lambda r: r.status == 'pending')
        current_sequence = min(pending.mapped('sequence')) if pending and not rejected else None

        # One dict per node, in order
        nodes = []
        if reviews:
            first = reviews[0]
            nodes.append(dict(state='done', label=_('Submitted'), icon=self._RIBBON_SUBMIT_ICON,
                              who=first.requested_by.name or '', when=self._ribbon_format_date(first.create_date)))
        else:
            nodes.append(dict(state='current', label=_('Draft'), icon=self._RIBBON_DRAFT_ICON,
                              who=_('Not submitted yet')))

        for review in reviews:
            node = dict(label=review.definition_id.frontend_name or review.name or _('Review'),
                        number=review.sequence)
            if review.status == 'approved':
                node.update(state='done', who=review.done_by.name or '',
                            when=self._ribbon_format_date(review.reviewed_date))
            elif review.status == 'rejected':
                node.update(state='rejected', who=review.done_by.name or '',
                            when=self._ribbon_format_date(review.reviewed_date))
            elif rejected:
                node.update(state='skipped', who=review.todo_by or '')
            elif review.sequence == current_sequence:
                node.update(state='current', who=_('Waiting: %s') % (review.todo_by or '-'))
            else:
                node.update(state='waiting', who=review.todo_by or '')
            nodes.append(node)

        if not rejected:
            all_done = bool(reviews) and not pending
            nodes.append(dict(state='done' if all_done else 'waiting', label=_('Approved'),
                              icon=self._RIBBON_FINAL_ICON))

        steps_html = []
        previous_state = None
        for node in nodes:
            steps_html.append(self._ribbon_step_html(
                node['state'], node['label'], number=node.get('number'),
                who=node.get('who', ''), when=node.get('when', ('', '')),
                line_done=(previous_state == 'done'), icon=node.get('icon')))
            previous_state = node['state']

        html = ['<div class="o_kderp_flow o_kderp_flow--%s">' % variant]
        if variant == 'statusbar':
            html.append(self._ribbon_statusbar_html(nodes))
        else:
            html += ['<ol class="o_kderp_flow_steps">', ''.join(steps_html), '</ol>']

        if rejected:
            rej = rejected[0]
            html.append(
                '<div class="o_kderp_flow_note">'
                '<strong>%s %s</strong>'
                '<span>%s</span></div>' % (self._ribbon_icon('fa-times-circle'),
                    html_escape(_('Rejected by %s') % (rej.done_by.name or _('Reviewer'))),
                    html_escape(rej.comment or _('No comment provided.'))))

        if not rejected:
            html.append(self._refusal_ribbon_note())

        if self.attachment_ids:
            chips = ''.join(
                '<a class="o_kderp_flow_file" href="/web/content/%s?download=true" target="_blank" title="%s">'
                '%s %s</a>' % (att.id, html_escape(att.name or ''), self._ribbon_icon('fa-paperclip'), html_escape(att.name or ''))
                for att in self.attachment_ids)
            html.append('<div class="o_kderp_flow_files">%s</div>' % chips)

        html.append('</div>')
        return ''.join(html)

    def _compute_matrix_reviewer_ids(self):
        """
        Flattens and permanently caches ALL designated reviewers across 
        all sequence lines using native Odoo 12 Many2many tuple formatting commands.
        """
        for record in self:
            all_reviewers = set()
            
            for review in record.review_ids:
                if review.reviewer_ids:
                    all_reviewers.update(review.reviewer_ids.ids)

            record.matrix_reviewer_ids = [(6, 0, list(all_reviewers))]

    def action_submit(self):
        for record in self:
            # Special cases are decided before the approval rules are applied (their
            # conditions may use special_case), and refuse a blocked request.
            record._special_case_freeze()
            state_field = getattr(self, '_state_field', 'state')
            target_submitted_state = getattr(self, '_submitted_state', 'submitted')
            if hasattr(record, state_field):
                record.write({state_field: target_submitted_state})
            if hasattr(record, 'request_validation'):
                record.request_validation()
                record.invalidate_recordset(['review_ids'])
                # Tell the first tier's reviewers right away
                if record.review_ids:
                    record._notify_reviewers(record.review_ids, event='arrived')

    # -------------------------------------------------------------------------
    # SPECIAL CASES
    # -------------------------------------------------------------------------
    def _special_case_depends(self):
        """Fields the live special-case check depends on. Procedures add theirs."""
        return ['state', 'special_case', 'special_reasons']

    @api.model
    def _special_rule(self, code):
        """This procedure's special-case rule row with this code (sudo), or empty."""
        return self.env['kderp.e.approval.special.rule'].get_rule(self._name, code)

    def _get_special_case_reasons(self):
        """Override in a procedure. Return a list of (action, text): action is the rule
        row's action ('special' or 'block'); rows switched off must not be returned
        (check rule.is_on()). Called on drafts, including unsaved form records."""
        self.ensure_one()
        return []

    def _special_case_evaluate(self):
        """(level, reasons): level 'blocked' if any reason blocks, 'special' if any reason,
        else 'normal'. Blocking reasons are listed first."""
        self.ensure_one()
        found = [(action, text) for action, text in (self._get_special_case_reasons() or [])
                 if action in ('special', 'block') and text]
        blocks = [text for action, text in found if action == 'block']
        specials = [text for action, text in found if action == 'special']
        level = 'blocked' if blocks else 'special' if specials else 'normal'
        return level, blocks + specials

    @api.depends(lambda self: self._special_case_depends())
    def _compute_special_case_live(self):
        for record in self:
            if record.state == 'draft':
                level, reasons = record._special_case_evaluate()
            else:
                level = record.special_case or 'normal'
                reasons = [line for line in (record.special_reasons or '').splitlines() if line.strip()]
            record.special_case_live = level
            record.special_case_banner = record._special_case_banner_html(level, reasons)

    def _special_case_banner_html(self, level, reasons):
        if level == 'normal' or not reasons:
            return False
        blocked = level == 'blocked'
        title = _('This request cannot be submitted:') if blocked else _('Special case:')
        return (
            "<div class='alert %s o_kderp_special_banner' role='status' style='margin-bottom:0;padding:8px 15px;'>"
            "<strong><i class='fa %s' role='presentation'></i> %s</strong>"
            "<ul style='margin-bottom:0;padding-left:20px;'>%s</ul></div>"
        ) % ('alert-danger' if blocked else 'alert-warning',
             'fa-ban' if blocked else 'fa-exclamation-triangle',
             html_escape(title),
             ''.join('<li>%s</li>' % html_escape(reason) for reason in reasons))

    def _special_case_freeze(self):
        """Run the checks at submit: refuse when blocked, else store the result."""
        for record in self:
            level, reasons = record._special_case_evaluate()
            if level == 'blocked':
                raise UserError(_("This request cannot be submitted:\n%s") %
                                '\n'.join('- %s' % reason for reason in reasons))
            explain = record._special_case_explain_field
            if level == 'special' and explain and not (record[explain] or '').strip():
                raise UserError(_("This request is a special case:\n%s\n\nPlease explain it in \"%s\" before submitting.") % (
                    '\n'.join('- %s' % reason for reason in reasons), record._fields[explain].string))
            record.write({'special_case': level, 'special_reasons': '\n'.join(reasons) or False})

    def pre_reset_to_draft_cleanup(self):
        """
            Placehold method allowing override to cleanup any custom fields before resetting to draft
        """
        self.ensure_one()
        self.validate_comments = False
        self.refuse_comments = False
        self.write({'special_case': 'normal', 'special_reasons': False})
    
    def action_reset_to_draft(self):
        """
        ADMIN ACTION: Clears out all current signature lines, unlocks 
        the document fields, and returns the request to a draft state.
        - override if needed
        """
        # Security Guard: Double-check that only authorized supervisors can execute this override
        admin_groups = self._admin_groups + ['kdvn_e_approval.group_e_approval_admin']
        if not any([self.env.user.has_group(g) for g in admin_groups]):
            raise UserError(_(
                "🔒 Access Denied!\n\n"
                "You do not have the right to unlock active validation procedures."
            ))

        reject_state = self._get_validation_target_states()[1]
        for record in self:
            was_refused = record[getattr(record, '_state_field', 'state')] == reject_state
            # 🚀 Core OCA Reset: Wipes out the background tier.review log lines completely
            if hasattr(record, 'restart_validation'):
                record.restart_validation()
                # Need to cleanup some fields values: here is the place
                record.pre_reset_to_draft_cleanup()

            # Roll back our visual tracking status bar safely back to draft
            # (a refused request: write() keeps the refusal in the log and says "Reset to Draft from Refused. Refused by ...")
            record.write({'state': 'draft'})

            if not was_refused:
                # Post a formal entry to the Odoo Chatter audit trail
                record.message_post(body=_("⚠️ Document unlocked and reset to Draft status by system administrator."))

    def action_user_force_budget_refresh(self):
        """
        USER-FACING SYNCHRONOUS FORCE REFRESH:
        Pings n8n with an explicit 'budgets_only' directive and waits for execution to complete.
        """
        self.ensure_one()
        
        # 1. ENFORCE DATABASE PERSISTENCE CHECKPOINT
        # Prevents validation crashes on newly initiated unsaved forms
        if not isinstance(self.id, int) or not self.id:
            raise UserError(_(
                "Unsaved Record Detected!\n\n"
                "Please click the 'Save' button to commit this request "
                "to the local database first before attempting to synchronize "
                "balance metrics from the remote server."
            ))

        # 2. Fetch your active n8n outbound link string parameter dynamically
        param_obj = self.env['ir.config_parameter'].sudo()
        webhook_url = param_obj.get_param('kderp_e_approval.n8n_webhook_job_sync_url', default=False)
        
        if not webhook_url:
            raise UserError(_("Configuration Error: The 'n8n Outbound Job Sync Link' must be configured in settings first."))
        
        # 2. Fire a SYNCHRONOUS POST request (holding the UI execution loop open)
        try:
            # We explicitly pass "sync_target": "budgets_only" to optimize the n8n route path
            response = requests.post(
                webhook_url.strip(), 
                json={
                    'triggered_by': self.env.user.name, 
                    'sync_target': 'budgets_only',
                    'record_id': self.id,
                    'model_name': self._name
                }, 
                timeout=20 # Safe timeout window for synchronous execution
            )
            
            if response.status_code != 200:
                raise UserError(_("The synchronization gateway rejected the live update request with status: %s") % response.status_code)
                
            # Parse telemetry counts returned straight out of your updated master pipeline endpoint
            response_json = response.json() or {}
            telemetry = response_json.get('telemetry', {})
            budgets_updated = telemetry.get('budgets_synced', 0)

        except requests.exceptions.RequestException as e:
            _logger.error("User on-demand budget sync routing timeout failure: %s", str(e))
            raise UserError(_("Could not reach synchronization gateway server. Please retry in a few moments."))

        # 3. Return an operational success banner notification that reloads the user's active viewport page layout
        
        log_message = _(
            "⚡ Master Pipeline Real-Time Synchronization Telemetry Clear:\n\n"
            "• Operation Status: SUCCESS\n"
            "• Target Cache Matrix: kderp.job.budget.cache\n"
            "• Total Records Synchronized: %s rows\n\n"
            "Your workspace dropdown views have been dynamically refreshed."
        ) % budgets_updated

        return self.env['kderp.notification.wizard'].show_notification_wizard(
            title=_("Data Synchronization Logs"),
            message=log_message,
            show_cancel=True # Exposes the Cancel button next to the OK button!
        )
        
    @api.model
    def generate_secure_signature(self, message):
        """
        CENTRAL CRYPTOGRAPHIC ENGINE (DRY):
        Generates a secure HMAC-SHA256 hex digest signature for any text message string.
        """
        if not message:
            return ""
            
        param_obj = self.env['ir.config_parameter'].sudo()
        secret_key = param_obj.get_param('kderp_e_approval.e_approval_secret_key', default=False)
        
        if not secret_key:
            _logger.warning("System Security Alert: 'e_approval_secret_key' is unconfigured!")
            return ""

        return hmac.new(
            key=secret_key.encode('utf-8'),
            msg=message.encode('utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()

    def _compute_verification_url(self):
        """
        Generates a secure, signed URL unique to this record instance's exact financial metadata.
        If an attacker tampers with the amount or ID on the PDF, the token validation will fail.
        """
        # Retrieve the secret key from System Parameters
        param_obj = self.env['ir.config_parameter'].sudo()
        secret_key = param_obj.get_param('kderp_e_approval.e_approval_secret_key', default=False)
        base_url = param_obj.get_param('web.base.url', default='http://localhost:8069')

        for record in self:
            if not secret_key:
                record.verification_token = False
                record.verification_url = False
                continue

            # Extract a unique transaction baseline message (Model + Record ID + Budget/Total Amount)
            # We use amount_total as a generic fallback, or adapt based on the inherited cache model
            amount = getattr(record, 'estimated_amount', 0.0)
            message = "%s-%s-%s" % (record._name, record.id, amount)

            # Generate the HMAC-SHA256 signature token
            signature = record.generate_secure_signature(message)

            # Compile into the secure gateway route query parameters
            query_params = {
                'model': record._name,
                'id': record.id,
                'token': signature
            }
            
            record.verification_token = signature
            record.verification_url = "%s/api/v1/verify_approval?%s" % (base_url.strip('/'), url_encode(query_params))

    def get_py3o_barcode_base64(self):
        """
        DRY 1D BARCODE GENERATOR:
        Generates a clean industrial Code128 barcode wrapping the verification URL.
        Natively bakes the document reference name text string right underneath the lines.
        """
        self.ensure_one()
        if not barcode or not self.verification_url:
            _logger.warning("Barcode generation skipped: Libraries or verification_url missing.")
            return ""

        try:
            # 1. Select standard industrial Code128 format
            code128_class = barcode.get_barcode_class('code128')
            
            # 2. Configure the ImageWriter options to inject text cleanly underneath the lines
            writer_options = {
                'text_distance': 3.0,     # Space between barcode lines and text string
                'font_size': 9,           # Font sizing for the text under the barcode
                'background': 'white',
                'foreground': 'black',
                'write_text': True        # ENFORCED: Forces the reference text to print under the barcode
            }
            
            # 3. Create the barcode instance mapping back to your secure cryptographic URL string
            # We explicitly pass the record's sequence name (self.name) to display under the barcode layout lines!
            bc = code128_class(self.verification_url, writer=ImageWriter())
            
            # 4. Save image payload directly into memory buffer stream
            buffer = io.BytesIO()
            bc.write(buffer, options=writer_options)
            barcode_bytes = buffer.getvalue()
            buffer.close()

            # 5. Package as clean base64 string stream for Py3o ODT processing
            return base64.b64encode(barcode_bytes).decode('utf-8')

        except Exception as e:
            _logger.error("Failed to compile 1D barcode data stream: %s", str(e))
            return ""

    def get_py3o_qr_base64(self, *args, **kwargs):
        """
        SAFE BASE64 IMAGE GENERATOR:
        Protects the pipeline from throwing "Incorrect padding" validation errors
        if Py3o passes raw background dictionaries into the template context.
        """

        # -------------------------------------------------------------------------
        # THE GUARD CLAUSE: Detect and filter out unparseable dictionary payloads
        # -------------------------------------------------------------------------
        # If 'self' arrived as a blank context, an unexpected list, or a user dictionary
        if not self or isinstance(self, dict) or isinstance(args, tuple) and any(isinstance(a, dict) for a in args):
            _logger.warning("Skipping execution: Malformed template dictionary context intercepted.")
            return ""

        # Ensure we are evaluating a concrete record instance
        try:
            self.ensure_one()
        except Exception:
            # Fallback if self is an unexpected multi-record set
            if self.ids:
                record = self[0]
            else:
                return ""
        else:
            record = self

        if not record or not record.verification_url:
            _logger.warning("Skipping execution: verification_url is unpopulated.")
            return ""

        # 4. Generate QR Code Matrix via Python qrcode engine
        qr = qrcode.QRCode(version=1, box_size=10, border=1)
        qr.add_data(record.verification_url)
        qr.make(fit=True)

        buffer = io.BytesIO()
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(buffer, format="PNG")
        qr_bytes = buffer.getvalue()
        buffer.close()

        # 5. Extract Base64 and force correct padding validation structure
        encoded_str = base64.b64encode(qr_bytes).decode('utf-8')
        
        # Safe structural padding check to prevent binascii errors
        rem = len(encoded_str) % 4
        if rem > 0:
            encoded_str += "=" * (4 - rem)

        return encoded_str

    # Signature strip colours (project palette) and labels per review status
    _SIGNATURE_STYLES = {
        'approved': ('#28a745', u'\u2713 APPROVED'),
        'rejected': ('#dc3545', u'\u2717 REJECTED'),
        'pending': ('#7C7BAD', u'PENDING'),
    }
    _SIGNATURE_WAITING = ('#adb5bd', u'WAITING')

    def _signature_review_info(self, review):
        """ Title, status key/label/colour, signer name and local date-time of one review line. """
        status = review.status
        color, label = self._SIGNATURE_STYLES.get(status, self._SIGNATURE_WAITING)
        # Who actually decided (done_by) once decided; otherwise the expected reviewer(s)
        if status in ('approved', 'rejected') and review.done_by:
            raw_name = review.done_by.name or ''
        else:
            raw_name = review.todo_by or ''
        # Strip employee codes like 'S1085 - ' or 'HE12 - '
        clean_name = re.sub(r'^[A-Z0-9\s]+[-\u2013\u2014]\s*', '', raw_name) or '---'
        when = '---'
        if review.reviewed_date:
            local = fields.Datetime.context_timestamp(self, fields.Datetime.to_datetime(review.reviewed_date))
            when = local.strftime('%d/%m/%Y %H:%M')
        return {
            'title': (review.definition_id.frontend_name or _('Reviewer')).upper(),
            'status': status,
            'label': label,
            'color': color,
            'name': clean_name,
            'date': when,
        }

    @api.model
    def _render_signature_strip_png(self, infos, min_slots=4, scale=3):
        """ PNG (base64) of one signature cell per review. The canvas is always at least
        `min_slots` cells wide (cells centred), so a template that prints it at a fixed width
        keeps the same cell size for 1..min_slots steps. Drawn at `scale`x for a sharp print. """
        if not infos:
            return False
        slot_w, slot_h, gap = 170 * scale, 104 * scale, 8 * scale
        slots = max(len(infos), min_slots)
        img = Image.new('RGB', (slot_w * slots, slot_h), color='#FFFFFF')
        draw = ImageDraw.Draw(img)

        def font(bold, size):
            names = ['DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold \
                else ['DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
            for name in names:
                try:
                    return ImageFont.truetype(name, size * scale)
                except IOError:
                    continue
            return ImageFont.load_default()

        f_title, f_status = font(True, 8), font(True, 10)
        f_name, f_date = font(True, 9), font(False, 8)

        def width(text, fnt):
            if hasattr(draw, 'textlength'):
                return draw.textlength(text, font=fnt)
            return draw.textsize(text, font=fnt)[0]

        def fit(text, fnt, max_w):
            if width(text, fnt) <= max_w:
                return text
            while text and width(text + u'\u2026', fnt) > max_w:
                text = text[:-1]
            return text + u'\u2026'

        # Works with old Pillow too (production Pillow may predate rounded_rectangle, the
        # rectangle width= argument and float text coordinates): integer coordinates only.
        def box(xy, outline, fill=None, radius=6 * scale, line=1 * scale):
            xy = [int(v) for v in xy]
            if hasattr(draw, 'rounded_rectangle'):
                draw.rounded_rectangle(xy, radius=radius, outline=outline, fill=fill, width=line)
                return
            if fill:
                draw.rectangle(xy, fill=fill)
            for k in range(line):
                draw.rectangle([xy[0] + k, xy[1] + k, xy[2] - k, xy[3] - k], outline=outline)

        x0 = (slots - len(infos)) * slot_w // 2
        for i, info in enumerate(infos):
            left = x0 + i * slot_w + gap // 2
            right = left + slot_w - gap
            cx, inner = (left + right) / 2.0, right - left - 12 * scale
            decided = info['status'] in ('approved', 'rejected')
            # Card with a coloured band at the top (= status)
            box([left, 1 * scale, right, slot_h - 1 * scale], '#dee2e6')
            box([left + 4 * scale, 4 * scale, right - 4 * scale, 8 * scale], info['color'],
                fill=info['color'], radius=2 * scale)
            lines = [
                (fit(info['title'], f_title, inner), f_title, '#495057', 16),
                (info['label'], f_status, info['color'], 38),
                (fit(info['name'], f_name, inner), f_name, '#212529' if decided else '#6c757d', 64),
                (info['date'], f_date, '#6c757d', 82),
            ]
            for text, fnt, color, top in lines:
                draw.text((int(cx - width(text, fnt) / 2.0), int(top * scale)), text, fill=color, font=fnt)
            # Thin "signature line" between status and name
            draw.line([int(left + 18 * scale), 58 * scale, int(right - 18 * scale), 58 * scale], fill='#dee2e6', width=1 * scale)

        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

    def _prepare_reviews_signatures(self):
        """ Report data for the approval signatures:
        - signature_blocks: one dict per review (title, status, name, date) for templates that loop;
        - signature_strip_png: the same as one image (see _render_signature_strip_png).
        """
        self.ensure_one()
        infos = [self._signature_review_info(r) for r in self.review_ids.sorted(key=lambda r: r.sequence)]
        if not infos:
            _logger.info("No review lines on %s: signature strip not drawn", self.display_name)
        report_data = {
            'signature_blocks': [{
                'title': i['title'], 'status': '[ %s ]' % (i['status'] if i['status'] in self._SIGNATURE_STYLES else 'waiting').upper(),
                'name': i['name'], 'date': i['date'],
            } for i in infos],
            'signature_strip_png': False,
        }
        try:
            report_data['signature_strip_png'] = self._render_signature_strip_png(infos)
        except Exception:
            _logger.exception("Failed drawing the signature strip for %s", self.display_name)
        return report_data

    def action_print_secure_authenticated_report(self):
        """
        UNIVERSAL CONTEXT ROUTER:
        - Validates security authorization checkpoints.
        - Extracts target report ID and data formatting method name string from context.
        - Dynamically invokes the specified formatting method via getattr().
        """
        self.ensure_one()

        # 1. UNIVERSAL SECURITY CHECKPOINT
        if self.state != 'approved':
            return self.env['kderp.notification.wizard'].show_notification_wizard(
                title=_("Printing Operations Blocked"),
                message=_("Beta Core Block: Only fully 'Approved' requests can compile signed reports."),
                show_cancel=False
            )

        # 2. EXTRACT DYNAMIC ARCHITECTURE ENVELOPE PARAMETERS FROM CONTEXT
        report_xml_id = self.env.context.get('target_report_xml_id') or self._default_approval_report_xml_id
        format_method_name = self.env.context.get('report_format_method')

        if not report_xml_id:
            raise UserError(_("Developer Error: 'target_report_xml_id' is missing from the button context."))

        # 3. DYNAMIC METHOD INVOCATION VIA GETATTR
        # datas = self.read()[0]
        datas = {}
        # If a custom data prep method is specified and exists on the current model class
        if format_method_name and hasattr(self, format_method_name):
            # Dynamically grab and execute the specific format method defined on the sub-model
            target_method = getattr(self, format_method_name)
            if callable(target_method):
                formatted_data = [target_method()]
                datas['formatted_data'] = formatted_data
        
        # 4. STREAM CLEAN DATA PACKET TO TARGET PY3O LAYOUT
        # return self.env.ref(report_xml_id).with_context().report_action(res_ids, data=datas)
        return self.env.ref(report_xml_id).with_context(wizard_report=True).report_action([], data=datas)


    def _get_or_create_nextcloud_room_token(self, nc_url, bot_user, bot_pass, nc_login):
        """
        Helper backend method executing queries directly against the Spreed API engine
        to discover or build direct chat conversations with the target login alias.
        """
        try:
            # 1. Trigger API lookup to create or fetch a direct one-on-one room
            endpoint = f"{nc_url}/ocs/v1.php/apps/spreed/api/v4/room"
            headers = {"OCS-APIRequest": "true", "Accept": "application/json"}
            payload = {"roomType": 1, "invite": nc_login} # roomType 1 represents a Direct One-on-One chat room
            
            resp = requests.post(endpoint, auth=(bot_user, bot_pass), headers=headers, data=payload, timeout=10)
            if resp.status_code in [200, 201]:
                data = resp.json()
                # Extract the native conversation room token string directly from the OCS payload body
                return data.get('ocs', {}).get('data', {}).get('token', False)
        except Exception as e:
            _logger.error("Failed resolving Nextcloud room token for login %s: %s", nc_login, e)
        return False
