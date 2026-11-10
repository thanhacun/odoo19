"""Excel reports of the safety tool store, in the layout of the original 'Safety Tool Control Sheet' file:
- sheet 'Safety tool control sheet' (always): one block per item / size, opening line (yellow), one row per move, running remain;
- for the Accounting Dept. also 'Detail check - report to Acc. D' (supplier invoice > stock-in lot > tools taken from it, FIFO, unit cost) and
  'Code.Mat' (totals per material code). Accounting adds information and imports the file into their software: keep the columns."""
import base64
import datetime
import io
import re
import textwrap

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.image import image_process

MONEY = '_-* #,##0\\ _\u20ab_-;\\-* #,##0\\ _\u20ab_-;_-* "-"??\\ _\u20ab_-;_-@_-'
RED, BLUE = '#FF0000', '#003399'


def _short_receipt(no):
    """SM-26-0163 -> 26-163 (how the paper forms and the old sheets write it)."""
    m = re.match(r'^SM-(\d{2})-0*(\d+)$', no or '')
    return '%s-%s' % (m.group(1), m.group(2)) if m else (no or '')


def _picture(image, size, expand=False):
    """PNG bytes of an item photo (field value = base64) resized to fit `size`. Odoo 19: image_process (Odoo 12: tools.image_resize_image)."""
    return image_process(base64.b64decode(image), size=size, expand=expand, output_format='PNG')


def _item_number(code):
    """ST0034-1 -> 34-1 (item number of the control sheet)."""
    m = re.match(r'^ST0*(\d+)(-\d+)?', code or '')
    return ('%s%s' % (m.group(1), m.group(2) or '')) if m else (code or '')


