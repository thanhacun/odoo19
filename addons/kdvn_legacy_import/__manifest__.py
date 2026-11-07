{
    'name': 'KDVN Legacy Import (Odoo 12)',
    'summary': 'Re-runnable copy of staff, organisation and later attendance data from the Odoo 12 database into Odoo 19.',
    'description': """
Reads a snapshot of the Odoo 12 database (database `legacy12`, made by tools/legacy12_snapshot.sh) with plain SQL,
read-only, and writes through the ORM. Every record is tagged with its Odoo 12 id (external id
legacy12.<table>_<id>), so a second run updates instead of duplicating. Used for dev test data now and as the
base of the go-live migration.
""",
    'version': '19.0.1.2.0',
    'category': 'Hidden/Tools',
    'author': 'Kinden Vietnam',
    'license': 'LGPL-3',
    'depends': ['kdvn_hr_ext'],
    'external_dependencies': {'python': ['psycopg2']},
    'data': [
        'security/ir.model.access.csv',
        'views/import_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
