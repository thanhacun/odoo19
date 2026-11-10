# E-Approval platform contract (`kderp_e_approval`)

Reference for anyone (or any AI assistant) adding a new approval procedure.
Checked against the code on 14 Oct 2026. **If this file and the code disagree, the code wins**: say so, and update this file.

## Environment
- Odoo 12 Community. Code must run on Python 3.6 (f-strings are fine; no walrus, no 3.7+ features).
- OCA `base_tier_validation` 12.0 (+ `_formula`) used from `~/odoo12/extra-addons` (read-only, like every third-party module).
- **Only change code in `~/odoo12/addons`.** Override third-party behaviour from our modules (`_inherit`, view inheritance, JS `include`, QWeb `t-extend` or new templates).
- Py3o reports (LibreOffice `.odt` → PDF).
- The approve/reject links open Odoo pages `/ea/<code>` (setting "Approve/Reject pages in Odoo"; legacy: n8n "E-Approval Decision Center"); Nextcloud Talk + email for notifications.

## How a procedure plugs in
```python
class StaffTransfer(models.Model):
    _name = 'staff.transfer'
    _inherit = ['mail.thread', 'kderp.e.approval.mixin']   # note the ".e."
    _description = 'Staff Transfer Request'

    _approval_category = 'hr'                               # key of _APPROVAL_CATEGORY_MAP
    _approval_procedure_title = 'Staff Movement / Transfer Request'
```
Nothing else is needed to register the model: `tier.definition` finds every model that has `_universal_state_changer` (a mixin method) and offers it in the approval rules.

