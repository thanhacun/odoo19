import logging

from odoo import api, fields, models
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)

INQUIRY_EMAIL_PARAM = 'kdvn_website.inquiry_email'


class KdvnWebsiteInquiryType(models.Model):
    """Options of the 'Inquiry type' list on the website inquiry form."""
    _name = 'kdvn.website.inquiry.type'
    _description = 'KDVN Website Inquiry Type'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class KdvnWebsiteInquiry(models.Model):
    """A message sent with the website inquiry form (/contactus)."""
    _name = 'kdvn.website.inquiry'
    _description = 'KDVN Website Inquiry'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'
    _rec_name = 'contact_name'

    contact_name = fields.Char('Full Name', required=True)
    company_name = fields.Char('Company')
    email = fields.Char(required=True)
    phone = fields.Char()
    inquiry_type_id = fields.Many2one('kdvn.website.inquiry.type', string='Inquiry Type', ondelete='restrict')
    message = fields.Text()
    state = fields.Selection([('new', 'New'), ('done', 'Handled')], default='new', required=True,
                             tracking=True)
    website_id = fields.Many2one('website', readonly=True)
    lang = fields.Char('Language', readonly=True)

    def action_set_done(self):
        self.write({'state': 'done'})

    def action_set_new(self):
        self.write({'state': 'new'})

    @api.model
    def _kdvn_notify_email(self):
        """Who receives new inquiries: Settings > Website > Inquiry form, else the company email."""
        param = self.env['ir.config_parameter'].sudo().get_param(INQUIRY_EMAIL_PARAM)
        return param or self.env.company.email or ''

    @api.model
    def _kdvn_create_from_website(self, values):
        """Create an inquiry from form values (already checked by the controller)
        and queue the notification email."""
        inquiry = self.sudo().create(values)
        template = self.env.ref('kdvn_website.mail_template_website_inquiry', raise_if_not_found=False)
        if template and inquiry._kdvn_notify_email():
            template.sudo().send_mail(inquiry.id)
        else:
            _logger.warning("Website inquiry %s: no recipient set, no email sent", inquiry.id)
        return inquiry

    @api.model
    def _kdvn_clean_email(self, email):
        return email_normalize(email or '') or False


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kdvn_inquiry_email = fields.Char(
        'Inquiry Form Recipients', config_parameter=INQUIRY_EMAIL_PARAM,
        help="Email address(es), comma separated, that receive messages sent with the website "
             "inquiry form. Empty: the company email.")
