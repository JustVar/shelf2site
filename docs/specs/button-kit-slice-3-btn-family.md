# Button kit, slice 3: retire the .btn family

    STATUS:   DRAFT, rev 1, 2026-09-21, written by Chat before any build.
              Slices 1 and 2 of the button track (B1 on the board) shipped
              at 3036972 and 3ffe7c2 with no spec of their own; this is the
              first spec in the track. Nothing below has been built.
    Board:    BACKLOG-TRIAGE.md item B1, slice 3. Open read 2 (the census)
              closes with this document.
    Taken at: HEAD 3ffe7c2, branch main. Every anchor below was read with
              grep -n on copies proven against the commit's blob ids. They
              age from the first commit that touches the file; the build
              re-reads each one before editing.
    Related:  DESIGN_SYSTEM.md:62 (the Buttons row). fl-restyle.css:221-242
              and :297-302 (the kit rules). Slice 2's commit message at
              3ffe7c2 records the inv-btn and itk-submit retirement this
              slice follows.

## What is wrong

Three button vocabularies still coexist. The fl kit (`fl-cta`, `fl-obtn`,
`fl-btn`) is the standard since the restyle and the one the design system
names. The legacy `.btn` family (`btn`, `btn-sm`, `btn-primary`,
`btn-success`, `btn-danger`, `btn-secondary`, `btn-warning`, `btn-submit`)
is still on 157 class attributes across 18 templates and the tour engine,
carried by two competing base definitions (`main.css:1126`, and
`receive.css:80` which wins on `/receive` by load order) plus a third layer
of kit-coloured overrides in `fl-restyle.css` (`:582-587`, `:621-631`,
`:657`) that exist only to make the legacy classes look like the kit.
Slice 2 retired `inv-btn` and `itk-submit`; this slice retires the rest, so
that one set of rules describes every button and the kit's anchor and
disabled rules (`fl-restyle.css:300-302`) apply everywhere.

## Decisions (Jus, 2026-09-21)

1. **Mapping.** `btn` and `btn-secondary` become `fl-obtn`. `btn-success`
   becomes `fl-obtn ready`. `btn-danger` becomes `fl-obtn danger`.
   `btn-warning` (one site) becomes plain `fl-obtn`; no amber variant is
   added for one button. `btn-primary` becomes `fl-cta`, reading a modal
   as its own view for the design system's one-per-view rule. A
   `btn-primary` inside a table row is never a CTA: it becomes `fl-obtn`
   (three sites, marked in the census).
2. **`btn-sm` is dropped with no replacement.** The kit has no small
   variant; slice 2 measured row buttons at 32px in 56px rows and accepted
   it. Inline `font-size` and `padding` overrides on family sites go with
   it, as slice 2 did. Inline danger colours (`color: var(--danger)`,
   `#FF4444`, danger border-color) become the `danger` modifier. Inline
   `text-decoration: none` on anchors goes; `fl-restyle.css:301` covers it.
   Inline `opacity` on a disabled button goes; `:302` covers it.
3. **Rule retirement is last.** The global family rules in `main.css` and
   the overrides in `fl-restyle.css` are deleted in 3f, after every site
   has moved and after the tour engine no longer needs `.btn`. Page-scoped
   rules (`receive.css`, the two `mobile.css` receive lines, the inline
   rule at `provisioning_detail.html:149`) go with their page's sub-slice.
   Every intermediate commit leaves the app consistent.
4. **Six sub-slices, one spec, six commits.** 3a admin pages and the
   review queue (31 sites). 3b vendors, sites and warranty (44). 3c the
   provisioning pair (26). 3d order detail and the deploy wizard (33).
   3e receive (18, plus its own stylesheet). 3f the tour engine and the
   rule deletion (5, plus CSS). Order is not load-bearing except that 3f
   is last.
5. **The standalone `btn-*` classes are out of scope.** `btn-edit`,
   `btn-label`, `btn-page`, `btn-cancel`, `btn-assign`, `btn-ship`,
   `btn-login`, `btn-change`, `btn-ocr-fill`, `btn-view-mobile`,
   `btn-creds`, `btn-history` each have their own rules and do not sit on
   the `.btn` base. They stay.

## Rules the build follows

- **R1, tokens.** Replace the family tokens in the class attribute per
  decision 1 and keep every other token (ids, `tour-btn-*`, page classes)
  in place. Order: kit class first, modifier second, other tokens after.
