#!/usr/bin/env bash
# at-backup.sh — nightly Asset Tracker backup (runs on apphost as root via systemd).
#
# What it does, in order:
#   1. pg_dump (custom format) of the asset_tracker DB as the read-only
#      backup_reader role -> /data/asset-tracker/backups/daily/
#   2. Sundays (or --with-globals): pg_dumpall --globals-only (roles) -> globals/
#   3. tar.gz of upload dirs + /opt/asset_tracker/.env -> daily/
#   4. Prune: keep newest 14 daily dumps + 14 files tars, 12 globals.
#      (GFS weekly/monthly tiers live on the workstation — at-backup-pull.sh.)
#   5. Write status.json (read by the /admin/maintenance page) and append
#      a line to history.jsonl (feeds the dump-size anomaly check).
#
# Manual run:      sudo /opt/asset_tracker/scripts/at-backup.sh
# Force globals:   sudo /opt/asset_tracker/scripts/at-backup.sh --with-globals
# Prune dry-run:   sudo DRY_RUN=1 /opt/asset_tracker/scripts/at-backup.sh
# Schedule:        at-backup.timer, 02:15 UTC nightly (deploy/at-backup.timer)
# Docs / restore:  docs/BACKUPS.md
set -uo pipefail

# Overridable for sandboxed testing (e.g. AT_BACKUP_ROOT=/tmp/at_prune_test).
BACKUP_ROOT="${AT_BACKUP_ROOT:-/data/asset-tracker/backups}"
DAILY_DIR="$BACKUP_ROOT/daily"
GLOBALS_DIR="$BACKUP_ROOT/globals"
STATUS_FILE="$BACKUP_ROOT/status.json"
HISTORY_FILE="$BACKUP_ROOT/history.jsonl"

DB_CONTAINER="asset_tracker_db"
DB_NAME="asset_tracker"
DUMP_ROLE="backup_reader"        # read-only (pg_read_all_data); cannot mutate data
SUPER_ROLE="asset_tracker_user"  # container superuser; needed for pg_dumpall globals

KEEP_DAILY=14
KEEP_GLOBALS=12
DRY_RUN="${DRY_RUN:-0}"          # 1 = prune reports only, deletes nothing

# Everything persistent that is NOT in Postgres and NOT regenerable from git.
# Paths are relative to / so tar members restore cleanly with `tar -xzf ... -C /`.
FILES_SRC=(
  data/asset-tracker/photos
  data/asset-tracker/receipts
  data/asset-tracker/cert-reports
  data/asset-tracker/c2c-cert-reports
  data/asset-tracker/install-cert-reports
  data/asset-tracker/security
  opt/asset_tracker/.env
)

TS=$(date -u +%Y-%m-%d_%H%M)
START=$(date +%s)
DUMP_BYTES=0
FILES_BYTES=0
DUMP_NAME=""
FILES_NAME=""
GLOBALS_DONE=false

# Write status.json + append to history.jsonl. $1 = true|false, $2 = error text.
json_status() {
  local ok="$1" err="$2"
  local dur=$(( $(date +%s) - START ))
  # Median of the last 7 successful dump sizes; alert needs >=4 data points.
  local sizes count median alert=false
  sizes=$(grep '"ok": true' "$HISTORY_FILE" 2>/dev/null | tail -n 7 \
          | grep -oE '"dump_bytes": [0-9]+' | grep -oE '[0-9]+' | sort -n)
  count=$(echo "$sizes" | grep -c . || true)
  median=0
  if [ "$count" -ge 1 ]; then
    median=$(echo "$sizes" | awk -v c="$count" 'NR==int((c+1)/2){print; exit}')
  fi
  if [ "$ok" = true ] && [ "$count" -ge 4 ] && [ "$DUMP_BYTES" -gt $(( median * 2 )) ]; then
    alert=true
  fi
  printf '{"ok": %s, "ts": "%s", "dump_file": "%s", "dump_bytes": %s, "files_file": "%s", "files_bytes": %s, "median7_bytes": %s, "size_alert": %s, "globals_included": %s, "duration_s": %s, "error": "%s"}\n' \
    "$ok" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$DUMP_NAME" "$DUMP_BYTES" \
    "$FILES_NAME" "$FILES_BYTES" "$median" "$alert" "$GLOBALS_DONE" "$dur" "$err" \
    > "$STATUS_FILE"
  cat "$STATUS_FILE" >> "$HISTORY_FILE"
  tail -n 60 "$HISTORY_FILE" > "$HISTORY_FILE.tmp" && mv "$HISTORY_FILE.tmp" "$HISTORY_FILE"
  chown brand:brand "$STATUS_FILE" "$HISTORY_FILE" 2>/dev/null || true
}

