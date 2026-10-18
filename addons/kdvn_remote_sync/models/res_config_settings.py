import logging
import secrets

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_N8N_URL = 'kdvn_remote_sync.n8n_server_url'
PARAM_N8N_JOB_SYNC_URL = 'kdvn_remote_sync.n8n_webhook_job_sync_url'
PARAM_API_KEY = 'kdvn_remote_sync.api_key'


class ResConfigSettings(models.TransientModel):
    """Settings > Remote Sync."""
    _inherit = 'res.config.settings'

    kdvn_n8n_server_url = fields.Char('n8n Server URL', config_parameter=PARAM_N8N_URL)
    kdvn_n8n_webhook_job_sync_url = fields.Char('n8n Job Sync Trigger URL', config_parameter=PARAM_N8N_JOB_SYNC_URL)
    kdvn_remote_sync_api_key = fields.Char(
        'Sync API Key', config_parameter=PARAM_API_KEY,
        help="n8n must send this key in the X-API-Key header when posting to /api/v1/sync_jobs. "
             "Without a key the endpoint refuses all data.")

    def action_kdvn_generate_api_key(self):
        """Create a new random key (n8n must then be updated with it)."""
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param(PARAM_API_KEY, secrets.token_urlsafe(32))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_kdvn_trigger_n8n_sync(self):
        """Ask n8n to run the job sync now; n8n then posts the data to /api/v1/sync_jobs."""
        self.ensure_one()
        url = (self.env['ir.config_parameter'].sudo().get_param(PARAM_N8N_JOB_SYNC_URL) or '').strip()
        if not url:
            raise UserError(_("Fill in the 'n8n Job Sync Trigger URL' and save before running a sync."))
        try:
            response = requests.post(
                url, json={'triggered_by': self.env.user.name, 'source': 'res.config.settings'}, timeout=30)
        except requests.exceptions.RequestException as e:
            _logger.error("Remote sync: cannot reach n8n at %s: %s", url, e)
            raise UserError(_("Could not reach the n8n server: %s", e)) from e
        if response.status_code != 200:
            raise UserError(_("n8n answered with error status %s.", response.status_code))
        try:
            telemetry = (response.json() or {}).get('telemetry') or {}
        except ValueError:
            telemetry = {}
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Remote sync finished"),
                'message': _("Jobs: %(jobs)s, budgets: %(budgets)s, customers: %(customers)s",
                             jobs=telemetry.get('jobs_synced', 0),
                             budgets=telemetry.get('budgets_synced', 0),
                             customers=telemetry.get('customers_synced', 0)),
                'type': 'success',
                'sticky': False,
            },
        }
