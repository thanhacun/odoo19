# Builds reports/safety_tool_request.odt (py3o template). Run from the module folder:
#   python3 reports/tools/build_safety_tool_odt.py reports/safety_tool_request.odt
# The result can also be edited by hand in LibreOffice (keep the py3o fields and links).
import sys, zipfile

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
      'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
      'xmlns:xlink="http://www.w3.org/1999/xlink" '
      'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
      'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" office:version="1.2"')
FONT = 'DejaVu Sans'
INK, MUTED, LINE, LABEL_BG, ACCENT, DONE = '#212529', '#6c757d', '#adb5bd', '#f1f3f5', '#7C7BAD', '#28a745'


def pstyle(name, size, bold=False, italic=False, color=INK, align='start', mt='0cm', mb='0cm', extra_p='', extra_t=''):
    t = 'style:font-name="%s" fo:font-size="%s" style:font-size-complex="%s" fo:color="%s"' % (FONT, size, size, color)
    if bold:
        t += ' fo:font-weight="bold" style:font-weight-complex="bold"'
    if italic:
        t += ' fo:font-style="italic"'
    return ('<style:style style:name="%s" style:family="paragraph" style:parent-style-name="Standard">'
            '<style:paragraph-properties fo:text-align="%s" fo:margin-top="%s" fo:margin-bottom="%s" %s/>'
            '<style:text-properties %s %s/></style:style>') % (name, align, mt, mb, extra_p, t, extra_t)


def cstyle(name, bg=None, border='0.5pt solid %s' % LINE, valign='middle', pad='0.12cm', extra=''):
    b = 'fo:border="%s"' % border
    bgs = 'fo:background-color="%s"' % bg if bg else ''
    return ('<style:style style:name="%s" style:family="table-cell"><style:table-cell-properties '
            'style:vertical-align="%s" fo:padding="%s" %s %s %s/></style:style>') % (name, valign, pad, b, bgs, extra)


def tstyle(name, widths):
    out = ['<style:style style:name="%s" style:family="table"><style:table-properties style:width="17cm" '
           'table:align="margins" fo:margin-top="0cm" fo:margin-bottom="0cm" table:border-model="collapsing"/></style:style>' % name]
    for i, w in enumerate(widths):
        out.append('<style:style style:name="%s.%d" style:family="table-column">'
                   '<style:table-column-properties style:column-width="%scm"/></style:style>' % (name, i, w))
    return ''.join(out)


TABLES = {'Head': [13.4, 3.6], 'Info': [2.8, 5.7, 2.8, 5.7], 'Tools': [1.2, 8.2, 3.4, 2.0, 2.2],
          'Exp': [2.8, 5.7, 2.8, 5.7], 'Cost': [5.67, 5.67, 5.66], 'Trouble': [3.2, 13.8]}

AUTO = ''.join([
    ''.join(tstyle(k, v) for k, v in TABLES.items()),
    cstyle('N', border='none', pad='0cm'),
    cstyle('NQ', border='none', pad='0cm', valign='top'),
    cstyle('L', bg=LABEL_BG),
    cstyle('V'),
    cstyle('VT', valign='top'),
    cstyle('H', bg=LABEL_BG, pad='0.08cm'),
    cstyle('K', pad='0.14cm'),
    cstyle('KT', pad='0.14cm', bg=LABEL_BG),
    pstyle('Ctrl', '6pt', color='#0000ff'),
    pstyle('Company', '8pt', bold=True, color=MUTED, extra_t='fo:letter-spacing="0.04cm"'),
    pstyle('Title', '15pt', bold=True, mt='0.1cm', mb='0.1cm'),
    pstyle('Sub', '9pt', color=MUTED),
    pstyle('Stamp', '9pt', bold=True, color=DONE, mt='0.12cm'),
    pstyle('QR', '7pt', color=MUTED, align='center'),
    pstyle('QRRef', '8pt', bold=True, align='center'),
    pstyle('Sec', '10pt', bold=True, color=INK, mt='0.4cm', mb='0.15cm',
           extra_p='fo:border-bottom="1.2pt solid %s" fo:padding-bottom="0.05cm" fo:keep-with-next="always"' % ACCENT),
    pstyle('Lbl', '8.5pt', color=MUTED),
    pstyle('Val', '9.5pt'),
    pstyle('ValB', '9.5pt', bold=True),
    pstyle('Head', '8.5pt', bold=True, color=MUTED),
    pstyle('KLbl', '8pt', color=MUTED, align='center'),
    pstyle('KVal', '13pt', bold=True, align='center'),
    pstyle('KValS', '11pt', bold=True, align='center'),
    pstyle('Name', '9.5pt', mt='0.02cm', mb='0.02cm'),
    pstyle('Compact', '7.5pt', extra_p='fo:line-height="115%"'),
    pstyle('TotalOnly', '9.5pt', italic=True, color=MUTED),
    pstyle('Note', '7.5pt', italic=True, color=MUTED, mt='0.1cm', align='center'),
    pstyle('Gap', '4pt'),
    pstyle('ValC', '9.5pt', align='center'),
    pstyle('ValR', '9.5pt', align='end'),
    pstyle('HeadC', '8.5pt', bold=True, color=MUTED, align='center'),
    pstyle('Photo', '8pt', color=MUTED, align='center', mt='0.1cm'),
    '<style:style style:name="fr1" style:family="graphic"><style:graphic-properties style:vertical-pos="top" '
    'style:vertical-rel="baseline" fo:border="none" fo:padding="0cm" style:wrap="none"/></style:style>',
])


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def f(expr, label=None):
    return '<text:text-input text:description="py3o://function=&quot;%s&quot;">%s</text:text-input>' % (expr, label or expr.split('.')[-1])


