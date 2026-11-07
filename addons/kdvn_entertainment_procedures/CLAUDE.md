# kderp_entertainment_procedures (Odoo 12)

Entertainment fee requests (`entertainment.request`, prefix EF-YYYY-) on `kderp.e.approval.mixin`.
**Reference procedure**: copy its pattern for new ones (see `kderp_e_approval/CLAUDE.md` and
`kderp_e_approval/ai_prompts/`). Status: `../../docs/progress-e-approval.md`.

## Decisions
- Late registration is a special case, warning only (no block): rules `late_input` (input date > entertainment
  date) and `backdated_input` (input date < creation date), limit 0, in `data/entertainment_special_rules.xml`.
  Editor group `group_entertainment_request_functional_manager`.
- Japanese GM: late requests need a reason; client + attendees are otherwise enough. So `reason` is labelled
  "Purpose", optional, required only for special cases (`_special_case_explain_field`).
- No Duplicate on the form (`duplicate="false"`): production drafts like EF-2026-0029 were manual Duplicates.
- Approved report: redesigned with signature strip (`reports/entertainment_approved.odt`, builder in `reports/tools/`).
- Budget cache (`kderp_remote_sync`) is keyed by (job, budget_code): codes repeat across jobs.

## Advance request on the remote server (12.0.2.5.0)
- Button "Create Advanced Request" (approved, applicant or admin groups) opens wizard `entertainment.advance.wizard` (wizard/advance_wizard.py). Logic: `models/remote_advance.py` (prepare/create/store)
  and `models/remote_candidates.py` (who can continue the process).
- **Input user = who continues the process on the remote** (`user_input`; remote rule `user_input.user_id = me`). Real data (Nov 2026): the input user, not the applicant, creates the advance (116 of 117);
  only 13% of the jobs have a Site Admin list and even then the input user is one of them in 74%. So the dialog SUGGESTS, in this order, each with its reason and team: (1) the job's site admins (all),
  (2) people who entered earlier advances on THIS job (all-time count), (3) people who usually enter THIS applicant's advances (last 365 days), (4) only if fewer than 3 people so far: the job PM's usual
  input users, then the applicant's office's. Up to 6 rows (job admins are never cut). The first person who can process it is preselected (star); the applicant can pick another. Back-test (2025-2026,
  jobs without site admin): first pick right 82-87%, 95% inside the top 3. A job without site admin is NOT an error: an info banner asks to add a site admin on the job (remote: Job > Site Admin tab).
  Only when nobody at all is found (or nobody can process) is it blocked with a message.
- Eligible = active + employee + location with a code letter (not 'all': "Global" stays out until decided) + remote group "User Input" (`kderp_advance_payment.group_kderp_advance_management_menu_user_input`).
  NO other group is required (decided 6 Nov): the people come from the job's own list or from history, so they are proven input users. Real mix of input users since 2025: team + site admin 301 advances,
  "Manage a Location" only (Hai Phong) 178, Advance Cash Admin/Submit (e.g. General Affair) 81, site admin only 23 - a group rule would have rejected 44%. The list shows a "Remote role" column
  (Team ..., Site admin, Manage a Location, Advance Cash Admin/Submit) for information only.
- Temporary note "How these people were suggested" (field `how` of the wizard, `_build_how`): for the discussion; it lists what was read for THIS request (admins, job history, applicant history, PM/office or why
  they were not read), the order and the eligibility rule, and the back-test figures. Remove it (field, view line, `_build_how`) when the discussion is over.
- Remote reads (all reads): job, `read_group` of advances by `user_input` (job, applicant, PM, office), employees, users, `kderp.base.code`, groups (about 10 calls, no change to the job cache or n8n). All remote calls use the Writer login and the 'advance' live switch of `kderp_remote_integration` (Settings > Remote Server Connection).
  The integration user needs the remote group "KDERP - Advance Cash / Admin" (implies Submit > User Input; sees all advances). A read-only user sees almost no history, so it only gets the job's admins.
- Preview shows the values and "Why this person"; "Create" needs the 'Advance requests' live switch of kderp_remote_integration (otherwise a dry-run message, nothing written).
- Remote draft `kderp.advance.payment`: user_id = applicant (remote employee found by staff code), user_input = chosen person's employee, location_id = her office,
  code = remote sequence `code_next` read right before create (office letter of the input user, last 4 of applicant code), retried once if taken; one line with the amount (`estimated_amount`, VND).
  Notes and the line start with `Entertainment fee <EF number> - ` (no ref field exists on the remote; the same text is the duplicate lookup: an existing advance is linked, never created twice).
  The accountants' extra 0-amount line "<job> Code 4082" (32% of the advances; looks like the entertainment budget code) is NOT created: decided later.
- Stored on the request: `remote_advance_id`, `remote_advance_code`, `remote_advance_admin` (allowed to write when approved), shown on the form; the button hides once set. The chatter says who continues
  it, her team, and why she was chosen.
- Tests: `tests/test_remote_advance.py` (fake remote, 23 tests). Run: `odoo -d att18mar --test-file=/home/odoo/project/addons/kderp_entertainment_procedures/tests/test_remote_advance.py --stop-after-init --http-port=12099`.
- NOT yet done against the real remote: the first real create (integration user in the remote Admin group + live switch ON). Real reads were checked on dev with `info_writer` (dry run, rolled back).
  Replace the e-approval number into a proper remote field once the remote has one.

## Deploy notes
- Versions below 12.0.2.0.0 also run the renumber migration
  (`migrations/12.0.2.0.0/post-renumber_entertainment_requests.py`). Current version 12.0.2.5.0.
- Skipped request numbers were fixed earlier (`ab1e2778`, `52472abd`): sequence code = model name.
