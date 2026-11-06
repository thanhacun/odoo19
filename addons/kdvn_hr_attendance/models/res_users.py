from odoo import models


class ResUsers(models.Model):
    """User notifications used by the attendance code (OCA web_notify has no 19.0 version here): same four methods,
    sent as Odoo 19 core `simple_notification` bus messages, shown by the web client."""
    _inherit = 'res.users'

    def _kdvn_notify(self, message, title=None, notif_type='info', sticky=False):
        bus = self.env['bus.bus'].sudo()
        for user in self:
            bus._sendone(user.partner_id, 'simple_notification', {
                'title': title or '', 'message': message, 'sticky': sticky, 'type': notif_type})
        return True

    def notify_info(self, message='Default message', title=None, sticky=False, target=None):
        return self._kdvn_notify(message, title, 'info', sticky)

    def notify_warning(self, message='Default message', title=None, sticky=False, target=None):
        return self._kdvn_notify(message, title, 'warning', sticky)

    def notify_danger(self, message='Default message', title=None, sticky=False, target=None):
        return self._kdvn_notify(message, title, 'danger', sticky)

    def notify_success(self, message='Default message', title=None, sticky=False, target=None):
        return self._kdvn_notify(message, title, 'success', sticky)
