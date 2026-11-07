# Odoo 19 side: odoo shell -d <db with the imported month> < this file; then tools/compare_reports.py <report keys> (order independent row comparison).
import time
X = {'overtime':'at_monthly_overtime_report_py3o','estimate_overtime':'at_monthly_estimate_overtime_report_py3o','workingtime':'at_monthly_workingtime_report_py3o','leave':'at_monthly_leave_report_py3o','attendance':'at_monthly_attendance_report_py3o','leave_remain':'at_leave_allocation_remain_py3o','attendance_location':'at_location_report_py3o'}
for key, xid in X.items():
    t0 = time.time()
    try:
        wiz = env['hr.attendance.admin.control.wizard'].create({'at_date': '2025-12-10', 'monthly_report': key})
        datas = wiz.read()[0]
        res, ft = env['ir.actions.report']._render('kdvn_hr_attendance.' + xid, wiz.ids, data=datas)
        open('/home/odoo/project/temp/parity_reports/o19_%s.%s' % (key, ft), 'wb').write(res)
        print("P19 OK", key, ft, len(res), round(time.time() - t0))
    except Exception as e:
        print("P19 FAIL", key, type(e).__name__, str(e)[:200])
env.cr.rollback()