def ctrl(directive):
    href = directive.replace('"', '%22').replace(' ', '%20')
    return '<text:p text:style-name="Ctrl"><text:a xlink:type="simple" xlink:href="py3o://%s">%s</text:a></text:p>' % (href, esc(directive))


def p(style, inner=''):
    return '<text:p text:style-name="%s">%s</text:p>' % (style, inner)


def cell(style, *paras, span=1):
    s = ' table:number-columns-spanned="%d"' % span if span > 1 else ''
    out = '<table:table-cell table:style-name="%s" office:value-type="string"%s>%s</table:table-cell>' % (style, s, ''.join(paras))
    return out + '<table:covered-table-cell/>' * (span - 1)


def row(*cells):
    return '<table:table-row>%s</table:table-row>' % ''.join(cells)


def table(name, *rows):
    cols = ''.join('<table:table-column table:style-name="%s.%d"/>' % (name, i) for i in range(len(TABLES[name])))
    return '<table:table table:name="%s" table:style-name="%s">%s%s</table:table>' % (name, name, cols, ''.join(rows))


def image(expr, w, h):
    return ('<draw:frame draw:style-name="fr1" draw:name="py3o.image(%s, \'png\', %s, isb64=True)" text:anchor-type="as-char" '
            'svg:width="%s" svg:height="%s" draw:z-index="0"><draw:text-box><text:p/></draw:text-box></draw:frame>') % (
        expr, ("width='%s'" % w) if w else ("height='%s'" % h), w or h, h)


body = ''.join([
    ctrl('for="r in formatted_data"'),
    table('Head', row(
        cell('N',
             p('Company', 'KINDEN VIETNAM CO., LTD.'),
             p('Title', f('r.title')),
             p('Sub', 'No. <text:span text:style-name="B">%s</text:span>   |   Date: %s' % (f('r.reference_no'), f('r.date_input'))),
             p('Stamp', f('r.stamp'))),
        cell('NQ',
             ctrl('if="r.qr_code_base64"'), p('QR', image('r.qr_code_base64', None, '2.5cm')), ctrl('/if'),
             p('QRRef', f('r.reference_no')), p('QR', 'Scan to verify')),
    )),
    p('Sec', '1. Applicant'),
    table('Info',
          row(cell('L', p('Lbl', 'Applicant')), cell('V', p('ValB', f('r.applicant'))),
              cell('L', p('Lbl', 'Staff no.')), cell('V', p('Val', f('r.staff_no')))),
          row(cell('L', p('Lbl', 'Department')), cell('V', p('Val', f('r.department'))),
              cell('L', p('Lbl', 'Request type')), cell('V', p('Val', f('r.request_type')))),
          row(cell('L', p('Lbl', 'Purpose')), cell('V', p('Val', f('r.reason')), span=3)),
          ),
    p('Sec', '2. Tools requested'),
    table('Tools',
          row(cell('H', p('HeadC', 'No.')), cell('H', p('Head', 'Tool')), cell('H', p('HeadC', 'Size')),
              cell('H', p('HeadC', 'Quantity')), cell('H', p('HeadC', 'Unit'))),
          # py3o repeats the rows BETWEEN the row holding the 'for' and the row holding the '/for' (both are removed)
          row(cell('V', ctrl('for="l in r.lines"'), span=5)),
          row(cell('V', p('ValC', f('l.no'))),
              cell('V', p('Val', f('l.item'))),
              cell('V', p('ValC', f('l.size'))),
              cell('V', p('ValC', f('l.qty'))),
              cell('V', p('ValC', f('l.uom')))),
          row(cell('V', ctrl('/for'), span=5))),
    p('Sec', '3. Expense'),
    table('Exp',
          row(cell('L', p('Lbl', 'Job')), cell('V', p('Val', f('r.job')), span=3)),
          row(cell('L', p('Lbl', 'Budget code')), cell('V', p('Val', f('r.budget_code'))),
              cell('L', p('Lbl', 'Office code')), cell('V', p('Val', f('r.office_code'))))),
    p('Gap'),
    table('Cost', row(
        cell('KT', p('KLbl', 'Cost'), p('KValS', f('r.cost'))),
        cell('K', p('KLbl', 'VAT (10%)'), p('KValS', f('r.vat'))),
        cell('KT', p('KLbl', 'Total'), p('KValS', f('r.total'))))),
    ctrl('if="r.is_replace"'),
    p('Sec', '4. Trouble report (company assets)'),
    table('Trouble',
          row(cell('L', p('Lbl', 'Date of the trouble')), cell('V', p('Val', f('r.trouble_date')))),
          row(cell('L', p('Lbl', 'Place')), cell('V', p('Val', f('r.trouble_place')))),
          row(cell('L', p('Lbl', 'Damaged item')), cell('V', p('Val', f('r.damaged_item')))),
          row(cell('L', p('Lbl', 'Fixed assets code')), cell('V', p('Val', f('r.asset_code')))),
          row(cell('L', p('Lbl', 'Situation')), cell('VT', p('Val', f('r.trouble_note')))),
          row(cell('L', p('Lbl', 'Solution')), cell('V', p('Val', f('r.solution')))),
          row(cell('L', p('Lbl', 'Estimated cost to repair')), cell('V', p('Val', f('r.repair_cost'))))),
    ctrl('for="ph in r.photos"'),
    p('Photo', image('ph', '8cm', '6cm')),
    ctrl('/for'),
    ctrl('/if'),
    p('Sec', f('r.approval_title')),
    ctrl('if="r.signature_strip_png"'),
    p('QR', image('r.signature_strip_png', '17cm', '2.6cm')),
    ctrl('/if'),
    p('Note', f('r.approval_note')),
    ctrl('/for'),
])

