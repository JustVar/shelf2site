# C2C Cert PDF + Per-Serial History (append-only)

Status: DECIDED (Chat), building. Baseline `b9defe5`.
Scope: C2C surface only. Build in sub-slices 5a-5e; browser-verify at two seams;
commit + full four-location sync at two consolidation points only.

## Problem

C2C certification is one mutable row per provisioning row, checklist-only, with no
source-file attachments, no generated certificate PDF, no cancel/re-cert workflow,
and no per-serial history. This slice makes the cert an **append-only event log**
with **source-file uploads**, a **generated composite PDF**, a **cancel +
copy-forward re-cert** workflow, and a **per-serial history timeline**.

## Grounded facts (already read; do not re-derive)

- `c2c_certify` is a JSON handler (`await request.json()`) - checklist booleans +
  `firmware_evidence` (JSONB) + `notes`. It cannot carry file bytes; uploads need a
  separate multipart endpoint.
- Cert is keyed on `device_provisioning_id` (FK CASCADE), **never `item_id`**. A new
  provisioning row already gets a fresh cert. Per-serial history across a camera =
  its provisioning rows, each with its cert event(s).
- **Live index is NON-unique**: `idx_c2c_cert_provisioning btree(device_provisioning_id)`.
  Many rows per provisioning row are already allowed - **no index change needed**.
- `C2CCertification` today: id, device_provisioning_id, camera_serial_snapshot,
  status ('pending'|'certified'), checklist JSONB, firmware_evidence JSONB, notes,
  certified_by, certified_at, created_at, created_by. **No file/PDF columns.**
- The board cert-status read is an `outerjoin(C2CCertification == DeviceProvisioning.id)`
  pulling `C2CCertification.status` in `_c2c_board_data.cam_records`. With multiple
  cert rows per provisioning row this fans out to one row per event - it MUST become a
  latest-event join.
- File-storage app pattern: **bytes on disk under a `stored_name` + metadata in DB**
  (no blobs/bytea). Precedents: `InstallationCertification` (single-file cols),
  `BuildCertificationFile` (many-files child table). Build-cert also does a PyMuPDF
  composite merge (font token `hebo` = Helvetica-Bold; needs a LIVE render test -
  py_compile/import pass even with a bad font token).
- No `revert` concept on the C2C surface today. Cancel-certification is net-new.

## DECIDED event model (draft-finalize)

A provisioning row has an **append-only sequence** of cert events. Status values:
`pending` | `certified` | `cancelled`.

- **One mutable pending draft** per provisioning row at a time. Certify get-or-creates
  the current draft: if the latest event is `pending`, reuse it; else (latest is
  certified/cancelled, or none) start a fresh `pending` draft. Checklist edits and
  source-file uploads accumulate on this draft.
- **Certify (all-pass) finalizes the draft IN PLACE**: `pending -> certified`, set
  `certified_by`/`certified_at`, generate the composite PDF. Once `certified`, the row
  is **frozen** - never mutated again.
- **Cancel APPENDS a new `cancelled` event** (`cancel_reason` + `cancelled_by` +
  `cancelled_at`); the prior certified row is untouched. No PDF/files on a cancel event.
- **Re-cert** (latest event is `cancelled`) APPENDS a new `pending` draft, copy-forward
  the prior event's source files (selective replace allowed), then finalize.
- **Immutability**: certified and cancelled rows are frozen; only a `pending` draft is
  mutable. **Latest event wins** for status. A row with no events, or whose latest event
  is `cancelled`, reads **pending**.
- **Never touch `is_complete`** on certify or cancel (option D - stays False for life).

### Latest-event status read (load-bearing)

Every cert-status read switches to latest-event semantics. Latest = `max(id)` per
`device_provisioning_id` (id is monotonic). The `cam_records` outer-join becomes a join
against a latest-cert subquery (`group by device_provisioning_id`, `max(id)`), then
`C2CCertification.id == max_id`. `cert_status == "certified"` (certified bucket) is only
true when the latest event is certified; `pending`/`cancelled`/none all read pending.

