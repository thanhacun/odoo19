# kderp_hr_procedures (Odoo 12)

HR approval procedures on `kderp.e.approval.mixin`: **Project Peak Time** (`kderp.project.peak.time`)
and **Staff Transfer** (`staff.transfer`, spec in `staff_transfer_request.md`, section "Staff transfer" below).
Status and next steps: `../../docs/progress-peak-time.md`, `../../docs/progress-staff-transfer.md`.

## Rules
- Special cases use the shared e-approval feature (`kderp_e_approval/models/special_rule.py` + mixin).
  Peak time only writes the checks (`_get_special_case_reasons`) and the rule rows
  (`data/peak_time_special_rules.xml`). Do not add a separate rule model or banner here.
- Limits are data, not code: read them with `self._special_rule('<code>')` (`.is_on()`, `.value`,
  `.action`). New kind of rule = code change + new row; HR only edits values and actions.
- Settings that are not special cases stay in `kderp.peak.time.rule` (only `reminder_days` now).
- Reminder email look is in `models/peak_time/peak_time_notify_render.py` (pure function, uses the shared
  blocks of `kderp_e_approval/models/approval_notify_render.py`). Company green `render.KDVN` (#01622f,
  same as `$o-community-color` in `kderp_web_theme`); change both together.
- Sequences: peak time `seq_project_peak_time` (PT-YYYY-, date ranges on), staff transfer
  `seq_staff_transfer` (ST-YYYY-). Never reuse an xml id from another file.
- A migration needs a NEW version folder (scripts for an installed version never run).

## How peak time works
- Form: job (domain big job + KOM date + user is viewer) fills Client Name (read-only, force_save),
  execution dates and KOM peak dates from `kderp.job.lookup`. Actual peak From/To use `month_date`
  (21st / 20th). Months: `_calculate_months_between_dates` (end inclusive, ≥15 leftover days = +1).
- Special-case rule codes (data/peak_time_special_rules.xml, manager group
  `group_peak_time_functional_manager`):
  `registration_no` 2 (special; rejected requests not counted), `long_peak` 2 months (special),
  `late_days` 7 (special), `late_days_block` 20 (block). "Late" = calendar days from Actual Peak From
  to `create_date` in VN time (`_peak_days_late`).
- Shared feature: live banner while editing; checked again and frozen at submit into `special_case` /
  `special_reasons`; blocked refuses submit (draft save allowed). `proceed_flow_type` /
  `proceed_flow_message` are non-stored aliases kept for old approval-rule conditions.
- Approved → `_generate_hr_attendance_rules` creates and submits an `hr.attendance.rule`
  (by employee, OT 90/40) and sets state `synced`. Reset to draft cancels that rule.
- KOM reminder: cron `ir_cron_peak_time_kom_reminder` → `cron_send_kom_peak_reminders()`. Emails the
  job PM (`user_id`) once when KOM Peak From is within `reminder_days` (14), job is big and not
  done/close/cancel, and has no non-rejected request. `kderp.job.lookup.peak_time_reminder_sent_for`
  stops repeats (changed KOM date sends again). Respects `kderp_e_approval.global_notify_email`.

## Decisions (BOD review 15 Oct, Thanh 20 Oct)
- Old "5 working days after KOM date" rule dropped; lateness counts from Actual Peak From.
- Registration count: 2nd and later is special; rejected requests don't count (also for the reminder).
- Reminder: once per KOM date, email only, PM only.
- Rules editable by HR (peak time manager group), changes tracked.
- Comments and extra approvers for special requests come from approval rules (tier definitions),
  not from code.

## Pitfalls
- `proceed_flow_*` are not stored: never use them in searches or domains; use `special_case`.
- `tracking=True` on fields does nothing in Odoo 12 (`track_visibility='onchange'` does).
- `kderp.job.lookup` PM is overwritten by every remote sync; set it by hand only right before a demo.
- Dev peak time numbers are out of order (0001–0006 between 0131 and 0132): test data, leave them.

## Staff transfer
Spec and open business decisions: `staff_transfer_request.md`. The request itself (approval steps,
menus, security) is not reworked yet; the allowance part is done.

### How it works
- Allowance database (reference only, monthly, VND; source = table on paper form CR04-03-F01):
  `transfer.allowance.grade` (G01–G14, `category_id` = the employee tag HR uses),
  `transfer.allowance.band` (S01–S08, S21, SS11, SS12 project; T01 ×2 training 1–6 / >6 months;
  km from/to inclusive, months "over"/"up to", 0 = no limit),
  `transfer.allowance.matrix` (grade × band × `date_from` → `amount`; `date_to` set by code from the next
  version). All in `models/staff_transfer/transfer_allowance_matrix.py`. No line = not entitled.
