from odoo import http, SUPERUSER_ID, _
from odoo.http import request
from odoo.tools import html2plaintext, html_escape
import json
import hmac
import hashlib
import logging

_logger = logging.getLogger(__name__)

class KderpEApprovalController(http.Controller):
    @http.route('/api/v1/sync_jobs_back', type='http', auth='none', methods=['POST'], csrf=False)
    def receive_external_jobs_back(self, **kwargs):
        """
        UNIFIED HTTP POST GATEWAY: Captures Jobs, Budgets, and Customer
        data packet streams from n8n and transfers them to the core pipeline.
        """
        try:
            # 1. Safely parse incoming payload strings from the n8n form data packet
            raw_jobs = kwargs.get('jobs_data', '[]')
            raw_budgets = kwargs.get('budgets_data', '[]')
            raw_customers = kwargs.get('customers_data', '[]')

            jobs_list = json.loads(raw_jobs)
            budgets_list = json.loads(raw_budgets)
            customers_list = json.loads(raw_customers)

        except Exception as e:
            _logger.error("Failed to parse incoming consolidated master payload data: %s", str(e))
            # --- FIXED: Odoo 12 HTTP 400 Error Return Format ---
            res = request.make_response(
                json.dumps({"status": "error", "message": "Malformed JSON Payloads: %s" % str(e)}),
                headers=[('Content-Type', 'application/json')]
            )
            res.status = '400 Bad Request' # Explicit property override assignment
            return res

        # 2. Forward execution payload straight to the core model sync master engine as Root Sudo Administrator
        try:
            sync_engine = request.env['kderp.job.lookup'].sudo()
            result = sync_engine.execute_master_sync_pipeline(
                jobs_data=jobs_list,
                budgets_data=budgets_list,
                customers_data=customers_list
            )
        except Exception as e:
            _logger.error("Database tracking crash occurred during sync pipeline execution: %s", str(e))
            # --- FIXED: Odoo 12 HTTP 500 Error Return Format ---
            res = request.make_response(
                json.dumps({"status": "error", "message": "Pipeline processing runtime failure: %s" % str(e)}),
                headers=[('Content-Type', 'application/json')]
            )
            res.status = '500 Internal Server Error' # Explicit property override assignment
            return res

        # 3. Return clean confirmation telemetry back to the n8n execution log (HTTP 200)
        return request.make_response(
            json.dumps({
                "status": "success",
                "telemetry": result
            }),
            headers=[('Content-Type', 'application/json')]
        )

    def _verify_hmac_token(self, secret_key, res_model, res_id, review_id, user_id, incoming_token):
        """ Re-calculates and verifies the cryptographic token data signature string """
        data_string = "%s-%s-%s-%s" % (res_model, res_id, review_id, user_id)
        calculated_token = hmac.new(
            secret_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(calculated_token, incoming_token)

    @http.route('/api/v1/mobile_review_action', type='jsonrpc', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors="*")
    def receive_mobile_review_action(self, **kwargs):
        """
        CENTRAL CONTROLLER HUB: Authenticates, inspects double-clicks, 
        and executes real-time sequential multi-tier workflow updates.
        """
        # Odoo's type='json' parser automatically maps the incoming params dictionary
        params = request.params
        # Short links: n8n forwards the code from ?c=...; model, record, user and action come from it
        if params.get('code'):
            parsed = request.env['kderp.e.approval.mixin'].sudo()._short_link_parse(params.get('code'))
            if not parsed:
                return {"status": "error", "message": "Security Alert: link is invalid or was changed."}
            review = parsed['review']
            params = dict(params, res_model=review.model, res_id=review.res_id, review_id=review.id,
                          user_id=parsed['user_id'], action=parsed['action'])
        res_model = params.get('res_model')
        res_id = params.get('res_id')
        review_id = params.get('review_id')
        user_id = params.get('user_id')
        action = params.get('action')
        comment = params.get('comment', '').strip()
        incoming_token = params.get('token')
        short_link = bool(params.get('code'))

        # 1. Parameter Validation Safe-Gate
        if not all([res_model, res_id, review_id, user_id]) or not (short_link or incoming_token):
            return {"status": "error", "message": "Missing vital transactional parameters."}

        # 2. Cryptographic Security Token Verification Check (short links were checked above)
        if not short_link:
            icp = request.env['ir.config_parameter'].sudo()
            secret_key = icp.get_param('kderp_e_approval.e_approval_secret_key')
            if not secret_key:
                return {"status": "error", "message": "E-Approval secret key is not configured."}
            if not self._verify_hmac_token(secret_key, res_model, res_id, review_id, user_id, incoming_token):
                return {"status": "error", "message": "Security Alert: Signature token verification failed."}

        # 3. Elevate execution context permissions
        env = request.env(user=int(user_id))
        record = env[res_model].browse(int(res_id))
        review_line = env['tier.review'].browse(int(review_id))

        if not record.exists() or not review_line.exists():
            return {"status": "error", "message": "The requested business document line references no longer exist."}

        # =====================================================================
        # 🚀 4. THE SINGLE UNIFIED DOUBLE-CLICK GUARD
        # =====================================================================
        if review_line.status in ['approved', 'rejected']:
            _logger.info("⚠️ Guard block intercepted double-click: Record %s was already completed.", record.name)
            return dict(self._review_summary(record, review_line),
                        status="already_processed",
                        message="This request step has already been reviewed previously.",
                        current_status=review_line.status,
                        done_by=review_line.sudo().done_by.name or '')

        # =====================================================================
        # 5. WORKFLOW ROUTING BRANCHES
        # =====================================================================
        try:
            if action == 'approve':
                # The user's pending reviews on this record (same rule as the Approve button)
                sequences = record._get_sequences_to_approve(env.user)
                reviews = record.review_ids.filtered(
                    lambda r: r.sequence in sequences and r.status == 'pending' and env.user in r.reviewer_ids)
                if review_line not in reviews:
                    return {"status": "error", "message": "This step is not waiting for your approval."}
                # Approval rule with "Comment" ticked: the approver must write a comment
                comment_required = any(reviews.mapped('has_comment'))
                # Opening a link (GET) must never approve on its own: chat link previews and
                # email security scanners open links automatically. Ask the user to confirm first.
                if not params.get('confirmed'):
                    return dict(self._review_summary(record, review_line), status="confirm",
                                comment_required=comment_required,
                                message="Please confirm your approval.")
                if comment_required and not comment:
                    return dict(self._review_summary(record, review_line), status="comment_required",
                                comment_required=True,
                                message="A comment is required to approve this step.")
                if comment:
                    reviews.write({'comment': comment})
                # Same steps as the comment wizard / validate_tier, without the wizard
                record.with_context(xml_id=res_model)._validate_tier(reviews)
                record._update_counter()
                review_line.invalidate_recordset()
                if review_line.status != 'approved':
                    _logger.error("Link approval did not approve review %s (%s %s)", review_line.id, res_model, res_id)
                    return {"status": "error", "message": "The approval could not be recorded. Please open the request in Odoo."}
                record.message_post(body="📱 <b>Approved Securely</b> via single-use mobile token transaction link.")
                return {"status": "approved", "message": "Approved successfully."}

            elif action == 'reject':
                summary = self._review_summary(record, review_line)
                if not comment:
                    return dict(summary, status="rejecting", message="Rejection comment needed.")
                record.with_context(xml_id=res_model, remote_rejection_comment=comment).reject_tier()
                review_line.invalidate_recordset()
                if review_line.status != 'rejected':
                    _logger.error("Link rejection did not reject review %s (%s %s)", review_line.id, res_model, res_id)
                    return {"status": "error", "message": "The rejection could not be recorded. Please open the request in Odoo."}
                record.message_post(body="📱 <b>Rejected Securely via Mobile Link</b><br/><b>Reason:</b> %s"
                                         % html_escape(comment))
                return dict(summary, status="rejected", comment=comment,
                            message="Rejection processed successfully.")
            else:
                return {"status": "error", "message": "Unknow error"}
                
        except Exception as e:
            _logger.error("Database constraint fault during validation loop update: %s", str(e))
            return {"status": "error", "message": "Database validation transition error: %s" % str(e)}

        return {"status": "error", "message": "Invalid workflow routing signature instruction."}


    def _review_summary(self, record, review_line):
        """Short description of the request, shown on the confirmation page."""
        rec = record.sudo()
        details = ''
        try:
            details = html2plaintext(str(rec.get_approval_digest_details() or ''))
        except Exception:
            details = rec.reason or ''
        details = ' · '.join(' '.join(l.split()) for l in details.replace('*', '').splitlines() if l.strip())
        special = [l.strip() for l in (rec.special_reasons or '').splitlines() if l.strip()] \
            if getattr(rec, 'special_case', 'normal') == 'special' else []
        if special:
            # Shown first on the confirmation page (the current n8n page prints "details")
            details = ('Special case: %s' % '; '.join(special)) + (' · ' + details if details else '')
        total = max(rec.review_ids.mapped('sequence') or [0])
        return {
            "ref": rec.name or '',
            "title": rec.approval_procedure_title or rec._description,
            "applicant": rec.employee_id.name or rec.create_uid.name or '',
            "step": "Step %s of %s: %s" % (review_line.sequence, total,
                                           review_line.definition_id.frontend_name or review_line.name or ''),
            "details": details,
            "special_reasons": special,
        }

    @http.route('/api/v1/verify_approval', type='http', auth='none', methods=['GET'], csrf=False)
    def verify_approval_token(self, model=None, id=None, token=None, **kwargs):
        """
        Public Headless Gateway: Verifies token integrity against live database 
        records without requiring standard user credentials session logs.
        """
        if not model or not id or not token:
            return "<h3>Invalid Request: Missing Verification Parameters</h3>"

        try:
            # 1. Public page: read as superuser. uid 2 (admin) is not a superuser in Odoo 12 and
            #    is limited by record rules (e.g. "own requests only"), so it could not read
            #    requests created by other users. Access is granted by the signed token below.
            env = request.env(user=SUPERUSER_ID)
            
            # Fetch the secret key safely
            secret_key = env['ir.config_parameter'].get_param('kderp_e_approval.e_approval_secret_key')
            # Only e-approval documents can be verified (model comes from the URL)
            if model not in env or 'verification_url' not in env[model]._fields:
                return "<h3>Verification Failure: Unknown document type.</h3>"
            record = env[model].browse(int(id))
            
            if not record.exists():
                return "<h3>Verification Failure: Target record does not exist.</h3>"

            # 2. Recalculate signature to verify against tampering
            amount = getattr(record, 'estimated_amount', 0.0)
            message = "%s-%s-%s" % (model, id, amount)
            
            # expected_signature = hmac.new(
            #     key=secret_key.encode('utf-8'),
            #     msg=message.encode('utf-8'),
            #     digestmod=hashlib.sha256
            # ).hexdigest()

            expected_signature = env['kderp.e.approval.mixin'].generate_secure_signature(message)

            # 3. Perform a secure, constant-time comparison check
            if not expected_signature or not hmac.compare_digest(str(token), str(expected_signature)):
                # Token did not match or record variables were modified! Show no document details.
                return self._render_verification_card(status="failed", record=env[model].browse())

            # 4. Check if the document state is explicitly Approved
            if record.state != 'approved':
                return self._render_verification_card(status="pending_or_rejected", record=record)

            # Success: Token matches and record state is fully approved
            return self._render_verification_card(status="success", record=record)

        except Exception as e:
            _logger.exception("Approval verification failed for %s %s", model, id)
            return "<h3>Internal Execution Error: %s</h3>" % html_escape(str(e))

    def _render_verification_card(self, status, record):
        """ Small self-contained HTML card (no external CSS) shown when the QR code is scanned. """
        state_label = lambda r: dict(r._fields['state'].selection).get(r.state, r.state) or '-'
        if status == "success":
            color, title = "#28a745", "VERIFIED AUTHENTIC"
            msg = "This request is fully authorized and cleared for settlement processing."
        elif status == "pending_or_rejected":
            color, title = "#7C7BAD", "NOT APPROVED"
            msg = "The link is valid, but the document is currently '%s'." % (state_label(record) if record else '-')
        else:
            color, title = "#dc3545", "INVALID LINK"
            msg = "This verification link does not match any approved document. It may have been altered."

        rows = []
        if record:
            applicant = record.employee_id if 'employee_id' in record._fields else False
            rows = [
                ("Document", getattr(record, '_approval_procedure_title', '') or record._description),
                ("Reference", record.name or '-'),
                ("Applicant", (applicant.name if applicant else record.create_uid.name) or '-'),
            ]
            if 'estimated_amount' in record._fields:
                rows.append(("Amount", "VND {:,.0f}".format(record.estimated_amount or 0.0).replace(',', '.')))
            rows.append(("Status", state_label(record)))
        table = ''.join(
            '<tr><td style="padding:6px 16px 6px 0;color:#6c757d;white-space:nowrap">%s</td>'
            '<td style="padding:6px 0;font-weight:bold">%s</td></tr>' % (html_escape(k), html_escape(v))
            for k, v in rows)

        return """<!DOCTYPE html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Approval verification</title></head>
<body style="margin:0;background:#f8f9fa;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#212529">
<div style="max-width:480px;margin:32px auto;padding:0 16px">
<div style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.1)">
<div style="background:%s;color:#fff;padding:20px 24px;font-size:20px;font-weight:bold">%s</div>
<div style="padding:20px 24px">
<p style="margin:0 0 16px">%s</p>
<table style="border-collapse:collapse;font-size:15px">%s</table>
</div></div>
<p style="text-align:center;color:#adb5bd;font-size:12px">KDERP e-Approval</p>
</div></body></html>""" % (color, title, html_escape(msg), table)
