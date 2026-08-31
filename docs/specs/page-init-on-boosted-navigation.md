# Boosted navigation and page JavaScript

Filename note: this file is `page-init-on-boosted-navigation.md`. Its scope
widened past page init. The name is kept because other documents point at it;
a dangling pointer costs more than a narrow filename.

Status: partly built. `5e4cfb5` shipped the PageInit helper, inert. `a599eee`
opted eleven nav links out of boost. This document has been corrected three
times by reads, twice for scope and once for the wrong defect boundary. It
should be stable now, because the scope is enumerated by a TEST rather than by a
list somebody has to keep reading.

Owner note: WHAT and WHY only. The HOW is the `asset-tracker-workflow` skill.
Repo facts live in `CLAUDE.md`.

## The rule

**A page whose JavaScript renders outside `<main>` cannot be boosted.**

Everything below is that sentence and its consequences.

## Why

One element in the app is boosted. `base.html:94`:

    <nav class="sx-nav" id="sx-nav" hx-boost="true" hx-target="main"
         hx-select="main" hx-swap="innerHTML">

`hx-boost="true"` appears exactly once in the codebase. Links inside `<main>`
inherit nothing from the nav, so every in-page link is a normal full-page
navigation.

`hx-select="main"` is the operative attribute. A boosted navigation fetches the
whole rendered page and then keeps ONLY `<main>`, which spans `base.html:473` to
`495`. Everything the template rendered outside that is discarded and never
inserted. A template can render outside main in two places:

    {% block head %}      base.html:87
    {% block scripts %}   base.html:837

Two defects follow.

## Defect B: JavaScript outside main never arrives

The page renders completely and is inert. No error, no missing content, no
symptom other than things not working.

**This has two halves, and only recognising one of them is how it stayed hidden.**

- **The scripts half.** 24 templates put page JS in `{% block scripts %}`; 11 of
  them are sidenav destinations. Observed on `admin_errors`: root present, 9 rows
  rendered, filter select present, `filterErrors` undefined.
- **The head half.** Templates loading an external asset in `{% block head %}`.
  `fulfillment.html:464-465` loads `scanner.css` and `scanner.js` there.
  Observed: boosting from `/inventory/` to `/fulfillment/` leaves
  `BarcodeScanner` undefined and the scan workflow dead.

Also observed, and worth keeping: a tab carries exactly ONE page's script payload
for its whole life, whichever page was hard-loaded, because a full load replaces
the document. No accumulation. And within a document the payload leaks across
pages: `filterErrors` stays defined while the user sits on `/fulfillment/`.

**Already fixed once, as a special case.** `base.html:168-171` opts `/map/` out
with the comment "MapLibre loads outside `<main>`; a boosted swap of only
`<main>` would leave the map uninitialized - a dead page." That is the rule
above, stated once and never generalised. Map hit it through the head half.

### The fix

Opt every violating link out of boost, following the map precedent. Twelve as of
this track: the eleven in `a599eee` plus `/fulfillment/`.

    a599eee   dashboard  search  admin_audit  admin_errors  admin_intune
              admin_notifications  admin_oui  admin_maintenance
              admin_spreadsheet_sync  admin_part_numbers  admin_zendesk
    this      fulfillment

That list is a snapshot. **The tripwire is the live enumeration**; do not
maintain the list here.

### Why not move the JS inside main

Considered and rejected. Recording it so it is not relitigated from scratch.

Moving page scripts into the swap region would let those pages keep boosted
navigation, and the greppable hazard is small: ten of eleven scripts-block
templates carry zero top-level `let`/`const`, and `search.html`'s seven at 53-59
are a smaller change than `3f3c0f7` already made once.

The deciding argument is not audit cost. It is that **these scripts have never
re-executed**, so "no top-level declarations" proves one hazard absent and says
nothing about how eleven pages behave running twice against a fresh DOM. That
property is not greppable.

Set against that: boosting a violating page currently costs the FULL network
payload and delivers a broken page, because the server renders everything and
htmx discards all but main. Boost is strictly worse than no boost for them today.
Opting out is a strict improvement. Moving the JS is a further improvement bought
with unexercised re-execution.

### The tripwire

A test that fails when someone boosts a page whose JS lives outside `<main>`.

- One case per boosted sidenav href. Assert the page contributes no `<script>`
  outside `<main>` beyond `base.html`'s own set. **Both blocks**, head and
  scripts: a test covering only scripts would pass the map case reintroduced.
- Plus one structural case: **`hx-boost="true"` appears exactly once in
  `base.html`.** Every conclusion in this document turns on that. If a second
  element is ever boosted, all of it needs rechecking, and this fails at that
  moment.

Modelled on the endpoint auth census, which parametrises per route. Failure
locality should name the page; which block it was belongs in the assertion
message, not the case count.

The test is self-adjusting: remove an `hx-boost="false"` and that href re-enters
the enumerated set, so the count changes AND the new case fails.

Implementation preference, not a requirement: render each boosted page through
the test client and compare its set of scripts outside `<main>` against a clean
baseline page's set. That needs no href-to-template mapping to maintain and tests
what actually ships. `/inventory/` is a verified-clean baseline: zero external
asset tags. Fall back to parsing template source with an explicit map if
authenticating ten renders is more friction than it is worth.

## Defect A: page init does not re-run

A page whose script IS inside main arrives with the swap and re-executes, but its
`DOMContentLoaded` registration never fires again, because that event belongs to
the document and the document was never replaced.

**Scope: one template. `triage.html:632`.**

Nine `DOMContentLoaded` registrations exist across eight templates. Six of those
templates are not sidenav destinations, so they always full-load and their init
always fires. `admin_errors` and `fulfillment` are sidenav destinations but both
belong to defect B and are opted out, so their init fires normally too.

