"""Reader of the Safety Tool Control Sheet (xlsx) with the standard library only
(zipfile + ElementTree): production needs no extra Python package.

Layout (checked on 'Safety Tool Control Sheet 2026-T8', report No. 142):
- one sheet named like 'Safety tool control sheet'; row 2 holds the report date (a serial number) in the last column
- a header row with 'No.' in column B and 'Item', 'Date', 'Project Name', 'PIC', "Q'ty" over IN / OUT / Remain
- an item block starts at a row with a number in column B (item name in column C); the first row is the opening
  balance (date 31 Dec, Remain = quantity); then one row per event: date, project, PIC staff code (+ name), IN or OUT,
  Remain (running), remarks. Extra text in column C (e.g. 'Size L') describes the item.
- a block without a number can start at a row with a Remain value, no IN/OUT and 'Periodical check' as remark.
"""
import datetime
import re
import zipfile
from xml.etree import ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
EPOCH = datetime.date(1899, 12, 30)


def _col(ref):
    return re.match(r'[A-Z]+', ref).group(0)


def _text(elem):
    return ''.join(t.text or '' for t in elem.iter('{%s}t' % NS['m']))


def _clean(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def normalize(value):
    """Lower case, no accents-insensitive tricks: just spaces and punctuation folded, for matching."""
    return re.sub(r'[^0-9a-z]+', ' ', (value or '').lower()).strip()


def _to_date(value):
    if value in (None, ''):
        return None
    try:
        return EPOCH + datetime.timedelta(days=int(float(value)))
    except (TypeError, ValueError):
        pass
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_sheet_rows(data, sheet_hint='control'):
    """{row number: {column letter: value}} of the sheet whose name contains `sheet_hint`
    (else the last sheet). Values are strings (numbers keep their text form)."""
    archive = zipfile.ZipFile(data)
    shared = []
    if 'xl/sharedStrings.xml' in archive.namelist():
        root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        shared = [_text(si) for si in root.findall('m:si', NS)]
    workbook = ET.fromstring(archive.read('xl/workbook.xml'))
    rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    targets = {rel.get('Id'): rel.get('Target') for rel in rels}
    sheets = [(s.get('name'), targets[s.get('{%s}id' % NS['r'])]) for s in workbook.find('m:sheets', NS)]
    chosen = next((t for n, t in sheets if sheet_hint in (n or '').lower()), sheets[-1][1])
    path = chosen.lstrip('/') if chosen.startswith('/') else 'xl/' + chosen
    root = ET.fromstring(archive.read(path))
    rows = {}
    for row in root.iter('{%s}row' % NS['m']):
        cells = {}
        for cell in row.findall('m:c', NS):
            kind = cell.get('t')
            if kind == 'inlineStr':
                value = _text(cell)
            else:
                v = cell.find('m:v', NS)
                if v is None or v.text is None:
                    continue
                value = shared[int(v.text)] if kind == 's' else v.text
            if value != '':
                cells[_col(cell.get('r'))] = value
        if cells:
            rows[int(row.get('r'))] = cells
    return rows


def parse_control_sheet(data):
    """-> {'report_date': date or None, 'report_no': str, 'blocks': [block, ...]}
    block = {'no', 'name', 'texts': [str], 'size_text', 'opening_date', 'opening_qty', 'last_remain',
             'rows': [{'row', 'date', 'project', 'staff_code', 'staff_name', 'qty_in', 'qty_out', 'remain', 'remarks'}]}"""
    rows = read_sheet_rows(data)
    # Columns from the header row (fall back to the layout above)
    cols = {'no': 'B', 'item': 'C', 'date': 'E', 'project': 'F', 'code': 'G', 'name': 'H', 'in': 'I', 'out': 'J',
            'remain': 'K', 'remarks': 'L'}
    header_row = next((r for r, c in sorted(rows.items()) if _clean(c.get('B')).lower() in ('no.', 'no')), None)
    report_date = None
    report_no = ''
    for r in sorted(rows)[:6]:
        for letter, value in rows[r].items():
            if re.match(r'^No\.?\s*\d+', _clean(value)):
                report_no = _clean(value)
            if letter > 'M' and report_date is None and r < (header_row or 99):
                report_date = _to_date(value)
    if header_row:
        for letter, value in rows[header_row].items():
            key = _clean(value).lower()
            for name, words in (('item', ('item',)), ('date', ('date',)), ('project', ('project',)),
                                ('code', ('pic',)), ('remarks', ('remraks', 'remarks', 'remark'))):
                if key in words:
                    cols[name] = letter
        sub = rows.get(header_row + 1, {})
        for letter, value in sub.items():
            key = _clean(value).upper()
            if key == 'IN':
                cols['in'] = letter
            elif key == 'OUT':
                cols['out'] = letter
            elif key == 'REMAIN':
                cols['remain'] = letter
        cols['name'] = chr(ord(cols['code']) + 1)

    blocks = []
    current = None
    start_row = (header_row or 0) + 2
    for r in sorted(rows):
        if r < start_row:
            continue
        c = rows[r]
        no = _clean(c.get(cols['no']))
        text = _clean(c.get(cols['item']))
        qty_in = _to_float(c.get(cols['in']))
        qty_out = _to_float(c.get(cols['out']))
        remain = _to_float(c.get(cols['remain']))
        remarks = _clean(c.get(cols['remarks']))
        date = _to_date(c.get(cols['date']))
        no_match = re.match(r"^(\d+)(?:\s*-\s*(\d+))?\s*'?$", no) if no else None
        starts_numbered = bool(no_match)
        starts_plain = (not no and remain is not None and qty_in is None and qty_out is None
                        and 'periodical' in remarks.lower() and text)
        if starts_numbered or starts_plain:
            current = {'no': (no_match.group(1) + ('-' + no_match.group(2) if no_match.group(2) else '')) if starts_numbered else '',
                       'name': text, 'texts': [],
                       'size_text': '', 'opening_date': date, 'opening_qty': remain or 0.0,
                       'last_remain': remain, 'rows': [], 'first_row': r}
            blocks.append(current)
            continue
        if current is None:
            continue
        if text and not (qty_in or qty_out):
            current['texts'].append(text)
        if qty_in or qty_out:
            if text:
                current['texts'].append(text)
            current['rows'].append({
                'row': r, 'date': date, 'project': _clean(c.get(cols['project'])),
                'staff_code': _clean(c.get(cols['code'])).upper(), 'staff_name': _clean(c.get(cols['name'])),
                'qty_in': qty_in or 0.0, 'qty_out': qty_out or 0.0, 'remain': remain, 'remarks': remarks})
        if remain is not None and (qty_in or qty_out or not text):
            current['last_remain'] = remain
    for block in blocks:
        block['desc'] = ''
        block['dims'] = ''
        for text in block['texts']:
            if re.search(r'\bW\s*[\d,.]+\s*x\s*H\s*[\d,.]+', text, re.I):
                block['dims'] = block['dims'] or text            # sign / flag dimensions: a note, not a size
                continue
            m = re.match(r'^size\s*:?\s*(.+)$', text, re.I)
            if m:
                block['size_text'] = block['size_text'] or _clean(m.group(1))
            elif re.match(r'^\d+(\.\d+)?\s*cm\b', text, re.I):
                block['size_text'] = block['size_text'] or text
            elif not block['desc']:
                block['desc'] = text
        if block['last_remain'] is None:
            block['last_remain'] = block['opening_qty']
    return {'report_date': report_date, 'report_no': report_no, 'blocks': blocks, 'columns': cols}


def read_images(data, sheet_hint='control'):
    """Pictures placed on the sheet: [{'row': first row (1-based), 'col': column (0-based), 'media': file name,
    'data': bytes}], one entry per picture position (Excel often writes each picture twice)."""
    archive = zipfile.ZipFile(data)
    workbook = ET.fromstring(archive.read('xl/workbook.xml'))
    rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    targets = {rel.get('Id'): rel.get('Target') for rel in rels}
    sheets = [(s.get('name'), targets[s.get('{%s}id' % NS['r'])]) for s in workbook.find('m:sheets', NS)]
    chosen = next((t for n, t in sheets if sheet_hint in (n or '').lower()), sheets[-1][1])
    sheet_path = chosen.lstrip('/') if chosen.startswith('/') else 'xl/' + chosen
    folder, name = sheet_path.rsplit('/', 1)
    rels_path = '%s/_rels/%s.rels' % (folder, name)
    if rels_path not in archive.namelist():
        return []
    drawing = None
    for rel in ET.fromstring(archive.read(rels_path)):
        if rel.get('Type', '').endswith('/drawing'):
            drawing = rel.get('Target')
    if not drawing:
        return []
    drawing_path = ('xl/' + drawing.replace('../', '')) if not drawing.startswith('/') else drawing.lstrip('/')
    d_folder, d_name = drawing_path.rsplit('/', 1)
    media_of = {}
    d_rels = '%s/_rels/%s.rels' % (d_folder, d_name)
    if d_rels in archive.namelist():
        for rel in ET.fromstring(archive.read(d_rels)):
            media_of[rel.get('Id')] = 'xl/' + rel.get('Target').replace('../', '')
    xdr = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
    a_ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    result, seen = [], set()
    for anchor in ET.fromstring(archive.read(drawing_path)).iter():
        if not anchor.tag.endswith('Anchor'):
            continue
        origin = anchor.find('{%s}from' % xdr)
        blip = next((e for e in anchor.iter('{%s}blip' % a_ns)), None)
        if origin is None or blip is None:
            continue
        media = media_of.get(blip.get('{%s}embed' % NS['r']))
        if not media or media not in archive.namelist():
            continue
        row = int(origin.find('{%s}row' % xdr).text) + 1
        col = int(origin.find('{%s}col' % xdr).text)
        if (row, col, media) in seen:
            continue
        seen.add((row, col, media))
        result.append({'row': row, 'col': col, 'media': media.rsplit('/', 1)[-1], 'data': archive.read(media)})
    return sorted(result, key=lambda i: (i['row'], i['col']))


def pictures_by_block(blocks, images, max_col=4, min_bytes=2000):
    """{index of the block in `blocks`: image dict}: the first picture placed inside the rows of each block."""
    starts = sorted((b['first_row'], i) for i, b in enumerate(blocks) if b.get('first_row'))
    result = {}
    for image in images:
        if image['col'] > max_col or len(image['data']) < min_bytes:
            continue
        owner = None
        for first_row, index in starts:
            if first_row <= image['row']:
                owner = index
            else:
                break
        if owner is not None and owner not in result:
            result[owner] = image
    return result
