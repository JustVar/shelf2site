# Boosted navigation and page JavaScript

Filename note: this file is `page-init-on-boosted-navigation.md`. The scope has
since widened past page init. The name is kept because other documents point at
it; a dangling pointer costs more than a slightly narrow filename.

Status: partly built. `5e4cfb5` shipped the PageInit helper, inert, with nothing
adopting it yet. This document has been corrected twice by reads: once because
it under-scoped the defect, once because it over-scoped it.

Owner note: WHAT and WHY only. The HOW is the `asset-tracker-workflow` skill.
Repo facts live in `CLAUDE.md`.

## Why

One element in the app is boosted. `base.html:94`:

    <nav class="sx-nav" id="sx-nav" hx-boost="true" hx-target="main"
         hx-select="main" hx-swap="innerHTML">

`hx-boost="true"` appears exactly once in the codebase. Three descendants opt
out: `/map/` at 171, `/change-password` at 395, the logout form at 399. Links
inside `<main>` inherit nothing from the nav, so every in-page link is a normal
full-page navigation.

`hx-select="main"` is the operative attribute. A boosted navigation fetches the
whole rendered page and then keeps ONLY `<main>`. Everything the template
rendered outside main is discarded from the response and never inserted.
`<main>` spans `base.html:473` to `495`. `{% block head %}` renders at 87 and
`{% block scripts %}` at 837, both outside it.

Two distinct defects follow from that one fact.

### Defect A: page init does not re-run

A page whose script IS inside main arrives with the swap and re-executes, but
its `DOMContentLoaded` registration never fires again, because that event
belongs to the document and the document was never replaced. Init never runs on
a boosted return.

**Scope: two templates.** `triage.html:632` and `fulfillment.html:3402`.

Nine `DOMContentLoaded` registrations exist across eight templates, but six of
those templates are not sidenav destinations. They are reached by in-page links,
which are not boosted, so they always full-load and their init always fires.
`admin_errors.html` is a sidenav destination but belongs to defect B: its script
never arrives at all.

Symptom on fulfillment, which is where this was first seen: returning to the
board through the sidenav leaves no active deployment tab, every card
unfiltered, and the mini-step trackers empty.

### Defect B: page scripts never arrive

A page whose script is in `{% block scripts %}` renders it at 837, outside main.
On a boosted entry that content is discarded. The page renders completely and is
entirely inert.

**Scope: eleven sidenav destinations.**

    dashboard.html            admin_audit.html          admin_intune.html
    search.html               admin_errors.html         admin_notifications.html
    admin_oui.html            admin_maintenance.html    admin_spreadsheet_sync.html
    admin_part_numbers.html   admin_zendesk.html

24 templates use `{% block scripts %}`; the other 13 are reached only by in-page
links, always full-load, and always work.

**This defect has been found before and fixed once.** `base.html:168-171`:

    hx-boost="false" because MapLibre loads outside <main>; a boosted swap
    of only <main> would leave the map uninitialized - a dead page.

That is the general rule stated as a special case. Map hit it through
`{% block head %}`; these eleven hit it through `{% block scripts %}`. Same rule:
**a page whose JS renders outside `<main>` cannot be boosted.**

## What the reads established

| Question | Answer |
|---|---|
| What is boosted | The nav at `base.html:94`, and nothing else. Three opt-outs already exist |
| What a boosted nav keeps | Only `<main>`, per `hx-select="main"`. Everything else in the response is discarded |
| Boosted sidenav destinations | 21, after the two opt-outs |
| Of those, how many use `{% block scripts %}` | 11 |
| Defect A's real scope | 2 templates. The other six with `DOMContentLoaded` are not boosted destinations |
| Does an inert page look broken | NO. Observed on `admin_errors`: root present, 9 rows rendered, filter select present, `filterErrors` undefined, `openErrorDetail` undefined |
| Do stale scripts accumulate | NO. Observed: a full load replaces the document, so a tab carries exactly ONE page's script payload for its whole life, whichever page was hard-loaded. Hard-loading `/admin/errors` then `/search` leaves `filterErrors` undefined |
| Does the leak cross pages | YES, within one document. Observed: `filterErrors` stays defined while the user sits on `/fulfillment/` |
| Top-level `let`/`const` in the 11 | 10 of 11 have zero. `search.html` has 7 at lines 53-59, genuinely top-level. Zero `class` declarations anywhere in the 11 |

