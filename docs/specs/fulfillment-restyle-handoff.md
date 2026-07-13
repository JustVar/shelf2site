# Fulfillment Restyle — Code Handoff

Date: 2026-07-08. Design phase complete and approved in Chat. This doc + `fulfillment-restyle-mock-v1.html` + CLAUDE.md are the build inputs. Repo `/opt/asset_tracker` on apphost, app at `http://192.0.2.10:8100/assettracker/`. Base HEAD at design time: `6ad6483`.

## Scope

Pilot: the Fulfillment page (`/assettracker/fulfillment/`) only. Lock the new design language there, verify in browser, ship. Propagation to Orders, Provisioning, Inventory, and Dashboard are follow-up slices reusing the same tokens/classes — do NOT touch those pages in this slice.

The approved mock (`fulfillment-restyle-mock-v1.html`) is the visual source of truth. Open it in a browser; it has a working light/dark toggle, hover states, hotkeys, and the animated background.

## Design summary

Neutral charcoal dark theme with a mauve-blush identity accent. Gradient + glow are reserved for hero metric tiles only; everything else is flat and quiet. One loud button per page. Duotone two-layer SVG icons colored by CSS variable. Animated page background (dot grid + aurora drift + cursor spotlight). Full light-mode equivalent.

## Token block (locked)

Scope under a page-level class (suggested `fl-page` or reuse `.fulfillment-page` scoping used in the mock). All new CSS classes get a `fl-` prefix. NEVER edit shared classes (`.pfb-*`, `.kanban-grid`, `.k-col`, `.bld-*`) — add new ones.

```css
.fulfillment-page {
    /* surfaces */
    --bg: #0B0D12;
    --bg-header: #08090D;
    --sidebar-bg: #0F1218;
    --card-bg: #151821;
    --card-bg-hover: #202636;
    --card-shadow-hover: 0 6px 18px rgba(0,0,0,0.40);
    --card-edge: rgba(255,255,255,0.10);
    --hero-grad: linear-gradient(127deg, #1C2130 0%, #0F121A 100%);
    --border: rgba(148,163,184,0.13);
    --border-hover: rgba(148,163,184,0.45);
    /* text */
    --text: #EDF0F6;
    --text-muted: #97A3B6;
    /* accent (mauve blush) */
    --accent-primary: #C29E9B;
    --accent-primary-l: #E3CBC7;
    --accent-primary-dim: rgba(194,158,155,0.12);
    --accent-border: rgba(194,158,155,0.45);
    --on-accent: #17222E;
    /* info (Vision UI blue, small doses only) */
    --info: #0075FF;
    --info-2: #2CD9FF;
    /* status */
    --fl-green: #01B574;
    --fl-amber: #FFB547;
    --fl-red: #FF6B6B;
    --fl-red-deep: #E31A1A;
    --fl-purple: #A492D6;
    --green-dim: rgba(1,181,116,0.12);
    --amber-dim: rgba(255,181,71,0.12);
    --red-dim: rgba(255,107,107,0.12);
    /* animated background */
    --grid-dot: rgba(148,163,184,0.10);
    --aurora-1: rgba(194,158,155,0.10);
    --aurora-2: rgba(70,105,143,0.13);
    --spot: rgba(194,158,155,0.07);
}
[data-theme="light"] .fulfillment-page {
    --bg: #F5F6F8;
    --bg-header: #FFFFFF;
    --sidebar-bg: #ECEEF2;
    --card-bg: #FFFFFF;
    --card-bg-hover: #F0F3F8;
    --card-shadow-hover: 0 6px 18px rgba(27,32,40,0.12);
    --card-edge: rgba(255,255,255,0.9);
    --hero-grad: linear-gradient(127deg, #FFFFFF 0%, #EEF0F5 100%);
    --border: #E2E5EB;
    --border-hover: #C6CCD6;
    --text: #1B2028;
    --text-muted: #5C6675;
    --accent-primary: #85605E;
    --accent-primary-l: #C29E9B;
    --accent-primary-dim: rgba(133,96,94,0.08);
    --accent-border: rgba(133,96,94,0.40);
    --on-accent: #FFFFFF;
    --fl-green: #1E8E63;
    --fl-amber: #C07220;
    --fl-red: #C43D45;
    --fl-red-deep: #A82C33;
    --fl-purple: #7458B8;
    --green-dim: rgba(30,142,99,0.10);
    --amber-dim: rgba(192,114,32,0.10);
    --red-dim: rgba(196,61,69,0.10);
    --grid-dot: rgba(27,32,40,0.13);
    --aurora-1: rgba(133,96,94,0.20);
    --aurora-2: rgba(70,105,143,0.18);
    --spot: rgba(133,96,94,0.11);
}
```

