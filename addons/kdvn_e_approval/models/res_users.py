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

    def __init__(self, pool, cr):
        init_res = super(ResUsers, self).__init__(pool, cr)
        # copy the lists so the original references are not modified
        type(self).SELF_WRITEABLE_FIELDS = list(self.SELF_WRITEABLE_FIELDS)
        type(self).SELF_WRITEABLE_FIELDS.extend(['approval_notify_type', 'approval_ribbon_style'])
        type(self).SELF_READABLE_FIELDS = list(self.SELF_READABLE_FIELDS)
        type(self).SELF_READABLE_FIELDS.extend(['approval_notify_type', 'approval_ribbon_style'])
        return init_res
    @api.model
    def get_reviews(self, data):
        """Add what the Reviews panel shows like the list view: reviewer names
        and a short local date (OCA returns a timezone-aware datetime)."""
        res = super(ResUsers, self).get_reviews(data)
        reviews = {r.id: r for r in self.env['tier.review'].browse([row['id'] for row in res])}
        for row in res:
            review = reviews.get(row['id'])
            row['reviewer_names'] = review.reviewer_ids.mapped('name') if review else []
            if review and not row.get('frontend_step_name'):
                row['frontend_step_name'] = review.frontend_step_name
            date = row.get('reviewed_date')
            row['reviewed_date_display'] = date.strftime('%d/%m/%Y %H:%M') if date else ''
        return res

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

