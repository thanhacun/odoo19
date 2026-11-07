# Porting KDERP (Odoo 12) to Odoo 19

Status file for the port. Odoo 12 code is reference only (~/odoo12/addons, never changed from here). Update this file at the end of every module.
Odoo 19 core addons for checks live in the container: `docker exec odoo19 ls /usr/lib/python3/dist-packages/odoo/addons` (~/odoo19-src has no addons folder).

## Decisions (Thanh, 6 Nov 2026)
- Test data: a re-runnable import in Odoo 19 reads the Odoo 12 dev DB (`att18mar`, container `kdvn.odoo12.db.dev`) read-only with SQL and writes through the ORM.
  Every imported record is tagged with its Odoo 12 id (external id `legacy12.<table>_<id>`), so a second run updates instead of duplicating; limit by date range / employees. The same tool becomes the go-live data migration.
- Real names and details are copied (dev only); an anonymise switch can be added later.
- Order: foundation -> attendance (in stages) -> e-approval and its procedures.
- Naming: module `kderp_x` becomes `kdvn_x`; model technical names and config parameter keys stay `kderp.*` / `kderp_remote.*` (as already done in kdvn_remote_sync), so data and later Odoo 12 changes map 1:1.

## Dependencies on Odoo 19 (checked 6 Nov 2026)
| Odoo 12 dependency | Odoo 19 |
|---|---|
| hr, hr_attendance, hr_org_chart, mail, bus | core (hr_holidays and hr_holidays_attendance too) |
| base_tier_validation (+ _formula, _forward, ...) | OCA `tier-validation` 19.0, copied to extra-addons (git-ignored) |
| web_notify, web_widget_numeric_step, web_ir_actions_act_window_message, queue_job, queue_job_batch, report_py3o, document_page(_approval), web_m2x_options, web_responsive, web_dialog_size | OCA 19.0 exists |
| hr_holidays_public | NO 19.0 branch, no open PR. Our own `hr.holidays.public` models are already inside kderp_hr_attendance: port them into our module, drop the OCA dependency |
| web_widget_timepicker | NO 19.0. Use native time/float_time widgets, or a small widget of ours |
| kderp_base, kderp_web, kderp_web_theme (Odoo 12 web client) | Odoo 12 JS/QWeb does not port; only the data helpers we really use |

## Modules, simple to complicated
| Step | Odoo 12 module (py lines) | Odoo 19 module | State |
|---|---|---|---|
| 1a | kderp_remote_integration (307) | kdvn_remote_integration 19.0.1.0.0: DONE 6 Nov, 18 tests pass on kdvn_test, install clean. Settings page = Settings > Remote Server Connection (app block). Not yet tried against the real remote: fill the page on odoo19_dev and press Test. |
| 1b | kderp_remote_sync 12.0.1.5.0 direct pull | kdvn_remote_sync 19.0.1.3.0: direct pull added (crons inactive) next to the n8n push, `purge=False` on the pipeline; DONE 6 Nov, 19 tests pass (11 old + 8 new). Not yet tried against the real remote. | done |
| 2a | kderp_hr (286) | kdvn_hr 19.0.1.0.0: staff code, working flag, location history, dept code/type/2nd manager. DONE 6 Nov, 8 tests pass on kdvn_test. Skipped: kderp_base mixins, OE7 image migration, translated name (see its CLAUDE.md). | done |
| 2b | kderp_hr_ext (1014) | kdvn_hr_ext 19.0.1.0.0: department / manager / project history, admin section, manager-user chains, org-chart data. DONE 6 Nov, 19 tests pass (27 with kdvn_hr). GM group and attendance hook are optional until attendance is ported; org-chart screen, queue_job and kanban/action tweaks not ported (see its CLAUDE.md). Cron shipped inactive. | done |
| 3 | import tool | kdvn_legacy_import 19.0.1.0.0: DONE 6 Nov, 12 tests (fake snapshot). Real run on a scratch DB from `legacy12` (copy of att18mar, `tools/legacy12_snapshot.sh`): 444 employees, 431 users, 100 departments, 1862 locations, 951 department history lines, 145 manager history; manager / department / working compared with Odoo 12: 0 differences; 2nd run 30 s, no errors. Attendance and requests are later steps of kdvn_hr_attendance. Legacy groups not mapped yet are listed in the log (attendance, procedures). | done |
| 4 | kderp_hr_attendance (16763) | kdvn_hr_attendance, in stages: A records, machines, locations, rules; B time off, allocations, public holidays; C requests (working time, overtime, leave) with approval; D summaries and reports; E face-machine feed (not needed in dev, raw data comes from the import) | todo |
| 5 | kderp_e_approval (2872) | kdvn_e_approval on OCA base_tier_validation 19.0 (mixin, refusal log, special rules, settings) | todo |
| 6 | kderp_entertainment_procedures (1339), kderp_hr_procedures (1851), kderp_procurement_procedures (2033) | kdvn_* | todo |
| 7 | kderp_dashboard (559), kderp_knowledge (815) | kdvn_dashboard, kdvn_knowledge (guides) | todo |

