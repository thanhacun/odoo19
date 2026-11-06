#!/usr/bin/env python3
"""Odoo 12 view XML -> Odoo 19 syntax (mechanical part of the KDERP port).

  tools/port_view.py <src.xml> <dst.xml> [--module-rename kderp_hr_attendance=kdvn_hr_attendance ...]

Converts: <tree> -> <list>; attrs="{'invisible': domain, ...}" -> invisible="python expr" (readonly, required, column_invisible);
states="a,b" -> invisible="state not in ('a','b')"; a bare invisible="1" on a column of a <list> -> column_invisible="1";
view_type / tree view modes in actions; <group ...> attributes inside <search>; oe_chatter div -> <chatter/>; groups_id -> group_ids.
Does NOT touch inherit views of core records (xpath targets changed in Odoo 19): those are written by hand, the tool only reports them.
"""
import ast
import re
import sys

from lxml import etree

MODULE = 'kdvn_hr_attendance'
# views that cannot be converted mechanically (Odoo 12 kanban-box / t-raw QWeb, legacy JS widgets): dropped and listed, rewritten by hand later
DROP = {'view_hr_attendance_kanban'}
OPS = {'=': '==', '!=': '!=', '<': '<', '>': '>', '<=': '<=', '>=': '>='}


def leaf(field, op, value):
    if op in ('=', '==') or op == '!=':
        neg = op == '!='
        if value is False or value is None:
            return field if neg else 'not %s' % field
        if value is True:
            return 'not %s' % field if neg else field
        return '%s %s %r' % (field, '!=' if neg else '==', value)
    if op in ('in', 'not in'):
        vals = list(value) if isinstance(value, (list, tuple)) else [value]
        if vals in ([False], [None]):
            return field if op == 'not in' else 'not %s' % field
        if set(vals) == {False, 0} or set(vals) == {False, 0, None}:
            return field if op == 'not in' else 'not %s' % field
        return '%s %s %r' % (field, op, vals)
    if op in OPS:
        return '%s %s %r' % (field, OPS[op], value)
    raise ValueError('operator %s' % op)


def domain_to_expr(domain):
    """Polish-notation Odoo domain -> python expression string."""
    items = list(domain)

    def parse(pos):
        tok = items[pos]
        if tok in ('&', '|'):
            left, pos = parse(pos + 1)
            right, pos = parse(pos)
            word = 'and' if tok == '&' else 'or'
            return '(%s %s %s)' % (left, word, right), pos
        if tok == '!':
            inner, pos = parse(pos + 1)
            return 'not (%s)' % inner, pos
        if isinstance(tok, (list, tuple)):
            return leaf(*tok), pos + 1
        if tok in (1, True):
            return 'True', pos + 1
        raise ValueError('bad token %r' % (tok,))

    parts, pos = [], 0
    while pos < len(items):
        expr, pos = parse(pos)
        parts.append(expr)
    if not parts:
        return ''
    out = ' and '.join(parts) if len(parts) > 1 else parts[0]
    return out[1:-1] if out.startswith('(') and out.endswith(')') and out.count('(') == 1 else out


def convert_attrs(text):
    """attrs string -> {attribute: expression}; domains using `uid`/context stay as python (uid is allowed)."""
    data = ast.literal_eval(text.strip())
    res = {}
    for key, dom in data.items():
        if key not in ('invisible', 'readonly', 'required', 'column_invisible'):
            continue   # e.g. {'format': 'HH:mm'} had no effect in Odoo 12
        if isinstance(dom, bool):
            res[key] = '1' if dom else '0'
        elif isinstance(dom, (int,)):
            res[key] = '1' if dom else '0'
        else:
            res[key] = domain_to_expr(dom)
    return res