- **R2, row buttons.** `sites.html:115`, `admin_part_numbers.html:121`,
  `admin_oui.html:132` are per-row Edit buttons carrying `btn-primary`.
  They become `fl-obtn`, not `fl-cta`. The build reads five lines of
  context on each before editing to confirm the `<tr>`.
- **R3, more than one CTA on a page.** After mapping, these pages carry
  more than one `fl-cta` outside a modal: `admin_maintenance` (:101, :139),
  `admin_notifications` (:78, :113), `admin_spreadsheet_sync` (:19, :49;
  two stages of one flow), `warranty` (:63, :190; one per section),
  `receive` (:68, :252, :262; different stages), `provisioning` (:115 and
  the bulk bar at :1453). The spec converts them as mapped and records
  them here; demoting any to `fl-obtn` is a per-page design call for the
  gate, made in the browser with the page in front of Jus, not by the
  patch.
- **R4, anchors.** `<a class="btn ...">` sites (`warranty.html:65, :66`,
  `provisioning.html:111`, `provisioning_detail.html:537, :739`,
  `order_detail.html:323`) take the same mapping. `fl-restyle.css:301`
  removes the underline; the gate reads `text-decoration-line` on one.
- **R5, disabled.** Sites with a static `disabled` attribute
  (`admin_maintenance.html:141`, `receive.html:284`,
  `provisioning.html:1382`) and the buttons JS disables (`receive.html`
  submit, `admin-spreadsheet-sync.js:151`, `admin-maintenance.js:158`)
  get the kit rule at `:302` for free once they carry a kit class. The
  gate reads `opacity` (.45) and `pointer-events` (none) on one static
  and one JS-driven site per sub-slice where either exists.
- **R6, the `btn-submit` hook.** `receive.html:252` is the only
  `btn-submit` site and `receive.html:1129, :1232, :1490` select it by
  class. The class goes; the button gains `id="submit-device-btn"` and the
  three selectors become `getElementById`. New id: assert it free in the
  repo first. `receive.css:126` (`.btn-submit`) and `mobile.css:261`
  (`.receive-page .btn-submit`) then have no subject; `:261` becomes
  `.receive-page #submit-device-btn` if the 52px mobile height is to
  stay, else it is deleted. The gate at 596px decides: read the computed
  `min-height` before and after. Built at 3e: `:126` became
  `.receive-page #submit-device-btn { width: 100%; margin-top: 0.5rem; }`
  (layout kept, padding and size to the kit; Jus 2026-09-21) and `:261`
  kept its 52px on the id, read at 596px before and after.
- **R7, elements outside the wrapper.** The kit rules are all scoped
  under `.fl-restyle`. Every slice 3 page carries the wrapper (READ, one
  per page, `base.html:445` is only the mobile offer bar). Two elements
  in `provisioning.html` sit outside it at runtime: the assign modal is
  built as a string and appended to `document.body` (`:1354-1386`), and
  `#bulk-action-bar` (`:1448`) sits in `{% block scripts %}`, rendered by
  `base.html:891` outside `<main>`. Both gain `fl-restyle` on their root
  (`#assign-order-modal` at `:1355`, `#bulk-action-bar` at `:1448`).
  Every other string-built site is inserted into an element inside the
  wrapper (`#avail-tbody`, `#zendesk-details`, `#event-status`,
  `#scan-result`, `#ocr-results`; targets READ). The gate proves R7 by
  reading a computed `border-radius` on a kit button inside the modal
  and inside the bar: 8px from the kit, 6px from `.btn`, unset otherwise.
- **R8, the tour engine.** `guide.js` builds its buttons with
  `btn btn-sm [btn-primary] tour-btn-*` (`:388`, `:586-590`) and mounts
  the tooltip on `document.body` (`:380`, `:562`), outside every wrapper,
  so kit classes would style nothing there. The tooltip already has its
  own per-button rules (`main.css:2132-2166`) layered over `.btn`. 3f
  drops the family tokens from the five strings, gives `#tour-wait-skip`
  the `tour-btn-skip` class, and adds one rule in `main.css` next to
  `:2132` carrying the base properties the buttons lose:
  `.tour-tooltip .tour-nav button, .tour-tooltip #tour-wait-skip {
  padding: 8px 12px; min-height: 36px; font-size: 0.8rem; font-family:
  inherit; font-weight: 500; cursor: pointer; display: inline-flex;
  align-items: center; justify-content: center; transition: all 0.2s; }`.
  The tooltip does not gain `fl-restyle`; that would swap its palette
  variables (`fl-restyle.css:29-45`) and is a different change.
  Re-read `.tour-nav` (`:2125`) and the button markup at build time to
  confirm the selector reaches all four buttons.
