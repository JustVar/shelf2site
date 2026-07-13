# Build-Cert "Mimic C2C" Port — Design Spec

**Baseline:** main HEAD `66a8688` (2026-07-07).
**Status:** DECIDED in Chat. This spec is the build contract for sub-slices B1–B5. Do not re-open settled points.
**Companion:** `docs/specs/c2c-cert-pdf-history.md` — the C2C append-only model this port mirrors.
**Provenance:** design decided from an adversarially-verified scoping pass (7/8 load-bearing claims CONFIRMED, 1 REFUTED-and-corrected). Facts below are read-facts with anchors *as of 66a8688*; re-read anchors right before editing — line numbers drift.

## Goal

Bring the build-certification subsystem (Edge Box QA + Hardware sign-off, `app/routes/fulfillment.py`) onto the C2C append-only pattern: freezable **attempts**, an explicit **cancel** event, copy-forward **re-certification**, a **persisted + self-checked composite PDF**, and a **per-serial attempt history** timeline — WITHOUT rewriting the working dual-signoff flow.

## Grounded facts (do not re-derive; RE-READ anchors before editing)

- Build-cert is NOT append-only today: QA + HW sign-offs share ONE write path `_apply_cert_half` (`fulfillment.py:1019`); both halves MUTATE the SAME row; a new row is added only when no open pending attempt exists (`:1027/1029/1031/1043`). [LBC-1 CONFIRMED]
- Subject key is **`oem_serial`**, NOT `device_provisioning_id` — `_open_attempt`, history, and file lookups filter by `oem_serial` (`:1010/1200/1233`). `device_provisioning_id` is written but not the lookup key. Per-serial history is already serial-keyed. [LBC-6 CONFIRMED]
- `reason` column exists (`varchar(20)` DEFAULT `'initial'`, `models.py:1942`) but is DEAD — only ever written `'initial'` (`:1041`). [LBC-2 CONFIRMED]
- `device_provisioning_id` is NON-unique (plain `idx_build_cert_device`, migration `050:53-57`); append-many is the intended contract. Do NOT add uniqueness. [LBC-3 CONFIRMED]
- An attempt is terminal only when BOTH halves complete: the gate (`:1073-1075`) sets `cert_status` via `_compute_cert_gate` → `'certified'` iff all 5 QA checks + components ok + smart=='pass', else `'failed'`. [LBC-4 CONFIRMED]
- The report PDF uses PyMuPDF (`import fitz`), generated on-the-fly per GET, streamed, NEVER persisted, no self-check, merges ALL files (no kind filter). `build_certification_files` has NO `kind` column (`:1645-1703`, `models.py:1952-1965`). [LBC-5 CONFIRMED]
- No cancel path: no endpoint, no `'cancelled'` status, no `cancel_*` columns. [LBC-7 CONFIRMED]
- `certified_at` is set at QA-half time (`:1063`) and never updated — means "QA sign-off time", not "certification time". [open Q, verified]
- `co_certified_by` IS rendered as the HW submitter (`certification_detail.html:257`); only the history-table dict fields `h.co_certified_by`/`h.co_certified_at` go unrendered (history table shows only `h.certified_by` at `:300`). [LBC-8 correction]
- `cert_status` is a free `String(20)` — `'cancelled'` fits with NO enum/schema change; only the code writing it changes.

## Decided design — attempt-level append-only (Option A/C)

- The **ATTEMPT** is the unit. The QA → HW dual-signoff flow is PRESERVED — do NOT rewrite `_apply_cert_half` into per-signoff events.
- An attempt FREEZES on finalize (both halves + gate) or on cancel.
- Re-cert opens a NEW attempt row (append-many, already permitted; `device_provisioning_id` stays NON-unique).
- Cancel APPENDS a cancelled event (new `cancel_*` columns + `cert_status='cancelled'`).
- Per-serial history LISTS attempts (not individual sign-offs).

## Decided specifics

1. **Cancel** = mirror C2C migration 059 exactly: add `cancel_reason` / `cancelled_by` / `cancelled_at` to `build_certification`, plus a `'cancelled'` `cert_status` value.
2. **`reason`**: re-cert attempts write `reason='recert'` (first attempt stays `'initial'`). Activates the dead column; history distinguishes re-certs.
3. **`certified_at`**: MOVE its assignment from QA-half time to the GATE (finalize time, `fulfillment.py:1073-1075`), matching C2C. This touches the working sign-off flow → regression smoke required (SEAM 1).
4. **Composite PDF**: persist on finalize as a `kind='composite'` `BuildCertificationFile` (mirror C2C `_generate_c2c_composite`) WITH a live-render self-check; filter the merge to `kind=='source'` so a persisted composite is never re-merged.
5. **`checklist_file_path`**: DROP the dead column via migration. Use `DROP COLUMN IF EXISTS` (idempotent, non-destructive — confirmed zero reads/writes).

## Kept separate / OUT OF SCOPE (do not build)

- **Two notions of done**: `cert_status` (quality gate) and `prov.is_complete` (close route) STAY INDEPENDENT, as today. Cancel only changes `cert_status`; `is_complete` stays orthogonal. The existing close-gate (`cert_status=='certified'`) correctly prevents re-closing a cancelled cert until re-certified. Do NOT unify.
- **Distinct-signer check** (QA != HW): NOT added this port.

