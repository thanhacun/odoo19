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
        domain = []
        if item_ids is not None:
            domain = [('item_id', 'in', [i for i in item_ids if isinstance(i, int)])]
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