The inert-page row is why this survived unnoticed: a page that renders correctly
and whose filter silently does nothing gets blamed on the user.

## Defect B: the fix

**Opt the eleven links out of boost**, following the map precedent. One attribute
per link in `base.html`. No template restructuring.

### Why this and not moving the scripts inside main

Three alternatives were considered and rejected. Recording them so the decision
is not relitigated from scratch:

- **Move `{% block scripts %}` inside `<main>`.** Fixes everything at once, but
  the block currently renders after `_lockManager` at 747 and would then render
  before it, and all 24 templates would begin re-executing simultaneously.
- **Pull the block out of band** with an additional htmx select. Preserves
  ordering, but depends on `hx-select-oob` semantics nobody here has verified.
- **A new block inside main, migrated template by template.** Stageable, and the
  best of the three, but still ends with eleven pages re-executing.

**The deciding argument is not audit cost.** That was the first argument and it
did not survive measurement: the greppable hazard is one template and seven
declarations, a smaller change than `3f3c0f7` already made once.

The deciding argument is that these scripts have NEVER re-executed. Zero
top-level declarations proves one hazard absent. It does not show that eleven
pages behave correctly when their scripts run a second time against a fresh DOM,
and that property is not greppable. `search.html`'s seven are
`document.getElementById` results captured at parse time, which is a small
illustration of the general shape.

Set against that: **boosting these eleven currently costs the full network
payload and delivers a broken page**, because the server renders everything and
htmx throws all but main away. Boost is strictly worse than no boost for them
today. Opting out is a strict improvement with no downside against current
behaviour. Moving scripts into the swap region is a further improvement, real
client-side savings, bought with unexercised re-execution. Take the strict
improvement.

**This treats the instances, not the class.** A twelfth `{% block scripts %}`
page added to the nav later would be silently broken exactly as these were. That
is what the tripwire is for, and a note in `CLAUDE.md` is not sufficient because
nobody reads documentation while adding a nav link.

### The tripwire

A test that fails when someone boosts a page whose JS lives outside `<main>`.

Assert, for every boosted sidenav href: the template that href resolves to
contributes no `<script>` to `{% block head %}` or to `{% block scripts %}`.

**Both blocks, not just scripts.** Head renders at 87, also outside main, and is
how the map page hit this. A test covering only `{% block scripts %}` would pass
a future page that loads a library in head and is boosted, which is the map case
reintroduced.

Modelled on the endpoint auth census, which already generates a case per route.
This adds cases per sidenav link, so the suite total moves and the movement is
predictable in advance.

## Defect A: the fix

`PageInit`, shipped inert in `5e4cfb5`.

    PageInit.init(name, fn)   called by the page, after its root
    PageInit.ready()          called once by base.html, after _lockManager

`init()` finds the root carrying `data-page-init="<name>"`, and does nothing if
it is missing or already marked. It marks the root, then runs `fn` immediately if
`ready()` has fired or queues it if not. `ready()` flushes and sets the flag.
`init()` logs a console error naming the page when the root is missing, and
returns; not a throw, because a throw inside swapped content can abort the
remaining scripts in that fragment.

**Placement.** The root's opening tag must appear before the script in document
order. Inside the root is sufficient but NOT required: a script after the root's
closing tag still finds it, because the root and its children are parsed by then.

**Queueing is the ordering guarantee.** On a full load a script inside main runs
before `base.html:747`, so `_lockManager` does not exist yet. On a boosted swap
it was never destroyed. Queueing covers both without an event.

