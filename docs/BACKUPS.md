# Database & File Backups

Nightly logical backups of the Asset Tracker Postgres DB plus all persistent
files that are not in git. Written to be followable at 3am.

## What is protected

| What | How | By |
|---|---|---|
| `asset_tracker` DB (inventory, orders, provisioning, audit trail) | `pg_dump -Fc` as the read-only `backup_reader` role | `scripts/at-backup.sh` |
| Postgres roles + passwords | `pg_dumpall --globals-only` (weekly, Sundays) | `scripts/at-backup.sh` |
| Uploads: photos, receipts, cert-reports, c2c-cert-reports, security | tar.gz snapshot | `scripts/at-backup.sh` |
| `/opt/asset_tracker/.env` (incl. `CREDENTIAL_ENCRYPTION_KEY` — without it, encrypted credentials in the DB are unrecoverable) | included in the same tar.gz | `scripts/at-backup.sh` |

NOT backed up (regenerable): app code and static assets (git, four-way synced),
the password blocklist file, Docker images (rebuildable from Dockerfile).

## Schedule & locations

| Where | When | What | Retention |
|---|---|---|---|
| apphost `/data/asset-tracker/backups/daily/` | 02:15 UTC nightly (`at-backup.timer`, systemd, `Persistent=true`) | dump + files tar | newest 14 of each |
| apphost `/data/asset-tracker/backups/globals/` | Sundays (or `--with-globals`) | globals SQL | newest 12 |
| Workstation `C:\Users\you\Backups\asset-tracker\` | 09:30 local daily (Task Scheduler: "AssetTracker Backup Pull", runs late if machine was asleep) | pull of everything above + GFS | daily 14 / weekly 8 / monthly 12 / globals 12 |

GFS = grandfather-father-son: the workstation pull promotes the first backup of
each ISO week into `weekly/` and the first of each month into `monthly/`.
The pull is SSH pull-only (workstation → apphost); apphost has no credentials
toward the workstation.

## Health visibility

`/admin/maintenance` shows a "Database Backup" status row (reads
`status.json`, bind-mounted read-only into the app container):

- **quiet** — last backup < 36 h old
- **amber** — stale > 36 h, dump size > 2× the 7-day median, or no status file
- **red** — stale > 72 h, or the last run failed

Manual check on apphost:

```bash
cat /data/asset-tracker/backups/status.json
systemctl list-timers at-backup.timer
journalctl -u at-backup.service -n 20
```

## Restore procedure — full DB (DESTRUCTIVE, real data loss only)

On apphost:

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

If apphost itself is gone: copy the newest dump + files tar from the
workstation (`Backups\asset-tracker\daily\`) to the new box, bring up
the compose stack (fresh cluster auto-creates `asset_tracker_user` from
compose env), then `psql -f globals_<date>.sql` first (recreates
`backup_reader`/`casey` roles), then pg_restore as above, then untar files.

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

Run it monthly and after any Postgres/compose change. Last full pass:
2026-07-10 (all 6 tables exact match, file round-trip PASS).

## Least privilege

Dumps run as `backup_reader` (LOGIN + `pg_read_all_data` only — cannot write).
Created 2026-07-10 directly on the cluster (cluster-level, like the `casey`
role; captured by the weekly globals dump). Only the weekly globals dump uses
the superuser, because `pg_authid` (password hashes) needs it.

## Sizing actuals (measured 2026-07-10)

| Metric | Value |
|---|---|
| Live DB (`pg_database_size`) | 13 MB |
| `-Fc` dump | 287 KB |
| Files tar (≈30 MB of uploads + .env) | 11.5 MB |
| Globals SQL | 1.2 KB |
| Nightly set | ≈ 12 MB |
| apphost at full retention (14 days) | ≈ 170 MB |
| Workstation at full GFS (34 sets) | ≈ 420 MB |

The nightly status line records dump size; the maintenance row goes amber if a
dump doubles vs the 7-day median (runaway growth or a dump bug — either is
worth a look).

## Components

| File | Runs on | Purpose |
|---|---|---|
| `scripts/at-backup.sh` | apphost (root, systemd) | nightly dump + globals + files tar + prune + status |
| `scripts/at-restore-test.sh` | apphost (sudo, manual) | scratch-DB restore verification |
| `scripts/at-backup-pull.sh` | workstation (Git Bash) | off-box pull + GFS retention |
| `deploy/at-backup.service` + `deploy/at-backup.timer` | apphost | schedule; install: `sudo cp deploy/at-backup.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now at-backup.timer` |

Prune dry-run on either script: `DRY_RUN=1 <script>` (reports victims, deletes
nothing). Sandbox a whole run: `AT_BACKUP_ROOT=/tmp/x at-backup.sh` /
`AT_BACKUP_LOCAL=/tmp/y at-backup-pull.sh`.

## Trouble at 3am

| Symptom | Do |
|---|---|
| Maintenance row red "Last backup FAILED" | `journalctl -u at-backup.service -n 50` on apphost; the `error` field in `status.json` has the first failing step |
| Row amber/red "Backups stale" | `systemctl list-timers at-backup.timer` — timer gone? reinstall per Components table. Host was off? `Persistent=true` should catch up on boot |
| Row amber "size anomaly" | compare `dump_bytes` vs `median7_bytes` in `status.json`; if growth is real (bulk import), it self-clears as the median catches up |
| Pull not running | Task Scheduler → "AssetTracker Backup Pull" → Last Run Result; log at `Backups\asset-tracker\pull.log` |
| Need a backup NOW before something risky | `sudo /opt/asset_tracker/scripts/at-backup.sh --with-globals` |
