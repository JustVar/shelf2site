# The fl design language — in-repo reference

The visual language ("fl") started on the fulfillment board and now covers every
page plus the app chrome. This doc captures the token set and the component
archetypes so the system lives in the repo, not in chat specs. Source of truth
for values is **`static/css/fl-restyle.css`** — if this doc and the CSS ever
disagree, the CSS wins and this doc gets fixed.

## The two token layers (this distinction bites)

| Layer | Scope | Where defined | Use for |
|---|---|---|---|
| **Page tokens** | `.fl-restyle` container (each opted-in page wraps its content) | `fl-restyle.css` top, dark at `.fl-restyle`, light at `[data-theme="light"] .fl-restyle` | everything inside a page's `<main>` |
| **Chrome tokens** `--flc-*` | `:root` — reach **body-mounted** elements | `fl-restyle.css` "Chrome" section (~line 719) | sidebar, tour engine, launcher, modals appended to `<body>`, anything outside `.fl-restyle` |

A body-mounted element (tour card, launcher, flyout, scanner overlay) **cannot
see** `.fl-restyle`-scoped tokens. Style it with `--flc-*` (plus fallback
literals). This is why the tour engine and launcher use `var(--flc-accent, …)`.

### Core palette (dark / light)

| Token | Dark | Light | Meaning |
|---|---|---|---|
| `--accent-primary` / `--flc-accent` | `#C29E9B` | `#85605E` | the mauve-blush accent; solid CTAs, active states |
| `--accent-primary-l` / `--flc-accent-l` | `#E3CBC7` | `#C29E9B` | lighter accent for text-on-dark, active labels |
| `--accent-primary-dim` / `--flc-accent-dim` | blush @ 12% | blush @ 8–10% | tint fills (hover, active nav, tint buttons) |
| `--accent-border` / `--flc-accent-border` | blush @ 45% | blush @ 40% | borders on tint buttons/chips |
| `--on-accent` / `--flc-on-accent` | `#17222E` | `#FFFFFF` | text on solid accent |
| `--fl-green` / `--flc-green` | `#01B574` | `#1E8E63` | success / ready / complete |
| `--fl-amber` | `#FFB547` | `#C07220` | warning / due-soon / pending |
| `--fl-red` (+`-deep`) / `--flc-red` | `#FF6B6B` | `#C43D45` | error / overdue / danger |
| `--fl-purple` | `#A492D6` | `#7458B8` | installed / special states |
| `--green-dim` `--amber-dim` `--red-dim` `--purple-dim` | color @ 12% | color @ 10% | status tint fills — always pair with the solid color as text+border |
| `--info` / `--info-2` / `--flc-info` | `#0075FF` / `#2CD9FF` | blue both | info blue, **small doses only** (column dots, info icons; light theme collapses info-2 → info for contrast) |
| `--card-bg` / `--flc-card` | `#151821` | `#FFFFFF` | card surface |
| `--card-edge` / `--flc-card-edge` | white @ 10% | white @ 90% | the "lit top edge" — set as `border-top-color` on cards |
| `--bg` / `--text` (`--flc-text`) / `--text-muted` (`--flc-text-muted`) / `--border` | `#0B0D12` / `#EDF0F6` / `#97A3B6` / slate @ 13% | light equivalents | base surfaces and text |

**The status recipe** (used everywhere — badges, chips, banners, statuses):
`color: var(--fl-X); background: var(--X-dim); border: 1px solid var(--fl-X);`

### Body zoom (the geometry gotcha)

`body` carries `zoom: 1.15` on desktop (reset to 1 under 767px). Fixed-position
elements that are children of the zoomed body lay out in zoomed px while
`getBoundingClientRect()` returns real viewport px — **divide by the computed
body zoom at style-write time** (`fl-restyle.js` `_zoom()` pattern; the tour
engine and nav flyout both do this). Same reason `100vh` inside a panel is 15%
too tall — see the tour launcher's `calc(100vh / 1.15 - 64px)`.

## Component archetypes (canonical class names)

Grab the existing archetype before inventing a new one. Representative markup
lives in the named templates.