fail() {
  echo "BACKUP FAILED: $1" >&2
  json_status false "$1"
  exit 1
}

mkdir -p "$DAILY_DIR" "$GLOBALS_DIR" || { echo "cannot create $DAILY_DIR" >&2; exit 1; }

# ── 1. logical dump (read-only role, custom format) ─────────────────────────
DUMP_NAME="asset_tracker_${TS}.dump"
DUMP="$DAILY_DIR/$DUMP_NAME"
docker exec "$DB_CONTAINER" pg_dump -U "$DUMP_ROLE" -Fc -d "$DB_NAME" > "${DUMP}.part" \
  || fail "pg_dump exited non-zero"
[ -s "${DUMP}.part" ] || fail "dump file is empty"
head -c 5 "${DUMP}.part" | grep -q 'PGDMP' || fail "dump missing PGDMP header"
mv "${DUMP}.part" "$DUMP"
DUMP_BYTES=$(stat -c%s "$DUMP")

# ── 2. weekly globals: roles incl. passwords (Sundays, or forced) ───────────
if [ "$(date -u +%u)" = "7" ] || [ "${1:-}" = "--with-globals" ]; then
  GL="$GLOBALS_DIR/globals_$(date -u +%Y-%m-%d).sql"
  docker exec "$DB_CONTAINER" pg_dumpall -U "$SUPER_ROLE" --globals-only > "${GL}.part" \
    || fail "pg_dumpall --globals-only exited non-zero"
  grep -q "CREATE ROLE" "${GL}.part" || fail "globals dump has no CREATE ROLE lines"
  mv "${GL}.part" "$GL"
  GLOBALS_DONE=true
fi

# ── 3. non-DB files: uploads + .env (regenerable artifacts excluded) ────────
FILES_NAME="files_${TS}.tar.gz"
FILES_TAR="$DAILY_DIR/$FILES_NAME"
tar -czf "${FILES_TAR}.part" -C / "${FILES_SRC[@]}"
rc=$?
# tar rc=1 = "file changed as we read it" — acceptable for live upload dirs
[ "$rc" -le 1 ] || fail "files tar exited $rc"
mv "${FILES_TAR}.part" "$FILES_TAR"
FILES_BYTES=$(stat -c%s "$FILES_TAR")

# ── 4. prune (apphost keeps dailies only; GFS tiers are off-box) ───────────
prune() {  # $1 = glob pattern, $2 = keep count
  local victims
  victims=$(ls -1 $1 2>/dev/null | sort | head -n -"$2")
  [ -z "$victims" ] && return 0
  if [ "$DRY_RUN" = "1" ]; then
    echo "DRY_RUN prune would delete:"; echo "$victims"
  else
    echo "$victims" | xargs -r rm -f
  fi
}
prune "$DAILY_DIR/asset_tracker_*.dump" "$KEEP_DAILY"
prune "$DAILY_DIR/files_*.tar.gz"       "$KEEP_DAILY"
prune "$GLOBALS_DIR/globals_*.sql"      "$KEEP_GLOBALS"

# ── 5. ownership + status (artifacts stay fetchable by the brand pull) ────
chown -R brand:brand "$DAILY_DIR" "$GLOBALS_DIR" 2>/dev/null || true
json_status true ""
echo "OK: dump=${DUMP_BYTES}B files=${FILES_BYTES}B globals=${GLOBALS_DONE} at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
