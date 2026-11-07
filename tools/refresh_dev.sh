#!/bin/sh
# Rebuild an Odoo 19 DEV database from Odoo 12 data (one source: the Odoo 12 production database).
#
#   tools/refresh_dev.sh <target_db> <date_from> <date_to> [--dump FILE | --from-db DB] [--template odoo19_empty]
#                        [--password PW] [--no-neutralize] [--yes]
#
# Steps (shown first; nothing happens without --yes):
#   1. legacy12  : --dump FILE   pg_restore of a production backup (<db>.dump made by backup_odoo.sh, pg_dump -Fc)
#                  --from-db DB  copy of an Odoo 12 DB from the Odoo 12 dev Postgres (tools/legacy12_snapshot.sh)
#                  (neither)     keep the legacy12 that is there now
#   2. target_db : DROPPED and created again as a copy of the empty template (tools/make_empty_template.sh); filestore copied
#   3. neutralize: `odoo neutralize` on the target (crons off, outgoing mail dummy) unless --no-neutralize
#   4. import    : tools/legacy_import.sh <target_db> <from> <to> --apply  (background, log in temp/)
# After step 2 restart the Odoo server that serves <target_db> (it still holds the old database in memory).
# Docs: docs/legacy_import_runbook.md
set -eu
[ $# -ge 3 ] || { sed -n 2,17p "$0"; exit 1; }
DB=$1; FROM=$2; TO=$3; shift 3
DUMP=""; FROMDB=""; TPL=odoo19_empty; PW=""; NEUT=1; YES=0
while [ $# -gt 0 ]; do
  case $1 in
    --dump) DUMP=$2; shift;;
    --from-db) FROMDB=$2; shift;;
    --template) TPL=$2; shift;;
    --password) PW=$2; shift;;
    --no-neutralize) NEUT=0;;
    --yes) YES=1;;
    *) echo "unknown option $1"; exit 1;;
  esac
  shift
done
HERE=$(cd "$(dirname "$0")/.." && pwd)
CONTAINER=${CONTAINER:-odoo19}; PGC=${PGC:-db}
psqlx() { docker exec "$PGC" psql -U odoo -d postgres -Atc "$1"; }

case "$DB" in odoo19_thcn|legacy12|postgres|template0|template1|"$TPL") echo "refusing: $DB must not be rebuilt"; exit 1;; esac
[ -z "$DUMP" ] || [ -f "$DUMP" ] || { echo "dump not found: $DUMP"; exit 1; }
[ -z "$DUMP" ] || [ -z "$FROMDB" ] || { echo "use --dump or --from-db, not both"; exit 1; }
[ "$(psqlx "select count(*) from pg_database where datname='$TPL'")" = 1 ] || { echo "template $TPL does not exist: run tools/make_empty_template.sh"; exit 1; }
if docker exec "$CONTAINER" pgrep -f "odoo shell" >/dev/null 2>&1; then echo "an import (odoo shell) is running in $CONTAINER: wait for it"; exit 1; fi

echo "PLAN"
if [ -n "$DUMP" ]; then echo " 1. legacy12 = restore of $DUMP"; elif [ -n "$FROMDB" ]; then echo " 1. legacy12 = copy of Odoo 12 dev database $FROMDB"; else echo " 1. legacy12 kept as it is (latest attendance day: $(docker exec "$PGC" psql -U odoo -d legacy12 -Atc 'select max(at_date) from hr_attendance' 2>/dev/null || echo 'legacy12 missing'))"; fi
echo " 2. database $DB DROPPED ($(psqlx "select pg_size_pretty(pg_database_size('$DB'))" 2>/dev/null || echo 'does not exist yet')) and recreated from $TPL"
[ "$NEUT" = 1 ] && echo " 3. odoo neutralize on $DB" || echo " 3. (no neutralize)"
echo " 4. import window $FROM .. $TO, working staff, password: $([ -n "$PW" ] && echo set || echo none)"
[ "$YES" = 1 ] || { echo "Nothing done. Add --yes to run."; exit 0; }

echo "== 1. legacy12"
if [ -n "$DUMP" ]; then
  psqlx "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='legacy12' AND pid<>pg_backend_pid()" >/dev/null
  psqlx "DROP DATABASE IF EXISTS legacy12" >/dev/null; psqlx "CREATE DATABASE legacy12" >/dev/null
  docker exec -i "$PGC" pg_restore -U odoo -d legacy12 --no-owner --no-privileges < "$DUMP" 2>"$HERE/temp/legacy12_restore.err" || true
  echo "restore messages: $(wc -l < "$HERE/temp/legacy12_restore.err") lines in temp/legacy12_restore.err"
elif [ -n "$FROMDB" ]; then
  "$HERE/tools/legacy12_snapshot.sh" "$FROMDB"
fi
docker exec "$PGC" psql -U odoo -d legacy12 -Atc "select 'legacy12: '||(select count(*) from hr_employee)||' employees, attendance up to '||(select max(at_date) from hr_attendance)"

echo "== 2. $DB from $TPL"
psqlx "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB','$TPL') AND pid<>pg_backend_pid()" >/dev/null
psqlx "DROP DATABASE IF EXISTS \"$DB\"" >/dev/null
psqlx "CREATE DATABASE \"$DB\" TEMPLATE \"$TPL\"" >/dev/null
rm -rf "$HERE/odoodata/filestore/$DB"
[ ! -d "$HERE/odoodata/filestore/$TPL" ] || cp -a "$HERE/odoodata/filestore/$TPL" "$HERE/odoodata/filestore/$DB"
echo "created. RESTART the Odoo server that serves $DB."

if [ "$NEUT" = 1 ]; then
  echo "== 3. neutralize"
  docker exec "$CONTAINER" odoo neutralize -c /etc/odoo/odoo.conf -d "$DB" 2>&1 | tail -2
fi

echo "== 4. import"
if [ -n "$PW" ]; then "$HERE/tools/legacy_import.sh" "$DB" "$FROM" "$TO" --apply --password "$PW"; else "$HERE/tools/legacy_import.sh" "$DB" "$FROM" "$TO" --apply; fi
