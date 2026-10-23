# Database & File Backups

Nightly logical backups of the Asset Tracker Postgres DB plus all persistent
files that are not in git. Written to be followable at 3am.

## What is protected

| What | How | By |
|---|---|---|
| `asset_tracker` DB (inventory, orders, provisioning, audit trail) | `pg_dump -Fc` as the read-only `backup_reader` role | `scripts/at-backup.sh` |
| Postgres roles + passwords | `pg_dumpall --globals-only` (weekly, Sundays) | `scripts/at-backup.sh` |
| Uploads: photos, receipts, cert-reports, c2c-cert-reports, install-cert-reports, security | tar.gz snapshot | `scripts/at-backup.sh` |
| `/opt/asset_tracker/.env` (incl. `CREDENTIAL_ENCRYPTION_KEY` — without it, encrypted credentials in the DB are unrecoverable) | included in the same tar.gz | `scripts/at-backup.sh` |

NOT backed up (regenerable): app code and static assets (git),
the password blocklist file, Docker images (rebuildable from Dockerfile).

## Schedule & locations

| Where | When | What | Retention |
|---|---|---|---|
| Host `/data/asset-tracker/backups/daily/` | 02:15 UTC nightly (`at-backup.timer`, systemd, `Persistent=true`) | dump + files tar | newest 14 of each |
| Host `/data/asset-tracker/backups/globals/` | Sundays (or `--with-globals`) | globals SQL | newest 12 |

**Copy the backups off the host.** A backup on the same disk as the database
does not survive losing that disk. Pull `/data/asset-tracker/backups/` to
another machine or bucket once a day with whatever you already use (rsync,
rclone, restic), and pull rather than push, so the app host holds no
credentials toward the copy. Keep longer tiers there, for example 14 daily,
8 weekly and 12 monthly.

## Health visibility

`/admin/maintenance` shows a "Database Backup" status row (reads
`status.json`, bind-mounted read-only into the app container):

- **quiet** — last backup < 36 h old
- **amber** — stale > 36 h, dump size > 2× the 7-day median, or no status file
- **red** — stale > 72 h, or the last run failed

Manual check on the host:

```bash
cat /data/asset-tracker/backups/status.json
systemctl list-timers at-backup.timer
journalctl -u at-backup.service -n 20
```

## Restore procedure — full DB (DESTRUCTIVE, real data loss only)

On the host:

```bash
cd /opt/asset_tracker
docker compose stop app

# keep the broken DB as evidence; restore into a fresh one
LATEST=$(ls -1 /data/asset-tracker/backups/daily/asset_tracker_*.dump | sort | tail -1)
docker exec asset_tracker_db psql -U asset_tracker_user -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='asset_tracker' AND pid <> pg_backend_pid()"
docker exec asset_tracker_db psql -U asset_tracker_user -d postgres -c \
  "ALTER DATABASE asset_tracker RENAME TO asset_tracker_broken_$(date +%Y%m%d)"
docker exec asset_tracker_db psql -U asset_tracker_user -d postgres -c "CREATE DATABASE asset_tracker"
docker cp "$LATEST" asset_tracker_db:/tmp/restore.dump
docker exec asset_tracker_db pg_restore -U asset_tracker_user -d asset_tracker --no-owner /tmp/restore.dump
docker exec asset_tracker_db rm /tmp/restore.dump

docker compose start app
# verify, then drop asset_tracker_broken_* when confident
```

If the host itself is gone: copy the newest dump + files tar from the
off-host copy to the new box, bring up the compose stack (fresh cluster
auto-creates `asset_tracker_user` from compose env), then
`psql -f globals_<date>.sql` first (recreates `backup_reader` and any other
roles), then pg_restore as above, then untar files.

## Restore procedure — files

```bash
# restores /data/asset-tracker/<uploads> and /opt/asset_tracker/.env in place
tar -xzf /data/asset-tracker/backups/daily/files_<ts>.tar.gz -C /
# single file: list with tar -tzf, extract with tar -xzf ... -C / <member>
```

## Restore test (monthly habit)

```bash
sudo /opt/asset_tracker/scripts/at-restore-test.sh
```

Restores the newest dump into a scratch DB (`asset_tracker_restore_test`),
row-count spot checks vs live (items, orders, provisioning, audit_log, users,
pending_devices), round-trips one sampled file out of the files tar, drops the
scratch DB. Never touches the live DB. Result lands in
`/data/asset-tracker/backups/last_restore_test.txt`.

Run it monthly and after any Postgres/compose change.

## Least privilege

Dumps run as `backup_reader` (LOGIN + `pg_read_all_data` only — cannot write).
Create it once on the cluster; the weekly globals dump captures it. Only the
weekly globals dump uses the superuser, because `pg_authid` (password hashes)
needs it.

## Example sizing (one small deployment)

| Metric | Value |
|---|---|
| Live DB (`pg_database_size`) | 13 MB |
| `-Fc` dump | 287 KB |
| Files tar (≈30 MB of uploads + .env) | 11.5 MB |
| Globals SQL | 1.2 KB |
| Nightly set | ≈ 12 MB |
| Host at full retention (14 days) | ≈ 170 MB |
| Off-host copy, 14 daily + 8 weekly + 12 monthly | ≈ 420 MB |

The nightly status line records dump size; the maintenance row goes amber if a
dump doubles vs the 7-day median (runaway growth or a dump bug — either is
worth a look).

## Components

| File | Runs on | Purpose |
|---|---|---|
| `scripts/at-backup.sh` | host (root, systemd) | nightly dump + globals + files tar + prune + status |
| `scripts/at-restore-test.sh` | host (sudo, manual) | scratch-DB restore verification |
| `deploy/at-backup.service` + `deploy/at-backup.timer` | host | schedule; install: `sudo cp deploy/at-backup.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now at-backup.timer` |

Prune dry-run: `DRY_RUN=1 scripts/at-backup.sh` (reports victims, deletes
nothing). Sandbox a whole run: `AT_BACKUP_ROOT=/tmp/x scripts/at-backup.sh`.

## Trouble at 3am

| Symptom | Do |
|---|---|
| Maintenance row red "Last backup FAILED" | `journalctl -u at-backup.service -n 50` on the host; the `error` field in `status.json` has the first failing step |
| Row amber/red "Backups stale" | `systemctl list-timers at-backup.timer` — timer gone? reinstall per Components table. Host was off? `Persistent=true` should catch up on boot |
| Row amber "size anomaly" | compare `dump_bytes` vs `median7_bytes` in `status.json`; if growth is real (bulk import), it self-clears as the median catches up |
| Need a backup NOW before something risky | `sudo /opt/asset_tracker/scripts/at-backup.sh --with-globals` |

## Container-path rule

Every `*_UPLOAD_DIR` (in `app/config.py` or `.env`) MUST resolve to a
bind-mounted path, or files land in the container's writable layer —
invisible to the host, absent from this backup, destroyed on recreate.
Verify with a write-through probe: `touch` inside the container, `ls`
the host dir. Two traps found and closed: `PHOTO_UPLOAD_DIR` (.env
pointed at a container-internal path, 2026-07-11) and
`install-cert-reports` (no mount existed; one demo-order PDF was lost
before the fix).