| Archetype | Classes | Notes / where to copy from |
|---|---|---|
| **Hero strip** | `.fl-hero` (fl pages) · `.db-hero`/`.db-hero-cell` (dashboard) | gradient card (`--hero-grad`) with glow pseudo-elements; dashboard hero is a 3-cell grid. `fulfillment.html`, `dashboard.html` |
| **Card** | `.fl-card` (+`.fl-ocard` order cards, `.oem-card`) | `--card-bg`, 1px `--border`, **lit top edge** via `border-top-color: var(--card-edge)`, radius 10–12, hover raises with `--card-shadow-hover` |
| **Chips** | `.fl-ochip` (primary id chip) · `.fl-mchip` (muted meta chip) | inline facts on cards: PO number, order number, qty `x/y`. `fulfillment.html` |
| **Status badge** | `.fl-badge` + `.ok`/`.warn`/`.urg` | the status recipe; SHORT/OVER receiving badges reuse this language (`rcv-badge--full`/`--over`) |
| **Buttons** | `.fl-btn` (solid accent) · `.fl-obtn` (tint; `+.ready` green, `+.danger` red) | solid = `--accent-primary` bg + `--on-accent` text; tint = `--accent-primary-dim` bg + `--accent-border` border |
| **Tables** | `.data-table` + fl overrides (`.fl-restyle .table-override-*`) | dark surface rows, `--border` separators; overrides restyle legacy tables without rewriting them |
| **Filter tiles** | `.fl-filter-tiles` (fl) · `.inv-tiles`/`.inv-tile` (inventory) | small clickable tiles with a static category hue; act as filters, not just stats |
| **Banner** | `.fl-banner` + `.warn`/`.urg` | page-level notices (maintenance staleness, backup health) — status recipe at banner scale |
| **Composition bar** | `.fl-comp-bar` (fl) · `.db-comp-bar` (dashboard) | segmented clickable proportion bar + legend; segments filter on click (see also the map's `#mp-deal-bars` chart-as-filter) |
| **Tour card / launcher** | `.tour-tooltip`, `.tour-ring`, `.tour-dim` · `.tour-launcher`, `.tlr-*` | body-mounted → `--flc-*` tokens only; blush solid Next, tint Back, quiet Skip, blush dots, 2px blush ring + glow |
| **Pipeline pills** | `.pfb-*` (pipeline filter bar), `#bld-tabs`/`.bld-tabs` | click-to-filter stage rollups; active pill gets accent tint |
| **Stage dots** | `.fl-stage`, `.fl-sdot`/`.fl-sline` (+`.done`/`.half`) | five-dot build tracker on device-linked cards |
| **Nav chrome** | `.sx-nav__*` (link, section, badge, toggle) | styled via `--flc-*`; active link = blush tint + 2px left bar; flyout `.fl-nav-flyout` is JS-built |
| **Scanner overlay** | `.scanner-*` (frame, toast, trail, torch, flash) | theme-independent (fixed dark rgba) by design — it covers the camera feed |
| **Toast** | `SxToast` (`static/js/toast.js`, loaded on every page from `base.html`) | body-mounted, fixed top-right, z 100000. `SxToast.success/error/warning/info(msg, duration)`; duration 0 is sticky, default 6000ms for error and 4000 otherwise. Styled inline on `--flc-card`, `--flc-text`, `--flc-text-muted`, with the status colour on border and icon via `--flc-green`/`--flc-red`/`--flc-amber`/`--flc-info`. The same file owns the global error-capture pipeline (window error, unhandledrejection, HTMX handlers, rate-limited beacon to `/api/errors/report`), so touching toast.js touches that too. A page reached by redirect can carry a toast in the `toast` and `toast_type` query parameters, rendered by a handler in `base.html` and specified in `docs/specs/toast-redirect-kind.md` |
| **Dialog** | `SxDialog` (`static/js/dialog.js`, loaded on every page from `base.html`, the line after toast.js) | body-mounted, centred, z 90000: above every page modal and the legacy coming-soon toast, below SxToast. `SxDialog.confirm({title, message, okLabel, cancelLabel, danger})` resolves `true` or `false`; `SxDialog.prompt({title, message, label, value, placeholder, required, okLabel, danger})` resolves the entered string (as typed) or `null`; `SxDialog.reveal({title, message, value, okLabel, copyLabel})` is a readout rather than a question: it shows `value` in a selectable monospace block with a Copy button and no Cancel, and resolves `true` however it is dismissed. confirm and prompt accept a plain string as the message. Esc, Cancel and the backdrop cancel; Enter confirms unless Cancel or Copy has focus; focus returns to the opener; a call made while one is open waits its turn. Styled inline on `--flc-card`, `--flc-card-edge`, `--flc-text`, `--flc-text-muted`, with the OK button on `--flc-accent` and `--flc-on-accent` (`--flc-red` when `danger`). Replaces native `confirm` and `prompt`; the confirm and prompt conversions are `docs/specs/native-dialogs-track-2-dialogs.md`, and the credential readout is Track 4 in `docs/specs/native-dialogs-track-1-alerts.md` |

## Rules that keep it coherent

1. **Both themes, always.** Every new component gets dark AND light values. If
   it's body-mounted, add the `[data-theme="light"]` override on `--flc-*` use
   sites (see launcher CSS).
2. **Status colors mean status.** Green/amber/red/purple are semantic — don't
   use them decoratively. The accent (blush) carries "interactive/active";
   info blue stays in small doses.
3. **Tint + border together.** A `-dim` background without its solid-color text
   and border reads as dirt, not status.
4. **New page? Opt in.** Wrap the page content in `.fl-restyle`, reuse
   archetypes above; only mint a new token when no existing one fits, and add
   it to BOTH theme blocks (and to this doc).
5. **Cache-busting:** both stylesheets are versioned automatically via
   `request.state.js_v()` in `base.html`. Edit the CSS, restart the app;
   nothing to bump.
6. **Comment density:** style rules carry a one-line "why" only when the value
   is load-bearing (zoom math, contrast collapses, scope reasons) — match this.
