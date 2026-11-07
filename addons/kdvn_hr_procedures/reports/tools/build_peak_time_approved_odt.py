# Builds reports/peak_time_approved.odt (py3o template for form CR03-03-F01, A4). Run from the module folder:
#   python3 reports/tools/build_peak_time_approved_odt.py reports/peak_time_approved.odt
# The result can also be edited by hand in LibreOffice (keep the py3o fields and links).
# Data: kderp.project.peak.time.prepare_peak_time_report_data(). Same technique as
# kderp_entertainment_procedures/reports/tools/build_entertainment_approved_odt.py.
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
FONT = 'Liberation Sans'  # Arial-compatible, like the paper form
INK, GREY = '#000000', '#444444'
BORDER = '0.5pt solid #000000'


def pstyle(name, size, bold=False, italic=False, color=INK, align='start', mt='0cm', mb='0cm', extra_p=''):
    t = 'style:font-name="%s" fo:font-size="%s" style:font-size-complex="%s" fo:color="%s"' % (FONT, size, size, color)
    if bold:
        t += ' fo:font-weight="bold" style:font-weight-complex="bold"'
    if italic:
        t += ' fo:font-style="italic"'
    return ('<style:style style:name="%s" style:family="paragraph" style:parent-style-name="Standard">'
            '<style:paragraph-properties fo:text-align="%s" fo:margin-top="%s" fo:margin-bottom="%s" %s/>'
            '<style:text-properties %s/></style:style>') % (name, align, mt, mb, extra_p, t)


def cstyle(name, border=BORDER, valign='middle', pad='0.1cm'):
    return ('<style:style style:name="%s" style:family="table-cell"><style:table-cell-properties '
            'style:vertical-align="%s" fo:padding="%s" fo:border="%s"/></style:style>') % (name, valign, pad, border)


def rstyle(name, h):
    return ('<style:style style:name="%s" style:family="table-row"><style:table-row-properties '
            'style:min-row-height="%s" fo:keep-together="always"/></style:style>') % (name, h)


def tstyle(name, widths):
    out = ['<style:style style:name="%s" style:family="table"><style:table-properties style:width="17cm" '
           'table:align="margins" fo:margin-top="0cm" fo:margin-bottom="0cm" table:border-model="collapsing"/></style:style>' % name]
    for i, w in enumerate(widths):
        out.append('<style:style style:name="%s.%d" style:family="table-column">'
                   '<style:table-column-properties style:column-width="%scm"/></style:style>' % (name, i, w))
    return ''.join(out)


# Column widths scaled from the paper form (17 cm usable on A4)
TABLES = {'Main': [0.8, 2.9, 2.2, 2.2, 2.2, 2.2, 1.5, 1.5, 1.5], 'Notes': [0.8, 2.9, 13.3],
          'Staff': [0.8, 2.9, 8.5, 4.8]}