## What you get for free (do not re-implement)
**Fields**
| Field | Notes |
|---|---|
| `name` | Request number. Default "New"; the real number is taken in `create()` from the `ir.sequence` whose **code = the model's `_name`**. |
| `reason` | Char, required, editable in draft. Use it as the main purpose field (don't add a second "reason"). |
| `employee_id` | Applicant (`hr.employee`), defaults to the current user's employee. |
| `attachment_ids` | Many2many to `ir.attachment` (own table per model); uploaded files are attached to the record automatically. |
| `state` | `draft` / `submitted` / `approved` / `rejected`. |
| `is_emergency` | Urgent flag: urgent styling in notifications. |
| `approval_progress` | Stored text ("2/3", "Rejected") for list views. |
| `approval_workflow_ribbon` | HTML progress ribbon for the form. |
| `validate_comments`, `refuse_comments` | Reviewer comments, collected. |
| `verification_url`, `verification_token` | Signed URL for the QR code on printed reports. |
| OCA fields | `review_ids`, `can_review`, `validated`, `rejected`, `need_validation`. |

**Behaviour**
- `action_submit` → creates review lines (from the approval rules) and notifies the first step.
- `validate_tier` / `reject_tier` (reject always asks for a comment).
- If the next step's only reviewer is the person who just approved, that step is approved automatically.
- State changes to approved/rejected; the applicant is told the result.
- Notifications: email and/or Talk per user preference, daily digest cron, approve/reject links through n8n (short links, confirmation page).
- `action_reset_to_draft` (E-Approval admins + `_admin_groups`).
- Printing: `action_print_secure_authenticated_report` (only when approved). It reads `target_report_xml_id` and `report_format_method` from the button context, calls that method, and passes `data['formatted_data'] = [<your dict>]` to the report.
- Report helpers: `get_py3o_qr_base64()`, `get_py3o_barcode_base64()`, `_prepare_reviews_signatures()` (returns `signature_blocks` list + `signature_strip_png`).

## Class attributes you may override
| Attribute | Default | Meaning |
|---|---|---|
| `_approval_category` | `'other'` | One of `entertainment`, `attendance`, `hr`, `procurement`, `it`, `finance`, `other`. |
| `_approval_procedure_title` | `'Other Request'` | Shown in emails, Talk and the confirmation page. |
| `_state_from` / `_state_to` / `_cancel_state` | `['submitted']` / `['approved']` / `'rejected'` | Only change if you add states. |
| `_allow_to_write_field_list` | (merged with the mixin's list) | Extra fields reviewers may edit while the request is under review. |
| `_default_approval_report_xml_id` | `False` | Fallback report for the print button. |
| `_admin_groups` | `[]` | Extra groups (xml ids) allowed to reset to draft. |

## Methods to override
- `get_approval_digest_details(self)` → short HTML for emails/Talk, one item per line:
  ```python
  def get_approval_digest_details(self):
      self.ensure_one()
      return '<strong>Staff:</strong> %s<br/><strong>Effective:</strong> %s' % (
          html_escape(', '.join(self.transfer_employee_ids.mapped('name'))), self.transfer_from_date or '')
  ```
  Always `html_escape` user text. Always return a string.
- `<prepare_xxx_report_data>(self)` → flat dict of strings for the Py3o template (name it in the print button context).
- `pre_reset_to_draft_cleanup(self)` → clear your own fields when an admin resets (call `super()`).
- `action_reset_to_draft(self)` → only to add guards (call `super()`).

## Files a procedure needs (copy the pattern of `kderp_entertainment_procedures`)
| File | Content |
|---|---|
| `__manifest__.py` | `depends`: `kderp_e_approval` (+ modules providing your lookup models). |
| `data/ir_sequence_data.xml` | `ir.sequence` with **`code` = model `_name`**, prefix like `ST-%(year)s-`, padding 4. |
| `security/ir.model.access.csv` | Access for `base.group_user` (+ any functional group). |
| `security/<model>_security.xml` | Record rules: own records `[('create_uid', '=', user.id)]`; reviewers `[('review_ids', 'in', user.review_ids.ids)]`; NO rule for the E-Approval Administrator / Read-Only Auditor: `kdvn_e_approval` (`models/ir_rule.py`) gives them all requests of every model on the mixin automatically (also the menus of a new module must list both groups); optional functional manager group in category `kderp_e_approval.module_category_kderp_e_approval`. |
| `views/<model>_views.xml` | Form, tree, search (see below). |
| `views/<model>_menu.xml` | Menus under `kderp_e_approval.menu_sub_my_requests`, `kderp_e_approval.menu_sub_my_reviews`, `kderp_e_approval.menu_sub_cat_master_audit`. |
| `reports/…` (optional) | `ir.actions.report` with `report_type` `py3o` + `.odt` template. |

**Form view must contain**
- Header buttons: `action_submit` (normal + emergency variant), `validate_tier` and `reject_tier` with `attrs="{'invisible': [('can_review', '=', False)]}"`, `action_reset_to_draft` (group `kderp_e_approval.group_e_approval_admin`), the print button; hidden fields `need_validation`, `can_review`, `validated`, `is_current_applicant`, `is_emergency`.
- Ribbon: `<field name="approval_workflow_ribbon" widget="html" readonly="1" nolabel="1"/>`.
- Reviews panel, after the sheet, before the chatter:
  `<field name="review_ids" widget="tier_validation" attrs="{'invisible': [('review_ids', '=', [])]}"/>`.

**Tree/search**: show `approval_progress`; search filter "To Approve" `[('can_review', '=', True), ('state', '=', 'submitted')]`; the reviews menu action uses `{'search_default_filter_to_approve': 1}`.

**Approval steps are data, not code**: E-Approval → Configuration → Approval Rules. Per step: model, sequence, reviewer (user / group / field / python expression), **Frontend Step Display Name** (shown to users), description `[CODE] …` (admins only), procedure tag.

## Rules and pitfalls
- In XML client domains/contexts use `uid`; `user.id` only in `ir.rule`.
- Icons: never `aria-hidden="true"` (a global CSS rule in this database hides them); use `role="presentation"`.
- Escape user text that goes into HTML (`from odoo.tools import html_escape`).
- `_origin` only exists on onchange records in Odoo 12; `NewId` is falsy.
- Data migrations: `migrations/<new version>/pre-*.py` (before models load, SQL only) or `post-*.py` (ORM available); raise the module version.

## Not in the code (old prompts mention these; don't use them)
`kderp.approval.mixin` (wrong name) · `matrix_reviewer_ids` field · `fields_view_get` injection of the review tab · `bypass_validation_check` context · `_universal_state_changer = True` attribute · `formatted_records` (the key is `formatted_data`) · menu parent `kderp_web_infrastructure.kderp_e_approval_operations_category` · creating the sequence number in your own `create()`.

## Done checklist for a new procedure
1. Module installs/upgrades without errors.
2. A new request gets a number like `ST-2026-0001` on save (not on opening the form).
3. Approval rules exist for the model; Submit creates the expected steps; the ribbon shows them.
4. First approver gets a notification (email or Talk) with correct details; approve via link shows the confirmation page.
5. Approve all steps → state approved, applicant notified; print button works.
6. Reject with comment → state rejected, applicant sees the reason.
7. Admin reset to draft → resubmit works.
8. Record rules: applicant sees own, reviewer sees assigned, auditor sees all read-only.
