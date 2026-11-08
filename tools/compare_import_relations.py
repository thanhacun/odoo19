#!/usr/bin/env python3
"""Compare many2many side tables of two import runs through the legacy external ids. A = reference (usually a subset of B).
Usage: compare_import_relations.py dbA dbB   (the side tables of attendance, requests, leave covers: viewer lists, status marks, cover links)"""
import subprocess, sys
A, B = sys.argv[1:3]
RELS = [('hr_attendance_res_users_rel', 'hr_attendance_id', 'hr.attendance', 'res_users_id', 'res.users'),
        ('hr_attendance_request_res_users_rel', 'hr_attendance_request_id', 'hr.attendance.request', 'res_users_id', 'res.users'),
        ('hr_leave_cover_res_users_rel', 'hr_leave_cover_id', 'hr.leave.cover', 'res_users_id', 'res.users'),
        ('hr_attendance_kderp_base_code_rel', 'hr_attendance_id', 'hr.attendance', 'kderp_base_code_id', 'kderp.base.code'),
        ('hr_attendance_hr_leave_cover_rel', 'hr_attendance_id', 'hr.attendance', 'hr_leave_cover_id', 'hr.leave.cover')]
def psql(db, q):
    return subprocess.run(['docker', 'exec', 'db', 'psql', '-U', 'odoo', '-d', db, '-Atc', q], capture_output=True, text=True, check=True).stdout.splitlines()
for rel, ca, ma, cb, mb in RELS:
    if mb == 'kderp.base.code':   # the status codes are records of the module itself (same ids in both databases)
        q = ("select d1.name, r.%s::text from %s r join ir_model_data d1 on d1.module='legacy12' and d1.model='%s' and d1.res_id=r.%s" % (cb, rel, ma, ca))
    else:
        q = ("select d1.name, d2.name from %s r join ir_model_data d1 on d1.module='legacy12' and d1.model='%s' and d1.res_id=r.%s "
             "join ir_model_data d2 on d2.module='legacy12' and d2.model='%s' and d2.res_id=r.%s" % (rel, ma, ca, mb, cb))
    a, b = set(psql(A, q)), set(psql(B, q))
    owners = {l.split('|')[0] for l in a}
    b_sub = {l for l in b if l.split('|')[0] in owners}
    print('%-38s A=%d  B(same records)=%d  only in A=%d  only in B=%d' % (rel, len(a), len(b_sub), len(a - b_sub), len(b_sub - a)))
