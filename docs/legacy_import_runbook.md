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

### Delta (nightly during the training weeks, and the final one at cut-over) - BUILT 9 Nov 2026
Decision (Thanh, 8-9 Nov): no change tracking. The bulk loader is fast enough to re-run on a moving window; deletes are found by comparing id lists.
1. Odoo 12 stays the only place where people work; nothing entered in Odoo 19 before the cut-over survives the next run (the delta overwrites). All areas switch at once.
2. `tools/legacy_nightly.sh <target_db> [--dump-path FILE | --fetch-ssh att@172.16.10.198] [--window-months 3] [--full]`:
   fetch (read-only ssh/scp of the newest `*-daily.dump` of /home/att/backups into ~/odoo12/tmp/hn_backups, size and `pg_restore -l` checked) ->
   restore into a fresh snapshot database next to the old one, swapped in only when the restore looks sane -> point the target at it ->
   `legacy_import.sh --apply --bulk --all-staff --prune [--window-months N]` -> parity check of the 30 days that end 3 days ago -> summary line.
3. `--window-months N` (legacy_import.sh): the window is the first day of the month N months back up to the future. Attendance days, raw checks, requests of those
   days, leaves, covers and OT plans of the window are reloaded (upsert by external id); the status marks, leave links and viewer lists are rewritten only for the rows
   of the window; allocations and the refusal log always run again. Older rows are not touched: HR corrections to old months are caught by a weekly `--full` run (about 9 minutes).
   The small ORM steps (staff, org, rules, leave types: about 8 minutes of ORM work, most of it leave types that refuse a re-write) are SKIPPED when the Odoo 12 tables
   they read are unchanged since the last run: `--skip-unchanged` (implied by --window-months) compares a fingerprint (md5 of the content of those tables without the columns
   that change every day: write_date, write_uid, last_attendance_id, login_date, oauth_access_token), kept in the parameter `kdvn_legacy.fingerprint`. A day with a real
   change in those tables (a new employee, a transfer, a rule) runs them once (about 8 more minutes). Every bulk run stores the fingerprint after those steps.
4. `--prune` (`--prune-dry` only counts, `--prune-force` lifts the limit): after loading, per big table (children first: requests, OT lines, OT plans, calendar leaves, leaves,
   covers, allocations, raw checks, attendance) the ids of the Odoo 12 table are compared with the external ids `legacy12.<table>_<id>` in Odoo 19; what is no longer in
   Odoo 12 is deleted (SQL, in chunks, a row blocked by a dependent is kept and listed) together with its external id. A record WITHOUT a legacy12.* external id is never
   touched. Safety limit: a table that would lose more than max(200, 2 %) rows is not pruned and counts as a problem (an empty or truncated snapshot must not wipe the history).
5. Failure signal: exit code (0 fine or no new backup, 1 a step failed, 2 problems or parity differences) and one line in `temp/legacy_nightly_last.txt`
   (`<date time> OK|SKIP|FAIL|PROBLEMS <target> exit N <details>`). If the newest daily has the same sha256 as the one processed last (`temp/legacy_nightly_last.sha`)
   the run says "no new backup" and exits 0 (`--force` runs anyway).
6. When and where: on Thanh's PC, after the HN server backup (cron Tue-Sat 20:30 Hanoi time, about 10 min): start after 21:30, e.g. 21:45. The PC must be on and on the
   office network (ssh to att@172.16.10.198) at that hour; otherwise the fetch fails (exit 1) and nothing changes. Cron line and a systemd user timer are in the header of
   `tools/legacy_nightly.sh` (ready to copy, NOT installed). The server is only READ: one `ls -l` and one `scp` of the newest `-daily` dump. Dropbox is only a fallback
   (it needs the restricted rclone remote of docs/backup-restore.md; the `dbremote` of this PC is the whole account and must not be used).
7. Cut-over: stop Odoo 12, run the server backup (or a pg_dump), `tools/legacy_nightly.sh <target_db> --dump-path <that dump> --full`, check the parity, start using Odoo 19.

### Delta test results (9 Nov 2026, scratch databases, production dumps of 6 and 7 Nov)
- Day over day: full import of the 6 Nov daily, then `legacy_nightly.sh --dump-path <7 Nov daily> --window-months 3`: restore 83 s + import **42 s** + parity 110 s = 231 s in all
  (the full run is about 9 minutes import + restore + parity = 13.6 min). The result is **identical to a full import of the 7 Nov daily** in every table (attendance, raw, requests,
  OT plans and lines, leaves, covers, allocations, calendar leaves: 0 different rows, same row counts) and in all five side tables. The one request that was gone in Odoo 12 was pruned.
- The same dump again: "no new backup", exit 0, 0 s. The same dump with `--force`: 221 s (import 41 s, ORM steps skipped by the fingerprint).
- Simulated day of work (copy of the 7 Nov snapshot): 5 attendance days of Sep 2026 and 2 of Jun 2024 deleted, 1 leave deleted, 5 attendance and 5 leaves changed in the window,
  1 leave changed outside the window. After the nightly: the 7 attendance days, the leave and its calendar entry are pruned (and their external ids); the 10 changed rows are updated;
  the change outside the window is not applied (the weekly `--full` run does it); the comparison with the database before shows exactly those rows and nothing else (side tables:
  only the rows of the deleted days).
- Safety limit: a snapshot that lacks 5 % of the raw checks (17,212 of 344,148) is refused ("NOT deleted", 0 rows removed, reported as a problem).
- Parity of the 30 days that end 3 days ago: 13-14 of about 7,880 days differ (0.2 %): days that Odoo 12 has not settled at the backup, and a few days at the period boundary.
  It is listed, not an alarm (limit 1 %, `--max-parity-pct`). Not yet explained one by one.