### The fix

`PageInit`, shipped inert in `5e4cfb5`.

    PageInit.init(name, fn)   called by the page, after its root
    PageInit.ready()          called once by base.html, after _lockManager

`init()` finds the root carrying `data-page-init="<name>"` and does nothing if it
is missing or already marked. It marks the root, then runs `fn` immediately if
`ready()` has fired or queues it if not. `ready()` flushes and sets the flag.
`init()` logs a console error naming the page when the root is missing and
returns; not a throw, because a throw inside swapped content can abort the
remaining scripts in that fragment.

**Placement.** The root's opening tag must appear before the script in document
order. Inside the root is sufficient but NOT required: a script after the root's
closing tag still finds it, because the root and its children are parsed by then.

**Queueing is the ordering guarantee.** On a full load a script inside main runs
before `base.html:747`, so `_lockManager` does not exist yet. On a boosted swap
it was never destroyed.

**No htmx event is used.** With no partial swaps anywhere in the app, a page's
own inline script executes exactly once per entry and is a better trigger than an
event whose semantics would need re-verifying per htmx version. That swapped
scripts re-execute is established: `fulfillment.html:3229` comments "var, not let
or const: hx-boost re-executes this block on a boosted return", and `3f3c0f7`
fixed that redeclaration.

**One caller is the honest count.** The helper is not machinery looking for work:
it is what any page needs the moment someone wants it boosted, and the tripwire
is what will send them here. If the scanner follow-up below lands, fulfillment
returns to boost and becomes the second caller.

**Before migrating `triage.html`**, check it for top-level `let`, `const` and
`class`. Its script already re-executes today, so any such declaration is a live
bug rather than a new risk.

## Verification

Gate order is the skill's, plus the browser checks.

**A gate row must name an observable whose value DIFFERS between the working and
the broken system.** Filtering on a value every row shares produces the same
count either way, so it cannot discriminate. State the input and the expected
delta, not just the behaviour. This bit once already, on defect B's filter check.

1. pytest baseline immediately before editing. The opt-out and migration commits
   add no routes and no tests, so predict no movement. The tripwire commit adds
   one case per boosted href plus the structural one; state the number first.
2. jinja parse on every changed template
3. JS check: node is not on apphost, so the browser console after a fresh reload
   is the real check
4. restart app, confirm worker up
5. Browser gates below
6. `git diff` review, then commit, then four location sync

**Defect B gate.**

| Check | Expected |
|---|---|
| Each opted-out page, reached from the sidenav | Full load. Page JS present and working |
| `admin_errors`: filter on a value ABSENT from the data | 9 rows to 0, then back to 9 on reset. Filtering on a value every row shares cannot tell a working filter from a dead one |
| `fulfillment` reached from the sidenav | `typeof BarcodeScanner` is `"function"`, `scanner.js` present in the document |
| The remaining boosted pages | Still boosted, still working. No regression |
| Locking and live updates on one opted-out page | Still work. Full loading rebuilds `_lockManager` and any SSE connection |
| Browser Back into an opted-out page | Works. htmx history restore replays a main-only swap, a third entry path into the same discard |
| `openErrorDetail` | Undefined, and NOT a regression: it was undefined on a direct load before the fix too. Recorded because it reads as one in console output |

**Defect A gate**, for `triage.html`:

| Check | Expected |
|---|---|
| Direct load by URL | Init runs. TO BE NAMED: read `triage.html:632`'s handler and state the observable it produces |
| Sidenav away and back | Same observable present |
| Browser Back into the page | Same observable present |
| Console on all paths | Clean. No redeclaration error, and no `PageInit` error, which would mean the root was not found |

The first row is deliberately unfinished. Do not write it from the outside; read
the handler first, or the gate checks nothing.

## Commit plan

`5e4cfb5` shipped the helper. `a599eee` opted out eleven. Then:

1. **Opt `/fulfillment/` out**, plus this document. Closes the head half of
   defect B.
2. **The tripwire.** Lands right behind the fix it guards.
3. **Migrate `triage.html`.** Closes defect A.

## Follow up tracks this creates

- **Make `scanner.js` re-execution safe, then move the asset tags inside main.**
  That is what would return boosted navigation to `/fulfillment/`, and it fixes
  `receive.html` and `provisioning_detail.html` at the same time, both of which
  load it in their head blocks and are safe today only because they are not
  sidenav-reachable.

  `scanner.js:18` declares `class BarcodeScanner` at top level, unwrapped, and
  `:615` assigns it to `window`. A top-level `class` is lexically scoped like
  `let`, so re-execution throws "Identifier already declared" while appearing to
  work, since `window.BarcodeScanner` survives from the first run. An IIFE with an
  early return on `window.BarcodeScanner` fixes that.

  **It does not fix load ordering, and that is the open question.** A `<script
  src>` inserted dynamically does not block the way a parse-time one does, so an
  inline script in the same swapped fragment may run before the external file
  finishes. `fulfillment.html:3127` does `new BarcodeScanner(BP)`. Unverified
  against htmx 2.0.4. Answer that before relying on it; if the answer is bad,
  fulfillment's init has to become async, which is a real change to a 3,400-line
  page. This is a track, not a two-line edit.

- **htmx is loaded from unpkg.com at runtime.** `base.html:83`, no integrity
  attribute, no vendored copy in `static/js/`. Lose egress and hx-boost stops
  working. Blast radius is small, since htmx does nothing here but the nav boost,
  and the degraded state is full page loads, which would incidentally mask both
  defects above. One vendored file plus one line.

- **`search.html` carries seven top-level `const` and `let` at 53-59.** Harmless
  while that script never re-executes. It becomes a live bug the moment anyone
  boosts that page or moves its scripts inside main.
