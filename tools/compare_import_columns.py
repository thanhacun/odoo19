#!/usr/bin/env python3
"""Which columns differ between two import runs (same legacy external ids). Usage: compare_import_columns.py dbA dbB table model [sample]"""
import json, subprocess, sys, collections
A, B, table, model = sys.argv[1:5]
def rows(db):
    q = ("select d.name, to_jsonb(t)::text from %s t join ir_model_data d on d.model='%s' and d.res_id=t.id and d.module='legacy12'" % (table, model))
    out = subprocess.run(['docker', 'exec', 'db', 'psql', '-U', 'odoo', '-d', db, '-Atc', q], capture_output=True, text=True, check=True).stdout
    return {l.split('|', 1)[0]: json.loads(l.split('|', 1)[1]) for l in out.splitlines() if '|' in l}
a, b = rows(A), rows(B)
cnt, sample = collections.Counter(), {}
for k in a:
    for c in a[k]:
        if c in ('id', 'create_date', 'write_date', 'create_uid', 'write_uid') or c.endswith('_id') or c.endswith('_ids'):
            continue
        if a[k][c] != b.get(k, {}).get(c):
            cnt[c] += 1; sample.setdefault(c, (k, a[k][c], b.get(k, {}).get(c)))
print(table, len(a), len(b), dict(cnt))
for c, s in sample.items(): print('  ', c, s)
