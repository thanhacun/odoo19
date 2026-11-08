#!/bin/bash
# Nightly delta of the Odoo 12 -> Odoo 19 transition (Odoo 12 stays the master until the cut-over, docs/legacy_import_runbook.md).
#
#   tools/legacy_nightly.sh <target_db> [--dump-path FILE | --fetch-ssh att@172.16.10.198] [--window-months 3] [--full] [--legacy-db legacy12]
#                           [--parity-days 30] [--no-parity] [--max-problems 5] [--prune-force]
#
#   <target_db>      the Odoo 19 database that follows Odoo 12 (never a database where people already work for real)
#   --dump-path      a `pg_dump -Fc` of the Odoo 12 database (the nightly backup <db>.dump). It is restored into --legacy-db (a fresh copy is built next to
#                    the old one and swapped in, so a failed restore leaves the previous snapshot). Without it the existing snapshot is used.
#   --fetch-ssh      instead of --dump-path: copy the newest <remote-db>-*-daily.dump from the production server (READ-ONLY: one `ls -l` and one `scp` of that
#                    file; nothing is written, deleted or run there) into --fetch-dir (default ~/odoo12/tmp/hn_backups, git-ignored), check it with
#                    `pg_restore -l` and the size, and use it as the dump. Only the `-daily` files (the -test and -predeploy ones are never taken).
#                    Dropbox is only a fallback (restricted rclone remote, docs/backup-restore.md).
#   --remote-dir / --remote-db   where the backups are on the server (defaults /home/att/backups and AT_211101)
#   --window-months  attendance/requests/raw/leaves of the last N months (first day of the month N months back .. the future) are reloaded; default 3.
#                    Older rows are not touched (a weekly --full run catches corrections HR makes to old months).
#   --full           everything again (all history), ~9 minutes
#   --legacy-db      name of the snapshot database on the Odoo 19 Postgres (default legacy12; the target database is pointed to it)
#   --parity-days    parity check (Odoo 19 recompute against the stored Odoo 12 values) of the N days that end 3 days ago; default 30
#   --force          run even when the newest backup is the one that was processed last
#   --max-parity-pct parity differences (days of the window whose Odoo 19 recompute differs from the stored Odoo 12 value) that are still fine, in percent
#                    of the days checked; default 1. A few days always differ (about 0.2 %: days Odoo 12 has not settled, period boundary): they are listed, not an alarm.
#   --max-problems   problems in the import log that are still "normal" (the legacy rows that violate a constraint); default 5
#
# Steps: restore -> bulk import (--all-staff --prune) -> prune of hard deletes -> parity. Deletes only records that carry a legacy12.* external id and whose
# Odoo 12 row is gone; a table that would lose more than 2 % is skipped (looks like a bad snapshot) and counted as a problem.
# Exit code: 0 all fine; 1 a step failed (restore, import did not finish, safety limit); 2 the import finished with more problems than allowed or the parity differs by more than --max-parity-pct.
# One run at a time (lock file). Log: temp/legacy_nightly_<db>_<time>.log (the import log is next to it).
#
# FAILURE SIGNAL: the exit code (0 fine or "no new backup", 1 a step failed, 2 finished with problems / parity differences) and one line in
# temp/legacy_nightly_last.txt:  `<date time> OK|SKIP|FAIL|PROBLEMS <target> exit N <details>` (look at that file each morning, or let cron mail it).
# NO NEW BACKUP: the sha256 of the dump that was processed last is kept in temp/legacy_nightly_last.sha; if the newest daily is the same file
# the run says so, skips the import and exits 0 (--force runs anyway). So a night when the server backup did not happen does no harm.
#
# WHEN TO RUN: on THIS PC, after the HN backup (the server cron runs Tue-Sat 20:30 Hanoi time, about 10 minutes), so start after 21:30. The PC must be on and
# on the office network (ssh to att@172.16.10.198) at that hour; if it is not, the run fails at the fetch step (exit 1) and nothing changes.
# READY-TO-COPY (NOT installed; Thanh decides). Cron, Tue-Sat 21:45, mail goes to the local mailbox:
#   45 21 * * 2-6  cd $HOME/odoo19_thcn && ODOO_CONF=/etc/odoo/odoo.conf tools/legacy_nightly.sh <target_db> --fetch-ssh att@172.16.10.198 --window-months 3 >> temp/legacy_nightly_cron.log 2>&1
# or a systemd user timer (~/.config/systemd/user/legacy-nightly.{service,timer}), `systemctl --user enable --now legacy-nightly.timer`:
#   [Service] Type=oneshot, WorkingDirectory=%h/odoo19_thcn, ExecStart=%h/odoo19_thcn/tools/legacy_nightly.sh <target_db> --fetch-ssh att@172.16.10.198 --window-months 3
#   [Timer]   OnCalendar=Tue..Sat 21:45, Persistent=true (runs at the next start if the PC was off), [Install] WantedBy=timers.target
# A weekly full run (all history, ~9 min) for corrections HR makes to old months: the same line with --full on Saturday night, or Friday.
set -uo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
PROJECT_HOST=${PROJECT_HOST:-$HOME/odoo19_thcn}
CONTAINER=${CONTAINER:-odoo19}; PGC=${PGC:-db}
TARGET=${1:-}; [ -n "$TARGET" ] || { sed -n 2,23p "$0"; exit 1; }; shift
DUMP=""; FETCH=""; FETCHDIR=$HOME/odoo12/tmp/hn_backups; RDIR=/home/att/backups; RDB=AT_211101; WM=3; FULL=0; LEGACY=legacy12; PDAYS=30; PARITY=1; MAXPROB=5; PFORCE=""; FORCE=0; PPCT=1
while [ $# -gt 0 ]; do
  case $1 in
    --dump-path) DUMP=$2; shift;;
    --fetch-ssh) FETCH=$2; shift;;
    --fetch-dir) FETCHDIR=$2; shift;;
    --remote-dir) RDIR=$2; shift;;
    --remote-db) RDB=$2; shift;;
    --window-months) WM=$2; shift;;
    --full) FULL=1;;
    --legacy-db) LEGACY=$2; shift;;
    --parity-days) PDAYS=$2; shift;;
    --no-parity) PARITY=0;;
    --force) FORCE=1;;
    --max-parity-pct) PPCT=$2; shift;;
    --max-problems) MAXPROB=$2; shift;;
    --prune-force) PFORCE="--prune-force";;
    *) echo "unknown option $1"; exit 1;;
  esac
  shift