## Component rules

### 1. Animated page background
Fixed full-viewport layer, `z-index: 0`, `pointer-events: none`, behind everything; page content wrappers get `position: relative; z-index: 1`. Three sublayers: dot grid (`radial-gradient(var(--grid-dot) 1px, transparent 1px)` at 24px), two blurred aurora blobs (blush top-left 16s loop, slate-blue bottom-right 20s loop, `filter: blur(60px)`, CSS-only), and a cursor spotlight (`radial-gradient(320px circle at var(--mx) var(--my), var(--spot), transparent 70%)`) driven by one document-level `mousemove` listener. Exact CSS/JS in the mock.

### 2. Hero metric tiles — the ONLY glowing elements
Applies to the top metric strip (Active / Overdue / Due Soon / Stock) and nothing else. `background: var(--hero-grad)`, resting hairline glow along the top edge in the tile status color, and on hover the hairline fades while a lit segment laps the tile perimeter (conic-gradient + `@property --a` animation — full CSS in the mock; Chrome/Edge/Safari 16.4+/Firefox 128+, older browsers degrade to a static line). Layout: label 12px muted, value 30px/700, sub-line 12px in status color, 38px duotone icon top-right. The current colored bottom-underline treatment on the live metric strip is REMOVED.

### 3. Body cards — everything that is not a hero tile
Flat `var(--card-bg)`, 1px `var(--border)`, top border `var(--card-edge)` (the lit-edge echo), radius 12px. NO gradients, NO glow, NO left color bars (the current left accent bars on order cards are removed). Hover: `background: var(--card-bg-hover)`, `border-color: var(--border-hover)`, `translateY(-2px)`, `box-shadow: var(--card-shadow-hover)`.

### 4. Order card anatomy (top to bottom)
- Row 1: customer name as title, 16px/600, left; one status badge top-right (tint style: status color text + `--*-dim` bg + status border). At most ONE colored badge per card.
- Row 2: ID chip (blush, mono, e.g. AT-9001) left; due/checklist text right-aligned, muted with small muted duotone icon.
- Stage tracker: 16px dots. Done = green fill + check; current = blush fill + 2s pulse; future = `var(--border)`. Connector lines match (done green, done-to-current gradient green-to-blush, future border color).
- Footer (separated by 1px border): owner bottom-left = muted duotone person icon + FIRST NAME ONLY, name wrapped in its own `<span>` inside `.o-owner` (the engineer filter depends on that span — spec constraint). Action button bottom-right.
- No UUID display on cards. No avatar/initials circles anywhere on cards.

### 5. Buttons
- Exactly one solid CTA per page: header "New Order" — `background: var(--accent-primary)`, `color: var(--on-accent)`, blush shadow on hover.
- All other action buttons are tints: `--accent-primary-dim` bg + `--accent-border` border + `--accent-primary-l` text (light mode: `--accent-primary` text); hover fills to `--accent-border`.
- Ready/advance actions (e.g. Move to Delivery): same tint pattern in green (`--green-dim` / `--fl-green`).
- The existing bright blue "+ New Order" and any gradient buttons are replaced. Blue (`--info`) survives only as small informational marks (column dots, info icons).

### 6. Duotone icon system
Jinja macro, inline SVG, e.g. `{{ icon('box', 'green') }}` -> 24px viewBox, two layers: base silhouette `class="b"` at `opacity: .28`, accent stroke/detail `class="s"` at full opacity, both filled/stroked with `var(--duo-c)`. Color classes: `st-c-green`, `st-c-amber`, `st-c-red`, `st-c-blush`, `st-c-info`, `st-c-mute` (each sets `--duo-c`). Starter set (16): box, truck, clock, alert, clipboard-check, plus, check, x, search, filter, users, arrow-right, fingerprint, chart, activity, settings. Paths for several are in the mock; keep stroke-width ~1.7, round caps/joins.
- New macro file = new top-level names; assert names free before adding (per CLAUDE.md gotcha).

