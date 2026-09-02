# Customer order cancel path

Status: SPECCED, not built. Written against
`docs/specs/fulfillment-vendor-direction.md` (ratified 2026-09-01, fde8629).
Owner of the customer-order terminal status and the cancel action.

Scope: `CustomerOrder` only. OEM purchase orders and deployment records
already carry their own `cancelled` status and their own cancel modeling;
neither is touched here.

## Problem

`CustomerOrder.ORDER_STATUSES` (models.py:1248 at HEAD 5753601) has seven
members: new, sourcing, building, testing, shipped, delivered, installed.
None is terminal. An order that dies has nowhere to go and stays on the
board in whatever stage it reached.

The read side already defends a status the write side cannot produce.
`GET /api/orders/open` (orders.py:680, the bulk-assign picker feed)
excludes `{installed, cancelled}`; no route writes `cancelled` and no row
carries it (9 live orders: new 5, testing 2, building 1, shipped 1). All
READ 2026-09-02.

Precedent exists on both adjacent axes. `OEMPurchaseOrder.OEM_STATUSES`
carries a real `cancelled`, excluded from the active count
(fulfillment.py:621). `DeploymentRecord.DEPLOYMENT_STATUSES` carries one,
excluded at both the query (fulfillment.py:499) and the column list
(:635). Customer orders are the only axis without it.

## Decision

Add `cancelled` to `ORDER_STATUSES` as an eighth, terminal status.

Rationale (Jus, 2026-09-02): under the vendor direction, in-house builds
are winding down; cancellations are expected to be rare. A simple terminal
status is sufficient. The stage an order died at is NOT preserved in a
separate column.

## Cancel action

`POST /orders/{id}/cancel`, provisioning-manager auth, matching the
existing order mutation routes.

Requires a reason. Free text, non-empty after trim, server-validated.
Refusal shape is 409 with the `{"error": ...}` body, following the
orders.py convention (same choice as the 51b5f9e order-delete guard and
`item-decommission.md`; the two-convention question, board item 5, remains
open and this spec does not settle it).

Cancelling is REFUSED if the order is already cancelled. Otherwise it is
allowed from any stage.

### What happens to linked units

Units are HARD-UNLINKED: `device_provisioning.customer_order_id` is set to
NULL for every row tied to the order. The provisioning rows themselves
survive; they are the device's own history.

The unit list is captured in the audit event before unlinking (below).

Decided against (Jus, 2026-09-02): a soft-unlink `released_at` column on
`device_provisioning`. It is the structurally better answer — it would
give the decommission guard a single predicate
(`returned_date IS NULL AND released_at IS NULL`) covering both release
paths — but it costs a migration plus a whole-repo reconciliation of every
"is this unit live" query. Not worth it for a path expected to be rare.

Consequence, stated plainly: after a cancel, the tie between the order and
its units exists ONLY in the audit entry. The DB cannot reconstruct it.

Rows are found by `customer_order_id`, NOT by `item_id`. `item_id` is
nullable and legacy-path rows carry `device_table` + `device_id` instead
(schema READ 2026-09-02); a query written against `item_id` alone silently
misses them.

## No reversal

Cancelled is terminal. There is no un-cancel.

Rationale: the unit links are gone, so a reversal could not restore the
order to its prior state without making the audit log load-bearing for a
write path. Correcting a mistaken cancel means creating a new order.

Known consequence: `po_number` is unique (models.py:1199), so a
replacement order cannot reuse the cancelled order's PO. Whether POs
should be reusable is a separate question and is NOT settled here.

Reversal was considered and deferred, not overlooked. It can be added
later without undoing anything specced here.

## Audit event

`order_cancelled` — reason, who, and the unit list as it stood before
unlinking.

Basis: the two-clause principle in `docs/audit-log-scope.md`. The cancel
action itself is an application-specific state transition and belongs in
the audit log without question.

The unit list is a deliberate exception, taken with eyes open. It is
business history, and the principle says business history belongs on the
domain surface that owns it. Customer orders have no history surface
today, so the audit log is the only place it can live. If an order history
surface is ever built, ownership of the unit list moves there and this
spec's exception ends. Recorded so a future reader sees a decision rather
than a violation.

## The vocabulary sites: build-time trap

`ORDER_STATUSES` at models.py:1248 is the authority. Three further sites
restate its members by hand, and adding an eighth status without touching
them fails SILENTLY — no error, no column, the order simply does not
render:

1. `fulfillment.py:63` `ACTIVE_STATUSES` = new, sourcing, building,
   testing, shipped
