# kderp_procurement_procedures (Odoo 12)

Home of the procurement / logistics e-approval procedures (category `procurement`). First procedure:
**Safety Tool Request** (`safety.tool.request`, prefix `SFT-YYYY-`) with the safety tool store.
Spec and decisions: `../../docs/spec-safety-tool-request.md`. Platform facts: `../kderp_e_approval/CLAUDE.md`.

## How it fits together
- Request (mixin `kderp.e.approval.mixin`): `request_type` new / replace (replace = Trouble Report block). Lines = item + size + qty.
- Approval steps are PREDEFINED in `data/safety_tool_tier_definitions.xml` (noupdate): SM (sequence 30, `employee_id.parent_id.user_id`),
  GM (20, `gm_id.user_id`), Safety Manager (10, group). Highest sequence = first step. A step is skipped when the applicant is a GM or nobody is found.
- After approval `fulfilment_state` (not an approval step): to_issue / to_purchase (stock check) -> ordered -> issued (admin "Hand over" posts OUT moves)
  -> received (applicant confirms; reminder cron after 3 days, parameter `kderp_procurement_procedures.receipt_reminder_days`). The applicant's
  confirmation never changes stock; "Reverse handover" (admin) puts the tools back.
- Stock = sum(IN) - sum(OUT) of `safety.tool.move` per item and size, always read with sudo (`stock_map`). Moves made by a request are locked.
- Sizes are a property of the item (`safety.tool.size`). `safety.tool.item.external_code` is a placeholder for a later link to the remote
  product.product (remote has no stock and no size attributes: checked 1 Nov 2026).
- Special cases (all shipped OFF = no limit, edit in E-Approval Portal > Special Case Rules): `shoe_limit` (12-month window), `qty_over`, `replace_no_photo`.
- Groups: Safety Tool Admin (store keeper) and Safety Tool Manager (last approval step).

## Excel import (wizard: Safety Tool Store > Import the Control Sheet, group Safety Tool Admin / E-Approval admin)
- Reader `models/safety_tool_xlsx.py` (stdlib only, no openpyxl needed). Wizard + batch + alias in `models/safety_tool_import.py`.
- Per Excel block: item + size (alias memory `safety.tool.import.alias`, else same name, else create; blocks with the same name share one item with sizes).
  Opening line -> opening move (only the first time an item/size is imported); IN rows -> stock-in moves; OUT rows -> requests already approved + received
  (`is_imported`, number `SFT-IMP-`, grouped per day/staff/project, staff by `hr.employee.code`, project text kept; job matched only when the name matches).
  OUT rows with an unknown staff code become plain moves. Last step: stock at the report date = SUM of the Excel remaining per item/size (adjustment move).
- Idempotent: every row has an `import_key` (hash + occurrence); a newer file adds only new rows. A batch can be undone (`Excel Imports`).
- The Excel is never deployed: the store keeper runs the wizard with the latest file. Dry run on a copy: `temp/safety_import_dryrun.py` (odoo shell, rolls back).
- Real sheet (T8, report 142): 56 blocks, 329 OUT rows, 4 blocks whose own running balance does not add up (adjusted), 31 OUT rows without a known staff code.

## Print, report, guides
- Print form `reports/safety_tool_request.odt` (py3o), built by `reports/tools/build_safety_tool_odt.py`; data: `prepare_safety_tool_report`. py3o repeats table rows BETWEEN a row
  holding `for` and a row holding `/for` (both rows are removed). Photos of the trouble go in as small PNG (base64).
- Control Sheet report (wizard `safety.tool.report.wizard`, xlsxwriter): per item/size opening line + moves with a running remaining quantity.
- Guides: `guides/e-approval/safety-tool/` (10-request, 20-store), roles in `guides/_roles.json`, Help entry `menu_help_guide_safety_tool`. Rebuild with `documentation/guides/tools/build.py`.

## Notifications, pictures, guide pictures (1 Nov 2026, later)
- Handover / approved (to the store staff) / not received / reminder: `_tool_notify` (Talk and/or email as each person chose, same channel rules as the approvals
  via `_notify_channels`); the chatter only gets a log note (no second email). Texts: `models/safety_tool_notify.py` (reuses the e-approval render blocks).
- Item photo = field `image` of the item. The Excel import also takes the pictures anchored on each block (`xlsx.read_images`, `pictures_by_block`; only
  items without a photo; resized 600x600). Wizard option `import_pictures`.
- `move_ids` of the request has FIELD-level groups (store staff, auditor): a view-level `groups` only hides the field, the browser still reads it and a
  plain user gets an AccessError on `safety.tool.move` (found 1 Nov). Test: `test_11_plain_user_can_open_the_form`.
- A model field with `states={...}` makes Odoo add a modifier on `state`: any inline list showing it must also contain `state` (invisible), else the browser says
  "Unknown field state in domain" (import batch screen, 1 Nov). Check script idea: temp/check_safety_views.py (fields_view_get + modifiers).
- Guide pictures: fixtures `documentation/guides/scenarios/kderp_procurement_procedures/make_fixtures.py` (dev, odoo shell), scenarios in
  `.../e-approval/safety-tool/{10-request,20-store}.yaml`, `tools/guide_external_safety.py` (Talk bubble + printed form, names invented). Screenshots need the
  dev server WITHOUT the web-client bus problem: run it with `--workers=0` (or open it by its domain name); the printed-form picture needs the normal
  `workers=2` server (py3o cannot print from a `workers=0` instance). Free text from the Excel (remarks) is not masked: the ledger picture is filtered to
  "Issued to requests".

## Pitfalls
- Two many2many to ir.attachment on one model need explicit relation names (`trouble_photo_ids` has its own).
- Writes on a request are locked by tier validation while state is draft/submitted (`_state_from`), but not after approval.
- Tests: `odoo -d <db> --test-file=addons/kderp_procurement_procedures/tests/test_safety_tool.py --stop-after-init` (inside odoo12.dev, from /home/odoo/project).
