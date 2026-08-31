# Page init on boosted navigation

Status: specced, not built.
Owner note: WHAT and WHY only. The HOW is the `asset-tracker-workflow` skill.
Repo facts live in `CLAUDE.md`.

## Why

`app/templates/fulfillment.html` registers its page init on `DOMContentLoaded`.
That event does not fire on an hx-boost swap, so returning to the board through
the sidenav leaves no active deployment tab, every card unfiltered, and the
mini-step trackers empty.

Fulfillment is not the page with the bug. It is the page that was looked at.
Nine registrations across eight templates, all inside `<main>` and therefore all
inside the swap region:

    triage.html:632        provisioning_detail.html:803  fulfillment.html:3402
    item_detail.html:681   receive.html:1202 and :1501   admin_errors.html:229
    certification_detail.html:565                        provisioning.html:1287

`base.html`'s four registrations are NOT affected. The sidenav boosts with
`hx-target="main"`, so `base.html` sits outside the swap, runs once, persists.

**The root cause is that neither available event means "this page arrived."**
`DOMContentLoaded` fires too rarely: never on a swap. `htmx:load` fires too
often: on every swap, which is why moving the block verbatim would re-run
`switchBldTab` and `switchDeployTab` and stomp the chosen tab. Choosing between
them cannot work. Build the trigger that is missing instead.

## What the reads established

| Question | Answer |
|---|---|
| How many affected sites | 9 registrations across 8 templates, all inside `<main>` |
| Does any page swap a fragment of itself | NO. `hx-target`, `hx-swap`, `hx-get` and `hx-post` appear nowhere outside `base.html`. Seven of the eight templates contain zero `hx-` occurrences; fulfillment's single hit at line 3229 is a comment, not an attribute |
| The only swap in the app | The sidenav hx-boost with `hx-target="main"`, replacing main's children wholesale |
| Where is `<main>` | `base.html:473` to `495` |
| Where is `_lockManager` | `base.html:747`, after `<main>` and outside it |
| Do swapped scripts re-execute | YES, established not assumed. `fulfillment.html:3229` carries the comment "var, not let or const: hx-boost re-executes this block on a boosted return", and `3f3c0f7` shipped the fix for that redeclaration |
| htmx | 2.0.4, pulled from unpkg.com at runtime, not vendored. See follow ups |

The second row is what makes this tractable. With no partial swaps anywhere, a
page's own inline script executes exactly once per page entry, on a full load and
on a boosted swap alike. That script is the trigger the app was missing.

## The design

A helper defined in `base.html` BEFORE `<main>` so page scripts can call it,
plus a release call at the END of `base.html`, after `_lockManager`.

    PageInit.init(name, fn)   called by each page, at the end of its template
    PageInit.ready()          called once by base.html, after _lockManager

Semantics:

- `init()` finds the page root carrying `data-page-init="<name>"`. If the root is
  missing or already marked, it does nothing.
- It marks the root, then either runs `fn` immediately, if `ready()` has already
  fired, or queues it until `ready()` fires.
- `ready()` flushes the queue and sets the flag.

Why each piece exists:

- **Queueing until `ready()`** is the ordering guarantee. On a full page load a
  script at the end of `<main>` runs before `base.html:747`, so `_lockManager`
  does not exist yet. That is exactly why `item_detail.html:679` wraps in
  `DOMContentLoaded` today. Queueing preserves the guarantee without the event.
- **Running immediately once ready** is the boosted case. On a swap
  `_lockManager` was never destroyed, so there is nothing to wait for.
- **The root marker** is a guard, not load bearing. With no partial swaps it
  cannot fire twice today. It exists so that adding an `hx-get` to one of these
  pages later does not silently reintroduce the stomp.

**No htmx event listener is required.** The design does not depend on when
`htmx:load` fires, or whether it fires at initial load. That is deliberate: the
page script is a more reliable trigger than an event whose semantics would have
to be re-verified per htmx version.