AUTO = ''.join([
    ''.join(tstyle(k, v) for k, v in TABLES.items()),
    cstyle('C'), cstyle('CT', valign='top'), cstyle('N', border='none', pad='0.05cm'),
    rstyle('R1', '0.9cm'), rstyle('R7', '3.4cm'), rstyle('RS', '0.58cm'), rstyle('RH', '0.7cm'), rstyle('RC', '0cm'),
    pstyle('Ctrl', '6pt', color='#0000ff'),
    pstyle('Title', '14pt', bold=True, align='center', mt='0.2cm'),
    pstyle('Date', '9pt', align='end', mt='0.3cm', mb='0.2cm'),
    pstyle('Intro', '9pt', mb='0.25cm'),
    pstyle('NoC', '8.5pt', bold=True, italic=True, align='center'),
    pstyle('Lbl', '8.5pt', bold=True, italic=True),
    pstyle('Mid', '9pt', italic=True, align='center'),
    pstyle('Val', '9pt'),
    pstyle('ValC', '9pt', align='center'),
    pstyle('NoteH', '7.5pt', italic=True, mt='0.1cm', mb='0.1cm'),
    pstyle('Note', '7.5pt', italic=True),
    pstyle('StaffH', '9pt', bold=True, italic=True, mt='0.4cm', mb='0.15cm', extra_p='fo:keep-with-next="always"'),
    pstyle('Th', '8.5pt', bold=True, align='center'),
    pstyle('Gap', '6pt'),
    pstyle('Sign', '8pt', align='center', mt='0.4cm'),
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


def row(style, *cells):
    return '<table:table-row table:style-name="%s">%s</table:table-row>' % (style, ''.join(cells))


def table(name, *rows, header=''):
    cols = ''.join('<table:table-column table:style-name="%s.%d"/>' % (name, i) for i in range(len(TABLES[name])))
    return '<table:table table:name="%s" table:style-name="%s">%s%s%s</table:table>' % (name, name, cols, header, ''.join(rows))


def image(expr, w, h):
    return ('<draw:frame draw:style-name="fr1" draw:name="py3o.image(%s, \'png\', width=\'%s\', isb64=True)" text:anchor-type="as-char" '
            'svg:width="%s" svg:height="%s" draw:z-index="0"><draw:text-box><text:p/></draw:text-box></draw:frame>') % (expr, w, w, h)


def item(no, label, *value_cells, h='R1'):
    return row(h, cell('C', p('NoC', no)), cell('C', p('Lbl', label)), *value_cells)


def period(label, no, prefix, h='R1'):
    """ From / To / Total months row of items (4) to (6). """
    from_to = ('From', 'To') if prefix == 'exec' else ('From (month)', 'To (month)')
    return item(no, label,
                cell('C', p('Mid', from_to[0])), cell('C', p('ValC', f('r.%s_from' % prefix))),
                cell('C', p('Mid', from_to[1])), cell('C', p('ValC', f('r.%s_to' % prefix))),
                cell('C', p('Mid', 'Total')), cell('C', p('ValC', f('r.%s_months' % prefix))),
                cell('C', p('Mid', 'months')))


NOTES = [('1.', 'Item (5), (6)', 'These months should be match with the salary calculation time (From 21st of the last month to 20th of the certain month).'),
         ('2.', 'Item (1) ~(6)', 'In a special case that cannot determine the jobs, the information is only requested to be filled in the item (6) only and the item (1) ~(5) can be blank.'),
         ('3.', 'Item (7)', 'Explanation for special cases.')]

# Staff rows: r.staff_rows is padded to at least 9 rows by the report data method.
# py3o repeats the rows BETWEEN the row holding "for" and the row holding "/for" (those two rows
# are removed), so the data row sits between two control rows.
staff_row = ''.join([
    row('RC', cell('N', ctrl('for="s in r.staff_rows"'), span=4)),
    row('RS', cell('C', p('ValC', f('s.no'))), cell('C', p('ValC', f('s.code'))),
        cell('C', p('Val', f('s.name'))), cell('C', p('Val', f('s.remark')))),
    row('RC', cell('N', ctrl('/for'), span=4)),
])
staff_head = '<table:table-header-rows>%s</table:table-header-rows>' % row(
    'RH', cell('C', p('Th', 'No.')), cell('C', p('Th', 'Staff No.')), cell('C', p('Th', 'Staff Name')), cell('C', p('Th', 'Remark')))

body = ''.join([
    ctrl('for="r in formatted_data"'),
    p('Title', 'REQUEST OF APPROVAL<text:line-break/>FOR PROJECT PEAK TIME'),
    p('Date', 'Date: %s' % f('r.date_input')),
    p('Intro', 'In consideration of actual project execution plan, please kindly approve the peak time of working as follows:'),
    table('Main',
          item('(1)', 'Project Name', cell('C', p('Val', f('r.job_name')), span=7)),
          item('(2)', 'Client Name', cell('C', p('Val', f('r.client_name')), span=7)),
          item('(3)', 'Project No.', cell('C', p('Val', f('r.job_no')), span=7)),
          period('Execution Period', '(4)', 'exec'),
          period('Peak time<text:line-break/>(est. at K.O.M)', '(5)', 'kom'),
          period('Peak time (actual)', '(6)', 'actual'),
          item('(7)', 'Explanation', cell('CT', ctrl('for="l in r.reason_lines"'), p('Val', f('l')), ctrl('/for'), span=7), h='R7')),
    p('NoteH', 'Notes:'),
    table('Notes', *[row('RS', cell('N', p('Note', n)), cell('N', p('Note', i)), cell('N', p('Note', t)))
                     for n, i, t in NOTES]),
    p('StaffH', 'List of project execution staff :'),
    table('Staff', staff_row, header=staff_head),
    p('Gap'),
    ctrl('if="r.signature_strip_png"'),
    p('Sign', image('r.signature_strip_png', '17cm', '2.6cm')),
    ctrl('/if'),
    ctrl('/for'),
])

content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content %s>'
           '<office:font-face-decls><style:font-face style:name="%s" svg:font-family="&apos;%s&apos;" '
           'style:font-family-generic="swiss" style:font-pitch="variable"/></office:font-face-decls>'
           '<office:automatic-styles>%s</office:automatic-styles>'
           '<office:body><office:text>%s</office:text></office:body></office:document-content>') % (NS, FONT, FONT, AUTO, body)

PAGE = ('Page <text:page-number text:select-page="current">1</text:page-number>/'
        '<text:page-count>1</text:page-count>')
styles = ('<?xml version="1.0" encoding="UTF-8"?><office:document-styles %s>'
          '<office:font-face-decls><style:font-face style:name="%s" svg:font-family="&apos;%s&apos;" '
          'style:font-family-generic="swiss" style:font-pitch="variable"/></office:font-face-decls>'
          '<office:styles><style:default-style style:family="paragraph"><style:text-properties style:font-name="%s" '
          'fo:font-size="9pt" fo:language="en" fo:country="US"/></style:default-style>'
          '<style:style style:name="Standard" style:family="paragraph" style:class="text"/>%s%s</office:styles>'
          '<office:automatic-styles><style:page-layout style:name="pm1"><style:page-layout-properties fo:page-width="21cm" '
          'fo:page-height="29.7cm" style:print-orientation="portrait" fo:margin-top="1.0cm" fo:margin-bottom="1.0cm" '
          'fo:margin-left="2cm" fo:margin-right="2cm"/><style:header-style><style:header-footer-properties '
          'fo:min-height="0cm" fo:margin-bottom="0.3cm"/></style:header-style><style:footer-style>'
          '<style:header-footer-properties fo:min-height="0cm" fo:margin-top="0.3cm"/></style:footer-style></style:page-layout>'
          '</office:automatic-styles><office:master-styles><style:master-page style:name="Standard" style:page-layout-name="pm1">'
          '<style:header>%s</style:header><style:footer>%s</style:footer></style:master-page></office:master-styles>'
          '</office:document-styles>') % (
    NS, FONT, FONT, FONT, pstyle('FormNo', '7pt', italic=True, align='center',
                                extra_p='fo:margin-left="12.8cm" fo:border="%s" fo:padding="0.05cm"' % BORDER),
    pstyle('Page', '7pt', align='end'), p('FormNo', 'Form No.: CR03-03-F01'), p('Page', PAGE))

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