**The design uses no htmx event.** With no partial swaps anywhere in the app, a
page's own inline script executes exactly once per entry and is a more reliable
trigger than an event whose semantics would need re-verifying per htmx version.
That swapped scripts re-execute is established, not assumed:
`fulfillment.html:3229` comments "var, not let or const: hx-boost re-executes
this block on a boosted return", and `3f3c0f7` fixed that redeclaration.

**Two migrations**, `triage.html` and `fulfillment.html`. Each gets
`data-page-init` on its existing page root and its `DOMContentLoaded`
registration becomes a `PageInit.init` call taking the former handler body.

**Check both for top-level `let`, `const` and `class`** before migrating. Their
scripts already re-execute today, so any such declaration is a live bug, not a
new risk.

## Verification

Gate order is the skill's, plus the browser checks.

1. pytest baseline immediately before editing. Current is 874 passed, 39
   skipped. The opt-out commit and the migration commit add no routes and no
   tests, so predict 874 and treat any movement as a signal. The tripwire commit
   adds cases; state the expected number before running it.
2. jinja parse on every changed template
3. JS check: node is not on apphost, so the browser console after a fresh
   reload is the real check
4. restart app, confirm worker up
5. Browser gates below
6. `git diff` review, then commit, then four location sync

**Defect B gate.** For each of the eleven: reach it from the sidenav, confirm it
full-loads, and confirm its page JavaScript works. `admin_errors` is the sharpest
case, since it was observed broken: `filterErrors` must be defined and the filter
must actually filter.

| Check | Expected |
|---|---|
| Each of the eleven, reached from the sidenav | Full load. Page JS present and working |
| The ten unaffected sidenav pages | Still boosted, still working. No regression |
| Locking and any live updates on one of the eleven | Still work. Full loading tears down and rebuilds `_lockManager` and any SSE connection, which map already does, but confirm |
| Browser Back into one of the eleven after a boosted nav | Works. htmx history restore replays a main-only swap, so it is a third entry path into the same discard |

**Defect A gate.** For `triage` and `fulfillment`:

| Check | Expected |
|---|---|
| Direct load by URL | Init runs, page fully initialised |
| Sidenav away and back | Init runs again, fully initialised, not the degraded state |
| Browser Back into the page | Same as the sidenav return |
| Console on all paths | Clean. No redeclaration error, and no `PageInit` error, which would mean the root was not found |

Fulfillment on a boosted return must show an active deployment tab, filtered
cards and populated mini-step trackers.

## Commit plan

`5e4cfb5` already shipped the helper, inert. Then:

1. **The eleven opt-outs.** `base.html` only. Fixes the more severe defect first
   and carries no re-execution risk.
2. **The tripwire test.** Lands right after the fix it guards.
3. **The two PageInit migrations.** `triage.html` and `fulfillment.html`.

Ordered by severity. Defect B leaves eleven pages inert; defect A degrades two.

## Follow up tracks this creates

- **Moving page scripts inside `<main>`.** Not needed, but it is what would buy
  boosted navigation back on those eleven pages. Cost is auditing eleven pages
  for behaviour under re-execution, which is not greppable. Revisit only if the
  client-side savings are wanted; the tripwire makes deferring it safe.

- **htmx is loaded from unpkg.com at runtime.** `base.html:83` pulls
  `htmx.org@2.0.4` from a public CDN, no integrity attribute, no vendored copy in
  `static/js/`. Lose egress and hx-boost stops working. Blast radius is small,
  since htmx does nothing here but the nav boost, and the degraded state is full
  page loads, which would incidentally mask both defects above. Fix is one
  vendored file plus one line.

- **`search.html` carries seven top-level `const` and `let` at 53-59.** Harmless
  today because that script never re-executes. It becomes a live bug the moment
  anyone boosts that page or moves its scripts inside main. Recorded so the next
  person does not rediscover it.
