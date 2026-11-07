import hmac, hashlib
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class TierReview(models.Model):
    _inherit = "tier.review"

    # Pass the clean name from the definition down to the live tracking line
    frontend_step_name = fields.Char(string='Approval Layer', compute='_compute_frontend_step_name')
    comment = fields.Text()

    @api.depends('definition_id', 'definition_id.frontend_name')
    def _compute_frontend_step_name(self):
        for record in self:
            if record.definition_id and record.definition_id.frontend_name:
                record.frontend_step_name = record.definition_id.frontend_name
            else:
                record.frontend_step_name = record.name  # Fallback to technical name if empty

    def _get_reviewers(self):
        """
        OVERRIDE: Intercepts the evaluation stream to prevent 
        base_tier_validation_formula from polluting expressions with dirty data.
        """
        self.ensure_one()
        empty_users = self.env["res.users"]
        
        # Guard clause: If there is no configuration definition, degrade gracefully
        if not self.definition_id:
            return super(TierReview, self)._get_reviewers()

        current_type = self.definition_id.review_type

        # 🐍 CASE 1: PYTHON EXPRESSION 
        # Bypasses super() completely to prevent leftover column fields from loading!
        if current_type == 'expression':
            if hasattr(self, 'python_reviewer_ids') and self.python_reviewer_ids:
                return self.python_reviewer_ids
            return empty_users

        # 🎯 CASE 2: SPECIFIC USER WORKFLOW
        elif current_type == "individual":
            return self.reviewer_id if self.reviewer_id else empty_users

        # 👥 CASE 3: SECURITY GROUP WORKFLOW
        elif current_type == "group":
            return self.reviewer_group_id.users if self.reviewer_group_id else empty_users

        # 📄 CASE 4: DYNAMIC DOCUMENT FIELD WORKFLOW
        elif current_type == "field":
            if self.reviewer_field_id:
                resource = self.env[self.model].browse(self.res_id)
                reviewer_field = getattr(resource, self.reviewer_field_id.name, False)
                if reviewer_field and reviewer_field._name == "res.users":
                    return reviewer_field
                raise ValidationError(_("The targeted field does not contain valid res.users records."))
            return empty_users

        # Fallback safety default
        return super(TierReview, self)._get_reviewers()


class CommentWizard(models.TransientModel):
    _inherit = ['comment.wizard']

    comment = fields.Text(required=True)

    @api.constrains('comment')
    def _check_comment_not_empty(self):
        for record in self:
            # .strip() removes empty spaces. If nothing is left, it's invalid.
            if not record.comment or not record.comment.strip():
                raise ValidationError("The comment field cannot be empty or just spaces!")

