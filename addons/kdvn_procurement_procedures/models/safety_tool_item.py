from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

ITEM_TYPES = [
    ('indicator', 'Indicator / Sign / Flag'),
    ('vest', 'Vest'),
    ('helmet', 'Helmet'),
    ('belt', 'Safety Belt'),
    ('shoe', 'Safety Shoe'),
    ('other', 'Other'),
]


class SafetyToolItem(models.Model):
    """Catalogue of the safety tools (the numbered items of the Excel control sheet).

    Local for now. `external_code` is the code of the same product on the remote KDERP server
    (product.product default_code): a later link to a synced product cache, nothing uses it yet.
    Sizes are a property of the item (safety.tool.size)."""
    _name = 'safety.tool.item'
    _description = 'Safety Tool Item'
    _order = 'sequence, code, name'

    sequence = fields.Integer(default=10)
    code = fields.Char(string='No.', index=True, help='Item number of the control sheet.')
    name = fields.Char(string='Item', required=True)
    item_type = fields.Selection(ITEM_TYPES, string='Type', required=True, default='other')
    uom = fields.Char(string='Unit', required=True, default='pcs')
    size_ids = fields.One2many('safety.tool.size', 'item_id', string='Sizes', copy=True)
    has_sizes = fields.Boolean(compute='_compute_has_sizes', store=True)
    reorder_level = fields.Float(string='Reorder level', digits=(16, 2),
                                 help='A warning is shown when the stock is at or below this value. 0 = no warning.')
    image = fields.Binary(string='Photo', attachment=True)
    note = fields.Text()
    external_code = fields.Char(string='Remote product code',
                                help='Code of the same product on the remote KDERP server (not used yet).')
    active = fields.Boolean(default=True)
    stock_qty = fields.Float(string='In stock', compute='_compute_stock', search='_search_stock_qty', digits=(16, 2))
    low_stock = fields.Boolean(string='Low stock', compute='_compute_stock', search='_search_low_stock')

    @api.depends('size_ids')
    def _compute_has_sizes(self):
        for item in self:
            item.has_sizes = bool(item.size_ids)

    def _is_low(self, qty):
        self.ensure_one()
        return bool(self.reorder_level) and qty <= self.reorder_level

    def _compute_stock(self):
        stock = self.env['safety.tool.move'].stock_map(self.ids)
        for item in self:
            qty = sum(q for (item_id, size_id), q in stock.items() if item_id == item.id)
            item.stock_qty = qty
            item.low_stock = item._is_low(qty)

    @api.model
    def _search_stock_qty(self, operator, value):
        return self._search_by_stock(lambda item, qty: self._cmp(qty, operator, value))

    @api.model
    def _search_low_stock(self, operator, value):
        want_low = bool(value) == (operator == '=')
        return self._search_by_stock(lambda item, qty: item._is_low(qty) == want_low)

    @api.model
    def _search_by_stock(self, test):
        items = self.search([])
        stock = self.env['safety.tool.move'].stock_map(items.ids)
        ids = [i.id for i in items if test(i, sum(q for (iid, sid), q in stock.items() if iid == i.id))]
        return [('id', 'in', ids)]

    @staticmethod
    def _cmp(left, operator, right):
        return {'=': left == right, '!=': left != right, '<': left < right, '<=': left <= right,
                '>': left > right, '>=': left >= right}.get(operator, False)

    def action_view_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock moves: %s') % self.name,
            'res_model': 'safety.tool.move',
            'view_mode': 'list,form',
            'domain': [('item_id', '=', self.id)],
            'context': {'default_item_id': self.id, 'default_source': 'purchase'},
        }

    _reorder_level_positive = models.Constraint('check(reorder_level >= 0)', 'The reorder level cannot be negative.')


class SafetyToolSize(models.Model):
    _name = 'safety.tool.size'
    _description = 'Safety Tool Size'
    _order = 'item_id, sequence, id'

    item_id = fields.Many2one('safety.tool.item', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Size', required=True, help='e.g. 26.0 cm (42) or XL')
    sequence = fields.Integer(default=10)
    stock_qty = fields.Float(string='In stock', compute='_compute_stock', digits=(16, 2))

    _item_size_unique = models.Constraint('unique(item_id, name)', 'This size already exists for the item.')

    def _compute_stock(self):
        stock = self.env['safety.tool.move'].stock_map(self.mapped('item_id').ids)
        for size in self:
            size.stock_qty = stock.get((size.item_id.id, size.id), 0.0)

    @api.depends('name')
    def _compute_display_name(self):
        for size in self:
            size.display_name = size.name