def convert(tree, report):
    root = tree.getroot()
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        # tree -> list
        if el.tag == 'tree':
            el.tag = 'list'
        if el.tag == 'xpath' and el.get('expr'):
            el.set('expr', re.sub(r'\btree\b', 'list', el.get('expr')))
        # <attribute name="attrs">{...}</attribute> inside xpath/field position="attributes"
        if el.tag == 'attribute' and el.get('name') == 'attrs':
            try:
                new = convert_attrs(el.text or '{}')
            except Exception as err:
                report.append('attribute attrs not converted (%s): %s' % (err, (el.text or '')[:80]))
                new = {}
            parent = el.getparent()
            idx = parent.index(el)
            for k, (key, expr) in enumerate(new.items()):
                n = etree.Element('attribute', name=key)
                n.text = expr
                n.tail = el.tail
                parent.insert(idx + 1 + k, n)
            parent.remove(el)
            continue
        if el.tag == 'attribute' and el.get('name') == 'states':
            states = [x.strip() for x in (el.text or '').split(',') if x.strip()]
            el.set('name', 'invisible')
            el.text = "state not in (%s)" % ', '.join(repr(x) for x in states)
            continue
        # attrs
        if el.get('attrs'):
            try:
                new = convert_attrs(el.get('attrs'))
            except Exception as err:
                report.append('attrs not converted (%s): %s' % (err, el.get('attrs')[:90]))
                continue
            del el.attrib['attrs']
            in_list = el.getparent() is not None and el.getparent().tag == 'list'
            for key, expr in new.items():
                if key == 'invisible' and el.get('invisible') and el.get('invisible') != '1':
                    expr = '(%s) or (%s)' % (el.get('invisible'), expr)
                el.set(key, expr)
        # Odoo 12 colour option of a list cell: options='{"fg_color": "red:expr"}' -> decoration-danger="expr"
        if el.tag == 'field' and el.get('options') and 'fg_color' in el.get('options'):
            try:
                opts = ast.literal_eval(el.get('options'))
                color, _, expr = opts.pop('fg_color').partition(':')
                el.set({'red': 'decoration-danger', 'orange': 'decoration-warning', 'green': 'decoration-success', 'blue': 'decoration-info'}.get(color, 'decoration-danger'), expr)
                if opts:
                    el.set('options', repr(opts))
                else:
                    del el.attrib['options']
            except Exception as err:
                report.append('fg_color not converted (%s)' % err)
        # states="a,b"
        if el.get('states') and el.tag in ('button', 'field', 'group', 'page', 'div'):
            states = [s.strip() for s in el.get('states').split(',') if s.strip()]
            cond = 'state not in %r' % (states,) if len(states) > 1 else "state != '%s'" % states[0]
            cond = cond.replace('[', '(').replace(']', ')') if len(states) > 1 else cond
            prev = el.get('invisible')
            el.set('invisible', '(%s) or (%s)' % (prev, cond) if prev and prev != '1' else cond)
            del el.attrib['states']
        # bare column invisible
        if el.tag == 'field' and el.getparent() is not None and el.getparent().tag == 'list' and el.get('invisible') in ('1', 'True', 'true'):
            del el.attrib['invisible']
            el.set('column_invisible', '1')
        # search: group attributes are not allowed
        if el.tag == 'group' and el.getparent() is not None and el.getparent().tag == 'search':
            for a in list(el.attrib):
                del el.attrib[a]
        # chatter
        if el.tag == 'div' and 'oe_chatter' in (el.get('class') or ''):
            el.clear()
            el.tag = 'chatter'
    for tpl in list(root.iter('template')):
        if (tpl.get('inherit_id') or '').startswith('web.assets'):
            tpl.getparent().remove(tpl)
            report.append('dropped asset template %s (Odoo 12 JS is not ported)' % tpl.get('id'))
    # actions
    for rec in root.iter('record'):
        if rec.get('model') == 'ir.ui.view':
            for f in list(rec.findall('field')):
                if f.get('name') == 'type':
                    rec.remove(f)
        if rec.get('model') == 'ir.actions.act_window.view':
            for f in rec.findall('field'):
                if f.get('name') == 'view_mode' and (f.text or '').strip() == 'tree':
                    f.text = 'list'
        if rec.get('model') == 'ir.actions.act_window':
            for f in list(rec.findall('field')):
                if f.get('name') == 'view_type':
                    rec.remove(f)
                if f.get('name') == 'view_mode' and f.text:
                    f.text = ','.join('list' if m.strip() == 'tree' else m.strip() for m in f.text.split(',') if m.strip() != 'kanban')   # Odoo 12 kanban-box views are not ported
        for f in rec.findall('field'):
            if f.get('name') == 'groups_id' and rec.get('model') in ('ir.ui.menu', 'ir.actions.act_window', 'ir.actions.server', 'ir.actions.report', 'ir.actions.client'):
                f.set('name', 'group_ids')
            if f.get('name') == 'inherit_id':
                report.append('INHERITS %s (record %s): check the xpath against Odoo 19' % (f.get('ref'), rec.get('id')))
    return tree


def model_xmlid(model):
    """xml id of the ir.model record: core hr_attendance / hr_holidays models keep their module, ours are in the target module."""
    core = {'hr.attendance': 'hr_attendance', 'hr.leave': 'hr_holidays', 'hr.leave.type': 'hr_holidays', 'hr.leave.allocation': 'hr_holidays',
            'hr.employee': 'hr', 'hr.department': 'hr', 'res.users': 'base'}
    module = core.get(model, 'MODULE')
    return '%s.model_%s' % (module, model.replace('.', '_'))


