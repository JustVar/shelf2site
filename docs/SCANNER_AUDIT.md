# Barcode Scanning — Phase 1 Audit

Date: 2026-07-10 · Status: read-only audit + live probes, no code changes.
Purpose (owner): scan barcodes to intake items from shipping orders.
Method: full-source trace of every scan surface, plus live endpoint probes on
apphost using throwaway `CONTRACT-TEST-AUD*` data (created and deleted in the
same run). Probe transcript summarized inline as **[PROBED]**.

This document is the Phase 1 deliverable. Nothing below is fixed yet —
Phase 2 scope is decided at the decision gate (§7).

---

## 1. What exists today (the actual flow)

Four scan surfaces share `static/js/scanner.js` (native `BarcodeDetector`,
falling back to html5-qrcode from the unpkg CDN):

| Surface | What it does | State |
|---|---|---|
| Receive & Scan — Receive mode (`receive.html:457`) | scan → `POST /api/receive/scan` → branch already_exists / recognized / unknown → manual form → `check-duplicate` → `POST /api/receive/device` | Works, with the defects in §2 |
| Receive & Scan — Quick Mode (`receive.html:470-528`) | camera stays open; **only** status `recognized` auto-submits, `direct_to_inventory: true`, status hardcoded `Inventory` | Works mechanically; dangerous (F6) |
| Receive & Scan — Assign Drive mode (`receive.html:1008`) | scan drive serial → `GET /api/drives/lookup` | **Fully dead** — router never mounted; every scan shows "Drive not found in inventory. Add it first via Receive mode" (F7) |
| Fulfillment "Scan" (`fulfillment.html:2976`) | lookup-only scan-to-find via `/api/receive/scan` | Lookup works for editors; View action navigates to the wrong record; view-only users get false "not in inventory" (F8) |
| Provisioning detail serial-verify (`provisioning_detail.html:629`) | pure client-side compare vs expected serial | Works; only case-insensitive surface; latent wrong-expected-serial cross-table id bug |

Decode formats requested (both engines): QR, Code 128, Code 39, EAN-13/8,
UPC-A. **Not enabled** (both engines support them upstream — config-only):
DataMatrix (compact electronics serial plates), ITF-14 (shipping cartons —
directly relevant to the stated purpose), PDF417 (carrier labels), UPC-E.
Same-code debounce 2 s; no cross-code debounce; no beep/vibrate/flash/torch.

`POST /api/receive/scan` classification knows exactly two moves
(`receiving.py:104-144`): exact **case-sensitive** serial equality across the
22 **legacy** `TABLE_MODELS` tables, then one vendor heuristic
(`vendor_defaults.py:25`: starts with `Q`, length ≥ 10 ⇒ QNAP NAS).

## 2. Findings

Severity: C = breaks the stated purpose or corrupts data · M = major · m = minor.

### Correctness (probe-confirmed)

- **F1 [C] Scan and check-duplicate never search `item_schema.items`** — the
  current system of record (Intake page, Casey imports, global search all use
  it). Also skipped: `gpus.gpu_serial`, `nas_drives.serial_number`,
  trade_show_boxes. **[PROBED]** `C2C-SX-0003` (items-only serial) → scan
  `unknown`, check-duplicate `exists: false` ⇒ double-intake invited.
- **F2 [C] Direct-to-inventory writes into the retired legacy tables.**
  `submit_device` creates rows via `TABLE_MODELS[target_table]` (public.*).
  **[PROBED]** direct intake landed in `public.edge_boxes`, count in
  `item_schema.items` = 0 ⇒ scanned-in items are invisible to the Inventory
  page and Global Search (both read item_schema since the route migration).
  The scan pipeline currently feeds the schema being retired.
- **F3 [C] Pending-review path discards the scan.** `PendingDevice` has no
  serial/model/notes/event columns; serial survives only inside the
  `intake-<serial>` placeholder stuffed into the NOT NULL mac_address.
  **[PROBED]** pending row = `('intake-CONTRACT-TEST-AUD-QM1', '', 'edge_boxes')`
  — model, notes, event id all gone; event counter not incremented.
