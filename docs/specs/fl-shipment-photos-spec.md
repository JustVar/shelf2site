# Slice: shipment photos — inbound arrivals + outbound dispatches

Requirement (Jus, 2026-07-10): photograph shipments we receive from partners (edge/cloud boxes — serial labels visible + how the shipment looked on arrival) and units we ship or hand off in the deployment pipeline. Photos tie by serial to the units, with an easy way to save/export the history and details of a unit.

Builds on: the existing receive-page photo upload + OCR (currently orphaned — audit F13/H18: photos are never linked to anything), the uploads backup (photos are now covered by the nightly files tar), and the install-cert PDF pattern (the export precedent).

## Data model

One `unit_photos` table: id, file path, thumbnail path, direction (`inbound` | `outbound`), caption, taken_at, uploaded_by, plus polymorphic context links (nullable): receiving_event_id, customer_order_id, deployment/ship record id. Serial tying is N:M — a single arrival photo can show three boxes' labels — via a `unit_photo_items` join (photo_id, item_id). Tag items on upload by serial (scan or type, reusing the serial lookup); adding/removing tags later is editor-level.

This SUPERSEDES H18: the orphaned photo-link call gets replaced by real linking, and existing orphaned intake photos get a one-time review/adopt-or-archive pass in the migration.

## Capture points (UI)

1. INBOUND — Receive & Scan page: "Add Photos" on the receiving event (and offered right after a scan-intake creates/matches an item, pre-tagged with that serial). Camera capture on mobile (after HTTPS) or file upload; multiple photos per event.
2. OUTBOUND — the Ship Order pane (order action panel) and the deployment wizard: "Add Photos" step — packed unit, serial label, carrier label. Pre-tagged with the order's assigned units; adjustable.
3. Anywhere an item is in hand — Item Detail gains an "Add Photo" action (direction picked at upload).

## Display

- Item Detail: new PHOTOS section — chronological thumbnails, inbound/outbound badge, caption, date, uploader; click for full size. Sits between Receipts and Component History.
- Order detail: photos grouped by direction for all units on the order.
- Receiving event view (event dropdown context or admin receipts page): the event's photo set.

## Export — the "unit dossier"

One click from Item Detail: "Export Dossier" — a PDF (reuse the install-cert PDF generation pattern) containing: item details, current containment + place, custody history, component history, deployment/order history, and all photos (with captions, dates, direction) laid out chronologically. Also available from order detail ("Export All Unit Dossiers" -> one PDF per unit, zipped). This is the artifact someone opens to see a unit's whole life.

## Rules

- RBAC: editor+ upload/tag; viewer sees photos except on sensitive orders (visibility helper applies); kiosk sees none.
- Files stored under the uploads tree (backed up nightly, restore-tested); thumbnails generated server-side; EXIF orientation respected, GPS EXIF stripped on save (photos may leave the building in dossiers).
- Size cap per file + count cap per event (config constants); HEIC accepted if cheap, else clear error.
- Deletion: soft-hide with audit-log entry (photos are condition evidence — hard delete admin-only).

## Gates

Upload from desktop on receive + ship points; tag/untag by serial; item detail section renders both directions; dossier PDF generates with photos and opens; sensitive-order photo hidden from viewer; kiosk 403; mobile capture verified after HTTPS lands (same constraint as scanner camera); backup tar picks up the new files (check the next nightly status size delta); both themes; consoles.

## Sequencing

After the SKU-editor/pipeline unblock (the E2E report's #1) and containment land — outbound photos want the Ship pane to be reachable, and the dossier wants component history to have real data. Mobile capture rides the HTTPS task.
