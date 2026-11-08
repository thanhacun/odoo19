# Importing Odoo 12 data into Odoo 19 (runbook)

Written 7 Nov 2026. Same procedure for dev test data now and for the production move later.
Module: `addons/kdvn_legacy_import` (read its CLAUDE.md for what each step copies). Command: `tools/legacy_import.sh`.

## How it works
1. Odoo 12 data is copied into a read-only database `legacy12` on the Odoo 19 Postgres (`tools/legacy12_snapshot.sh`).
2. The importer reads `legacy12` with plain SQL and writes into the target database through the Odoo 19 ORM, so every Odoo 19 rule and computation applies.
3. Every record gets the external id `legacy12.<odoo12 table>_<id>`. A re-run updates records instead of duplicating them. An untagged record with the same natural key (staff code, login, department code, location name, type code) is adopted and tagged.
4. A bad row is rolled back alone, counted and listed in the log; the run goes on. Each step commits when it finishes (`kdvn_commit_steps`), so a crash is resumed by running the same command again.

## Step 1: snapshot (when the Odoo 12 data changed)
```
cd ~/odoo19_thcn && tools/legacy12_snapshot.sh att18mar
```
Drops and recreates `legacy12` and copies the source database into it (about 75 s, 1.3 GB). Nothing is written to Odoo 12.
For production: restore the production backup into `legacy12` instead (Odoo 12 stopped first, so there is no gap).

## Step 2: dry run
```
tools/legacy_import.sh odoo19_dev 2026-08-21 2026-11-20
tail -f temp/legacy_import_odoo19_dev_<time>.log        # the path is printed
```
Without `--apply` it does everything and rolls back. The log ends with `RESULT DRY RUN`, the counts per table and a list of "N problem(s)". Read the problems before applying.
The command starts the work in the background (`docker exec -d`), so closing the terminal does not stop it. The running Odoo server can stay up.

## Step 3: apply
```
tools/legacy_import.sh odoo19_dev 2026-08-21 2026-11-20 --apply
```
Options: `--password PW` (dev only: one password on ALL imported users; never on a real database), `--codes "S0001 S0002"` (only these staff; their managers are added), `--all-staff` (include leavers), `--steps "at_attendance at_raw"` (only these steps).
The window (date_from / date_to) limits attendance days, raw checks and requests. Staff, history, rules, leave types and allocations are always complete.
Time: roughly 10 minutes per month of all working staff (a whole year about 2 hours; first run on an empty database is the slowest).

## Step 4: check
- Log ends with `RESULT APPLIED` and the problem list. Known harmless items are in the module CLAUDE.md.
- Counts, for example `docker exec db psql -U odoo -d odoo19_dev -tAc "select count(*) from hr_attendance"`.
- Parity (the real proof): `tools/parity_attendance.py` recomputes the window's days in Odoo 19 and compares them with the stored Odoo 12 values. 4,488 of 4,488 days were identical for 21 Oct - 20 Nov 2026.

## Re-running and extending
Run the same command with a wider window: existing records are updated, new ones added. Steps in order: department_types, locations, departments, users, employees, employee_categories, employee_links, histories, organisation, at_policy, at_calendars, at_holidays, at_locations, at_codes, at_rules, at_attendance, at_raw, at_requests, at_ot_plans, lv_reasons, lv_types, lv_allocations, lv_leaves, lv_links, at_refuse, at_restore.

## Production move (to settle with the plan later)
- Fresh empty Odoo 19 database with all modules installed (`lunarcalendar`, `weasyprint` in the image; see `requirements-extra.txt`).
- No `--password`: users get a proper password reset.
- Cut-over: stop Odoo 12, back up, restore into `legacy12`, run with no window limit (full history). A year takes about 2 hours, so either plan the downtime or load history earlier and run a short final delta (a narrow window re-run).
- Business rule (payroll cannot take two leave types on one day): any such day found in a parity run must be explained before go-live.
- Known open items: leave types 90 (Annual Leave) and 96 (AH Jul. 2026) fail to update on a re-run (only their metadata stays stale); employee photos, summaries and the refuse log are not all covered (see the module CLAUDE.md).

## Bulk mode (`--bulk`, 8 Nov 2026) and the nightly delta (design)
`tools/legacy_import.sh <db> <from> <to> --apply --bulk` loads the big history tables with streamed SQL instead of one ORM create per row
(`addons/kdvn_legacy_import/models/legacy_bulk.py`): attendance days (+ status marks), raw checks, requests, OT plans and lines, leave covers,
leaves, allocations, calendar leaves, and the side tables (viewer lists, attendance-cover links). Staff, organisation, rules, leave types
and the refusal log stay on the ORM steps (small). The legacy tables are read with a server side cursor in chunks of 5,000 rows (constant memory:
the ORM path died with MemoryError on 480k attendance days); one INSERT per chunk; a failing chunk is retried row by row and the bad rows listed.
- Values are the Odoo 12 stored values as they are (also for leaves: the ORM path recomputed `number_of_days` and `date_to` of 63 of 316 leaves
  of one month; bulk copies the Odoo 12 value). Stored computed fields with no Odoo 12 value get their formula: attendance `expected_hours`
  (= worked hours), `overtime_hours` / `validated_overtime_hours` (0), `summary_id`, `date` (local date of the check in), allocation
  `number_of_hours_display` and the allocation dates (leave type validity), leave `duration_display`, `number_of_hours`, `request_unit_half`.
- Re-runnable: rows with the external id `legacy12.<table>_<id>` are updated in place (INSERT .. ON CONFLICT (id) DO UPDATE), new rows take the
  next id of the sequence. create/write dates are the Odoo 12 ones.

### Delta (nightly during the training weeks, and the final one at cut-over) - design, not built yet
1. Odoo 12 stays the only place where people work; nothing is entered in Odoo 19 until cut-over (so the delta may overwrite).
2. Changed rows: every source table has `write_date`. Keep `kdvn_legacy.last_delta` (ir.config_parameter) = the largest source `write_date`
   seen minus 10 minutes. `_bulk_load(table, ..., where="write_date > last_delta")` already updates in place by external id. Relations of a changed
   record are replaced (delete the record's rows, insert the legacy ones: `_bulk_relation(..., delete_ids=changed ids)`).
3. Deleted rows: Odoo 12 hard-deletes (nothing remains in the table). Detect by comparing id lists: stream `SELECT id` of the legacy table
   (ints only, about a second for 480k) against the external ids of the target; ids in Odoo 19 but not in Odoo 12 are deleted in Odoo 19
   (rows, side table rows and the external id), counted in the log.
4. Small ORM steps (staff, org, rules, leave types, refusal log) simply run again (about 90 s).
5. Cut-over: stop Odoo 12, back up, restore the final dump into `legacy12`, run the delta (minutes), start using Odoo 19.
