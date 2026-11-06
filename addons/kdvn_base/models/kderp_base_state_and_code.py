from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

TYPE_CODE = [('state', 'Status'), ('budget_type', 'Budget Type'), ('area_type', 'Area Type')]   # other modules add types with selection_add
permission_warning = "KDERP Warning!\nYou don't have permission, change state of %s"


class KDERPBaseCode(models.Model):
    _name = 'kderp.base.code'
    _description = 'KDERP Base Code Model'
    _inherit = 'kderp.base.model'
    _order = 'sequence'
    _code_only = False
    _name_only = True
    _code_unique = False

    @api.model
    def _get_default_base_code(self, model, type_code, default_state=''):
        if not default_state:
            res = self.search([('model_id', '=', model), ('default_code', '=', True), ('type_code', '=', type_code)])
        else:
            res = self.search([('model_id', '=', model), ('code', '=', default_state), ('type_code', '=', type_code)])
        return res[0] if res else False

    code = fields.Char(size=32)
    sequence = fields.Integer('Seq.')
    default_code = fields.Boolean('Default State')
    model_id = fields.Many2one('ir.model', 'Model ID', required=True, ondelete='cascade')
    active = fields.Boolean(default=True, string='Active')
    model_name = fields.Char(related='model_id.model', string='Model Name')
    type_code = fields.Selection(TYPE_CODE, 'Type', required=True)
    # index of the colors: 0 none, 1 red, 2 orange, 3 yellow, 4 light blue, 5 dark purple, 6 salmon pink, 7 medium blue, 8 dark blue, 9 fushia, 10 green, 11 purple
    # (Odoo 12 had a Selection with integer keys; Odoo 19 selections need string keys, so it is a plain integer here with the same values)
    color = fields.Integer(string='Code/State color', default=0)

    @api.constrains('default_code', 'model_id', 'type_code')
    def _check_model_default(self):
        for rec in self:
            if len(self.search([('model_id', '=', rec.model_id.id), ('default_code', '=', True), ('type_code', '=', rec.type_code)])) > 1:
                raise ValidationError(_('KDERP Configuration error!\nThe default Code and Type of the model should be the unique.'))

    _uniqe_state_model = models.Constraint('unique(type_code, code, model_id)', 'Please check data, data of type code must be unique')


class KDERPBaseStateCode(models.Model):
    _name = 'kderp.base.state'
    _description = 'KDERP Base State Model'
    _inherit = 'kderp.base.code'
    _parent_name = 'previous_id'

    previous_id = fields.Many2one('kderp.base.state', ondelete='restrict')
    next_id = fields.Many2one('kderp.base.state', compute='_get_next_id')
    model_id = fields.Many2one('ir.model', 'Model ID', ondelete='cascade')
    group_id = fields.Many2one('res.groups', 'Group')
    group_editable_id = fields.Many2one('res.groups', 'User Group Editable')
    type_code = fields.Selection(default='state')
    condition = fields.Char('Condition?', default='True', required=True, size=128)
    ignore = fields.Char('Ignore?', size=128)
    finalstate = fields.Boolean('Closed Workflow state', default=False)
    button_label = fields.Char('Button Label', size=16)
    button_class = fields.Char('Button Class', size=32)
    button_icon = fields.Char('Button Icon', size=32)

    def get_next_id(self):
        """Next state of the workflow: the first following state whose `condition` is true for the active record
        (context active_record_id); states whose `ignore` is true for the record are skipped."""
        self.ensure_one()
        active_record_id = self.env.context.get('active_record_id', False)
        active_rs = self.env[self.model_id.model].browse(active_record_id) if active_record_id else False
        next_states = self.search([('previous_id', '=', self.id)])   # default order: sequence (as Odoo 12 order="")
        next_state = False
        if active_rs:
            for candidate in next_states:
                if eval(candidate.condition.replace('record.', 'active_rs.'), {'active_rs': active_rs}):
                    next_state = candidate
                    break
        next_state = next_state or (next_states and next_states[0])
        ignore = next_state.ignore
        if not next_state.finalstate and ignore and active_rs and eval(ignore.replace('record.', 'active_rs.'), {'active_rs': active_rs}):
            return next_state.get_next_id()
        return next_state

    def _get_next_id(self):
        context = self.env.context
        for state in self:
            state.with_context(**context).next_id = state.get_next_id()

    def _check_group(self, target):
        if self.env.user.id != 1 and target.group_id and not self.env.user.has_group(target.group_id.get_external_id().get(target.group_id.id)):
            raise AccessError(permission_warning % self.model_id.name)

    def action_change_state(self, res_id):
        """Change to the state given in context (`state` / `tostate`, or `finalstate`), if the user is in the state's group."""
        self.ensure_one()
        context = self.env.context
        to_state = context.get('state', '') or context.get('tostate', '')
        origin_state_id = context.get('origin_state_id', False)
        if not to_state and context.get('finalstate', False):
            final = self.search([('model_id', '=', self.model_id.model), ('finalstate', '=', True)])
            to_state = final and final.code
        if to_state:
            target = self.search([('model_id', '=', self.model_id.model), ('code', '=', to_state)])
            if target:
                self._check_group(target)
                self.env[self.model_id.model].browse(res_id).write({'state_id': target.id, 'origin_state_id': origin_state_id})

    def nextState(self, res_id):
        self.ensure_one()
        target = self.with_context(active_record_id=res_id).next_id
        if target:
            self._check_group(target)
            self.env[self.model_id.model].browse(res_id).write({'state_id': target.id})

    def backState(self, res_id):
        self.ensure_one()
        target = self.previous_id
        if target:
            self._check_group(target)
            self.env[self.model_id.model].browse(res_id).write({'state_id': target.id})

    def actionCancel(self, res_id):
        self.ensure_one()
        cancel = self.search([('model_id', '=', self.model_id.model), ('code', '=', 'cancel')])
        if not cancel:
            raise ValidationError(_("KDERP Configuration error!\nThe %s model don't have state CANCEL", self.model_id.name))
        self._check_group(cancel[0])
        self.env[self.model_id.model].browse(res_id).write({'state_id': cancel[0].id})

    def actionReset(self, res_id):
        self.ensure_one()
        draft = self.search([('model_id', '=', self.model_id.model), ('default_code', '=', True)])
        if not draft:
            raise ValidationError(_("KDERP Configuration error!\nThe %s model don't have state DRAFT", self.model_id.name))
        self._check_group(draft[0])
        self.env[self.model_id.model].browse(res_id).write({'state_id': draft[0].id})


