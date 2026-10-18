import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

API_KEY_HEADER = 'X-API-Key'


class KdvnRemoteSyncController(http.Controller):

    @http.route('/api/v1/sync_jobs', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_external_jobs(self, **kwargs):
        """n8n posts jobs_data, budgets_data and customers_data (JSON strings
        in form fields, as for Odoo 12; a JSON body with the same three keys
        also works) with the API key in the X-API-Key header."""
        expected = request.env['ir.config_parameter'].sudo().get_param('kdvn_remote_sync.api_key') or ''
        given = request.httprequest.headers.get(API_KEY_HEADER, '')
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            _logger.warning("Remote sync: rejected request from %s (missing or wrong API key)",
                            request.httprequest.remote_addr)
            return request.make_json_response(
                {'status': 'error', 'message': 'Missing or invalid API key'}, status=401)

        try:
            payload = self._read_payload(kwargs)
        except (ValueError, TypeError) as e:
            _logger.warning("Remote sync: malformed payload: %s", e)
            return request.make_json_response(
                {'status': 'error', 'message': 'Malformed JSON payload: %s' % e}, status=400)

        try:
            telemetry = request.env['kderp.job.lookup'].sudo().execute_master_sync_pipeline(**payload)
        except Exception as e:
            _logger.exception("Remote sync: pipeline failed")
            request.env.cr.rollback()
            return request.make_json_response(
                {'status': 'error', 'message': 'Pipeline processing failure: %s' % e}, status=500)

        return request.make_json_response({'status': 'success', 'telemetry': telemetry})

    @staticmethod
    def _read_payload(kwargs):
        keys = ('jobs_data', 'budgets_data', 'customers_data')
        if request.httprequest.mimetype == 'application/json':
            body = json.loads(request.httprequest.get_data(as_text=True) or '{}')
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            values = {key: body.get(key) or [] for key in keys}
        else:
            values = {key: json.loads(kwargs.get(key) or '[]') for key in keys}
        for key, value in values.items():
            if isinstance(value, str):
                value = values[key] = json.loads(value)
            if not isinstance(value, list):
                raise ValueError("%s must be a list" % key)
        return values
