#!/bin/sh
# Import Odoo 12 data (database legacy12) into an Odoo 19 database through kdvn_legacy_import.
# Re-runnable. Dry run by default (does everything, then rolls back). Docs: docs/legacy_import_runbook.md
#
#   tools/legacy_import.sh <db> <date_from> <date_to> [--apply] [--password PW] [--codes "S0001 S0002"] [--all-staff] [--steps "at_attendance at_raw"] [--bulk]
#
#   <db>         target Odoo 19 database (e.g. odoo19_dev)
#   date_from/to attendance window, YYYY-MM-DD (history of staff, rules, allocations is always complete)
#   --apply      really write (without it: dry run)
#   --password   dev only: set this password on ALL imported users
#   --codes      only these staff codes (their managers are added automatically); default everybody
#   --all-staff  include leavers too (default: working staff only)
#   --steps      only these steps (names in addons/kdvn_legacy_import/models/*.py)
#   --bulk       load the big history tables with streamed SQL (models/legacy_bulk.py): fast, no memory growth
# Output goes to temp/legacy_import_<db>_<time>.log; the run goes on in the background (docker exec -d), follow it with tail -f.
set -eu
[ $# -ge 3 ] || { sed -n 2,15p "$0"; exit 1; }
DB=$1; FROM=$2; TO=$3; shift 3
APPLY=0; PW=""; CODES=""; ALL=0; STEPS=""; BULK=0
while [ $# -gt 0 ]; do
  case $1 in
    --apply) APPLY=1;;
    --password) PW=$2; shift;;
    --codes) CODES=$2; shift;;
    --all-staff) ALL=1;;
    --steps) STEPS=$2; shift;;
    --bulk) BULK=1;;
    *) echo "unknown option $1"; exit 1;;
  esac
  shift
done
CONTAINER=${CONTAINER:-odoo19}
HERE=$(cd "$(dirname "$0")/.." && pwd)
LOG=temp/legacy_import_${DB}_$(date +%y%m%d_%H%M).log
mkdir -p "$HERE/temp"
docker exec -d -e DB="$DB" -e FROM="$FROM" -e TO="$TO" -e APPLY="$APPLY" -e PW="$PW" -e CODES="$CODES" -e ALL="$ALL" -e STEPS="$STEPS" -e BULK="$BULK" "$CONTAINER" sh -c "odoo shell -c ${ODOO_CONF:-/etc/odoo/odoo.conf} -d '$DB' --no-http > /home/odoo/project/$LOG 2>&1 <<'PY'
import os, datetime
iso = datetime.date.fromisoformat
imp = env['kdvn.legacy.import'].with_context(kdvn_commit_steps=True)
apply_ = os.environ['APPLY'] == '1'
res = imp.run(
    employee_codes=os.environ['CODES'].replace(',', ' ').split(),
    working_only=os.environ['ALL'] != '1',
    password=os.environ['PW'] or None,
    dry_run=not apply_,
    steps=os.environ['STEPS'].split() or None, bulk=os.environ['BULK'] == '1',
    date_from=iso(os.environ['FROM']), date_to=iso(os.environ['TO']),
)
print('=' * 20, 'RESULT', 'APPLIED' if apply_ else 'DRY RUN')
print(res['log'])
env.cr.commit()
PY"
echo "started ($( [ "$APPLY" = 1 ] && echo APPLY || echo dry run )), log: $HERE/$LOG"
echo "follow:  tail -f $HERE/$LOG"
