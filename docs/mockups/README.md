# Fulfillment design tokens and card contract

Canonical reference for the Building board and fulfillment UI. Values read directly from the live stylesheets and `app/routes/fulfillment.py`, not transcribed from memory. Update this file when the tokens change.

## Superdesign mockups

Light-mode Superdesign reference mockups live in [`superdesign/`](superdesign/SUPERDESIGN.md). They are design intent only (layout, component structure, the 5-dot stage tracker, initials badges, modal shapes). Translate them into the dark tokens documented in this file. Do not copy their light-mode Tailwind.

## How theming works

There is **no `:root`**. Theming is driven by a `data-theme` attribute on the document:

- Global tokens: `[data-theme="dark"]` (default) and `[data-theme="light"]` in `static/css/main.css`.
- Page tokens: `.fulfillment-page` (default) and `[data-theme="light"] .fulfillment-page` in `fulfillment.html` override a subset of globals and add the `--fl-*` / `--tint-*` sets.

A token's value depends on **which scope the element is in**. Inside `.fulfillment-page` the overrides win; everywhere else the globals apply.

## Gotchas (read first)

1. **`--accent-blue` is teal globally but emerald on the fulfillment page.** The name says "blue"; on `.fulfillment-page` it resolves to emerald. Anything referencing `--accent-blue` must know its scope.

   | scope | dark | light | reads as |
   |---|---|---|---|
   | global (`[data-theme]`, main.css) | `#127CA3` | `#0e6a8e` | teal-blue |
   | `.fulfillment-page` (override) | `#10b981` | `#059669` | emerald |

2. **`--bg` is referenced but undefined.** `.o-sku` sets `background: var(--bg)` but no token block defines `--bg`, so it resolves transparent. Either define it or give the `var()` a fallback if the SKU chip needs a fill.

3. **SE palette hues overlap board tokens.** `#10b981` (SE index 3) equals the fulfillment `--accent-blue` (emerald); `#3b82f6` (SE index 0) equals the `--tint-normal` blue. An avatar can share a hue with the board accent or a card tint.

4. **Urgency color is inconsistent across card parts.** Overdue renders **red** on the left accent bar (`--urg` = `--fl-red`) but **orange** on the status dot and the High Priority pill (`--fl-orange` / `rgba(249,115,22,…)`). Same urgency, two hues. Decide deliberately if you touch this.

## Global tokens (main.css)

| token | dark | light |
|---|---|---|
| `--text` | `#ecf0f1` | `#1a202c` |
| `--text-muted` | `#95a5a6` | `#64748b` |
| `--card-bg` | `#1e2a3a` | `#ffffff` |
| `--border` | `#2c3e50` | `#e2e8f0` |
| `--accent-blue` (teal) | `#127CA3` | `#0e6a8e` |
| `--accent-blue-l` | `#1a9fd4` | `#127CA3` |
| `--accent-blue-dim` | `rgba(18,124,163,.15)` | `rgba(14,106,142,.12)` |

## Fulfillment-page tokens (`.fulfillment-page`)

Surface / text overrides:

| token | dark | light |
|---|---|---|
| `--card-bg` | `#232a44` | `#ffffff` |
| `--border` | `#2d3748` | `#e2e8f0` |
| `--text` | `#e2e8f0` | `#0f172a` |
| `--text-muted` | `#94a3b8` | `#64748b` |
| `--accent-blue` (emerald) | `#10b981` | `#059669` |
| `--accent-blue-l` | `#6ee7b7` | (emerald family) |
| `--accent-blue-dim` | `rgba(16,185,129,.15)` | (emerald family) |

Semantic `--fl-*`:

| token | dark | light |
|---|---|---|
| `--fl-green` | `#22c55e` | `#22c55e` |
| `--fl-green-dim` | `rgba(34,197,94,.15)` | `rgba(34,197,94,.10)` |
| `--fl-amber` | `#f59e0b` | `#d97706` |
| `--fl-amber-dim` | `rgba(245,158,11,.12)` | `rgba(217,119,6,.10)` |
| `--fl-red` | `#ef4444` | `#dc2626` |
| `--fl-red-dim` | `rgba(239,68,68,.12)` | `rgba(220,38,38,.10)` |
| `--fl-orange` | `#f97316` | `#ea580c` |
| `--fl-purple` | `#a855f7` | `#9333ea` |
| `--fl-card2` | `rgba(255,255,255,0.04)` | `#f1f5f9` |
| `--fl-border2` | `rgba(255,255,255,0.08)` | `#cbd5e1` |

