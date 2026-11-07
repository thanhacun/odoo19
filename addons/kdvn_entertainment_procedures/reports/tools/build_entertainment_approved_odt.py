# Builds reports/entertainment_approved.odt (py3o template). Run from the module folder:
#   python3 reports/tools/build_entertainment_approved_odt.py reports/entertainment_approved.odt
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


TABLES = {'Head': [13.4, 3.6], 'Info': [2.4, 5.6, 3.2, 5.8], 'Count': [8.5, 8.5],
          'Names': [8.5, 8.5], 'Amount': [8.5, 8.5], 'Att': [2.4, 14.6]}

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


def people(prefix):
    """ Names cell: one-per-line list / compact paragraph / count only (one of the three is filled). """
    return ''.join([
        ctrl('for="n in r.%s_list"' % prefix), p('Name', f('n')), ctrl('/for'),
        ctrl('if="r.%s_compact"' % prefix), p('Compact', f('r.%s_compact' % prefix)), ctrl('/if'),
        ctrl('if="r.%s_total"' % prefix), p('TotalOnly', f('r.%s_total' % prefix)), ctrl('/if'),
    ])


body = ''.join([
    ctrl('for="r in formatted_data"'),
    table('Head', row(
        cell('N',
             p('Company', 'KINDEN VIETNAM CO., LTD.'),
             p('Title', 'REQUEST OF APPROVAL FOR<text:line-break/>ENTERTAINMENT EXPENSE'),
             p('Sub', 'No. <text:span text:style-name="B">%s</text:span>   |   Request date: %s' % (f('r.reference_no'), f('r.date_input'))),
             p('Stamp', '&#10003; APPROVED')),
        cell('NQ',
             ctrl('if="r.qr_code_base64"'), p('QR', image('r.qr_code_base64', None, '2.5cm')), ctrl('/if'),
             p('QRRef', f('r.reference_no')), p('QR', 'Scan to verify')),
    )),
    p('Sec', '1. Entertainment details'),
    table('Info',
          row(cell('L', p('Lbl', 'Applicant')), cell('V', p('ValB', f('r.applicant'))),
              cell('L', p('Lbl', 'Entertainment date')), cell('V', p('ValB', f('r.date_entertainment')))),
          row(cell('L', p('Lbl', 'Place')), cell('V', p('Val', f('r.place'))),
              cell('L', p('Lbl', 'Type')), cell('V', p('Val', f('r.entertainment_type')))),
          row(cell('L', p('Lbl', 'Purpose')), cell('V', p('Val', f('r.reason')), span=3)),
          row(cell('L', p('Lbl', 'Job')), cell('V', p('Val', f('r.job_display_name')), span=3)),
          row(cell('L', p('Lbl', 'Budget')), cell('V', p('Val', f('r.budget_code')), span=3)),
          ),
    p('Sec', '2. Attendance'),
    table('Count', row(
        cell('K', p('KLbl', 'Our company (listed)'), p('KVal', f('r.emp_count'))),
        cell('KT', p('KLbl', 'Total people'), p('KVal', f('r.total_pax'))),
    )),
    p('Gap'),
    table('Names',
          row(cell('H', p('Head', 'Our company')), cell('H', p('Head', 'Owner / Client / Guest'))),
          row(cell('VT', people('emp')), cell('VT', people('guest')))),
    p('Sec', '3. Amount'),
    table('Amount', row(
        cell('KT', p('KLbl', 'Estimated amount'), p('KVal', f('r.estimated_amount'))),
        cell('K', p('KLbl', 'Amount per person'), p('KValS', f('r.per_pax_amount'))),
    )),
    p('Gap'),
    table('Att', row(cell('L', p('Lbl', 'Attachments')), cell('V', p('Val', f('r.attachments'))))),
    p('Sec', '4. Approval'),
    ctrl('if="r.signature_strip_png"'),
    p('QR', image('r.signature_strip_png', '17cm', '2.6cm')),
    ctrl('/if'),
    p('Note', 'Approved electronically in KDERP e-Approval; no handwritten signature is required. '
              'Scan the QR code to check this approval online.'),
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
    ('Rem', '1. For each entertainment occurrence, please fill in the purpose of the expense in this form:'),
    ('RemI', '* If the total entertainment expense is VND 2.000.000 and over (total amount of all invoices), approval from the General Director is required.'),
    ('RemI', '* If the total entertainment expense is less than VND 2.000.000 (total amount of all invoices), approval from the Area Manager / General Manager is required.'),
    ('Rem', '2. Attach this form to the invoice(s) when making settlement.'),
    ('Rem', '3. For payment of VND 5.000.000 or more, it is required to pay by Credit Card or Bank Transfer in accordance with the '
            'Regulation No. QCTC/2025-001 dated 20<text:span text:style-name="Sup">th</text:span> June 2025. It is also required to attach '
            'a successful Credit Card Swipe receipt or Bank Transfer receipt when making settlement.'),
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
