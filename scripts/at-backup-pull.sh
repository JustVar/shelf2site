#!/usr/bin/env bash
# at-backup-pull.sh — pull Asset Tracker backups from apphost to this
# workstation and apply grandfather-father-son retention. Runs on the
# WORKSTATION (Git Bash), scheduled daily via Windows Task Scheduler
# (task "AssetTracker Backup Pull", 09:30 local, runs-when-late enabled).
#
# Local layout (C:\Users\you\Backups\asset-tracker\):
#   daily/    newest 14 dump + files pairs (mirror of apphost)
#   weekly/   first backup of each ISO week, newest 8
#   monthly/  first backup of each month, newest 12
#   globals/  weekly pg_dumpall --globals-only, newest 12
#
# Manual run:      scripts/at-backup-pull.sh
# Prune dry-run:   DRY_RUN=1 scripts/at-backup-pull.sh
# Docs / restore:  docs/BACKUPS.md
set -uo pipefail

# Keepalives + connect timeout: a scheduled pull must fail fast, never hang.
SSH_OPTS="${AT_SSH_OPTS:--i $HOME/.ssh/id_ed25519 -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4}"
SSH_HOST="${AT_SSH_HOST:-admin@192.0.2.10}"
REMOTE_ROOT="/data/asset-tracker/backups"
LOCAL_ROOT="${AT_BACKUP_LOCAL:-/c/Users/you/Backups/asset-tracker}"

KEEP_DAILY=14
KEEP_WEEKLY=8
KEEP_MONTHLY=12
KEEP_GLOBALS=12
DRY_RUN="${DRY_RUN:-0}"          # 1 = prune reports only, deletes nothing

mkdir -p "$LOCAL_ROOT/daily" "$LOCAL_ROOT/weekly" "$LOCAL_ROOT/monthly" "$LOCAL_ROOT/globals"

# ── 1. fetch anything we do not have yet (pull-only; never writes to apphost)
fetched=0
fetch_missing() {  # $1 = remote subdir, $2 = local subdir
  local f
  for f in $(ssh $SSH_OPTS "$SSH_HOST" "ls -1 $REMOTE_ROOT/$1 2>/dev/null"); do
    if [ ! -f "$LOCAL_ROOT/$2/$f" ]; then
      scp -q $SSH_OPTS "$SSH_HOST:$REMOTE_ROOT/$1/$f" "$LOCAL_ROOT/$2/$f" \
        || { echo "FAIL: scp $1/$f" >&2; exit 1; }
      fetched=$((fetched+1))
    fi
  done
}
fetch_missing daily daily
fetch_missing globals globals
scp -q $SSH_OPTS "$SSH_HOST:$REMOTE_ROOT/status.json" "$LOCAL_ROOT/status.json" 2>/dev/null || true

# ── 2. GFS promotion: keep the FIRST backup of each ISO week / month ────────
date_of() { basename "$1" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}'; }

promote() {  # $1 = weekly|monthly
  local tier="$1" dump d key existing e ekey have pair
  for dump in $(ls -1 "$LOCAL_ROOT/daily"/asset_tracker_*.dump 2>/dev/null | sort); do
    d=$(date_of "$dump")
    if [ "$tier" = weekly ]; then key=$(date -d "$d" +%G-W%V); else key="${d:0:7}"; fi
    have=false
    for existing in $(ls -1 "$LOCAL_ROOT/$tier"/asset_tracker_*.dump 2>/dev/null); do
      e=$(date_of "$existing")
      if [ "$tier" = weekly ]; then ekey=$(date -d "$e" +%G-W%V); else ekey="${e:0:7}"; fi
      [ "$ekey" = "$key" ] && { have=true; break; }
    done
    if [ "$have" = false ]; then
      cp "$dump" "$LOCAL_ROOT/$tier/"
      pair="$LOCAL_ROOT/daily/files_$(basename "$dump" | sed 's/^asset_tracker_//; s/\.dump$//').tar.gz"
      [ -f "$pair" ] && cp "$pair" "$LOCAL_ROOT/$tier/"
      echo "promoted $(basename "$dump") -> $tier/ ($key)"
    fi
  done
}
promote weekly
promote monthly

# ── 3. prune each tier by count ──────────────────────────────────────────────
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
prune "$LOCAL_ROOT/daily/asset_tracker_*.dump"   "$KEEP_DAILY"
prune "$LOCAL_ROOT/daily/files_*.tar.gz"         "$KEEP_DAILY"
prune "$LOCAL_ROOT/weekly/asset_tracker_*.dump"  "$KEEP_WEEKLY"
prune "$LOCAL_ROOT/weekly/files_*.tar.gz"        "$KEEP_WEEKLY"
prune "$LOCAL_ROOT/monthly/asset_tracker_*.dump" "$KEEP_MONTHLY"
prune "$LOCAL_ROOT/monthly/files_*.tar.gz"       "$KEEP_MONTHLY"
prune "$LOCAL_ROOT/globals/globals_*.sql"        "$KEEP_GLOBALS"

# ── 4. staleness breadcrumb (the /admin/maintenance banner is the real alert)
newest=$(ls -1 "$LOCAL_ROOT/daily"/asset_tracker_*.dump 2>/dev/null | sort | tail -n 1)
if [ -n "$newest" ]; then
  age_h=$(( ( $(date +%s) - $(date -d "$(date_of "$newest")" +%s) ) / 3600 ))
  [ "$age_h" -gt 60 ] && echo "WARNING: newest local dump is ~${age_h}h old"
fi
echo "OK: pull complete, $fetched new file(s), $(date)"
