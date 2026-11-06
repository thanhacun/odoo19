#!/usr/bin/env python3
"""kdvn_hr_attendance: the Odoo 12 module changed core hr_attendance views with xpath inheritance. Odoo 19 core views are different,
so the four hr.attendance views become standalone (primary) views built from the same pieces. Run once on views/hr_attendance_view.xml
after tools/port_view.py. Idempotent."""
import copy
import sys

from lxml import etree

path = sys.argv[1]
tree = etree.parse(path, etree.XMLParser(remove_blank_text=False))
root = tree.getroot()


def record(rid):
    for rec in root.iter('record'):
        if rec.get('id') == rid:
            return rec


def arch_of(rec):
    for f in rec.findall('field'):
        if f.get('name') == 'arch':
            return f


def drop_inherit(rec):
    for f in rec.findall('field'):
        if f.get('name') == 'inherit_id':
            rec.remove(f)


def new_arch(rec, element):
    arch = arch_of(rec)
    for child in list(arch):
        arch.remove(child)
    arch.text = '\n            '
    arch.append(element)
    element.tail = '\n        '


# ---- list
rec = record('view_attendance_tree')
if rec is not None and rec.find("field[@name='inherit_id']") is not None:
    arch = arch_of(rec)
    attrs, cols_before, cols_after = {}, [], []
    for node in arch:
        if not isinstance(node.tag, str):
            continue
        if node.tag == 'xpath' and node.get('position') == 'attributes':
            for a in node.findall('attribute'):
                attrs[a.get('name')] = a.text
        elif node.tag == 'list' and node.get('position') == 'attributes':
            for a in node.findall('attribute'):
                attrs[a.get('name')] = a.text
        elif node.tag == 'field' and node.get('name') == 'employee_id' and node.get('position') == 'replace':
            cols_before = [copy.deepcopy(c) for c in node]
        elif node.tag == 'field' and node.get('name') == 'check_out' and node.get('position') == 'after':
            cols_after = [copy.deepcopy(c) for c in node]
    lst = etree.Element('list', string='Attendances')
    for k, v in attrs.items():
        lst.set(k, v)
    for c in cols_before:
        lst.append(c)
    for name in ('check_in', 'check_out'):
        etree.SubElement(lst, 'field', name=name, column_invisible='1')
    for c in cols_after:
        lst.append(c)
    drop_inherit(rec)
    new_arch(rec, lst)

# ---- form
rec = record('hr_attendance_view_form')
if rec is not None and rec.find("field[@name='inherit_id']") is not None:
    arch = arch_of(rec)
    attrs, header, sheet = {}, None, None
    for node in arch:
        if not isinstance(node.tag, str):
            continue
        if node.tag == 'xpath' and node.get('position') == 'attributes':
            for a in node.findall('attribute'):
                attrs[a.get('name')] = a.text
        elif node.tag == 'sheet' and node.get('position') == 'before':
            header = copy.deepcopy(node.find('header'))
        elif node.tag == 'sheet' and node.get('position') == 'replace':
            sheet = copy.deepcopy(node.find('sheet'))
    form = etree.Element('form', string='Attendance')
    for k, v in attrs.items():
        form.set(k, v)
    if header is not None:
        form.append(header)
    if sheet is not None:
        form.append(sheet)
    drop_inherit(rec)
    new_arch(rec, form)

# ---- search
rec = record('hr_attendance_view_filter')
if rec is not None and rec.find("field[@name='inherit_id']") is not None:
    arch = arch_of(rec)
    fields_, filters_, groups_ = [], [], []
    for node in arch:
        if not isinstance(node.tag, str):
            continue
        pos, tag, name = node.get('position'), node.tag, node.get('name')
        if tag == 'field' and pos == 'after' and name == 'department_id':
            fields_ = [copy.deepcopy(c) for c in node]
        elif tag == 'filter' and name == 'myattendances' and pos == 'before':
            filters_ += [copy.deepcopy(c) for c in node if isinstance(c.tag, str)]
        elif tag == 'filter' and name == 'employee' and pos == 'before':
            groups_ = [copy.deepcopy(c) for c in node if isinstance(c.tag, str)] + groups_
        elif tag == 'filter' and name == 'groupby_check_out' and pos == 'replace':
            groups_ += [copy.deepcopy(c) for c in node if isinstance(c.tag, str)]
        elif tag == 'filter' and name == 'nocheckout' and pos == 'replace':
            filters_ += [copy.deepcopy(c) for c in node]
    search = etree.Element('search', string='Attendance Search')
    etree.SubElement(search, 'field', name='employee_id')
    etree.SubElement(search, 'field', name='department_id', operator='child_of')
    for c in fields_:
        search.append(c)
    etree.SubElement(search, 'filter', string='My Attendances', name='myattendances', domain="[('employee_id.user_id', '=', uid)]")
    for c in filters_:
        search.append(c)
    group = etree.SubElement(search, 'group')
    etree.SubElement(group, 'filter', string='Employee', name='employee', context="{'group_by': 'employee_id'}")
    for c in groups_:
        group.append(c)
    drop_inherit(rec)
    new_arch(rec, search)

# ---- pivot (the inherit replaced the whole pivot)
rec = record('hr_attendance_overtime_pivot')
if rec is not None and rec.find("field[@name='inherit_id']") is not None:
    arch = arch_of(rec)
    pivot = copy.deepcopy(arch.find('pivot').find('pivot'))
    drop_inherit(rec)
    new_arch(rec, pivot)

text = etree.tostring(tree, encoding='unicode')
open(path, 'w').write('<?xml version="1.0" encoding="utf-8"?>\n' + text)
