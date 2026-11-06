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
| B | IN PROGRESS: time off: `hr.leave.cover` / `hr.leave` / types / allocations on Odoo 19 `hr_holidays` (core was rewritten: durations, allocation flow), AH allocations, annual leave, OT compensation | todo |
| C | requests (`hr.attendance.request`: working time, overtime), workflow buttons of `hr.mixin`, refuse log, OT holiday plan, GM approval settings, notification emails | todo |
| D | reports, wizards, summaries, dashboards | todo |
| E | face-machine feed, remote staff sync, bizone SQL Server | todo (not needed for dev data) |
| Import | kdvn_legacy_import steps for each stage's tables (raw checks, attendance, requests, leaves, allocations) | follows each stage |


### Step 4 status, 7 Nov 2026 (end of session part 1)
Module `kdvn_hr_attendance` (19.0.0.1.0) + `kdvn_base` (19.0.1.0.0) on branch `feature/kdvn_hr_attendance` (`.worktrees/attendance`), 11 commits. Tests: `docker exec odoo19 odoo -c <conf with worktree path> -d kdvn_test -u kdvn_hr_attendance --test-tags /kdvn_hr_attendance ...` : 219 tests, 170 pass, 49 fail (all need leave: LS 11, SB 4, AH 8-10, LV 12, GM/leave 7, OT-on-AH 2, ST-07-04 Saturday AH).
What I learned (all in the module CLAUDE.md): Odoo 19 core hr.attendance has its own overtime engine and requires check_in: neutralised (`_update_overtime`, `_get_overtimes_to_update_domain`); `create` overrides must take a list (`@api.model_create_multi`, legacy body kept as `_legacy_create`); selections need str keys (int `color`/`at_month` became Integer); `resource.calendar` Odoo 12 methods are re-created in `models/resource_calendar.py`; OCA web_notify / hr_holidays_public have no 19 build here: replaced by `res_users.py` (notify_*) and own models; company working calendar must use timezone Asia/Ho_Chi_Minh (the Odoo 12 production data does; the legacy import must bring the calendars).
Next (stage B, leave): the 49 failures are all in `hr_leave.py` (2800 lines) against Odoo 19 `hr_holidays`: fix `hr.leave.create` path (rights check, durations), `hr.leave.allocation` flow (no action_confirm/validate), type fields moved (`valid`, `validity_*`, `allocation_type` shimmed), leave report SQL view (not loaded), employee `leaves_count`, then views (`hr_leave_views.xml`, `hr_views.xml`, `res_users_views.xml`, settings, mail templates, reports) and the data of leave types (`data/data_leave_types_stageB.xml`). Then stage C polish (notifications/emails, QWeb reports), D reports, E feed, and the importer steps for attendance/requests/leave/allocations (then the baseline comparison against Odoo 12 on the same employees).
