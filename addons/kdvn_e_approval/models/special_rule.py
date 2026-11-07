"""Special-case rules shared by every e-approval procedure.

Each row is one check that a procedure implements in Python (rule code). The row only holds
what HR may change: the threshold and what happens when it is exceeded. Rows are created by the
procedure's data file; a new kind of rule means a code change.

Editing: e-approval admins edit every row; each row names the group that may edit it
(e.g. HR for peak time). Every change is tracked in the chatter.
"""
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

SPECIAL_RULE_ACTIONS = [
    ('special', 'Special case'),
    ('block', 'Block submit'),
    ('off', 'Off'),
]


class KderpEApprovalSpecialRule(models.Model):
    _name = 'kderp.e.approval.special.rule'
    _inherit = ['mail.thread']
    _description = 'E-Approval Special Case Rule'
    _order = 'procedure, sequence, id'

    @api.model
    def _selection_procedures(self):
        options = []
        for name, model in self.env.items():
            if (name != 'kderp.e.approval.mixin' and not model._abstract
                    and hasattr(model, '_universal_state_changer')):
                options.append((name, getattr(model, '_approval_procedure_title', None) or model._description or name))
        return sorted(options, key=lambda o: o[1])

    procedure = fields.Selection('_selection_procedures', string='Procedure', required=True, index=True)
    code = fields.Char(required=True, help='Technical code read by the procedure (set by the developer).')
    name = fields.Char(string='Rule', required=True, translate=True)
    sequence = fields.Integer(default=10)
    # group_operator=False: limits of different rules must not be summed in grouped lists
    value = fields.Float(string='Limit', digits=(16, 2), tracking=True, group_operator=False)
    unit = fields.Char(help='Shown next to the limit, e.g. days or months.')
    action = fields.Selection(SPECIAL_RULE_ACTIONS, string='When exceeded', required=True,
                              default='special', tracking=True)
    description = fields.Text(string='How it is checked')
    manager_group_id = fields.Many2one('res.groups', string='Editable by',
                                       help='Members of this group may change this rule '
                                            '(e-approval administrators always can).')

    _sql_constraints = [
        ('procedure_code_unique', 'unique(procedure, code)', 'Each rule code can be used once per procedure.'),
    ]

    @api.constrains('value')
    def _check_value(self):
        if any(rule.value < 0 for rule in self):
            raise ValidationError(_('A special-case limit cannot be negative.'))

    @api.model
    def get_rule(self, procedure, code):
        """The rule row (sudo), or an empty recordset when the procedure has no such row."""
        return self.sudo().search([('procedure', '=', procedure), ('code', '=', code)], limit=1)

    def is_on(self):
        """True when the row exists and is not switched off."""
        return bool(self) and self.action != 'off'