Card tints (`data-tint` background + border):

| token | dark | light |
|---|---|---|
| `--tint-high-bg` | `rgba(249,115,22,.10)` | `rgba(249,115,22,.06)` |
| `--tint-high-border` | `rgba(249,115,22,.2)` | `rgba(249,115,22,.15)` |
| `--tint-normal-bg` | `rgba(59,130,246,.10)` | `rgba(59,130,246,.06)` |
| `--tint-normal-border` | `rgba(59,130,246,.2)` | `rgba(59,130,246,.15)` |
| `--tint-ready-bg` | `rgba(16,185,129,.10)` | `rgba(16,185,129,.06)` |
| `--tint-ready-border` | `rgba(16,185,129,.2)` | `rgba(16,185,129,.15)` |

## Stage tuple

Defined as `_btabs` in `fulfillment.html`; drives the tab bar, per-card stage context, and the flat-mode stage chip.

| key | label | color (`tcolor`) |
|---|---|---|
| `queued` | Queued | `var(--text-muted)` |
| `in_progress` | In Progress | `var(--accent-blue)` (emerald here) |
| `ready_for_handoff` | Ready for Handoff | `var(--fl-green)` |

## Card visual contract

Driven by `g.tab` and `g.urgency`. Queued cards omit the tint, dot, and pill entirely.

| part | ready_for_handoff | overdue | critical | soon | else (normal) |
|---|---|---|---|---|---|
| `data-tint` | `ready` | `high` | `high` | `normal` | `normal` |
| `--urg` (left bar) | `--fl-green` | `--fl-red` | `--fl-amber` | `--fl-amber` | `--accent-blue` |
| status dot (avatar badge) | `--fl-green` | `--fl-orange` | `--fl-orange` | `--accent-blue` | `--accent-blue` |
| `o-pill` | "Ready" `.ready` | "High Priority" `.high` | "High Priority" `.high` | "Normal" `.normal` | "Normal" `.normal` |

Pill styles: `.ready` = `--fl-green-dim` bg / `--fl-green` text; `.high` = `rgba(249,115,22,.14)` bg / `--fl-orange` text; `.normal` = `--fl-card2` bg / `--text-muted` text.

Flat-mode stage chip (`.o-stage-chip`): outlined chip, `color` and label from the stage tuple's `tcolor`/`tlabel`; hidden by default, shown only under `#kanban-ih.flat`.

Status dot is a corner badge on the avatar (`oc-head-r` is `position: relative`; dot is `position: absolute; bottom:-1px; right:-1px` with a `box-shadow: 0 0 0 2px var(--card-bg)` ring).

## SE avatar palette

`_SE_PALETTE` in `app/routes/fulfillment.py:127`, theme-agnostic (raw hex, no CSS var):

| index | hex | hue |
|---|---|---|
| 0 | `#3b82f6` | blue (= `--tint-normal`) |
| 1 | `#a855f7` | purple |
| 2 | `#f97316` | orange |
| 3 | `#10b981` | emerald (= fulfillment `--accent-blue`) |
| 4 | `#f43f5e` | rose |
| 5 | `#f59e0b` | amber |

- `_se_color(name)`: unassigned → `var(--text-muted)`; else `_SE_PALETTE[sum(ord(c) for c in name) % 6]`. The hash is a plain char-sum, so it is **order-insensitive** (anagrams / same letter sets collide to one color).
- `_se_initials(name)`: empty → `?`; two or more words → first letter of the first two (`Alice Smith` → `AS`); else first two chars (`Bob` → `BO`).

## Fonts (all self-hosted in `static/css/fonts.css`, no CDN)

Loaded at `/assettracker/static/fonts/*.ttf`, `format('truetype')`, `font-display: swap`.

| family | weights | role |
|---|---|---|
| Inter | 400 / 500 / 600 / 700 | body sans; modal + slide-panel text |
| Barlow | 300–700 | — |
| Barlow Condensed | 400 / 600 / 700 | — |
| IBM Plex Mono | 400 / 500 | mono; `.o-sku` (weight 500) |
| Space Grotesk | 700 | numeric accent: stat numbers, badges, counts |

Cache-busted via `fonts.css?v=N` in `base.html` (currently `v=3`). Bump `N` when adding or changing a face so cached clients re-fetch.