class KDERPBasePreventUnlink(models.AbstractModel):
    _name = 'kderp.base.states.prevent.unlink.model'
    _description = 'KDERP Base States Prevent Unlink Record Abstract Model'
    _unlinkable_states = ['draft']

    def unlink(self):
        for obj in self:
            if obj.state not in self._unlinkable_states:
                raise UserError(_('You cannot delete an %(what)s in state %(state)s', what=self._description, state=obj.state))
        return super().unlink()


class KDERPBaseStatesReadonly(models.AbstractModel):
    """Odoo 12 edited fields_get to make fields readonly per state. Odoo 19 views do that with readonly="state == ..." : nothing here."""
    _name = 'kderp.base.states.readonly.model'
    _description = 'KDERP Base States Readonly Abstract Model'


class KDERPBaseStateModel(models.AbstractModel):
    _name = 'kderp.base.state.model'
    _description = 'KDERP Base State Abstract Model'
    _inherit = 'kderp.base.states.readonly.model'
    _unlinkable_states = []
    _check_fields_cancel = []

    @api.constrains('state', 'origin_state_id')
    def check_state_revising(self):
        if self.filtered(lambda obj: obj.origin_state_id and obj.origin_state_id.code == 'revising'):
            raise ValidationError('KDERP Error, Please check revising state')

    @api.model
    def _get_state_selection(self):
        return [(s.code, s.name) for s in self.env['kderp.base.state'].search([('model_id', '=', self._name)])]

    @api.model
    def _get_default_state(self):
        res = self.env['kderp.base.state'].search([('model_id', '=', self._name), ('default_code', '=', True)])
        return res and res.id

    def button_change_state(self):
        self.ensure_one()
        return self.state_id.action_change_state(self.id)

    def button_next_state(self):
        self.state_id.nextState(self.id)
        return True

    def button_previous_state(self):
        self.state_id.backState(self.id)
        return True

    def button_cancel(self):
        for fld in self._check_fields_cancel:
            if self.mapped(fld).filtered(lambda rec: rec.state != 'cancel'):
                raise ValidationError('KDERP Warning, Please cancel all %s before you cancel this document!' % self[fld]._description)
        self.state_id.actionCancel(self.id)
        return True

    def button_reset(self):
        self.state_id.actionReset(self.id)
        return True

    @api.depends('state_id', 'state_id.code')
    def _get_state_code(self):
        for rec in self:
            rec.state = rec.state_id and rec.state_id.code

    def _inverse_state_id(self):
        for rec in self:
            state = self.env['kderp.base.state'].search([('model_id', '=', self._name), ('code', '=', rec.state)], limit=1)
            rec.state_id = state or False

    @api.onchange('state_id')
    def _update_state(self):
        self.state = self.state_id and self.state_id.code

    state_id = fields.Many2one('kderp.base.state', string='Status ID', required=True, domain=lambda self: [('model_id', '=', self._name)],
                               default=_get_default_state, ondelete='restrict')
    state = fields.Selection(_get_state_selection, compute='_get_state_code', inverse='_inverse_state_id', string='Status', store=True, readonly=True, index=True)
    origin_state_id = fields.Many2one('kderp.base.state', string='State of Document before Open', ondelete='restrict')

    def action_open_for_revising(self):
        self.ensure_one()
        if self.state_id.code != 'revising':
            self.state_id.with_context(state='revising', origin_state_id=self.state_id.id).action_change_state(self.id)

    def action_close_revising(self):
        self.ensure_one()
        current = self.origin_state_id
        if not current:
            raise ValidationError('KDERP Warning, Please check your status or contact to Administrator System')
        self.write({'state_id': current.id, 'origin_state_id': False})

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.update(self.default_get(['state_id']))
        return super().copy(default)

    def unlink(self):
        for obj in self:
            if not obj.state_id.default_code and obj.state_id.code not in self._unlinkable_states:
                raise UserError(_('You cannot delete an %(what)s in state %(state)s', what=self._description, state=obj.state_id.name))
        return super().unlink()