done
case "$TARGET" in postgres|template0|template1|odoo19_empty|"$LEGACY"|legacy12|legacy12_prod) echo "refusing: $TARGET is not a target database"; exit 1;; esac
mkdir -p "$HERE/temp"
exec 9>/tmp/legacy_nightly.lock
flock -n 9 || { echo "another legacy_nightly run is going on (lock /tmp/legacy_nightly.lock)"; exit 1; }
NLOG="$HERE/temp/legacy_nightly_${TARGET}_$(date +%y%m%d_%H%M).log"
exec > >(tee -a "$NLOG") 2>&1
say() { echo "[$(date +%H:%M:%S)] $*"; }
LAST="$HERE/temp/legacy_nightly_last.txt"; WHAT=""; RESULT=""
fail() { say "FAILED: $*"; WHAT="$*"; exit 1; }
finish() {   # the one-line signal of the last run (also on a failure in the middle)
  code=$?
  case "$RESULT" in SKIP) word=SKIP;; *) case $code in 0) word=OK;; 2) word=PROBLEMS;; *) word=FAIL;; esac;; esac
  echo "$(date '+%F %H:%M') $word $TARGET exit $code ${WHAT:-}" > "$LAST"
}
trap finish EXIT
psqlx() { docker exec "$PGC" psql -U odoo -d "$1" -Atc "$2"; }
START=$(date +%s)
say "nightly delta into $TARGET, snapshot $LEGACY, $( [ $FULL = 1 ] && echo 'FULL' || echo "window $WM months" ), log $NLOG"

