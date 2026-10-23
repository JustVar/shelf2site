# Slice: SKU requirements editor + order panel opener (E2E blocker)

Fixes the E2E test's headline: a UI-created order cannot reach the outbound pipeline. Root causes: no SKU-requirements editor exists anywhere, the Assign/Ship panel has no visible opener, and the panel does not reload per order. Reference: e2e-workflow-test-report.md findings 2, 5, 6, 7; live repro = order AT-9009 (id 80), left in place for this purpose.

## 1. SKU requirements editor

Home: the SKU Requirements card on ORDER DETAIL gets "+ Add SKU" (editor+). Line editor: SKU picker (typeahead over the part_numbers catalog) + quantity; add/edit/remove lines. Free-text SKU allowed but rendered with a "not in catalog" hint chip (the import proved catalog gaps are real — 27 preserved mismatches); catalog entries always preferred in the picker.

Fix the broken affordances around it: the card's empty-state text currently says "Edit order to add them" — change to the real action ("Add SKU requirements below" / the + button). The Edit Order modal does NOT gain a SKU editor (one home, not two) — its scope note in the card stands corrected instead.

## 2. Panel opener on order cards

Each fulfillment board card gets explicit action buttons that stopPropagation from the card's navigate-onclick: "Assign" (opens the panel on the Assign Boxes tab for THAT order) and, for orders with assignments, "Ship". Tint style, bottom-right of the card, always visible (not hover-only — discoverability was the failure). The panel's "View Full Order" link stays.

## 3. Panel correctness

- openPanel(orderId) fully reloads panel state for the given order every time (the stale-state bug: AT-9007's panel showed order 80's emptiness).
- The Assign tab's box list populates by the order's SKU requirement lines (existing matching logic) and says WHICH SKUs it is matching; zero-requirements state links to the order detail editor.
- "N Intended" chip on cards: discovery — find what feeds it today, then unify it to the SKU requirement quantity sum. If a separate legacy expected_quantity concept exists (receiving-side), document the distinction rather than merging blindly.

## 4. Riders (small, from the same E2E report)

- F-C: order detail's "Link them from the Provisioning page" -> stale circular link; fix the copy/target (provisioning merged into fulfillment long ago).
- F-A partial: server-side required-field validation on order create (customer name minimum) and item create (name + category minimum) so empty submits 400 — the ghost-item class. (Item 39 itself is in ledger #44, delete after its origin is checked.)
- Pilots Due Back scope (E2E F-B, recommendation accepted unless Jus vetoes): the page derives from loan-type ORDERS (pilot/try_and_buy/demo) with due dates — shipped units of ANY loaner order appear, not just C2C cameras; copy updated from "loan cameras" to loaner units. Same derivation source as today, widened filter.

## Acceptance test (the point of the slice)

Complete the exact flow the E2E test could not, on AT-9009: add a SKU requirement (PVA-100-30NR x1) -> Assign button on the card opens the panel showing USCFS0226002 (Ready to Deploy, matching SKU) -> assign it -> Ship Order tab -> ship with tracking -> order progresses (In Progress/shipped), unit status transitions, deployment pipeline shows it -> Pilots Due Back shows the box pilot with its Jul 24 due date (per rider 3) -> then return it (whatever the return flow is — discovery; if none exists for box pilots, REPORT THAT as the next gap rather than inventing one) -> AT-9009 and the unit end in a clean state, documented.

## Gates

Standard: contract tests for the new routes + validation, both themes, adjacent boards unaffected, consoles clean, diff review. The acceptance run recorded step-by-step in the report.
