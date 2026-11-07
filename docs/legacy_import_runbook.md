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
