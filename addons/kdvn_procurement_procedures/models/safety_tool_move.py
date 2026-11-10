from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

MOVE_SOURCES = [
    ('opening', 'Opening balance'),
    ('purchase', 'Stock in (purchase)'),
    ('request', 'Issued to a request'),
    ('reverse', 'Reversal of an issue'),
    ('manual', 'Manual adjustment'),
]
LOCKED_FIELDS = ('item_id', 'size_id', 'qty_in', 'qty_out', 'request_id', 'line_id', 'source')


class SafetyToolMove(models.Model):
    """Stock ledger: one row = one event of the control sheet (date, item, size, project, PIC, IN / OUT).
    Stock = sum(IN) - sum(OUT) per item and size. Rows made by a request are locked."""
    _name = 'safety.tool.move'
    _description = 'Safety Tool Stock Move'
    _order = 'date desc, id desc'

    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    item_id = fields.Many2one('safety.tool.item', string='Item', required=True, index=True, ondelete='restrict')
    size_id = fields.Many2one('safety.tool.size', string='Size', domain="[('item_id', '=', item_id)]", ondelete='restrict')
    qty_in = fields.Float(string='IN', digits=(16, 2), default=0.0)
    qty_out = fields.Float(string='OUT', digits=(16, 2), default=0.0)
    source = fields.Selection(MOVE_SOURCES, required=True, default='manual', index=True)
    request_id = fields.Many2one('safety.tool.request', string='Request', ondelete='restrict', index=True)
    line_id = fields.Many2one('safety.tool.request.line', string='Request line', ondelete='restrict')
    job_id = fields.Many2one('kderp.job.lookup', string='Project')
    employee_id = fields.Many2one('hr.employee', string='PIC')
    note = fields.Char(string='Remarks')
    import_key = fields.Char(string='Import key', index=True, copy=False, readonly=True,
                             help='Identifies the Excel row this move came from (a re-import skips known rows).')
    import_batch_id = fields.Many2one('safety.tool.import.batch', string='Import', ondelete='set null', index=True,
                                      copy=False, readonly=True)

    # --- Stock-in data for the accounting report (the remote server is the source of truth) ---
    payment_no = fields.Char(string='Payment No.', index=True,
                             help='Supplier payment number on the remote server (EN26-2566). Type it and use "Get from remote server": '
                                  'supplier, invoice and expense no. are filled in. Leave empty until the payment exists.')
    expense_no = fields.Char(string='Expense No.', readonly=True, copy=False,
                             help='Fixed cost expense of the payment on the remote server (kept for later use).')
    supplier_name = fields.Char(string='Supplier')
    invoice_no = fields.Char(string='Invoice No.')
    invoice_date = fields.Date(string='Invoice date')
    unit_cost = fields.Float(string='Unit cost', digits=(16, 2), help='Price of one piece without VAT.')
    remote_amount = fields.Float(string='Amount (remote, no VAT)', digits=(16, 2), readonly=True)
    remote_synced_on = fields.Datetime(string='Remote data read on', readonly=True, copy=False)
    accounting_only = fields.Boolean(string='Accounting history', index=True, copy=False, readonly=True,
                                     help='Old purchase or handover that only exists in the accounting sheets of the Excel file (before the opening balance). '
                                          'It is NOT part of the stock; the accounting report uses it to cost the stock (FIFO).')
    # --- Handover data (OUT) ---
    work_area = fields.Char(string='Working area', help='Area of the staff (Tlip, Hai phong ...) when the tools were handed over.')
    receipt_no = fields.Char(string='Receipt No.', related='request_id.receipt_no', readonly=True)

    @api.constrains('qty_in', 'qty_out')
    def _check_quantities(self):
        for move in self:
            if move.qty_in < 0 or move.qty_out < 0:
                raise ValidationError(_('IN and OUT cannot be negative.'))
            if bool(move.qty_in) == bool(move.qty_out):
                raise ValidationError(_('A stock move is either IN or OUT: fill exactly one of them.'))

    @api.constrains('item_id', 'size_id')
    def _check_size(self):
        for move in self:
            if move.item_id.size_ids and not move.size_id:
                raise ValidationError(_('"%s" has sizes: choose the size.') % move.item_id.name)
            if move.size_id and move.size_id.item_id != move.item_id:
                raise ValidationError(_('Size "%s" does not belong to "%s".') % (move.size_id.name, move.item_id.name))

    @api.onchange('item_id')
    def _onchange_item_id(self):
        if self.size_id and self.size_id.item_id != self.item_id:
            self.size_id = False

    def write(self, vals):
        if not self.env.context.get('safety_tool_system') and any(f in vals for f in LOCKED_FIELDS):
            if self.filtered('request_id'):
                raise UserError(_('Stock moves made by a request cannot be changed. Use "Reverse issue" on the request.'))
        return super(SafetyToolMove, self).write(vals)

    def unlink(self):
        if not self.env.context.get('safety_tool_system') and self.filtered('request_id'):
            raise UserError(_('Stock moves made by a request cannot be deleted. Use "Reverse issue" on the request.'))
        return super(SafetyToolMove, self).unlink()

    # ------------------------------------------------------------------
    @api.model
    def stock_map(self, item_ids=None, upto=None):
        """{(item_id, size_id or False): quantity in stock} (read as superuser: applicants may
        not read the ledger but must see the stock warning). `upto`: only moves dated up to that day."""
        domain = [('accounting_only', '=', False)]
        if item_ids is not None:
            domain.append(('item_id', 'in', [i for i in item_ids if isinstance(i, int)]))
        if upto:
            domain.append(('date', '<=', upto))
        rows = self.sudo()._read_group(domain, ['item_id', 'size_id'],
                                      ['qty_in:sum', 'qty_out:sum'])
        stock = {}
        for item, size, qty_in, qty_out in rows:          # Odoo 19: _read_group gives tuples (groupby values, then aggregates)
            stock[(item.id or False, size.id or False)] = (qty_in or 0.0) - (qty_out or 0.0)
        return stock

    @api.model
    def stock_of(self, item, size=None):
        """Stock of one item (and size)."""
        if not item or not isinstance(item.id, int):
            return 0.0
        return self.stock_map([item.id]).get((item.id, size.id if size else False), 0.0)

    # ------------------------------------------------------------------
    # Remote server
    # ------------------------------------------------------------------
    @api.onchange('payment_no')
    def _onchange_payment_no(self):
        """Typing a payment no. fills the purchase data in the form only: nothing is saved until Save, so Discard throws it away."""
        if not self.payment_no or not self.payment_no.strip():
            return
        try:
            data = self._remote_payment_data(self.payment_no)
        except UserError as error:
            return {'warning': {'title': _('Remote server'), 'message': str(error)}}
        for field, value in data.items():
            if value and field != 'remote_amount':
                self[field] = value
        self.remote_amount = data.get('remote_amount') or 0.0
        self.remote_synced_on = fields.Datetime.now()
        if data.get('remote_amount') and self.qty_in and not self.unit_cost:
            self.unit_cost = round(data['remote_amount'] / self.qty_in, 2)

    def action_fetch_remote(self):
        """Read supplier, invoice, expense no. and amount of the payment from the remote server. Without a payment no. but with an
        invoice no. and date, the payment is looked up through the VAT invoice (only when exactly one payment uses it)."""
        for move in self.filtered(lambda m: m.qty_in):
            payment_no = move.payment_no
            if not payment_no and move.invoice_no and move.invoice_date:
                payment_no = self._remote_find_payment(move.invoice_no, move.invoice_date)
            if not payment_no:
                continue
            data = self._remote_payment_data(payment_no)
            vals = {'remote_synced_on': fields.Datetime.now(), 'payment_no': payment_no}
            vals.update({k: v for k, v in data.items() if v})
            if data.get('remote_amount') and not move.unit_cost and move.qty_in:
                vals['unit_cost'] = round(data['remote_amount'] / move.qty_in, 2)
            move.write(vals)
        return True

    @api.model
    def _remote_allowed_codes(self):
        """Staff codes that may be the COST USER of a purchase this user can look up on the remote server: the members of the
        group Safety Tool: Admin. None = no limit (superuser, E-Approval Administrator)."""
        user = self.env.user
        if self.env.uid == 1 or user.has_group('kdvn_e_approval.group_e_approval_admin'):
            return None
        group = self.env.ref('kdvn_procurement_procedures.group_safety_tool_admin').sudo()
        return {c.strip().upper() for c in group.user_ids.filtered('active').mapped('employee_ids.code') if c}

    @api.model
    def _remote_allowed_payment_ids(self, payments):
        """Ids of the given remote payments (dicts with 'id' and 'expense_id') whose expense has a cost user that is allowed."""
        allowed = self._remote_allowed_codes()
        if allowed is None:
            return {p['id'] for p in payments}
        expense_of = {p['id']: p['expense_id'][0] for p in payments if p.get('expense_id')}
        if not allowed or not expense_of:
            return set()
        lines = self.env['kderp.remote.client'].execute(
            'kderp.other.expense.line', 'search_read', [[['expense_id', 'in', list(set(expense_of.values()))]]],
            {'fields': ['expense_id', 'employee_id']})
        ok_expenses = set()
        for line in lines:
            code = (line['employee_id'] and line['employee_id'][1] or '').split(' - ')[0].strip().upper()
            if code in allowed and line['expense_id']:
                ok_expenses.add(line['expense_id'][0])
        return {pid for pid, eid in expense_of.items() if eid in ok_expenses}

    @api.model
    def _remote_find_payment(self, invoice_no, invoice_date):
        """Payment no. (ENYY-XXXX) of the supplier payment that carries the VAT invoice (number + date); False when none or several."""
        client = self.env['kderp.remote.client']
        invs = client.execute('kderp.supplier.vat.invoice', 'search_read',
                              [[['name', '=', (invoice_no or '').split(',')[0].strip()], ['date', '=', str(invoice_date)]]],
                              {'fields': ['kderp_supplier_payment_expense_ids']})
        ids = sorted({i for inv in invs for i in inv['kderp_supplier_payment_expense_ids']})
        if not ids:
            return False
        pays = client.execute('kderp.supplier.payment.expense', 'read', [ids], {'fields': ['code', 'expense_id']})
        okay = self._remote_allowed_payment_ids(pays)
        codes = sorted({p['code'] for p in pays if p['code'] and p['id'] in okay})
        return codes[0] if len(codes) == 1 else False

    @api.model
    def _remote_payment_data(self, payment_no):
        """{supplier_name, invoice_no, invoice_date, expense_no, remote_amount} of a supplier payment (fixed cost, ENYY-XXXX)
        on the remote server (read only, Reader login). Unknown number: UserError. remote_amount = total without VAT."""
        payment_no = (payment_no or '').strip()
        client = self.env['kderp.remote.client']
        rows = client.execute('kderp.supplier.payment.expense', 'search_read', [[['code', '=', payment_no]]],
                              {'fields': ['code', 'partner_id', 'total', 'tax_amount', 'expense_id', 'kderp_vat_invoice_ids'], 'limit': 1})
        # the same message for "unknown" and "not a safety tool purchase": nobody can probe other payments
        not_found = _('Payment %s was not found on the remote server, or it is not a purchase of the safety tool store (its cost user must be '
                      'one of the Safety Tool Admin staff).') % payment_no
        if not rows or rows[0]['id'] not in self._remote_allowed_payment_ids(rows):
            raise UserError(not_found)
        pay = rows[0]
        out = {'supplier_name': pay['partner_id'] and pay['partner_id'][1] or False,      # name_get of the supplier
               'remote_amount': (pay.get('total') or 0.0) - (pay.get('tax_amount') or 0.0)}
        if pay['expense_id']:
            out['expense_no'] = pay['expense_id'][1].split(' - ')[0].strip()
        if pay['kderp_vat_invoice_ids']:
            invs = client.execute('kderp.supplier.vat.invoice', 'read', [pay['kderp_vat_invoice_ids']], {'fields': ['name', 'date']})
            invs.sort(key=lambda i: i['date'] or '')
            out['invoice_no'] = ', '.join(i['name'] for i in invs if i['name']) or False
            out['invoice_date'] = invs[0]['date'] or False
        return out