For each module: read the Odoo 12 module's CLAUDE.md / readme first, port models, then views (Odoo 17+ syntax: `<list>`, `invisible=` expressions, no `attrs`), security, then tests; run
`docker exec odoo19 odoo -c /etc/odoo/odoo.conf -d kdvn_test -u <module> --test-tags /<module> --stop-after-init --http-port=8079 --gevent-port=8082`.


## Step 4: kdvn_hr_attendance (read 7 Nov 2026)
Source: ~/odoo12/addons/kderp_hr_attendance (15.7k py lines; read its CLAUDE.md and attendance_rules.md first: rule ids TM-, RW-, ST-, AH-, OT-, AL-, RQ-, LV-).
**Payroll depends on the results (status marks, OT hours, allowance, leave days, allocations): the computation code is ported literally, only the Odoo API is adapted. Nothing is "improved" while porting.**
Proof of equality (the real test): the Odoo 12 module has `scripts/at_baseline.py` (+ compare). When stages A-C are in, the same period and the same employees are computed in Odoo 12 and in Odoo 19 (data from kdvn_legacy_import) and the results compared; every difference is explained before the stage is called done. Unit tests per rule id come first.

Decisions:
- `hr.attendance` stays `_inherit = 'hr.attendance'` (same table/model name). Odoo 19 core also has its own overtime engine (`hr.attendance.overtime.line`, `overtime_hours`...): ours does not use it; core constraints that clash with one-record-per-employee-per-day are overridden where needed (noted below).
- Public holidays: Odoo 19 has no hr_holidays_public. Our module defines the two OCA models itself (`hr.holidays.public`, `hr.holidays.public.line`: year, country, lines, variable date, states) plus our additions (company day, substitute, calendar, memo).
- Optional python libs: `lunarcalendar` and `pyodbc` are NOT in the Odoo 19 image. `to_lunar` imports lazily; the SQL Server (bizone) link is stage E.
- Attendance approvals stay on the attendance state machine (not tier validation), as in Odoo 12.
- Groups: our groups live in kdvn_hr_attendance with the same names; Odoo 12 changed core group records (`hr_attendance.group_hr_attendance_user` name/implied); in Odoo 19 we add implied ids instead of renaming core records.

