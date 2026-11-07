#!/bin/sh
# Build (or rebuild) the EMPTY Odoo 19 template database: all KDVN HR modules installed, no data.
# tools/refresh_dev.sh copies it (createdb -T) to make a fresh dev database in seconds.
# Rebuild it after a module version bump or a new module (then every refresh starts from the current code).
#   tools/make_empty_template.sh [template_db]        (default odoo19_empty, about 3-5 min)
set -eu
TPL=${1:-odoo19_empty}
CONTAINER=${CONTAINER:-odoo19}
PGC=${PGC:-db}
MODULES=${MODULES:-kdvn_legacy_import,kdvn_hr_attendance,kdvn_remote_sync,kdvn_web,kdvn_e_approval,kdvn_entertainment_procedures,kdvn_hr_procedures,kdvn_procurement_procedures,kdvn_dashboard,kdvn_knowledge}   # their dependencies come with them
case "$TPL" in odoo19_dev|odoo19_thcn|legacy12|postgres) echo "refusing: $TPL is not a template name"; exit 1;; esac
docker exec "$PGC" psql -U odoo -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$TPL' AND pid<>pg_backend_pid()" >/dev/null
docker exec "$PGC" psql -U odoo -d postgres -c "DROP DATABASE IF EXISTS \"$TPL\"" -c "CREATE DATABASE \"$TPL\""
rm -rf "$(cd "$(dirname "$0")/.." && pwd)/odoodata/filestore/$TPL"
docker exec "$CONTAINER" odoo -c /etc/odoo/odoo.conf -d "$TPL" -i "$MODULES" --without-demo=all --stop-after-init --no-http --log-level=warn 2>&1 | tail -5
docker exec "$PGC" psql -U odoo -d "$TPL" -Atc "select count(*)||' modules installed, '||(select count(*) from hr_employee)||' employees' from ir_module_module where state='installed'"
echo "template $TPL ready (no connection is left open, so createdb -T works)"
