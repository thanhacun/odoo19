kdvn_remote_sync — module spec and decisions

This is the Odoo 19 version of the Odoo 12 module kderp_remote_sync. It currently mirrors Odoo 12 version 12.0.1.2.1.

The Odoo 12 module is on Thanh's machine at ~/odoo12/addons/kderp_remote_sync. That folder is reference only: never change it.
When Thanh changes the Odoo 12 module, mirror the change here.

Repo: addons/kdvn_remote_sync, version 19.0.1.2.0. Detailed notes: design/kdvn_remote_sync/README.md.

Purpose
n8n reads active jobs (state doing/done), budgets and customers on the KDERP (Odoo 12) server and posts them to POST /api/v1/sync_jobs on Odoo 19.
They are kept in cache models that future Odoo 19 business modules can link to (requests, approvals, ...).
Not for the website (Thanh, 2026-10-20). Closed jobs must not be added to this sync, because that would change its purpose. The website's Past Prominent Projects (kdvn_website_project) gets finished big jobs from its own n8n workflow (POST /api/v1/website_projects) and has no link to this module.
Decisions (Thanh, 2026-10-18)
Scope: all three datasets, as in Odoo 12: jobs, budgets, customers.
Security: an API key is required, sent in the X-API-Key header (Odoo 12 had no check).
The key is generated in Settings → Remote Sync ("Generate new key"). The field is read-only with a copy button.
With no key set, all data is refused.
Names: model names stay kderp.job.lookup, kderp.job.budget.cache, kderp.customer.cache. The module is named kdvn_remote_sync.
Not ported: the ir.rule extension in the Odoo 12 module (custom domain field with SQL). It isn't part of the sync; rebuild it separately if a module needs it.
Job numbers: real format HM11-26-0004, PM11-24-0001-F01. A big job has 0 as the 9th character (rule from Odoo 12, confirmed by Thanh's examples).
Menu: top-level app "KDERP Jobs" (Jobs, Customers, Configuration → Settings), Settings admins only for now.
Changes from Odoo 12
display_name / _rec_names_search replace name_get / name_search.
Settings use the standard res.config.settings app (parameters kdvn_remote_sync.*).
The sync result is shown as an Odoo notification, so the module no longer depends on kderp_base or kderp_web_infrastructure.
Fixes:
Jobs are matched by remote id first, then by job number.
Customer admin rights now go to Settings admins only (Odoo 12 gave them to all internal users).
big_job no longer crashes on job numbers shorter than 9 characters.
Customer lookups are batched.
A budget without a name gets its code as the name.
Each remote id is unique for jobs and customers.
Mirrored from Odoo 12 (2026-10-19)
Odoo 12 versions 12.0.1.2.0 and 12.0.1.2.1 → Odoo 19 version 19.0.1.2.0: budgets are matched by (job, budget code).
Why: ids from kderp.budget.data and kderp.fixed.cost.data collide.
Constraint: unique (job_id, budget_code). external_id is kept for tracing only.
Purge: budget rows whose (job, code) was not sent are deleted.
Migration 19.0.1.2.0/pre-migrate.py drops the old unique(external_id) constraint and removes duplicate rows.
Odoo 12's script scripts/repair_request_budget_links.py is not needed in Odoo 19, because nothing links to budgets yet.
The two budget sources use different code sets (Budget data: 4082, 8000, 7000; Fixed cost: 8100A21, 7000A21), so the same (job, code) never comes from both. Thanh confirmed 2026-10-19 that 4082 is not in Fixed Cost Budget Data.
n8n
Workflow "OE Hanoi Active Job List":
Duplicate the final "HTTP Request" node for Odoo 19.
Add the headers X-API-Key and X-Odoo-Database (needed because the dev server has several databases).
Connect the new node from "Format data" and set "On Error: Continue".
n8n reaches odoo19.local through extra_hosts in its docker compose file.
The payload is unchanged: form fields jobs_data, budgets_data, customers_data as JSON strings. A JSON body with the same keys also works.
Advised Thanh: the Odoo 12 password is stored in plain text in the Config and fields_get nodes. Change it and move it to an n8n credential.
The Job List domain stays at active jobs (doing/done). Closed jobs are not synced here (see Purpose).
Tests
tests/test_sync_pipeline.py covers:
first sync, update and purge, empty lists
KOM dates
the big-job rule with real job numbers
records in use are kept
budgets matched by job and code (colliding ids, a code reused on another job)
tests/test_sync_endpoint.py covers API key checks, the form payload, a JSON body and a malformed payload.