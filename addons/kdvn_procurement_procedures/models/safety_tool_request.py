import datetime
import base64
import io
import logging
import re

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup
from odoo.tools import html_escape

from . import safety_tool_notify as notify

_logger = logging.getLogger(__name__)

TOOL_ADMIN_GROUP = 'kdvn_procurement_procedures.group_safety_tool_admin'
E_APPROVAL_ADMIN_GROUP = 'kdvn_e_approval.group_e_approval_admin'
SHOE_WINDOW_MONTHS = 12
VAT_RATE = 0.10

OFFICE_CODES = [
    ('H', 'H - Head Office'),
    ('S', 'S - HCMC Branch'),
    ('T', 'T - Thang Long Office'),
    ('Y', 'Y - Hun Yen G.Store'),
    ('P', 'P - Hai Phong Office'),
    ('B', 'B - Bien Hoa Office'),
]

FULFILMENT_STATES = [
    ('to_issue', 'To issue (in stock)'),
    ('to_purchase', 'To purchase (short of stock)'),
    ('ordered', 'Ordered'),
    ('issued', 'Handed over'),
    ('received', 'Received by applicant'),
    ('not_received', 'Applicant says not received'),
]


class SafetyToolRequest(models.Model):
    _name = 'safety.tool.request'
    _inherit = ['mail.thread', 'kderp.e.approval.mixin']
    _description = 'Safety Tool Request'
    _order = 'id desc'

    _state_from = ['draft', 'submitted']
    _state_to = ['approved']
    _cancel_state = 'rejected'
    _allow_to_write_field_list = []
    # A special case (e.g. too many shoes) needs the purpose as the explanation
    _special_case_explain_field = 'reason'

    _approval_category = 'procurement'
    _approval_procedure_title = 'Safety Tool Request'
    _admin_groups = [TOOL_ADMIN_GROUP]
    _default_approval_report_xml_id = 'kdvn_procurement_procedures.safety_tool_request_report_py3o'

    reason = fields.Char(string='Purpose', required=True)
    request_type = fields.Selection([
        ('new', 'New tool'),
        ('replace', 'Replace a broken tool'),
    ], string='Request type', required=True, default='new', readonly=True, tracking=True)
    date_input = fields.Date(string='Date', required=True, default=fields.Date.context_today, readonly=True,)
    # Required for a new request (view + check at submit); imported history may have no matching job
    job_id = fields.Many2one('kderp.job.lookup', string='Job', readonly=True,)
    budget_code_id = fields.Many2one('kderp.job.budget.cache', string='Budget Code', readonly=True,)
    office_code = fields.Selection(OFFICE_CODES, string='Office Code', readonly=True,)
    line_ids = fields.One2many('safety.tool.request.line', 'request_id', string='Tools', copy=True,
                               readonly=True,)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Awaiting Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Document State', default='draft', tracking=True)

    # Trouble Report (Company Assets): only for a replacement
    trouble_date = fields.Date(string='Date of the trouble', readonly=True,)
    trouble_place = fields.Char(string='Place of the trouble', readonly=True,)
    damaged_item_id = fields.Many2one('safety.tool.item', string='Damaged item', readonly=True,)
    asset_code = fields.Char(string='Fixed assets code', readonly=True,)
    trouble_note = fields.Text(string='The trouble situation', readonly=True,)
    trouble_photo_ids = fields.Many2many('ir.attachment', 'safety_tool_request_trouble_photo_rel', 'request_id',
                                         'attachment_id', string='Photos of the trouble', readonly=True,)
    solution = fields.Selection([
        ('repair', 'Repair'),
        ('dispose', 'Disposal (or throw-away)'),
        ('buy_new', 'Others (buying new ones)'),
    ], string='Solution', default='buy_new', readonly=True,)
    repair_cost = fields.Float(string='Estimated cost to repair (VND)', digits=(16, 0), readonly=True,)

    # Cost: blank at request time on the paper form; filled by the Safety Tool Admin when bought
    cost_amount = fields.Float(string='Cost (VND)', digits=(16, 0), tracking=True)
    vat_amount = fields.Float(string='VAT 10% (VND)', digits=(16, 0), compute='_compute_totals', store=True)
    total_amount = fields.Float(string='Total (VND)', digits=(16, 0), compute='_compute_totals', store=True)

    # After approval: the store side (not an approval step)
    fulfilment_state = fields.Selection(FULFILMENT_STATES, string='Fulfilment', readonly=True, copy=False,
                                        tracking=True, index=True)
    issued_date = fields.Date(readonly=True, copy=False)
    receipt_no = fields.Char(string='Receipt No.', readonly=True, copy=False, index=True,
                             help='Number of the paper "Receipt for Safety Tool" (SM-YY-####), given at the first handover.')
    issued_by_id = fields.Many2one('res.users', string='Handed over by', readonly=True, copy=False)
    issue_override_note = fields.Char(string='Reason to issue with insufficient stock', copy=False,
                                      help='Needed only when the stock is lower than the quantities requested.')
    receipt_date = fields.Date(string='Receipt confirmed on', readonly=True, copy=False)
    receipt_reminded = fields.Boolean(readonly=True, copy=False)
    # Only the store staff and auditors read the ledger. Field-level groups (not view-level) so that the field is
    # removed from the form of everybody else: a view-level group only hides it and the browser still reads it.
    move_ids = fields.One2many('safety.tool.move', 'request_id', string='Stock moves', readonly=True,
                               groups='kdvn_procurement_procedures.group_safety_tool_admin,'
                                      'kdvn_e_approval.group_e_approval_admin,'
                                      'kdvn_e_approval.group_e_approval_global_auditor')
    stock_warning = fields.Html(compute='_compute_stock_warning', sanitize=False)
    is_tool_admin = fields.Boolean(compute='_compute_is_tool_admin')
    # History imported from the Excel control sheet: already approved and handed over, no approval steps
    is_imported = fields.Boolean(string='Imported from Excel', readonly=True, copy=False, index=True)
    import_batch_id = fields.Many2one('safety.tool.import.batch', string='Import', readonly=True, copy=False,
                                      ondelete='set null', index=True)
    import_project_text = fields.Char(string='Project (as in the Excel)', readonly=True, copy=False)
    import_staff_text = fields.Char(string='Staff (as in the Excel)', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('cost_amount')
    def _compute_totals(self):
        for rec in self:
            rec.vat_amount = round((rec.cost_amount or 0.0) * VAT_RATE)
            rec.total_amount = (rec.cost_amount or 0.0) + rec.vat_amount

    def _compute_is_tool_admin(self):
        is_admin = self._is_tool_admin()
        for rec in self:
            rec.is_tool_admin = is_admin

    @api.model
    def _is_tool_admin(self):
        user = self.env.user
        return user.has_group(TOOL_ADMIN_GROUP) or user.has_group(E_APPROVAL_ADMIN_GROUP)

    def _shortages(self):
        """[(item, size, needed, in stock)] for every item/size whose total requested quantity
        is higher than the stock."""
        self.ensure_one()
        need = {}
        for line in self.line_ids:
            if line.item_id:
                key = (line.item_id, line.size_id)
                need[key] = need.get(key, 0.0) + (line.qty or 0.0)
        stock = self.env['safety.tool.move'].stock_map([item.id for item, size in need])
        result = []
        for (item, size), qty in need.items():
            available = stock.get((item.id, size.id if size else False), 0.0)
            if qty > available:
                result.append((item, size, qty, available))
        return result

    @api.depends('line_ids.item_id', 'line_ids.size_id', 'line_ids.qty', 'state', 'fulfilment_state')
    def _compute_stock_warning(self):
        for rec in self:
            warning = False
            if rec.state != 'rejected' and rec.fulfilment_state not in ('issued', 'received', 'not_received'):
                shorts = rec._shortages()
                if shorts:
                    rows = ''.join('<li>%s: requested %s, in stock %s</li>' % (
                        html_escape('%s%s' % (item.name, size and ' (%s)' % size.name or '')),
                        '{:g}'.format(need), '{:g}'.format(have)) for item, size, need, have in shorts)
                    warning = (
                        "<div class='alert alert-warning' role='status' style='margin-bottom:0;padding:8px 15px;'>"
                        "<strong><i class='fa fa-exclamation-triangle' role='presentation'></i> %s</strong>"
                        "<ul style='margin-bottom:0;padding-left:20px;'>%s</ul></div>"
                    ) % (html_escape(_('Not enough stock for part of this request:')), rows)
            rec.stock_warning = warning

    # ------------------------------------------------------------------
    # Onchange / constraints
    # ------------------------------------------------------------------
    @api.onchange('job_id')
    def _onchange_job_id_filter_budget(self):
        if self.job_id:
            if self.budget_code_id and self.budget_code_id.job_id != self.job_id:
                self.budget_code_id = False
            return {'domain': {'budget_code_id': [('job_id', '=', self.job_id.id)]}}
        return {'domain': {'budget_code_id': [('id', '=', False)]}}

    @api.constrains('cost_amount', 'repair_cost')
    def _check_amounts(self):
        for rec in self:
            if rec.cost_amount < 0 or rec.repair_cost < 0:
                raise ValidationError(_('Amounts cannot be negative.'))

    # ------------------------------------------------------------------
    # Attachments of the trouble report belong to the request (like attachment_ids)
    # ------------------------------------------------------------------
    def _adopt_trouble_photos(self):
        for rec in self:
            orphans = rec.trouble_photo_ids.filtered(lambda a: not a.res_id)
            if orphans:
                orphans.sudo().write({'res_model': rec._name, 'res_id': rec.id})

    @api.model_create_multi
    def create(self, vals_list):
        records = super(SafetyToolRequest, self).create(vals_list)
        records._adopt_trouble_photos()
        return records

    def write(self, vals):
        res = super(SafetyToolRequest, self).write(vals)
        if 'trouble_photo_ids' in vals:
            self._adopt_trouble_photos()
        return res

    def unlink(self):
        if self.env.context.get('safety_tool_system') and all(self.mapped('is_imported')):
            return super(SafetyToolRequest, self).unlink()      # undo of an Excel import
        if self.filtered(lambda r: r.state != 'draft' or r.review_ids):
            raise UserError(_("Deletion restricted: the request is not a draft or has an approval history. "
                              "Please contact the E-Approval Administrator."))
        return super(SafetyToolRequest, self).unlink()

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    def _check_before_submit(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Add at least one tool to the request.'))
        if not self.job_id:
            raise UserError(_('Choose the job.'))
        if self.request_type == 'replace':
            missing = [label for fname, label in (
                ('trouble_date', _('Date of the trouble')), ('trouble_place', _('Place of the trouble')),
                ('damaged_item_id', _('Damaged item'))) if not self[fname]]
            if missing:
                raise UserError(_('A replacement request needs the Trouble Report: %s.') % ', '.join(missing))

    def action_submit(self):
        for rec in self:
            rec._check_before_submit()
        return super(SafetyToolRequest, self).action_submit()

    # ------------------------------------------------------------------
    # Special cases (limits are rows of kderp.e.approval.special.rule, shipped switched off)
    # ------------------------------------------------------------------
    def _special_case_depends(self):
        return super(SafetyToolRequest, self)._special_case_depends() + [
            'request_type', 'reason', 'employee_id', 'date_input', 'trouble_photo_ids',
            'line_ids', 'line_ids.qty', 'line_ids.item_id']

    def _get_special_case_reasons(self):
        self.ensure_one()
        reasons = []
        # A line quantity above the limit
        rule = self._special_rule('qty_over')
        if rule.is_on():
            for line in self.line_ids:
                if line.item_id and line.qty > rule.value:
                    reasons.append((rule.action, _('%s: quantity %s is above the limit of %s') % (
                        line.item_id.name, '{:g}'.format(line.qty), '{:g}'.format(rule.value))))
        # Too many safety shoes for the same staff within the period
        rule = self._special_rule('shoe_limit')
        if rule.is_on() and self.employee_id:
            asked = sum(l.qty for l in self.line_ids if l.item_id.item_type == 'shoe')
            if asked:
                start = (self.date_input or fields.Date.context_today(self)) - relativedelta(months=SHOE_WINDOW_MONTHS)
                domain = [('employee_id', '=', self.employee_id.id), ('state', 'in', ['submitted', 'approved']),
                          ('date_input', '>=', start)]
                if isinstance(self.id, int):
                    domain.append(('id', '!=', self.id))
                before = sum(l.qty for r in self.sudo().search(domain) for l in r.line_ids
                             if l.item_id.item_type == 'shoe')
                if before + asked > rule.value:
                    reasons.append((rule.action, _('Safety shoes: %s asked + %s in the last %s months is above the limit of %s') % (
                        '{:g}'.format(asked), '{:g}'.format(before), SHOE_WINDOW_MONTHS, '{:g}'.format(rule.value))))
        # Replacement without a photo of the broken tool
        rule = self._special_rule('replace_no_photo')
        if rule.is_on() and self.request_type == 'replace' and not self.trouble_photo_ids:
            reasons.append((rule.action, _('Replacement request without a photo of the broken tool')))
        return reasons

    def _dashboard_date(self):
        """Date the home dashboard shows in My requests: imported history shows its own date (the Excel row),
        not the day it was imported. Noon, so any time zone keeps the same calendar day."""
        self.ensure_one()
        if self.is_imported and self.date_input:
            return datetime.datetime.combine(self.date_input, datetime.time(12, 0))
        return self.write_date

    # ------------------------------------------------------------------
    # After approval: the store side
    # ------------------------------------------------------------------
    def _universal_state_changer(self, target_state):
        res = super(SafetyToolRequest, self)._universal_state_changer(target_state)
        if target_state == getattr(self, '_state_to', ['approved'])[-1]:
            for rec in self.filtered(lambda r: not r.fulfilment_state):
                rec._after_approved()
        return res

    # ------------------------------------------------------------------
    # Notifications: Talk and / or email as each person chose (same channel rules as the approvals);
    # the chatter keeps a log note without sending anything, so nobody is told twice.
    # ------------------------------------------------------------------
    def _tools_text(self, limit=4):
        self.ensure_one()
        tools = ['%s%s x %s' % (l.item_id.name or '', l.size_id and ' (%s)' % l.size_id.name or '', '{:g}'.format(l.qty))
                 for l in self.line_ids]
        return '; '.join(tools[:limit]) + (' +%s more' % (len(tools) - limit) if len(tools) > limit else '')

    def _tool_notify(self, users, event, note=''):
        """Tell `users` (res.users) about `event` (see safety_tool_notify.EVENTS)."""
        self.ensure_one()
        cfg = self._notify_config()
        url = '%s/web#id=%s&model=%s&view_type=form' % (cfg['base_url'], self.id, self._name)
        who = self.employee_id.sudo().name or ''
        for user in users:
            email = (self.employee_id.sudo().work_email or self.create_uid.email) if user == self.employee_id.user_id else user.email
            send_email, send_talk = self._notify_channels(user, cfg, 'result', email=email)
            if send_email:
                subject, html = notify.email_parts(event, user.name, self.name or '', who, self._tools_text(), note, url)
                self._notify_send_email(email, subject, html, auto_delete=True)
            if send_talk:
                self._notify_send_talk(user, notify.talk_text(event, self.name or '', who, self._tools_text(), note, url), cfg)

    def _tool_admin_users(self):
        group = self.env.ref(TOOL_ADMIN_GROUP, raise_if_not_found=False)
        return group.sudo().user_ids.filtered('active') if group else self.env['res.users']

    def _applicant_user(self):
        self.ensure_one()
        return self.employee_id.user_id or self.create_uid

    def _after_approved(self):
        """Decide in stock / short of stock and tell the Safety Tool Admin staff."""
        self.ensure_one()
        shorts = self._shortages()
        self.sudo().write({'fulfilment_state': 'to_purchase' if shorts else 'to_issue'})
        if shorts:
            lines = Markup('').join(Markup('<li>%s: requested %s, in stock %s</li>') % (
                '%s%s' % (item.name, size and ' (%s)' % size.name or ''),
                '{:g}'.format(need), '{:g}'.format(have)) for item, size, need, have in shorts)
            body = Markup('%s<ul>%s</ul>') % (_('Approved, but the stock is not enough: please purchase.'), lines)
            note = _('Short of stock: %s') % '; '.join('%s%s (asked %s, in stock %s)' % (
                item.name, size and ' %s' % size.name or '', '{:g}'.format(need), '{:g}'.format(have))
                for item, size, need, have in shorts)
        else:
            body = _('Approved and in stock: please hand the tools over to the applicant.')
            note = _('All the tools are in stock: please hand them over.')
        self.sudo().message_post(body=body, subtype_xmlid='mail.mt_note')
        self.sudo()._tool_notify(self._tool_admin_users(), 'approved_short' if shorts else 'approved_stock', note)

    def _require_tool_admin(self):
        if not self._is_tool_admin():
            raise UserError(_('Only the Safety Tool Admin staff can do this.'))

    def action_check_stock(self):
        """After a stock in: 'to purchase' / 'ordered' becomes 'to issue' when the stock is enough."""
        self._require_tool_admin()
        for rec in self.filtered(lambda r: r.fulfilment_state in ('to_purchase', 'ordered')):
            if rec._shortages():
                raise UserError(_('%s: the stock is still not enough.') % rec.name)
            rec.write({'fulfilment_state': 'to_issue'})

    def action_mark_ordered(self):
        self._require_tool_admin()
        self.filtered(lambda r: r.fulfilment_state == 'to_purchase').write({'fulfilment_state': 'ordered'})

    @api.model
    def _next_receipt_no(self, date):
        """SM-YY-#### : the highest number of that year + 1 (so it continues after numbers typed or imported from the paper forms)."""
        prefix = 'SM-%s-' % str(date.year)[2:]
        last = 0
        for no in self.sudo().search([('receipt_no', '=like', prefix + '%')]).mapped('receipt_no'):
            tail = no[len(prefix):]
            if tail.isdigit():
                last = max(last, int(tail))
        return '%s%04d' % (prefix, last + 1)

    def action_issue(self):
        """Hand the tools over: post the OUT moves. Stock leaves the store at this moment."""
        self._require_tool_admin()
        Move = self.env['safety.tool.move'].with_context(safety_tool_system=True)
        for rec in self:
            if rec.state != 'approved' or rec.fulfilment_state not in ('to_issue', 'to_purchase', 'ordered'):
                raise UserError(_('%s cannot be handed over now.') % rec.name)
            shorts = rec._shortages()
            if shorts and not (rec.issue_override_note or '').strip():
                raise UserError(_('Not enough stock:\n%s\n\nPurchase first, or write the reason to hand over anyway '
                                  'in "Reason to issue with insufficient stock".') % '\n'.join(
                    '- %s%s: requested %s, in stock %s' % (item.name, size and ' (%s)' % size.name or '', need, have)
                    for item, size, need, have in shorts))
            if not rec.receipt_no:
                rec.write({'receipt_no': self._next_receipt_no(fields.Date.context_today(rec))})
            for line in rec.line_ids:
                Move.create({
                    'date': fields.Date.context_today(rec),
                    'item_id': line.item_id.id, 'size_id': line.size_id.id or False,
                    'qty_out': line.qty, 'source': 'request', 'request_id': rec.id, 'line_id': line.id,
                    'job_id': rec.job_id.id, 'employee_id': rec.employee_id.id, 'note': rec.name,
                    'work_area': rec.employee_id.sudo().work_location or False,
                })
            rec.write({'fulfilment_state': 'issued', 'issued_date': fields.Date.context_today(rec),
                       'issued_by_id': self.env.uid, 'receipt_reminded': False, 'receipt_date': False})
            rec.message_post(
                body=_('The tools were handed over by %s. Please confirm on the request that you received them.') % self.env.user.name,
                subtype_xmlid='mail.mt_note')
            rec.sudo()._tool_notify(rec._applicant_user(), 'handover',
                                    _('Handed over by %s. Please open the request and confirm that you received the tools.') % self.env.user.name)

    def action_reverse_issue(self):
        """Undo a handover (tools came back, or the applicant did not receive them): IN moves."""
        self._require_tool_admin()
        Move = self.env['safety.tool.move'].with_context(safety_tool_system=True)
        for rec in self:
            if rec.fulfilment_state not in ('issued', 'received', 'not_received'):
                raise UserError(_('%s has not been handed over.') % rec.name)
            for move in rec.move_ids.filtered(lambda m: m.source == 'request'):
                Move.create({
                    'date': fields.Date.context_today(rec),
                    'item_id': move.item_id.id, 'size_id': move.size_id.id or False,
                    'qty_in': move.qty_out, 'source': 'reverse', 'request_id': rec.id, 'line_id': move.line_id.id,
                    'job_id': rec.job_id.id, 'employee_id': rec.employee_id.id,
                    'note': _('Reversal of the handover of %s') % rec.name,
                })
            rec.write({'fulfilment_state': 'to_issue', 'issued_date': False, 'issued_by_id': False,
                       'receipt_date': False, 'receipt_reminded': False})
            rec.message_post(body=_('Handover reversed by %s: the tools are back in stock.') % html_escape(self.env.user.name))

    def action_confirm_received(self):
        for rec in self:
            if not rec.is_current_applicant:
                raise UserError(_('Only the applicant can confirm the receipt.'))
            if rec.fulfilment_state not in ('issued', 'not_received'):
                raise UserError(_('Nothing to confirm on %s.') % rec.name)
            rec.write({'fulfilment_state': 'received', 'receipt_date': fields.Date.context_today(rec)})
            rec.message_post(body=_('Receipt confirmed by the applicant.'))

    def action_not_received(self):
        for rec in self:
            if not rec.is_current_applicant:
                raise UserError(_('Only the applicant can report this.'))
            if rec.fulfilment_state != 'issued':
                raise UserError(_('Nothing to report on %s.') % rec.name)
            rec.write({'fulfilment_state': 'not_received'})
            rec.sudo().message_post(
                body=_('The applicant says the tools were NOT received. Safety Tool Admin: please check, and use "Reverse handover" if the stock-out was wrong.'),
                subtype_xmlid='mail.mt_note')
            rec.sudo()._tool_notify(rec._tool_admin_users(), 'not_received',
                                    _('Please check. Use "Reverse handover" on the request if the stock-out was wrong.'))

    @api.model
    def cron_remind_receipt(self):
        """Daily: remind applicants who have not confirmed the receipt (once, never blocks)."""
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'kdvn_procurement_procedures.receipt_reminder_days', default='3') or 3)
        limit = fields.Date.context_today(self) - relativedelta(days=days)
        for rec in self.sudo().search([('fulfilment_state', '=', 'issued'), ('receipt_reminded', '=', False),
                                       ('issued_date', '<=', limit)]):
            rec.message_post(body=_('Reminder: please confirm on the request that you received your safety tools.'),
                             subtype_xmlid='mail.mt_note')
            rec._tool_notify(rec._applicant_user(), 'reminder',
                             _('Please open the request and confirm that you received the tools (or press Not received).'))
            rec.receipt_reminded = True

    # ------------------------------------------------------------------
    # Reset to draft
    # ------------------------------------------------------------------
    def action_reset_to_draft(self):
        for rec in self:
            if rec.fulfilment_state in ('issued', 'received', 'not_received'):
                raise UserError(_('%s was already handed over (stock moves posted). Use "Reverse issue" first.') % rec.name)
        return super(SafetyToolRequest, self).action_reset_to_draft()

    def pre_reset_to_draft_cleanup(self):
        res = super(SafetyToolRequest, self).pre_reset_to_draft_cleanup()
        self.write({'fulfilment_state': False, 'issue_override_note': False})
        return res

    # ------------------------------------------------------------------
    # Printed form (py3o): "Approval Sheet - Request of Safety Tool" (+ Trouble Report for a replacement)
    # ------------------------------------------------------------------
    PRINT_PHOTOS_MAX = 2

    def _report_photos(self):
        """Photos of the trouble as small PNG (base64) for the form; files that are not images are skipped."""
        self.ensure_one()
        photos = []
        try:
            from PIL import Image
        except ImportError:                                                    # pragma: no cover
            return photos
        for att in self.sudo().trouble_photo_ids[:self.PRINT_PHOTOS_MAX]:
            try:
                img = Image.open(io.BytesIO(base64.b64decode(att.datas))).convert('RGB')
                img.thumbnail((900, 700))
                out = io.BytesIO()
                img.save(out, 'PNG')
                photos.append(base64.b64encode(out.getvalue()).decode('ascii'))
            except Exception:
                continue
        return photos

    def prepare_safety_tool_report(self):
        self.ensure_one()
        fmt_date = lambda d: fields.Date.from_string(d).strftime('%d - %b - %Y') if d else ''
        fmt_vnd = lambda v: ('VND {:,.0f}'.format(v).replace(',', '.')) if v else '-'
        qty = lambda v: '{:g}'.format(v)
        selection = lambda fname, value: dict(self._fields[fname].selection).get(value, '')
        is_replace = self.request_type == 'replace'
        data = {
            'reference_no': self.name or '',
            # hr.employee is private in Odoo 19: the applicant prints his own form, read these three values as superuser
            'applicant': self.employee_id.sudo().name or '',
            'staff_no': self.employee_id.sudo().code or '',
            'department': self.employee_id.sudo().department_id.name or '',
            'qr_code_base64': self.get_py3o_qr_base64(),
            'title': _('APPROVAL SHEET: REQUEST OF SAFETY TOOL') if not is_replace else _('APPROVAL SHEET: REPLACEMENT OF A BROKEN SAFETY TOOL'),
            'date_input': fmt_date(self.date_input),
            'request_type': selection('request_type', self.request_type),
            'reason': self.reason or '-',
            'job': self.job_id.display_name if self.job_id else (self.import_project_text or ''),
            'budget_code': self.budget_code_id.display_name if self.budget_code_id else '-',
            'office_code': dict(OFFICE_CODES).get(self.office_code, '-'),
            'lines': [{'no': str(i), 'item': l.item_id.name or '', 'size': l.size_id.name or '-',
                       'qty': qty(l.qty), 'uom': l.uom or ''} for i, l in enumerate(self.line_ids, 1)],
            'cost': fmt_vnd(self.cost_amount), 'vat': fmt_vnd(self.vat_amount), 'total': fmt_vnd(self.total_amount),
            'is_replace': is_replace,
            'approval_title': '5. Approval' if is_replace else '4. Approval',
            'stamp': u'\u2713 APPROVED' if not self.is_imported else 'IMPORTED HISTORY',
            'approval_note': (_('Approved electronically in KDERP e-Approval; no handwritten signature is required. '
                                'Scan the QR code to check this approval online.') if not self.is_imported else
                              _('Imported from the Excel safety tool control sheet: past issue of the tools, no approval steps were recorded.')),
            'trouble_date': fmt_date(self.trouble_date), 'trouble_place': self.trouble_place or '',
            'damaged_item': self.damaged_item_id.name or '', 'asset_code': self.asset_code or '-',
            'trouble_note': self.trouble_note or '-', 'solution': selection('solution', self.solution),
            'repair_cost': fmt_vnd(self.repair_cost),
            'photos': self._report_photos() if is_replace else [],
        }
        data.update(self._prepare_reviews_signatures())
        return data

    def prepare_safety_tool_receipt(self):
        """Data of the paper 'Receipt for Safety Tool': one row per catalogue item (in code order), the sizes in the remark."""
        self.ensure_one()
        fmt = lambda d: d.strftime('%d/%m/%Y') if d else ''
        q = lambda v: '{:g}'.format(v) if v else '-'
        items = self.env['safety.tool.item'].sudo().search([]).sorted(lambda i: (i.code or '~', i.sequence, i.name))
        rows = []
        for item in items:
            lines = self.line_ids.filtered(lambda l: l.item_id == item)
            if not lines and not item.active:
                continue
            total = sum(lines.mapped('qty'))
            m = re.match(r'^ST0*(\d+)(-\d+)?', item.code or '')
            rows.append({'no': ('%s%s' % (m.group(1), m.group(2) or '')) if m else (item.code or ''), 'item': item.name or '', 'uom': item.uom or '',
                         'request': q(total), 'receive': q(total),
                         'remark': ', '.join('%s x %s' % (l.size_id.name, '{:g}'.format(l.qty)) if l.size_id else ''
                                             for l in lines).strip(', ')})
        issued = self.issued_date
        return {
            'receipt_no': self.receipt_no or '', 'reference_no': self.name or '', 'date': fmt(issued or self.date_input),
            'title': _('RECEIPT FOR SAFETY TOOL'), 'qr_code_base64': self.get_py3o_qr_base64(),
            'stamp': (u'\u2713 RECEIVED' if self.receipt_date else _('HANDED OVER, WAITING FOR THE APPLICANT')),
            'project': (self.job_id.display_name if self.job_id else (self.import_project_text or '')) or
                       self.employee_id.sudo().work_location or '',
            'staff_no': self.employee_id.sudo().code or '', 'applicant': self.employee_id.sudo().name or '',
            'lines': rows, 'receipt_date': fmt(self.receipt_date),
            'delivered_by': self.issued_by_id.name or '', 'issued_date': fmt(issued),
            'signature_strip_png': self._receipt_signature_png(fmt),
        }

    def _receipt_signature_png(self, fmt):
        """The signature cards of the other forms (same drawing as the approval signatures): who handed the tools over and who
        confirmed the receipt in e-Approval."""
        got = bool(self.receipt_date)
        infos = [
            {'title': 'RECEIVED BY', 'status': 'approved' if got else 'pending', 'color': '#28a745' if got else '#7C7BAD',
             'label': u'\u2713 RECEIVED' if got else 'NOT CONFIRMED YET', 'name': self.employee_id.sudo().name or '---',
             'date': fmt(self.receipt_date) or '---'},
            {'title': 'DELIVERED BY', 'status': 'approved', 'color': '#28a745', 'label': u'\u2713 DELIVERED',
             'name': self.issued_by_id.name or '---', 'date': fmt(self.issued_date) or '---'},
        ]
        try:
            return self._render_signature_strip_png(infos, min_slots=2)
        except Exception:
            _logger.exception('Receipt signatures not drawn for %s', self.display_name)
            return False

    # ------------------------------------------------------------------
    # Notification summary
    # ------------------------------------------------------------------
    def get_approval_digest_details(self):
        self.ensure_one()
        tools = ['%s%s x %s' % (l.item_id.name or '', l.size_id and ' (%s)' % l.size_id.name or '', '{:g}'.format(l.qty))
                 for l in self.line_ids]
        shown = '; '.join(tools[:3]) + (' +%s more' % (len(tools) - 3) if len(tools) > 3 else '')
        parts = [
            '<strong>Type:</strong> %s' % html_escape(dict(self._fields['request_type'].selection).get(self.request_type, '')),
            '<strong>Job:</strong> %s' % html_escape(self.job_id.display_name or ''),
            '<strong>Tools:</strong> %s' % html_escape(shown),
        ]
        if self.office_code:
            parts.append('<strong>Office:</strong> %s' % html_escape(dict(OFFICE_CODES).get(self.office_code, '')))
        if self.request_type == 'replace':
            parts.append('<strong>Trouble:</strong> %s %s' % (html_escape(self.trouble_place or ''), self.trouble_date or ''))
        if self.reason:
            parts.insert(0, '<strong>Purpose:</strong> %s' % html_escape(self.reason))
        return '<br/>'.join(parts)


