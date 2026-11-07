# Builds reports/staff_transfer.odt (py3o template for form CR04-03-F01, A4). Run from the module folder:
#   python3 reports/tools/build_staff_transfer_odt.py \
#       ../kderp_entertainment_procedures/reports/entertainment_approved.odt reports/staff_transfer.odt
# Arg 1 only supplies the page styles (A4, 2 cm side margins); its footer is removed.
# The result can also be edited by hand in LibreOffice (keep the py3o fields, links and image frames).
# Data: staff.transfer._prepare_staff_transfer_report_data(). Images: r.qr_code_base64, r.matrix_png
# (transfer.allowance.matrix.render_matrix_png), r.signature_strip_png (mixin _prepare_reviews_signatures).
import sys, zipfile, os
from xml.sax.saxutils import escape, quoteattr
ENT, OUT = sys.argv[1], sys.argv[2]

def fn(expr, placeholder):
    return '<text:text-input text:description="py3o://function=&quot;%s&quot;">%s</text:text-input>' % (expr, escape(placeholder))

def ctrl(stmt):  # py3o control paragraph (for/if), removed when rendered
    href = 'py3o://' + stmt.replace('"', '%22').replace(' ', '%20')
    return '<text:p text:style-name="Ctrl"><text:a xlink:type="simple" xlink:href=%s>%s</text:a></text:p>' % (quoteattr(href), escape(stmt))

def img(expr, w, h, style='fr1'):
    return ('<draw:frame draw:style-name="%s" draw:name=%s text:anchor-type="as-char" svg:width="%s" svg:height="%s" draw:z-index="0">'
            '<draw:text-box><text:p/></draw:text-box></draw:frame>') % (style, quoteattr(expr), w, h)

def p(content, style='Body'):
    return '<text:p text:style-name="%s">%s</text:p>' % (style, content)

def cell(content, style='C', span=1):
    s = '<table:table-cell table:style-name="%s" office:value-type="string"%s>%s</table:table-cell>' % (
        style, (' table:number-columns-spanned="%d"' % span) if span > 1 else '', content)
    return s + '<table:covered-table-cell/>' * (span - 1)

def table(name, widths, rows):
    cols = ''.join('<table:table-column table:style-name="%s.%d"/>' % (name, i) for i in range(len(widths)))
    return '<table:table table:name="%s" table:style-name="%s">%s%s</table:table>' % (
        name, name, cols, ''.join('<table:table-row>%s</table:table-row>' % r for r in rows))

def table_styles(name, widths):
    s = '<style:style style:name="%s" style:family="table"><style:table-properties style:width="%.2fcm" table:align="margins"/></style:style>' % (name, sum(widths))
    for i, w in enumerate(widths):
        s += '<style:style style:name="%s.%d" style:family="table-column"><style:table-column-properties style:column-width="%.2fcm"/></style:style>' % (name, i, w)
    return s

L = lambda t: p(escape(t), 'Label')
V = lambda e, ph: p(fn(e, ph), 'Value')

widths_info = [3.2, 5.3, 3.2, 5.3]
info = table('Info', widths_info, [
    cell(L('Staff No.:'), 'CL') + cell(V('r.staff_code', 'staff_code')) + cell(L('Request No.:'), 'CL') + cell(V('r.reference_no', 'reference_no')),
    cell(L('Staff Name:'), 'CL') + cell(V('r.staff_name', 'staff_name')) + cell(L('Grade:'), 'CL') + cell(V('r.grade', 'grade')),
    cell(L('Requested by:'), 'CL') + cell(V('r.applicant', 'applicant')) + cell(L('Request date:'), 'CL') + cell(V('r.request_date', 'request_date')),
    cell(L('Reason of transfer:'), 'CL') + cell(V('r.reason', 'reason'), 'C', 3),
])

