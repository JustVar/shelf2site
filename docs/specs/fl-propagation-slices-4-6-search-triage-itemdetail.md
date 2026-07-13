# Propagation slices 4-6: Search, Asset Triage, Item Detail

Three slices, one page each, in this order (smallest first). Each: own commit + gates + four-location sync before the next. All three flip to `FL_CATEGORY_COLORS` on opt-in and reuse existing archetypes — no new archetypes expected; anything genuinely new comes back to Chat for a mock before building.

Shared opt-in recipe as before. After slice 6 ships, legacy `CATEGORY_COLORS` may have zero remaining consumers — check and note it for a cleanup commit if so.

Scope guard: the sidebar/topbar chrome stays legacy on ALL pages for now — chrome is a future dedicated cross-page slice, not part of these.

## Slice 4: Global Search (`/assettracker/search`)

| Live element (2026-07-09) | Treatment |
|---|---|
| Page header + subtitle | Standard restyle header text |
| Big search input (clear x inside, Clear button beside) | Search archetype: hover border, accent focus ring; Clear = tint button; keep debounce and the 2-char hint |
| Results summary: "N results found" + per-category count pills | Count = 500-weight; pills = tint chips in FL hues with count |
| Results table (Category pill, Name/Device, Serial, Status, MAC, Location, Actions pencil) | `fl-table`: category tint chip (drop the legacy dot, chip suffices), serial + MAC mono muted, status per the status rule (alert statuses chip, neutral muted text), pencil = blush tint icon button |
| Search-all flat mode stage chips (`.o-stage-chip`, JS-built) | PRESERVE — this class is alive only through JS strings (772b724 regression history). Restyle its rule under `.fl-restyle` scope, do not rename it |
| Hint / empty state | Muted centered text |

Contracts: debounced live search, clear behaviors, edit-pencil navigation, `.o-stage-chip` render in flat mode (force a query that produces it), tour selectors.

Suggested commit: `Opt global search into the fl restyle language`

## Slice 5: Asset Triage (`/assettracker/triage/`)

| Live element | Treatment |
|---|---|
| Role tabs (Hardware inventory 12 / Accounting 14 / Deployment 14) | Tab archetype: blush underline active; count badges = amber tint chips (they are alert counts) |
| Sort select + Per Page select | Select treatment (card-bg, border, accent focus) |
| Table: checkbox, expand caret, ID, Item (name+serial), Category, "N missing", Open | `fl-table` + checkbox archetype. ID mono muted; category tint chip FL hue; "N missing" = amber tint chip; Open = blush tint button; expand caret = muted duotone chevron that rotates when open |
| Row expansion panel (inline missing-fields editor) | Inset body-card surface within the row; inputs/selects get the focus-ring treatment; the panel's save/apply follows tint pattern; EXPANSION BEHAVIOR IS A CONTRACT — exercise expand, edit, collapse live |
| Bulk selection (select-all present) | Same checkbox + bulk-bar archetypes as inventory IF bulk actions exist (discovery — none were visible in my session) |

Contracts: tab switching with counts, sort + per-page reload, row expand/collapse + inline save, Open navigation (items/:id?edit=1), select-all state, tour selectors, htmx re-init idempotent.

Suggested commit: `Opt asset triage into the fl restyle language`

## Slice 6: Item Detail (`/assettracker/items/:id`, view + edit modes)

| Live element | Treatment |
|---|---|
| Back link "<- Inventory" | Muted link with arrow |
| Header: item name + category chip + status | Category chip FL hue; status per status rule; name stays h1 |
| Edit button (view mode, currently blue solid) | The page's ONE solid blush CTA in view mode |
| Edit mode: Cancel (top right) + Save (discovery: find it) | Save = the one solid blush in edit mode; Cancel = tint. Never two solids at once |
| Presence banner ("X is viewing this record", locks.js) | `fl-banner` info variant (info tint). Do NOT touch locks.js logic |
| Section cards (Details, Specifications, Identifiers, Receipts, Component History, Maintenance Log, Check-out History) | Body cards, muted tracked uppercase headers; definition grid = 11px tracked muted labels over 13px values; empty states muted text |
| + Add Receipt | Blush tint button; receipt rows (when present) = list rows with hover step |
| Edit mode inputs/selects across all sections | Focus-ring form treatment |
| History sections with tabular data (discovery: check populated items, e.g. check-out history) | `fl-table` if tabular, list rows if not |

Contracts: edit-mode toggle + save/cancel round trip (exercise on a test item, revert changes), locks/presence banner behavior with a second session if feasible or by code inspection, receipt add flow opens (cancel before submit), category/status select options, tour selectors.

Suggested commit: `Opt item detail into the fl restyle language`

## Discipline and gates (all three)

Discovery-first per page — my session saw empty receipts/history and no bulk ops on triage; the templates know better. All new CSS under `.fl-restyle`; guarded patches; `var` + idempotent `htmx:load`; `|tojson|forceescape`; no shared legacy class edits; wrapper kit reuse.

Gates per slice: jinja parse -> restart -> Chrome smoke BOTH themes (page-specific interactions listed above) -> adjacent opted pages unaffected -> remaining non-opted pages (Intake, Pilots Due Back, Admin) unchanged with legacy hues -> console clean -> diff review -> commit -> four-location sync.