**"Preserve selection" is not a requirement.** The original framing asked for an
idempotent hook that preserves the user's chosen tab. On a genuine re-entry the
DOM is new and no selection exists, so setting the default is correct. The stomp
case arose only from `htmx:load` firing on partial swaps, and there are none.

## Changes

### 1. The helper

In `base.html`, before `<main>` (before line 473). Small, no dependencies.

`PageInit` is a NEW top-level JS name. Assert it free before adding, per
`CLAUDE.md`.

### 2. The release call

In `base.html`, after the `_lockManager` construction at line 747.

### 3. Page root elements

Each of the eight templates gets a root carrying `data-page-init="<page>"`. Use
the existing outermost page container where one exists rather than adding a
wrapper element.

### 4. Eight migrations

Each `DOMContentLoaded` registration becomes a `PageInit.init` call taking the
former handler body as its function. `receive.html` has two registrations and
needs a decision: two names, or one init that does both. Read them before
choosing.

### 5. Re-execution safety, per template

Because swapped scripts re-execute, any TOP-LEVEL `let` or `const` in these
templates throws on a boosted return. Moving a handler body into a function
scopes what was inside it; declarations outside the old handler are not covered.

Check each of the eight for top-level `let` and `const`, and for top-level
function names, which `CLAUDE.md` already flags as a hazard.

This is the same class of defect `3f3c0f7` fixed in `fulfillment.html`. Expect
to find others. Any found are part of this track, not a separate one.

## Verification

Gate order is the skill's, plus the per-page browser check.

1. pytest baseline immediately before editing. Current is 874 passed, 39
   skipped. This change adds no routes, so the endpoint auth census contributes
   nothing and the total should NOT move. Predict 874 and treat any movement as
   a signal.
2. jinja parse on every changed template
3. JS check: node is not on apphost, so the browser console after a fresh
   reload is the real check. Read it on each of the eight pages
4. restart app, confirm worker up
5. Browser gate, below
6. `git diff` review, then commit, then four location sync

**Browser gate, and it covers all eight pages, not just fulfillment.**

For each of triage, provisioning_detail, fulfillment, item_detail, receive,
admin_errors, certification_detail and provisioning:

| Check | Expected |
|---|---|
| Load the page directly by URL | Init runs, page fully initialised |
| Navigate away through the sidenav and back | Init runs again, page fully initialised, not the degraded state |
| Console on both paths | Clean. In particular no redeclaration error on the return |

`fulfillment` carries the original symptom and is the sharpest check: on a
boosted return it must show an active deployment tab, filtered cards and
populated mini-step trackers.

`item_detail` is the ordering check. Its init depends on `_lockManager`. Confirm
locking still works on a DIRECT load, which is the case where ordering matters.

## Commit plan

Three commits.

1. The helper plus the release call. `base.html` only. Nothing uses it yet, so it
   ships inert and is reviewable on its own.
2. `fulfillment.html` migrated. One page, the page with the reported symptom, so
   the pattern is proven against the known case before it is applied seven more
   times.
3. The remaining seven.

Split this way because commit 2 is where the design is validated. If the pattern
is wrong it is wrong on one page rather than eight.

## Follow up tracks this creates

- **htmx is loaded from unpkg.com at runtime.** `base.html:83` pulls
  `htmx.org@2.0.4` from a public CDN, with no integrity attribute and no
  vendored copy in `static/js/`. For a LAN tool that puts a third party on the
  critical path of every page load: lose egress or hit a CDN outage and hx-boost
  stops working. Blast radius is smaller than it looks, because the same read
  that found no `hx-get` anywhere proves htmx does nothing in this app but the
  sidenav boost. Losing it degrades navigation to full page loads, which would
  ironically mask this track's bug by making `DOMContentLoaded` fire again.
  Still worth vendoring, and the fix is one file plus one line.

- **The stomp guard is untestable by construction.** The root marker cannot be
  exercised while no page issues an htmx request. Whoever first adds an `hx-get`
  to one of these pages should verify it then.
