from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError

PREFIX_CONSTRAINTS = 'sql_constraint_code_unique'


class KDERPBaseModel(models.AbstractModel):
    """Code + name records. display name = 'CODE - Name'; search finds by code first, then by name."""
    _name = 'kderp.base.model'
    _description = 'KDERP Base Model Abstract'
    _order = 'code, name'
    _separate_char = ' - '
    _alternate_name = 'name'
    _ingore_copy_fields = {}   # fields that are not copied (name kept from Odoo 12)
    _code_only = False
    _name_only = False
    _code_size = 9
    _name_size = 128
    _code_unique = True
    _auto_fill = True   # fill the code on create when exactly one suggestion exists (kdvn: no suggestion model, stays empty)

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.update(self._ingore_copy_fields)
        return super().copy(default)

    @api.model
    def _get_default_code(self, location='', date=False, return_object=False):
        """Odoo 12 suggested a code from ir.sequence records bound to the model. Not ported (no suggestion UI): no default."""
        return False

    fullName = fields.Char(string='Full Name', compute='_get_fullname')
    code = fields.Char(string='Code', size=_code_size, required=True, default=lambda self: self._auto_fill and self._get_default_code(), index=True)
    name = fields.Char(string='Name', size=_name_size, required=True, translate=True)

    @api.depends('code', 'name')
    def _get_fullname(self):
        for obj in self:
            obj.fullName = '%s%s%s' % (obj.code or '', self._separate_char, obj[self._alternate_name] or '')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for obj in self:
            if self.env.context.get('code_only', False) or self._code_only:
                obj.display_name = obj.code
            elif self.env.context.get('name_only', False) or self._name_only:
                obj.display_name = obj[self._alternate_name]
            else:
                obj.display_name = '%s%s%s' % (obj.code or '', self._separate_char, obj[self._alternate_name] or '')

    @api.constrains('code')
    def unique_code(self):
        for rec in self.filtered(lambda obj: obj.code):
            if self._code_unique and self.search([('code', '=', rec.code), ('id', '!=', rec.id)], limit=1):
                raise UserError(_('Code of %s must be unique', self._description.title()))

    @api.model
    def _search_display_name(self, operator, value):
        """Code first, then name (same order as Odoo 12 name_search): an exact '=' on the code wins, otherwise code or name ilike."""
        if value and operator in ('=', 'ilike', '=ilike', 'like', '=like'):
            if operator == '=' and self.search_count([('code', '=', value)], limit=1):
                return [('code', '=', value)]
            return ['|', ('code', operator, value), (self._alternate_name, operator, value)]
        return super()._search_display_name(operator, value)
