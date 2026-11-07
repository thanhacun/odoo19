"""Stock report of the safety tool store in the layout of the old Excel 'Safety Tool Control Sheet'
(one block per item / size: opening line, one row per move with a running remaining quantity)."""
import base64
import datetime
import io

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SafetyToolReportWizard(models.TransientModel):
    _name = 'safety.tool.report.wizard'
    _description = 'Safety Tool Control Sheet (Excel export)'

    date_from = fields.Date(string='From', required=True,
                            default=lambda s: fields.Date.context_today(s).replace(day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    item_ids = fields.Many2many('safety.tool.item', string='Only these items', help='Empty = all items.')
    file = fields.Binary(string='Excel file', readonly=True)
    filename = fields.Char(readonly=True)

    def action_generate(self):
        self.ensure_one()
        if not self.env['safety.tool.request']._is_tool_admin():
            raise UserError(_('Only the Safety Tool Admin staff can print the control sheet.'))
        if self.date_from > self.date_to:
            raise UserError(_('"From" must be before "To".'))
        import xlsxwriter
        out = io.BytesIO()
        book = xlsxwriter.Workbook(out, {'in_memory': True})
        sheet = book.add_worksheet('Safety tool control sheet')
        title = book.add_format({'bold': True, 'font_size': 14})
        head = book.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'align': 'center'})
        block = book.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1})
        cell = book.add_format({'border': 1})
        num = book.add_format({'border': 1, 'num_format': '#,##0.##'})
        datef = book.add_format({'border': 1, 'num_format': 'dd/mm/yyyy', 'align': 'left'})
        for col, width in enumerate([6, 34, 16, 12, 34, 10, 24, 8, 8, 9, 40]):
            sheet.set_column(col, col, width)
        sheet.write(0, 0, _('Safety Tool Control Sheet'), title)
        sheet.write(1, 0, _('From %s to %s') % (self.date_from.strftime('%d/%m/%Y'), self.date_to.strftime('%d/%m/%Y')))
        for col, label in enumerate([_('No.'), _('Item'), _('Size'), _('Date'), _('Project'), _('PIC'), _('PIC name'),
                                     _('IN'), _('OUT'), _('Remain'), _('Remarks')]):
            sheet.write(3, col, label, head)
        Move = self.env['safety.tool.move'].sudo()
        items = self.item_ids or self.env['safety.tool.item'].sudo().search([])
        before = Move.stock_map(items.ids, upto=self.date_from - datetime.timedelta(days=1))
        moves = Move.search([('item_id', 'in', items.ids), ('date', '>=', self.date_from), ('date', '<=', self.date_to)],
                            order='date, id')
        by_key = {}
        for m in moves:
            by_key.setdefault((m.item_id.id, m.size_id.id or False), []).append(m)
        row = 4
        source = dict(Move._fields['source'].selection)
        for item in items.sorted(lambda i: (i.sequence, i.code or '', i.name)):
            keys = [(item.id, size.id) for size in item.size_ids] if item.size_ids else [(item.id, False)]
            for key in keys:
                opening = before.get(key, 0.0)
                rows = by_key.get(key, [])
                if not opening and not rows:
                    continue
                size = self.env['safety.tool.size'].browse(key[1]) if key[1] else False
                sheet.write(row, 0, item.code or '', block)
                sheet.write(row, 1, item.name, block)
                sheet.write(row, 2, size.name if size else '', block)
                sheet.write(row, 3, self.date_from - datetime.timedelta(days=1), datef)
                for col in range(4, 9):
                    sheet.write(row, col, '', cell)
                sheet.write(row, 9, opening, num)
                sheet.write(row, 10, _('Opening balance'), cell)
                row += 1
                remain = opening
                for m in rows:
                    remain += m.qty_in - m.qty_out
                    sheet.write(row, 0, '', cell)
                    sheet.write(row, 1, '', cell)
                    sheet.write(row, 2, '', cell)
                    sheet.write(row, 3, m.date, datef)
                    sheet.write(row, 4, m.job_id.display_name if m.job_id else (m.note or ''), cell)
                    sheet.write(row, 5, m.employee_id.code or '', cell)
                    sheet.write(row, 6, m.employee_id.name or '', cell)
                    sheet.write(row, 7, m.qty_in or '', num)
                    sheet.write(row, 8, m.qty_out or '', num)
                    sheet.write(row, 9, remain, num)
                    sheet.write(row, 10, ' / '.join(x for x in (source.get(m.source, ''), m.request_id.name, m.note if m.job_id else '') if x), cell)
                    row += 1
                row += 1
        book.close()
        self.write({'file': base64.b64encode(out.getvalue()),
                    'filename': 'Safety_Tool_control_sheet_%s_%s.xlsx' % (self.date_from, self.date_to)})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new', 'name': _('Safety Tool Control Sheet')}