def shortcut_tags(root, report, module):
    """<act_window> and <report> data shortcuts do not exist in Odoo 19: replace them by full records."""
    for el in list(root.iter('act_window', 'report')):
        parent = el.getparent()
        rec = etree.Element('record', id=el.get('id'))
        def add(name, text=None, ref=None, evalx=None):
            f = etree.SubElement(rec, 'field', name=name)
            if ref: f.set('ref', ref)
            if evalx: f.set('eval', evalx)
            if text is not None: f.text = text
        if el.tag == 'act_window':
            rec.set('model', 'ir.actions.act_window')
            add('name', el.get('name'))
            add('res_model', el.get('res_model'))
            if el.get('view_mode'):
                add('view_mode', ','.join('list' if m.strip() == 'tree' else m.strip() for m in el.get('view_mode').split(',')))
            for key in ('target', 'domain', 'context', 'limit', 'view_id'):
                if el.get(key):
                    if key == 'view_id':
                        add('view_id', ref=el.get(key))
                    else:
                        add(key, el.get(key))
            if el.get('src_model'):
                add('binding_model_id', ref=model_xmlid(el.get('src_model')).replace('MODULE', module))
            if el.get('groups'):
                add('group_ids', evalx='[(6, 0, [%s])]' % ', '.join("ref('%s')" % g.strip() for g in el.get('groups').split(',')))
        else:
            rec.set('model', 'ir.actions.report')
            add('name', el.get('string') or el.get('name'))
            add('model', el.get('model'))
            add('report_type', el.get('report_type', 'qweb-pdf'))
            add('report_name', el.get('name'))
            add('report_file', el.get('file') or el.get('name'))
            for key, field in (('print_report_name', 'print_report_name'),):
                if el.get(key):
                    add(field, el.get(key))
            if el.get('paperformat'):
                add('paperformat_id', ref=el.get('paperformat'))
            add('binding_model_id', ref=model_xmlid(el.get('model')).replace('MODULE', module))
            add('binding_type', 'report')
            report.append('report %s converted: check the QWeb template %s (Odoo 12 qweb)' % (el.get('id'), el.get('name')))
        rec.tail = el.tail
        parent.replace(el, rec)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    renames = dict(a.split('=') for a in sys.argv[3:] if '=' in a)
    parser = etree.XMLParser(remove_blank_text=False, remove_comments=False)
    tree = etree.parse(src, parser)
    report = []
    for rec in list(tree.getroot().iter('record')):
        arch_text = etree.tostring(rec, encoding='unicode')
        if rec.get('model') == 'ir.ui.view' and ('kanban-box' in arch_text or 't-raw' in arch_text) and '<kanban' in arch_text and rec.find("field[@name='inherit_id']") is None:
            DROP.add(rec.get('id'))
        if rec.get('id') in DROP:
            rec.getparent().remove(rec)
            report.append('DROPPED view %s: rewrite by hand' % rec.get('id'))
    shortcut_tags(tree.getroot(), report, MODULE)
    convert(tree, report)
    renamed = {}
    for rec in list(tree.getroot().iter('record')):
        rid = rec.get('id') or ''
        if rid.split('.')[0] in ('hr_attendance', 'hr_holidays', 'hr') and '.' in rid and rec.get('model') in ('ir.actions.act_window', 'ir.actions.server', 'ir.actions.report'):
            short = rid.split('.', 1)[1]
            renamed[rid] = short
            if rec.get('model') == 'ir.actions.act_window' and rec.find("field[@name='res_model']") is None:
                f = etree.Element('field', name='res_model')
                f.text = 'hr.attendance'
                f.tail = '\n        '
                rec.insert(0, f)
                if rec.find("field[@name='name']") is None:
                    n = etree.Element('field', name='name')
                    n.text = short.replace('_', ' ').title()
                    n.tail = '\n        '
                    rec.insert(0, n)
    text = etree.tostring(tree, encoding='unicode')
    for rid, short in renamed.items():
        text = text.replace('id="%s"' % rid, 'id="%s"' % short).replace('"%s"' % rid, '"%s"' % short).replace("'%s'" % rid, "'%s'" % short)
        report.append('core record %s is now ours: %s' % (rid, short))
    for old, new in renames.items():
        text = text.replace(old, new)
    text = text.replace('name="gender"', 'name="sex"')   # hr.employee.gender is `sex` in Odoo 19
    text = '<?xml version="1.0" encoding="utf-8"?>\n' + text
    open(dst, 'w').write(text)
    for line in report:
        print('  ! ' + line)


if __name__ == '__main__':
    main()
