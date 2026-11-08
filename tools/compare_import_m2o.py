#!/usr/bin/env python3
"""Compare the many2one columns of two import runs through the legacy external ids (ids differ between databases).
Usage: compare_import_m2o.py dbA dbB table model   (A = reference, usually a subset of B)"""
import subprocess, sys, collections
A, B, table, model = sys.argv[1:5]
def psql(db, q):
    return subprocess.run(['docker', 'exec', 'db', 'psql', '-U', 'odoo', '-d', db, '-Atc', q], capture_output=True, text=True, check=True).stdout
cols = [l.split('|') for l in psql(A, "select f.name, f.relation from ir_model_fields f join ir_model m on m.id=f.model_id where m.model='%s' and f.ttype='many2one' and f.store "
        "and f.name not in ('create_uid','write_uid') and exists (select 1 from information_schema.columns c where c.table_name='%s' and c.column_name=f.name)" % (model, table)).splitlines()]
def expr(name, rel):
    return ("coalesce((select x.name from ir_model_data x where x.module='legacy12' and x.model='%s' and x.res_id=t.\"%s\"), 'id:'||t.\"%s\"::text, '')" % (rel, name, name))
def rows(db):
    sel = ', '.join(expr(n, r) for n, r in cols)
    q = "select d.name, %s from %s t join ir_model_data d on d.model='%s' and d.res_id=t.id and d.module='legacy12'" % (sel.replace(', ', ' || \'|\' || ') if False else "concat_ws('~', " + sel + ")", table, model)
    out = {}
    for l in psql(db, q).splitlines():
        k, v = l.split('|', 1)
        out[k] = v.split('~')
    return out
a, b = rows(A), rows(B)
cnt, sample = collections.Counter(), {}
for k, va in a.items():
    vb = b.get(k)
    for i, (n, _r) in enumerate(cols):
        if vb is None or va[i] != vb[i]:
            cnt[n] += 1; sample.setdefault(n, (k, va[i], vb[i] if vb else None))
print('%s m2o columns=%d rows A=%d B=%d differing: %s' % (table, len(cols), len(a), len(b), dict(cnt)))
for n, s in sample.items():
    print('   ', n, s)
