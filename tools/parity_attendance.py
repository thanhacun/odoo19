# Parity check: recompute imported attendance days in Odoo 19 and compare with the stored Odoo 12 values (rolled back, nothing changes).
# Run: odoo shell -d <db> < tools/parity_attendance.py   after editing __FROM__ / __TO__ (dates of the import window). Writes parity.json in the worktree.
import json, collections
F = ['status_codes','absence','absence_count','ot_total','ot_wd','ot_hd','ph_ot','wd_ot','ot_am','ot_pm','wd_st','hd_st','ph_st','late_in','early_out']
env.cr.execute("""select a.id from hr_attendance a join ir_model_data d on d.model='hr.attendance' and d.res_id=a.id and d.module='legacy12'
   where a.at_date between '__FROM__' and '__TO__' order by a.id""")
ids = [r[0] for r in env.cr.fetchall()]
ats = env['hr.attendance'].sudo().with_context(active_test=False).browse(ids)
def snap(recs):
    out = {}
    for a in recs:
        out[a.id] = {f: (round(a[f],3) if isinstance(a[f], float) else a[f]) for f in F}
        out[a.id]['emp'] = a.employee_id.code; out[a.id]['date'] = str(a.at_date)
    return out
before = snap(ats)
try:
    with env.cr.savepoint():
        ats._compute_at_status(force_run=True)
        ats.flush_recordset(); ats.invalidate_recordset()
        after = snap(ats)
        diffs = []
        for i in ids:
            d = {f: (before[i][f], after[i][f]) for f in F if before[i][f] != after[i][f]}
            if d: diffs.append((before[i]['emp'], before[i]['date'], d))
        cnt = collections.Counter(k for _,_,d in diffs for k in d)
        json.dump({'n': len(ids), 'ndiff': len(diffs), 'cnt': cnt, 'diffs': diffs}, open('/home/odoo/project/.worktrees/attendance/parity.json','w'), default=str)
        raise Exception("rollback")
except Exception as e:
    print("END", e)
