from odoo import models, fields, api

class ResUsers(models.Model):
    _inherit = 'res.users'

    approval_notify_type = fields.Selection([
        ('email', 'Email'),
        ('talk', 'Nextcloud Talk'),
        ('both', 'Talk (instant) + Email (daily digest)'),
    ], string="E-Approval Notifications", default='email', required=True,
        help="Email: a daily digest of requests waiting for you, and the result of your own requests.\n"
             "Nextcloud Talk: a short message for every change (a request reaches you, your request "
             "moves on or is decided), plus a daily reminder.\n"
             "Talk + Email: instant Talk messages, and one daily digest email instead of single emails.")

    approval_ribbon_style = fields.Selection([
        ('default', 'Company default'),
        ('statusbar', 'Odoo 12 statusbar (arrows)'),
        ('stepper', 'Stepper with names and dates'),
        ('badge', 'Compact stepper'),
    ], string="Approval Progress Layout", default='default', required=True,
        help="How the approval progress is shown on request forms. "
             "'Company default' follows the setting in E-Approval configuration.")

    # Odoo 19: the lists a user may read / write on his own record are properties (Odoo 12 changed class attributes in __init__)
    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['approval_notify_type', 'approval_ribbon_style']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['approval_notify_type', 'approval_ribbon_style']

    # TODO (port): Odoo 12 `get_reviews` added reviewer names and a short local date to the data of the OCA "Reviews" panel. OCA's 19.0 widget
    # (extra-addons/base_tier_validation/static/src/components/tier_review_widget) no longer calls res.users.get_reviews: redo this with the
    # OWL widget (see HANDOFF.md, e-approval open item 2). The columns are still in tier.review `frontend_step_name`, `reviewer_names`.

    @api.model
    def cron_send_all_manager_digests(self):
        """
        🎯 ENTERPRISE CRON PIPELINE ENGINE:
        Finds only records that are strictly waiting for action RIGHT NOW,
        resolves validation group members accurately, and sends zero-spam digest tables.
        """
        sudo_self = self.sudo()
        
        # 1. Get ALL active system models that utilize tier validation features
        tier_models = sudo_self.env['tier.definition'].search([]).mapped('model')
        unique_models = [m for m in set(tier_models) if m in sudo_self.env]

        # 2. Query pending review lines directly instead of loading every request record.
        #    The digest method keeps only the lowest pending sequence per record.
        active_reviews = sudo_self.env['tier.review'].search([
            ('model', 'in', unique_models),
            ('status', '=', 'pending'),
        ])

        # 3. Step 3: Now iterate through our clean unique set and send exactly 1 digest email per manager account
        sudo_self.env['kderp.e.approval.mixin']._notify_reviewers(active_reviews, event='digest')

