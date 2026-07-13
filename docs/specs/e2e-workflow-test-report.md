# E2E Workflow Test Report — 2026-07-10

Live-site test of the full unit lifecycle (intake -> build -> pilot -> return -> redeploy), 1A Inventory + 1B Fulfillment, links/buttons/UX. OEM excluded per scope. Run while the containment slice was mid-build (its "Standalone — not installed in any unit" line appeared on item detail mid-test). Test data prefix: E2E-TEST.

## What works end-to-end (verified)

- Intake -> Inventory -> Search: item created via Intake appears everywhere immediately with correct chips/counts; toast + redirect correct.
- Scan lookup (H1 fix): lowercased serial of the new item_schema item correctly returns "already exists in Inventory Items" — the pre-fix double-intake trap is closed.
- Checkout/check-in custody: full round trip clean — status transitions (Unassigned -> Checked Out -> Unassigned), history entries with notes appended, "Out — not yet returned" badging, return restores prior status. This flow is production-quality.
- Order creation: New Order modal works; Pilot semantics correct (no PO required, Loan Due Date field, PILOT badge, "Due in 31 Days" on the board card).
- Order Delete button present (with confirm) — cleanup path for test orders exists.
- Fulfillment board renders, tabs switch, Coverage filter panel works, Stock hero tile opens the Edge Box Stock side panel with SKU counts.

## THE BLOCKER (finding 6, compounded by 2, 5, 7)

A freshly created order CANNOT progress through the outbound pipeline via the UI:

1. SKU Requirements have NO editor anywhere. The empty state says "Edit order to add them" but the Edit Order modal contains no SKU fields (finding 2).
2. The Assign Boxes panel gates its box list on SKU requirements existing — "No SKUs assigned / No boxes to display", even when searching an in-stock SKU directly (finding 6).
3. The Assign/View Status/Ship Order side panel has NO discoverable opener — order cards navigate to order detail on click; the panel only opened via the internal openPanel() function (finding 5).
4. AT-9007 wears a "2 Intended" chip yet its panel also says "No SKUs assigned" — either the panel does not reload per order or "Intended" reads a different field than requirements (finding 7).

Net: assign -> ship -> deliver -> install -> return could not be exercised for any UI-created order. The pipeline works only for legacy/seeded orders. THIS IS THE #1 BUILD ITEM from this test: an SKU requirements editor (on order detail and/or the Edit Order modal) + a visible panel opener on order cards + panel state reload per order.

## Other findings

- F-A (data integrity): a GHOST ITEM exists in inventory — no name, serial, category, or status, created Jul 10 (visible as an all-dashes row). Either stray test data or the intake path accepts an empty submit; the audit already noted category required-field validation is never called. Fix: server-side required fields on create_item + delete the ghost row (id discoverable via the dashes row's View).
- F-B (scope definition needed): Pilots Due Back page copy says "loan cameras"; a pilot ORDER with a loan due date does not appear (possibly by design until units ship — untestable due to the blocker). DECISION NEEDED: should box pilots appear here once shipped, and should the page rename to cover all loaner units? (My read: yes to both.)
- F-C (stale link): order detail "Link them from the Provisioning page" -> /provisioning/ -> 301 back to Fulfillment. Circular. Remove or repoint the copy.
- F-D (semantic): the Checkout item list offers Deployed customer units for internal checkout. Probably should exclude Deployed (or warn).
- F-E (UX papercuts): submit buttons sometimes need a second click (Intake Create Item, Check Out — first click appears to only focus/scroll; suspect the scroll-into-view + click race at page zoom); success toast overlaps the Edit button on item detail; the receive "already exists" banner is error-red and does not link to the found item (H9 group covers messaging).
- F-F: checked earlier in the session — cluster count text centering on map (already tasked, #25).

## Component build/replace step

Deliberately not exercised: the containment slice (task 37) was landing during the test. Its e2e gate covers receive -> install-into-unit -> move -> uninstall. The lifecycle test should be RE-RUN after that slice + the SKU editor land, to finally walk intake -> build -> pilot -> ship -> return -> replace -> redeploy in one pass.

## Cleanup ledger (for the next Code session)

- Item id 305 (E2E-TEST GPU RTX A2000) — keep or delete via SQL (no item-delete endpoint; consider whether one is wanted).
- Order 80 / AT-9009 (E2E-TEST Pilot Corp) — deletable via its Delete button; left in place as a repro for the SKU-editor gap.
- The ghost item row — investigate its origin BEFORE deleting (audit trail should say who/what created it).

## Recommendations, priority order

1. SKU requirements editor + panel opener + per-order panel reload (unblocks the whole outbound pipeline) — pairs naturally with the PO reconciliation slice since both touch SKU lines.
2. Server-side required-field validation on item create + ghost-row cleanup.
3. Pilots Due Back scope decision (boxes, not just cameras).
4. Checkout excludes Deployed; papercuts (double-click submits, toast overlap, already-exists banner) fold into the H9 error/UX group.
5. Re-run this lifecycle test after containment + SKU editor land.
