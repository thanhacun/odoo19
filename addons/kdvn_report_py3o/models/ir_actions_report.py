import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

try:
    from py3o.formats import Formats
except ImportError:
    _logger.debug('Cannot import py3o.formats')


class IrActionsReport(models.Model):
    """py3o.formats of the container knows no 'xlsx' (only 'xls'). The report is converted by LibreOffice with
    `--convert-to <filetype>`, which accepts xlsx, so the type only has to be offered and treated as non native."""
    _inherit = 'ir.actions.report'

    @api.model
    def _get_py3o_filetypes(self):
        return (super()._get_py3o_filetypes() or []) + [('xlsx', 'Excel (xlsx)')]

    @api.depends('report_type', 'py3o_filetype')
    def _compute_is_py3o_native_format(self):
        known = Formats().get_known_format_names()
        for rec in self:
            if rec.py3o_filetype in known or not rec.py3o_filetype:
                super(IrActionsReport, rec)._compute_is_py3o_native_format()
            else:
                rec.is_py3o_native_format = False

    @api.model
    def _py3o_ids_from_context(self, res_ids, data):
        """The web client sends a report with `data` as /report/py3o/<name>?options=..&context=.. : the ids are not in
        the URL, only in the context (active_ids). The OCA controller passes None, which crashes (len(None)).
        Used by every print button that passes `data` (approval procedures, attendance wizards)."""
        if res_ids is None:
            res_ids = ((data or {}).get('context') or {}).get('active_ids') or []
        return res_ids

    @api.model
    def _render_py3o(self, report_ref, res_ids, data=None):
        return super()._render_py3o(report_ref, self._py3o_ids_from_context(res_ids, data), data=data)

    def gen_report_download_filename(self, res_ids, data):
        return super().gen_report_download_filename(self._py3o_ids_from_context(res_ids, data), data)