Stages (each: port, unit tests from the rule doc, commit, update this table):
| Stage | Content | State |
|---|---|---|
| A1 | DONE 7 Nov (19.0.0.1.0, 32 tests; deviations D1-D4 in the module CLAUDE.md): module, company policy (`res.company` fields, `at_policy`), groups, `hr.attendance.rule` (+ `_at_rules`, merge by sequence, memo), public holidays (own models), `hr.mixin` time helpers (AT month/year, AT day start, early offset, holidays, Saturday rules), `is_no_sat_working`, `_is_holiday` | done |
| A0 | `kdvn_base` 19.0.1.0.0 DONE 7 Nov (5 tests): subset of kderp_base the attendance port needs: `kderp.base.model` (code/name), `kderp.base.code`, `kderp.base.state`, `kderp.base.state.model`. Not ported: Odoo 12 view-editing hacks, code suggestion, QR. `color` is an Integer (Odoo 19 selections need str keys). | done |
| A2/A3 | DONE as a literal port, 7 Nov (19.0.0.1.0): all models of kderp_hr_attendance load in Odoo 19 (attendance, raw, raw status, locations, requests, summary SQL views, refuse, OT holiday plan, wizards); states + status codes + inactive crons; views converted with `tools/port_view.py`. **Parity proof so far (Odoo 12 HR case sheets, `tests/cases/*.csv`):** status sheet: every non-leave case passes (38 of 54; the other 16 need time off); OT sheet: **50 of 50**; raw checks, settings, summary key tests pass. Not yet green: 49 tests that need time off (below) | done except time off |
| B | LOGIC DONE 7 Nov (219/219 tests pass: leave statuses, substitute leave, AH algorithm, OT compensation, annual leave, GM limits); still todo: leave screens, leave type data, leave report, employee leave counters. time off: `hr.leave.cover` / `hr.leave` / types / allocations on Odoo 19 `hr_holidays` (core was rewritten: durations, allocation flow), AH allocations, annual leave, OT compensation | todo |
| C | requests (`hr.attendance.request`: working time, overtime), workflow buttons of `hr.mixin`, refuse log, OT holiday plan, GM approval settings, notification emails | LOGIC DONE 7 Nov: workflow, refuse, emails, request screen, OT holiday plan tested (20 tests); mail templates, settings page, leave/hr screens loaded; see "Stage C status" and "Stage C, part 2" |
| D | reports, wizards, summaries, dashboards | REPORTS DONE 7 Nov (14 py3o reports render; see "Stage D reports"); admin wizard, summaries loaded earlier; dashboards / Plotly test report not ported |
| E | face-machine feed, remote staff sync, bizone SQL Server | todo (not needed for dev data) |
| Import | kdvn_legacy_import steps for each stage's tables (raw checks, attendance, requests, leaves, allocations) | follows each stage |


### Step 4 status, 7 Nov 2026 (end of session part 1)
Module `kdvn_hr_attendance` (19.0.0.1.0) + `kdvn_base` (19.0.1.0.0) on branch `feature/kdvn_hr_attendance` (`.worktrees/attendance`), 11 commits. Tests: `docker exec odoo19 odoo -c <conf with worktree path> -d kdvn_test -u kdvn_hr_attendance --test-tags /kdvn_hr_attendance ...` : 219 tests, 170 pass, 49 fail (all need leave: LS 11, SB 4, AH 8-10, LV 12, GM/leave 7, OT-on-AH 2, ST-07-04 Saturday AH).
What I learned (all in the module CLAUDE.md): Odoo 19 core hr.attendance has its own overtime engine and requires check_in: neutralised (`_update_overtime`, `_get_overtimes_to_update_domain`); `create` overrides must take a list (`@api.model_create_multi`, legacy body kept as `_legacy_create`); selections need str keys (int `color`/`at_month` became Integer); `resource.calendar` Odoo 12 methods are re-created in `models/resource_calendar.py`; OCA web_notify / hr_holidays_public have no 19 build here: replaced by `res_users.py` (notify_*) and own models; company working calendar must use timezone Asia/Ho_Chi_Minh (the Odoo 12 production data does; the legacy import must bring the calendars).
Next (stage B, leave): the 49 failures are all in `hr_leave.py` (2800 lines) against Odoo 19 `hr_holidays`: fix `hr.leave.create` path (rights check, durations), `hr.leave.allocation` flow (no action_confirm/validate), type fields moved (`valid`, `validity_*`, `allocation_type` shimmed), leave report SQL view (not loaded), employee `leaves_count`, then views (`hr_leave_views.xml`, `hr_views.xml`, `res_users_views.xml`, settings, mail templates, reports) and the data of leave types (`data/data_leave_types_stageB.xml`). Then stage C polish (notifications/emails, QWeb reports), D reports, E feed, and the importer steps for attendance/requests/leave/allocations (then the baseline comparison against Odoo 12 on the same employees).


### Data import and parity, 7 Nov 2026
`kdvn_legacy_import` now imports the attendance data (see its CLAUDE.md). Parity runs (scratch DB `kdvn_att_try`, recompute in Odoo 19 vs Odoo 12 stored values, requests included):
- 21 Oct - 20 Nov 2026, 34 staff, 408 days: 381 identical, OT hours 100 % identical; the 27 differences are Saturday AH days (need stage B time off).
- 21 Jun - 20 Jul 2026, 2 staff with OT/WT requests (+ their managers), 108 days: of the 54 days Odoo 12 had computed, 43 identical; the 11 differences are 10 Saturday AH / OT-holiday days (stage B) and 1 day with check-out earlier than check-in (to review). The other 54 days were never computed in Odoo 12 (empty status), so there is nothing to compare.
Real-data findings fixed: Odoo 19 core refuses check_out < check_in (the import sets `kdvn_skip_checkin_check`); OT holiday line `create` must return the records.


