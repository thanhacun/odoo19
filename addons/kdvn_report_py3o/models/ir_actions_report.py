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
