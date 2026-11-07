# Odoo 12 side of the report comparison: run in the Odoo 12 container: odoo shell -d att18mar < this file (read-only, rolls back). Writes xlsx to ~/odoo12/tmp/parity_reports/.
import time
X = {'overtime':'at_monthly_overtime_report_py3o','estimate_overtime':'at_monthly_estimate_overtime_report_py3o','workingtime':'at_monthly_workingtime_report_py3o','leave':'at_monthly_leave_report_py3o','attendance':'at_monthly_attendance_report_py3o','leave_remain':'at_leave_allocation_remain_py3o','attendance_location':'at_location_report_py3o'}
for key, xid in X.items():
    t0 = time.time()
    try:
        wiz = env['hr.attendance.admin.control.wizard'].create({'at_date': '2025-12-10', 'monthly_report': key})
        datas = wiz.read()[0]
        res, ft = env.ref('kderp_hr_attendance.' + xid).render_py3o([wiz.id], datas)
        open('/home/odoo/project/tmp/parity_reports/o12_%s.%s' % (key, ft), 'wb').write(res)
        print("P12 OK", key, ft, len(res), round(time.time() - t0))
    except Exception as e:
        print("P12 FAIL", key, type(e).__name__, str(e)[:200])
env.cr.rollback()