### 7. Search box
Hover: border shifts to `--accent-border`. Focus (`:focus-within`): border `--accent-primary`, ring `0 0 0 3px var(--accent-primary-dim)` + soft blush outer glow, keycap chip highlights. `/` keycap shown in the box. Hotkeys: `/` focuses (preventDefault), Esc blurs. Skip hotkey handling when target is INPUT/TEXTAREA. The Dashboard already has `/` — mirror the pattern, do not duplicate global listeners.

### 8. Quick actions (rail pattern, also used on Dashboard later)
Body-card rows with duotone icon + label + mono keycap. Hover: card hover treatment + keycap lifts 1px and tints blush. Hotkey press: row flashes (`--accent-primary-dim` bg + accent border + keycap scale 1.15, ~450ms). Rows carry `data-key="n|o|i|t"`; one delegated keydown listener.

### 9. Text rules
Short status/label texts in Title Case: "Needs Triage", "2 Reserved", "+4 This Week", "Due in 2 Days", "4 Days Late", "Checklist Attached", "All Systems Operational". Column headers uppercase tracked (QUEUED, IN PROGRESS).

## Mapping mock -> live Fulfillment page

| Live element (seen 2026-07-08) | Treatment |
|---|---|
| Metric strip (Active/Overdue/Due Soon/Stock) with colored underlines | Hero tiles: gradient + hairline glow + hover lap; underlines removed; 38px duotone icons |
| Search box + Coverage button in metric card | Search animation + `/` hotkey; Coverage becomes tint button |
| In-House / OEM segmented toggle, Scan, Export | Body-card/tint styling, no color |
| + New Order (bright blue) | The single solid blush CTA |
| Order Pipeline tabs (Queued / In Progress / Ready for Handoff) | Keep structure; restyle as quiet tabs, active tab accent underline in blush |
| Order cards: left color bar, Unspecified chip, customer title, assignee line, AT-#### + SALE/PO / PILOT chips, N intended, avatar circle top-right | New card anatomy (section 4): bars and avatar removed, customer title 16px, ID chip row 2, one badge top-right, first-name owner bottom-left |
| Deployment Pipeline tabs + Schedule Deployment | Same tab + tint-button treatment |
| Recently Completed cards: date chips, certified lines, VERIFIED/SIGN-OFF/DOCS/CLOSED dots | Body cards; stage dots use tracker treatment (green done, blush current) |

## Build discipline (inherit, non-negotiable)

- Follow CLAUDE.md and the asset-tracker-workflow skill: read-only discovery first; guarded Python patch scripts (exact-count anchors, idempotency guard, post-check) written to apphost /tmp via SSH heredoc; re-read anchors immediately before editing; .bak deleted before commit; show git diff before committing.
- Page-level JS uses `var` (hx-boost re-executes scripts); all init hooks idempotent and re-run on `htmx:load`.
- Jinja onclick args: `|tojson|forceescape`.
- SSH heredoc mangles backslash escapes and em dashes — embed real glyphs or build with chr().
- Verification gates per change: jinja parse -> browser console JS check (node is not on apphost) -> restart app -> Chrome MCP smoke (render, interaction incl. hover lap + hotkeys + light/dark toggle, console clean, no regression to adjacent boards) -> git diff review -> commit -> four-location sync (at-sync-commit.sh on apphost, wsync on workstation; done only when all four HEADs match).
- Commit messages: plain imperative, no apostrophes, no em dashes, no AI attribution.
- 192.0.2.174 is defunct; the app is 192.0.2.10:8100.

## Suggested slice order

1. Tokens + animated background + page scoping (visual base, no behavior change).
2. Icon macro file + starter set.
3. Hero metric strip (underlines out, hairline/lap in).
4. Order cards restyle (anatomy, buttons, tracker).
5. Tabs, header controls, search + quick-action hotkeys/animations.
6. Light mode pass + full browser verification, both themes.

Each slice: verify + commit + four-location sync before the next.
