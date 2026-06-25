# Build Certification (F3 / S6) — schema and model spec

Status: APPROVED. The S6a through S6d slices (schema, QA half, Hardware half + all-pass gate, report file uploads) are
implemented and verified. Remaining slices S6e through S6f are specified
below and not yet built. This document is the reference the S6 slices are
built against.

Implementation status:
- S6a (051 migration: 9 columns + 3 indexes; read-only /fulfillment/certifications): DONE
- S6b (per-device cert detail + QA capture, first write path): DONE
- S6c (SMART + co-sign + all-pass gate): DONE
- S6d (report file uploads, build_certification_files child table): DONE
- S6e (composite cert report): not started
- S6f (board button wiring + is_complete board-close + blast-radius check): not started

## What this feature is

A per-device build certification system with an append-only audit trail keyed to the OEM serial number. Certification is a two-person effort completed at two different times, gated on all checks passing. A physical box can be certified more than once over its life (retest after failure, or re-cert after repurposing), and every certification — including failures — is retained as history.

## Core decisions (locked)

- Grain: certification is per individual device, not per order x SKU group. The board button is an entry point to N per-device certifications.
- Audit spine: the OEM serial number (from the box sticker, OEM-issued for both edge boxes and Cloud2 cams). It is snapshotted onto each cert row at certification time so history survives even when a device is repurposed (which creates a new provisioning row) or its order link is nulled.
- Append-only: a terminal cert row (certified or failed) is never mutated. A retest or re-cert creates a new row. An in-progress (pending) row is editable by the two contributors until it reaches a terminal state.
- Two contributors: The QA role captures QA + component inventory + licenses; the Hardware role captures the SMART test + report files. The row tracks each half independently.
- All-pass gate: a device is certified only when both halves are complete and every check passes. Any failure makes the row terminal-failed; a new row is created to retry.
- Two history kinds, distinguished by a reason label on each row (not separate counters): within-effort retries vs lifetime re-certs.
- Home: a dedicated certification view (Option B), organized by date / customer / SKU with search — not a board drawer. The board button deep-links into it.
- Board close: the existing DeviceProvisioning.is_complete flag (option e), layered in later. No new column for closing. This is separate from the cert schema below.

## Certification lifecycle

```
new attempt -> row created (cert_status = pending, reason set)
   QA role submits its half     -> qa_status = complete
   Hardware role submits its half -> hw_status = complete
   when both halves complete:
       all checks pass       -> cert_status = certified   (row frozen, history)
       any check fails        -> cert_status = failed      (row frozen, history)
   a failed device, after rebuild or OTA, gets a NEW row (reason = retest)
   a repurposed / returned box gets a NEW row (reason = repurpose | pilot_return)
```

A box's full history = all cert rows sharing its oem_serial, ordered by created_at, with reason labeling each.

## Existing columns on build_certification (kept as-is)

From app/models.py:1881. These already exist; the migration does not touch them.

| column | type | role |
|---|---|---|
| id | int PK | |
| device_provisioning_id | int FK -> device_provisioning, CASCADE, not null | live link to the provisioning instance |
| device_uuid | varchar(64) null | convenience id |
| hardware_validation | JSONB null | component inventory + SMART (shape below) |
| qa_checklist | JSONB null | the 5 QA checks (shape below) |
| license_counts | JSONB null | assigned / ordered (shape below) |
| appliance_version | varchar(64) null | Appliance version string |
| certified_by | varchar(128) null | QA half signer |
| co_certified_by | varchar(128) null | Hardware/SMART half signer |
| certified_at | datetime null | when the QA half landed |
| checklist_file_path | varchar(512) null | legacy single-path; superseded by a file child table in S6d |
| created_at | datetime server_default now | row creation |

## New columns (the S6a migration)

| column | type | default | null | purpose |
|---|---|---|---|---|
| oem_serial | varchar(64) | — | yes (app-required) | audit spine; snapshotted at cert time |
| reason | varchar(20) | 'initial' | no | initial / retest / repurpose / pilot_return |
| qa_status | varchar(20) | 'pending' | no | QA half: pending / complete |
| hw_status | varchar(20) | 'pending' | no | Hardware half: pending / complete |
| cert_status | varchar(20) | 'pending' | no | computed terminal: pending / certified / failed |
| co_certified_at | datetime | null | yes | when the Hardware half landed (mirrors certified_at) |
| customer_name | varchar(256) | null | yes | snapshot at cert time (durable for the index + audit) |
| order_number | varchar(64) | null | yes | snapshot at cert time |
| sku | varchar(128) | null | yes | snapshot at cert time |

