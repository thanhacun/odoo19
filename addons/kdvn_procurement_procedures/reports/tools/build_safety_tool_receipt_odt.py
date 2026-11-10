# Builds reports/safety_tool_receipt.odt (py3o template "Receipt for Safety Tool"). Run from the module folder:
#   python3 reports/tools/build_safety_tool_receipt_odt.py reports/safety_tool_receipt.odt
import sys, zipfile

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:xlink="http://www.w3.org/1999/xlink" '
      'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" office:version="1.2"')
FONT = 'DejaVu Sans'
LINE = '#6c757d'
TABLES = {'Head': [13.4, 3.6], 'Info': [2.6, 8.0, 1.5, 4.9], 'Items': [1.2, 8.3, 1.4, 1.7, 1.7, 2.7]}


def pst(name, size, bold=False, align='start', mt='0cm', mb='0cm', color='#000000', extra_t=''):
    return ('<style:style style:name="%s" style:family="paragraph" style:parent-style-name="Standard"><style:paragraph-properties '
            'fo:text-align="%s" fo:margin-top="%s" fo:margin-bottom="%s"/><style:text-properties style:font-name="%s" fo:font-size="%s" '
            'fo:color="%s" %s %s/></style:style>') % (name, align, mt, mb, FONT, size, color,
                                                      'fo:font-weight="bold"' if bold else '', extra_t)


def cst(name, border='0.5pt solid %s' % LINE, bg=None, valign='middle'):
    return ('<style:style style:name="%s" style:family="table-cell"><style:table-cell-properties style:vertical-align="%s" '
            'fo:padding="0.035cm" fo:border="%s" %s/></style:style>') % (name, valign, border, 'fo:background-color="%s"' % bg if bg else '')


def tst(name, widths):
    out = ['<style:style style:name="%s" style:family="table"><style:table-properties style:width="17cm" table:align="margins" '
           'table:border-model="collapsing"/></style:style>' % name]
    out += ['<style:style style:name="%s.%d" style:family="table-column"><style:table-column-properties style:column-width="%scm"/></style:style>'
            % (name, i, w) for i, w in enumerate(widths)]
    return ''.join(out)


AUTO = ''.join([''.join(tst(k, v) for k, v in TABLES.items()),
                cst('N', border='none'), cst('NQ', border='none', valign='top'), cst('B'), cst('H', bg='#e9ecef'), cst('U', border='none'),
                pst('Ctrl', '6pt', color='#0000ff'), pst('Company', '8pt', bold=True, color='#6c757d', extra_t='fo:letter-spacing="0.04cm"'), pst('Title', '15pt', bold=True, mt='0.1cm', mb='0.1cm'),
                pst('Sub', '9pt', color='#6c757d'), pst('Stamp', '9pt', bold=True, color='#28a745', mt='0.12cm'),
                pst('QR', '7pt', color='#6c757d', align='center'), pst('QRRef', '8pt', bold=True, align='center'), pst('L', '8.5pt', bold=True), pst('V', '8.5pt'),
                pst('Hd', '8pt', bold=True, align='center'), pst('C', '8pt', align='center'), pst('D', '8pt'),
                pst('Sg', '9pt', bold=True, mt='0.3cm'), pst('SgN', '8.5pt', mt='1.1cm'), pst('Gap', '5pt'), pst('Sig', '8pt', align='center', mt='0.4cm'),
                '<style:style style:name="fr1" style:family="graphic"><style:graphic-properties style:vertical-pos="top" style:vertical-rel="baseline" fo:border="none" fo:padding="0cm" style:wrap="none"/></style:style>'])


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def f(expr):
    return '<text:text-input text:description="py3o://function=&quot;%s&quot;">%s</text:text-input>' % (expr, expr.split('.')[-1])


def ctrl(d):
    return '<text:p text:style-name="Ctrl"><text:a xlink:type="simple" xlink:href="py3o://%s">%s</text:a></text:p>' % (
        d.replace('"', '%22').replace(' ', '%20'), esc(d))


def p(style, inner=''):
    return '<text:p text:style-name="%s">%s</text:p>' % (style, inner)


def cell(style, *paras, span=1):
    s = ' table:number-columns-spanned="%d"' % span if span > 1 else ''
    return ('<table:table-cell table:style-name="%s" office:value-type="string"%s>%s</table:table-cell>' % (style, s, ''.join(paras))
            + '<table:covered-table-cell/>' * (span - 1))


def image(expr, w, h):
    return ('<draw:frame draw:style-name="fr1" draw:name="py3o.image(%s, \'png\', width=\'%s\', isb64=True)" text:anchor-type="as-char" '
            'svg:width="%s" svg:height="%s" draw:z-index="0"><draw:text-box><text:p/></draw:text-box></draw:frame>') % (expr, w, w, h)