### Stage B (time off) logic, 7 Nov 2026
All 219 module tests pass. What Odoo 19 needed: core computes leave dates (half days via periods set from our morning/afternoon boxes; `request_unit_half` always on); `_onchange_leave_dates` / `action_draft` / `holiday_type` / `remaining_leaves` / `valid` kept as compat; allocations need dates (default = leave type validity) and keep their name (Odoo 19 renames on every change); `sudo(uid)` is `with_user(uid)`; SQL-view summary needs a flush before reading; fixture calendar must have Saturday. Not yet: leave views/menus (`views/hr_leave_views.xml`, `hr_views.xml`, `res_users_views.xml` are converted but not loaded), leave type data (`data/data_leave_types_stageB.xml`), `hr.leave.report` SQL view, `leaves_count` compute, mail templates and QWeb reports.


### Leave import (7 Nov 2026) - state
`kdvn_legacy_import` has the steps lv_reasons, lv_types, lv_allocations, lv_leaves (covers, leaves, calendar entries), lv_links. On a fresh scratch DB they created 81 leave types, 1,177 allocations and 10 covers/leaves/calendar entries for 2 staff (21 Jun - 20 Jul). Known issues, NOT solved yet:
1. A RE-RUN on a database that already holds imported covers stops in step `organisation` with "OdooBot doesn't have read access to hr.leave.cover" (path: kdvn_hr_ext `_compute_1st_manager` -> employee write -> hr.leave write -> `related_at_ids`). First runs on an empty database work. Next: make the nested reads superuser (or give OdooBot read ACL on the cover model).
2. 30 allocations failed in the first run because of Odoo 19's "duration > 0" check (fixed by `_duration_check` override, not yet re-verified after the fix).
3. The Saturday AH days of the trial staff still differ (10 of 65 compared days) because their AH leaves/allocations were not imported in the same run; re-check once issue 1 is fixed.


### Leave import issues 1 and 2 (7 Nov 2026)
1. FIXED. Cause was not OdooBot rights: `hr.leave.cover._search` hides covers with reason `ah` unless `show_ah`, and Odoo 19 reads fields through `_search([('id','in',ids)])` (Odoo 12 did not), so reading an AH cover raised a false access error. Id lookups now skip the filter. Re-run on `kdvn_att_try` (264 staff, 21 Jun - 20 Jul) passes every step.
2. Allocation "duration > 0": 0 allocation failures (15,048 created, 1,207 updated). New: 2 leave types fail to update ("This modification is not allowed in the current state": type 90 Annual Leave, 96 AH for Jul. 2026) and 1 employee (S1429, still manages sections: data). To look at next.

BUSINESS RULE (Thanh, 7 Nov 2026): the payroll system (third party) does not accept a day with two leave types. Technically Odoo can create them, but we must not allow or produce them; any day with two types in an import or parity run is to be explained. Also in addons/kdvn_hr_attendance/CLAUDE.md.
Leave types 90 (Annual Leave) / 96 (AH Jul. 2026) re-run update failure: the type write recomputes durations of their VALIDATED leaves in an env that lost the skip flag (`leave_skip_state_check` set on run and step did not help); only metadata of those 2 types stays stale on a re-run, nothing else is lost. Not solved; low priority.


### Parity, 21 Oct - 20 Nov 2026 (7 Nov 2026): 4,488 of 4,488 days identical
284 working staff, full import of the window incl. covers, leaves, allocations and calendar entries into `kdvn_att_try`, then every imported attendance day recomputed in Odoo 19 (`tools/parity_attendance.py`, rolled back) and compared with the stored Odoo 12 values (status marks, absence, OT hours, working/holiday hours, late/early): **0 differences** (before the fix: 15, all Saturday AH days).
Cause of the 15: the importer left adopted employees on Odoo 19's default calendar / time zone UTC, so their working hours were read as UTC and the AH leave (on the company calendar, Asia/Ho_Chi_Minh) never removed the Saturday work. The calendars step (`at_calendars`) now copies each employee's Odoo 12 calendar and time zone. Tests 232/232 (attendance + import).
Earlier parity window 21 Jun - 20 Jul (the 11 differences) should be re-run the same way. Stage B logic is therefore proven against real data for this window; the open stage B items are screens, leave type data, leave report, mail templates (see table).


