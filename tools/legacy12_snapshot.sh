#!/bin/sh
# Copy the Odoo 12 dev database into a READ-ONLY reference database `legacy12` on the Odoo 19 Postgres,
# so kdvn_legacy_import can read it with plain SQL (the two Postgres containers are on different docker networks).
# Re-runnable: drops and recreates legacy12. Nothing is written to the Odoo 12 database.
#   tools/legacy12_snapshot.sh [source_db]        (default att18mar)
set -eu
SRC=${1:-att18mar}
SRC_CONTAINER=${SRC_CONTAINER:-kdvn.odoo12.db.dev}
DST_CONTAINER=${DST_CONTAINER:-db}
docker exec "$DST_CONTAINER" psql -U odoo -d postgres -c "DROP DATABASE IF EXISTS legacy12" -c "CREATE DATABASE legacy12"
docker exec "$SRC_CONTAINER" pg_dump -U odoo --no-owner --no-privileges "$SRC" | docker exec -i "$DST_CONTAINER" psql -q -U odoo -d legacy12 -v ON_ERROR_STOP=0 >/dev/null 2>/tmp/legacy12_restore.err || true
docker exec "$DST_CONTAINER" psql -U odoo -d legacy12 -Atc "select 'hr_employee', count(*) from hr_employee"
echo "restore messages: $(wc -l < /tmp/legacy12_restore.err) lines in /tmp/legacy12_restore.err"
