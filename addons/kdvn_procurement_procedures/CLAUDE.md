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

## Accounting report + receipt (10 Nov 2026, Odoo 12 12.0.1.5.0, ported in 19.0.0.2.0)
- Control Sheet wizard, tick "For the Accounting Dept.": adds sheets "Detail check - report to Acc. D" and "Code.Mat" (layout of the old Excel; formulas kept).
  FIFO per material code (`_fifo_lots`): each stock-in (lot: invoice, unit cost) lists the OUT moves taken from it; reversed handovers are netted out.
- ONE material code for everybody: `safety.tool.item.code` ("Code Mat.", ST0018) and optional `safety.tool.size.code` (ST0036-1, overrides the item's). The number
  in the code is the item number on the receipt form. Migration 19.0.0.2.0 (12.0.1.5.0 in Odoo 12) turns old numbers (18, 34-1) into ST0018, ST0034-1; the keeper checks the rest.
- Stock-in move: `payment_no` (typed: supplier payment ENYY-XXXX of the remote = `kderp.supplier.payment.expense`), then "Get from remote server" (Reader, read only)
  fills supplier (name_get), invoice no./date (VAT invoice tab), `expense_no` (fixed cost expense, only stored for later: it also holds jobs and cost user) and
  unit cost = (total - VAT) / qty (wrong when one payment covers several items: edit). The payment comes after the purchase: the report re-reads moves that have a
  payment_no but no invoice yet (option "Refresh ..."). The remote has NO quantities.
- LIMIT (10 Nov): a payment (EN) can be read only when its remote expense has a line whose COST USER (`kderp.other.expense.line.employee_id`, matched by staff code) is
  an employee of a user in the group Safety Tool: Admin (`_remote_allowed_codes`; E-Approval Administrator and the superuser are not limited). Same for the
  invoice -> EN lookup. "Unknown" and "not allowed" give the SAME message, so nobody can probe other payments. Adding a store keeper = put them in the group and
  make sure their employee has the staff code.
- OUT: `work_area` (employee `work_location` = area of the admin department, snapshot at handover); request `receipt_no` = SM-YY-#### (given at the first handover,
  highest number of the year + 1; imported rows take it from the Excel remark "26-163" or "163").
- Printout "Receipt for Safety Tool" (button "Print Receipt" once handed over): `prepare_safety_tool_receipt`, template `reports/safety_tool_receipt.odt`, built by
  `reports/tools/build_safety_tool_receipt_odt.py`; one row per catalogue item in code order, sizes in the remark. Checked: fits one A4 page with 44 rows (py3o + soffice in odoo12.dev).

