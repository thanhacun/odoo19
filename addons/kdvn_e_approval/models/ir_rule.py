from odoo import api, models
from odoo.fields import Domain


class IrRule(models.Model):
    _inherit = 'ir.rule'

    @api.model
    def _compute_domain(self, model_name, mode="read"):
        """E-Approval Administrator and Read-Only Auditor are defined here, once, for every request model (every model
        built on kderp.e.approval.mixin, also those of later modules): the Administrator reads, writes and creates all
        requests, the Auditor reads all of them. Nobody deletes through these groups. Modules add no rule for them."""
        domain = super()._compute_domain(model_name, mode)
        if mode == 'unlink' or self.env.su or not self._is_approval_model(model_name):
            return domain
        user = self.env.user
        if user._has_group('kdvn_e_approval.group_e_approval_admin') or (
                mode == 'read' and user._has_group('kdvn_e_approval.group_e_approval_global_auditor')):
            return Domain.TRUE
        return domain

    @api.model
    def _is_approval_model(self, model_name):
        model_cls = self.env.registry.get(model_name)
        mixin_cls = self.env.registry.get('kderp.e.approval.mixin')
        return bool(model_cls and mixin_cls and model_name != 'kderp.e.approval.mixin' and issubclass(model_cls, mixin_cls))
