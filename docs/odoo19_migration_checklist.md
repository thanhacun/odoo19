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

## 3. Versions between 12 and 17
No official script exists. Our rules cover the changes we know (`@api.multi/@api.one` gone in 14, `invalidate_cache` in 15, `attrs`/`states` in 17,
`name_get` in 17, `sudo(user)` -> `with_user`, `track_visibility` -> `tracking`, `message_post(subtype=)` -> `subtype_xmlid`, `fields_view_get` -> `get_view`,
JS `odoo.define` -> ES modules). Not covered: anything we do not know about. To close the gap: run the OCA `odoo-module-migrator` (rules per version 8 -> 17+) on a copy
and compare with our sweep (to do, not done yet).

## 4. Runtime checks that static rules cannot do (in the module tests)
- every window action opens (`tests/test_screens.py`), every model's computed fields read on an empty record and on many records,
- our views are the ones `get_view` resolves for the model,
- read the imported data field by field (script in the session notes: `temp/scan_read.py`, models x 400 records) on a real import.
