"""Transfer allowance database (v1).

Three tables HR maintains:
- transfer.allowance.grade   G codes (G01..G14), each linked to the employee tag HR uses
                             for it (hr.employee.category, e.g. "G8")
- transfer.allowance.band    S codes (project transfer) and T codes (training):
                             distance range in km, optional duration range in months
- transfer.allowance.matrix  one rate line = grade x band x effective date -> monthly amount (VND)

Reference data only: shows which allowance applies in the salary calculation.

Lookup entry points (model transfer.allowance.matrix):
- find_band(transfer_type, distance_km, months)
- get_rate(grade, band, on_date)
- get_amount(grade, transfer_type, distance_km, months, on_date)
- months_between(date_from, date_to)
"""
import base64
import io
import logging
import math

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

TRANSFER_TYPES = [('project', 'Project Transfer'), ('training', 'Training')]


class TransferAllowanceGrade(models.Model):
    _name = 'transfer.allowance.grade'
    _description = 'Transfer Allowance - Grade (G code)'
    _order = 'sequence, code'
    _rec_name = 'code'

    code = fields.Char('G Code', required=True)
    name = fields.Char('Description')
    category_id = fields.Many2one('hr.employee.category', 'Employee Tag', ondelete='set null',
                                  help='The tag HR puts on employees of this grade (Employees > Tags).')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint('unique(code)', 'This G code already exists.')
    _category_uniq = models.Constraint('unique(category_id)', 'This employee tag is already linked to another grade.')

    @api.model
    def _link_employee_tags(self):
        """Link grades without a tag to an existing employee tag named G8 / G08 (any case).
        Never creates tags. Safe to run again."""
        Tag = self.env['hr.employee.category'].sudo()
        linked_tags = self.sudo().search([('category_id', '!=', False)]).mapped('category_id')
        for grade in self.sudo().search([('category_id', '=', False)]):
            digits = grade.code[1:]
            if not digits.isdigit():
                continue
            names = {'G%d' % int(digits), 'G%02d' % int(digits)}
            tags = Tag.browse()
            for name in names:
                tags |= Tag.search([('name', '=ilike', name)])
            tags -= linked_tags
            if len(tags) == 1:
                grade.category_id = tags
                linked_tags |= tags
            elif len(tags) > 1:
                _logger.warning('Grade %s: several matching employee tags %s, not linked.',
                                grade.code, tags.mapped('name'))

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for g in self:
            g.display_name = '%s - %s' % (g.code, g.name) if g.name else g.code