def image_h(expr, h):
    return ('<draw:frame draw:style-name="fr1" draw:name="py3o.image(%s, \'png\', height=\'%s\', isb64=True)" text:anchor-type="as-char" '
            'svg:width="%s" svg:height="%s" draw:z-index="0"><draw:text-box><text:p/></draw:text-box></draw:frame>') % (expr, h, h, h)


def row(*c):
    return '<table:table-row>%s</table:table-row>' % ''.join(c)


def table(name, *rows):
    cols = ''.join('<table:table-column table:style-name="%s.%d"/>' % (name, i) for i in range(len(TABLES[name])))
    return '<table:table table:name="%s" table:style-name="%s">%s%s</table:table>' % (name, name, cols, ''.join(rows))


body = ''.join([
    ctrl('for="r in formatted_data"'),
    table('Head', row(
        cell('N',
             p('Company', 'KINDEN VIETNAM CO., LTD.'),
             p('Title', f('r.title')),
             p('Sub', 'No. <text:span text:style-name="B">%s</text:span>   |   Date: %s' % (f('r.receipt_no'), f('r.date'))),
             p('Stamp', f('r.stamp'))),
        cell('NQ',
             ctrl('if="r.qr_code_base64"'), p('QR', image_h('r.qr_code_base64', '2.5cm')), ctrl('/if'),
             p('QRRef', f('r.reference_no')), p('QR', 'Scan to verify')),
    )),
    p('Gap'),
    table('Info',
          row(cell('B', p('L', 'Project Name')), cell('B', p('V', f('r.project'))), cell('N', p('V')), cell('N', p('V'))),
          row(cell('B', p('L', 'Staff No.')), cell('B', p('V', f('r.staff_no'))), cell('N', p('V')), cell('N', p('V'))),
          row(cell('B', p('L', 'Name')), cell('B', p('V', f('r.applicant'))), cell('N', p('V')), cell('N', p('V')))),
    p('Gap'),
    table('Items',
          row(cell('H', p('Hd', 'No.')), cell('H', p('Hd', 'Description')), cell('H', p('Hd', 'Unit')),
              cell('H', p('Hd', 'Request')), cell('H', p('Hd', 'Receive')), cell('H', p('Hd', 'Remark'))),
          row(cell('B', ctrl('for="l in r.lines"'), span=6)),
          row(cell('B', p('C', f('l.no'))), cell('B', p('D', f('l.item'))), cell('B', p('C', f('l.uom'))),
              cell('B', p('C', f('l.request'))), cell('B', p('C', f('l.receive'))), cell('B', p('D', f('l.remark')))),
          row(cell('B', ctrl('/for'), span=6))),
    ctrl('if="r.signature_strip_png"'),
    p('Sig', image('r.signature_strip_png', '11cm', '3.4cm')),
    ctrl('/if'),
    ctrl('/for'),
])
content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content %s><office:font-face-decls><style:font-face style:name="%s" '
           'svg:font-family="&apos;%s&apos;" style:font-family-generic="swiss"/></office:font-face-decls><office:automatic-styles>%s'
           '<style:style style:name="B" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style></office:automatic-styles><office:body><office:text>%s</office:text></office:body></office:document-content>') % (NS, FONT, FONT, AUTO, body)
styles = ('<?xml version="1.0" encoding="UTF-8"?><office:document-styles %s><office:font-face-decls><style:font-face style:name="%s" '
          'svg:font-family="&apos;%s&apos;" style:font-family-generic="swiss"/></office:font-face-decls><office:styles>'
          '<style:default-style style:family="paragraph"><style:text-properties style:font-name="%s" fo:font-size="9pt"/></style:default-style>'
          '<style:style style:name="Standard" style:family="paragraph" style:class="text"/></office:styles><office:automatic-styles>'
          '<style:page-layout style:name="pm1"><style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" '
          'fo:margin-top="1cm" fo:margin-bottom="0.8cm" fo:margin-left="2cm" fo:margin-right="2cm"/></style:page-layout></office:automatic-styles>'
          '<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="pm1"/></office:master-styles>'
          '</office:document-styles>') % (NS, FONT, FONT, FONT)
manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
            '<manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
            '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/></manifest:manifest>')
meta = '<?xml version="1.0" encoding="UTF-8"?><office:document-meta %s><office:meta/></office:document-meta>' % NS
with zipfile.ZipFile(sys.argv[1], 'w') as z:
    z.writestr(zipfile.ZipInfo('mimetype'), 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
    for n, d in [('content.xml', content), ('styles.xml', styles), ('meta.xml', meta), ('META-INF/manifest.xml', manifest)]:
        z.writestr(n, d, compress_type=zipfile.ZIP_DEFLATED)
