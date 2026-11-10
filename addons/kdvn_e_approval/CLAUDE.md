# kderp_e_approval (Odoo 12)

Shared approval engine. `kderp.e.approval.mixin` (with `.e.`) inherits OCA `tier.validation`
(`extra-addons/base_tier_validation`, 12.0.3.9.3). Procedures inherit it: `entertainment.request`
(`kderp_entertainment_procedures`, the reference), `staff.transfer` and `kderp.project.peak.time`
(`kderp_hr_procedures`). Home screen on top of it: `kderp_dashboard`.
Facts for adding a procedure: `ai_prompts/platform_contract.md` (checked 14 Oct, predates special cases;
if it disagrees with the code, the code wins). Template: `ai_prompts/new_procedure_template.md`.
Status and next steps: `../../docs/progress-e-approval.md`.

## Rules
- Attendance approvals (OT, working time, leave) stay on the attendance state machine, NOT tier validation
  (about 5,000 requests a month). Do not move them here.
- Approval steps are data (E-Approval › Configuration › Approval Rules). Comments for a step come from the
  rule's Comment tick (`has_comment`), not from code.
- Never reuse an xml id from another file. Procedures never re-implement what the mixin gives.

## How it works
- `name`: numbered in `create()` from the `ir.sequence` whose code = the model `_name` (default "New").
- `employee_id` (Applicant): read-only, always the creator's employee (`_default_applicant`, set in create;
  error if the user has no employee). `reason`; `attachment_ids` (M2M, `_adopt_attachments`).
- States: `_state_from=['submitted']`, `_state_to=['approved']`, `_cancel_state='rejected'`.
- `action_submit` → `_special_case_freeze` → state submitted → `request_validation` → notify first step.
  `_validate_tier` auto-approves consecutive steps whose sole reviewer is the same person, then notifies.
- Notifications: `_notify_reviewers`, `_notify_applicant`; look in `models/approval_notify_render.py`
  (pure functions, shared blocks). User choice `res.users.approval_notify_type` = email / Talk / both;
  Talk is instant, email is a daily digest (cron). Special cases show as a SPECIAL pill and a Talk line.
- Links: HMAC short links `<review>-<user>-<a|r>-<sig>` → n8n "E-Approval Decision Center" →
  `POST /api/v1/mobile_review_action` (`controllers/main.py`). Opening a link never approves (confirmation
  page). Steps whose rule has Comment need a comment (status `comment_required`); success is reported only
  when the review really changed; reject and already-decided answers carry the request summary.
  QR verification page: `/api/v1/verify_approval` (read as superuser, details hidden on a bad token).
- Since 19.0.0.2.7 (mirror of Odoo 12 12.0.2.7.0) Odoo serves the Decision Center itself: setting "Approve/Reject pages in
  Odoo" (`kderp_e_approval.decision_in_odoo`) makes links `<web.base.url>/ea/<code>` (`controllers/main.py`
  `decision_center`, `views/decision_templates.xml`, shared logic `_review_action`). GET shows the page, POST decides; the
  signed code is the credential (csrf=False on purpose). Both routes are `readonly=False`: in Odoo 19 `auth='none'` routes
  get a read-only cursor by default. Archived users are refused; unexpected errors show a generic text (detail in the log).
  Tests: `kdvn_entertainment_procedures/tests/test_decision_center.py`.
- n8n workflows are kept with the code (legacy while the setting is off): `n8n/` (dev, HN production, `README.md`). One workflow per site;
  its "Site settings" node holds the Odoo URL.

### Special cases (shared feature)
- Model `kderp.e.approval.special.rule` (`models/special_rule.py`): procedure, code, limit `value` + unit,
  action special / block / off, `manager_group_id` = who may edit it. Menu E-Approval Portal › Special Case Rules.
- Procedure implements `_get_special_case_reasons()` → `[(action, text)]` using `self._special_rule(code)`
  (`.is_on()`, `.value`, `.action`) and `_special_case_depends()`.
- Stored `special_case` / `special_reasons` are frozen at each submit, before `request_validation`, so approval-rule
  conditions can use `rec.special_case == 'special'`. Blocked = submit refused (draft save allowed).
  `special_case_banner` is live for drafts. `_special_case_explain_field` = field the applicant must fill
  when the request is special.
