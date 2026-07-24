#!/usr/bin/env bash
# at-sync-commit.sh — stage, commit, bundle, verify tip. Run on apphost.
# Usage:  at-sync-commit.sh <path> [<path>...]   (commit message on stdin)
# Emits PREV / NEW / BUNDLE for the workstation wsync step.
set -uo pipefail

REPO="/opt/asset_tracker"
cd "$REPO" || { echo "ABORT: cannot cd $REPO" >&2; exit 1; }

if [ "$#" -lt 1 ]; then
  echo "ABORT: need at least one path to stage" >&2; exit 1
fi

PREV=$(git rev-parse --short=7 HEAD)

# Skip paths already staged for deletion (e.g. via `git rm`): a plain `git add`
# fails on them ("pathspec did not match"), aborting before the commit. Filter
# those out but keep the add scoped to the surviving paths in "$@" — the staged
# deletion rides into the commit on its own. A genuinely bad path (absent AND
# not staged-deleted) still reaches git add and errors, exactly as before.
staged_deletes=$(git diff --cached --name-only --diff-filter=D)
declare -a to_add=()
for p in "$@"; do
  if printf '%s\n' "$staged_deletes" | grep -qxF -- "$p"; then
    echo "note: '$p' already staged for deletion; not re-adding" >&2
    continue
  fi
  to_add+=("$p")
done
if [ "${#to_add[@]}" -gt 0 ]; then
  git add -- "${to_add[@]}" || { echo "ABORT: git add failed" >&2; exit 1; }
fi

if git diff --cached --quiet; then
  echo "ABORT: nothing staged. Paths unchanged?" >&2; exit 1
fi

git commit -F - || { echo "ABORT: commit failed" >&2; exit 1; }
NEW=$(git rev-parse --short=7 HEAD)

if [ "$PREV" = "$NEW" ]; then
  echo "ABORT: HEAD did not advance ($PREV)" >&2; exit 1
fi

BUNDLE="/tmp/sync_${PREV}_${NEW}.bundle"
git bundle create "$BUNDLE" "${PREV}..main" >/dev/null \
  || { echo "ABORT: bundle create failed" >&2; exit 1; }

TIP=$(git bundle list-heads "$BUNDLE" | awk '/refs\/heads\/main/{print substr($1,1,7)}')
if [ "$TIP" != "$NEW" ]; then
  echo "ABORT: bundle tip $TIP != NEW $NEW" >&2; exit 1
fi

echo "PREV=$PREV"
echo "NEW=$NEW"
echo "BUNDLE=$BUNDLE"
echo "TIP=$TIP (matches NEW)"
echo "OK -> on workstation run:  wsync $PREV $NEW"
