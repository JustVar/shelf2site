# Tail slices: complete coverage

Goal declared by Jus: EVERY page restyled. So this spec ends with a provable sweep, not a page list from memory.

## T0 first: route-table census (do this before any styling)

Enumerate the full route -> template map from app/main.py (and any routers), list every template that renders a page (extends base.html or standalone), and diff against the opted-in set. Output the census table in the session notes BEFORE starting T1 — it drives the remaining work and catches anything this spec does not name (the audit_log.html orphan lesson, systematized). Known-unopted from Code memory + Chat discovery: checkout, checkin, disposal, map, warranty, receive, cert histories, and whatever the Orders/Provisioning family maps to in routes.

## T1: flow form pages (checkout, checkin, disposal, receive, warranty, and any census-found siblings)

All appear to be small form pages (checkout verified live 2026-07-09: two selects + external-name input + notes + Cancel/solid-blue Check Out). Treatment is pure archetype reuse, one commit for the whole family if diffs stay mechanical, else split:

- Opt-in recipe per page; section body cards; focus-ring form treatment; helper text muted.
- Page action button (Check Out / Check In / Dispose / Receive) = the page's ONE solid blush; Cancel = tint.
- Destructive flavor (disposal): keep the solid blush for the primary action but confirmation modal (if any) uses red tint for the destructive confirm per the danger rule — no solid red.
- Contracts: each form's submit round trip exercised on test data where safe; item selects populate; checkout/checkin state round trip (check an item out, verify, check it back in — self-reversing, safe).

Suggested commit: `Opt checkout checkin and flow form pages into the fl restyle language`

## T2: deployment map (`/assettracker/map/`)

Two-column: map canvas + right rail (search, status filter checkboxes, stats, legend, needs-location list).

- Rail: search archetype input; checkboxes = blush checkbox archetype; Clear All Filters = tint button; stats = definition rows (Missing Coordinates count keeps amber); legend dots keep their SERVER-FED status colors (functional, like inventory tiles); needs-location rows = body-card list rows with mono serials.
- Map canvas: wrap in a body card frame (lit top edge). The map library's tiles/markers are OUT of scope for restyle — do not fight the library CSS; only check the library popups/controls do not clash (zoom buttons may take card-bg + border if trivially styleable).
- Contracts: filter checkboxes re-render markers, search filters, needs-location list links, map interactions (zoom/pan) unaffected.

Suggested commit: `Opt deployment map into the fl restyle language`

## T3: cert histories + Orders/Provisioning family + census stragglers

Discovery-first per page from the T0 census. Expected mapping: histories -> fl-table or list rows; provisioning boards -> fulfillment card/board archetypes (note the DeviceProvisioning polymorphic device link gotcha from CLAUDE.md when touching anything data-adjacent — this slice is CSS/template-only, do not refactor that linkage). Anything with no archetype: STOP, bring to Chat for a mock. One commit per coherent group.

## T4: cleanup

- Delete orphaned audit_log.html (verify no route/include references first).
- Dead CSS sweep in the c2c/receipts orbit (same grep-matrix discipline as the hygiene slice: templates + JS-built strings + tour targets).
- After T1-T3: re-run the census; assert zero unopted page templates remain. Paste the final census in the report — that is the "every page restyled" proof.

Suggested commits: `Remove orphaned audit log template` / `Remove dead css in the c2c receipts orbit`

## Investigation item (separate, before or parallel): collapsed sidebar icon overload

Observed live (2026-07-09): collapsing the sidebar flattens EVERY nav item into one strip of ~20 duotone icons — including all Admin sub-pages — with no grouping, labels, or hierarchy. Expanded mode has nested sections; collapsed mode loses them entirely.

Investigate in Code: how sxNavCollapse() builds the collapsed state (server-rendered always, CSS-hidden labels? or JS rebuild), whether nested groups are collapsible there today, and what tooltips exist.

Design direction to validate (final design gets a Chat mock before build):
1. Collapsed mode shows TOP-LEVEL items only; nested groups (Admin, and its PEOPLE/DATA & LOGS/INTEGRATIONS/SYSTEM subgroups) collapse to ONE Admin icon.
2. Clicking/hovering a group icon in collapsed mode opens a flyout panel (card-bg, lit edge, rail-row items) listing the children.
3. Thin section dividers between MAIN / OPERATIONS / FULFILLMENT / ADMIN in the collapsed strip.
4. Hover tooltips (title or styled) on every collapsed icon.

Deliverable of the investigation: findings + feasibility notes back to Chat; then mock; then its own slice.

## Discipline and gates

Standard: discovery-first, `.fl-restyle` scope (chrome-level rules under fl-nav-*), guarded patches, `var` + idempotent `htmx:load`, `|tojson|forceescape`, no shared legacy edits. Gates per commit: jinja parse -> restart -> Chrome smoke both themes -> adjacent pages -> consoles -> diff -> commit -> four-location sync.
