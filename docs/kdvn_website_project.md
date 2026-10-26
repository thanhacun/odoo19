kdvn_website_project — Past Prominent Projects

Module addons/kdvn_website_project (19.0.3.4.0, see the manifest), branch feature/kdvn_website_project, merged into dev. It depends only on kdvn_website. Page spec: design/kdvn_website/specs/prominent-projects.md. Import notes and the n8n workflow are in design/kdvn_website_project/.

This is the successor of the Odoo 12 module kdvn_website_project (kdvn.publish.project). The Odoo 12 module is reference only, at ~/odoo12/addons/kdvn_website_project; its XML-RPC helper kdvn.website.copy.rpc.data.mixin is in ~/odoo12/addons/kdvn_website.

Decisions (Thanh)
2026-10-19: a separate model kdvn.website.project for website projects.
2026-10-19: card chips are work-scope tags (kdvn.website.project.tag, translatable), separate from type and category.
2026-10-20: no link to kdvn_remote_sync. Closed jobs don't belong in the remote-sync cache, because that would change its purpose.
2026-10-20: projects come from finished big jobs, as in Odoo 12:
domain state in (done, closed) and job_scale = '00-big_job';
jobs grouped by name, ignoring case and spaces;
only projects of at least 1,000,000 USD are kept (Settings → Website Projects).
2026-10-20: n8n pushes the jobs. The KDERP/OpenERP servers are only reachable inside the company network (VPN), so a direct XML-RPC import from the DigitalOcean server is impossible.
The XML-RPC version (19.0.2.0.0: import sources and daily cron) was replaced by the endpoint POST /api/v1/website_projects in 19.0.3.0.0.
Workflow: design/kdvn_website_project/n8n/kderp_closed_big_jobs_to_odoo19.json.
2026-10-20:
Keep website edits. Imported data goes into the read-only kderp_* fields. Name, year, area and type are only pre-filled when a project is created.
New projects are unpublished.
2026-10-19 (later): KDERP now runs on Odoo 12 (kderp_job), with no contracted_amount_usd. "As close as possible to the old website": amount = job_amount (without VAT) in the job's default currency currency_id; converted with each job's own KDERP exchange rates like kderp.custom.currency.compute(): USD = job_amount × rate(job currency) / rate(USD) (rate = rate to company currency; n8n node "Job Rates" reads kderp.job.currency, sent as currency_rates). Fallback without rates: Settings → Website Projects → VND per USD (25,000). contracted_amount_usd still accepted. Domain now job_type = '00-big_job' (KDERP's job_type = job scale); E/M from em. KDERP's _search hides closed jobs unless context many2one_show_all → the n8n search passes it.
Model
kdvn.website.project (website.published.mixin, image.mixin) has these fields:
website fields: name (translatable), sequence, active, year, area (translatable), project_type (electrical / mechanical / me / other), category_id, tag_ids, description (Html, not shown yet);
imported, read-only: kderp_key (unique; normalised job name), kderp_name, kderp_job_codes, kderp_type (job types joined, e.g. "E&M"), kderp_location (city/province), kderp_date_start (earliest), kderp_completion_date (latest; completion_date or actual_completion_date), kderp_amount_usd (sum of the jobs' USD amounts), kderp_imported_on.
_kdvn_import_jobs(jobs) groups the jobs and either creates unpublished projects (when the amount reaches the minimum) or refreshes the kderp_* fields of existing ones. It returns {created, updated, skipped}.
Settings → Website Projects holds:
the API key (kdvn_website_project.api_key, generated in Settings, read-only with a copy button);
the minimum amount (kdvn_website_project.min_amount_usd).
Endpoint POST /api/v1/website_projects:
header X-API-Key required;
body JSON {"jobs": [...]}, or a form field jobs;
response {status, jobs, result}.
kdvn.website.project.category: name (translatable) and the slug used in the URL. Seed: factory, data-center, building, logistics, educational, hotel, shopping-mall, other.
Back office: Website → Site → Content → Projects; Website → Configuration → Project Categories / Project Work Scopes.
n8n workflow
Daily at 02:00, plus a manual trigger.
Steps:
Servers — a code node with one item per KDERP server: Hanoi 172.16.10.192:8169 / odoo_hanoi pre-filled; HCMC still to add; passwords are placeholders.
Authenticate, over JSON-RPC.
Closed Big Jobs — search_read on account.analytic.account.
Collect jobs — merges all servers and stops on a server error.
Send to Odoo 19 — https://beta.kinden.com.vn/api/v1/website_projects with a JSON body.
A disabled Check fields node (fields_get) is included to confirm the field names on each server, because the active-job workflow uses actual_completion_date while Odoo 12's module used completion_date and job_scale.
Page
/prominent-projects?category=&year=&view= is rendered on the server.
Year tabs: All, the 5 latest years, then "Earlier".
Grid: one row of cards per year. List: a table.
Images are served at /prominent-projects/image/<id>/<size>, for published projects only.
Category menus in menus.csv link to ?category=<slug>.
Open
n8n: Thanh to import the workflow, fill in server credentials (preferably as n8n credentials) and the HCMC server, and check the field names with "Check fields".
Payload size: if nginx returns 413, raise client_max_body_size for the host.
Designer questions: the mobile category tiles, view buttons on mobile, what a card click does, tablet card widths.
Data migration: existing Odoo 12 kdvn.publish.project records and their photos (descriptions, categories, images) need a separate plan.
Homepage section: built 2026-10-20 (4 cards, Show on Homepage flag; see docs/kdvn_website_progress.md).