- **R9, tours.** `tours.py:245` (`review_queue_tour`, `/review`) targets
  `.btn-success`; it becomes `.fl-obtn.ready` in 3a. `tours.py:372`
  (`sites_tour`) targets `.btn-primary`; it becomes `.fl-cta` in 3b.
  `tours.py:438` (`trials_tour`, `/trials`) and `:700` (`disposal_tour`,
  `/disposal`) target pages with no route (READ, rc=1 on both strings in
  `app/routes` and `app/main.py`); both disabled at 893af71, targets
  left as they are until the pages ship. Gate: open the tour on `/review` and
  `/sites` and reach the retargeted step.
- **R10, CSS deletions in 3f.** `main.css:1126-1149` (the base and the
  four variants, `btn-sm` included) deleted whole. `fl-restyle.css:582-584`
  keep their `.rcpt-btn` and `.btn-page` selectors and lose the
  `.fl-restyle .btn` member (and its light-theme and hover twins);
  `:585-586`, `:621-631`, `:657` deleted. The comment at `main.css:2131`
  is rewritten to stop citing `.btn`. Before deleting, the habit 30
  census reruns on the expected tree and must return zero family class
  sites outside `docs/`.
- **R11, page-scoped CSS.** 3c deletes `provisioning_detail.html:149`
  (`.prov-detail-actions .btn`) after reading what it sets and moving
  anything still wanted onto a kit class. 3e edits `receive.css` (`:80-130`
  base and variants, `:166`, `:314`, `:391`) and `mobile.css:199` (the
  44px block names `.receive-page .btn`; it becomes `.receive-page
  .fl-obtn, .receive-page .fl-cta` in the same shape the checkout and
  checkin entries already use) and `:261` per R6.
- **R12, docs.** 3f adds one line to the `DESIGN_SYSTEM.md:62` Buttons
  row stating the `.btn` family is retired, and may carry the rider for
  board read 13 (the kit disabled and anchor rules) if Jus wants it.

## Census at 3ffe7c2

157 class attributes carry the bare `btn` token: 152 in templates, 5 in
`guide.js`. Tokens inside them: `btn` 157, `btn-sm` 81, `btn-primary` 40,
`btn-success` 12, `btn-danger` 12, `btn-secondary` 8, `btn-warning` 1,
`btn-submit` 1. Method: every file under `app`, `static/css`, `static/js`,
`docs`, `tests` at 3ffe7c2, proven by blob id; class attributes split on
whitespace and matched as whole tokens; the bare-token grep run
repo-wide per habit 30 and every non-class hit accounted for (JS
identifiers named `btn`, one inline CSS rule, tour targets, one test
asserting an id, one Tailwind mockup under `docs/`).

Non-template sites that must follow, all READ:

- CSS definitions: `main.css:1126-1149`; `receive.css:80-130, :166, :314,
  :391`; `fl-restyle.css:582-587, :621-631, :657`; `mobile.css:199, :261`;
  `provisioning_detail.html:149`.
- JS selectors on a family class: `receive.html:1129, :1232, :1490` only.
- Tour targets: `tours.py:245, :372` live; `:438, :700` disabled tours.
- Tests: none (`test_order_cancel.py` asserts `id="cancel-order-btn"`).

Site tables. `today` is the class attribute as it reads at 3ffe7c2, `after`
is what the patch writes, other tokens on the same attribute are kept.

### 3a

