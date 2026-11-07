#!/usr/bin/env python3
"""Compare Odoo 12 views with our Odoo 19 views of the same xml id: fields and buttons that exist in Odoo 12 but not in 19 (dropped by the port).
    python3 tools/compare_views_12_19.py <odoo12_views_dir> <odoo19_views_dir>
Fields inside XML comments are ignored. A field may legitimately be gone (e.g. replaced by a core 19 field): read the list, do not trust it blindly."""
import glob
import os
import sys
from lxml import etree


def records(dirname):
    out = {}
    for path in sorted(glob.glob(os.path.join(dirname, '*.xml'))):
        root = etree.parse(path).getroot()
        for rec in root.iter('record'):
            if rec.get('model') == 'ir.ui.view' and rec.get('id'):
                arch = rec.find("field[@name='arch']")
                if arch is None:
                    continue
                fields, buttons = set(), set()
                for el in arch.iter():
                    if not isinstance(el.tag, str):
                        continue
                    if el.tag == 'field' and el.get('name'):
                        fields.add(el.get('name'))
                    if el.tag == 'button' and el.get('name'):
                        buttons.add(el.get('name'))
                model = rec.find("field[@name='model']")
                out[rec.get('id')] = (os.path.basename(path), model.text if model is not None else '', fields, buttons)
    return out


old, new = records(sys.argv[1]), records(sys.argv[2])
missing_views, rows = [], []
for rid, (path, model, fields, buttons) in sorted(old.items()):
    if rid not in new:
        missing_views.append((rid, model, path))
        continue
    nf, nb = new[rid][2], new[rid][3]
    lost_f, lost_b = sorted(fields - nf), sorted(buttons - nb)
    if lost_f or lost_b:
        rows.append((rid, model, lost_f, lost_b))
print('views in Odoo 12: %d, same id in Odoo 19: %d, not found in 19: %d' % (len(old), len(old) - len(missing_views), len(missing_views)))
print('\n== views with fields/buttons lost (%d)' % len(rows))
for rid, model, lost_f, lost_b in rows:
    print('%s (%s)' % (rid, model))
    if lost_f:
        print('    fields : ' + ', '.join(lost_f))
    if lost_b:
        print('    buttons: ' + ', '.join(lost_b))
print('\n== Odoo 12 views with no view of the same id in 19 (%d)' % len(missing_views))
for rid, model, path in missing_views:
    print('%-55s %-30s %s' % (rid, model, path))
