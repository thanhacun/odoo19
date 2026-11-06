# kdvn_legacy_import (Odoo 19)
Re-runnable import of Odoo 12 data (dev test data now, go-live migration later). Design decided 6 Nov 2026: SQL read, ORM write.
- Source: database `legacy12` on the Odoo 19 Postgres (param `kdvn_legacy.db`), made by `tools/legacy12_snapshot.sh` (pg_dump of att18mar from `kdvn.odoo12.db.dev`, ~75 s, 1.5 GB). The two Postgres containers are on different docker networks, hence the copy. Read-only session; same server and login as Odoo.
- Every record gets external id `legacy12.<odoo12 table>_<id>`. Rerun = update; an untagged record with the same natural key (employee code or linked user, user login, department code, location name, type code) is adopted and tagged; else created. Odoo 12 users 1 and 2 map to `base.user_root` / `base.user_admin` and are never rewritten.
- A bad row is rolled back in a savepoint, counted, and listed in the log; the run goes on.
- Scope: `employee_codes` (empty = all) + `working_only`; managers (parent, admin manager, department managers) of the chosen staff are always added so chains stay whole.
- Odoo 12 values are copied as they are (parent, admin manager, sections), not recomputed from history; history is then loaded with `kdvn_defer_org_refresh` and the manager-user chains are computed once at the end.
- Groups: legacy group -> Odoo 19 group with the same xml id, module `kderp_x` renamed `kdvn_x`; `base.*` never copied. Groups with no counterpart show in the log as "legacy group not mapped": the module that needs them maps them when it is ported.
- Not imported yet: employee photos, leave balances, attendance and requests (later steps of kdvn_hr_attendance; add steps by extending `_import_steps` in your own module).
- `password` option (dev only) sets one password on all imported users. Never use it on a real database.
- Wizard: Settings > Technical > Import from Odoo 12 (system admins). From code / shell: `env['kdvn.legacy.import'].run(employee_codes=[...], working_only=True, password='...', dry_run=True)`.
- Tests use a small fake snapshot (no `legacy12` needed): `-u kdvn_legacy_import --test-tags /kdvn_legacy_import` (12 tests).
