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