# ---- 0. fetch the newest daily backup from the production server (read-only)
if [ -n "$FETCH" ] && [ -z "$DUMP" ]; then
  mkdir -p "$FETCHDIR"
  LINE=$(ssh -o BatchMode=yes -o ConnectTimeout=15 "$FETCH" "ls -l --time-style=+%F_%H%M $RDIR/$RDB-*-daily.dump | sort -k6 | tail -1") || fail "cannot list the backups on $FETCH"
  RFILE=$(echo "$LINE" | awk '{print $NF}'); RSIZE=$(echo "$LINE" | awk '{print $5}')
  [ -n "$RFILE" ] && [ -n "$RSIZE" ] || fail "no $RDB-*-daily.dump on $FETCH:$RDIR"
  case "$(basename "$RFILE")" in *-daily.dump) ;; *) fail "refusing to fetch $RFILE (only -daily dumps)";; esac
  DUMP="$FETCHDIR/$(basename "$RFILE")"
  if [ -f "$DUMP" ] && [ "$(stat -c %s "$DUMP")" = "$RSIZE" ]; then
    say "already fetched: $DUMP ($RSIZE bytes)"
  else
    say "fetching $FETCH:$RFILE ($RSIZE bytes)"
    scp -o BatchMode=yes -q "$FETCH:$RFILE" "$DUMP.part" || { rm -f "$DUMP.part"; fail "scp failed"; }
    [ "$(stat -c %s "$DUMP.part")" = "$RSIZE" ] || { rm -f "$DUMP.part"; fail "size differs after the copy: the previous snapshot is kept"; }
    docker exec -i "$PGC" pg_restore -l < "$DUMP.part" >/dev/null 2>&1 || { rm -f "$DUMP.part"; fail "the fetched dump is not a valid pg_dump -Fc file (pg_restore -l failed)"; }
    mv "$DUMP.part" "$DUMP"
  fi
fi

# ---- 0b. is it a new backup?
if [ -n "$DUMP" ] && [ -f "$DUMP" ]; then
  SHA=$(sha256sum "$DUMP" | cut -d' ' -f1)
  if [ $FORCE = 0 ] && [ -f "$HERE/temp/legacy_nightly_last.sha" ] && [ "$(cut -d' ' -f1 "$HERE/temp/legacy_nightly_last.sha")" = "$SHA" ] \
      && [ "$(cut -d' ' -f2- "$HERE/temp/legacy_nightly_last.sha")" = "$TARGET" ]; then
    RESULT=SKIP; WHAT="no new backup (same sha256 as the last run: $(basename "$DUMP"))"
    say "$WHAT: nothing to do (--force runs anyway)"
    exit 0
  fi
fi

# ---- 1. restore the dump into a fresh snapshot and swap it in
if [ -n "$DUMP" ]; then
  [ -f "$DUMP" ] || fail "dump not found: $DUMP"
  NEXT=${LEGACY}_next
  say "restoring $DUMP into $NEXT ($(du -h "$DUMP" | cut -f1))"
  psqlx postgres "DROP DATABASE IF EXISTS $NEXT" >/dev/null || fail "cannot drop $NEXT"
  psqlx postgres "CREATE DATABASE $NEXT" >/dev/null || fail "cannot create $NEXT"
  docker exec -i "$PGC" pg_restore -U odoo -d "$NEXT" --no-owner --no-privileges < "$DUMP" 2> "$HERE/temp/legacy_nightly_restore.err" || true   # warnings (owners, extensions) are normal: check the content
  EMP=$(psqlx "$NEXT" "select count(*) from hr_employee" 2>/dev/null || echo 0); ATT=$(psqlx "$NEXT" "select count(*) from hr_attendance" 2>/dev/null || echo 0)
  say "restored: $EMP employees, $ATT attendance days ($(wc -l < "$HERE/temp/legacy_nightly_restore.err") restore message lines)"
  [ "${EMP:-0}" -gt 50 ] && [ "${ATT:-0}" -gt 1000 ] || fail "the restored snapshot looks empty or truncated: previous snapshot kept"
  psqlx postgres "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LEGACY' AND pid <> pg_backend_pid()" >/dev/null
  psqlx postgres "DROP DATABASE IF EXISTS $LEGACY" >/dev/null || fail "cannot drop the old snapshot $LEGACY (open connections?)"
  psqlx postgres "ALTER DATABASE $NEXT RENAME TO $LEGACY" >/dev/null || fail "cannot rename $NEXT"
  say "snapshot $LEGACY replaced"
else
  [ "$(psqlx postgres "select count(*) from pg_database where datname = '$LEGACY'")" = 1 ] || fail "no snapshot $LEGACY and no --dump-path"
  say "no --dump-path: using the existing snapshot $LEGACY"
fi

# ---- 2. point the target at the snapshot
psqlx "$TARGET" "INSERT INTO ir_config_parameter (key, value, create_date, write_date) VALUES ('kdvn_legacy.db', '$LEGACY', now(), now()) ON CONFLICT (key) DO UPDATE SET value = '$LEGACY', write_date = now()" >/dev/null \
  || fail "cannot set kdvn_legacy.db in $TARGET (does the database exist?)"

