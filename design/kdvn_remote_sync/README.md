# kdvn_remote_sync — notes

Odoo 19 version of the Odoo 12 module `odoo12/addons/kderp_remote_sync` (**12.0.1.2.1**, read on 2026-10-19; first port from 12.0.1.1.0 on 2026-10-18).
The Odoo 12 folder is reference only: never change it from here.

## What it does
n8n reads jobs, budgets and customers on the KDERP (Odoo 12) server and posts them to
`POST /api/v1/sync_jobs`. The module upserts them into three cache models and deletes
records the server no longer sends, unless another document still points to them.
Settings > Remote Sync: API key, n8n URLs, "Sync now" (calls the n8n trigger webhook).
Menu: Settings > Technical > Remote Sync (KDERP) > Jobs / Customers / Settings.

## Odoo 12 → Odoo 19
| Odoo 12 | Odoo 19 | Notes |
|---|---|---|
| `kderp.job.lookup`, `kderp.job.budget.cache`, `kderp.customer.cache` | same names and fields | kept so other kderp modules can be migrated as they are |
| `name_get` / `name_search` | `_compute_display_name` / `_rec_names_search` | same display "[code] name" |
| controller `auth='none'`, no check | `auth='public'` + **`X-API-Key` header** required | key in Settings > Remote Sync; no key = everything refused |
| form fields `jobs_data`, `budgets_data`, `customers_data` (JSON strings) | same; a JSON body with the same keys also works | |
| HTTP 400 / 500 / 200 + telemetry | same | |
| `kderp.remote.sync.config.settings` (own settings model) | standard `res.config.settings` app "Remote Sync" | parameters `kdvn_remote_sync.*` |
| result shown with `kderp.notification.wizard` (kderp_web_infrastructure) | Odoo notification | no dependency on other kderp modules |
| `base_ir_rule.py` (custom `domain` + SQL in record rules) | **not ported** (decision 2026-10-18) | not part of the sync; rebuild separately if a module needs it |
| depends `kderp_base`, `kderp_web_infrastructure` | `base`, `web` | |

## Behaviour kept from Odoo 12
- Order: customers → jobs → budgets. An empty or missing list leaves that cache untouched.
- Roles (`role_logins`) are matched to users by login on *this* server; unknown logins stay empty.
- `kom_peak_from` / `kom_peak_to` only change when the payload contains the keys.
- Dates `False` / `'False'` = empty. Ids may come as `12` or `[12, "Name"]`.
- Purge keeps records referenced by any stored many2one/many2many of another model (and jobs whose budgets are referenced).

## Small fixes compared with Odoo 12
- Jobs matched by remote id first, then job number (Odoo 12: number only, but purged by id).
- Customers: admin rights were given to all internal users → now Settings admins only.
- `big_job` no longer crashes on job numbers shorter than 9 characters.
- Customer lookups for jobs done in one query instead of one per job.
- Budget without a name gets its code as name (name is required).
- Unique remote id per cache model (jobs, customers).

## Changes mirrored from Odoo 12
- **12.0.1.2.0 / 12.0.1.2.1 → 19.0.1.2.0:** budgets matched by (job, budget code) instead of remote id, because ids from the two remote budget models (budget data, fixed cost data) collide. Unique (job, code); `external_id` for tracing only; purge = rows whose (job, code) was not sent. Migration `19.0.1.2.0/pre-migrate.py` drops the old unique(external_id) constraint and removes duplicate rows. (Odoo 12's request repair script is not needed: no Odoo 19 module links to budgets yet.)

## n8n change needed
In the HTTP Request node that posts to Odoo 19, add header `X-API-Key: <key from Settings > Remote Sync>`.
Point the URL to the Odoo 19 server: `https://<odoo19-host>/api/v1/sync_jobs`. Everything else stays the same.

## When the Odoo 12 module changes
1. Tell Claude what changed (or the new version number); Claude diffs the Odoo 12 folder (read only).
2. Update the same place here (fields, payload keys, `execute_master_sync_pipeline`), the table above and the version line at the top.
3. Bump `version` in the manifest; add / adjust tests in `tests/`.
