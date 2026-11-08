#!/bin/bash
# Make (or refresh) the experiment database odoo19_lab as a copy of the mirror odoo19_dev.
#
#   tools/make_lab.sh [--source odoo19_dev] [--lab odoo19_lab] [--yes]
#
# odoo19_dev is the MIRROR: the nightly import (tools/legacy_nightly.sh) overwrites imported records there, so nobody experiments in it.
# odoo19_lab is for experiments and ideas: the nightly never touches it. A refresh DROPS the lab and copies the mirror again
# (data, filestore, then `odoo neutralize`: crons off, outgoing mail dummy). Without --yes it only shows the plan.
# Serve it with the Odoo server on port 8069 (since 8 Nov the server on 8069 serves odoo19_lab; odoo19_dev has no server, it is only the mirror the nightly fills):
#   docker exec -d odoo19 bash -lc 'odoo --dev all -d odoo19_lab; exec bash'   -> http://172.30.0.4:8069
#   stop it before a refresh: docker exec odoo19 pkill -f 'bin/odoo --dev all -d odoo19_lab'
#   look at the mirror once: the same command with -d odoo19_dev --http-port=8070 --gevent-port=8073
set -eu
SRC=odoo19_dev; LAB=odoo19_lab; YES=0
while [ $# -gt 0 ]; do
  case $1 in
    --source) SRC=$2; shift;;
    --lab) LAB=$2; shift;;
    --yes) YES=1;;
    *) echo "unknown option $1"; sed -n 2,10p "$0"; exit 1;;
  esac
  shift
done
HERE=$(cd "$(dirname "$0")/.." && pwd)
CONTAINER=${CONTAINER:-odoo19}; PGC=${PGC:-db}
psqlx() { docker exec "$PGC" psql -U odoo -d postgres -Atc "$1"; }
case "$LAB" in odoo19_dev|odoo19_thcn|odoo19_empty|legacy12*|postgres|template0|template1|kdvn_test) echo "refusing: $LAB must not be overwritten"; exit 1;; esac
[ "$LAB" != "$SRC" ] || { echo "source and lab are the same database"; exit 1; }
[ "$(psqlx "select count(*) from pg_database where datname='$SRC'")" = 1 ] || { echo "source $SRC does not exist"; exit 1; }
echo "PLAN: $LAB ($(psqlx "select coalesce((select pg_size_pretty(pg_database_size('$LAB')) from pg_database where datname='$LAB'),'does not exist yet')")) is DROPPED and rebuilt as a copy of $SRC ($(psqlx "select pg_size_pretty(pg_database_size('$SRC'))")), filestore copied, neutralized."
[ "$YES" = 1 ] || { echo "Nothing done. Add --yes to run."; exit 0; }
if docker exec "$CONTAINER" pgrep -f "odoo.* -d $LAB" >/dev/null 2>&1; then echo "a server is running on $LAB: stop it first (pkill -f 'odoo --dev all -d $LAB' in the container)"; exit 1; fi
psqlx "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$LAB' AND pid<>pg_backend_pid()" >/dev/null
psqlx "DROP DATABASE IF EXISTS \"$LAB\"" >/dev/null
psqlx "CREATE DATABASE \"$LAB\"" >/dev/null
echo "copying data ..."
docker exec "$PGC" bash -c "pg_dump -U odoo -Fc '$SRC' | pg_restore -U odoo -d '$LAB' --no-owner --no-privileges" 2>&1 | tail -3 || true
rm -rf "$HERE/odoodata/filestore/$LAB"
[ ! -d "$HERE/odoodata/filestore/$SRC" ] || cp -a "$HERE/odoodata/filestore/$SRC" "$HERE/odoodata/filestore/$LAB"
echo "neutralizing ..."
docker exec "$CONTAINER" odoo neutralize -c /etc/odoo/odoo.conf -d "$LAB" 2>&1 | tail -2
psqlx "select 'ready: $LAB, '||(select count(*) from pg_stat_activity where datname='$LAB')||' connections'" >/dev/null
docker exec "$PGC" psql -U odoo -d "$LAB" -Atc "select 'employees '||(select count(*) from hr_employee)||', attendance days '||(select count(*) from hr_attendance)||', entertainment requests '||(select count(*) from entertainment_request)"
