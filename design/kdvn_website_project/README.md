# kdvn_website_project — notes

Odoo 19 successor of the Odoo 12 module `kdvn_website_project` (`kdvn.publish.project`, reference only).

## Where the projects come from
- Odoo 12 read finished big jobs over XML-RPC from the KDERP/OpenERP servers (`website.servers_json`):
  `state in (done, closed)`, `job_scale = '00-big_job'`, grouped by job name, kept from 1,000,000 USD.
- Those servers are only reachable inside the company network (VPN), so in Odoo 19 **n8n** reads them and
  pushes the jobs to `POST /api/v1/website_projects` (header `X-API-Key`, Settings > Website Projects).
  Workflow: `n8n/kderp_closed_big_jobs_to_odoo19.json` (import it in n8n, fill in servers and key).
- Independent of `kdvn_remote_sync` (active jobs only; decision Thanh 2026-10-20).

## Payload
`{"jobs": [{name, code, state, job_type, date_start, completion_date | actual_completion_date,
city_province_id ([id, name] or text), contracted_amount_usd}, ...]}` — JSON body (or form field `jobs`).
Odoo groups by name (case/spaces ignored), sums the USD amounts, takes the earliest start / latest completion.
New projects: unpublished, website fields pre-filled (name, year, "City, Vietnam", type E/M/M&E).
Existing projects: only the read-only KDERP fields are refreshed; website edits are kept.
Response: `{"status": "success", "jobs": n, "result": {"created", "updated", "skipped"}}`.

## Size
A full list is sent each run. Use the JSON body; if nginx answers 413, raise `client_max_body_size`
for the Odoo host in nginx-proxy (`vhost.d/<host>`).
