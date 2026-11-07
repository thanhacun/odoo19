from odoo import models, fields, api, _

class KderpEApprovalSettingsInherit(models.TransientModel):
    _inherit = 'res.config.settings'     # Odoo 12: kderp.remote.sync.config.settings

    n8n_analytic_webhook_url = fields.Char(
        string='n8n Analytic Webhook URL',
        help="Endpoint payload URL to push finalized analytical account lines to central finance server."
    )
    e_approval_secret_key = fields.Char(
        string='System Encryption Token Key',
        help="A unique long password used as a salt passphrase to digitally sign approval links sent to manager emails. "
             "Leave empty to keep the saved key; it is never shown again. Changing it makes the approval links already sent invalid."
    )
    e_approval_secret_key_status = fields.Char(string='Saved secret key', readonly=True)
    e_approval_secret_key_saved = fields.Boolean(readonly=True)
    e_approval_short_link_path = fields.Char(
        string="Short Link Webhook Path",
        help="n8n webhook path for short approve/reject links (e.g. 'ea'). Empty = use the long links.")
    e_approval_email_webhook_path = fields.Char(
        string="Email Approval Webhook Path",
        help="The path to the webhook in n8n that will be used for approval/reject by email."
    )
    e_approval_ribbon_style = fields.Selection([
        ('statusbar', 'Odoo 12 statusbar (arrows)'),
        ('stepper', 'Stepper with names and dates'),
        ('badge', 'Compact stepper'),
    ], string="Ribbon Progress Layout", default='statusbar')
    # Global System-Wide Delivery Strategy Toggles
    global_notify_email = fields.Boolean(string="Global Email Notifications", default=True)
    global_notify_talk = fields.Boolean(string="Global Nextcloud Talk Alerts", default=False)
    
    # Nextcloud Talk API Endpoint Credentials
    nc_base_url = fields.Char(string="Nextcloud Instance URL")
    nc_bot_username = fields.Char(string="Nextcloud Bot Username")
    nc_bot_password = fields.Char(string="Nextcloud Bot Password",
                                  help="Leave empty to keep the saved password. It is never shown again.")
    nc_bot_password_status = fields.Char(string='Saved bot password', readonly=True)
    nc_bot_password_saved = fields.Boolean(readonly=True)

    @api.model
    def _secret_status(self, icp, key, saved_text, missing_text):
        return saved_text if icp.get_param(key) else missing_text

    # 2. EXTEND READ: Call super to read sync items, then append your specific keys
    @api.model
    def get_values(self):
        res = super(KderpEApprovalSettingsInherit, self).get_values()
        icp = self.env['ir.config_parameter'].sudo()
        
        res.update(
            n8n_analytic_webhook_url=icp.get_param('kderp_e_approval.n8n_analytic_webhook_url', default=''),
            e_approval_secret_key='',      # a secret is never sent to the browser
            e_approval_secret_key_saved=bool(icp.get_param('kderp_e_approval.e_approval_secret_key')),
            e_approval_secret_key_status=self._secret_status(icp, 'kderp_e_approval.e_approval_secret_key', _('A key is saved (type a new one only to change it)'), _('No key saved yet')),
            e_approval_email_webhook_path=icp.get_param('kderp_e_approval.e_approval_email_webhook_path', default=''),
            e_approval_short_link_path=icp.get_param('kderp_e_approval.short_link_webhook_path', default=''),
            e_approval_ribbon_style=icp.get_param('kderp_e_approval.ribbon_style', default='statusbar'),
            global_notify_email=icp.get_param('kderp_e_approval.global_notify_email', default='True') == 'True',
            global_notify_talk=icp.get_param('kderp_e_approval.global_notify_talk', default='False') == 'True',
            nc_base_url=icp.get_param('kderp_e_approval.nc_base_url', default=''),
            nc_bot_username=icp.get_param('kderp_e_approval.nc_bot_username', default=''),
            nc_bot_password='',
            nc_bot_password_saved=bool(icp.get_param('kderp_e_approval.nc_bot_password')),
            nc_bot_password_status=self._secret_status(icp, 'kderp_e_approval.nc_bot_password', _('A password is saved (type a new one only to change it)'), _('No password saved yet')),
        )
        return res

    # 3. EXTEND WRITE: Call super to write sync items, then save your specific keys
    def set_values(self):
        super(KderpEApprovalSettingsInherit, self).set_values()
        icp = self.env['ir.config_parameter'].sudo()
        
        icp.set_param('kderp_e_approval.n8n_analytic_webhook_url', (self.n8n_analytic_webhook_url or '').strip())
        if (self.e_approval_secret_key or '').strip():           # empty = keep the saved one
            icp.set_param('kderp_e_approval.e_approval_secret_key', self.e_approval_secret_key.strip())
        icp.set_param('kderp_e_approval.e_approval_email_webhook_path', (self.e_approval_email_webhook_path or '').strip())
        icp.set_param('kderp_e_approval.short_link_webhook_path', (self.e_approval_short_link_path or '').strip().strip('/'))
        icp.set_param('kderp_e_approval.ribbon_style', self.e_approval_ribbon_style)
        icp.set_param('kderp_e_approval.global_notify_email', str(self.global_notify_email))
        icp.set_param('kderp_e_approval.global_notify_talk', str(self.global_notify_talk))
        icp.set_param('kderp_e_approval.nc_base_url', (self.nc_base_url or '').strip('/'))
        icp.set_param('kderp_e_approval.nc_bot_username', self.nc_bot_username or '')
        if self.nc_bot_password:
            icp.set_param('kderp_e_approval.nc_bot_password', self.nc_bot_password)
