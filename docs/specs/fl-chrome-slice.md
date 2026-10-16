# Chrome slice: sidebar, topbar/banners, footer, login

The finale. Chrome spans EVERY page, so this slice interacts with scaffolding the content slices built around it: the `body:has(.fl-restyle)` z-lifts, the fixed `.fl-bg` layer, and the login page living outside base.html. Approved via mock 2026-07-09 (one tweak: real logo assets, below).

## Logo directives (approved)

- Sidebar: KEEP the current logo exactly as it is today. Do not swap or restyle it.
- Login page: use the actual full logo lockup (mark + wordmark) instead of any text rendering.
  - ASSET SOURCE: the file is in the workstation Downloads folder, named `Logo-Full` (check extension). Copy it into the repo static images directory (e.g. `static/img/logo-full.png`), commit it with this slice, and reference it with the cache-busted static path convention.
  - CONTRAST CHECK at build time: if the file has a solid white background or the wordmark reads poorly on the charcoal card, place the logo inside a white rounded inset panel on the card rather than editing the asset. Verify visually in both themes.

## Sidebar

| Element | Treatment |
|---|---|
| Surface | `--sidebar-bg`, 1px `--border` right edge |
| Section labels (MAIN, OPERATIONS, FULFILLMENT, ADMIN groups) | Muted tracked uppercase (existing style tokenized) |
| Nav items | Muted text + duotone icon (16px, from the macro set; add nav icons to the set as needed) |
| Active item | Blush tint bg + `--accent-primary-l` text + 2px blush left bar (approved; nav convention, distinct from the banned card bars) |
| Hover | `--card-bg-hover`-style step, text brightens |
| Triage count badge | Amber tint chip |
| Admin expandable groups | Same nav treatment; chevron muted duotone, rotates open |
| User footer | Flat blush avatar circle (subject exception), name 500-weight, role in mono muted |
| Bottom action row (Tours / Light / Password / Logout) | Muted duotone icons + labels; hover brightens; no color except hover |
| Collapse toggle | Muted, tint on hover |

## Topbar / banners / footer

Discovery first: inventory what base.html actually renders (the z-lifted topbar and banner regions referenced by the `body:has` rules, the fulfillment footer, toasts from toast.js). Treatment: banners use `fl-banner` variants; toasts get card-bg surface + lit top edge + status tint edge per type; footer = muted text + green pulse dot (already styled on fulfillment — unify).

## Login page

Outside base.html — needs its own opt-in handling (it cannot rely on the base template include). Charcoal bg + dot grid + ONE aurora blob (subtle; skip the spotlight and lap — no JS on login beyond what exists), centered card (card-bg, lit top edge, radius 14), full logo lockup centered, labeled inputs with the focus-ring treatment, Sign In as the page's one solid blush, error state (bad credentials) = red tint banner above the form. Both themes if login respects the theme; otherwise dark only is acceptable — discovery decides.

## Interactions to guard (the reason this is its own slice)

- `body:has(.fl-restyle)` z-lift rules: the restyled sidebar/topbar must not double-apply or fight them; consolidate rather than layer another `:has` chain.
- The fixed `.fl-bg` layer currently spans the viewport under the opaque sidebar — if the sidebar gains any translucency, the grid will show through; keep it opaque.
- Sidebar is shared by EVERY page including any not-opted edge templates; since chrome is now restyled globally, the `.fl-restyle` scoping model shifts: chrome styles may live OUTSIDE the scope (they apply everywhere) — put them in fl-restyle.css under a clear `/* chrome */` section with their own prefix (`fl-nav-*`), NOT under `.fl-restyle`, and verify on at least one of every template family.
- hx-boost: nav clicks re-render content, not chrome — verify active-item state updates correctly after boosted navigation (the htmx:load hook may need to re-mark the active item; check how it works today first).
- Tours: guide.js may anchor to sidebar selectors — grep and keep every targeted class/id.
- theme.js toggle lives in the bottom action row — its JS contract untouched.

## Gates

The widest verification of the project: jinja parse -> restart -> Chrome smoke on one page from every family (dashboard, fulfillment, C2C, pilots, inventory, search, triage, item detail, intake, admin people, admin logs, admin system) in BOTH themes, checking sidebar render + active state + boosted nav + no z-fighting with modals/drawers -> login page load + failed-login error state + successful login round trip -> toasts fire correctly (trigger one) -> consoles clean -> diff review -> commit -> four-location sync.

Suggested commits (two):
- `Restyle app chrome sidebar banners footer and toasts`
- `Restyle login page with full logo lockup`