| file:line | today | after | note |
|---|---|---|---|
| `admin_intune.html:22` | `btn` | `fl-obtn` |  |
| `admin_intune.html:23` | `btn btn-primary` | `fl-cta` |  |
| `admin_intune.html:116` | `btn btn-sm` | `fl-obtn` |  |
| `admin_maintenance.html:71` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `admin_maintenance.html:98` | `btn btn-sm` | `fl-obtn danger` | drop inline danger colour |
| `admin_maintenance.html:101` | `btn btn-sm btn-primary` | `fl-cta` |  |
| `admin_maintenance.html:139` | `btn btn-primary` | `fl-cta` |  |
| `admin_maintenance.html:141` | `btn` | `fl-obtn` | has disabled attr; drop inline `opacity: 0.5` (kit rule :302 dims) |
| `admin_maintenance.html:155` | `btn` | `fl-obtn` |  |
| `admin_notifications.html:78` | `btn btn-primary` | `fl-cta` |  |
| `admin_notifications.html:82` | `btn` | `fl-obtn` |  |
| `admin_notifications.html:113` | `btn btn-primary` | `fl-cta` |  |
| `admin_oui.html:57` | `btn btn-success` | `fl-obtn ready` |  |
| `admin_oui.html:132` | `btn btn-primary btn-sm` | `fl-obtn` | row button, not a CTA |
| `admin_oui.html:136` | `btn btn-danger btn-sm` | `fl-obtn danger` |  |
| `admin_oui.html:175` | `btn` | `fl-obtn` |  |
| `admin_oui.html:176` | `btn btn-success` | `fl-obtn ready` |  |
| `admin_part_numbers.html:62` | `btn btn-success` | `fl-obtn ready` |  |
| `admin_part_numbers.html:121` | `btn btn-primary btn-sm` | `fl-obtn` | row button, not a CTA |
| `admin_part_numbers.html:125` | `btn btn-danger btn-sm` | `fl-obtn danger` |  |
| `admin_part_numbers.html:180` | `btn` | `fl-obtn` |  |
| `admin_part_numbers.html:181` | `btn btn-success` | `fl-obtn ready` |  |
| `admin_spreadsheet_sync.html:19` | `btn btn-primary` | `fl-cta` |  |
| `admin_spreadsheet_sync.html:49` | `btn btn-primary` | `fl-cta` |  |
| `admin_spreadsheet_sync.html:52` | `btn btn-secondary` | `fl-obtn` |  |
| `admin_zendesk.html:41` | `btn btn-primary` | `fl-cta` |  |
| `admin_zendesk.html:55` | `btn btn-sm` | `fl-obtn` |  |
| `admin_zendesk.html:66` | `btn btn-sm` | `fl-obtn` |  |
| `admin_zendesk.html:77` | `btn btn-sm` | `fl-obtn` |  |
| `support.html:103` | `btn btn-success btn-sm` | `fl-obtn ready` |  |
| `support.html:105` | `btn btn-danger btn-sm` | `fl-obtn danger` |  |

### 3b