### Stage C status (7 Nov 2026)
DONE: `data/mail_templates.xml` loaded (daily manager email, refusal email, states-unsync, OT warning, rules / allocation / monthly summary templates; Odoo 12 `t-esc` / `t-raw` became `t-out`), `views/res_config_settings_views.xml` loaded (attendance policy, GM approval limits, face / BZ server; converted to Odoo 19 `<block>` / `<setting>`), `tests/test_requests.py` (12 tests: RQ-01 state chain and attendance state, RQ-01a status before final, RQ-03 description size, RQ-04 no OT, RQ-11 refuse comment + status back, RQ-13 withdraw / revise, RQ-14 daily email and refusal email).
Port bugs found and fixed by those tests: (1) `ir.ui.view.render()` no longer exists: 5 call sites now `ir.qweb._render(view.id, values)`; (2) the SQL views `hr.attendance.manager.request` / `ot.holiday.manager.request` return `json_agg` columns that psycopg2 now parses to a list, while the code does `json.loads` (Odoo 12 got strings): the columns are cast `::text`.
NOT done in stage C: the other QWeb templates are only checked for loading (rules / allocation / monthly summary are rendered by existing tests only where they run); leave screens and menus (`hr_leave_views.xml`, `hr_views.xml`, `res_users_views.xml`), employee leave counters, leave report; request wizards (OT / WT request screens: `hr_attendance_wizard.py`) are not exercised by tests; OT holiday plan screens; Talk notifications are later (as in Odoo 12). Reports (py3o ODS/ODT, stage D) not started.


### Stage B screens (7 Nov 2026)
DONE: `views/hr_leave_views.xml` (cover list / kanban / form / filter, leave form for the cover, leave type, reason, allocation forms / filter / list / pivots, OT days tracking list, actions, menus), `views/hr_views.xml` (employee form: leave balances, need-HR-action alert, joining date, OT flag, remote code in the KDERP group; department form), `views/res_users_views.xml` loaded; `models/hr_leave_report.py` loaded (allocation summary view, OT days tracking view rewritten for Odoo 19 `mail.tracking.value`); ACL rows added. Tests 248 pass (`tests/test_screens.py` opens every window action of the module with its views and reads the first row; `TestLeaveCounter`: `leaves_count` = allocated minus validated leave days).
Decisions: (1) Odoo 12 changed core `hr_holidays` actions, menus and views in place (All Leaves, My Leaves, Allocations, Leave Types, section leaves, the hr.leave form sheet and kanban, the Time Off root menu). Odoo 19 core views inherit each other more deeply, and in place changes would alter Odoo's own Time Off app, so our menus now use OUR OWN actions (`hr_leave_cover_action_section`, `hr_leave_allocation_action_working`, `open_view_holiday_status_kdvn`, `action_hr_leave_summary_pivot`); core actions are untouched. (2) The core hr.leave form and kanban replacements are not ported (nothing of ours used them). (3) Odoo 12's override of the SQL of core `hr.leave.report` is not ported: core report stays. (4) `data_leave_types_stageB.xml` (Odoo 12 overrides of demo leave types) is NOT loaded: real leave types come from the import (81 types). (5) Not ported: employee kanban attendance icon and department kanban leave counters (core 19 has both), the `general_director_id` read-only preference (kderp_base). (6) A search filter of the core allocation search is hidden with `invisible`, not removed (another core view inherits it).
Still open for stage B: mail templates for leave notifications (if any beyond the cover chatter), the `fa` icon title warnings of the cover buttons (cosmetic), a real browser look at the screens.