class SafetyToolReportWizard(models.TransientModel):
    _name = 'safety.tool.report.wizard'
    _description = 'Safety Tool Control Sheet (Excel export)'

    date_from = fields.Date(string='From', required=True,
                            default=lambda s: fields.Date.context_today(s).replace(month=1, day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    item_ids = fields.Many2many('safety.tool.item', string='Only these items', help='Empty = all items.')
    accounting = fields.Boolean(string='For the Accounting Dept.', default=False,
                                help='Adds the sheets "Detail check - report to Acc. Dept" (supplier invoice, stock-in, tools taken from it, FIFO, '
                                     'unit cost) and "Code.Mat" (totals per material code). They cover everything up to "To". '
                                     'Accounting adds its information and imports the file: keep the columns as they are.')
    refresh_remote = fields.Boolean(string='Refresh payment / invoice data from the remote server', default=True,
                                    help='Stock-ins that have a Payment No. but no invoice, or an invoice but no Payment No., are read from the remote server first.')
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
        if self.accounting and self.refresh_remote:
            self._refresh_from_remote()
        self._write_control_sheet(book)
        if self.accounting:
            self._write_accounting_sheets(book)
        book.close()
        self.write({'file': base64.b64encode(out.getvalue()),
                    'filename': 'Safety_Tool_control_sheet_%s%s.xlsx' % (self.date_to, '_ACC' if self.accounting else '')})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new', 'name': _('Safety Tool Control Sheet')}

    # ------------------------------------------------------------------
    # Sheet 1: Safety tool control sheet
    # ------------------------------------------------------------------
    def _report_no(self):
        batch = self.env['safety.tool.import.batch'].sudo().search([('report_no', '!=', False)], order='id desc', limit=1)
        no = (batch.report_no or '').strip()
        return ('No.%s' % no) if no.isdigit() else no

    def _outstanding(self):
        """{(item_id, size_id): (requested by staff and not handed over yet, of which already ordered with the supplier)}"""
        res = {}
        for req in self.env['safety.tool.request'].sudo().search([('state', '=', 'approved'),
                                                                  ('fulfilment_state', 'in', ['to_issue', 'to_purchase', 'ordered'])]):
            for line in req.line_ids:
                key = (line.item_id.id, line.size_id.id or False)
                asked, ordered = res.get(key, (0.0, 0.0))
                res[key] = (asked + line.qty, ordered + (line.qty if req.fulfilment_state == 'ordered' else 0.0))
        return res

    @staticmethod
    def _who(move):
        """(project / supplier text, PIC code, PIC name) of a move"""
        emp = move.employee_id.sudo()          # hr.employee is private in Odoo 19: the store keeper reads code and name as superuser
        parts = (move.note or '').split(' / ') if not emp else []
        code = emp.code or (parts[0] if parts and re.match(r'^[A-Za-z]\d+$', parts[0].strip()) else '')
        name = emp.name or (parts[1] if code and len(parts) > 1 else '')
        if move.qty_in:
            project = move.supplier_name or ''
        else:
            project = (move.job_id.display_name if move.job_id else (move.request_id.import_project_text or '')) or ''
            if code and not emp and len(parts) > 2:           # a plain move imported from the Excel: 'S1234 / name / project / remark'
                project = parts[2]
        return project, code, name

    def _write_control_sheet(self, book):
        sheet = book.add_worksheet('Safety tool control  sheet')
        cache = {}

        def fm(**kw):
            base = {'font_name': 'Arial', 'font_size': 10, 'valign': 'vcenter'}
            base.update(kw)
            key = tuple(sorted(base.items()))
            if key not in cache:
                cache[key] = book.add_format(base)
            return cache[key]
        edge = dict(left=1, right=1, top=4, bottom=4)                    # thin sides, hair rows
        for col, width in enumerate([1.7, 6.9, 28.7, 14.7, 14.7, 22.3, 10.9, 22.6, 10.7, 10.7, 10.7, 26.7, 24, 24, 24, 8.9]):
            sheet.set_column(col, col, width)
        sheet.set_row(0, 22.15)
        sheet.set_row(1, 22.15)
        sheet.write(1, 1, 'Safety Tool Control Sheet', fm(bold=True, font_size=14))
        sheet.write_datetime(1, 14, datetime.datetime.combine(self.date_to, datetime.time()), fm(bold=True, font_size=9, align='right', num_format='dd-mmm-yy'))
        sheet.write(2, 14, self._report_no(), fm())
        head = fm(border=1, align='center', text_wrap=True)
        sheet.set_row(3, 22.15)
        sheet.set_row(4, 22.15)
        sheet.set_row(5, 7.9)
        sheet.merge_range(3, 1, 4, 1, 'No.', head)
        sheet.merge_range(3, 2, 4, 3, 'Item', head)
        sheet.merge_range(3, 4, 4, 4, 'Date', head)
        sheet.merge_range(3, 5, 4, 5, 'Project Name', head)
        sheet.merge_range(3, 6, 4, 7, 'PIC', head)
        sheet.merge_range(3, 8, 3, 10, "Q'ty", head)
        for col, label in ((8, 'IN'), (9, 'OUT'), (10, 'Remain')):
            sheet.write(4, col, label, head)
        sheet.merge_range(3, 11, 4, 11, 'Remarks', head)
        sheet.merge_range(3, 12, 4, 12, 'Request from Kinden staff', head)
        sheet.merge_range(3, 13, 4, 13, 'Already order with supplier', head)
        sheet.merge_range(3, 14, 4, 14, 'Now order with supplier', head)
        sheet.freeze_panes(5, 0)
        sheet.repeat_rows(0, 5)
        sheet.set_paper(9)
        sheet.fit_to_pages(1, 0)
        sheet.set_margins(0.4, 0.4, 0.5, 0.5)

        Move = self.env['safety.tool.move'].sudo()
        items = self.item_ids or self.env['safety.tool.item'].sudo().search([])
        day_before = self.date_from - datetime.timedelta(days=1)
        before = Move.stock_map(items.ids, upto=day_before)
        moves = Move.search([('item_id', 'in', items.ids), ('date', '>=', self.date_from), ('date', '<=', self.date_to),
                             ('accounting_only', '=', False)], order='date, id')
        by_key = {}
        for m in moves:
            by_key.setdefault((m.item_id.id, m.size_id.id or False), []).append(m)
        outstanding = self._outstanding()
        Size = self.env['safety.tool.size']
        yellow = dict(bg_color='#FFFF00', bold=True)
        D = lambda d: datetime.datetime.combine(d, datetime.time())
        r = 6
        for item in items.sorted(lambda i: (i.code or '~', i.sequence, i.name)):
            keys = [(item.id, size.id) for size in item.size_ids] if item.size_ids else [(item.id, False)]
            for key in keys:
                opening = before.get(key, 0.0)
                rows = by_key.get(key, [])
                asked, ordered = outstanding.get(key, (0.0, 0.0))
                if not opening and not rows and not asked:
                    continue
                size = Size.browse(key[1]) if key[1] else Size
                # the name goes over the first rows of the block (column C), the picture sits in column D, as in the original
                lines = textwrap.wrap(item.name or '', 26) + (textwrap.wrap(size.name, 26) if size else [])
                total = max(1 + len(rows), len(lines), 4)
                remain, prev, first = opening, None, r
                for i in range(total):
                    sheet.set_row(r, 22.15)
                    text = lines[i] if i < len(lines) else ''
                    sheet.write(r, 1, _item_number(Size.code_of(item, size)) if i == 0 else '', fm(bold=True, align='center', **edge))
                    sheet.write(r, 2, text, fm(bold=True, left=1))
                    if i == 0:
                        sheet.write(r, 3, '', fm(right=1))
                        sheet.write_datetime(r, 4, D(day_before), fm(num_format='d-mmm-yy', align='center', **dict(edge, **yellow)))
                        for col in (5, 6, 7, 8, 9):
                            sheet.write(r, col, '', fm(**dict(edge, **yellow)))
                        sheet.write_number(r, 10, opening, fm(align='center', **dict(edge, **yellow)))
                        sheet.write(r, 11, 'Periodical check', fm(**dict(edge, **yellow)))
                        sheet.write(r, 12, asked, fm(align='center', **edge)) if asked else sheet.write(r, 12, '', fm(**edge))
                        sheet.write(r, 13, ordered, fm(align='center', **edge)) if ordered else sheet.write(r, 13, '', fm(**edge))
                        sheet.write(r, 14, '', fm(**edge))
                    elif i <= len(rows):
                        m = rows[i - 1]
                        project, code, name = self._who(m)
                        sheet.write(r, 3, '', fm(right=1))
                        sheet.write_datetime(r, 4, D(m.date), fm(num_format='d-mmm-yy', align='center', **edge))
                        sheet.write(r, 5, project, fm(align='left', **edge))
                        sheet.write(r, 6, code, fm(align='left', **edge))
                        sheet.write(r, 7, name, fm(align='left', **dict(edge, left=0)))
                        sheet.write(r, 8, m.qty_in or '', fm(align='center', **edge))
                        sheet.write(r, 9, m.qty_out or '', fm(align='center', **edge))
                        remain += m.qty_in - m.qty_out
                        sheet.write_formula(r, 10, '=K%d%s%s' % (prev + 1, '+I%d' % (r + 1) if m.qty_in else '', '-J%d' % (r + 1) if m.qty_out else ''),
                                            fm(align='center', **edge), remain)
                        if m.qty_in:
                            remark = ('Invoice No. %s' % m.invoice_no) if m.invoice_no else (m.note or '')
                            sheet.write(r, 11, remark, fm(bold=bool(m.invoice_no), align='left', **edge))
                        else:
                            parts = (m.note or '').split(' / ')
                            plain = ' / '.join(parts[3:]) if code and not m.employee_id and len(parts) > 3 else ('' if code and not m.employee_id else (m.note or ''))
                            sheet.write(r, 11, _short_receipt(m.receipt_no) or ('' if m.request_id else plain), fm(align='left', **edge))
                        for col in (12, 13, 14):
                            sheet.write(r, col, '', fm(**edge))
                    else:                                                 # empty rows under the last move: the picture needs the room
                        for col in range(3, 15):
                            sheet.write(r, col, '', fm(**dict(edge, left=1) if col == 3 else edge))
                    prev = r
                    r += 1
                if item.image:
                    try:
                        sheet.insert_image(first, 3, 'item%s.png' % item.id, {'image_data': io.BytesIO(_picture(item.image, (96, 64), expand=True)),
                                                                              'x_offset': 4, 'y_offset': 3, 'object_position': 1})
                    except Exception:
                        pass
                sheet.set_row(r, 22.15)
                r += 1
        sheet.print_area(0, 1, max(r, 7), 15)

    def _refresh_from_remote(self):
        todo = self.env['safety.tool.move'].sudo().search([('qty_in', '>', 0), ('source', '=', 'purchase'), '|',
                                                           '&', ('payment_no', '!=', False), ('invoice_no', '=', False),
                                                           '&', ('payment_no', '=', False), ('invoice_no', '!=', False)])
        for move in todo:
            try:
                move.action_fetch_remote()
            except UserError:
                continue          # remote not reachable / number unknown: the lot stays as it is

    # ------------------------------------------------------------------
    # FIFO
    # ------------------------------------------------------------------
    def _fifo_lots(self, upto):
        """[(code, name, lot, [(move, qty, unit_cost)])] : every stock-in lot per material code with the OUT moves
        taken from it, oldest lot first (FIFO). A handover that was reversed is left out (net quantity)."""
        Move = self.env['safety.tool.move'].sudo()
        moves = Move.search([('date', '<=', upto)], order='date, id')
        reversed_qty = {}
        for m in moves.filtered(lambda m: m.source == 'reverse'):
            reversed_qty[m.line_id.id] = reversed_qty.get(m.line_id.id, 0.0) + m.qty_in
        Size = self.env['safety.tool.size']
        codes = {}
        # a code with accounting history (older lots of the Excel file) is costed from that history: its opening balance is inside it
        with_history = {(m.item_id.id, m.size_id.id) for m in moves if m.accounting_only}
        for m in moves:
            if m.source == 'reverse' or (m.source == 'opening' and (m.item_id.id, m.size_id.id) in with_history):
                continue
            code = Size.code_of(m.item_id, m.size_id) or ('ITEM-%s' % m.item_id.id)
            entry = codes.setdefault(code, {'name': m.item_id.name + (' - %s' % m.size_id.name if m.size_id else ''),
                                            'lots': [], 'outs': []})
            if m.qty_in:
                entry['lots'].append({'move': m, 'qty': m.qty_in, 'left': m.qty_in, 'outs': []})
            else:
                qty = m.qty_out - (reversed_qty.get(m.line_id.id, 0.0) if m.line_id else 0.0)
                if qty > 0:
                    entry['outs'].append((m, qty))
        result = []
        for code in sorted(codes):
            entry = codes[code]
            lots = entry['lots']
            orphan = {'move': False, 'qty': 0.0, 'left': 0.0, 'outs': []}
            for out, qty in entry['outs']:
                for lot in lots:
                    if qty <= 0:
                        break
                    take = min(lot['left'], qty)
                    if take > 0:
                        lot['left'] -= take
                        lot['outs'].append((out, take))
                        qty -= take
                if qty > 0:
                    orphan['outs'].append((out, qty))
            if orphan['outs']:
                lots = lots + [orphan]
            result.append((code, entry['name'], lots))
        return result


    # ------------------------------------------------------------------
    # Sheets 2 and 3: for the Accounting Dept.
    # ------------------------------------------------------------------
    def _write_accounting_sheets(self, book):
        cache = {}

        def fm(**kw):
            base = {'font_name': 'Times New Roman', 'font_size': 12, 'valign': 'vcenter'}
            base.update(kw)
            key = tuple(sorted(base.items()))
            if key not in cache:
                cache[key] = book.add_format(base)
            return cache[key]
        hair = dict(left=4, right=4, top=4, bottom=4)
        dmy = 'd mmmm yyyy'
        lots = self._fifo_lots(self.date_to)
        Size = self.env['safety.tool.size']

        # ---- regroup: supplier invoice > lots (code order) ; each lot keeps its OUT rows
        groups = {}
        for code, name, lot_list in lots:
            for lot in lot_list:
                m = lot['move']
                key = (m.payment_no or '', m.invoice_no or '', m.invoice_date, m.supplier_name or '') if m else ('', '', None, '')
                groups.setdefault(key, []).append((code, name, lot))
        order = sorted(groups, key=lambda k: (k[2] is None, k[2] or datetime.date.min, k[1], k[0]))

        ws = book.add_worksheet('Detail check - report to Acc. D')
        for col, width in enumerate([12, 11.3, 47.4, 12.4, 22.6, 9, 19.4, 10, 18.9, 16.7, 16.7, 16.7, 16.7, 14, 13, 14, 14, 14, 30]):
            ws.set_column(col, col, width)
        ws.set_row(0, 34.5)
        ws.set_row(1, 34.5)
        ws.write(0, 0, 'KINDEN VIETNAM CO., LTD', fm(bold=True, font_size=14))
        ws.write(0, 13, _('Update on %s') % self.date_to.strftime('%d %b. %Y'), fm(bold=True, font_name='Arial', font_size=9, align='right'))
        ws.write(1, 0, 'BẢNG THEO DÕI ĐỒ BẢO HỘ LAO ĐỘNG', fm(bold=True, font_size=20))
        head = fm(bold=True, font_size=11, border=1, align='center', text_wrap=True)
        labels = ['Ref No.', 'Code Mat.', 'Name', 'Inv. No.', 'Inv Date', 'Code', 'Name', 'In\nSL mua', 'Date Out', 'Out\nSL dùng',
                  'Unit Cost', 'Total In\nMua về', 'Total Out\nĐã dùng', 'Working area', 'Remark', 'Use by pre-order',
                  'Time Allocated Exps', 'Job Allocated Exps']
        ws.set_row(2, 45.75)
        for col, label in enumerate(labels):
            ws.write(2, col, label, head)
        ws.freeze_panes(3, 3)
        ws.set_landscape()
        ws.set_paper(8)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(2)
        name_formula = '=+IF(ISERROR(VLOOKUP(B%d,Code.Mat,2,FALSE)),"",VLOOKUP(B%d,Code.Mat,2,FALSE))'

        r = 3
        for key in order:
            payment_no, invoice_no, invoice_date, supplier = key
            members = sorted(groups[key], key=lambda x: (x[0], x[2]['move'].date if x[2]['move'] else datetime.date.min))
            yellow = dict(bg_color='#FFFF00', bold=True, font_color=RED, **hair)
            head_row = r
            ws.set_row(r, 21)
            ws.write(r, 0, payment_no, fm(**yellow))
            ws.write(r, 1, '', fm(**yellow))
            ws.write(r, 2, supplier or (_('No stock-in found for these handovers') if not any(l['move'] for c, n, l in members) else ''),
                     fm(**dict(yellow, font_name='Arial', font_size=10, align='left')))
            ws.write(r, 3, invoice_no, fm(**yellow))
            if invoice_date:
                ws.write_datetime(r, 4, datetime.datetime.combine(invoice_date, datetime.time()), fm(num_format=dmy, align='center', **yellow))
            else:
                ws.write(r, 4, '', fm(**yellow))
            for col in range(5, 18):
                ws.write(r, col, '', fm(**yellow))
            total_in = 0.0
            r += 1
            first_lot = r
            for code, name, lot in members:
                m = lot['move']
                cost = (m.unit_cost if m else 0.0) or 0.0
                orange = dict(bg_color='#FFC000', font_color=RED, **hair)
                lot_row = r
                ws.set_row(r, 21)
                ws.write(r, 0, '', fm(**orange))
                ws.write(r, 1, code, fm(**orange))
                ws.write_formula(r, 2, name_formula % (r + 1, r + 1), fm(**orange), name)
                ws.write(r, 3, invoice_no, fm(bold=True, **orange))
                if invoice_date:
                    ws.write_datetime(r, 4, datetime.datetime.combine(invoice_date, datetime.time()), fm(bold=True, num_format=dmy, align='center', **orange))
                else:
                    ws.write(r, 4, '', fm(**orange))
                for col in (5, 6, 8, 13, 14, 15, 16, 17):
                    ws.write(r, col, '', fm(**orange))
                ws.write_number(r, 7, lot['qty'], fm(bold=True, **orange))
                n_out = len(lot['outs'])
                ws.write_formula(r, 9, '=SUM(J%d:J%d)' % (r + 2, r + 1 + n_out) if n_out else '=0', fm(bold=True, align='center', **orange),
                                 sum(q for o, q in lot['outs']))
                ws.write(r, 10, cost, fm(align='center', num_format=MONEY, **orange))
                ws.write_formula(r, 11, '=K%d*H%d' % (r + 1, r + 1), fm(bold=True, num_format=MONEY, **orange), cost * lot['qty'])
                ws.write(r, 12, '', fm(**orange))
                total_in += cost * lot['qty']
                r += 1
                for out, qty in lot['outs']:
                    emp = out.employee_id.sudo()
                    hist = (out.note or '').split(' ', 1) if out.accounting_only and not emp else []
                    if not emp and not hist:
                        parts = (out.note or '').split(' / ')
                        hist = [parts[0], parts[1] if len(parts) > 1 else ''] if parts and re.match(r'^[A-Za-z]\d+$', parts[0].strip()) else []
                    plain = dict(**hair)
                    ws.set_row(r, 21)
                    ws.write(r, 0, '', fm(**plain))
                    ws.write(r, 1, code, fm(**plain))
                    ws.write_formula(r, 2, name_formula % (r + 1, r + 1), fm(**plain), name)
                    for col in (3, 4, 7, 11, 15, 16, 17):
                        ws.write(r, col, '', fm(**plain))
                    ws.write(r, 5, emp.code or (hist[0] if hist else ''), fm(**plain))
                    ws.write(r, 6, emp.name or (hist[1] if len(hist) > 1 else ''), fm(**plain))
                    ws.write_datetime(r, 8, datetime.datetime.combine(out.date, datetime.time()), fm(num_format=dmy, **plain))
                    ws.write(r, 9, qty, fm(align='center', font_color=RED, **plain))
                    ws.write_formula(r, 10, '=K%d' % (lot_row + 1), fm(align='center', num_format=MONEY, **plain), cost)
                    ws.write_formula(r, 12, '=K%d*J%d' % (r + 1, r + 1), fm(num_format=MONEY, **plain), cost * qty)
                    ws.write(r, 13, out.work_area or ('' if out.accounting_only else emp.work_location) or '', fm(**plain))
                    ws.write(r, 14, _short_receipt(out.receipt_no), fm(font_size=11, **plain))
                    r += 1
            ws.write_formula(head_row, 11, '=SUM(L%d:L%d)' % (first_lot + 1, r), fm(num_format=MONEY, **yellow), total_in)
        last = max(r, 5)

        # ---- Code.Mat
        wc = book.add_worksheet('Code.Mat')
        for col, width in enumerate([10, 40, 11.7, 9.3, 9.3, 9, 15.7, 15.7, 15.7]):
            wc.set_column(col, col, width)
        wc.write(0, 0, 'KINDEN CO., LTD', fm(bold=True, font_size=11))
        wc.write(2, 0, 'BẢNG TỔNG HỢP SỬ DỤNG ĐỒ BHLĐ', fm(bold=True, font_size=20))
        wc.write(3, 0, 'As of', fm(align='left'))
        wc.write_datetime(3, 1, datetime.datetime.combine(self.date_to, datetime.time()), fm(align='left', num_format=dmy))
        box = dict(border=1, font_size=11)
        wc.merge_range(5, 3, 5, 5, 'Số lượng', fm(align='center', font_color=BLUE, **box))
        wc.merge_range(5, 6, 5, 8, 'Số tiền', fm(align='center', font_color=BLUE, **box))
        wc.write(5, 0, '', fm(**box))
        wc.write(5, 1, '', fm(**box))
        wc.write(5, 2, '', fm(**box))
        for col, label in enumerate(['Code Mat.', 'Name', 'Imagine', 'In', 'Out', 'Remain', 'Mua về', 'Đã dùng', 'Remain']):
            wc.write(6, col, label, fm(bold=True, align='center', text_wrap=True, font_color=BLUE if col >= 3 and col != 5 and col != 8 else None, **box)
                     if col >= 3 and col not in (5, 8) else fm(bold=True, align='center', text_wrap=True, **box))
        wc.set_row(6, 28.5)
        rng = lambda col: "'Detail check - report to Acc. D'!$%s$4:$%s$%d" % (col, col, last)
        images = {}
        for it in self.env['safety.tool.item'].sudo().with_context(active_test=False).search([('image', '!=', False)]):
            images[it.id] = it
        r = 7
        for code, name, lot_list in lots:
            n = r + 1
            tin = sum(l['qty'] for l in lot_list)
            tout = sum(q for l in lot_list for o, q in l['outs'])
            cin = sum((l['move'].unit_cost or 0.0) * l['qty'] for l in lot_list if l['move'])
            cout = sum((l['move'].unit_cost or 0.0 if l['move'] else 0.0) * q for l in lot_list for o, q in l['outs'])
            mid = dict(align='center', num_format=MONEY, **box)
            wc.set_row(r, 46.5)
            wc.write(r, 0, code, fm(**box))
            wc.write(r, 1, name, fm(align='center', text_wrap=True, **dict(box, font_size=11)))
            wc.write(r, 2, '', fm(**box))
            wc.write_formula(r, 3, '=SUMIFS(%s,%s,A%d)' % (rng('H'), rng('B'), n), fm(font_color=BLUE, **mid), tin)
            wc.write_formula(r, 4, '=SUMIFS(%s,%s,A%d,%s,"=")' % (rng('J'), rng('B'), n, rng('H')), fm(font_color=RED, **mid), tout)
            wc.write_formula(r, 5, '=D%d-E%d' % (n, n), fm(**mid), tin - tout)
            wc.write_formula(r, 6, '=SUMIFS(%s,%s,A%d)' % (rng('L'), rng('B'), n), fm(font_color=BLUE, **dict(box, num_format=MONEY)), cin)
            wc.write_formula(r, 7, '=SUMIFS(%s,%s,A%d)' % (rng('M'), rng('B'), n), fm(font_color=RED, **dict(box, num_format=MONEY)), cout)
            wc.write_formula(r, 8, '=G%d-H%d' % (n, n), fm(**dict(box, num_format=MONEY)), cin - cout)
            item = self.env['safety.tool.item'].sudo().search([('code', '=', code)], limit=1) or \
                self.env['safety.tool.size'].sudo().search([('code', '=', code)], limit=1).item_id
            if item and item.image:
                try:
                    wc.insert_image(r, 2, 'item.png', {'image_data': io.BytesIO(_picture(item.image, (60, 60))), 'x_offset': 4, 'y_offset': 4,
                                                       'x_scale': 0.8, 'y_scale': 0.8, 'object_position': 1})
                except Exception:
                    pass
            r += 1
        book.define_name('Code.Mat', '=Code.Mat!$A$8:$C$%d' % max(r, 9))
        wc.freeze_panes(7, 0)
        wc.set_landscape()
        wc.set_paper(8)
        wc.fit_to_pages(1, 0)
