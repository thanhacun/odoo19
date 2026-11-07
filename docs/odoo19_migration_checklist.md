# Odoo 12 -> 19 migration checklist (sweep)

Written 7 Nov 2026. Run this on every module we port, BEFORE writing tests, and again before merging.

## 1. The official rewrite tool (Odoo 17.5 -> 19)
Odoo ships `odoo upgrade_code` (scripts in `odoo/upgrade_code/`: tree->list, `_sql_constraints` -> `models.Constraint`, `type='json'` routes,
deprecated properties, dynamic dates in domains). It only knows versions from 17.5 on; for 12 -> 17 there is no official tool (see section 3).
```
cd <worktree> && git status            # must be clean: the tool edits files in place
docker exec odoo19 odoo upgrade_code --from 17.5 --dry-run --addons-path /home/odoo/project/.worktrees/<wt>/addons --glob 'kdvn_*/**/*'
docker exec odoo19 odoo upgrade_code --from 17.5 --addons-path ... --glob 'kdvn_*/**/*'     # apply, then READ git diff
```
Known flaw: it rewrites commented-out code too and can break syntax (it did on a commented `_sql_constraints`). Compile every changed file
(`python3 -m py_compile`) and read the diff. What it fixed for us: `view_mode "tree,form"` and `mode="tree,form"` in Python actions and one2many fields,
`context_today()` filters -> dynamic dates (`'today'`), `self._context` -> `self.env.context`.

## 2. Our static sweep
```
docker exec odoo19 python3 /home/odoo/project/.worktrees/<wt>/tools/odoo19_sweep.py /home/odoo/project/.worktrees/<wt>/addons [module ...]
```
BREAK = no longer works; WARN = works, deprecated. Run it in the container (Python 3.12, same as Odoo). Rules are in the script (each has its reason).
Things it found or that bit us before: compute methods that do not assign every field or call `ensure_one()`; `name_get` -> `_compute_display_name`;
`invisible="1"` in list fields -> `column_invisible="1"`; primary views that lose to core's priority 16; `groups_id` -> `group_ids`;
`invalidate_cache()`; `kanban-box` -> `card` and `t-esc` -> `t-out`; x2many defaults must be commands; selection keys must be strings.

## 3. Versions between 12 and 17: the OCA migrator
`odoo-module-migrator` (pip, version 0.5.0 checked 7 Nov 2026) has rules per Odoo version: start 8.0-17.0, target up to 18.0. Together with section 1
(17.5 -> 19) the two tools cover 12 -> 19. Use it on a COPY, never on `~/odoo12`:
```
python3 -m venv /tmp/oca && /tmp/oca/bin/pip install odoo-module-migrator
mkdir /tmp/mig && rsync -a --exclude __pycache__ ~/odoo12/addons/<module> /tmp/mig/ && cd /tmp/mig && git init -q . && git add -A && git commit -qm base && git branch -m 12.0
/tmp/oca/bin/odoo-module-migrate -d /tmp/mig -m <module> -i 12.0 -t 18.0 -nc -npc -nrmf -ll WARNING > /tmp/oca_log.txt
cd /tmp/mig && git diff --stat        # what it rewrote (compare with our port); the log lists what it could not do
```
Tried on `kderp_hr_attendance` (Odoo 12 copy): it rewrote 37 files (229 `@api.multi` removed, `<tree>` -> `<list>`, `sudo(2)` forms) and warned about
`invalidate_cache`/`refresh`/`flush`/`recompute` (24), `@api.model_cr`, `@api.returns`, `message_post_with_view`, `numbercall`/`doall`, `@string=` xpath,
`env.user.company_id` -> `env.company` (56). It does NOT convert `attrs=` or `name_get`. Its extra rule types were added to `tools/odoo19_sweep.py`.
For a module not ported yet (e-approval, procedures): run the migrator on a copy first, read the diff and the log, then port by hand and run section 2.
Its messages are a good source for new sweep rules: when the log shows a message our sweep lacks, add a rule.

## 3b. Odoo 20 readiness
Odoo 20 is not available here, so we use what Odoo 19 itself marks deprecated ("Since 19.0 ..." warnings in the 19 source): `odoo.osv`/`expression` -> `Domain`,
`read_group` -> `_read_group` / `formatted_read_group`, `request.env`/`request.cr`/`request.context` shortcuts, `check_access` variants, `type='json'` routes.
`tools/odoo_deprecations.py` runs Odoo (tests, upgrade) and records every Deprecation/FutureWarning raised from our code with the caller (file:line):
```
docker exec odoo19 python3 /home/odoo/project/<tree>/tools/odoo_deprecations.py -c <conf> -d kdvn_test -u <modules> --test-tags /<module> --stop-after-init ...
python3 tools/odoo_deprecations.py --report temp/deprecations.tsv
```
First run (7 Nov, attendance + HR + import + remote): 8 findings (`odoo.osv` import, `read_group` x4, `Domain` x2, WeasyPrint HarfBuzz notice). Tests only touch part of the code, so
the static sweep (WARN rules) and this runtime list complement each other. Policy: fix BREAK at once; fix WARN/deprecations module by module when we touch that code or before each
Odoo major upgrade; re-run both tools when Odoo 20 is released and read its `upgrade_code` scripts first.

## 4. Runtime checks that static rules cannot do (in the module tests)
- every window action opens (`tests/test_screens.py`), every model's computed fields read on an empty record and on many records,
- our views are the ones `get_view` resolves for the model,
- read the imported data field by field (script in the session notes: `temp/scan_read.py`, models x 400 records) on a real import.
