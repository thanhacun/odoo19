# New e-approval procedure: request template

How to use: copy this file, fill in sections 1–9 (leave a section empty or write "none" if it doesn't apply),
and give it to the assistant together with access to the `addons` folder. Keep the "Instructions" part unchanged.

---

## Instructions to the assistant (keep as is)

Before writing code:
1. Read `kderp_e_approval/ai_prompts/platform_contract.md`.
2. Read the mixin `kderp_e_approval/models/kderp_approval_mixin.py` (class attributes and fields at the top).
3. Read the reference module `kderp_entertainment_procedures` (model, views, menu, security, sequence, report) and copy its structure and naming.
4. Check every model, field, group and menu id you plan to use actually exists. Don't invent ids.
5. Reply first with: open questions, anything in my spec that contradicts the code, and the list of files you will create or change. Wait for my answer.

When writing code:
- Reuse the mixin. Don't re-implement anything listed under "What you get for free".
- Odoo 12 API, Python 3.6 compatible. Complete files, not fragments.
- Use the mixin's `reason` field for the main purpose text; don't add a second reason field.
- `get_approval_digest_details` must escape user text and always return a string.
- Finish with the "Done checklist" from the contract, filled in for this procedure, and the approval rules I need to create in the UI.

---

## 1. Basics
- Procedure title (`_approval_procedure_title`):
- Model `_name`:
- Module: (existing module to add it to, e.g. `kderp_hr_procedures`, or new module name)
- Category (`_approval_category`): entertainment / attendance / hr / procurement / it / finance / other
- Number prefix (4 digits follow): e.g. `ST-%(year)s-`
- Who creates requests:
- Applicant rules (e.g. "applicant must be a Section Manager"):

## 2. Fields specific to this procedure
(Don't list name, reason, employee_id, attachments, state, emergency: the mixin has them.)

| Field | Type | Label | Required | Editable when | Details (relation / selection values / default / compute / domain) |
|---|---|---|---|---|---|
|  |  |  |  | draft only |  |

## 3. Business rules
- Validations (raise an error when …):
- Computed values / onchange behaviour:
- Fields reviewers may still edit during review (`_allow_to_write_field_list`):

## 4. Approval steps (I will create them in Approval Rules; needed for tests)
| # | Frontend name (users see) | Description `[CODE] …` (admins see) | Reviewer: user / group / field / python | Only when (condition) |
|---|---|---|---|---|
| 1 |  |  |  |  |

## 5. Notification summary
Lines to show in emails and Talk (`get_approval_digest_details`), e.g. `Staff`, `New section`, `From date`:
-

## 6. Security
- Applicant sees: own requests
- Reviewers see: requests they review
- Read-all: E-Approval global auditor
- Extra group (e.g. HR manager, read/edit all)?:

## 7. Menus
- Category sub-menu name (under My Requests / My Reviews), e.g. "Human Resources":
- Request menu name:
- Review menu name:

## 8. Printed report (optional)
- Report needed? yes / no
- Fields on the PDF and their format (dates `dd - MMM - YYYY`, money `VND 2.500.000`, …):
- Signatures / QR code needed?:

## 9. After approval (optional)
- Anything to create or update automatically when approved (e.g. expense sheet, employee history):
- Guards on reset to draft (e.g. block if a linked document exists):