- Grade comes from employee tags (`hr.employee.category_ids`), HR's existing practice:
  `hr.employee.transfer_allowance_grade_id` (computed, not stored) and `get_transfer_allowance(band, date)`
  in `models/staff_transfer/hr_employee_allowance.py`. Tag "G8" means G01–G08 and is linked to grade G08.
  `_link_employee_tags()` links grades to existing tags named Gn/G0n (never creates tags).
- Rendering: `_matrix_layout()` (shared; merges consecutive grades with identical amounts, e.g. G01-G08),
  `render_matrix_html()` → `staff.transfer.allowance_matrix_html` on the form (Transfer Details tab),
  `render_matrix_png()` → printed report. Rates valid on `transfer_from_date` (else today).
- Print: button "Print Secure Form" (approved only) → `action_report_staff_transfer_py3o`,
  data `_prepare_staff_transfer_report_data()`, template `reports/staff_transfer.odt`
  (built by `reports/tools/build_staff_transfer_odt.py`; can be edited by hand in LibreOffice).
- Lookup API (unused so far): `find_band(type, km, months)`, `get_rate(grade, band, date)`,
  `get_amount(...)`, `months_between()` on `transfer.allowance.matrix`.
- Access: everyone reads the allowance tables (form/report render with sudo); edit = `hr.group_hr_manager`
  and `kderp_hr.group_kderp_hr_admin`. HR menu: Employees › Configuration › Transfer Allowances.
- Seed data `data/transfer_allowance_data.xml` is noupdate (HR edits survive upgrades); its `<function>`
  only runs on install, so upgrades link tags in `migrations/12.0.1.1.0/post-migrate.py`.

### Decisions (Thanh, 15 Oct 2026)
- Amounts stored in full VND per month (form says 1,000 VND); displayed in 1,000 VND like the paper.
- The matrix is reference information (staff/HR see which allowance payroll applies): no distance or S code
  input, no current/new allowance on the request. Thanh will integrate S code / allowance into the employee data.
- Shown on the form and on the printed report; everyone may read it.
- Rate change = new line with a later Effective From (history kept), not an edit.

### Pitfalls
- Old matrix (selection fields) was moved to table `transfer_allowance_matrix_v0` by the 12.0.1.1.0
  pre-migration; never reuse that table.
- PNG drawing must work on old Pillow (Odoo 12 server): no `rectangle(width=)`, use `draw.line`;
  `draw.textlength` may not exist, fall back to `textsize`. Fonts DejaVu Sans (Condensed); without them
  Pillow's tiny default font is used.
- T01 has two band rows with the same code: `get_rate(grade, 'T01')` raises "ambiguous", pass the record.



### Several staff per request, notification, distance (ported from Odoo 12 12.0.1.7.0, here 19.0.0.2.0)
- `transfer_employee_ids` (Many2many to `hr.employee.public`, table `staff_transfer_employee_rel`; a plain SM/PM cannot read `hr.employee` and a
  Many2many write checks read access on the comodel) replaces `transfer_employee_id`. Private fields (department / project history, work location,
  allowance grade, user) are read through `_staff()` (sudo, `hr.employee`). Current area / section / project are computed Many2many
  (`current_*_ids`), the "before" project is frozen at approval in `current_project_frozen_ids` (old approved rows: their manual value).
  Report fields `staff_code`, `staff_name`, `grade`, `src_*` are joined strings; `staff_list` is also in the data.
- Migration `migrations/19.0.0.2.0/post-multi_staff.py`: copies the staff into the relation, freezes the project of approved rows, drops the old
  NOT NULL column and rewrites the (noupdate) tier expressions to `rec.transfer_employee_ids.mapped(...)`. Safe to run twice.
- The legacy import accepts both Odoo 12 shapes (column `transfer_employee_id` before 12.0.1.7.0, relation table after) and never calls the map
  service (context `skip_distance`).
- After approval: project history for every staff, then `_notify_transferred_staff()` (email from `work_email`, Talk if that is the user's choice;
  follows the e-approval global switches; result in the chatter, names escaped: `Markup % value`).
- Distance by car: `kderp.job.lookup.project_address` (kdvn_remote_sync) -> `transfer.route.distance` (cache 90 days, failures 1 hour; provider and
  Goong key are System Parameters `kderp_hr_procedures.route_provider` / `goong_api_key`, set on the E-Approval settings screen, defined in
  `kdvn_e_approval`). One distance per office: staff `work_location` containing "PHONG" -> Hai Phong office (company address with City = Hai Phong,
  tab "Office Addresses" on the company form; else parameter `office_address_hp`), else Head Office = company address. Calculated on save of a
  draft, on Submit and by "Recalculate"; never blocks. After submit a found distance never changes; Recalculate is shown only while one is missing.
  The writes use `skip_validation_check` (OCA refuses other writes while the request is under validation). Setup: `docs/route-distance-setup.md`.
- Tests never touch the internet: `requests.get` / `_fetch` are mocked.
