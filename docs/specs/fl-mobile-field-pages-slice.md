# Slice: mobile field pages

Decision (Jus, 2026-07-09): mobile support is scoped to FIELD PAGES ONLY — Receive & Scan, Checkout, Checkin, Global Search, Item Detail. Everything else stays desktop-first and unverified on mobile. Rationale: the only real mobile workflows are warehouse/field ones (camera barcode scanning, quick check-in/out, item lookup); dashboards and boards are desktop-dense by design.

## Work items

1. Fix the hamburger (global chrome, small): `toggleMobileSidebar` targets the long-gone `#nav-sidebar` — repoint to the current nav so mobile nav opens/closes on all pages. This is a bug fix, not a mobile redesign; the drawer reuses the existing nav DOM.
2. Field-page responsive pass (the real work), per page at ~390px width:
   - Single-column stacking of section cards; full-width inputs and buttons.
   - Touch targets minimum 44px; primary action sticky at the bottom of the viewport on forms (Check Out / Check In / the receive actions).
   - Inputs at >=16px font-size on mobile widths (prevents iOS focus zoom).
   - Receive & Scan: camera scan is the hero on mobile — Start Camera prominent, Quick Mode reachable, manual serial entry below.
   - Search: input full-width; results table collapses to stacked row-cards (name, serial, status chip, chevron to item) below a breakpoint — reuse the fl-table CSS with a mobile modifier rather than a second markup path if possible.
   - Item Detail: view mode stacks; edit mode inputs full-width. Keep the presence banner readable.
3. Discovery item: the global `body { zoom: 1.15 }` — check how it behaves at mobile widths (it predates this work); likely needs a media query reset below the mobile breakpoint. Verify against the nav-height compensation and the flyout math from the collapse slice (both divide by computed zoom, so a reset must keep them consistent).
4. MOBILE ROUTING (approved 2026-07-09, replaces the banner idea): when a phone is detected, non-field routes redirect to a MOBILE LAUNCHER page.
   - Launcher: a simple field-action menu — big touch buttons (56px+) for Scan / Receive, Check Out, Check In, Search, each with its duotone icon; user footer with name + logout; fl language, both themes. Phone logins land here.
   - Launcher design approved via mock 2026-07-10 with one directive: the header uses the ACTUAL Company logo asset (reuse static/img/logo-brand-full.png from the login slice, sized for mobile ~48-64px mark), never text. Scan / Receive is the hero button (blush tint, top slot); the other three are quiet cards with colored duotone icons and one-line descriptions; "View Desktop Version" escape link at the bottom.
   - Detection: server-side User-Agent check (phone classes) deciding the redirect, backed by a client viewport check (<768px) that offers the launcher on pages UA sniffing missed. Tablets (>=768px) are treated as desktop.
   - ESCAPE HATCH: the launcher (and any redirect) carries a "View desktop version" link — sets a session flag that disables the redirect until logout. This is UX routing, NOT security; the map kiosk role remains the only access-enforcement mechanism and is unaffected by the desktop-view flag.
   - Field pages and their data endpoints are never redirected. Deep links to field pages work directly.
5. The collapse slice's known item closes here: mobile drawer behavior supersedes the auto-collapse rail below the phone breakpoint (rail hidden, hamburger + drawer instead). Keep the <1200px tablet auto-collapse as is.

## Verification

Chrome device emulation (or window resize) at ~390x844: the five field pages exercised end-to-end — hamburger open/close, receive scan UI renders (camera permission flow at least reaches the prompt), checkout/checkin form submit reachable with sticky action, search -> stacked results -> item detail round trip — BOTH themes. Desktop layouts pixel-unchanged at >=1200px (the responsive work must live entirely behind media queries). Consoles clean. Standard gates + four-location sync.

Suggested commits:
- `Fix mobile sidebar toggle targeting removed element`
- `Add mobile layouts for field pages`