- **F4 [M] No server-side dedupe.** Client check-duplicate fails open
  (`catch → null`), is user-bypassable, and `submit_device` never re-checks.
  **[PROBED]** same serial direct-submitted twice → two rows (ids 123, 124).
  Where DB uniques exist (nas_devices.serial, hard_drives.serial,
  edge_boxes/nucs mac) the second insert is an unhandled 500 instead.
- **F5 [M] Case-sensitive exact matching.** **[PROBED]** lowercased known
  serial → `unknown`. Code-39 wedges emit uppercase; DB rows are as-imported
  mixed case. Precedent for ilike exists (`import_all_categories.py:552`).
- **F6 [M] Quick Mode auto-inserts any `Q…`(≥10) scan as a QNAP NAS device**
  with `direct_to_inventory: true` and status `Inventory` — a value that does
  not exist in the manual form's vocabulary (Received/In Storage/…). A
  Q-prefixed QR URL or PO becomes a phantom inventory row with no confirm.
- **F7 [M] Assign Drive mode is dead three ways.** Router never mounted;
  mounting it would **crash the app at startup** (imports `StorageDrive`,
  which no longer exists; backing table dropped by migration 029; successor
  `hard_drives` lacks the `installed_in*` columns it writes). The 404 is
  rendered as "Drive not found — add it first via Receive mode", inviting
  duplicate intake. **[PROBED]** `/api/drives/lookup` → 404.
