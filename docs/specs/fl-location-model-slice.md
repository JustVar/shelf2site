# Slice: typed location model + address geocoding

Decisions locked 2026-07-09 (Jus): the map shows CUSTOMER UNITS ONLY (an office map for in-stock items is a someday item, not now); site coordinates come from ADDRESS + AUTO-GEOCODE on the site record; the two place vocabularies (item `locations` and fulfillment `sites`) get TYPED UNIFICATION.

## The lifecycle model (the contract everything else follows)

- Every unit has exactly one current place at a time.
- Place records are typed: `office` or `customer_site`.
- In stock -> unit sits at an office place. Set at intake/receive via the existing location select. Offices are geocoded once ever (or not at all — they never render on the customer map).
- Deployed -> unit sits at a customer site. The assignment happens in the deployment/fulfillment flow (the deploy wizard already captures the site) — never manually on the map.
- Geo lives ON the place record. Units inherit their place's pin. The map Fix flow becomes a fallback for stragglers, not the primary entry point.
- Inconsistency surfacing: a unit with status in_stock assigned to a customer_site (or deployed status at an office) is a data smell — expose it as a triage-able condition (candidate: a new check in Asset Triage's deployment-tracking role rather than a new page).

## Work items

1. Migration (next number per directory): one unified place table with `type` (`office` | `customer_site`), merging the item `locations` vocabulary and the `sites` vocabulary. Backfill: existing item locations default to `office`; fulfillment sites to `customer_site`; the 8 seeded geo records classify as customer sites. Preserve ids or provide a mapping so item FKs, deploy wizard references, and the map data endpoint survive. This is the five-free-text-columns problem's sibling — do NOT attempt the customers unification here, just places.
2. Site create/edit form gains an address field; on save, geocode to lat/lng.
   - Geocoding service: default Nominatim (OSM) with proper User-Agent, 1 req/sec rate compliance, and result caching on the place row (only re-geocode when the address changes). Graceful failure: save succeeds without coordinates, banner offers retry / pick-on-map fallback (the existing Fix flow). Egress note: apphost must be able to reach the geocoder; if egress is blocked, the flow degrades to Fix-only and says so.
   - Store both: address text (source of truth for humans) and resolved lat/lng + geocode timestamp (source of truth for the map).
3. Map data endpoint: filter to `type = customer_site` places only (composed into the shared visibility helper from the map slice). Office-located units drop off the map entirely.
4. Intake/receive location select: offices only. Deploy wizard site select: customer sites only. Both read the unified table filtered by type.
5. Popup semantics: unit status shown Title Case (folds in the existing polish task); the in_stock-at-customer-site case renders with an amber data-check hint instead of pretending it is fine.

## Contracts to preserve

Existing item location assignments and their history, deploy wizard round trip, map visibility helper + kiosk filtering (types compose with, not replace, visibility), sites/site_detail pages (they become the customer_site management surface and the natural home of the address field), inventory location filter select, item detail location display.

## Gates

Migration dry-run with row-count assertions both vocabularies -> unified table; geocode round trip on a real address (verify pin lands where expected); graceful-failure path exercised (bad address, geocoder unreachable); map shows only customer sites; office units absent; intake and deploy selects correctly split; triage inconsistency check fires on a seeded bad record and clears; both themes; consoles.

Backlog note recorded: office map for in-stock items — someday, explicitly not now.
