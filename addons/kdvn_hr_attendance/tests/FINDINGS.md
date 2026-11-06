# Findings from the attendance tests (for review)

Written 1 Nov 2026. Status: **open** = needs a decision, **fixed** = already changed, **doc** = documented only.
Test ids refer to `tests/cases/*.csv` and `tests/test_*.py`. Nothing here was changed in behaviour unless marked fixed.

| # | Area | Finding | Test | Status |
|---|------|---------|------|--------|
| 1 | Annual leave (LV-01) | `employee_annual_leave` (`hr_leave.py` ~2235, commit 848e8005) sets 17 days inside the loop before the year check: every staff with 10+ years gets 17 (+bonus), not only 25+. Production allocations (Dec 2025) are 16; the 21 Dec 2026 run would give 17. Fix: 17 only when service >= 25 years. | LV-01 (14 years) GAP | fixed 1 Nov 2026 (17 from 25 completed years) |
| 2 | OT on AH day (OT-09-02) | Last-two-Saturday AH day worked WITHOUT an OT Holidays Plan line is not refused: 8 h is paid as weekday OT, only a server-log error. A last Saturday that is not an AH day is refused (OT-08-01). | test_ot_ah | closed 1 Nov 2026: intended (not registered = weekday OT) |
| 3 | Holiday OT start (OT-04-10) | On holidays OT starts at the actual check-in even when the registered start is later (rule RW-04 says the later one). | OT-04-10 GAP | open |
| 4 | AH month (AH-07/AH-08) | With a half-day Saturday the month ends with 1.5 AH instead of 2. | AH-07, AH-08 GAP | open (HR) |
| 5 | Child care (OT-07-03/04) | +60 min is added to OT even when the staff came 60 min late. | OT-07-03/04 | leave as is (Thanh 1 Nov 2026) |
| 6 | out_by_reg (OT-05-02) | Registered end is paid even if the staff left earlier. | OT-05-02 | leave as is (Thanh 1 Nov 2026) |
| 7 | Summary index/view id | `(employee_id*1000000 + at_year*100 + at_month)::integer` overflows above employee id 2147: any hr_attendance write fails. Real max id 1049 (prod copy 1083). | test_settings | fixed 1 Nov 2026: id = employee*10000 + months since Jan 2000 (fits to employee id 214,748); migration 12.0.1.0.2 rewrites hr_attendance.summary_id |
| 8 | WT request timing | A working-time request changes status/compute times only after the manager approved (waiting_fhr+), not in draft or waiting_fman. Rules file corrected (RQ-01a). | WS-01, WS-10 | doc |
| 9 | OT on holidays | Needs a done OT Holidays Plan line; the plan creates the OT request. | OT-04, OT-08 | doc |
| 10 | RQ-05(a) | WT cutoff compared with `ot_before`; now `wt_before`. | - | fixed (058fc7d1) |
| 11 | RQ-05(b) | Cutoff uses the stored UTC hour instead of Vietnam time (also `hr_leave.py:805`). Found 1 Nov: OT/WT path converts with astimezone on a naive value (depends on server TZ), leave path uses UTC: see RQ-05 in the rules file. | test_settings | fixed 1 Nov 2026 (one helper, D+1 10:00; migration 12.0.1.0.3) |
| 12 | Raw checks | Test staff need `joining_date`, otherwise the sync creates no attendance for days before today. Test setup only. | test_raw_checks | doc |
