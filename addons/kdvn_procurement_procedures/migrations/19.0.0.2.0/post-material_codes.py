"""Item 'No.' (1, 2 ... 44, 34-1) becomes the material code ST0001 ... ST0044, ST0034-1, shared by the store, the receipt and
the accounting report (Odoo 12 migration 12.0.1.5.0, same rule). Safe to run twice: only codes that are still a plain number
(with an optional -suffix) change."""


def migrate(cr, version):
    cr.execute("""UPDATE safety_tool_item
                  SET code = 'ST' || lpad(split_part(code, '-', 1), 4, '0') ||
                             CASE WHEN position('-' in code) > 0 THEN '-' || substr(code, position('-' in code) + 1) ELSE '' END
                  WHERE code ~ '^[0-9]{1,4}(-[0-9]+)?$'""")