## Migration numbering

Next free migration number is **061** (053/054 = installation_certification; 055–060 = C2C/provisioning). B1's schema changes land in a single migration `061_build_cert_cancel_kind_dropchecklist.py`.

## Build structure — B1–B5 (build in order; browser-verify at the SEAMS; sync at 2 consolidation points only)

**B1 — schema/foundation.** Migration 061: add `cancel_*` columns (build_certification) + `kind` column + index (build_certification_files) + `DROP COLUMN IF EXISTS checklist_file_path` (build_certification). Model updates (BuildCertification: +cancel_*, −checklist_file_path; BuildCertificationFile: +kind default 'source'). Accept `'cancelled'` as a valid `cert_status` in code. Move `certified_at` set to the gate.
- **SEAM 1 (browser):** REGRESSION — a normal QA → HW → finalize still works; `certified_at` now reflects the finalize moment; cert board / detail render unchanged; console clean.
- **CONSOLIDATION COMMIT + FULL SYNC #1** here, after Chat verifies B1 (spec + B1 as separable commits).

**B2 — cancel.** POST `/fulfillment/certifications/{prov_id}/cancel` (append cancelled event: reason + cancelled_by + cancelled_at, same role gate as certify). Cancel action in the detail UI. A cancelled attempt freezes; the close-gate already blocks re-close.

**B3 — re-cert.** POST `/fulfillment/certifications/{prov_id}/recertify` (append a fresh pending attempt inheriting prior checklist/evidence, copy-forward files under new stored_names, `reason='recert'`). Wire the detail template's "Start re-certification" to the real endpoint (currently a client-only reveal). Group detail files per-attempt by `build_certification_id` (not the lifetime-wide `oem_serial` query).

**B4 — composite persist + history.** Persist the composite on finalize (`kind='composite'`, self-check, source-only merge). New GET `/fulfillment/certifications/history/{serial}` route + `build_cert_history.html` (mirror `c2c_history.html`): per-attempt badges, BOTH signers (certified_by + co_certified_by), reason, per-attempt files, report PDF link. Add "View history →" links on list + detail.
- **SEAM 2 (browser):** certify with files → composite persists + OPENS in the browser (live-render gate, fitz); history timeline renders all attempts newest-first with correct badges + both signers + reason.

**B5 — restyle.** Reshape the build-cert cert UI (list + detail) toward the C2C look/flow. Use the C2C token/class patterns; NEVER edit a shared rule (`.bld-*`, `.kanban-grid`, `.k-col`) for one board — add new classes.
- **CONSOLIDATION COMMIT + FULL SYNC #2** here, after Chat verifies B2–B5.

## Verification (hand to Chat at each seam + end)

- **SEAM 1:** dual-signoff regression (normal cert path intact; `certified_at` at gate).
- **SEAM 2:** composite persists + opens (live render); history timeline correct.
- **END:** full lifecycle — certify → cancel (reason) → re-cert (inherit + copy-forward, `reason='recert'`) → history shows all attempts + both signers + PDFs; DB confirms append-many attempts, prior attempts frozen, `is_complete` untouched by cancel.

## Do not

- Rewrite `_apply_cert_half` into per-signoff events (attempt-level only).
- Add uniqueness to `device_provisioning_id`.
- Unify the two notions of done, or add a distinct-signer check.
- Claim the composite works from `py_compile`/import — live render only.
- Edit shared CSS rules for one board (add new classes).
- Chain the two remote pushes.
- Commit+sync after every sub-slice — only at the 2 consolidation points.

## B6 - Full stage labels on the wide build-cert surfaces (follow-up, shipped after B5)

The build-cert list + detail are wide tables, so they show FULL-WORD stage labels while the narrow Kanban keeps its abbreviations.

**Not responsive.** Full-word widths were measured against the build-cert STAGE column at ~14 inch laptop width: the column has ~138px available and every full word fits with headroom (Hardware Check 94px, Registered 63px, Certified 51px). So NO breakpoints, dual-form DOM, or media queries - this is a pure per-surface label choice.

**Design.** A build-cert-only `_BUILD_STAGE_FULL` map lives next to `_stage_label` in `app/routes/fulfillment.py`; the `stage_label` Jinja filter PREFERS it, then falls back:

    _stage_label(value) = _BUILD_STAGE_FULL.get(value) or STAGE_LABELS.get(value) or value.replace("_", " ").title()

Full forms (build-cert surfaces only): `registered -> Registered`, `certified -> Certified`, `sw_version -> SW Version`, `pva_events -> PVA/Events`. `hw_check` STAYS `HW Check` (its permanent form; do not expand it to "Hardware Check"). Stages already full in `STAGE_LABELS` (staged / building / licensed) need no override.

**Untouched (do not modify).** `STAGE_LABELS` (models.py) stays abbreviated - the narrow Kanban (`fulfillment.html` JS via the `stage_labels` context) and provisioning (`_get_stage_label`, a separate resolver) depend on it. Display only; stored stage values are never mutated.