## Import of the original file (ACC), 10 Nov 2026
- The ORIGINAL control sheet is the ACC file (the one without the extra sheets is the manager's copy). Use the ACC file in the import wizard: sheet 1 is imported as before;
  with "Also read the accounting sheets" (default on) `_apply_accounting` then reads "Detail check - report to Acc. D" + "Code.Mat" (`xlsx.parse_accounting_sheets`)
  and UPDATES existing moves, it creates nothing: stock-in lots -> IN moves (same item/size/qty, nearest date; fills only EMPTY invoice no./date, unit cost, payment no.
  (from the EN header rows of the sheet), supplier); opening balances with no cost are split per invoice (exact FIFO of the Excel lots still in stock on the opening
  date, only when the sum equals the opening quantity); OUT rows -> OUT moves (staff code + date + item/size + qty): working area (from the row) and receipt no. (remark).
- Items/sizes are found by Code Mat.; an item/size of the file without a code gets ST<block No.> (18 -> ST0018, 34-1 -> ST0034-1); new items get it too.
  Codes used by several items (e.g. two ST0018 after the migration) are left out and listed in the result: fix the codes, import again (safe to repeat).
- Option "Add the older lots (accounting history)" (default ON, 10 Nov): lots and OUT rows up to the opening date of an item/size that Odoo does not hold become
  `accounting_only` moves (import_key `accin|..` / `accout|..`, repeatable). They are NOT stock: `stock_map`, the control sheet ledger and item stock ignore them; only the
  accounting report (`_fifo_lots`) uses them, and for a code that has history it skips the opening move (the history already contains it). With the option off, the opening
  balance is split per invoice instead (older behaviour). Option "Create items for unknown codes" (default OFF): new item named as in Code.Mat (e.g. ST0029-1 Safety Belt SSEDA).
- Check on att08nov copy (10 Nov): amounts IN of ~28 of 49 codes equal the Excel Detail totals; the rest differ because that copy has other moves (adjustments, openings),
  duplicate/mis-coded items (ST0018/ST0019) and the Excel's own Code.Mat sheet is broken (#REF!): compare on the real data, code by code.
- Lot matching needs the stock-in date between invoice date -15 and +150 days (else an old lot grabbed a newer move of the same quantity). Every run first CLEARS
  invoice/date/cost/supplier of imported stock-ins that were not read from the remote (`remote_synced_on` empty) and refills them, so an earlier wrong match is corrected.
  History cutoff = first opening date, else the day before the first real move, else the sheet date.
- OUT matching: staff code = employee code, or the first part of the note for plain moves (staff not in the database); an Excel row that Odoo holds as several moves is
  matched when their quantities add up; a row without a date matches only when unambiguous. The history step runs AFTER both matching passes and rebuilds all
  `accounting_only` moves each run (deleted and created again).
- `stock_map` MUST keep the `accounting_only = False` filter also when item ids are given (bug found 10 Nov: history leaked into stock and made 23 stock-take adjustments).
- "Not found" lines before the first opening date (31 Dec 2025) are expected: Odoo holds no history before it.
- Tested on a copy of att08nov with the T10 ACC file (27 lots, 146 OUT rows, 107 receipt numbers matched); NOT yet on the real production data.

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

## Odoo 19 port notes (accounting / receipt / ACC import)
- Ported from Odoo 12 `12.0.1.5.1` by a three-way merge of the Odoo 12 changes (4c1ea6ef..HEAD) onto the 19 files; model and field names are unchanged.
- Remote lookups use `kderp.remote.client.execute` of `kdvn_remote_integration` (same call, Reader login, nothing written). Tests replace `execute` with a fake (`tests/test_safety_tool_accounting.py`).
- Pictures: `odoo.tools.image.image_process` (Odoo 12 `image_resize_image` does not exist in 19; the old import silently skipped every picture because of it).
- hr.employee is private: code/name/work_location of staff are read through `.sudo()` in the receipt and in both Excel reports (store keepers are plain users).
- `option create_history = off` used to raise KeyError 'hist_in' when writing the batch note (also in Odoo 12 `12.0.1.5.1`): counters now start at 0.
- Tests: `-u kdvn_procurement_procedures --test-tags /kdvn_procurement_procedures` (reports, remote lookup with a fake, receipt, ACC import round trips with xlsxwriter-built files).

## Export -> import round trip (11 Nov 2026, 19.0.0.2.1; same change in Odoo 12)
- Re-importing our own accounting export changes nothing (tests `TestRoundTrip`):
  - control sheet rows are "known" when the ledger already holds a move of the same day and quantity (OUT: and staff code), whatever its `import_key`
    (`_row_signature`, `_move_signatures`; the opening balance counts, moves made in Odoo have no key); an Odoo opening balance blocks a second opening;
  - a lot of the Detail sheet without any invoice data is matched to the opening balance / manual IN of the same quantity, so it is not added as accounting history;
  - OUT rows of the same day, staff and code that the report lists once per FIFO lot are matched together to the one handover;
  - a block of a sized item goes back to its size: text line equal to a size name (our export writes it under the item name), else the Code Mat. of the block number;
    a block whose name does not match is mapped by its Code Mat. (`_match_block`, `_size_of_block`).
- `safety.tool.size.code` is in the size list of the item form.
