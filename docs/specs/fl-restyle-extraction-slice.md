# Slice: Extract fl-restyle into a shared stylesheet

Prep slice for propagation (Orders -> Provisioning -> Inventory -> Dashboard). No visual change anywhere — fulfillment must render pixel-identical before/after, other pages untouched.

## Current state (verified live 2026-07-09)

- Restyle CSS: inline `<style>` block in fulfillment.html — 85 `fl-`prefixed rules, tokens scoped under `div.fl-restyle`, restyle layer pinned LAST in the block (cascade fix from 772b724).
- Shared CSS: `static/css/main.css?v=<content-hash>` (1184 rules).
- Icon macro already shared: `_fl_icons.html`.
- Hotkeys already shared: `static/js/shortcuts.js?v=20260708b`.

## The work

1. Create `static/css/fl-restyle.css`: move the token blocks (dark + `[data-theme="light"]`), all `fl-*` component rules, background-layer rules, hero/hairline/lap rules, `@property --a`, and keyframes. Leave nothing restyle-related inline in fulfillment.html (if a rule is genuinely page-specific, it stays, gets a comment saying why, and is listed in the commit message).
2. Extract the background-layer markup (`.fl-bg` grid/blobs/spotlight div block) into a Jinja partial (e.g. `_fl_bg.html`) so propagation pages include it instead of copy-pasting.
3. Spotlight mousemove JS: move into the shared JS (shortcuts.js or a new fl-restyle.js) if it is still inline. Keep it null-guarded (no .fl-bg on page = no-op), `var` declarations, idempotent on `htmx:load`.
4. Link the stylesheet in the base template with a cache-buster following the main.css convention. Pages opt in by having `.fl-restyle` on their container — loading app-wide is safe only if the cascade check below passes.

## Cascade risk — read before building (this bug already happened once)

The 772b724 fix worked because the restyle layer sits LAST in the page's inline style block. Moving it to a `<link>` in `<head>` puts it BEFORE every inline `<style>` block again — equal-specificity ties will flip back to legacy rules (the blue mode-toggle / white tabs symptom).

Mitigation, in order of preference:
- Verify every extracted selector carries the `.fl-restyle` scope (higher specificity than bare legacy selectors, making source order irrelevant). Audit the 85 rules for any unscoped ones (`@property` and `@keyframes` are global by nature and fine).
- If any rule genuinely relies on source order, either place the `<link>` after the legacy inline styles (end of head / into the template block that renders after them) or raise its specificity — do NOT re-pin it inline.
- The browser gate must specifically re-check the two past symptoms: mode toggle color and tab styling, plus C2C/receipts for bleed (boosted-nav stale-head gotcha from 772b724).

## Verification gates

Jinja parse -> restart -> hard-reload with cache bypass (content-hash must change; stale worker gotcha) -> Chrome smoke on fulfillment BOTH themes (heroes + lap, cards, search ring, hotkeys, background) -> adjacent pages (dashboard, C2C, receipts) unchanged -> console clean -> git diff review -> commit -> four-location sync.

Suggested commit: `Extract fulfillment restyle css into shared stylesheet and bg partial`