# ---- 3. the bulk import with prune
if [ $FULL = 1 ]; then ARGS="2000-01-01 2099-12-31"; else ARGS="auto auto --window-months $WM"; fi
OUT=$("$HERE/tools/legacy_import.sh" "$TARGET" $ARGS --apply --bulk --all-staff --prune $PFORCE) || fail "legacy_import.sh did not start: $OUT"
ILOG=$(echo "$OUT" | sed -n 's/.*log: //p' | head -1)
say "import started, log $ILOG"
WAITED=0
until grep -q "==== RESULT" "$ILOG" 2>/dev/null; do
  sleep 10; WAITED=$((WAITED + 10))
  if ! docker exec "$CONTAINER" pgrep -f "odoo shell.*-d '?$TARGET'?( |\$)" >/dev/null 2>&1 && ! grep -q "==== RESULT" "$ILOG" 2>/dev/null; then
    sleep 5; grep -q "==== RESULT" "$ILOG" 2>/dev/null || fail "the import process ended without a RESULT (see $ILOG)"
  fi
  [ $WAITED -lt 14400 ] || fail "the import did not finish in 4 hours"
done
sleep 2
PROBLEMS=$(sed -n 's/^\([0-9]*\) problem(s):.*/\1/p' "$ILOG" | tail -1); PROBLEMS=${PROBLEMS:-0}
TOTAL=$(grep "STEP TIME TOTAL" "$ILOG" | awk '{print $4}')
say "import finished in ${TOTAL}s, $PROBLEMS problem(s)"
grep -E "^(hr_attendance|hr_leave|hr_leave_cover|hr_leave_allocation|hr_attendance_request|hr_attendance_raw|hr_attendance_ot_holiday|hr_attendance_ot_holiday_line|resource_calendar_leaves) +(prune candidates|pruned) " "$ILOG" | sed 's/^/   /'
grep -E "NOT deleted" "$ILOG" | sed 's/^/   !! /'
STATUS=0
grep -q "NOT deleted" "$ILOG" && { say "a prune safety limit was hit: check the snapshot"; STATUS=1; }
if [ "$PROBLEMS" -gt "$MAXPROB" ]; then say "more problems ($PROBLEMS) than allowed ($MAXPROB): see $ILOG"; [ $STATUS = 0 ] && STATUS=2; fi

# ---- 4. parity of a past window (the last 2 days are not settled in Odoo 12)
if [ $PARITY = 1 ]; then
  PTO=$(date -d "-3 days" +%F); PFROM=$(date -d "-$((PDAYS + 3)) days" +%F)
  rm -f "$HERE/temp/legacy_nightly_parity.json"
  CPJ=/home/odoo/project${HERE#$PROJECT_HOST}/temp/legacy_nightly_parity.json
  sed -e "s#__FROM__#$PFROM#; s#__TO__#$PTO#" -e "s#/home/odoo/project/.worktrees/attendance/parity.json#$CPJ#" "$HERE/tools/parity_attendance.py" \
    | docker exec -i "$CONTAINER" odoo shell -c "${ODOO_CONF:-/etc/odoo/odoo.conf}" -d "$TARGET" --no-http --log-level=error > "$HERE/temp/legacy_nightly_parity.out" 2>&1
  if grep -q "END rollback" "$HERE/temp/legacy_nightly_parity.out" && [ -f "$HERE/temp/legacy_nightly_parity.json" ]; then
    read -r PN PD < <(python3 -c "import json; d=json.load(open('$HERE/temp/legacy_nightly_parity.json')); print(d['n'], d['ndiff'])")
    say "parity $PFROM .. $PTO: $PD of $PN days differ"
    if [ "$PD" != 0 ]; then
      if python3 -c "import sys; sys.exit(0 if $PD * 100.0 > $PPCT * $PN else 1)"; then say "parity differences above $PPCT %: see temp/legacy_nightly_parity.json"; [ $STATUS = 0 ] && STATUS=2
      else say "parity differences within $PPCT % (listed in temp/legacy_nightly_parity.json)"; fi
    fi
  else
    say "parity run failed: see $HERE/temp/legacy_nightly_parity.out"; [ $STATUS = 0 ] && STATUS=2
  fi
fi
[ $STATUS = 0 ] && [ -n "${SHA:-}" ] && echo "$SHA $TARGET" > "$HERE/temp/legacy_nightly_last.sha"   # remembered only after a clean run
WHAT="import ${TOTAL:-?}s, $PROBLEMS problem(s), parity ${PD:-n/a} of ${PN:-n/a} days differ, $(basename "${DUMP:-existing snapshot}")"
say "done in $(( $(date +%s) - START )) s, exit code $STATUS"
exit $STATUS
