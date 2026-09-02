# Item decommission and status vocabulary ownership

Status: ratified 2026-09-01 by Jus. This spec is the OWNER of item status
semantics for `item_schema.items`. No prior document owned them; four
hand-maintained status list copies drifted in its absence. This spec both
defines decommission and ratifies the derivation that closes that drift.

Written against `docs/specs/fulfillment-vendor-direction.md`: decommission is
an internal lab-inventory concern. Items installed at customers are order
records, not inventory, and are outside this feature by construction (see the
blocking rule below).

Scope: `item_schema.items` only (548 rows at ratification). The 22 legacy
device tables (336 rows) are OUT of scope; legacy data can be reimported if
ever needed.

## What decommission means

An item in our inventory that is no longer usable. Not deletion: the row,
its history, and its audit trail survive. Reversible by reactivation.

## Status vocabulary: ownership and derivation

The enum at `models.py:1875` is the single authority for item statuses.
This spec ratifies:

1. The four hand-maintained copies derive from the enum instead of
   restating it:
   - `intake.py:29` STATUSES
   - `inventory.py:26` (currently shadowing its own line-13 import)
   - `inventory.py:37` FILTER_STATUSES variant
   - `receiving.py:151` _ITEM_STATUS_VALUES
2. Derived lists may declare EXTRAS where a surface legitimately needs
   more than the hand-editable base, the enum MINUS the code-managed
   statuses (amended 2026-09-02: the earlier wording said "more than the
   enum", which is false; Checked Out is IN the enum at
   app/models.py:1876 as of 34309a5). Exactly one exists today: `Checked Out` on the
   receiving surface (in-house items taken by a person; checked in on
   return). Extras are declared additions to the derived list, never a
   fifth restated copy.
3. `Decommissioned` becomes a real, code-mediated status. The
   hand-settable paths (`intake.html:54`; the triage bulk panel builds
   its options from TRG_STATUSES at `triage.html:222`. Corrected
   2026-09-02: the ratified text named `triage_fix_panel.html:32`,
   which does not exist at 681a7b8)
   are REMOVED from the dropdowns; the status is entered and left only
   through the decommission and reactivation actions below.

Line numbers above are anchors at HEAD 681a7b8; re-read before editing.

## Decommission action

Required fields, all three, no defaults filled silently:

- **reason** — free text, required, non-empty
- **date** — the effective decommission date (defaults offered in UI as
  today, but explicit in the request)
- **who** — the acting authenticated user, taken from the session, not
  client-supplied

Blocking rule: decommission is REFUSED while the item is linked to any
order by an UNRETURNED unit, regardless of order status. There is no
status enumeration to maintain: the presence of the link is the block.
Release is unit removal from the order — a return brings the item back
into inventory, and only then is it decommissionable. (Order
cancellation would also release, but no customer-order cancel path
exists at ratification; if one is built, it releases by removing or
unlinking units, and this rule needs no change.)

Amended 2026-09-02: the ratified text read "linked to any order", which
taken literally contradicted the release sentence, since a returned unit
keeps its provisioning row. "Linked" means an unreturned unit; the built
guard reads device_provisioning rows with returned_date IS NULL.

Refusal shape: 409 with the `{"error": ...}` body, following the
orders.py convention (same choice as the 51b5f9e order-delete guard; the
two-convention question on the board, item 5, remains open and this spec
does not settle it).

## Reactivation

Reverses decommission. Requires a reason (same shape as decommission).
Returns the item to a normal status — which status is a build-time
decision to be made against the enum, not specced here beyond: never
silently to a status implying readiness it does not have.

## Audit events

Both directions are audit events via `log_event`:

- `item_decommissioned` — reason, date, who
- `item_reactivated` — reason, who

Basis: the two-clause principle in `docs/audit-log-scope.md`. These are
application-specific state transitions; items have no domain history
surface, and item-adjacent events (checkouts) already live in the audit
log by that document's settled consequence. If an item history surface is
ever built, these two types are candidates to migrate with the rest.

`target_table` remains unvalidated free text (open finding in
audit-log-scope.md). Use the literal `items` consistently at both call
sites; do not add to the junk-name problem.

## Visibility

- Decommissioned items are HIDDEN from normal searches and inventory
  lists by default.
- Every hiding surface gains an "include decommissioned" toggle.
- A dedicated Decommissioned view lists them with reason, date, who, and
  a reactivation entry point.

The hiding is a filter default, not a data change: the rows are present
and reachable, matching the reversibility requirement.

## Out of scope

- Legacy device tables (all 22).
- Any customer-order cancel path.
- The archived/completed minimized-order view for installed orders
  (separate board item).
- Item 30 (two inventory models) — this spec touches only the
  item_schema side and takes no position on the overlap.

## Build notes (for the implementing session)

- The suite total moves when routes are added (endpoint auth census);
  predict the delta before running.
- The derivation change touches four files whose imports interlock
  (inventory.py:26 shadows its own line-13 import); discovery-first.
- Template reachability, not existence: the two dropdown removals must be
  verified in the rendered page, not by grep (the Decommissioned option
  arrives through a loop variable — a literal grep cannot see it).