widths_tr = [3.2, 6.15, 1.3, 6.35]
arrow = p('&#8594;', 'Center')
tr = table('Transfer', widths_tr, [
    cell(p('', 'Label'), 'CL') + cell(p('Current', 'HeadC'), 'CH') + cell(p('', 'HeadC'), 'CH') + cell(p('New', 'HeadC'), 'CH'),
    cell(L('Area:'), 'CL') + cell(V('r.src_area', 'src_area')) + cell(arrow) + cell(V('r.dest_area', 'dest_area')),
    cell(L('Section:'), 'CL') + cell(V('r.src_dept', 'src_dept')) + cell(arrow) + cell(V('r.dest_dept', 'dest_dept')),
    cell(L('Project:'), 'CL') + cell(V('r.src_proj', 'src_proj')) + cell(arrow) + cell(V('r.dest_proj', 'dest_proj')),
    cell(L('Transfer period:'), 'CL') + cell(V('r.start_date', 'start_date')) + cell(arrow) + cell(V('r.end_date', 'end_date')),
])

title = table('Title', [14.2, 2.8], [
    cell(p(escape('REQUEST OF APPROVAL FOR PERSONNEL TRANSFER'), 'Title1'), 'N') +
    cell(ctrl('if="r.qr_code_base64"') + p(img("py3o.image(r.qr_code_base64, 'png', height='2.2cm', isb64=True)", '2.2cm', '2.2cm'), 'Center') + ctrl('/if')
         + p(fn('r.reference_no', 'reference_no'), 'Small'), 'N'),
])

body = ''.join([
    ctrl('for="r in formatted_data"'),
    p(fn('r.form_code', 'form_code'), 'FormCode'),
    title,
    p('Dear Sirs/ Madams,', 'Body'),
    p('Please kindly approve our request of personnel transfer detailed as follows:', 'Body'),
    info,
    p('', 'Gap'),
    tr,
    p('<text:span text:style-name="Bold">Change of petrol allowance: </text:span>' + fn('r.petrol_allowance', 'petrol_allowance'), 'Body'),
    p(escape('Site commute allowance (reference)'), 'Heading2'),
    ctrl('if="r.matrix_png"'),
    p(img("py3o.image(r.matrix_png, 'png', width='17cm', isb64=True)", '17cm', '4.5cm'), 'Center'),
    ctrl('/if'),
    p(fn('r.matrix_note', 'matrix_note'), 'Note'),
    p(escape('Approval by'), 'Heading2'),
    ctrl('if="r.signature_strip_png"'),
    p(img("py3o.image(r.signature_strip_png, 'png', width='17cm', isb64=True)", '17cm', '2cm'), 'Center'),
    ctrl('/if'),
    ctrl('/for'),
])

