# Hygiene slice: dead CSS, reduced motion, pfb banner

Three small items closing out the Fulfillment section before propagation. Suggested as three commits (each independently verifiable), one sync each or one sync at the end of all three if done in a single sitting — your call at the boundary.

## 1. Dead legacy CSS removal

Candidates flagged at Part A/B ship time: old `oc-*`, `cb-stat`, `c2c-pill` and related rules orphaned by the restyle.

Discipline: for EACH candidate class, grep all templates AND all JS (classList operations, string-built selectors, tour target selectors in guide.js) before deleting its rules. A class referenced only from JS is alive. Keep a removal list in the commit message. Exact-count anchors on the deletions. No visual diff expected anywhere — verify fulfillment, OEM, C2C, dashboard render unchanged after.

Suggested commit: `Remove dead legacy css orphaned by the fulfillment restyle`

## 2. prefers-reduced-motion guard (shared, benefits all future pages)

Add to fl-restyle.css:

```css
@media (prefers-reduced-motion: reduce) {
    .fl-restyle .fl-bg-blob { animation: none; }
    .fl-restyle .fl-hero::before,
    .fl-restyle .fl-hero::after { animation: none; opacity: 0 !important; }
    .fl-restyle [class*="pulse"], .fl-restyle .s-dot.cur { animation: none; }
    .fl-restyle .fl-bg-spot { display: none; }
}
```

Adjust selectors to the real class names in the file (discovery first — the pulse/current-step class name may differ from the mock). Static elements (hairline, grid, gradients) stay — they are not motion. Resting hairline must remain visible when the lap is disabled. Also guard the spotlight JS: skip binding when `window.matchMedia('(prefers-reduced-motion: reduce)').matches` (cheaper than writing styles that CSS then hides).

Verify with Chrome DevTools emulation (Rendering -> prefers-reduced-motion) on fulfillment: no drift, no lap, no pulse, hairlines still present, page fully usable.

Suggested commit: `Add prefers reduced motion guard to fl restyle animations`

## 3. pfb banner (the cyan "OEM PIPELINE" pill)

Live finding: `span.pfb-title` in `.pfb-header` renders with legacy cyan border (#2CD9FF) floating over the OEM column band. The `.pfb-*` family is shared across boards.

Approach — do NOT edit the legacy `.pfb-*` rules (other boards still depend on them). Instead add scoped overrides in fl-restyle.css under `.fl-restyle .pfb-*`: only opted-in pages change, non-opted boards keep the legacy look, and each future page opt-in brings the banner along automatically. This respects the shared-class gotcha while still being a cross-board pattern.

Treatment: quiet — `--card-bg` pill, 1px `var(--border)`, muted tracked uppercase text, no cyan, no glow. If the banner has interactive behavior (pin/unpin, click), preserve it and restyle states with the tint pattern.

Discovery first: grep `pfb-` across templates/JS to inventory every board and behavior it carries; verify each opted-in surface after (fulfillment in-house, OEM, C2C) plus one non-opted board to confirm it is unchanged.

Suggested commit: `Restyle pfb banner under fl restyle scope`

## Gates

Per commit: jinja parse (where templates change) -> restart -> Chrome smoke both themes on fulfillment/OEM/C2C -> non-opted page unchanged (dashboard or inventory) -> console clean -> diff review -> commit.
