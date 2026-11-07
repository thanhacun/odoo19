# Staff Movement / Transfer — request spec (`staff.transfer`)

Filled-in `kderp_e_approval/ai_prompts/new_procedure_template.md`. Items marked **(decide)** need an
answer from the business (Thanh). Synced from the Cowork project doc on 28 Oct 2026; status lives in
`../../docs/progress-staff-transfer.md`.

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

**This is a rework of an existing model** (`staff.transfer` in `kderp_hr_procedures`): keep the model name, table and existing records; fix what doesn't match this spec.

---

## 1. Basics
- Procedure title (`_approval_procedure_title`): Staff Movement / Transfer Request (code still says "Staff Tranfer Request")
- Model `_name`: `staff.transfer`
- Module: `kderp_hr_procedures` (existing)
- Category (`_approval_category`): hr
- Number prefix (4 digits follow): `ST-%(year)s-` (sequence `seq_staff_transfer`)
- Who creates requests: Section Managers (SM), for a staff member of their section.
- Applicant rules: the applicant (`employee_id`) must be a Section Manager (group `kderp_hr_attendance.group_hr_attendance_section_manager`) **(decide: block submit, or only hide the menu?)**
- Paper form being replaced: CR04-03-F01 "Request of approval for personnel transfer".

## 2. Fields specific to this procedure
| Field | Type | Label | Required | Editable when | Details |
|---|---|---|---|---|---|
| `transfer_employee_id` | Many2one `hr.employee` | Transfer Employee | yes | draft only | tracked |
| `transfer_area_id` | Many2one `hr.department` | New Area | no* | draft only | domain `[('type_id.code', '=', 'area')]` |
| `transfer_department_id` | Many2one `hr.department` | New Section | no* | draft only | domain: not an area `[('type_id.code', '!=', 'area')]` |
| `transfer_project_id` | Many2one `kderp.job.lookup` | New Project | no* | draft only | |
| `transfer_from_date` | Date | Transfer From | yes | draft only | |
| `transfer_to_date` | Date | Transfer To | yes | draft only | must be ≥ From |
| `petrol_allowance` | Boolean | Petrol Allowance | no | draft only | default False |
| `current_area_id` | Many2one `hr.department` | Current Area | – | read-only | computed (see 3) |
| `current_department_id` | Many2one `hr.department` | Current Section | – | read-only | computed (see 3) |
| `current_project_id` | Many2one `kderp.job.lookup` | Current Project | – | read-only | computed (see 3) |
| `allowance_matrix_html` | Html, computed | Transfer Allowance Matrix | – | read-only | DONE: reference matrix on the form, employee's grade row highlighted |

\* At least one of New Area / New Section / New Project is required.
The transfer reason uses the mixin's `reason` field (label "Reason of Transfer", multi-line in the form).
Decided 15 Oct 2026: no allowance / distance / S code input on the request, no current-vs-new allowance;
the matrix is shown (form and print) for reference only.

## 3. Business rules
- Validations:
  - At least one destination (area, section or project).
  - `transfer_to_date` ≥ `transfer_from_date` (as a constraint, not only on submit).
- Computed values: current area/section/project of `transfer_employee_id` on `transfer_from_date`:
  - section: latest `department_history_ids` line with `effective_date` ≤ From date, else the employee's current department; area = that section's `area_id`;
  - project: latest `project_history_ids` line with `effective_date` ≤ From date → `project_code`, else empty.
- Fields reviewers may still edit during review: none.

## 4. Approval steps (I will create them in Approval Rules)
| # | Frontend name | Description | Reviewer | Only when |
|---|---|---|---|---|
| 1 | New GM Approval | [ST] 1 New GM | python: `rec.employee_id.parent_id.user_id` (manager of the applicant SM) | always |
| 2 | Current SM Approval | [ST] 2 Current SM | python: `rec.transfer_employee_id.department_id.manager_id.user_id` | always |
| 3 | Current GM Approval | [ST] 3 Current GM | python: `rec.transfer_employee_id.department_id.manager_id.parent_id.user_id` | always |
| 4 | HR Manager Approval | [ST] 4 HR Manager | group: HR manager **(decide which group)** | always |
| 5 | Admin GM Approval | [ST] 5 Admin GM | specific user **(decide)** | always |
| 6 | Construction GM Approval | [ST] 6 Construction GM | specific user **(decide)** | **(decide: always, or only when a project is set?)** |

(Steps 1–3 need "Python expression" reviewers because the related records are employees, not users.)
Paper signature boxes: PM/SM (New), GM/AM (New), PM/SM (Current), GM/AM (Current), HRM, SGM-Admin Dept., SGM-Const. Dept.

## 5. Notification summary
- Staff: transfer employee name
- From: current section / project
- To: new area / section / project (whichever is set)
- Period: From – To date
- Petrol allowance: Yes/No

## 6. Security
- Applicant sees: own requests.
- Reviewers see: requests they review (not drafts).
- Read-all: E-Approval global auditor.
- Extra group: HR manager can read all **(decide: edit too?)**.

## 7. Menus
- Category sub-menu: "Human Resources & Transfers" (exists: `menu_cat_req_hr`, `menu_cat_rev_hr`)
- Request menu: Staff Movements
- Review menu: Staff Transfer Validation (opens with the "To Approve" filter)
- Master audit: Master Audit Tracking (Transfers)
- Visible to: everyone with the right access **(currently admin only — decide)**

## 8. Printed report — DONE (see CLAUDE.md "Staff transfer")
- py3o PDF, layout of paper CR04-03-F01 incl. the allowance matrix, signature strip, QR code.
- Not printed: main office, site commute S code current → new (decided not needed).

## 9. After approval
- Nothing automatic yet. Later: create department/project history lines for the employee on the From date **(decide)**.
- Reset to draft: admin only; old reviews must be cleared (mixin + OCA already do this).
