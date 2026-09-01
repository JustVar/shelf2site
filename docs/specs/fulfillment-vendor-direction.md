# Fulfillment vendor direction

Status: direction ratified 2026-09-01 by Jus. This file records the WHAT and
WHY of two decisions made together; the HOW of any build that follows is the
`asset-tracker-workflow` skill. Repo facts live in `CLAUDE.md`.

## Direction change: consumer orders route through a hardware vendor

All consumer orders going forward route through a 3rd-party hardware vendor.
The vendor builds, certifies, and ships. We coordinate between the vendor, the
system integrator, and customer delivery and setup. C2C is near-identical:
customers order through the C2C vendor rather than through us directly.

## Consequences for the pipeline

- **The fulfillment pipeline stays, streamlined.** We initially receive little
  from the vendor beyond the SKUs to build per order.
- **Certified documents arrive later.** Eventually we require the vendor's
  certified documents, software and hardware validations both, for our own
  records.
- **Build certification shrinks to internal and legacy use.** The in-app,
  two-person, all-pass flow was designed for builds we perform. The vendor
  performs them now.
- **Installation certification survives and gains weight.** Its shape, receive
  a completed document and record who certified and who installed, fits the
  vendor model as-is. See `docs/specs/installation-certification.md`.

## Deletion decision: refuse while deployment records exist

Ratified the same date: order deletion is REFUSED while any deployment record
exists on the order.

Rationale. No route deletes a deployment record directly; the reads table in
`docs/specs/link-units-to-deployments.md` (line 47) calls that out as create,
status, certify only. Yet `DELETE /api/orders/{id}` (orders.py:409) deleted
them wholesale: `customer_orders -> deployment_records` is ON DELETE CASCADE,
and `deployment_records -> installation_certification` cascades again, so one
unguarded order delete erased visits and their certifications with only a one
line order_deleted audit row surviving. The schema decided what no spec ever
did, in the direction the rest of the design implicitly rejects. Seven
order_deleted rows exist in the live log, so the path is exercised.

An app-layer guard is chosen over an FK migration for now. Changing the FK to
RESTRICT remains a possible follow-up; the guard is one read plus one refusal
in the handler and reversible without a migration.