class SafetyToolRequestLine(models.Model):
    _name = 'safety.tool.request.line'
    _description = 'Safety Tool Request Line'
    _order = 'sequence, id'

    request_id = fields.Many2one('safety.tool.request', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    item_id = fields.Many2one('safety.tool.item', string='Tool', required=True, ondelete='restrict')
    size_id = fields.Many2one('safety.tool.size', string='Size', domain="[('item_id', '=', item_id)]",
                              ondelete='restrict')
    has_sizes = fields.Boolean(related='item_id.has_sizes', readonly=True)
    qty = fields.Float(string='Quantity', digits=(16, 2), required=True, default=1.0)
    uom = fields.Char(string='Unit', related='item_id.uom', readonly=True)
    stock_qty = fields.Float(string='In stock', compute='_compute_stock_qty', digits=(16, 2))
    is_short = fields.Boolean(string='Short of stock', compute='_compute_stock_qty')

    @api.onchange('item_id')
    def _onchange_item_id(self):
        if self.size_id and self.size_id.item_id != self.item_id:
            self.size_id = False

    @api.depends('item_id', 'size_id', 'qty')
    def _compute_stock_qty(self):
        stock = self.env['safety.tool.move'].stock_map([l.item_id.id for l in self if l.item_id])
        for line in self:
            have = stock.get((line.item_id.id, line.size_id.id or False), 0.0) if line.item_id else 0.0
            line.stock_qty = have
            line.is_short = bool(line.item_id) and line.qty > have

    def _check_editable(self, requests):
        if self.env.context.get('safety_tool_system'):
            return
        if requests.filtered(lambda r: r.state != 'draft'):
            raise UserError(_('The tools of a request can only be changed while it is a draft.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_editable(self.env['safety.tool.request'].browse(
            [v['request_id'] for v in vals_list if v.get('request_id')]))
        return super(SafetyToolRequestLine, self).create(vals_list)

    def write(self, vals):
        self._check_editable(self.mapped('request_id'))
        return super(SafetyToolRequestLine, self).write(vals)

    def unlink(self):
        self._check_editable(self.mapped('request_id'))
        return super(SafetyToolRequestLine, self).unlink()

    @api.constrains('qty')
    def _check_qty(self):
        if any(line.qty <= 0 for line in self):
            raise ValidationError(_('The quantity must be greater than 0.'))

    @api.constrains('item_id', 'size_id')
    def _check_size(self):
        for line in self:
            if line.item_id.size_ids and not line.size_id:
                raise ValidationError(_('"%s" has sizes: choose the size.') % line.item_id.name)
            if line.size_id and line.size_id.item_id != line.item_id:
                raise ValidationError(_('Size "%s" does not belong to "%s".') % (line.size_id.name, line.item_id.name))