### Stage C, part 2 (7 Nov 2026): request screen and OT holiday plan tested
`tests/test_requests.py` now has 20 tests (256 in the module + import): `TestRequestWizard` (the request screen: a WT request typed on screen goes to the manager at once, as in Odoo 12; an OT request submitted from the screen; a refused attendance cannot be submitted again) and `TestOTHolidayPlan` (monthly record lists the holidays of the AT month; a registered line waits for the manager, the approved line makes the system create the draft OT request; refusing the line removes the open request; once the request is past the manager the line cannot be unregistered or refused: ValidationError / UserError).
Literal Odoo 12 behaviours worth knowing (not changed): (1) a request created through the screen or the ORM is submitted automatically unless `set_draft` is in the context; (2) un-ticking `ot_register` on an APPROVED line (state done) does not remove the draft OT request (the removal only runs when the line goes waiting_fman -> draft or is refused); (3) `OdooBot` (uid 1) may validate from any state, other users only from waiting_fhr.
Stage C is complete for the logic. Left in C: browser look at the screens, `fa` icon titles on buttons, Talk notifications (later, as in Odoo 12). Next: stage D (reports and wizards: py3o monthly reports, summaries, admin control wizard) and the importer steps for refuse log and summaries.


### Stage D start (7 Nov 2026)
- `report_py3o` 19.0.1.0.1 (OCA reporting-engine, commit 2e32402) copied by Claude into `~/odoo19_thcn/extra-addons/report_py3o` (git-ignored; Thanh allowed it on 7 Nov). py3o libraries and LibreOffice are in the odoo19 container. Reports not started yet: they will depend on `report_py3o`.
- Importer: new step `at_refuse` (refusal comments of the imported requests / covers). Real run, window 21 Nov - 20 Dec 2025: 4 comments imported. (Window 21 Oct - 20 Nov 2026 has none.)
- FOUND, NOT ANALYSED: the same real run (window 21 Nov - 20 Dec 2025, 7,861 attendance rows) failed on 6 attendance days (check_in and check_out not on the same day, night work, e.g. AT-251121-S1804), 30 requests and 16 covers. These are data rows the port rejects; each one needs an explanation before the go-live migration. Re-run with `run(...)['errors']` to list them.


### Stage D reports (7 Nov 2026)
DONE: 14 py3o reports of Odoo 12 ported literally (same .ods / .odt templates, copied to `report/`, report records in `report/at_reports.xml`): 9 admin-wizard reports (monthly overtime, estimate overtime, working time, leave, attendance record, yearly OT compensation, yearly AT performance, leave allocation remain, AT location; xlsx), attendance requests, approved attendance and compact attendance sheets, request of approval (attendance, leave) (pdf). `tests/test_reports.py` renders every one through py3o + LibreOffice and checks the file type (zip/xlsx, %PDF); 268 tests pass in total.
Not ported: `approved_att_bak/original`, `at_monthly_*_back/origin/_using_direct_method` templates (old copies), `new_att_report_faster.odt` and `ot_holiday_schedule` (their report records are commented out in Odoo 12), `test_plotly` (an experiment).
New / changed for Odoo 19:
- `report_py3o` 19.0 (OCA) in extra-addons; new module `kdvn_report_py3o` (depends on it): offers the `xlsx` output type (py3o.formats of the container knows only `xls`; LibreOffice converts with `--convert-to xlsx`). Left of kderp_report_py3o NOT ported yet (only needed by other modules): barcode / parser context extras, ReportLab T1 fonts, `print_lang`.
- `kdvn_base`: `res.company.report_date_format` (default `dd-MMM-yyyy`, used by the request-of-approval templates) + a KDVN tab on the company form. Other kderp_base company fields (`locationcode`, `general_director_id`) are not ported.
- The Print button (`action_print_monthly_reports`) now passes the wizard record to `report_action(self, ...)`: with an empty list the Odoo 19 py3o report has no record to render. Core note: an admin on a company without a configured document layout first gets Odoo's "Configure your document layout" dialog (core behaviour, once per company).
- The report data methods that run raw SQL (`report_ot_by_at_date`, `report_estimate_ot_by_at_date`, `report_at_locations`) flush pending ORM writes first (Odoo 19 does not).
- The monthly overtime templates need one attendance row for every day of the AT month per employee (they read `lastsat[0]` and `attendances[0..N]`); the real data has that (daily rows), a month with no data gives a template error (same in Odoo 12).
NOT proven yet: that the NUMBERS in the reports equal Odoo 12's (rendering only). Next check: print the same month in Odoo 12 and Odoo 19 (import of that window) and compare the xlsx cell by cell.
Deploy note: kdvn_hr_attendance now depends on `report_py3o` (OCA 19.0, copy into extra-addons by hand, outside git), `kdvn_report_py3o`, LibreOffice and py3o.template / py3o.formats on the server.