class TransferAllowanceBand(models.Model):
    _name = 'transfer.allowance.band'
    _description = 'Transfer Allowance - Distance / Duration Band (S or T code)'
    _order = 'transfer_type, sequence, code, months_over'
    _rec_name = 'code'

    code = fields.Char('Code', required=True, help='S code for project transfer, T code for training.')
    transfer_type = fields.Selection(TRANSFER_TYPES, 'Type', required=True, default='project')
    km_from = fields.Integer('Distance From (km)', required=True, default=0,
                             help='Inclusive. Distances are rounded to the nearest km before matching.')
    km_to = fields.Integer('Distance To (km)', default=0,
                           help='Inclusive. 0 = no upper limit (e.g. over 200 km).')
    months_over = fields.Float('Duration Over (months)', default=0,
                               help='Duration must be greater than this. 0 = no lower limit.')
    months_up_to = fields.Float('Duration Up To (months)', default=0,
                                help='Duration must be less than or equal to this. 0 = no upper limit.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    note = fields.Char('Note')

    _code_duration_uniq = models.Constraint(
        'unique(code, months_over)', 'The same code with the same duration already exists.')

    @api.constrains('km_from', 'km_to', 'months_over', 'months_up_to')
    def _check_ranges(self):
        for b in self:
            if b.km_from < 0 or b.km_to < 0 or b.months_over < 0 or b.months_up_to < 0:
                raise ValidationError(_('%s: distances and durations cannot be negative.') % b.code)
            if b.km_to and b.km_to < b.km_from:
                raise ValidationError(_('%s: "Distance To" must be greater than or equal to "Distance From".') % b.code)
            if b.months_up_to and b.months_up_to <= b.months_over:
                raise ValidationError(_('%s: "Duration Up To" must be greater than "Duration Over".') % b.code)

    def _distance_label(self):
        self.ensure_one()
        if self.km_to:
            return '%s-%s km' % (self.km_from, self.km_to)
        return '>%s km' % (self.km_from - 1 if self.km_from else 0)

    def _duration_label(self):
        self.ensure_one()
        if self.months_over and self.months_up_to:
            return '>%g-%g months' % (self.months_over, self.months_up_to)
        if self.months_up_to:
            return '1-%g months' % self.months_up_to
        if self.months_over:
            return '>%g months' % self.months_over
        return ''

    @api.depends('code', 'km_from', 'km_to', 'months_over', 'months_up_to')
    def _compute_display_name(self):
        for b in self:
            parts = [b.code, b._distance_label(), b._duration_label()]
            b.display_name = ' | '.join(p for p in parts if p)

    def _matches(self, km, months):
        self.ensure_one()
        if km < self.km_from or (self.km_to and km > self.km_to):
            return False
        if self.months_over and not months > self.months_over:
            return False
        if self.months_up_to and months > self.months_up_to:
            return False
        return True


class TransferAllowanceMatrix(models.Model):
    _name = 'transfer.allowance.matrix'
    _description = 'Transfer Allowance - Rate'
    _inherit = ['mail.thread']
    _order = 'transfer_type, grade_sequence, band_sequence, date_from desc'

    grade_id = fields.Many2one('transfer.allowance.grade', 'Grade', required=True, ondelete='restrict',
                               index=True, tracking=True)
    band_id = fields.Many2one('transfer.allowance.band', 'Band', required=True, ondelete='restrict',
                              index=True, tracking=True)
    transfer_type = fields.Selection(related='band_id.transfer_type', store=True, readonly=True)
    grade_sequence = fields.Integer(related='grade_id.sequence', store=True, readonly=True)
    band_sequence = fields.Integer(related='band_id.sequence', store=True, readonly=True)
    date_from = fields.Date('Effective From', required=True, default=fields.Date.context_today,
                            tracking=True)
    date_to = fields.Date('Effective To', readonly=True,
                          help='Set automatically: the day before the next rate for the same grade and band.')
    amount = fields.Float('Amount (VND/month)', required=True, digits=(16, 0), aggregator='max',
                          tracking=True)
    note = fields.Char('Note')

    _grade_band_date_uniq = models.Constraint(
        'unique(grade_id, band_id, date_from)', 'A rate for this grade and band already starts on this date.')
    _amount_positive = models.Constraint('CHECK(amount >= 0)', 'The amount cannot be negative.')

    @api.depends('grade_id.code', 'band_id.code', 'date_from')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s / %s (%s)' % (r.grade_id.code, r.band_id.code, r.date_from)

    # ------------------------------------------------------------------
    # Validity periods (date_to) are derived from the next version
    # ------------------------------------------------------------------
    @api.model
    def _refresh_date_to(self, pairs):
        for grade_id, band_id in pairs:
            versions = self.search([('grade_id', '=', grade_id), ('band_id', '=', band_id)],
                                   order='date_from asc')
            for current, nxt in zip(versions, list(versions[1:]) + [None]):
                new_to = (nxt.date_from - relativedelta(days=1)) if nxt else False
                if current.date_to != new_to:
                    super(TransferAllowanceMatrix, current).write({'date_to': new_to})

    def _pairs(self):
        return {(r.grade_id.id, r.band_id.id) for r in self}

    @api.model_create_multi
    def create(self, vals_list):
        recs = super(TransferAllowanceMatrix, self).create(vals_list)
        self._refresh_date_to(recs._pairs())
        return recs

    def write(self, vals):
        pairs = self._pairs()
        res = super(TransferAllowanceMatrix, self).write(vals)
        if {'grade_id', 'band_id', 'date_from'} & set(vals):
            self._refresh_date_to(pairs | self._pairs())
        return res

    def unlink(self):
        pairs = self._pairs()
        res = super(TransferAllowanceMatrix, self).unlink()
        self._refresh_date_to(pairs)
        return res

    # ------------------------------------------------------------------
    # Lookup API
    # ------------------------------------------------------------------
    @api.model
    def months_between(self, date_from, date_to):
        """Duration in months, both dates inclusive (1 Aug - 31 Jan = 6.0)."""
        if not date_from or not date_to:
            return 0.0
        d1 = fields.Date.to_date(date_from)
        d2 = fields.Date.to_date(date_to) + relativedelta(days=1)
        delta = relativedelta(d2, d1)
        return delta.years * 12 + delta.months + delta.days / 30.0

    @api.model
    def find_band(self, transfer_type, distance_km, months=0.0):
        """Return the band (S/T code) for a distance and duration, or an empty recordset."""
        km = int(math.floor((distance_km or 0.0) + 0.5))
        bands = self.env['transfer.allowance.band'].sudo().search([('transfer_type', '=', transfer_type)])
        matches = bands.filtered(lambda b: b._matches(km, months or 0.0))
        if len(matches) > 1:
            raise ValidationError(_('Allowance bands overlap for %s km / %s months: %s')
                                  % (km, months, ', '.join(matches.mapped('code'))))
        return matches.with_user(self.env.uid)

    @api.model
    def get_rate(self, grade, band, on_date=None):
        """Rate line valid on on_date (default today), or an empty recordset when the
        grade is not entitled to that band. grade/band: record, id or code."""
        grade = self._resolve(grade, 'transfer.allowance.grade')
        band = self._resolve(band, 'transfer.allowance.band')
        if not grade or not band:
            return self.browse()
        on_date = on_date or fields.Date.context_today(self)
        return self.sudo().search([
            ('grade_id', '=', grade.id),
            ('band_id', '=', band.id),
            ('date_from', '<=', on_date),
        ], order='date_from desc', limit=1).with_user(self.env.uid)

    @api.model
    def get_amount(self, grade, transfer_type, distance_km, months=0.0, on_date=None):
        """Monthly amount in VND, or False when no band or rate applies."""
        band = self.find_band(transfer_type, distance_km, months)
        rate = self.get_rate(grade, band, on_date) if band else self.browse()
        return rate.amount if rate else False

    @api.model
    def _resolve(self, value, model):
        Model = self.env[model].sudo()
        if isinstance(value, models.BaseModel):
            return value[:1]
        if isinstance(value, int):
            return Model.browse(value).exists()
        if isinstance(value, str) and value:
            recs = Model.search([('code', '=', value)])
            if len(recs) > 1:
                raise ValidationError(_('Code %s is ambiguous; pass the record instead.') % value)
            return recs
        return Model.browse()

    # ------------------------------------------------------------------
    # Read-only matrix rendering (same layout as paper form CR04-03-F01)
    # Shared layout -> HTML (form) and PNG (printed report)
    # ------------------------------------------------------------------
    @api.model
    def _matrix_layout(self, on_date=None):
        """Table structure of the rates valid on on_date (default today).
        Returns None when nothing is configured, else a dict:
          header: [(row label, [(text, colspan, is_heading)])]  type/code/distance/duration rows
          groups: [(grade label, grade ids, [amount or None per band])]
          n_cols: number of band columns
        Consecutive grades with identical amounts are merged (G01-G08, G09-G10...)."""
        on_date = on_date or fields.Date.context_today(self)
        grades = self.env['transfer.allowance.grade'].sudo().search([])
        bands = self.env['transfer.allowance.band'].sudo().search([])
        if not grades or not bands:
            return None

        amounts = {}
        for rate in self.sudo().search([('date_from', '<=', on_date)], order='date_from desc'):
            amounts.setdefault((rate.grade_id.id, rate.band_id.id), rate.amount)

        def merge(values, heading):
            out = []
            for v in values:
                if out and out[-1][0] == v:
                    out[-1][1] += 1
                else:
                    out.append([v, 1])
            return [(v[1] if isinstance(v, tuple) else v, n, heading) for v, n in out]

        types = dict(TRANSFER_TYPES)
        header = [
            ('', merge([types.get(b.transfer_type, b.transfer_type) for b in bands], True)),
            (_('Code'), merge([b.code for b in bands], True)),
            (_('Distance'), merge([(b.code, b._distance_label()) for b in bands], False)),
            (_('Duration'), [(b._duration_label(), 1, False) for b in bands]),
        ]
        groups = []
        for g in grades:
            values = [amounts.get((g.id, b.id)) for b in bands]
            if groups and groups[-1][2] == values:
                groups[-1][1].append(g)
            else:
                groups.append(['', [g], values])
        result = []
        for _label, group_grades, values in groups:
            label = group_grades[0].code if len(group_grades) == 1 else '%s-%s' % (
                group_grades[0].code, group_grades[-1].code)
            result.append((label, [g.id for g in group_grades], values))
        return {'header': header, 'groups': result, 'n_cols': len(bands),
                'on_date': fields.Date.to_date(on_date)}

    @staticmethod
    def _fmt_thousands(amount):
        if amount is None:
            return None
        value = amount / 1000.0
        return '{:,.0f}'.format(value) if value == int(value) else '{:,.1f}'.format(value)

    @api.model
    def _matrix_notes(self, layout, highlight_grade=None):
        note = _('Unit: 1,000 VND / month. Valid on %s.') % layout['on_date'].strftime('%d/%m/%Y')
        if highlight_grade:
            note += ' ' + _('Highlighted: grade %s.') % highlight_grade.code
        return [note, _('Distance: from the assigned main office (Hanoi Head Office, Hai Phong Office, '
                        'Ho Chi Minh Branch Office) to the new project/section, by Google Maps.')]

    @api.model
    def render_matrix_html(self, on_date=None, highlight_grade=None):
        """HTML table for the form (1,000 VND / month). highlight_grade: grade record to mark."""
        layout = self._matrix_layout(on_date)
        if not layout:
            return '<p class="text-muted">%s</p>' % html_escape(_('No allowance matrix configured.'))

        cell = 'border:1px solid #dee2e6;padding:2px 6px;text-align:center;vertical-align:middle;'
        head = cell + 'background:#f8f9fa;font-weight:bold;'

        def esc(value):
            return html_escape(value or '')

        rows = []
        for label, cells in layout['header']:
            rows.append('<tr><th style="%s">%s</th>%s</tr>' % (head, esc(label), ''.join(
                '<%s colspan="%d" style="%s">%s</%s>' % (
                    'th' if h else 'td', n, head if h else cell, esc(text), 'th' if h else 'td')
                for text, n, h in cells)))
        for label, grade_ids, values in layout['groups']:
            marked = bool(highlight_grade) and highlight_grade.id in grade_ids
            row_style = 'background:rgba(124,123,173,0.15);font-weight:bold;' if marked else ''
            first = head + ('border-left:4px solid #7C7BAD;' if marked else '')
            tds = ''.join('<td style="%s">%s</td>' % (
                cell, esc(self._fmt_thousands(v)) if v is not None
                else '<span style="color:#adb5bd;">&#8211;</span>') for v in values)
            rows.append('<tr style="%s"><th style="%s">%s</th>%s</tr>' % (row_style, first, esc(label), tds))

        notes = self._matrix_notes(layout, highlight_grade)
        return ('<div style="overflow-x:auto;">'
                '<table style="border-collapse:collapse;font-size:12px;min-width:100%%;">%s</table>'
                '<p class="text-muted" style="font-size:11px;margin-top:4px;">%s</p></div>') % (
            ''.join(rows), ' '.join(esc(n) for n in notes))

    @api.model
    def render_matrix_png(self, on_date=None, highlight_grade=None, scale=3):
        """Base64 PNG of the matrix for py3o reports (no notes: put them in the template).
        Drawn at `scale` x 96 dpi so it stays sharp when printed. '' when not configured."""
        layout = self._matrix_layout(on_date)
        if not layout:
            return ''
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            _logger.warning('Pillow missing: allowance matrix image skipped.')
            return ''

        # Sized for a 17 cm wide frame (~640 px at 96 dpi), so the text prints at ~8 pt.
        s = scale
        first_w, col_w, row_h = 74 * s, 43 * s, 18 * s
        n_rows = len(layout['header']) + len(layout['groups'])
        width = first_w + col_w * layout['n_cols'] + s
        height = row_h * n_rows + s
        img = Image.new('RGB', (width, height), '#FFFFFF')
        draw = ImageDraw.Draw(img)

        def load_font(names, size):
            for name in names:
                try:
                    return ImageFont.truetype(name, size)
                except IOError:
                    continue
            return ImageFont.load_default()
        bold_names = ['DejaVuSansCondensed-Bold.ttf', 'DejaVuSans-Bold.ttf']
        regular_names = ['DejaVuSansCondensed.ttf', 'DejaVuSans.ttf']
        font_bold = load_font(bold_names, 10 * s)
        font = load_font(regular_names, 10 * s)
        small = {font_bold: load_font(bold_names, 8 * s), font: load_font(regular_names, 8 * s)}

        # Compact labels: units move to the row labels
        def compact(text):
            return (text or '').replace(' km', '').replace(' months', '')
        header = []
        for label, cells in layout['header']:
            if label == _('Distance'):
                label = _('Distance (km)')
            elif label == _('Duration'):
                label = _('Duration (months)')
            header.append((label, [(compact(t), n, h) for t, n, h in cells]))

        def text_w(text, f):
            if hasattr(draw, 'textlength'):
                return draw.textlength(text, font=f)
            return draw.textsize(text, font=f)[0]

        def box(x, y, w, text, f, fill=None, color='#212529'):
            if fill:
                draw.rectangle([x, y, x + w, y + row_h], fill=fill)
            lw = max(1, s // 2)  # draw.line width works on old Pillow; rectangle(width=) needs >= 5.3
            for xy in ([x, y, x + w, y], [x, y + row_h, x + w, y + row_h], [x, y, x, y + row_h],
                       [x + w, y, x + w, y + row_h]):
                draw.line(xy, fill='#6c757d', width=lw)
            if text and text_w(text, f) > w - 4 * s:
                f = small.get(f, f)  # shrink long labels instead of overflowing the cell
            if text:
                draw.text((x + (w - text_w(text, f)) / 2, y + (row_h - 11 * s) / 2), text, fill=color, font=f)

        y = 0
        for label, cells in header:
            box(0, y, first_w, label, font_bold, '#f1f3f5')
            x = first_w
            for text, n, heading in cells:
                box(x, y, col_w * n, text, font_bold if heading else font, '#f1f3f5' if heading else None)
                x += col_w * n
            y += row_h
        for label, grade_ids, values in layout['groups']:
            marked = bool(highlight_grade) and highlight_grade.id in grade_ids
            fill = '#e5e5ef' if marked else None
            box(0, y, first_w, label, font_bold, fill or '#f1f3f5')
            x = first_w
            for v in values:
                if v is None:
                    box(x, y, col_w, '-', font, fill, '#adb5bd')
                else:
                    box(x, y, col_w, self._fmt_thousands(v), font_bold if marked else font, fill)
                x += col_w
            y += row_h

        buffer = io.BytesIO()
        img.save(buffer, format='PNG', dpi=(96 * s, 96 * s))
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
