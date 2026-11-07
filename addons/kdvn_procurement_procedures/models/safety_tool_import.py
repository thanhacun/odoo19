"""Import of the Excel 'Safety Tool Control Sheet' (wizard, run by the Safety Tool Admin staff).

What it does with a file (the same wizard on dev and on production, any version of the sheet):
- every item block is mapped to a catalogue item + size (remembered as an alias for the next file);
- the opening line becomes an opening-balance move (only the first time an item is imported);
- IN rows become stock-in moves; OUT rows become requests already approved and handed over (grouped per
  day / staff / project, applicant found by the staff code, history without approval steps);
- finally the stock at the report date is compared with the Excel remaining quantity and the difference
  is posted as a stock-take adjustment (the Excel's own running balance has mistakes).
Rows already imported (import key) are skipped, so a newer file only adds what is new.
"""
import base64
import hashlib
import io
import json
import logging
import re
import zipfile

from odoo import models, fields, api, _, SUPERUSER_ID
from odoo import tools
from odoo.exceptions import UserError

from . import safety_tool_xlsx as xlsx

_logger = logging.getLogger(__name__)

TYPE_WORDS = [('vest', 'vest'), ('helmet', 'helmet'), ('belt', 'belt'), ('shoe', 'shoe'),
              ('indicator', 'indicator'), ('flag', 'indicator'), ('board', 'indicator'), ('seal', 'other')]


def _guess_type(name):
    low = (name or '').lower()
    for word, kind in TYPE_WORDS:
        if word in low:
            return kind
    return 'other'


def _ident(block):
    """Stable identity of a block between two versions of the sheet (no row numbers, no item number)."""
    return '%s|%s|%s' % (xlsx.normalize(block['name']), xlsx.normalize(block.get('desc')),
                         xlsx.normalize(block.get('size_text')))


def _row_key(ident, row, occurrence):
    base = '|'.join([ident, str(row['date']), '%g' % row['qty_in'], '%g' % row['qty_out'], row['staff_code'] or '',
                     xlsx.normalize(row['project']), xlsx.normalize(row['remarks'])])
    return hashlib.sha1(base.encode('utf-8')).hexdigest() + '#%d' % occurrence


class SafetyToolImportAlias(models.Model):
    """Remembers how an Excel block (name + description + size text) maps to a catalogue item and size."""
    _name = 'safety.tool.import.alias'
    _description = 'Safety Tool Excel Alias'
    _order = 'key'

    key = fields.Char(required=True, index=True)
    excel_name = fields.Char(string='Excel item')
    size_text = fields.Char(string='Excel size')
    item_id = fields.Many2one('safety.tool.item', string='Item', required=True, ondelete='cascade')
    size_id = fields.Many2one('safety.tool.size', string='Size', ondelete='set null')

    _key_unique = models.Constraint('unique(key)', 'This Excel item is already mapped.')


class SafetyToolImportBatch(models.Model):
    _name = 'safety.tool.import.batch'
    _description = 'Safety Tool Excel Import'
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True)
    date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one('res.users', string='Imported by', default=lambda s: s.env.uid, readonly=True)
    file_name = fields.Char(readonly=True)
    report_no = fields.Char(string='Report', readonly=True)
    as_of_date = fields.Date(string='As of', readonly=True)
    state = fields.Selection([('done', 'Done'), ('undone', 'Undone')], default='done', readonly=True)
    note = fields.Text(readonly=True)
    move_ids = fields.One2many('safety.tool.move', 'import_batch_id', string='Stock moves', readonly=True)
    request_ids = fields.One2many('safety.tool.request', 'import_batch_id', string='Requests', readonly=True)
    n_moves = fields.Integer(compute='_compute_counts')
    n_requests = fields.Integer(compute='_compute_counts')

    @api.depends('move_ids', 'request_ids')
    def _compute_counts(self):
        for batch in self:
            batch.n_moves = len(batch.move_ids)
            batch.n_requests = len(batch.request_ids)

    def action_undo(self):
        """Delete what this import created (requests, moves). Items and aliases stay."""
        if not self.env['safety.tool.request']._is_tool_admin():
            raise UserError(_('Only the Safety Tool Admin staff can do this.'))
        for batch in self.filtered(lambda b: b.state == 'done'):
            later = self.env['safety.tool.move'].sudo().search_count([
                ('import_batch_id', '=', False), ('request_id', '!=', False), ('item_id', 'in', batch.move_ids.mapped('item_id').ids),
                ('create_date', '>', batch.date)])
            if later:
                raise UserError(_('Tools of this import were issued by a normal request afterwards. '
                                  'Reverse those handovers first.'))
            batch.sudo().move_ids.with_context(safety_tool_system=True).unlink()
            batch.sudo().request_ids.with_context(safety_tool_system=True).unlink()
            batch.state = 'undone'


