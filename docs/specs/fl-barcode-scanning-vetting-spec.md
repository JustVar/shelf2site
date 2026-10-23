# Barcode scanning: audit and hardening

Status: implemented "a while ago", never tested or fully vetted (Jus, 2026-07-09). Evidence of under-vetting: the quick-mode empty-MAC 500 fixed in `4368920` had been breaking every scan of a recognized device silently. Purpose per Jus: scan barcodes to intake items from shipping orders.

Inputs: barcode content is MIXED/UNKNOWN across vendors (audit catalogs it). Hardware targets: phone camera + workstation webcam; USB keyboard-wedge scanner as a cheap add (approved — it types into the focused field, so support is mostly focus/Enter handling).

## Known inputs from later slices (2026-07-10, fold into the audit)

- The `drive_assignment.py` router is NEVER MOUNTED — the Receive page's "Assign Drive" mode 404s today. The audit decides: mount and fix it, or remove the mode from the UI. Also dead: `/api/receive/photo/link` and `/api/activity/recent` (the latter probably outside scanner scope — note and hand to hygiene).
- Camera scanning cannot open on http:// origins in ANY browser — real camera testing is blocked until the HTTPS task (mkcert/LAN CA) lands. Sequence Phase 2's camera work AFTER HTTPS; Phase 1's audit and the decode-handler/synthetic-frame testing are unaffected.
- Mobile layouts shipped: the Receive page has a mobile hero layout (Start Camera, Quick Mode, manual entry, sticky submit) — Phase 2 camera UX builds on it, not alongside it.
- Receive null-MAC fix (`4368920`) and the MAC normalization helper (hardening sweep) already exist — the audit verifies scan paths route through the normalization helper rather than duplicating it.

## Phase 1 — audit (Code, read-only + safe probes)

1. Trace the whole flow: scanner.js + scanner.css, the Scan button on Fulfillment, Receive & Scan (both modes: Receive New Device / Assign Drive), Quick Mode, receiving-event select, and every route they call. Document ACTUAL behavior: camera library and decode formats (1D/2D? Code128? QR?), what happens on decode (lookup by what key?), item create vs update paths, dedupe on rescanning the same unit, unknown-barcode handling, error surfacing.
2. Shipping-order linkage: what connects a receiving event to procurement/OEM POs today, if anything. The stated purpose is intake FROM SHIPPING ORDERS — if there is no expected-units reconciliation (scan against a PO's expected line items, see what is missing), document that as the headline gap.
3. Decode routing: catalog what scanned strings can arrive (device serials by vendor pattern, MAC addresses, tracking numbers, vendor PO barcodes) and propose a routing table: classify the scanned string by pattern -> route to the right lookup -> helpful "recognized as X but not found" errors instead of generic failures.
4. Programmatic tests now: lookup endpoints with a known serial, known MAC, garbage, empty; quick-mode submit regression (the fixed bug); event create -> scan -> dismiss lifecycle; double-scan dedupe.
5. Report back to Chat: findings, the routing-table proposal, the shipping-order reconciliation gap assessment, and a costed list of hardening items. DECISION GATE before Phase 2.

## DECISION GATE OUTCOMES (2026-07-10, Jus)

1. Intake destination: RETARGET to item_schema.items (reuse the Intake page's create path). Everything in Phase 2 assumes this.
2. Assign Drive: REMOVE the dead mode and router — CONDITIONAL on the component-containment investigation (below) confirming or building the modern replacement. Do not remove until that lands.
3. Reconciliation: FULL slice (check-off UI, short/over badges) — skip the Starter tier as a separate deliverable but build it as the natural first commit of the full slice.
4. Routing table (SCANNER_AUDIT.md section 4): approved.
5. Sequencing (section 6): approved — correctness -> routing/errors -> wedge -> camera after HTTPS; reconciliation its own slice.

## NEW REQUIREMENT — component containment + history (investigate first, then slice)

Jus: components are now tracked individually per category; the system must show (a) which components are inside which unit (Edge Box / Cloud Box / C2C / PC) or standalone, (b) each unit's component history over time, and (c) each component's history — which units it lived in and where it is now.

Investigation (read-only, reports back to Chat before the containment slice is specced):
- What item_schema already has: Item Detail renders a "Component History" section — map the model behind it (containment relation? history table? events?), what writes to it, and what UI (if any) creates containment links today.
- Gap analysis against (a)/(b)/(c) above: current-state containment both directions, time-based history both directions, standalone state, and the interaction with places (a contained component's location = its parent unit's place).
- How scan-intake should participate: receiving a component then assigning it INTO a unit (the workflow Assign Drive was for) — propose where that action lives (item detail? receive flow? both).
- Only after this report + Chat decisions does the Assign Drive removal commit land, inside or alongside the containment slice.

## Phase 2 — hardening (shaped by the audit, expected items)

- Decode routing table implemented; every scan outcome gives specific feedback (found -> item card; recognized-but-missing -> offer intake with the field prefilled; unknown format -> shown as-is with guidance).
- USB wedge support: scan-ready state (auto-focused field with visible indicator), Enter triggers lookup, rapid-character tolerance, works on desktop receive bench with no camera at all.
- Camera UX: decode success feedback (flash/beep; vibrate on phones), torch toggle where supported, continuous batch-scan mode for multi-unit deliveries (scan, toast, keep scanning) if the audit shows the library supports it cheaply.
- Shipping-order reconciliation (if approved at the gate): receive against an order/PO — expected units list, scanned units check off, short/over flagged with the existing badge language. This is likely its own slice given data linkage.
- Both themes; the mobile field-pages slice owns the phone-sized layout — sequence this AFTER or WITH that slice so camera work lands once.

## Manual test protocol (Jus, at the bench — the part Chat/Code cannot do)

After Phase 2, a 15-minute physical script, run once on webcam and once on phone: scan a known device serial label, a MAC label, a vendor shipping label, a deliberately damaged/partial label, and a random consumer product barcode. Expected outcomes are written next to each in the final report; anything surprising goes back to Code with the scanned string captured in the audit log.

## Gates

Phase 1 is read-only + probe gates (no commits beyond test notes unless a bug is found — bugs get flagged fix commits like 4368920). Phase 2: standard gates, scanner exercised with synthetic decode events (the library can be fed test frames or the decode handler called directly), both themes. Camera-permission UI verified to the prompt in Chrome; full camera verification is the manual protocol.
