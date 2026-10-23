# Tours overhaul: shading, targeting, launcher

Reproduced live 2026-07-09 (dashboard tour, Chat browser session). Three defect classes plus a restyle.

## Observed defects

1. SHADING: the overlay's spotlight cutout renders as a stray bright strip near the top-left even on steps with NO target (visible on step 1, persists across steps at the same wrong position). The strip's offset and squashed size are consistent with rect math that ignores `body { zoom: 1.15 }` — the same coordinate trap the nav flyout fixed by dividing by computed zoom. Overall page dim is also weak/uneven.
2. TARGETING: step copy references specific UI that never gets spotlighted — dashboard step 2 says "the hero strip at the top" while the card stays centered and nothing highlights. Prior census note agrees: the dashboard tour has ZERO element targets (all centered steps). Either targets were never wired or were lost; both cases read as broken to the user. Separately, tours.py carries a stale ghost key referencing the nonexistent users.html (flagged in the tail census).
3. LAUNCHER MODAL: the Tours button opens a near-full-height flat list of every tour, header clipped offscreen at the top, internal scroll, legacy blue Start/Retake buttons, Close pinned at the bottom. Inefficient to scan and off-language.

## The work

### A. Overlay/engine rebuild (guide.js)
- Zoom-corrected geometry: every measured rect divides by the computed body zoom (reuse the flyout's exact pattern); re-measure on resize, scroll, and htmx:load; scroll the target into view BEFORE measuring; smooth transition of the cutout between steps.
- Proper dim: four-panel overlay or single SVG mask around the target rect — charcoal at a real opacity (e.g. rgba(11,13,18,0.65)), consistent edge-to-edge, no stray artifacts on targetless steps (no cutout rendered at all when a step has no target).
- Card placement: adjacent to the target with collision-aware flipping (above/below/side), centered only for genuinely untargeted steps.
- Target contract: a step's selector is validated at step time; if missing (element not on page, permission-hidden, collapsed nav variant), the step FALLS BACK to centered with its cutout suppressed — never a mispositioned zone. Log the miss to console.debug for maintenance.

### B. Full per-tour audit — every tour, step by step (targets AND content)
- Inventory every tour and step; wire real selectors for steps whose copy references specific UI (dashboard: hero strip, composition bar, type panels, activity, quick actions). Copy and target must agree — if no stable anchor exists, rewrite the copy to be genuinely general.
- POST-RESTYLE CONTENT PASS: walk every tour against the restyled app and rewrite copy that describes the old UI (legacy button names/colors, removed elements like the metric underlines and left card bars, moved controls, renamed pages). Every claim in every step must be true of the CURRENT interface. Check pacing while there: steps that say nothing get cut; steps covering two things get split only if genuinely needed.
- COVERAGE MATRIX: list every page/feature vs tour existence. Known gaps to expect: the redesigned map (deal filters, curation, modes), the collapsed-nav flyout, C2C certification, the coming mobile launcher. Deliver the matrix + drafted step outlines for missing tours back to Chat — WRITING new tours is approved in principle, but their copy gets a quick Chat review before shipping (content Jus may want a voice in).
- Remove the stale users.html ghost key. Verify every remaining selector against the live DOM per page (collapsed AND expanded nav where relevant).
- Tours are contract-protected: keep tour keys/completion storage stable so Completed states survive. New tours get new keys; never reuse a retired key.

### C. Restyle (fl language)
- Tour card: fl card surface (lit top edge, radius 12), blush solid Next (the one solid), tint Back/Skip, blush progress dots, muted step counter, Title Case headings.
- Overlay dim uses the charcoal token family; target ring: 2px blush outline + soft glow around the cutout.
- Both themes.

### D. Launcher redesign
- Replace the flat modal with a compact fl panel: grouped by section (Getting Started / Admin / per-page), each row = tour name + steps count + status (green check = completed, muted = not started) + tint Start/Retake; proper header INSIDE the viewport; max-height with grouped scroll; Close as tint.
- Add "Tour This Page" as the first row when the current page has a tour — the common case should be one click.
- Optional cheap win if storage allows: "Reset All Tours" tucked at the bottom as a muted link.

## Contracts
Completion tracking keys, auto-start-on-first-visit behavior (e.g. vendors), tour trigger points, the nav tour anchor from the collapse slice, kiosk role (tours must not fire for kiosk sessions on the map — verify).

## Suggested slicing
1. Engine + restyle (A + C) — one commit, gated on the dashboard + one anchored tour.
2. Per-tour audit + rewrites + ghost-key cleanup (B) — one commit per coherent group if large; coverage matrix + new-tour outlines delivered to Chat at this point.
3. Launcher redesign (D) — one commit.
4. New tours (post Chat copy review) — final commit(s).

## Gates
Run EVERY tour end-to-end on its own page: cutout lands on the named element (zoom 1.15 verified), targetless steps show no cutout, card never covers its target, dim uniform, copy true of the current UI, both themes, collapsed + expanded nav variants for nav-anchored steps, launcher opens fully on-screen, consoles clean.