Indexes to add: oem_serial (box-history lookups), cert_status (index-page filtering), created_at (date ordering).

Note on oem_serial nullability: nullable at the DB level so the migration cannot fail on an edge case where the polymorphic device lookup does not resolve, but the application requires it on every cert. device_provisioning uses a polymorphic pointer (device_table + device_id, models.py:999-1000), so the serial is resolved through whichever serial-bearing table device_table names and then snapshotted — the cert row does not depend on that join staying valid.

## JSONB shapes (locked)

qa_checklist — five checks, checked/unchecked, all required to pass. Map keyed by stable slug; labels live in code.

```json
{
  "hardware":     {"checked": true},
  "pva_events":   {"checked": true},
  "searches":     {"checked": true},
  "netplan":      {"checked": true},
  "registration": {"checked": true}
}
```

hardware_validation — variable-length component inventory (QA) plus the SMART test (Hardware). type is a fixed vocab (cpu / gpu / ram / hdd / ssd), repeatable so a device can list multiple GPUs or drives. model is free text. ok is the QA per-component validation.

```json
{
  "components": [
    {"type": "cpu", "model": "Intel i7-14700H", "ok": true},
    {"type": "gpu", "model": "Nvidia RTX A1000", "ok": true},
    {"type": "ssd", "model": "Samsung 990 1TB", "ok": true},
    {"type": "ssd", "model": "Samsung 990 2TB", "ok": true}
  ],
  "smart_test": {"result": "pass", "by": "casey", "at": "2026-06-24T15:00:00Z"}
}
```

license_counts — two integers, per device, hand-entered at cert time.

```json
{"assigned": 16, "ordered": 16}
```

## Contributor split

- QA half (qa_status, certified_by, certified_at): qa_checklist (5 items), hardware_validation.components (inventory + ok), license_counts, appliance_version.
- Hardware half (hw_status, co_certified_by, co_certified_at): hardware_validation.smart_test, and the report file uploads (S6d).

## All-pass gate (how cert_status is computed)

Computed in the route and written to cert_status when both halves are complete:

- certified: qa_status = complete AND hw_status = complete AND all five qa_checklist items checked AND every components[].ok is true AND smart_test.result = pass.
- failed: both halves submitted AND any of the above checks fails.
- pending: either half not yet complete.

## Board close (separate from this schema — S6f)

Close happens only when cert_status = certified through the all-pass gate (S6c); there is no one-click close that skips the gate. When a device reaches cert_status = certified, set DeviceProvisioning.is_complete = true and completed_at = now, and add DeviceProvisioning.is_complete == False to the device_rows query (routes/fulfillment.py:325) so certified devices drop off the Building board. A repurposed/returned box gets a new provisioning row (is_complete = false again), so it reappears for re-cert while prior cert rows remain as history. Blast-radius check required first: adding the is_complete filter hides every already-complete device, not only newly certified ones — measure how many rows are is_complete = true before applying.

## Backfill

The build_certification table has no inserting route today, so it is expected to be empty — the migration adds columns to an empty table, no data backfill. Existing ready_for_handoff devices are derived-complete via build_cert_complete (computed from device stages, routes/fulfillment.py:366) and have no formal cert rows; they surface in the new index as needing formal certification rather than being auto-backfilled.

## RBAC

- Reads (index, detail view): require_provisioning_viewer.
- Writes (submit either half): require_provisioning_manager (matches update_ship_details and create_deployment).

## Slice plan

- S6a — this migration + a read-only certification index page (/fulfillment/certifications): lists devices needing/having cert, organized by date / customer / SKU, with search. Proves the schema, ships the nav home. No writes.
- S6b — per-device cert detail view + QA capture (5 checks, component inventory, licenses, appliance_version). First write path (qa_status -> complete).
- S6c — Hardware contribution (SMART result + sign-off via co_certified_by), partial-state handling, and the computed all-pass cert_status gate (hw_status -> complete, terminal compute).
- S6d — report file uploads per device. Needs a child table (build_certification_files) for multiple files per cert; its own schema decision, not pre-baked here. Intersects the /tmp cleanup track.
- S6e — composite downloadable certification report per device (QA + hardware + SMART + licenses + files into one document).
- S6f — board button wiring + is_complete board-close (option e) + the blast-radius check.

## Deferred / not in this spec

- The file child table (build_certification_files) — designed in S6d.
- The report document format (PDF vs print view) — designed in S6e.
- The board-exit migration, if any beyond is_complete — revisited in S6f.