| file:line | today | after | note |
|---|---|---|---|
| `site_detail.html:54` | `btn btn-sm` | `fl-obtn` |  |
| `site_detail.html:94` | `btn btn-primary btn-sm` | `fl-cta` |  |
| `site_detail.html:95` | `btn btn-sm` | `fl-obtn` |  |
| `site_detail.html:162` | `btn btn-sm` | `fl-obtn` |  |
| `site_detail.html:164` | `btn btn-danger btn-sm` | `fl-obtn danger` |  |
| `site_detail.html:223` | `btn` | `fl-obtn` |  |
| `site_detail.html:224` | `btn btn-success` | `fl-obtn ready` |  |
| `site_detail.html:294` | `btn` | `fl-obtn` |  |
| `site_detail.html:295` | `btn btn-success` | `fl-obtn ready` |  |
| `sites.html:47` | `btn btn-primary btn-sm` | `fl-cta` |  |
| `sites.html:115` | `btn btn-primary btn-sm` | `fl-obtn` | row button, not a CTA |
| `sites.html:116` | `btn btn-danger btn-sm` | `fl-obtn danger` |  |
| `sites.html:196` | `btn` | `fl-obtn` |  |
| `sites.html:197` | `btn btn-success` | `fl-obtn ready` |  |
| `vendor_detail_profile.html:98` | `btn btn-sm` | `fl-obtn` |  |
| `vendor_detail_profile.html:347` | `btn` | `fl-obtn` |  |
| `vendor_detail_profile.html:348` | `btn btn-primary` | `fl-cta` |  |
| `vendors.html:14` | `btn btn-primary` | `fl-cta` |  |
| `vendors.html:17` | `btn` | `fl-obtn` |  |
| `vendors.html:96` | `btn btn-sm` | `fl-obtn` |  |
| `vendors.html:99` | `btn btn-sm` | `fl-obtn danger` | drop inline danger colour |
| `vendors.html:115` | `btn btn-primary` | `fl-cta` |  |
| `vendors.html:191` | `btn` | `fl-obtn` |  |
| `vendors.html:192` | `btn btn-primary` | `fl-cta` |  |
| `vendors.html:246` | `btn` | `fl-obtn` |  |
| `vendors.html:247` | `btn btn-primary` | `fl-cta` |  |
| `warranty.html:63` | `btn btn-primary btn-sm` | `fl-cta` |  |
| `warranty.html:65` | `btn btn-sm` | `fl-obtn` | anchor |
| `warranty.html:66` | `btn btn-sm` | `fl-obtn` | anchor |
| `warranty.html:125` | `btn btn-sm` | `fl-obtn` |  |
| `warranty.html:126` | `btn btn-sm` | `fl-obtn` |  |
| `warranty.html:128` | `btn btn-sm` | `fl-obtn danger` | drop inline danger colour |
| `warranty.html:173` | `btn btn-sm` | `fl-obtn` |  |
| `warranty.html:190` | `btn btn-primary btn-sm` | `fl-cta` |  |
| `warranty.html:232` | `btn btn-sm` | `fl-obtn` |  |
| `warranty.html:234` | `btn btn-sm` | `fl-obtn danger` | drop inline danger colour |
| `warranty.html:375` | `btn btn-secondary` | `fl-obtn` |  |
| `warranty.html:376` | `btn btn-primary` | `fl-cta` |  |
| `warranty.html:408` | `btn btn-secondary` | `fl-obtn` |  |
| `warranty.html:409` | `btn btn-primary` | `fl-cta` |  |
| `warranty.html:468` | `btn btn-secondary` | `fl-obtn` |  |
| `warranty.html:469` | `btn btn-primary` | `fl-cta` |  |
| `warranty.html:587` | `btn btn-secondary` | `fl-obtn` |  |
| `warranty.html:588` | `btn btn-primary` | `fl-cta` |  |

### 3c

| file:line | today | after | note |
|---|---|---|---|
| `provisioning.html:89` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `provisioning.html:111` | `btn` | `fl-obtn` | drop inline size override; anchor |
| `provisioning.html:115` | `btn btn-primary` | `fl-cta` |  |
| `provisioning.html:271` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `provisioning.html:274` | `btn btn-success btn-sm` | `fl-obtn ready` |  |
| `provisioning.html:275` | `btn btn-warning btn-sm` | `fl-obtn` |  |
| `provisioning.html:276` | `btn btn-danger btn-sm` | `fl-obtn danger` |  |
| `provisioning.html:630` | `btn` | `fl-obtn` | drop inline size override |
| `provisioning.html:653` | `btn` | `fl-obtn` |  |
| `provisioning.html:654` | `btn btn-success` | `fl-obtn ready` |  |
| `provisioning.html:725` | `btn` | `fl-obtn` |  |
| `provisioning.html:726` | `btn btn-success` | `fl-obtn ready` |  |
| `provisioning.html:1381` | `btn btn-sm` | `fl-obtn danger` | drop inline danger colour; body-mounted modal, R7 |
| `provisioning.html:1382` | `btn btn-primary btn-sm` | `fl-cta` | body-mounted modal, R7; has disabled attr |
| `provisioning.html:1453` | `btn btn-primary btn-sm` | `fl-cta` | `#bulk-action-bar` sits outside the wrapper, R7 |
| `provisioning.html:1454` | `btn btn-sm` | `fl-obtn` | `#bulk-action-bar`, R7 |
| `provisioning_detail.html:411` | `btn btn-sm` | `fl-obtn` |  |
| `provisioning_detail.html:503` | `btn btn-primary btn-sm` | `fl-cta` |  |
| `provisioning_detail.html:504` | `btn btn-sm` | `fl-obtn` |  |
| `provisioning_detail.html:537` | `btn btn-sm` | `fl-obtn` | anchor; drop inline `text-decoration` (kit rule :301) |
| `provisioning_detail.html:555` | `btn btn-success` | `fl-obtn ready` |  |
| `provisioning_detail.html:561` | `btn` | `fl-obtn` | drop inline background and border |
| `provisioning_detail.html:581` | `btn btn-sm` | `fl-obtn` |  |
| `provisioning_detail.html:582` | `btn btn-sm btn-danger` | `fl-obtn danger` |  |
| `provisioning_detail.html:586` | `btn btn-sm` | `fl-obtn` |  |
| `provisioning_detail.html:739` | `btn btn-sm` | `fl-obtn` | anchor; drop inline `text-decoration`; inserted into `#zendesk-details`, inside the wrapper |