class SafetyToolImportWizard(models.TransientModel):
    _name = 'safety.tool.import.wizard'
    _description = 'Import the Safety Tool Control Sheet'

    state = fields.Selection([('upload', 'Upload'), ('preview', 'Preview'), ('done', 'Done')], default='upload')
    file = fields.Binary(string='Excel file (.xlsx)')
    filename = fields.Char()
    report_no = fields.Char(string='Report', readonly=True)
    report_date = fields.Date(string='Date in the sheet', readonly=True)
    import_pictures = fields.Boolean(string='Import the tool pictures', default=True,
                                     help='Fills the photo of an item that has none yet; never replaces a photo.')
    as_of_date = fields.Date(string='Excel quantities are valid on', help='Taken from the sheet header; change it if you know better.')
    line_ids = fields.One2many('safety.tool.import.line', 'wizard_id', string='Excel items')
    summary = fields.Text(readonly=True)
    batch_id = fields.Many2one('safety.tool.import.batch', readonly=True)

    # ------------------------------------------------------------------
    def _require_admin(self):
        if not self.env['safety.tool.request']._is_tool_admin():
            raise UserError(_('Only the Safety Tool Admin staff can import the control sheet.'))

    @api.model
    def _employee_map(self):
        employees = self.env['hr.employee'].sudo().with_context(active_test=False).search_read(
            [('code', '!=', False)], ['code'])
        result = {}
        for e in employees:
            result.setdefault((e['code'] or '').strip().upper(), e['id'])
        return result

    @api.model
    def _job_resolver(self):
        jobs = self.env['kderp.job.lookup'].sudo().search_read([], ['job_no', 'job_name'])
        by_name, by_no, names = {}, {}, []
        for j in jobs:
            norm = xlsx.normalize(j['job_name'])
            by_name.setdefault(norm, j['id'])
            by_no.setdefault(xlsx.normalize(j['job_no']), j['id'])
            names.append((norm, j['id']))
        cache = {}

        def resolve(text):
            norm = xlsx.normalize(text)
            if not norm:
                return False
            if norm not in cache:
                found = by_name.get(norm) or by_no.get(norm)
                if not found and len(norm) >= 5:
                    hits = {jid for n, jid in names if norm in n}
                    found = hits.pop() if len(hits) == 1 else False
                cache[norm] = found or False
            return cache[norm]
        return resolve

    @api.model
    def _match_block(self, block):
        """(action, item, size) proposed for a block: alias, else same item name, else create."""
        Alias, Item = self.env['safety.tool.import.alias'], self.env['safety.tool.item']
        alias = Alias.search([('key', '=', _ident(block))], limit=1)
        if alias:
            return 'map', alias.item_id, alias.size_id
        label = ('%s %s' % (block['name'], block.get('desc') or '')).strip()
        item = Item.search([('active', 'in', [True, False])]).filtered(
            lambda i: xlsx.normalize(i.name) in (xlsx.normalize(label), xlsx.normalize(block['name'])))[:1]
        if not item:
            return 'create', Item, self.env['safety.tool.size']
        size = item.size_ids.filtered(lambda s: xlsx.normalize(s.name) == xlsx.normalize(block.get('size_text')))[:1]
        return 'map', item, size

    def action_read(self):
        self.ensure_one()
        self._require_admin()
        if not self.file:
            raise UserError(_('Choose the Excel file first.'))
        try:
            parsed = xlsx.parse_control_sheet(io.BytesIO(base64.b64decode(self.file)))
        except (zipfile.BadZipFile, KeyError, ValueError) as error:
            raise UserError(_('This is not a readable .xlsx control sheet (%s).') % error)
        if not parsed['blocks']:
            raise UserError(_('No item block found in the sheet. Is it the Safety Tool Control Sheet?'))
        last_row_date = max([r['date'] for b in parsed['blocks'] for r in b['rows'] if r['date']] or [False])
        try:
            pictures = xlsx.pictures_by_block(parsed['blocks'], xlsx.read_images(io.BytesIO(base64.b64decode(self.file))))
        except Exception as error:                                   # a picture problem must not stop the import
            _logger.warning('Safety tool import: pictures not read (%s)', error)
            pictures = {}
        seen_idents, seen_rows = {}, {}
        lines = []
        for seq, block in enumerate(parsed['blocks']):
            ident = _ident(block)
            seen_idents[ident] = seen_idents.get(ident, 0) + 1
            block['ident'] = '%s#%d' % (ident, seen_idents[ident])
            block['open_key'] = 'open|' + block['ident']
            for row in block['rows']:
                base = _row_key(block['ident'], row, 0)[:-2]
                seen_rows[base] = seen_rows.get(base, 0) + 1
                row['key'] = '%s#%d' % (base, seen_rows[base])
            action, item, size = self._match_block(block)
            if not block['rows'] and not (block['opening_qty'] or 0) and not (block['last_remain'] or 0):
                action = 'skip'                                   # nothing to import (empty block)
            lines.append((0, 0, {
                'has_picture': seq in pictures,
                'sequence': seq, 'excel_no': block['no'], 'excel_name': ('%s %s' % (block['name'], block.get('desc') or '')).strip(),
                'size_text': block.get('size_text'), 'action': action, 'item_id': item.id, 'size_id': size.id,
                'excel_qty': block['last_remain'] or 0.0, 'block_json': json.dumps(block, default=str)}))
        self.write({'line_ids': [(5, 0, 0)] + lines, 'report_no': parsed['report_no'], 'report_date': parsed['report_date'],
                    'as_of_date': parsed['report_date'] or last_row_date or fields.Date.context_today(self),
                    'state': 'preview'})
        self._compute_summary()
        return self._reopen()

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new', 'name': _('Import the Safety Tool Control Sheet')}

    def _compute_summary(self):
        self.ensure_one()
        staff = self._employee_map()
        resolve = self._job_resolver()
        new_rows = out_rows = unknown = 0
        unknown_codes, projects, bad_projects = set(), set(), set()
        for line in self.line_ids:
            for row in json.loads(line.block_json)['rows']:
                out_rows += 1 if row['qty_out'] else 0
            new_rows += line.n_new
        for line in self.line_ids:
            for row in json.loads(line.block_json)['rows']:
                if row['qty_out']:
                    if row['staff_code'] not in staff:
                        unknown_codes.add(row['staff_code'] or '(no code)')
                    if row['project']:
                        projects.add(row['project'])
                        if not resolve(row['project']):
                            bad_projects.add(row['project'])
        to_create = len(self.line_ids.filtered(lambda l: l.action == 'create'))
        mism = len(self.line_ids.filtered('has_gap'))
        self.summary = _(
            "%(blocks)s Excel blocks, %(rows)s rows not imported yet, %(out)s OUT rows in the file.\n"
            "New catalogue items to create: %(create)s.\n"
            "Blocks whose own running balance does not add up in the Excel: %(gap)s (the difference is posted as a stock-take adjustment).\n"
            "OUT rows without a known staff code (posted as stock moves without a request): codes %(codes)s\n"
            "Projects not matched to a job (kept as text on the request): %(bad)s of %(proj)s.\n"
            "Blocks with a picture in the Excel: %(pics)s."
        ) % {'pics': len(self.line_ids.filtered('has_picture')), 'blocks': len(self.line_ids), 'rows': new_rows, 'out': out_rows, 'create': to_create, 'gap': mism,
             'codes': ', '.join(sorted(unknown_codes)[:30]) or '-', 'bad': len(bad_projects), 'proj': len(projects)}

    def action_refresh(self):
        self.ensure_one()
        self.line_ids._compute_preview()
        self._compute_summary()
        return self._reopen()

    def action_back(self):
        self.write({'state': 'upload', 'line_ids': [(5, 0, 0)]})
        return self._reopen()

    # ------------------------------------------------------------------
    def _ensure_target(self, line, block):
        """(item, size) of a line; creates the item / size when asked."""
        Item, Size = self.env['safety.tool.item'], self.env['safety.tool.size']
        item = line.item_id
        if line.action == 'create' and not item:
            label = xlsx.normalize(line.excel_name or block['name'])
            item = Item.search([('active', 'in', [True, False])]).filtered(lambda i: xlsx.normalize(i.name) == label)[:1]
        if line.action == 'create' and not item:
            item = Item.create({'name': line.excel_name or block['name'], 'code': block['no'] or False,
                                'item_type': _guess_type(block['name']), 'uom': 'pcs',
                                'note': block.get('dims') or False})
        size = line.size_id
        if size and size.item_id != item:
            raise UserError(_('%s: the size "%s" does not belong to "%s".') % (line.excel_name, size.name, item.name))
        text = (block.get('size_text') or '').strip()
        if not size and text:
            size = item.size_ids.filtered(lambda s: xlsx.normalize(s.name) == xlsx.normalize(text))[:1] or Size.create(
                {'item_id': item.id, 'name': text, 'sequence': len(item.size_ids) * 10 + 10})
        if item.size_ids and not size:
            raise UserError(_('%s: "%s" has sizes, choose the size of this Excel block.') % (line.excel_name, item.name))
        return item, size

    def action_import(self):
        self.ensure_one()
        self._require_admin()
        if self.state != 'preview':
            raise UserError(_('Read a file first.'))
        problems = [_('%s: choose the catalogue item (or skip the block).') % l.excel_name
                    for l in self.line_ids if l.action == 'map' and not l.item_id]
        if problems:
            raise UserError('\n'.join(problems))
        env = self.env
        Move = env['safety.tool.move'].with_context(safety_tool_system=True)
        # Created as the system user: "My Requests", the own-requests rule and the dashboard all mean create_uid = me,
        # so history created as the person running the import would land in that person's own requests.
        Request = env['safety.tool.request'].with_user(SUPERUSER_ID).with_context(safety_tool_system=True, mail_create_nolog=True,
                                                         mail_notrack=True, tracking_disable=True)
        staff = self._employee_map()
        resolve = self._job_resolver()
        batch = env['safety.tool.import.batch'].create({
            'name': _('Import %s') % fields.Datetime.now(), 'file_name': self.filename, 'report_no': self.report_no,
            'as_of_date': self.as_of_date})
        stats = {'in': 0, 'out_requests': 0, 'out_moves': 0, 'open': 0, 'adjust': 0, 'known': 0, 'no_staff': 0}
        groups = {}                     # (date, staff, project) -> {'rows': [...], 'meta': ...}
        for line in self.line_ids.sorted('sequence'):
            if line.action == 'skip':
                continue
            block = json.loads(line.block_json)
            item, size = self._ensure_target(line, block)
            line.write({'item_id': item.id, 'size_id': size.id, 'action': 'map'})
            alias = env['safety.tool.import.alias'].search([('key', '=', _ident(block))], limit=1)
            vals = {'key': _ident(block), 'excel_name': line.excel_name, 'size_text': block.get('size_text'),
                    'item_id': item.id, 'size_id': size.id or False}
            alias.write(vals) if alias else env['safety.tool.import.alias'].create(vals)
            keys = [r['key'] for r in block['rows']] + [block['open_key']]
            known = set(Move.sudo().search([('import_key', 'in', keys)]).mapped('import_key'))
            base = {'item_id': item.id, 'size_id': size.id or False, 'import_batch_id': batch.id}
            # opening balance: only the first time this item / size is imported
            already = Move.sudo().search_count([('item_id', '=', item.id), ('size_id', '=', size.id or False),
                                                 ('import_batch_id', '!=', False), ('import_batch_id', '!=', batch.id)])
            if block['open_key'] not in known and not already and (block['opening_qty'] or 0) > 0:
                Move.create(dict(base, date=block['opening_date'] or self.as_of_date, qty_in=block['opening_qty'],
                                 source='opening', import_key=block['open_key'], note=_('Opening balance (Excel)')))
                stats['open'] += 1
            for row in block['rows']:
                if row['key'] in known:
                    stats['known'] += 1
                    continue
                date = row['date'] or self.as_of_date
                note = ' / '.join([x for x in (row['project'], row['remarks']) if x])[:200]
                if row['qty_in']:
                    Move.create(dict(base, date=date, qty_in=row['qty_in'], source='purchase', import_key=row['key'], note=note))
                    stats['in'] += 1
                if row['qty_out']:
                    emp_id = staff.get(row['staff_code'])
                    if not emp_id:
                        Move.create(dict(base, date=date, qty_out=row['qty_out'], source='manual', import_key=row['key'],
                                         note=(' / '.join([x for x in (row['staff_code'], row['staff_name'], note) if x]))[:200]))
                        stats['no_staff'] += 1
                        continue
                    gkey = (str(date), emp_id, xlsx.normalize(row['project']))
                    group = groups.setdefault(gkey, {'date': date, 'emp': emp_id, 'project': row['project'],
                                                     'staff_text': ' '.join([x for x in (row['staff_code'], row['staff_name']) if x]),
                                                     'rows': []})
                    group['rows'].append((base, row))
        # OUT rows: one approved + handed over request per day / staff / project
        for gkey in sorted(groups):
            group = groups[gkey]
            request = Request.create({
                'name': env['ir.sequence'].next_by_code('safety.tool.request.import') or _('New'),
                'reason': _('Imported from the Excel control sheet %s') % (self.report_no or ''),
                'request_type': 'new', 'date_input': group['date'], 'employee_id': group['emp'],
                'job_id': resolve(group['project']) or False, 'state': 'approved', 'fulfilment_state': 'received',
                'issued_date': group['date'], 'receipt_date': group['date'], 'receipt_reminded': True,
                'is_imported': True, 'import_batch_id': batch.id, 'import_project_text': group['project'],
                'import_staff_text': group['staff_text'],
                'line_ids': [(0, 0, {'item_id': b['item_id'], 'size_id': b['size_id'], 'qty': r['qty_out']})
                             for b, r in group['rows']]})
            for line_rec, (b, r) in zip(request.line_ids, group['rows']):
                Move.create(dict(b, date=group['date'], qty_out=r['qty_out'], source='request', request_id=request.id,
                                 line_id=line_rec.id, employee_id=group['emp'], job_id=request.job_id.id or False,
                                 import_key=r['key'], note=request.name))
                stats['out_moves'] += 1
            stats['out_requests'] += 1
        # pictures: only items that have none yet
        if self.import_pictures:
            stats['pictures'] = self._import_pictures()
        # stock-take: the stock at the report date must equal the Excel remaining quantity. Several Excel blocks can
        # share one item / size (e.g. two blocks numbered 40-1), so the quantities are summed per item / size.
        targets = {}
        for line in self.line_ids:
            if line.action != 'skip':
                block = json.loads(line.block_json)
                key = (line.item_id.id, line.size_id.id or False)
                targets[key] = targets.get(key, 0.0) + (block['last_remain'] or 0.0)
        for (item_id, size_id), target in sorted(targets.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
            have = Move.stock_map([item_id], upto=self.as_of_date).get((item_id, size_id), 0.0)
            diff = round(target - have, 4)
            if diff:
                Move.create({'item_id': item_id, 'size_id': size_id, 'import_batch_id': batch.id,
                             'date': self.as_of_date, 'qty_in': diff if diff > 0 else 0.0, 'qty_out': -diff if diff < 0 else 0.0,
                             'source': 'manual', 'import_key': 'adj|%s|%s|%s' % (item_id, size_id, batch.id),
                             'note': _('Excel stock-take difference (%s)') % (self.report_no or '')})
                stats['adjust'] += 1
        batch.note = _('Pictures added %(pics)s. ') % {'pics': stats.get('pictures', 0)} + _('Opening balances %(open)s, stock-in rows %(in)s, requests %(req)s (%(out_moves)s tools), '
                       'OUT rows without a staff match %(no_staff)s, rows already imported %(known)s, adjustments %(adjust)s.') % {
            'open': stats['open'], 'in': stats['in'], 'req': stats['out_requests'], 'out_moves': stats['out_moves'],
            'no_staff': stats['no_staff'], 'known': stats['known'], 'adjust': stats['adjust']}
        self.write({'state': 'done', 'batch_id': batch.id, 'summary': batch.note})
        return self._reopen()

    def _import_pictures(self):
        """Give the picture of each Excel block to its item (when the item has no photo). Returns the count."""
        blocks = [json.loads(l.block_json) for l in self.line_ids.sorted('sequence')]
        lines = self.line_ids.sorted('sequence')
        try:
            found = xlsx.pictures_by_block(blocks, xlsx.read_images(io.BytesIO(base64.b64decode(self.file))))
        except Exception as error:
            _logger.warning('Safety tool import: pictures not read (%s)', error)
            return 0
        done = 0
        for index, image in found.items():
            line = lines[index]
            if line.action == 'skip' or not line.item_id or line.item_id.image:
                continue
            try:
                line.item_id.image = tools.image_resize_image(base64.b64encode(image['data']), size=(600, 600), avoid_if_small=True)
                done += 1
            except Exception as error:
                _logger.warning('Safety tool import: picture %s not usable (%s)', image['media'], error)
        return done

    def action_open_batch(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'safety.tool.import.batch', 'res_id': self.batch_id.id,
                'view_mode': 'form', 'target': 'current'}


class SafetyToolImportLine(models.TransientModel):
    _name = 'safety.tool.import.line'
    _description = 'Safety Tool Excel Block'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('safety.tool.import.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer()
    block_json = fields.Text()
    excel_no = fields.Char(string='No.')
    excel_name = fields.Char(string='Excel item')
    size_text = fields.Char(string='Excel size')
    action = fields.Selection([('map', 'Import into'), ('create', 'Create the item'), ('skip', 'Skip')],
                              default='map', required=True, string='Action')
    item_id = fields.Many2one('safety.tool.item', string='Catalogue item')
    size_id = fields.Many2one('safety.tool.size', string='Size', domain="[('item_id', '=', item_id)]")
    excel_qty = fields.Float(string='Excel remaining', digits=(16, 2))
    has_picture = fields.Boolean(string='Picture in the Excel')
    n_new = fields.Integer(string='New rows', compute='_compute_preview')
    ledger_qty = fields.Float(string='Ledger now', compute='_compute_preview', digits=(16, 2))
    expected = fields.Float(string='After import', compute='_compute_preview', digits=(16, 2))
    diff = fields.Float(string='Adjustment', compute='_compute_preview', digits=(16, 2))
    has_gap = fields.Boolean(string="Excel balance doesn't add up", compute='_compute_preview')

    @api.onchange('item_id')
    def _onchange_item_id(self):
        if self.item_id and self.action == 'create':
            self.action = 'map'
        if self.size_id and self.size_id.item_id != self.item_id:
            self.size_id = False

    def _group_key(self):
        """Blocks that end up in the same item / size are compared with the stock together."""
        self.ensure_one()
        if self.item_id:
            return ('i', self.item_id.id, self.size_id.id or 0)
        return ('n', xlsx.normalize(self.excel_name), xlsx.normalize(self.size_text))

    @api.depends('action', 'item_id', 'size_id', 'wizard_id.as_of_date', 'block_json')
    def _compute_preview(self):
        Move = self.env['safety.tool.move']
        for line in self:
            block = json.loads(line.block_json) if line.block_json else {'rows': [], 'opening_qty': 0, 'last_remain': 0}
            rows = block['rows']
            calc = (block.get('opening_qty') or 0) + sum(r['qty_in'] - r['qty_out'] for r in rows)
            line.has_gap = abs(calc - (block.get('last_remain') or 0)) > 1e-9
            keys = [r['key'] for r in rows] + [block.get('open_key') or '-']
            known = set(Move.sudo().search([('import_key', 'in', keys)]).mapped('import_key'))
            line.n_new = len([r for r in rows if r['key'] not in known])
            if line.action == 'skip':
                line.ledger_qty = line.expected = line.diff = 0.0
                continue
            key = line._group_key()
            have = 0.0
            first_time = True
            if line.item_id:
                have = Move.stock_map([line.item_id.id], upto=line.wizard_id.as_of_date).get(
                    (line.item_id.id, line.size_id.id or False), 0.0)
                first_time = not Move.sudo().search_count([('item_id', '=', line.item_id.id),
                                                           ('size_id', '=', line.size_id.id or False),
                                                           ('import_batch_id', '!=', False)])
            expected = have
            target = 0.0
            for other in line.wizard_id.line_ids.filtered(lambda l: l.action != 'skip' and l._group_key() == key):
                ob = json.loads(other.block_json)
                o_known = set(Move.sudo().search([('import_key', 'in', [r['key'] for r in ob['rows']] + [ob['open_key']])]).mapped('import_key'))
                if first_time and ob['open_key'] not in o_known:
                    expected += ob.get('opening_qty') or 0
                expected += sum(r['qty_in'] - r['qty_out'] for r in ob['rows'] if r['key'] not in o_known)
                target += ob.get('last_remain') or 0
            line.ledger_qty = have
            line.expected = expected
            line.diff = target - expected
