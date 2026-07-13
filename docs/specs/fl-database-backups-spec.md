# Slice: database backups and restore verification

The four-location sync protects code; nothing protects the data. Single Postgres on apphost holds inventory, orders, provisioning, audit trail. This slice makes its loss survivable.

## Work items

1. Nightly logical backup: `pg_dump` (custom format, `-Fc`) via cron/systemd timer on apphost, timestamped, into a dedicated backup directory. Include globals (`pg_dumpall --globals-only`) weekly.
2. Off-box copy: sync each dump to at least ONE location that is not apphost — the workstation is the pragmatic candidate (a pull-based fetch fits the existing apphost->workstation trust direction; reuse the wsync-style pattern). Discovery: confirm available disk both ends.
3. Retention (grandfather-father-son): keep 14 daily, 8 weekly, 12 monthly on the off-box copy (apphost keeps 14 daily only); prune automatically on both ends. Expected footprint at current scale: 1-10 MB per -Fc dump, so ~50-350 MB total across all tiers — measure actuals in item 0 below and record them in the docs.
3a. SIZING DISCOVERY (day one): measure live DB size (`pg_database_size`) and the first dump's size; record both. The nightly status line includes dump size; the staleness indicator (item 5) also goes amber if a dump's size doubles vs the 7-day median (runaway growth or a dump bug — either is worth seeing).
3b. NON-DB DATA: inventory everything persistent outside Postgres — uploaded receipt/checklist files (likely on disk, currently unprotected), .env/config, anything else under the app's volumes. Regenerable artifacts (blocklist file, static assets in git) are excluded. Include the upload directories in the same nightly job via rsync with the same retention, and the restore test verifies one sampled file round-trips.
4. RESTORE TEST — the part that makes it real: restore the latest dump into a scratch database on apphost (`pg_restore` into `asset_tracker_restore_test`), run row-count spot checks against the live DB (items, orders, provisioning, audit), then drop the scratch DB. Script it so it can be re-run; run it once now as the gate, and note a monthly re-run habit.
5. Failure alerting (cheap): the backup script writes a status line; surface staleness in the app's admin System/Maintenance page ("Last backup: <timestamp>", amber >36h, red >72h) — one small fl-banner style row, reusing the maintenance page kit.
6. Document in the repo (docs/): schedule, locations, retention, restore procedure — short enough to follow at 3am.

## Constraints
Backup user with least privilege (read-only role for dumps). Dumps contain customer data — the off-box copy lives on the workstation, not a cloud service, unless Jus decides otherwise later. No app code changes beyond the maintenance-page status row.

## Gates
One full cycle proven end to end: dump -> off-box copy -> restore test passes row counts -> prune logic dry-run. Status row renders in both themes. Standard sync for the repo-side bits (scripts + docs committed).