auto_styles = ''.join([
    table_styles('Title', [14.2, 2.8]), table_styles('Info', widths_info), table_styles('Transfer', widths_tr),
    '<style:style style:name="N" style:family="table-cell"><style:table-cell-properties style:vertical-align="middle" fo:padding="0.05cm" fo:border="none"/></style:style>',
    '<style:style style:name="C" style:family="table-cell"><style:table-cell-properties style:vertical-align="middle" fo:padding="0.12cm" fo:border="0.5pt solid #000000"/></style:style>',
    '<style:style style:name="CL" style:family="table-cell"><style:table-cell-properties style:vertical-align="middle" fo:padding="0.12cm" fo:border="none"/></style:style>',
    '<style:style style:name="CH" style:family="table-cell"><style:table-cell-properties style:vertical-align="bottom" fo:padding="0.05cm" fo:border="none"/></style:style>',
])
para_styles = ''.join([
    '<style:style style:name="%s" style:family="paragraph" style:parent-style-name="Standard"><style:paragraph-properties %s/><style:text-properties style:font-name="Liberation Serif" %s/></style:style>' % x
    for x in [
        ('Body', 'fo:margin-top="0.1cm" fo:margin-bottom="0.1cm"', 'fo:font-size="11pt"'),
        ('Gap', 'fo:margin-top="0cm" fo:margin-bottom="0cm"', 'fo:font-size="6pt"'),
        ('Label', 'fo:margin-top="0cm" fo:margin-bottom="0cm"', 'fo:font-size="11pt"'),
        ('Value', 'fo:margin-top="0cm" fo:margin-bottom="0cm"', 'fo:font-size="11pt" style:font-name="Liberation Sans"'.replace('style:font-name="Liberation Sans"', '')),
        ('HeadC', 'fo:text-align="center" fo:margin-top="0cm" fo:margin-bottom="0cm"', 'fo:font-size="11pt"'),
        ('Center', 'fo:text-align="center" fo:margin-top="0.05cm" fo:margin-bottom="0.05cm"', 'fo:font-size="11pt"'),
        ('Small', 'fo:text-align="center" fo:margin-top="0cm" fo:margin-bottom="0cm"', 'fo:font-size="8pt"'),
        ('FormCode', 'fo:margin-top="0cm" fo:margin-bottom="0.1cm"', 'fo:font-size="9pt" fo:font-style="italic"'),
        ('Title1', 'fo:text-align="center"', 'fo:font-size="14pt" fo:font-weight="bold"'),
        ('Heading2', 'fo:margin-top="0.35cm" fo:margin-bottom="0.1cm"', 'fo:font-size="11pt" fo:font-weight="bold" fo:font-style="italic"'),
        ('Note', 'fo:margin-top="0.05cm" fo:margin-bottom="0.05cm"', 'fo:font-size="8.5pt" fo:font-style="italic"'),
        ('Ctrl', 'fo:margin-top="0cm" fo:margin-bottom="0cm"', 'fo:font-size="8pt" fo:color="#0000ff"'),
    ]
]) + '<style:style style:name="Bold" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>' \
   + '<style:style style:name="fr1" style:family="graphic"><style:graphic-properties style:vertical-pos="top" style:vertical-rel="baseline" fo:border="none" fo:padding="0cm" style:wrap="none"/></style:style>'

content = ('<?xml version="1.0" encoding="UTF-8"?>'
  '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
  'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
  'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
  'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" office:version="1.4">'
  '<office:font-face-decls><style:font-face style:name="Liberation Serif" svg:font-family="&apos;Liberation Serif&apos;" style:font-family-generic="roman" style:font-pitch="variable"/></office:font-face-decls>'
  '<office:automatic-styles>%s%s</office:automatic-styles><office:body><office:text>%s</office:text></office:body></office:document-content>') % (
    auto_styles, para_styles, body)

with zipfile.ZipFile(ENT) as src, zipfile.ZipFile(OUT, 'w') as dst:
    dst.writestr(zipfile.ZipInfo('mimetype'), 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
    import re
    styles = re.sub(r'<style:footer>.*?</style:footer>', '', src.read('styles.xml').decode(), flags=re.S)
    dst.writestr('styles.xml', styles, compress_type=zipfile.ZIP_DEFLATED)
    meta = re.sub(r'<dc:title>.*?</dc:title>', '<dc:title>Personnel Transfer Request</dc:title>', src.read('meta.xml').decode(), flags=re.S)
    dst.writestr('meta.xml', meta, compress_type=zipfile.ZIP_DEFLATED)
    for name in ('settings.xml', 'manifest.rdf'):
        dst.writestr(name, src.read(name), compress_type=zipfile.ZIP_DEFLATED)
    manifest = src.read('META-INF/manifest.xml').decode().replace(' <manifest:file-entry manifest:full-path="Configurations2/" manifest:media-type="application/vnd.sun.xml.ui.configuration"/>\n', '').replace(
        ' <manifest:file-entry manifest:full-path="Thumbnails/thumbnail.png" manifest:media-type="image/png"/>\n', '')
    dst.writestr('META-INF/manifest.xml', manifest, compress_type=zipfile.ZIP_DEFLATED)
    dst.writestr('content.xml', content, compress_type=zipfile.ZIP_DEFLATED)
print('written', OUT)
