import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class KderpCustomerCache(models.Model):
    _inherit = 'kderp.customer.cache'

    @api.model
    def _clients_with_request_refs(self, clients):
        """A client registered on the remote server names an entertainment request in its Notes: that request gets the client in place of
        the 'New Client' placeholder (only a request that still holds the placeholder is touched, so running again changes nothing)."""
        res = super()._clients_with_request_refs(clients)
        Request = self.env['entertainment.request'].sudo()
        for client in clients:
            if client.code == Request.NEW_CLIENT_CODE:
                continue
            refs = [r for r in (client.request_refs or '').split(',') if r]
            for request in Request.search([('name', 'in', refs)]):
                request._replace_new_client(client)
        return res
