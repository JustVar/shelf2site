# Slice: collapsed sidebar redesign

Approved via mock 2026-07-09. Builds directly on the investigation findings (collapse is class-based CSS hiding of an always-rendered DOM, localStorage persistence, pre-hydration class, auto-collapse below 1200px, CSS-only `attr(data-label)` tooltips already on all links).

## The design

Collapsed strip shows TOP-LEVEL items only (~9): Dashboard, Inventory, Asset Triage, Search / Intake / C2C Cameras, Pilots Due Back / Admin.

1. Top-level-only: replace the force-expand rule (`body.sx-nav-collapsed ... max-height: none`) with hiding group/subgroup contents. Admin's lock icon becomes the single entry for the whole admin tree.
2. Section dividers: reuse the hidden section-label elements as 1px hairline rules (`--border`) between MAIN / OPERATIONS / FULFILLMENT / ADMIN in collapsed mode. No markup change per the finding.
3. Admin flyout: opens on hover AND click of the group icon in collapsed mode. `position: fixed` (the `.sx-nav__links` scroll container clips absolute children — the finding's engineering risk), anchored to the icon's viewport rect at open time; re-anchor on scroll or close on scroll, whichever is simpler. Surface: card-bg, lit top edge, radius 12, `--shadow`-style drop, section labels (PEOPLE / DATA & LOGS / INTEGRATIONS / SYSTEM) + rail-style rows with hover tint. Dismiss: mouse-out with a small grace delay, Escape, click-out, or navigation.
4. Active state: when the current page lives inside a group, light BOTH the group icon (blush tint) and the flyout row. Top-level active items keep the blush tint treatment (no left bar needed at collapsed width if it crowds — builder's judgment, show both in the diff screenshot if unsure).
5. Triage alert: collapsed triage icon carries a small amber dot (7px, top-right, sidebar-bg ring) instead of the count chip.
6. Tooltips: keep the existing `attr(data-label)` tooltips on top-level icons; suppress them while a flyout is open for that icon.

## Also in this slice (approved)

- Boosted-nav accordion fix: extend the existing `htmx:load` active re-mark in fl-restyle.js to also open the active group in EXPANDED mode after boosted navigation (currently only on full load). Idempotent, `var`, no new listeners.

## Constraints and gotchas

- New JS goes in fl-restyle.js beside the re-mark logic; `var` declarations; idempotent `htmx:load` re-init; flyout builds from the existing always-rendered DOM (clone or reveal — do not fetch).
- Do not break: localStorage persistence key, the pre-hydration first-paint class, auto-collapse below 1200px, mobile sidebar functions (`toggleMobileSidebar`/`closeMobileSidebar`), tour selectors targeting nav elements (grep guide.js), theme toggle in the footer row.
- New CSS under the chrome section (`fl-nav-*` prefix, outside `.fl-restyle`), respecting the light-twin lesson: every rule that needs a light variant gets the `[data-theme=light]` twin up front, not as a fix-up.
- z-index: flyout above content and above the fixed background; check against modal/drawer layers (nav z=100 today; flyout needs to sit above nav but below modals).

## Gates

Restart -> Chrome smoke BOTH themes: collapse/expand round trip, persistence across reload, flyout open/close all four dismiss paths, active-state tracking into and out of admin pages, boosted-nav accordion opening in expanded mode, below-1200px auto-collapse, tooltips on top-level icons, tours still anchor -> consoles clean -> diff -> commit.

Suggested commit: `Redesign collapsed sidebar with top level icons dividers and admin flyout`