### 3d

| file:line | today | after | note |
|---|---|---|---|
| `fulfillment.html:1748` | `btn` | `fl-obtn` |  |
| `fulfillment.html:1749` | `btn` | `fl-obtn` |  |
| `fulfillment.html:1750` | `btn btn-primary` | `fl-cta` |  |
| `order_detail.html:38` | `btn btn-sm` | `fl-obtn` |  |
| `order_detail.html:39` | `btn btn-sm` | `fl-obtn` |  |
| `order_detail.html:40` | `btn btn-sm btn-danger` | `fl-obtn danger` |  |
| `order_detail.html:41` | `btn btn-sm btn-danger` | `fl-obtn danger` |  |
| `order_detail.html:108` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `order_detail.html:110` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `order_detail.html:138` | `btn btn-sm` | `fl-obtn` |  |
| `order_detail.html:139` | `btn btn-sm` | `fl-obtn` |  |
| `order_detail.html:183` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `order_detail.html:184` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `order_detail.html:201` | `btn btn-sm btn-primary` | `fl-cta` | its style is on `:202`, drop the size override there, keep `margin-left:auto` |
| `order_detail.html:246` | `btn btn-sm` | `fl-obtn` | its style is on `:252`, drop the size override |
| `order_detail.html:253` | `btn btn-sm` | `fl-obtn danger` | its style is on `:254`: size override and inline danger colour, both dropped |
| `order_detail.html:303` | `btn btn-sm` | `fl-obtn` | its style is on `:304`, drop the size override, keep `color:var(--text-muted)` (design call, Jus 2026-09-21) |
| `order_detail.html:323` | `btn btn-sm` | `fl-obtn` | anchor; its style is on `:324`, drop the size override there, keep `margin-left:auto` |
| `order_detail.html:358` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `order_detail.html:372` | `btn btn-sm` | `fl-obtn` | drop inline size override |
| `order_detail.html:419` | `btn btn-sm` | `fl-obtn` |  |
| `order_detail.html:515` | `btn` | `fl-obtn` |  |
| `order_detail.html:516` | `btn btn-primary` | `fl-cta` |  |
| `order_detail.html:542` | `btn` | `fl-obtn` |  |
| `order_detail.html:543` | `btn btn-danger` | `fl-obtn danger` |  |
| `order_detail.html:570` | `btn` | `fl-obtn` |  |
| `order_detail.html:571` | `btn btn-primary` | `fl-cta` |  |
| `order_detail.html:635` | `btn` | `fl-obtn` |  |
| `order_detail.html:636` | `btn btn-primary` | `fl-cta` |  |
| `order_detail.html:654` | `btn` | `fl-obtn` |  |
| `order_detail.html:655` | `btn btn-primary` | `fl-cta` |  |
| `order_detail.html:903` | `btn btn-sm` | `fl-obtn` | drop inline size override; inserted into `#avail-tbody`, inside the wrapper |
| `order_detail.html:904` | `btn btn-sm` | `fl-obtn` | drop inline size override; inserted into `#avail-tbody`, inside the wrapper |

### 3e

| file:line | today | after | note |
|---|---|---|---|
| `receive.html:68` | `btn btn-primary` | `fl-cta` |  |
| `receive.html:80` | `btn` | `fl-obtn` |  |
| `receive.html:111` | `btn` | `fl-obtn` |  |
| `receive.html:252` | `btn btn-primary btn-submit` | `fl-cta, id="submit-device-btn"` | JS hook moves to the id |
| `receive.html:262` | `btn btn-primary` | `fl-cta` |  |
| `receive.html:263` | `btn` | `fl-obtn` |  |
| `receive.html:264` | `btn` | `fl-obtn` |  |
| `receive.html:283` | `btn btn-secondary` | `fl-obtn` |  |
| `receive.html:284` | `btn btn-primary` | `fl-cta` | has disabled attr |
| `receive.html:295` | `btn btn-secondary` | `fl-obtn` |  |
| `receive.html:296` | `btn btn-danger` | `fl-obtn danger` |  |
| `receive.html:311` | `btn btn-secondary` | `fl-obtn` |  |
| `receive.html:312` | `btn btn-danger` | `fl-obtn danger` |  |
| `receive.html:378` | `btn btn-sm` | `fl-obtn` | drop inline size override; inserted into `#event-status`, inside the wrapper |
| `receive.html:380` | `btn btn-sm` | `fl-obtn` | drop inline size override on :381; inserted into `#event-status`, inside the wrapper |
| `receive.html:738` | `btn btn-sm` | `fl-obtn` | inserted into `#scan-result`, inside the wrapper |
| `receive.html:739` | `btn btn-sm` | `fl-obtn` | inserted into `#scan-result`, inside the wrapper |
| `receive.html:1062` | `btn btn-sm` | `fl-obtn` | inserted into `#ocr-results`, inside the wrapper |

