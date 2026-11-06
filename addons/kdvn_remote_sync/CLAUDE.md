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

## Direct pull (19.0.1.3.0)
Port of kderp_remote_sync 12.0.1.5.0 `models/remote_pull.py` (see ~/odoo12/addons/kderp_remote_sync/CLAUDE.md "Direct pull" for the design and measured load). Reads with the Reader login of kdvn_remote_integration,
feeds the same pipeline, so n8n and the pull can run together. Two crons (full hourly, changed customers every 5 minutes) ship INACTIVE. Params `kdvn_remote_sync.customer_since` / `kdvn_remote_sync.pull_status`.
Failure handling uses a savepoint (no cr.rollback). Tests: tests/test_remote_pull.py (8, fake remote).
