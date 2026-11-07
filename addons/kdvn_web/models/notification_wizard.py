from odoo import api, fields, models


class KderpNotificationWizard(models.TransientModel):
    """Universal notification dialog (port of Odoo 12 kderp_web_infrastructure). Model name kept on purpose."""
    _name = 'kderp.notification.wizard'
    _description = 'Universal Notification & Operation Log Wizard'

    title = fields.Char(string='Form Title', default='System Notification')
    message = fields.Text(string='Message', required=True)
    show_cancel = fields.Boolean(string='Show Cancel Button', default=False)

    def action_ok(self):
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def show_notification_wizard(self, message, title='System Notification', show_cancel=False):
        """Action that opens a centred modal with the message.
        Usage: return self.env['kderp.notification.wizard'].show_notification_wizard("Text", "Title", True)"""
        view = self.env.ref('kdvn_web.view_kderp_notification_wizard_form')
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'kderp.notification.wizard',
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {'default_title': title, 'default_message': message, 'default_show_cancel': show_cancel},
        }
