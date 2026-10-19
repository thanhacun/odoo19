# kdvn_website_project — notes

Odoo 19 successor of the Odoo 12 module `kdvn_website_project` (`kdvn.publish.project`, reference only).

## Where the projects come from
- Odoo 12 read finished big jobs over XML-RPC from the KDERP/OpenERP servers (`website.servers_json`):
  `state in (done, closed)`, `job_scale = '00-big_job'`, grouped by job name, kept from 1,000,000 USD
  (`contracted_amount_usd`). KDERP now runs on Odoo 12: `job_type = '00-big_job'`, `job_amount` + `currency_id`.
- Those servers are only reachable inside the company network (VPN), so in Odoo 19 **n8n** reads them and
  pushes the jobs to `POST /api/v1/website_projects` (header `X-API-Key`, Settings > Website Projects).
  Workflow: `n8n/kderp_closed_big_jobs_to_odoo19.json` (import it in n8n, fill in servers and key).
- Independent of `kdvn_remote_sync` (active jobs only; decision Thanh 2026-10-20).

## Payload
`{"jobs": [{name, code, state, em, job_type, date_start, completion_date | actual_completion_date,
city_province_id ([id, name] or text), job_amount, currency_id, currency_rates}, ...]}` — JSON body (or form field `jobs`).
Odoo groups by name (case/spaces ignored), sums the USD amounts, takes the earliest start / latest completion.

Amount (as close as possible to the old website: contract amount in USD **without VAT**):
- KDERP today (Odoo 12, `kderp_job`): `job_amount` (without VAT) in the job's default currency `currency_id`,
  converted with **the job's own exchange rates** like KDERP's `kderp.custom.currency.compute()`:
  `USD = job_amount * rate(job currency) / rate(USD)` (`rate` = rate to the company currency).
  n8n node "Job Rates" reads `kderp.job.currency` (`account_analytic_id`, `currency_id`, `rate`) and
  "Collect jobs" sends them per job as `currency_rates` (`{"VND": 1, "USD": 25000}`).
  Fallback when a job has no rates: USD as is, VND ÷ Settings > Website Projects > VND per USD.
- Old OpenERP servers: `contracted_amount_usd` is still accepted and used as is.
- E/M comes from `em` (KDERP's `job_type` is the job scale `00-big_job`, not E/M).
- KDERP's `account.analytic.account._search` hides `closed` jobs unless the context has
  `many2one_show_all`, so the n8n search passes it.
New projects: unpublished, website fields pre-filled (name, year, "City, Vietnam", type E/M/M&E).
Existing projects: only the read-only KDERP fields are refreshed; website edits are kept.
Response: `{"status": "success", "jobs": n, "result": {"created", "updated", "skipped"}}`.

## Size
A full list is sent each run. Use the JSON body; if nginx answers 413, raise `client_max_body_size`
for the Odoo host in nginx-proxy (`vhost.d/<host>`).
