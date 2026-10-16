#!/usr/bin/env bash
# at-restore-test.sh — prove the latest backup actually restores.
#
#   1. pg_restore the newest daily dump into a scratch DB
#      (asset_tracker_restore_test) inside the db container.
#   2. Row-count spot checks vs the live DB for key tables
#      (small drift = writes since the dump; that is tolerated and shown).
#   3. Round-trip one sampled file out of the newest files tar (byte compare).
#   4. Drop the scratch DB and clean up. Never touches the live DB.
#
# Run:   sudo /opt/asset_tracker/scripts/at-restore-test.sh
# Habit: monthly, and after any Postgres/compose change. See docs/BACKUPS.md.
set -uo pipefail

BACKUP_ROOT="/data/asset-tracker/backups"
FILE_OWNER="${AT_FILE_OWNER:-deploy}"
DAILY_DIR="$BACKUP_ROOT/daily"
RESULT_FILE="$BACKUP_ROOT/last_restore_test.txt"
DB_CONTAINER="asset_tracker_db"
LIVE_DB="asset_tracker"
SCRATCH_DB="asset_tracker_restore_test"
SUPER="asset_tracker_user"

# Spot-check tables: high-value business data + the audit trail.
CHECK_TABLES="item_schema.items public.customer_orders public.device_provisioning public.audit_log public.users public.pending_devices"

FAILS=0

psql_c() { docker exec "$DB_CONTAINER" psql -U "$SUPER" -d "$1" -Atc "$2"; }

DUMP=$(ls -1 "$DAILY_DIR"/asset_tracker_*.dump 2>/dev/null | sort | tail -n 1)
TARBALL=$(ls -1 "$DAILY_DIR"/files_*.tar.gz 2>/dev/null | sort | tail -n 1)
[ -n "$DUMP" ] || { echo "FAIL: no dump found in $DAILY_DIR" >&2; exit 1; }

echo "Restore test — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Dump:  $DUMP"
echo "Files: ${TARBALL:-<none>}"

# ── 1. fresh scratch DB + restore ───────────────────────────────────────────
psql_c postgres "DROP DATABASE IF EXISTS $SCRATCH_DB" >/dev/null
psql_c postgres "CREATE DATABASE $SCRATCH_DB" >/dev/null
docker cp "$DUMP" "$DB_CONTAINER:/tmp/at_restore_test.dump"
if docker exec "$DB_CONTAINER" pg_restore -U "$SUPER" -d "$SCRATCH_DB" --no-owner --exit-on-error /tmp/at_restore_test.dump; then
  echo "pg_restore: OK"
else
  echo "pg_restore: FAILED"
  FAILS=$((FAILS+1))
fi

# ── 2. row-count spot checks (live vs restored) ─────────────────────────────
printf "%-35s %10s %10s  %s\n" "table" "live" "restored" "verdict"
for t in $CHECK_TABLES; do
  live=$(psql_c "$LIVE_DB" "SELECT count(*) FROM $t")
  rest=$(psql_c "$SCRATCH_DB" "SELECT count(*) FROM $t" 2>/dev/null) || rest="ERR"
  if [ "$rest" = "ERR" ]; then
    verdict="FAIL (table missing in restore)"; FAILS=$((FAILS+1))
  elif [ "$rest" = "$live" ]; then
    verdict="PASS"
  else
    diff=$(( live - rest )); [ "$diff" -lt 0 ] && diff=$(( -diff ))
    tol=$(( live / 20 )); [ "$tol" -lt 5 ] && tol=5   # 5% or 5 rows, whichever is larger
    if [ "$diff" -le "$tol" ]; then
      verdict="PASS (drift $(( live - rest )) since dump)"
    else
      verdict="FAIL (drift $(( live - rest )))"; FAILS=$((FAILS+1))
    fi
  fi
  printf "%-35s %10s %10s  %s\n" "$t" "$live" "$rest" "$verdict"
done

# ── 3. sample-file round-trip out of the files tar ──────────────────────────
if [ -n "$TARBALL" ]; then
  member=$(tar -tzf "$TARBALL" | grep -E '^(data|opt)/' | grep -vE '/$' | grep -vE '\.env$' | head -n 1)
  if [ -z "$member" ]; then
    echo "file round-trip: SKIP (tar has no regular files yet)"
  else
    tmp=$(mktemp -d)
    tar -xzf "$TARBALL" -C "$tmp" "$member"
    if [ -f "/$member" ] && cmp -s "$tmp/$member" "/$member"; then
      echo "file round-trip: PASS ($member)"
    elif [ ! -f "/$member" ]; then
      echo "file round-trip: WARN ($member no longer on live disk — deleted since backup)"
    else
      echo "file round-trip: FAIL ($member differs from live)"; FAILS=$((FAILS+1))
    fi
    rm -rf "$tmp"
  fi
fi

# ── 4. cleanup ───────────────────────────────────────────────────────────────
docker exec "$DB_CONTAINER" rm -f /tmp/at_restore_test.dump
psql_c postgres "DROP DATABASE IF EXISTS $SCRATCH_DB" >/dev/null

if [ "$FAILS" -eq 0 ]; then RES="PASS"; else RES="FAIL ($FAILS failing check(s))"; fi
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $RES dump=$(basename "$DUMP")" > "$RESULT_FILE"
chown "$FILE_OWNER:$FILE_OWNER" "$RESULT_FILE" 2>/dev/null || true
echo "RESULT: $RES"
[ "$FAILS" -eq 0 ]