- Decision: option B. Checks in code, limits and actions editable by data; one editor group per procedure;
  approver comments via approval rules, not forced by the feature.

### Refusal log (12.0.2.5.0): the refusal comment stays after the reset to draft
- Problem: the comment of a refusal lives in `tier.review.comment`, and the reviews are deleted INSIDE the OCA `write()` as soon as the state goes to a `_state_from` state (draft), so `refuse_comments` (computed from the reviews)
  went empty at the reset. The chatter always kept "A review was rejected by X. (comment)" (OCA `_notify_rejected_review`), but nothing on the form did.
- Model `kderp.approval.refusal` (generic: `res_model` + `res_id`, no foreign key): who refused, when, step, comment, then `state` refused/reset, who reset, when, to which state. Written only by the mixin (sudo); ACL: E-Approval admin
  read + delete, nobody else. Menu E-Approval > Configuration > Refusal History (list, filters Still refused / Reset, group by procedure / person, button to open the request).
- Mixin: `_rejected_tier` logs the refused reviews (`_refusal_log`, once per review id). `write()` runs `_refusal_mark_reset` BEFORE `super().write()` when a refused request is written to a `_state_from` state (so every path is
  covered, `action_reset_to_draft` included): completes the rows and posts ONE short chatter line "Reset to <Draft> from <Rejected>. Refused by <name>: "<comment>"". A refusal made before the log existed is captured at that moment from
  the reviews still present. `action_reset_to_draft` keeps the generic "unlocked and reset" line only for a request that was NOT refused. `unlink` deletes the rows.
- Ribbon: `_refusal_ribbon_note` adds an amber note ("Refused earlier" + comment + who refused / who reset and when, "(+N more)" when there are older ones) under the ribbon of every procedure, as long as the request is not approved and
  not refused right now. No view change in the procedures. Style `.o_kderp_flow_note--history` in `approval_ribbon.scss`.
- Old refusals (made before the log existed) are rebuilt from the chatter: `kderp.approval.refusal.backfill_from_chatter(dry_run=True, records=None)`, menus E-Approval > Configuration > "Import old refusals (preview)" and
  "(apply)" (admins; preview first, both safe to repeat). It reads "A review was rejected by <name>. (<comment>)" (the comment is the text in the last brackets, newlines kept), takes who/when of the reset from the next
  "unlocked and reset to Draft" message, marks the last refusal of a request that is refused now as "still refused", and never doubles a refusal that is already logged (same person within 3 minutes of an exact row, or the
  same message id: `review_id` = -message id). A refusal with no reset message gives "Reset to Draft." with no invented who/when. `refused_by_name` keeps the name when the user cannot be found. Dev att18mar: 10 added + 2 live = 12 rows.
  The import is NOT run by a migration: run it once per database from the menu after the upgrade (HN).
- Not done: the E-Approval guide does not mention the note and the new menus yet (guides worktree, `tools/stale.py`).
- Tests (reference procedure, `kderp_entertainment_procedures/tests/test_refusal_log.py`, 18 with the import): log at refusal, survives the reset and is shown, escaping, note gone when approved, history of two refusals, reset of a non-refused request logs nothing,
  legacy refusal captured at reset, logged once, delete cascade, only admins read the list.

## Pitfalls
- OCA `validate_tier` returns the comment wizard for `has_comment` steps and does NOT approve: every caller
  (link controller, dashboard) must handle that. The old controller reported a false success.
- `tier.review` links to records by `model` / `res_id` (not `res_model`).
- Approve links never act on GET. Escape user text (`html_escape`). `role="presentation"` on icons.
- Not in the code (old prompts mention them): `kderp.approval.mixin`, `matrix_reviewer_ids`,
  `bypass_validation_check`, `formatted_records` (key is `formatted_data`).
- Odoo core source is not on the PC (inside a container): use github.com/odoo/odoo branch 12.0.
- Secrets in the settings page (signing key `e_approval_secret_key`, Nextcloud `nc_bot_password`): `get_values` returns '' (never the saved value, `widget="password"` alone only masks the box),
  a status text says whether one is saved, `set_values` writes only when a new value is typed (empty = keep). They are still stored in plain text in `ir.config_parameter`
  (System Parameters, Administrators in debug mode). Same pattern as the remote password in `kderp_remote_sync`. Tests: `tests/test_settings_secrets.py`.
  To clear one on purpose use Settings > Technical > System Parameters.