- **F8 [M] Fulfillment scan-to-find:** (a) View action navigates to
  `/provisioning/{device_id}` where a `DeviceProvisioning.id` is expected —
  wrong record on id collision, silent bounce otherwise; (b) button rendered
  for provisioning-viewers whose scans 403 → misreported as "not in
  inventory"; (c) no manual-entry fallback when the camera is unavailable
  (which on http:// is always).
- **F9 [M] RBAC bypass:** `direct_to_inventory` into edge_boxes requires only
  `require_editor`, while approving the same device out of the pending queue
  requires sites admin (`user_can_approve_table` — never called here).
- **F10 [M] Auth asymmetry:** `GET /receive` honors the `can_access_receiving`
  flag, but every API on the page is `require_editor` — flag-holders get a
  fully rendered page where every action 403s.
- **F11 [M] GPUs:** invisible to scan/dedupe (`gpu_serial` ≠ `serial`) AND a
  direct-intaken GPU is created **with no serial at all** (field loop drops it).
- **F12 [M] Silent error paths (10 catalogued):** submit network failure
  permanently bricks the button at "Submitting…"; `processBarcode` misreports
  server errors as "Serial not recognized" and writes literal `undefined`
  into the serial field; createEvent has no error handling; quick-scan fetch
  unhandled (scan silently lost, camera keeps running); check-duplicate fails
  open; photo-link swallowed; photo-upload rejection shown as "OCR
  unavailable"; assign search renders failures as "No devices found";
  unexpected submit status → zero feedback; CDN load failure → dead overlay.
- **F13 [m] `/api/receive/photo/link` doesn't exist** (payload lacks photo_id
  anyway) — intake photos permanently orphaned from devices. **[PROBED]** 405
  (POST lands in `GET /api/receive/photo/{photo_id}`'s path space).
- **F14 [m] Receiving events:** no close endpoint (**[PROBED]** 404 on both
  obvious shapes) — `open` forever, `complete|partial` vocabulary dead;
  `received_quantity` counts only direct submits (**[PROBED]** pending → 0,
  direct → 1); only `nas_devices` has `receiving_event_id`, so device→event
  linkage is silently dropped for every other category; the event's PO is
  never copied onto intaken devices; `receiving_events` has no migration file
  (create_all only — schema-drift risk for any future column).
- **F15 [m] Information oracle:** check-duplicate needs only
  `get_current_user` — any session incl. map_kiosk can enumerate serials and
  learn table/location/status. Intake photos served to any user by sequential id.
  **[CORRECTED 2026-07-10]** The map_kiosk clause was wrong: the kiosk
  confinement in `auth_redirect_middleware` runs before the `/api` passthrough
  and answers 403 — the route never executes for kiosks (now pinned in the
  kiosk contract test). The viewer-level oracle stands; fix remains H14.
- **F16 [m] Scanned content is interpolated into `innerHTML` unescaped**
  (toasts, banners, OCR buttons) — a QR code encoding HTML/JS executes in an
  authenticated editor's session. Internal tool, but intake scans untrusted
  physical labels by definition.
- **F17 [m] scanner.js lifecycle:** double-start TOCTOU (second overlay
  orphans the first — page bricked until reload); CDN failure → dead overlay
  with no message; insecure-origin failure shows the misleading "Camera
  access denied" (no HTTPS hint); no-camera shows the same; viewfinder and
  decode-region sizes diverge ≥ 600px.
- **F18 [m] OCR serial cleanup replaces `I→1`, `O→0` unconditionally** —
  corrupts legitimate serials containing I/O.
- **F19 [i]** "Recognized" is one QNAP prefix rule; `VENDOR_MODEL_DEFAULTS` /
  `lookup_by_model` are dead code; scan endpoints run 22 sequential queries;
  category required-fields validation imported but never called; quick-scan
  sends `receiving_event_id` to an endpoint that ignores it.

### Regression check (the known bug)

**4368920 holds. [PROBED]** `mac_address: null` (exact quick-mode payload
shape) → 200 `pending_review`. MAC normalization is consistent: receiving
routes through `validate_mac_address`, a thin wrapper over the canonical
`normalize_mac` — same canonicalization as intake/item_detail/triage/inventory.
**[PROBED]** `aa-bb-cc-dd-ee-01` stored as `AA:BB:CC:DD:EE:01`. One edge: the
direct-branch copy loop writes `""` (not NULL) for empty strings from non-UI
callers, violating the store-NULL doctrine.

## 3. Shipping-order linkage — the headline gap (CONFIRMED, with one nuance)

**No PO-level expected-units reconciliation exists.** `ReceivingEvent.purchase_order`
is free text, never matched against anything. `OEMPurchaseOrder.qty_received`
is updated only by hand on the fulfillment board. No code path ever compares
scanned intake to a PO.

The nuance: a **count-only, hand-typed** expectation display exists —
`expected_quantity` vs `received_quantity`, shown as `[x/y]` in the event
dropdown — but it has no SKU granularity, skips the pending path, is never
adjudicated (no close), and is disconnected from procurement.

**The data for real reconciliation already exists.** `oem_purchase_orders`
rows are effectively per-SKU line items (`sku`, `qty_ordered`,
`qty_received`, status lifecycle incl. `receiving`/`verified`). Feasibility:

| Tier | Content | Size |
|---|---|---|
| Starter (no schema change) | On event create, match free-text PO against `oem_purchase_orders.po_number` (case/space-insensitive); prefill expected qty; show the SKU line list; increment `qty_received` on intake; auto-advance PO status; add the missing event-close endpoint | **S** (1–2 days) |
| Full | `receiving_event_lines` table + polymorphic `received_devices` link (instead of adding `receiving_event_id` to 15+ legacy tables) + inbound tracking-number column + check-off UI with short/over badges | **M** (~1 week, own slice) |
| ASN/serial-level | Vendor ships expected serials in advance | **L** (needs external data) |

Any tier must also count the pending path (F14) or it undercounts.

## 4. Decode routing table (proposal)

Server-side in `/api/receive/scan` so every surface benefits. Pre-processing:
strip whitespace/control chars; detect GS1-128 (`]C1` prefix, `\x1d`
separators, `(AI)` patterns) and extract AI(21) serial / AI(01) GTIN /
AI(00) SSCC; classify on the uppercased value; all lookups case-insensitive.

| # | Pattern (uppercased) | Class | Lookup | On miss |
|---|---|---|---|---|
| 1 | `^([0-9A-F]{2}[:-]){5}[0-9A-F]{2}$` or dotted quad-pairs | MAC (separated) | `normalize_mac` → all MAC columns (legacy + `item_mac_address_1/2`) | "No device with MAC … — receive with MAC prefilled?" |
| 2 | UUID 8-4-4-4-12 | UUID | `edge_boxes.uuid`, `nucs.uuid`, `items.platform_uuid` | "UUID not linked — scan the serial instead" |
| 3 | `^1Z[0-9A-Z]{16}$` | Tracking (UPS) | tracking-number columns | "Shipping label — create/select a receiving event for this shipment?" |
| 4 | `^00\d{18}$` (SSCC) / `^\d{20,22}$` | Tracking (SSCC/FedEx/USPS) | same | same |
| 5 | `^AT-\d{4,}$` | Order number | `customer_orders.order_number` | "Order not found" |
| 6 | `^(PVA|EDGE|E2C)…-\d{5,6}$` | Unit PN (`item_pn`) | `items.item_pn` | "Unit PN not in items — receive with PN prefilled?" |
| 7 | SKU grammars (`PVA-25-30R5`, `EDGE25-56TB-NR`, `PVA50-84TB-Z2`, `E2C-…`) | SKU | part_numbers / `edge_boxes.part_number` | "That's a SKU, not a unit — now scan the unit serial" (prefill category) |
| 8 | `^[0-9A-F]{12}$` | **Ambiguous** MAC-vs-serial | tie-break: serial hit → MAC lookup → OUI-prefix check → serial-unknown with "looks like a MAC?" hint | per branch |
| 9 | `^USCF…` | 2026 edge-box serial | serial lookup; prefill edge_boxes/2026 on miss | "New 2026 edge box — confirm intake" |
| 10 | `^Q[A-Z0-9]{9,}$` (alnum only — kills QR-URL false positives) | QNAP candidate | serial lookup first; on miss prefill QNAP **with a confirm tap, never silent auto-insert** | "Recognized QNAP pattern — confirm" |
| 11 | `^\d{12}$` / `^\d{15}$` | Ambiguous UPC/FedEx/serial | serial → tracking → user chip prompt | per choice |
| 12 | anything else (3–100 chars) | Serial | ilike across **all** serial columns incl. `items.item_sn`, `gpu_serial`, `nas_drives.serial_number` | current "fill in manually" (now with the widened lookup) |

Currently handled: exact-case legacy-serial hits and the QNAP guess. Currently
misrouted: everything else in the table, plus GS1-wrapped serials that will
never match.

## 5. Hardware-target readiness

- **USB keyboard wedge:** mechanically works today (Enter handler on
  `#manual-serial`, no debounce in the way — a 20-char burst + Enter is fine).
  Not loop-ready: no autofocus, never cleared/refocused after a cycle (second
  trigger-pull concatenates → corrupt serial like `SER1SER2`), quick-path
  unreachable from manual entry. Fix list is small and camera-independent.
- **Camera:** blocked on http:// origins entirely (misleading "denied" toast).
  All camera-live work sequenced AFTER the HTTPS/mkcert task. The receive
  page's mobile hero layout (mobile slice) is the base for Phase 2 camera UX.
- **Synthetic testing (no camera needed):** the page callbacks are globals —
  `page.evaluate("onScanSuccess('SN123')")` injects a decode past the
  scanner; full-chain coverage via a stubbed `getUserMedia` (canvas
  captureStream) + fake `BarcodeDetector` whose `detect()` returns
  `[{rawValue: 'X'}]`. This is how Phase 2 gates will be verified.

## 6. Costed hardening list (Phase 2 candidates)

| # | Item | Fixes | Size |
|---|---|---|---|
| H1 | Unified, case-insensitive lookup (scan + check-duplicate over item_schema + gpu_serial + nas_drives) | F1, F5, F11(lookup) | **S** 0.5 d |
| H2 | Retarget direct intake at `item_schema.items` (reuse the Intake create path incl. receipts) — or explicitly bless legacy until the retirement track | F2 | **M** 1–2 d + decision |
| H3 | Pending path preserves serial/model/notes/event (payload JSONB or columns + migration) | F3, part of F14 | **S/M** 0.5–1 d |
| H4 | Server-side dedupe + IntegrityError handling | F4 | **S** 0.5 d |
| H5 | Routing table (server classification + specific not-found messages + GS1 preprocessing) | F19, §4 | **M** 1–2 d |
| H6 | Quick Mode: confirm tap for recognized-not-found; fix status vocabulary | F6 | **S** 2–4 h |
| H7 | Remove Assign Drive mode + delete dead router + tour update (rebuild later on item_schema if wanted — do NOT mount) | F7 | **S** 2–4 h |
| H8 | Fulfillment scan: right View target, permission-gate the button, manual-entry fallback | F8 | **S** 2–4 h |
| H9 | Error-surfacing sweep (10 silent paths) + escape scanned strings (XSS) | F12, F16 | **S** 0.5–1 d |
| H10 | Wedge loop: autofocus + scan-ready indicator + clear/refocus + wedge quick path | §5 | **S** 0.5–1 d |
| H11 | Decode formats config (DataMatrix, ITF-14, PDF417, UPC-E) | §1 | **S** 1 h |
| H12 | scanner.js lifecycle: double-start guard, CDN-failure message, vendored html5-qrcode, honest insecure-origin/no-camera messages | F17 | **S** 2–4 h |
| H13 | Camera UX: beep/vibrate/flash on decode, torch toggle, batch-mode feedback — **after HTTPS** | §5 | **S/M** 0.5–1 d |
| H14 | RBAC: direct-intake approval gate, receiving-flag API alignment, oracle lockdown | F9, F10, F15 | **S** 0.5 d |
| H15 | Event lifecycle: close endpoint, auto-complete at expected, copy PO onto devices, count pending | F14 | **S/M** 1 d |
| H16 | Reconciliation starter (PO match + SKU lines + counter sync) | §3 | **S** 1–2 d |
| H17 | Reconciliation full (line-item tables + check-off UI + short/over badges) | §3 | **M** ~1 wk, own slice |
| H18 | Photo link: real endpoint (with photo_id) or remove the call + orphan cleanup | F13 | **S** 2–4 h |

Suggested sequencing: correctness first (H1, H3, H4, H6, H7 — with H2 decided),
then routing + errors (H5, H9, H8, H18), then wedge (H10–H12), then camera
after HTTPS (H13), reconciliation as its own slice (H16 → H17).

## 7. Decision gate — questions for Jus

1. **Intake destination (H2, biggest call):** retarget scan-intake at
   `item_schema.items` now, or bless legacy public.* until the retirement
   track? Everything else assumes an answer.
2. **Assign Drive (H7):** confirm REMOVE (mount is impossible — the router
   crashes the app; the table it wrote to was dropped). Rebuild later on
   item_schema only if a real need exists (`nas_drives` already covers NAS bays).
3. **Reconciliation (H16/H17):** approve the S starter now, the M slice
   later, both, or neither?
4. **Routing table (§4):** approve as the Phase 2 lookup design?
5. **Scope/sequence:** the suggested sequencing above, or reprioritize?

## 8. Manual bench protocol (finalized against shipped Phase 2)

Run once on webcam, once on phone (needs `Shelf2Site-LAN-CA.crt` installed — see
`docs/CA_CERT_DISTRIBUTION.md`), plus the USB wedge on the receive bench.
Guidance strings below are verbatim from `app/routes/receiving.py`; classes
from `app/scan_routing.py`. **Core pass** = the eight rows marked ★ (~15 min);
the rest is the full sweep.

Rows marked **[EXPECTED]** are correct-but-surprising: the behavior looks wrong
at the bench and is not. Do not file these as defects.

### A. Device labels

| Scan | Expected |
|---|---|
| ★ Known device serial | `already_exists`, class `serial`, item card + link |
| Unknown serial | `unknown` — "Serial not found — fill in the details manually." |
| ★ MAC label, colon or dash format | known → `already_exists` class `mac`; unknown → "No device with MAC {MAC} — receive it with the MAC prefilled?" with the MAC prefilled |
| ★ MAC label, bare 12-hex containing letters | class `hex12` **[EXPECTED]** not `mac` — serial → MAC → OUI cascade; final miss: "Serial not found. 12 hex characters — could this be a MAC without separators?" |
| MAC label, bare, all digits | class `ambiguous_digits` **[EXPECTED]** not `hex12` — product-code guidance. Correct: rule 8 requires at least one A-F character, or UPC-A would be unreachable |
| Bare 12-hex, known OUI prefix, unknown device | `unknown` with response `class: "mac"` **[EXPECTED]** rewritten from `hex12` — "Looks like a {Manufacturer} MAC — receive with the MAC prefilled?" |
| UUID label | known → `already_exists` matched on `uuid`; unknown → "UUID not linked to any unit — scan the serial instead." |
| `USCF…` serial not in inventory | `recognized` — "New 2026 edge box — confirm intake.", prefills `edge_boxes` |

### B. Shipping labels

| Scan | Expected |
|---|---|
| ★ UPS `1Z…` matching a receiving event | `recognized`, class `tracking` — "Inbound shipment for receiving event #N (vendor) — event selected." The event auto-selects; this is the stated purpose working end to end |
| ★ UPS `1Z…` with no match | `unknown` — "Shipping label — create or select a receiving event for this shipment?" |
| SSCC (`00` + 18 digits) or 20–22 digit carrier code | class `tracking`, same cascade as above |
| ★ FedEx/USPS 12–15 digit tracking matching an event | the event still auto-selects, but class is `ambiguous_digits` **[EXPECTED]** not `tracking` — rules 3 and 4 cover only UPS, SSCC and 20–22 digit forms |
| ★ GS1-128 carton label (`]C1` + AI(01) + AI(21)) | unwraps to the AI(21) serial → `already_exists`; the response carries `gs1.serial` |

### C. Catalog and SKU labels

| Scan | Expected |
|---|---|
| SKU present in the catalog | `recognized` — "That's a SKU, not a unit serial — now scan the unit's serial." plus SKU and category prefill |
| SKU absent from the catalog | `unknown` — the same string plus " (SKU not in the catalog.)" |
| Unit PN | known → `already_exists` matched on `unit_pn`; unknown → "Unit PN not in inventory — receive it with the PN prefilled?" |
| Order number `AT-####` | known → customer order card with order number and customer; unknown → "Order not found." |

### D. Adversarial — must never create a phantom item

| Scan | Expected |
|---|---|
| ★ Consumer EAN-13 or UPC-A | `unknown`, class `ambiguous_digits` — "Looks like a product or shipping code (UPC/EAN or carrier tracking) — use it as a serial only if the label says so." |
| ★ QNAP-shaped serial not in inventory | `recognized` — "Recognized QNAP serial pattern — confirm before adding." Must require a confirm tap; a silent insert is the F6 regression |
| Q-prefixed QR URL | class `serial` **[EXPECTED]** not `qnap_candidate` — falls through to "Serial not found — fill in the details manually." This is the F6 guard holding |
| QR encoding HTML or JS | rendered as literal text, never executed — the `esc()` helper in `receive.html` escapes scanned strings before every `innerHTML` sink (F16) |
| Deliberately damaged or partial label | no decode at all — the endpoint is never called; manual entry and the wedge stay usable |
| Decoded junk (under 3 or over 100 characters) | `unknown`, class `unclassified` — "Could not read a usable code from that scan — try manual entry." |

### E. Wedge and auth

| Check | Expected |
|---|---|
| USB wedge: 20-character burst + Enter | routes identically to a camera scan; the field clears and refocuses so a second trigger pull cannot concatenate into `SER1SER2` |
| Non-editor holding `can_access_receiving` | the page renders **and** the scan action works — no 403 (F10 / H14) |

Anything surprising goes back to Code with the raw scanned string captured.
Routing misses are logged server-side with their raw payloads during the pilot
— keep the `scan-routing-pilot` logging enabled until this protocol completes.
