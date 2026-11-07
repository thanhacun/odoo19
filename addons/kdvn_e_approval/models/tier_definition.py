from odoo import models, fields, api, _

class TierDefinition(models.Model):
    _inherit = "tier.definition"

    # Add a friendly display label for employees
    frontend_name = fields.Char(
        string='Frontend Step Display Name', 
        required=True, 
        default="Manager Sign-off",
        help="Friendly name displayed to staff employees in the checklist track table (e.g. 'General Manager Sign-off')"
    )
    
    # Odoo 12 always logged "refused by" in the chatter; OCA 19 does it only when this is set.
    notify_on_rejected = fields.Boolean(default=True)

    procedure_tag = fields.Selection(
        selection='_get_dynamic_procedure_tags',
        string='Belongs to Procedure App',
        index=True,
        required=True
    )

    @api.model
    def _get_dynamic_procedure_tags(self):
        """
        Dynamically generates selection choices based on active database models 
        that implement your core universal state engine logic.
        """
        options = []
        # Pull models that actively contain your custom mixin anchor method
        for model_name, model_instance in self.env.items():
            if hasattr(model_instance, '_universal_state_changer') and model_name != 'kderp.e.approval.mixin':
                # Build an elegant string representation: "staff.transfer" -> "Staff Transfer"
                label = model_name.replace('.', ' ').title()
                options.append((model_name, label))
        
        # Fallback safeguard matrix list
        return sorted(options) if options else [('entertainment.request', 'Entertainment Request')]

    @api.model
    def _get_tier_validation_model_names(self):
        """
        🚀 FIX: Bypasses hardcoding completely.
        Scans system memory to find every loaded class that utilizes our custom mixin.
        """
        res = super(TierDefinition, self)._get_tier_validation_model_names()
        
        # Scan everything initialized inside Odoo's live runtime engine
        for model_name, model_instance in self.env.items():
            # If the model implements your mixin anchor method, register it for tier validations!
            if hasattr(model_instance, '_universal_state_changer') and model_name not in res and model_name != 'kderp.e.approval.mixin':
                res.append(model_name)
                
        return res