#!/usr/bin/env bash
# Download the common-password blocklist the password rules check against.
#
# Source: SecLists (MIT licence), Passwords/Common-Credentials/Pwdb_top-1000000.txt,
# pinned to one commit and checked against its sha256, so every install gets
# the same list. The app reads it once at startup (app/password_blocklist.py)
# and keeps only the entries at least PASSWORD_MIN_LENGTH long. Without the
# file the blocklist check is skipped and the length rule still applies.
#
# Run from the repo root:   bash scripts/fetch_password_blocklist.sh
# Inside Docker Compose:    docker compose exec app bash scripts/fetch_password_blocklist.sh
#                           docker compose restart app
set -euo pipefail

COMMIT="997dd861b9fa2623f06f30d5f9085713ce830f0c"
SHA256="e9a88f67aafe65496682dc374559ee714e978bee50314767494c3e37a18c9fc8"
URL="https://raw.githubusercontent.com/danielmiessler/SecLists/${COMMIT}/Passwords/Common-Credentials/Pwdb_top-1000000.txt"
DEST="${PASSWORD_BLOCKLIST_PATH:-data/security/password-blocklist.txt}"

mkdir -p "$(dirname "$DEST")"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

curl -fsSL --retry 3 -o "$tmp" "$URL"
actual="$(sha256sum "$tmp" | cut -d' ' -f1)"
if [ "$actual" != "$SHA256" ]; then
    echo "checksum mismatch: expected $SHA256, got $actual; nothing written" >&2
    exit 1
fi
mv "$tmp" "$DEST"
trap - EXIT
echo "wrote $DEST ($(wc -l < "$DEST") entries); restart the app to load it"
