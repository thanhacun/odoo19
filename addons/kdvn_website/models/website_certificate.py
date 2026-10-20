from datetime import timedelta

from odoo import api, fields, models

REMIND_DAYS_PARAM = 'kdvn_website.certificate_remind_days'
DEFAULT_REMIND_DAYS = 60


class KdvnWebsiteCertificate(models.Model):
    """Licenses & certificates shown on /company-profile/licenses-certifications.

    Certificates change over time (ISO certificates are renewed, licenses
    expire): each record has a validity period. The website shows only
    published certificates that have not expired; a daily job gives the
    responsible person a "Renew" to-do some days before the expiry date.
    Renewing = upload the new scan and dates on the same record (or add a new
    record and archive the old one)."""
    _name = 'kdvn.website.certificate'
    _description = 'Website License / Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    _order = 'sequence, id'

    name = fields.Char('Title', required=True, translate=True, tracking=True,
                       help="e.g. 'ISO 9001:2015 - Quality Management System'. Used as the image's alt text.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    website_published = fields.Boolean('Show on Website', default=True, tracking=True)
    issuer = fields.Char('Issued By', help="e.g. BSI, SGS, Ministry of Construction.")
    certificate_number = fields.Char('Number')
    holder = fields.Char('Holder', help="Company or branch on the certificate, e.g. 'Kinden Vietnam - HCMC Branch'.")
    date_start = fields.Date('Valid From', tracking=True)
    date_end = fields.Date('Valid Until', tracking=True,
                           help="Expiry date. After this date the certificate is no longer shown on the website. "
                                "Leave empty for licenses without expiry.")
    user_id = fields.Many2one('res.users', 'Responsible', default=lambda self: self.env.user,
                              help="Gets a 'Renew' to-do before the expiry date.")
    note = fields.Text('Internal Note')
    validity_state = fields.Selection([
        ('valid', 'Valid'),
        ('expiring', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], string='Validity', compute='_compute_validity_state')
    days_left = fields.Integer('Days Left', compute='_compute_validity_state')

    _date_check = models.Constraint(
        'CHECK(date_start IS NULL OR date_end IS NULL OR date_start <= date_end)',
        "'Valid From' must be before 'Valid Until'.")

    @api.model
    def _kdvn_remind_days(self):
        value = self.env['ir.config_parameter'].sudo().get_param(REMIND_DAYS_PARAM)
        try:
            return int(value) if value else DEFAULT_REMIND_DAYS
        except ValueError:
            return DEFAULT_REMIND_DAYS

    @api.depends('date_end')
    def _compute_validity_state(self):
        today = fields.Date.context_today(self)
        remind = self._kdvn_remind_days()
        for cert in self:
            if not cert.date_end:
                cert.validity_state = 'valid'
                cert.days_left = 0
                continue
            cert.days_left = (cert.date_end - today).days
            if cert.date_end < today:
                cert.validity_state = 'expired'
            elif cert.days_left <= remind:
                cert.validity_state = 'expiring'
            else:
                cert.validity_state = 'valid'

    @api.model
    def _kdvn_website_domain(self):
        today = fields.Date.context_today(self)
        return [('website_published', '=', True), '|', ('date_end', '=', False), ('date_end', '>=', today)]

    @api.model
    def _kdvn_website_certificates(self):
        """Certificates to show on the website (sudo: visitors cannot read the model)."""
        return self.sudo().search(self._kdvn_website_domain())

    def _kdvn_image_url(self, size=1024):
        self.ensure_one()
        return '/company-profile/licenses-certifications/image/%s/%s' % (self.id, size)

    @api.model
    def _cron_renewal_reminders(self):
        """Daily: a 'Renew' to-do for certificates that expire within the
        reminder period (Settings: kdvn_website.certificate_remind_days)."""
        today = fields.Date.context_today(self)
        limit = today + timedelta(days=self._kdvn_remind_days())
        todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        certs = self.search([('date_end', '!=', False), ('date_end', '<=', limit), ('date_end', '>=', today)])
        for cert in certs:
            if todo and cert.activity_ids.filtered(lambda a: a.activity_type_id == todo):
                continue
            cert.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=cert.date_end,
                summary=self.env._("Renew certificate (expires %s)", cert.date_end),
                note=self.env._("Upload the new certificate scan and its validity dates on this record."),
                user_id=(cert.user_id or self.env.user).id,
            )
