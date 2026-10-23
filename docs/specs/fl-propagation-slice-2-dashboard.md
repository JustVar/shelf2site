# Propagation slice 2: Dashboard

Dashboard (`/assettracker/dashboard`) opts into the fl-restyle language. Two NEW archetypes get designed into fl-restyle.css here (composition bar, status banner) — build them as reusable `fl-*` components, not dashboard one-offs.

Opt-in recipe as before: `fl-restyle` on the page container, `_fl_bg.html` first child, z-lift content. The pfb overrides and reduced-motion guard come along automatically.

## Component mapping (grounded on live page 2026-07-09)

| Live element | Treatment |
|---|---|
| Search / jump bar ("Search or press / to jump here...", `/` keycap) | Existing search archetype: hover border, focus ring + keycap highlight. `/` hotkey already exists — keep shortcuts.js behavior, do not double-bind |
| Total Items / Deployed / Ready to Deploy summary card | SPLIT into three hero tiles (approved): Total Items (blush glow, box icon), Deployed (green glow, check icon), Ready to Deploy (info glow, truck icon). Value 30px; per-type counts become the sub-line, e.g. "0 Edge · 1 Cloud · 5 C2C" (discovery decides exact data shape). Hairline + hover lap per hero rules |
| Pilots Due Back banner | NEW archetype `fl-banner`: quiet body-card band when all counts are zero; amber tint variant when due soon > 0; red tint variant when overdue > 0. Counts keep status colors either way |
| Inventory composition bar (click segment to filter) | NEW archetype `fl-comp-bar` inside a body card. Approved remap: Camera #A492D6, Computer #0075FF, GPU #FF6B6B, Storage Drive #FFB547, Edge Box #2CD9FF, Camera 2 Cloud #01B574, Cloud Box #7FA3CE. Segments 2px gap, 5px outer radius; hover = slight brighten; active-filter segment gets a lit edge; click-to-filter behavior preserved exactly. Legend dots use the same hues |
| Type cards (Edge Box / Cloud Box / Camera 2 Cloud with Pending / Unassigned / Un-deployable rows) | Body cards; row counts colored: Pending amber, Unassigned muted, Un-deployable red. Header = muted tracked uppercase |
| Quick Actions rail (Add Item N, Check Out O, Check In I, Triage T, Import ↑) | Handoff section 8 exactly: body-card rows, duotone icon per action (blush/green/info/red/amber), mono keycap, hover keycap lift, hotkey press flash. Hotkeys already live in shortcuts.js — wire the flash to the existing handler, do not re-bind |
| Recent Activity list | Body card. Type chips = tint chips using the SAME per-type hues as the composition bar (one hue per type everywhere on the page). New = green tint chip, Edit = muted chip. Dates muted mono. Row hover = subtle bg step. View All = muted link with arrow |

Title Case for status texts. First names only if any people names appear in activity rows (audit-style lines keep full names, same rule as C2C).

## Contracts to preserve (verify live)

Segment click-to-filter, quick-action hotkeys N/O/I/T/import, `/` jump, View All navigation, any tour selectors targeting dashboard elements (grep guide.js), realtime updates if activity list is htmx/websocket-fed (idempotent re-init on `htmx:load`).

## Discipline

Discovery-first on the real template before trusting this table. New CSS only under `.fl-restyle` scope in fl-restyle.css with the `fl-comp-bar` / `fl-banner` components documented in the file header. Guarded patches, `var`, `|tojson|forceescape`, no edits to shared legacy classes. The kept wrapper kit (cmd-band/cb-stats/cb-tools/search) was preserved for exactly this slice — reuse it where it fits rather than adding parallel wrappers.

## Gates

jinja parse -> restart -> Chrome smoke BOTH themes: heroes + lap, banner variants (if data allows, otherwise force via a dev toggle and revert), comp-bar hover/filter, quick-action hotkeys + flash, activity list, reduced-motion spot check -> fulfillment/OEM/C2C unaffected -> non-opted page (Inventory) unchanged -> console clean -> diff review -> commit.

Suggested commit: `Opt dashboard into the fl restyle language with comp bar and banner components`
