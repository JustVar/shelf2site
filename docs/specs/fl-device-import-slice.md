# Slice: device import into item_schema (Casey CSV)

Source of truth: `Casey_Postgresdb_data-1783692249371.csv` (544 rows, exported 2026-07-10). The `20260511_Backup_postgresdb` file is a plain-SQL pg_dump from May 11 with hardcoded ids — REFERENCE ONLY, never restore it into the live DB. Jus supplies the CSV path to the Code session (it lives on the workstation).

## Decisions locked (Jus, 2026-07-10)

1. MERGE RULE: match by serial (case-insensitive, trimmed). On match, LIVE WINS — app-managed fields (status, location, containment, custody) keep live values; CSV only fills fields that are currently empty on the live row. Field-level conflicts (both sides non-empty and different) are REPORTED, never applied.
2. SERIAL-LESS ROWS (154): import as-is; the missing-fields triage surfaces them. The literal serial "0" counts as serial-less.
3. DEPLOYED ROWS (288, no order linkage): import with status Deployed; they render as Unassigned deal class on the map until orders link them.

## Import tool requirements

- A migration-style re-runnable script (like 066): dry-run mode FIRST, then apply mode. Idempotent — re-running after apply is a no-op.
- DRY-RUN REPORT GOES TO CHAT BEFORE APPLY (decision gate): counts + per-row listing of {create, fill-blanks update, skip-identical, conflict}, the 11 in-CSV duplicate serials (first occurrence wins, rest listed for manual resolution), and the serial-less set.
- Normalization on ingest: placeholder junk ('0', blank, whitespace-only) in name/model/manufacturer/pn -> NULL; `cog` money strings ("$1,684.86") -> numeric; MACs through the canonical normalize_mac; dates parsed; NULL-string literals -> NULL.
- Never import CSV ids — new rows take sequence ids. Keep a `import_source` provenance note (e.g. notes suffix or dedicated column per what exists) so imported rows are identifiable.
- Known live overlaps to verify in the dry run: USCFS0226001/2/3 family, C2C-SX-000x cameras, RTX GPUs, Samsung SSD — these must MATCH, not duplicate.

## Post-import sequence (same session)

1. Re-run 066 backfill. Expected: partial resolution at best (the CSV contains NO INTERNAL-* serials, so the 24 computer containment rows will still not resolve; the 7 edge/GPU pairs may). Report the new accounting.
2. Spot-checks: inventory total (~16 -> ~550), category tile counts, scan lookup on three imported serials returns already-exists, search returns imported items, item detail renders an imported row cleanly.
3. Render/perf check: inventory list and search with 550+ rows (no pagination exists today — measure, and report if render time is objectionable; that becomes its own small slice, not a blocker).
4. EXPECTATION SET FOR JUS: the triage badge will jump from ~16 to potentially hundreds — that is the import making real data debt visible, not a bug. Report the number.
5. The next nightly backup picks up the enlarged DB — confirm the size delta on the maintenance row (the anomaly alert may fire once on the doubled dump size; that is the alert working).

## Gates

Dry-run report reviewed in Chat -> apply -> post-import checks above -> contract suite -> both-theme spot render of inventory -> four-location sync of the tool + any fixes. All probe data conventions as usual.
