# Map redesign: customer unit tracking

## PHASE A DECISIONS — LOCKED 2026-07-09 (supersede anything below that conflicts)

1. Deal type: QUERY-TIME derivation only, no new column now. Effective class = order-derived (customer_orders.order_type via device_provisioning) -> inferred from edge_boxes.deployment_type (marked as inferred in popups/provenance) -> 'unassigned'. The override column is deferred until unlinked legacy units actually get geolocated. Migration numbering: directory is truth, next is 062 (CLAUDE.md note stale).
2. Demo: OWN bucket. Map classes: Purchased green #01B574, Pilot amber #FFB547, Try & Buy blue #2C9FD9, Demo purple #A492D6, Unassigned muted gray. UI copy caution: "Try & Buy" means order_type='try_and_buy' (our hardware loaned out) — never conflate with the vendor_trials page (vendor hardware we evaluate).
3. Data source: ITEM-SCHEMA FIRST — key the map on device_provisioning.item_id -> item_schema + item_schema.locations (geo_lat/geo_lng/show_on_map exist), edge_boxes as legacy sidecar. Required for C2C cameras and the unit-type chips.
4. Kiosk: NEW TIER-0 ROLE + route allowlist in auth_redirect_middleware (map route, /map/data, static, logout; all else 302 to map). Update VALID_ROLES/ROLE_TIER in auth.py AND the duplicated role lists in admin-users-v2.js / admin-departments-v2.js. In scope with it, the four operational blockers: sliding session refresh for the kiosk role (wall displays must survive >24h), /map/data returns JSON 401 on expiry (never a 303 HTML redirect) with a client re-login prompt, self-host maplibre + tiles fallback decision for egress-blocked kiosks (investigate cost; at minimum document the constraint), and is_sensitive order filtering folded into the shared visibility helper.
5. Visibility: map_visibility table NOW (level customer|site, normalized string key, visible flag) + existing unit-level show_on_map. Effective visibility = unit AND site AND customer, computed in ONE shared helper that also applies sensitive-order filtering — replace the three copy-pasted show_on_map filters with it. First-class customers table logged as a separate future data-hygiene project (five free-text columns to reconcile).

Phase B also fixes the pre-existing defects found in Phase A: status-filter value mismatch (four vocabularies -> one), popup HTML built by string interpolation (XSS — escape or build via DOM), clearFilters fitBounds on empty bounds, and the DOM-marker performance model (replaced by GPU layers per requirement 4, with the style.load re-add hook for theme swaps).

Purpose: visual representation of where customer units (Cloud Boxes, Edge Units, C2C Cameras) are deployed, sorted by deal type (Pilot, Try & Buy, Purchased), with digestible metrics. Approved mock: `map-redesign-mock-v1.html` (references: Tableau "London in Numbers" for the metric-strip anatomy, "The Land is a Map" for the dark full-bleed map + chart-as-filter rail).

Default map scope: WORLD.

## Requirements added 2026-07-09 (Jus)

1. VISIBILITY CURATION: sites, customers, or individual units can be marked hidden so the map can show only a chosen subset. Server-side flag (not a client filter) at three levels — customer, site, unit — with cascade (hiding a customer hides its sites/units). UI: eye-toggle in the marker popup for editor+ roles, plus a "Hidden (N)" rail card listing hidden entities with one-click unhide. Hidden entities excluded from ALL metrics and rail counts, with the Hidden card as the only trace.
2. MAP-ONLY KIOSK ROLE: a new role that can view and interact with the map page and NOTHING else. Enforcement is SERVER-SIDE: middleware/dependency allows only the map route, its data endpoints, required static assets, and logout — every other route redirects to the map (no 403 page wandering). Client side: chrome renders no nav for this role (map + logout only), global hotkeys (/ jump, quick actions) disabled, and no links that leave the page except logout. Login as this role lands directly on the map. Breaking out requires logging in as a different role. NOTE: the Users page already shows a "Map" permission chip in the grant system — Phase A investigates whether the kiosk role composes from the existing permission model or needs a new role row. Also verify: the kiosk role sees only VISIBLE (non-hidden) entities — curation + kiosk together make the map safely showable to outsiders.
3. BOTH THEMES are a hard requirement for the revamped map, including the tile layer: dark tiles in dark mode, light tiles in light mode. If the current tile source lacks a light style, pick a maplibre-compatible pair and pre-wire both so the theme toggle swaps styles without re-creating the map instance.
4. PERFORMANCE is a hard requirement: pan/zoom must stay smooth. Implementation constraints: markers rendered as maplibre GPU layers (clustered GeoJSON source + circle/symbol layers), NEVER per-unit DOM/HTML markers; filters and mode switches update via setData / setPaintProperty, never tear down and rebuild the map; search debounced; popup is a single reused instance; theme swap keeps the camera. Gate with a synthetic dataset (500+ units) and verify pan/zoom smoothness and filter latency; also keep the map.loaded() race guard.