## Source files (child table, per event)

New table **`c2c_certification_files`**: FK -> `c2c_certification` (the event row) CASCADE,
`stored_name`, `original_name`, `content_type`, `size_bytes`, `uploaded_by`,
`uploaded_at`, `kind` ('source' | 'composite'). The generated composite PDF is also a row
here with `kind='composite'` (single source of truth for all cert artifacts; download
resolves by kind). Each event OWNS its own file rows.

- New MULTIPART upload endpoint `POST /fulfillment/c2c/{provisioning_id}/cert-file`:
  get-or-create the current pending draft, store bytes on disk under a generated
  `stored_name`, write metadata (`kind='source'`). Serve + delete endpoints as needed.
- 3+ source files per cert is typical.
- Bytes live on disk (path per the app pattern - a cert-files upload dir); DB stores
  metadata + `stored_name`.

## Composite PDF (PyMuPDF)

Generated at CERTIFY time (all-pass finalize): merge the event's `kind='source'` files
+ cert data (checklist, firmware_evidence, serial, certifier, date) into ONE composite
PDF; store bytes on disk + a `kind='composite'` file row. Use `hebo` for Helvetica-Bold.
**Validated with a LIVE render call** (not py_compile) - Chat also verifies it opens in
the browser.

## Copy-forward on re-cert (selective replace)

When a cancelled cert is re-certified, the new pending draft INHERITS the prior event's
`kind='source'` files by default - duplicate the child rows (and the on-disk files, or
reference the same bytes) for the new event; no forced re-upload. The user may
remove/replace individual inherited files before certifying. The old event + its files +
its composite PDF are frozen history, never modified.

## History view (per-serial timeline)

New UI: given a camera (item_id / serial), show the full cert timeline across ALL its
provisioning rows - every certified and cancelled event in order, each linking to its
composite PDF + source files, with certifier/date and cancel reason where applicable.
Self-contained `.c2c-*` / fulfillment CSS with hard hex fallbacks (standalone templates
do not resolve `--fl-*`).

## Certify UI changes

File input + current-file list in the certify modal (`.c2c-modal` chrome). On a re-cert,
show inherited files with remove/replace controls.

## Build structure (5a-5e)

- **5a - append-only foundation.** Migration: add `cancel_reason`, `cancelled_by`,
  `cancelled_at`; status vocabulary gains `cancelled` (varchar(16) fits; no index change).
  Rewrite certify to the draft-finalize model (get-or-create latest pending draft).
  Rewrite every cert-status read to latest-event. **SEAM 1 (browser-verify):** existing
  certify unbroken; board splits pending/certified via latest-event; a freshly-certified
  cam shows certified; row 254 (no cert) reads pending. **-> Consolidation commit + full
  sync #1** after Chat verifies 5a.
- **5b - file upload + child table.** `c2c_certification_files`, multipart upload +
  serve/delete, certify-modal file input + list.
- **5c - composite PDF.** PyMuPDF merge at certify, store, download link. **SEAM 2
  (browser-verify):** certify with 2-3 files -> composite PDF generates, downloads, and
  OPENS (live render gate - hebo).
- **5d - cancel + copy-forward.** Cancel endpoint (reason + who + when, same gate),
  cancelled event, re-cert appends a new pending draft, copy-forward with selective replace.
- **5e - history view.** Per-serial cert timeline UI. **-> Consolidation commit + full
  sync #2** after Chat verifies 5b-5e.

## Do NOT

- Mutate a frozen (certified/cancelled) event; append only.
- Touch `is_complete` on certify/cancel (option D).
- Store PDF/file bytes in the DB (bytes on disk + metadata).
- Claim the composite PDF works from py_compile/import alone - live render only.
- Rename cert code identifiers or routes gratuitously.
- Chain the two remote pushes (separate commands in wsync).
- Commit + sync after every sub-slice - only at the two consolidation points.
