# kdvn_remote_sync: KDERP jobs, budgets, customers
Odoo 19 version of the Odoo 12 module kderp_remote_sync (reference only: ~/odoo12/addons/kderp_remote_sync).
When Thanh changes the Odoo 12 module, mirror the change here. Spec and decisions: docs/kdvn_remote_sync.md;
notes: design/kdvn_remote_sync/README.md.

- n8n posts active jobs (doing/done), budgets and customers to POST /api/v1/sync_jobs, header X-API-Key
  (key from Settings > Remote Sync; no key means all data is refused). Header X-Odoo-Database is needed on the dev server.
- Cache models: kderp.job.lookup, kderp.job.budget.cache, kderp.customer.cache (names stay as in Odoo 12).
- Budgets are matched by (job, budget code). Migrations are in migrations/.
- Not for the website: do not add closed jobs to this sync.
- Tests: tests/test_sync_pipeline.py, tests/test_sync_endpoint.py.