## Phase A — deal type data model + permission model (investigation -> Chat decision -> migration)

Deal type is NOT tracked cleanly today (confirmed by Jus). Before any UI work:

1. Discovery: map the schema path from a deployed/mapped unit back to its commercial context. Known signals: orders carry Sale/PO vs Pilot chips; the trials page exists (candidate for Try & Buy); pilots-due-back tracks loaner returns. Document which units can and cannot be classified from existing data.
1b. Permission discovery: how the existing grant system works (the "Map" chip seen on Users), how roles gate routes today, and the cleanest path to the kiosk role. Also scope the visibility-flag storage (columns on customer/site/item vs a separate map_visibility table) and report both with the deal-type options.
2. Report back to Chat with derivation options, e.g.: (a) derive at query time from order linkage; (b) add a `deal_type` column on the deployment/item record, backfilled from orders/trials, editable thereafter; (c) hybrid — derived default + manual override. Include counts of classifiable vs unclassifiable units.
3. DECISION GATE: no migration until the option is picked in Chat. When it is: guarded migration per the workflow skill (SQLAlchemy JSONB reassignment gotcha if any JSONB is touched; DeviceProvisioning polymorphic device link gotcha for anything reaching devices via device_table + device_id).
4. Unclassified units render as a fourth muted gray "Unassigned Deal" class on the map — never silently dropped.

## Phase B — UI build (after Phase A lands)

### Hero metric strip (5 tiles, hairline treatment)
- Deployed Units (sub: N Customers · N Sites)
- Purchased (sub: % of fleet)
- Pilots (sub: N Due Back in 30 Days — same source as pilots-due-back)
- Try & Buy (sub: N converting this month, if derivable)
- New in 30 Days (sub: Pilot -> Purchase conversion %, if derivable; drop the sub rather than fake it)

### Left rail
- "Color units by" mode switcher: Deal Type / Unit Type / Status. Mode swaps the marker color dimension AND the legend. Persist choice in localStorage.
- Deal-type horizontal bars: count bars in deal colors; CLICK A BAR = filter toggle (dimmed when excluded). This replaces checkbox filters for the deal dimension.
- Unit-type chips (Cloud Box / Edge Unit / C2C Camera) in FL hues, toggleable.
- Top Customers by Units ranking (top 5, click -> zoom map to that customer's pins if cheap, else just filter).
- Missing Location Data card: count + "Fix" link to the existing needs-location flow. Keep the existing search box (search by serial/org/customer/site) at the top of the rail.

### Map (maplibre, existing)
- World default frame; cluster markers that split on zoom (maplibre cluster source), cluster color = dominant class in cluster.
- Dot markers colored by active mode; deal colors: Purchased green #01B574, Pilot amber #FFB547, Try & Buy blue #2C9FD9, Unassigned muted gray. Unit-type mode uses FL hues; status mode keeps the existing server-fed status colors.
- Click marker -> popup card (fl card surface): customer, site + city, unit name, mono serial, deal badge, deployed date, due-back date when pilot/try-and-buy (amber when within 30 days), View Item link.
- On-map legend card (bottom-left) reflecting active mode; zoom controls stay on card surfaces.
- FIX the pre-existing race: guard filter/search JS behind map.loaded() (observed maplibre lng error when interacting within ~1-2s of load).

### Theme + performance
Per requirements 3 and 4 above: paired dark/light tile styles swapped without map re-creation; GPU-layer markers only; setData updates; synthetic 500-unit perf gate.

### Visibility + kiosk in the UI
Editor+ view: eye-toggle in popup, Hidden (N) rail card with unhide. Kiosk role view: rail and map only — no chrome nav, no hotkeys, logout reachable; hidden entities absent entirely.

## Contracts
Existing map behaviors (search, status filters, needs-location list), pilots-due-back counts consistency, item links. Tours if any target the map page. Existing roles keep exactly their current access — the kiosk role is additive; permission changes must not touch other roles' route access (regression-check one admin, one editor, one viewer path).

## Gates
Phase A: migration dry-run + row-count assertions + rollback note before applying; report classifiable counts + permission findings. Phase B: standard gates + interaction smoke (mode switch, bar filter, chip toggles, cluster split, popup, world frame, race guard, theme swap keeping camera, 500-unit perf pass) in both themes. Kiosk role: attempt-every-route probe as the kiosk user (all must land back on the map), hotkeys dead, logout works, hidden entities invisible. Curation: hide/unhide round trip at all three levels with cascade verified.
