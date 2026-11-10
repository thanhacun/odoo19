"""Staff transfer: transfer_employee_id (one staff) became transfer_employee_ids (several), as in Odoo 12 (12.0.1.7.0).

1. Copy every old staff into the new relation table (safe to run again: existing pairs are skipped).
2. Approved requests: the frozen 'before' project is copied to current_project_frozen_ids (the manual value stays, too).
3. Rewrite the approval steps that read the old field names (the tier definitions are noupdate, so the data file does not).
4. Drop the old column (it is NOT NULL and would block every new request).
"""
import logging
import re

_logger = logging.getLogger(__name__)

# rec.transfer_employee_id.gm_id.user_id  ->  rec.transfer_employee_ids.mapped('gm_id.user_id')
RENAMES = [('transfer_employee_id', 'transfer_employee_ids'),
           ('current_department_id', 'current_department_ids'),
           ('current_area_id', 'current_area_ids'),
           ('current_project_id', 'current_project_ids')]


def _rewrite(text):
    for old, new in RENAMES:
        text = re.sub(r"rec\.%s((?:\.\w+)+)" % old,
                      lambda m: "rec.%s.mapped('%s')" % (new, m.group(1)[1:]), text)
        text = re.sub(r"rec\.%s\b(?!s)" % old, "rec." + new, text)
    return text


def migrate(cr, version):
    if not version:
        return
    cr.execute("""SELECT 1 FROM information_schema.columns
                  WHERE table_name = 'staff_transfer' AND column_name = 'transfer_employee_id'""")
    if cr.fetchone():
        cr.execute("""
            INSERT INTO staff_transfer_employee_rel (transfer_id, employee_id)
            SELECT t.id, t.transfer_employee_id FROM staff_transfer t
            WHERE t.transfer_employee_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM staff_transfer_employee_rel r
                              WHERE r.transfer_id = t.id AND r.employee_id = t.transfer_employee_id)
        """)
        _logger.info("staff transfer: %s staff copied to the new relation", cr.rowcount)
        cr.execute("""
            INSERT INTO staff_transfer_frozen_project_rel (transfer_id, job_id)
            SELECT t.id, t.current_project_manual_id FROM staff_transfer t
            WHERE t.state = 'approved' AND t.current_project_manual_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM staff_transfer_frozen_project_rel r
                              WHERE r.transfer_id = t.id AND r.job_id = t.current_project_manual_id)
        """)
        cr.execute("ALTER TABLE staff_transfer DROP COLUMN transfer_employee_id")

    cr.execute("""SELECT column_name FROM information_schema.columns
                  WHERE table_name = 'tier_definition'
                    AND column_name IN ('reviewer_expression', 'definition_domain', 'python_code')""")
    columns = [r[0] for r in cr.fetchall()]
    cr.execute("SELECT id FROM tier_definition WHERE model = 'staff.transfer'")
    for (tier_id,) in cr.fetchall():
        for column in columns:
            cr.execute("SELECT %s FROM tier_definition WHERE id = %%s" % column, (tier_id,))
            old = cr.fetchone()[0]
            if not old:
                continue
            new = _rewrite(old) if column != 'definition_domain' else old.replace('transfer_employee_id', 'transfer_employee_ids')
            if new != old:
                cr.execute("UPDATE tier_definition SET %s = %%s WHERE id = %%s" % column, (new, tier_id))
                _logger.info("tier definition %s, %s: %r -> %r", tier_id, column, old, new)
