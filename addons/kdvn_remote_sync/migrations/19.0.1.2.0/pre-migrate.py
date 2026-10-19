"""Budgets are now unique per (job, budget code) instead of per remote id
(mirrors kderp_remote_sync 12.0.1.2.0 / 12.0.1.2.1 on Odoo 12).

Drop the old unique(external_id) constraint and remove duplicate (job, code)
rows, keeping the lowest id. Nothing in Odoo 19 links to budget rows yet; the
next sync refreshes the kept rows."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("ALTER TABLE kderp_job_budget_cache DROP CONSTRAINT IF EXISTS kderp_job_budget_cache_external_id_unique")
    cr.execute("""
        DELETE FROM kderp_job_budget_cache b
         USING kderp_job_budget_cache keep
         WHERE b.job_id = keep.job_id AND b.budget_code = keep.budget_code AND b.id > keep.id
     RETURNING b.id
    """)
    deleted = [r[0] for r in cr.fetchall()]
    if deleted:
        _logger.warning("Budget cache: deleted %s duplicate (job, code) rows: %s", len(deleted), deleted)