### 3f

| file:line | today | after | note |
|---|---|---|---|
| `guide.js:388` | `btn btn-sm` | `tour-btn-skip` | gains the skip class; keeps `id="tour-wait-skip"` |
| `guide.js:586` | `btn btn-sm tour-btn-back` | `tour-btn-back` | base props move into main.css, R8 |
| `guide.js:588` | `btn btn-sm btn-primary tour-btn-next` | `tour-btn-next` | R8 |
| `guide.js:589` | `btn btn-sm btn-primary tour-btn-next` | `tour-btn-next` | R8 |
| `guide.js:590` | `btn btn-sm tour-btn-skip` | `tour-btn-skip` | R8 |

## Gates, per sub-slice

Same shape as slice 2, plus the observables named in R4 to R9.

1. Jinja parse of every touched template, local and in the container.
2. Chrome on every touched page, logged in as an editor: render, no
   console error after a fresh reload, one computed-style read per page
   on a converted button (`border-radius` 8px for `fl-obtn`, 10px for
   `fl-cta`; `.btn` gave 6px), and the disabled read from R5 where the
   page has one.
3. Habit 30 census on the page: whole-token family count 0 for the
   page's template after the patch (`\bbtn\b` over-matches `-btn` and
   `btn-edit`), and the bare-token grep showing only JS identifiers.
4. Adjacent-board regression: one page from the previous sub-slice
   re-rendered.
5. 3a and 3b: the retargeted tour step reached (R9).
6. 3c: the R7 reads inside the assign modal and the bulk bar.
7. 3e: `/receive` at 596px through the iframe route (`resize_window` is
   unreliable, board SURFACE FACTS); computed `min-height` on the submit
   button and one row button before and after; the three
   `getElementById` sites exercised by a scan-and-submit on a mock serial
   if the data allows, reversed afterwards.
8. 3f: open a tour on `/dashboard` and step through Back, Next, Skip;
   computed padding and min-height on the Next button before and after
   (36px both times is the pass).
9. Suite: 919 passed / 39 skipped predicted for every sub-slice; no route
   is added.
10. Diff review, commit, four-location sync, four HEADs read
    independently.

## Sizing

Templates: 18 files, 152 attributes, plus roughly 30 inline style edits
and the two `fl-restyle` additions in `provisioning.html`. Python: one
file, two lines. JS: `guide.js` five strings; `receive.html` three
selectors. CSS: `main.css` 24 lines deleted and one rule added;
`fl-restyle.css` 15 lines deleted or trimmed; `receive.css` about 40 lines
deleted; `mobile.css` two lines edited; one inline rule deleted. Docs: one
line. Six commits.

## Observations recorded on the board, not fixed here

- `trials_tour` and `disposal_tour` in `tours.py` (`:406`, `:668`) were
  enabled and target `/trials` and `/disposal` (no route); disabled at 893af71.
- `#bulk-action-bar` and the assign modal in `provisioning.html` render
  outside the page's `.fl-restyle` wrapper today, so any kit class already
  used inside them is unstyled. R7 fixes the two roots; the pattern may
  exist on other pages with body-mounted markup (UNREAD).
- The `fl-obtn` in a `<td>` renders at 32px in a 56px row; `btn-sm` gave
  36px. Accepted in slice 2; recorded again because slice 3 adds about
  80 such sites.

## Out of scope, left as it was

The standalone `btn-*` classes (decision 5). `fl-btn` on `fulfillment.html`
and `c2c.html` (board B1 note). `tours.py:2335`. The tour tooltip's
palette. `docs/mockups/` and `docs/specs/*.html` mock files.
