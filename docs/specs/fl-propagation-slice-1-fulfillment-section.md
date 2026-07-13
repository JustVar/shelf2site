# Propagation slice 1: finish the Fulfillment section

Two parts: (A) C2C Cameras page opts into the design language, (B) the deliberate holds inside fulfillment.html (OEM board internals, modal internals, quick-actions rail) are brought in. After this slice the whole Fulfillment section is coherent. Other pages still untouched.

Shared assets already exist — this slice is opt-in plus restyle, NOT new CSS systems. New rules only where a C2C component has no fulfillment equivalent, added to fl-restyle.css under the same .fl-restyle scope (bump the content hash source if main.py needs it — verify ?v= changes).

## A. C2C Cameras (`/assettracker/fulfillment/c2c`, template for C2C certification)

Opt-in recipe (per the fl-restyle.css header): add `fl-restyle` to the page container, include `_fl_bg.html` as its first child, content z-lift as fulfillment does.

Component mapping (grounded on live page 2026-07-09):

| Live element | Treatment |
|---|---|
| Three top stat tiles (Needed / Assigned / Available in Stock) with green underlines | This page's hero strip: hero gradient + hairline glow + hover lap. Suggested glow colors: Needed = info blue, Assigned = green, Available = blush. Underlines removed. Duotone icon 38px top-right each |
| `+ Assign camera` (green solid, header) | THE one solid blush CTA on this page |
| Order assignment rows (AT-#### chip, SALE/PO / PILOT badge, counts, OVER-ASSIGNED / SHORT chips, Assign button) | Body-card rows (flat + edge highlight + hover). AT chip = blush ID chip. OVER-ASSIGNED = amber tint badge, SHORT = red tint badge. Assign = blush tint button |
| Awaiting Certification cards: left color bar, model chip, PENDING chip, serial, order line, green Certify, View history link | Body-card anatomy: camera name 16px title + ONE badge top-right (PENDING amber tint / CERTIFIED green tint); model + serial as chip row (model = blush mono chip, serial muted); left bars removed; Certify = green tint button (advance-action pattern, same as Move to Delivery); View history stays a muted link |
| Certified cards | Same anatomy, CERTIFIED green tint badge, View = blush tint button |

Status text Title Case (Pending, Certified, Over-Assigned, Short). First names only if any assignee/certifier names appear on cards (certified-by lines keep full names — they are audit lines, not owner slots).

## B. Fulfillment holds

- OEM board internals: mirror the in-house board treatment exactly (same card anatomy, tracker, buttons). Re-check the `/` hotkey on the OEM view (772b724 fixed a swallow there — do not regress it).
- Modal internals: modal surface = `--card-bg` with `--card-edge` top edge, radius 16, overlay dim charcoal; inputs get the search-box focus treatment (accent border + dim ring); buttons = tint pattern, at most one solid blush confirm per modal; NO gradients or glow inside modals.
- Quick-actions rail (if present on fulfillment): handoff section 8 pattern — body-card rows, duotone icon + label + mono keycap, hover keycap lift, hotkey flash, `data-key` + one delegated listener (shortcuts.js already carries the pattern).

## Discipline

Same as always: discovery-first on the real templates (do not trust this doc's element list over what is in the file), guarded patches, new classes under .fl-restyle scope only, never edit shared legacy classes, `var` + idempotent `htmx:load` re-init, `|tojson|forceescape` for onclick args.

Contracts to preserve: certify/assign endpoints and their HTMX targets, view-history links, tour selectors if any target C2C, coverage/search on fulfillment unchanged by the holds work.

Gates per part (A commits separately from B): jinja parse -> restart -> Chrome smoke both themes (C2C: heroes + lap, rows, cards, Certify flow renders; fulfillment: OEM board, one modal open, quick actions + hotkeys) -> adjacent pages unaffected (dashboard, receipts) -> console clean -> diff review -> commit -> four-location sync.

Suggested commits:
- `Opt C2C camera certification page into the fl restyle language`
- `Restyle fulfillment OEM board internals modals and quick actions`