2. `fulfillment.py:66` `ARCHIVED_STATUSES` = delivered, installed
3. `fulfillment.py:567` builds the column dict from the union of the two;
   the `"new"` default at :569 catches only values outside the model
   entirely

All READ 2026-09-02 at HEAD 5753601. Line numbers are anchors at that
HEAD; re-read before editing.

`cancelled` belongs in `ARCHIVED_STATUSES`, matching how the OEM and
deployment boards treat their own cancelled rows.

This is the same drift shape `item-decommission.md` addressed for item
statuses, and the derivation pattern established there ports directly.
Closing it by derivation rather than by adding a fourth hand-maintained
entry is IN SCOPE for this build if it can be done without disturbing the
board layout; if it cannot, add the member by hand and leave a board item.

## Reconciliation set

`CustomerOrder` is referenced in eight route modules (READ 2026-09-02):
orders, fulfillment, c2c, provisioning, item_detail, map, receiving,
unit_photos.

Each is a potential site where "is this order live" is decided. The build
must account for every one BY NAME — confirming a module needs no change
is an acceptable outcome; not looking is not. Do not fix the two obvious
ones and declare the sweep done.

## Interaction with item decommission

`docs/specs/item-decommission.md` pre-ratifies this: a cancel path
releases decommission blocking by removing or unlinking units, and its
blocking rule needs no change. Hard-unlink satisfies that literally —
`customer_order_id` goes NULL, the link is gone, the item becomes
decommissionable.

## UI

Cancellation is rare but must be properly built when it fires (Jus,
2026-09-02). Not a hidden or admin-only path.

- A Cancel action on the order surface, visually distinct from the
  stage-advance controls.
- Reason capture. NOTE: do NOT follow the `item_detail.html` decommission
  pattern of chained native `prompt()` calls. That pattern is a live
  board item precisely because it is untestable by automation, off the
  design system, and fails silently when a second dialog is dismissed. Use
  an in-app modal.
- Confirmation before the write, naming the order and the number of units
  that will be unlinked.
- Cancelled orders appear in the archived section of the fulfillment
  board with their reason visible.

## Out of scope

- N3, the archived/completed view rework (searchable records, maps feed).
  Separate spec; `ARCHIVED_STATUSES` already partly implements it.
- Whether `po_number` should be reusable after a cancel.
- The two-error-shape convention question (board item 5).
- OEM PO and deployment record cancel modeling; both already exist.
- Promoting `customer_orders.status` to a Postgres enum type. Considered
  and DEFERRED (2026-09-02): it would give order statuses the same
  DB-level floor items have, but it is a migration over live rows to fix
  a problem that has not bitten — all nine live orders carry valid
  values. Board item, not this build. Doing it here would be exactly the
  scope creep the killed tracks came from.

## Rider on this commit

R4: `item-decommission.md` blocking rule wording. Lines 61-64 say
decommission is refused while an item is "linked to any order, regardless
of order status," then say a return releases it. Both cannot hold
literally: a returned unit keeps its provisioning row, so under the first
reading a returned item would be permanently undecommissionable. The
built guard resolves toward the release sentence — the predicate is
`returned_date IS NULL`, an ACTIVE link (REPORTED-from-Code, 5753601).
Amend the spec text to say "linked" means an unreturned unit, so text and
guard agree in wording rather than only in intent.

## Build notes

- Predict the census delta before running the suite. This spec adds ONE
  route (`POST /orders/{id}/cancel`); the endpoint auth census generates
  cases per route, so derive the expected total from the route count in
  the edit list rather than by hand.
- NO MIGRATION IS NEEDED. Settled by read, 2026-09-02:
  `ORDER_STATUSES` is a plain Python dict of seven entries
  (models.py:1248) and `customer_orders.status` is `character varying(32)`
  — indexed, nullable, no default, no CHECK constraint. Adding `cancelled`
  is a dict edit plus the three vocabulary sites above.

  This is the structural opposite of item statuses, which are backed by a
  real Postgres enum (`item_statuses_enum`, models.py:1873) that refuses
  invalid values at the DB floor. Orders have no such floor: any
  32-character string commits successfully. That is WHY the read-side
  filters at orders.py:691 and fulfillment.py:499/635 defend against
  `cancelled` despite nothing writing it — defensive filtering is the only
  guard available on this axis.

  Consequence for this build: validation of the status value lives
  entirely in the app layer. The cancel route must not assume the DB will
  catch a typo.
- The audit event writes to `new_values`, not `details` (READ 2026-09-02,
  rows 23625/23626).
- Verify the cancel path end to end in the browser before close, both the
  refusal (already-cancelled) and the success path, with the audit row
  read from the DB.