### Report parity, month 21 Nov - 20 Dec 2025 (7 Nov 2026)
Same month printed in Odoo 12 (att18mar) and Odoo 19 (scratch DB `kdvn_att_try`, 284 working staff imported with the window), compared row by row (`tools/parity_reports_odoo12.py`, `tools/parity_reports_odoo19.py`, `tools/compare_reports.py`).
RESULT: **identical** for monthly overtime, estimate overtime, attendance record (the payroll sheet), leave status and working time. Differences left, both explained and not bugs: leave allocation remain (18 of 267 staff: their leaves earlier in 2025 are outside the imported window, so the balance differs; a full import has them) and AT location (3 leavers are not imported with `working_only`, the rest identical).
What the first comparison found and fixed (all in the import or in literal-port gaps):
1. Staff tags (G8, Top Manager...) were not imported: G8 staff get OT compensated by leave, so 19 rows of the attendance record differed. New step `employee_categories`.
2. Odoo 19 recomputed stored fields of the imported days (absence, compute_out, OT hours, locations, status marks) while later steps ran, before the requests they depend on existed. New LAST step `at_restore` writes the Odoo 12 values back in SQL (and the status marks, and the machine locations): the import never recomputes.
3. Six night-start days failed the "same day" check (the day start moves with an early-in request that is imported later) and 28 requests failed the OT deadline check: both validations are skipped under the import-only context flag `kdvn_skip_checkin_check` (Odoo 12 had accepted the rows). Leaves beyond the allocation (Odoo 12 let AH go over) skip core `_check_validity` under `kdvn_legacy_import`. The holiday plan no longer creates OT requests while importing (`kdvn_no_ot_plan_sync`): it made duplicates.
4. **Real port bug:** Odoo 19 has no `name_get()`. Nine models still defined it, so `display_name` was the default (the working time report printed an empty reason, lists showed plain names). Converted to `_compute_display_name` (Odoo 12 bodies kept as `_legacy_name_get`); callers of `.name_get()[0][1]` now use `display_name`. Allocation names lost two Odoo 12 targets (`mode_company_id`, category) that Odoo 19 does not have.
Whole window now imports with 0 errors (7,861 days, 5,071 requests, 786 covers, 1,397 plan lines). Tests: 272 pass.
Stray rows from earlier import runs (untagged requests / covers made by 19 automation) had to be removed from the scratch DB by hand before the final run; a clean database does not have them.
NOT compared yet: the yearly reports (OT compensation, AT performance: need the whole year imported), the PDFs (visual check), and months with Saturday AH / holiday plan edge cases beyond Nov-Dec 2025 and Oct-Nov 2026.

### Report parity, whole year 2025 (7 Nov 2026)
Full import of 21 Dec 2024 - 20 Dec 2025 (working staff: 91,569 attendance days, 45,236 requests, 9,610 leaves, about 2 h) into the scratch DB, then the same reports printed in Odoo 12 and Odoo 19 and compared row by row (`tools/compare_reports.py`; `COMMON=1` keeps only staff printed by both sides, because leavers are not imported with `working_only`).
RESULT:
- Yearly OT compensation and yearly AT performance (year 2025): **identical**.
- Attendance record (the payroll sheet), all 12 AT months of 2025: **identical** (no filter needed).
- Monthly overtime, estimate overtime, working time and leave, months Jan-Nov 2025 (`COMMON=1`): **identical**; the only difference is the header row that counts staff (leavers).
- Leave allocation remain (Dec 2025): 17 of 267 staff differ, all explained: Odoo 12 also counts leave taken after 20 Dec 2025 (e.g. "Last Year Leave" 31 Dec - 7 Jan) which is outside the imported window. Checked on S2144 (4 days = the 4 days after the window).
- AT location: same rows; only the row numbers move (leavers missing).
Importer changes for a year: every step now clears the ORM cache and, with context `kdvn_commit_steps`, commits (a first all-in-one-transaction run died with MemoryError after 2 h and rolled back; steps are re-runnable so a crash resumes). Run: `env['kdvn.legacy.import'].with_context(kdvn_commit_steps=True).run(employee_codes=[], working_only=True, date_from=..., date_to=...)`. Report scripts take `AT_DATE` and `KEYS` environment variables.
NOT compared: PDFs (visual), Dec 2025 onwards beyond the earlier checks.