content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content %s>'
           '<office:font-face-decls><style:font-face style:name="%s" svg:font-family="&apos;%s&apos;" '
           'style:font-family-generic="swiss" style:font-pitch="variable"/></office:font-face-decls>'
           '<office:automatic-styles>%s<style:style style:name="B" style:family="text">'
           '<style:text-properties fo:font-weight="bold" fo:color="%s"/></style:style></office:automatic-styles>'
           '<office:body><office:text>%s</office:text></office:body></office:document-content>') % (NS, FONT, FONT, AUTO, INK, body)

REMARK = [
    ('RemH', 'Remark'),
    ('Rem', '1. Safety tools are company assets. A broken or worn tool must be reported with the Trouble Report (date, place, photo) before a replacement is requested.'),
    ('Rem', '2. The store hands the tools over only after this request is approved; please confirm the receipt in the e-Approval system.'),
]
styles = ('<?xml version="1.0" encoding="UTF-8"?><office:document-styles %s>'
          '<office:font-face-decls><style:font-face style:name="%s" svg:font-family="&apos;%s&apos;" '
          'style:font-family-generic="swiss" style:font-pitch="variable"/></office:font-face-decls>'
          '<office:styles><style:default-style style:family="paragraph"><style:text-properties style:font-name="%s" '
          'fo:font-size="10pt" fo:language="en" fo:country="US"/></style:default-style>'
          '<style:style style:name="Standard" style:family="paragraph" style:class="text"/>'
          '<style:style style:name="Sup" style:family="text"><style:text-properties style:text-position="super 58%%"/></style:style>'
          '%s%s%s</office:styles>'
          '<office:automatic-styles><style:page-layout style:name="pm1"><style:page-layout-properties fo:page-width="21cm" '
          'fo:page-height="29.7cm" style:print-orientation="portrait" fo:margin-top="1.5cm" fo:margin-bottom="1.2cm" '
          'fo:margin-left="2cm" fo:margin-right="2cm"/><style:footer-style><style:header-footer-properties '
          'fo:min-height="0cm" fo:margin-top="0.3cm"/></style:footer-style></style:page-layout></office:automatic-styles>'
          '<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="pm1"><style:footer>%s'
          '</style:footer></style:master-page></office:master-styles></office:document-styles>') % (
    NS, FONT, FONT, FONT,
    pstyle('RemH', '7.5pt', bold=True, color=MUTED, extra_p='fo:border-top="0.5pt solid %s" fo:padding-top="0.1cm"' % LINE),
    pstyle('Rem', '7pt', color=MUTED),
    pstyle('RemI', '7pt', color=MUTED, extra_p='fo:margin-left="0.3cm"'),
    ''.join(p(s, t) for s, t in REMARK))

manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
            '<manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
            '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
            '</manifest:manifest>')
meta = ('<?xml version="1.0" encoding="UTF-8"?><office:document-meta %s><office:meta>'
        '<meta:generator>kderp build_odt.py</meta:generator></office:meta></office:document-meta>') % NS

with zipfile.ZipFile(sys.argv[1], 'w') as z:
    z.writestr(zipfile.ZipInfo('mimetype'), 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
    for name, data in [('content.xml', content), ('styles.xml', styles), ('meta.xml', meta), ('META-INF/manifest.xml', manifest)]:
        z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
