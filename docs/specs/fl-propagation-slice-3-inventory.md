# Propagation slice 3: Inventory

Inventory (`/assettracker/inventory/`) opts into fl-restyle. Two NEW archetypes (approved via mock 2026-07-09): `fl-filter-tiles` and `fl-table`. Build both as reusable components in fl-restyle.css — Search and Asset Triage will reuse `fl-table`.

Opt-in recipe as before (`fl-restyle` container class, `_fl_bg.html` first child, z-lift). Import `FL_CATEGORY_COLORS` from dashboard.py (move it to a shared module if cleaner — it now has two consumers; keep legacy `CATEGORY_COLORS` untouched for search/item_detail/triage until their slices).

## Component mapping (grounded live 2026-07-09)

| Live element | Treatment |
|---|---|
| Category filter tile strip (All Items + 7 types, colored top borders, active state) | NEW `fl-filter-tiles`: mini body-card tiles (value 18px + tracked uppercase label). EVERY tile carries a faint static hairline in its category hue (50% alpha, no shadow). ACTIVE tile: hairline at full strength + glow shadow + stronger border. All Items tile uses blush. Hues from FL_CATEGORY_COLORS. Click-to-filter behavior preserved |
| Search input + All Statuses / All Locations selects | Search archetype for the input. Selects: card-bg surface, 1px border, radius 10, accent focus ring; option lists native (no custom dropdown build) |
| Bulk bar (appears on selection: "N selected", Clear, Actions dropdown) | Blush-bordered band (card-bg, `--accent-border` border), count 500-weight, Clear = muted underlined link, Actions = blush tint button. Dropdown menu = panel surface (card-bg, lit top edge, radius 10), rows hover like rail rows |
| Table | NEW `fl-table` inside a body card: muted tracked uppercase headers with 1px bottom border; rows separated by faint hairlines; hover = subtle bg step; selected row = blush wash (`rgba(194,158,155,0.07)`) + blush checkbox; name 500-weight with mono muted serial beneath; category chip = tint chip in FL hue; STATUS RULE: only alert statuses get tint chips (Deployed green, Pending amber, Un-deployable red) — neutral statuses (Ready to Deploy, Unassigned) are muted plain text; location/SKU/date muted (dates mono); View = blush tint button |
| Checkboxes (row + select-all) | 13px rounded squares, muted border; checked = blush fill + dark check; select-all indeterminate = blush dash |
| "14 items" header count | Muted text, keep |

Title Case status texts. One hue per category everywhere (tiles, chips) — same FL map as dashboard.

## Contracts to preserve (verify live)

Tile click-to-filter, search filtering, status/location select filtering, row selection + select-all + Clear, Actions dropdown operations (inventory bulk ops — exercise at least one non-destructive one), View navigation to item detail, sorting if any column headers sort (discovery: check for sort handlers), htmx/realtime row updates if present (idempotent re-init), tour selectors (grep guide.js for inventory targets).

## Discipline

Discovery-first on the template — this page is table-heavy and likely has states not visible in my session (empty filter results, pagination if any, un-deployable rows). Style the empty state too (muted centered text in the card, per the OEM column pattern). All new CSS under `.fl-restyle` scope; `fl-filter-tiles` and `fl-table` documented in the file header. Guarded patches, `var`, `|tojson|forceescape`, no shared legacy class edits, wrapper kit reuse where it fits.

## Gates

jinja parse -> restart -> Chrome smoke BOTH themes: tiles (active + inactive, click to filter), table (hover, select one + select-all, bulk bar + Actions menu, View), search + selects filter, empty-filter state, reduced-motion spot check -> dashboard/fulfillment/C2C unaffected -> non-opted page (Search or Triage) unchanged with legacy hues intact -> console clean -> diff review -> commit.

Suggested commit: `Opt inventory into the fl restyle language with filter tile and table components`
