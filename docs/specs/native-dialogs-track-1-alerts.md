# Native Dialogs, Track 1: alert() to SxToast

    STATUS:   rev 7, committed
    Written:  2026-09-09, rev 4 to rev 6 on 2026-09-10
    Board:    BACKLOG-TRIAGE.md item N7, track 1
    Taken at: HEAD 160d339, branch main
    Scope:    102 native alert() call sites across 18 files, converted to
              SxToast. Tracks 2 to 4 (confirm, prompt, credential display)
              are named at the end and are NOT specified here.
    Rev 2:    Totals corrected (warnings are 12, not 11). Ternary census
              re-run and closed. order_detail.html:960 read and demoted
              from exception to swap. SxToast availability on the two
              admin pages confirmed. Four exceptions remain, not five.
    Rev 3:    show() body READ; guard placement and duration mechanism
              confirmed. Guard now reports to error_log via the existing
              reportError pipeline, not console alone. Default strings
              settled. All owed items closed. Verified by program: the
              102 site rows and every line number diff clean against the
              repo at 160d339.
    Rev 4:    Known gap CLOSED by item A (2026-09-10). Cookie check in
              reportError removed, frontend reporting live. Two paragraphs
              rewritten, stale toast.js anchors stripped, the endpoint
              audit plan restored, a wrong date fixed.
    Rev 5:    Exception 2 decided: the success half carries across the
              reload via the ?toast= parameter, the count-0 half drops
              its reload. Rule 2 gains that third option. Stale
              toast.js line anchors stripped to names.
              provisioning_detail.html:800 corrected. Gates 2 and 6
              restated.
    Rev 6:    Exception 1 decided: the success message carries across the
              reload via the ?toast= parameter, auto-dismiss. Its "cannot
              recover" claim was false: the endpoint saves the coordinates
              and the page prints them. Gate 6 restated. Rule 1 and Rule 2
              notes added; Rule 2's stale "already sticky" corrected.
    Rev 7:    Track 1 COMPLETE at 0dc0059. Closing census added after the
              Totals section, with the per-type reconciliation against the
              site table. M1 recorded as served-and-parsed by decision, with
              the recipe that makes it observable. N14 recorded. Exception 3
              confirmed observed live. Exception 4's runtime type READ and no
              longer open. R28 and R29 corrected. The site table is
              deliberately unchanged: it is a record of where the sites were
              at 160d339, and its line numbers are stale by design.

## Why

`docs/specs/customer-order-cancel.md:177-181` bans native browser dialogs
with three grounded reasons: they are untestable by automation, they are off
the design system, and they fail silently on a second dismiss. That ruling
names an in-app modal as the remedy, because its subject was a confirmation.

**This spec extends that ruling to one-way notices.** An `alert()` asks the
user nothing. It reports. The correct remedy for a report is a toast, not a
modal, and `SxToast` is the shipped primitive for it (`static/js/toast.js`,
loaded from `base.html:84` through the `js_v()` cache-busting helper,
documented at `DESIGN_SYSTEM.md` archetype table, Toast row).

The ban and its reasons are unchanged. Only the remedy differs, and only for
the notice shape.

## Census

READ at HEAD 160d339, reconciled three ways.

| Measure | Value |
|---|---|
| Occurrences, `app/templates/` + `static/js/` | 102 |
| Occurrences, whole repo | 103 |
| Files in scope | 18 |
| Wrapper functions found (`showAlert(`, `.alert(`) | 0 |

Two call forms, cleanly partitioned by file: `window.alert(` is 11 sites and
all of them are in `c2c.html`. The other 91 sites use bare `alert(`.

**Excluded, 1 site.** `docs/mockups/superdesign/installation_completion.html`
carries the 103rd occurrence. It is a design mockup, not shipped code.
`grep -rn 'installation_completion\|superdesign' app/ static/` returns rc 1:
no route, template or script references it, so it is unreachable and
converting it would ship nothing. The sibling mockup
`building_delivery_board.html` carries zero native dialogs of any shape, so
this exclusion names one file, not the directory.

A future reader greping `alert(` will find this one hit. It survives by
decision, not by omission.

**SxToast availability confirmed.** Sixteen of the eighteen files are
templates. The two standalone scripts are loaded by exactly one template
each, `admin_part_numbers.html:192` and `admin_spreadsheet_sync.html:63`,
and both templates open with `{% extends "base.html" %}`. `SxToast` is
therefore defined on every page in scope. This was checked because a script
loading on a page outside `base.html` would have turned a working alert into
a silent throw.

## Prerequisite commit: the SxToast message guard

**This lands before the sweep, as its own commit, with its own gate.**

`show(message, type, duration)` in `toast.js` already defaults its second
and third arguments (`type = type || 'info'`, then duration). It
does not default the first.

Fourteen of the 102 sites pass an argument that can be `undefined`, `null`,
or a non-string:

- Six bare calls in `provisioning.html` (`alert(data.error)`,
  `alert(err.message)`, lines 1034, 1035, 1044, 1045, 1054, 1055)
- Two in `warranty.html` (723, 777)
- `map.html:564` and `:664`, bare `r.error` and `j.error || j.detail`
- Four others carrying `data.error` with no fallback string

Today these render the literal word `undefined` inside a native dialog. As a
toast they render an empty or nonsense body, which reads as broken.

**Required behaviour.** In `show`, between the existing defaults and
`ensureContainer()`. Everything downstream consumes `message` exactly once,
via `escapeHtml`, so a guard at that point covers every path.

1. If `message` is `null`, `undefined`, or an empty string after trimming,
   substitute the type default below.
2. If coercion yields `[object Object]`, or throws (a symbol), treat it as the
   empty case and substitute the type default. Otherwise coerce with
   `String(message)`, so an Error object or a number produces readable text.
3. When the fallback fires, do both of the following:
   - `reportError('SxToast called with empty message, type=' + type,
     new Error().stack, window.location.pathname, 'warning')`
   - `console.warn` with the same text.

**Why both.** An empty toast message is **not** a JS error. Nothing throws:
`escapeHtml(undefined)` assigns the literal word to `textContent` and the toast
renders reading "undefined". The global handlers in `toast.js` and the
`unhandledrejection` and HTMX capture never see it. The guard is what makes a
silent condition visible. The console serves whoever is at the screen now; the
`error_log` row is the durable, filterable record.

**The report lands somewhere real.** `error_routes.py` carries the receiving
endpoint at :80, a `log_error()` writer at :49, an admin page at
`error_log_page:207` with 24-hour totals split by frontend and backend source,
a detail view at :299, and a retention purge at :195.

**Level is `warning`, deliberately.** `MAX_REPORTS = 5` per minute is shared
across the whole pipeline, so a page firing many empty toasts would consume the
budget genuine JS errors need. Reporting at warning level keeps these
filterable and distinguishable from real errors on the admin page.

**`reportError` is declared below `show`.** Function declarations hoist
within the IIFE, so the call works. Do not reorder the file to "fix" this.

**The guard calls the reporting pipeline.** Through R15 and the guard commit,
the region from the "Error capture & reporting" marker to EOF stayed
byte-identical. Item A (2026-09-10) then removed one check inside
`reportError` and nothing else in that region, so the guard's call is live and
the gate can read `error_log` as well as the console. See "Known gap"
immediately following.

**Known gap, CLOSED by item A on 2026-09-10.** `reportError` returned early
unless the `inventory_session` cookie was visible in `document.cookie`. That
cookie is HttpOnly: starlette's `SessionMiddleware` hardcodes `httponly` in
`security_flags` and exposes no parameter to disable it, so the check failed
on EVERY call, not only on expired sessions. When this was found, `error_log`
held nine rows, all `backend`, newest 2026-07-23, and no `frontend` row had
ever been written. Three deliberate rows followed, in this order: 78, a
direct `fetch` POST from the console proving the endpoint and the admin page;
79, a direct `sendBeacon` proving the path the JS actually uses; then the
check was removed, and 80, the guard's own warning fired live, proved the
fix. The check was removed, not replaced. The endpoint authenticates via
`get_current_user`, `/api/` paths pass through the auth redirect middleware
to it, a logged-out beacon gets a JSON 401 that no handler logs, and the
login page does not load `toast.js`.

**Default strings.** Plain text only. These land in `innerHTML` through
`escapeHtml`, and the surrounding markup is assembled by string
concatenation, so no markup characters and no entities.

| Type | Default |
|---|---|
| error | `Request failed. Try again, and tell an admin if it keeps happening.` |
| success | `Done` |
| warning | `Something needs attention` |
| info | `(no message)` |

The error default is the one a real user will hit, and it is **actionable
rather than neutral**. The guard cannot manufacture a detail the server never
sent, so the message tells the user what to do instead: retry, and escalate.
Because the same fallback writes an `error_log` row carrying the URL and
username, by the time the user reports it the detail is already waiting.

`(no message)` for info is deliberately ugly. No info site in this census
passes a server value, so an empty info is a coding mistake rather than a data
state, and it should look like one.

**`@ts-check` is on at `toast.js:1`,** and `show` carries
`@param {string} message`. The JSDoc must widen when the guard lands, or the
file starts emitting type errors. The guard is what makes the fourteen call
sites above contract-legitimate, so this is not cosmetic.

**Gate. Console half only; the database half is void.** In the browser
console, call `SxToast.error(undefined)` and `SxToast.error({})`. Each must
render readable body text and emit exactly one `console.warn`, branched:
`empty` for the first, `non-serialisable` for the second.
`SxToast.error('real message')` must render its own text and emit no warning.

RESULT at this commit: PASSED. Three toasts rendered, the first two carrying
the error default and the third carrying `real message`; exactly two warnings,
correctly branched; no JS errors on the page, which is the real parse check
since node is not on apphost.

The originally specced database half CANNOT pass and is removed rather than
weakened. It required one warning-level frontend row in `error_log` per
fallback, and no frontend row can be written at all. See "Known gap" above.

## Rule 1: duration

`show` already defaults duration to 6000ms for `error` and 4000ms for every
other type, and `if (duration > 0)` in `show` registers no timeout when
duration is 0. Both READ, not assumed. **Auto-dismiss is therefore the default and the sweep writes
nothing for it.** Only sticky sites pass an explicit `0`.

> **Sticky (`duration: 0`) when the message carries information the user
> cannot reconstruct after it fades: a server-supplied error detail, or a
> scan result. Auto-dismiss otherwise.**

Applied across the census this yields **75 sticky, 27 auto-dismiss**. The
rule discriminates rather than rubber-stamping, but errors interpolating a
server value dominate this codebase, so the sticky share is high and that is
correct.

**Rev 5.** Exception 2's success half is now auto-dismiss (see Exception 2).
The 75 and 27 above were not re-derived for that change. They sum to 102
while the type assignments total 103, so how `vendors.html:364` was counted
is not recorded here.

**Rev 6.** `site_detail.html:472` is now auto-dismiss too (see Exception 1).
The 75 and 27 were not re-derived for this change either.

This rule is cheap to revise. It lives in this paragraph plus one column of
the site table, so changing it means editing a table, not re-reading 102
sites.

## Rule 2: reload-adjacent sites

Native `alert()` **blocks**. The browser halts until the user dismisses it,
so any statement after the alert waits. `SxToast` does not block. A toast
followed by a page load is destroyed before it can be read.

> **Where an `alert` is followed by `location.reload()` or a `location.href`
> assignment in the same branch, the toast is not a drop-in.** Either defer
> the navigation until after the toast, or drop the reload where the toast
> plus existing DOM already tells the story. Each such site is named in the
> exception list and is out of the mechanical sweep.

**Rev 5 adds a third option:** where the navigation is what shows the result
and the message is a success, carry it across with the `?toast=` parameter.
See Exception 2.

Censused two ways: same-line pairs by grep, then a five-line window after
every `alert(` with each candidate block read in full. **Two sites qualify.**
Both are success messages. Both were sticky under Rule 1 until rev 5 and
rev 6 moved them to auto-dismiss.

**Rev 5.** Exception 2's success half no longer shows its toast before the
navigation; it carries the message across it (see Exception 2).

**Rev 6.** Exception 1 takes the same third option. Both Rule 2 sites now
carry their success message across the navigation.

**Window residual.** A comment of five lines or more after an `alert(` fills
the window, so a reload after it would not be seen. `fulfillment.html:3391`
has a five-line comment after its toast. It was read in full and cleared:
its reload is `pkLoad()`, a modal list refresh, and the branch returns
before the page reload. The census itself was not re-run.

Three near-misses were read and cleared, and they are recorded so the census
is not re-run:

- `c2c.html:406` and `:415`. Reload and alert are in **opposite branches** of
  an if/else. They never both run.
- `fulfillment.html:2809` and `:3005`. Both sit inside
  `if (!res.ok) { ... return; }`; the returns are at :2810 and :3007. The
  reload is unreachable when the alert fires.
- `decommissioned.html:82` and `item_detail.html:883`. Same guard-and-return
  shape.

## Rule 3: convert, do not add

Track 1 converts existing notifications. **It does not add missing ones, and
it does not change where an existing one is displayed.**

`provisioning_detail.html:800` is the clearest case. Its catch reports only
thrown errors (a network failure, or a success response whose body is not
JSON). An HTTP error status is silent, because the function has no else
branch. Success updates the watch button and shows no message. Adding the
missing notifications would be an improvement and it is out of scope.

The second half of the rule is load-bearing at `order_detail.html:960`. See
"Recorded, not resolved" below. Without this rule the sweep quietly becomes a
UX redesign and its diff stops being reviewable.

## Rule 4: ternaries

**A ternary that selects between messages of different types is a split, not
a swap.** A toast call takes its type as an argument, so one call cannot be
two types. Such a site becomes an if/else with two toast calls.

**A ternary inside a message string is a swap.** It selects text, not type.

Censused with `grep -rn "alert([^;]*?[^;]*:"`, rc 0, two hits, both read:

- `vendors.html:364` selects between an info message and a success message.
  **Split.** See Exception 2.
- `fulfillment.html:3214` carries `${data.location ? ' at ' + data.location :
  ''}` inside a template literal. The type is `success` either way. **Swap.**

**Residual.** That grep is line-scoped and `fulfillment.html:3214` proves
multi-line `alert(` calls exist here. A ternary spanning two lines would not
have matched. The earlier five-line-window reads surfaced no other
continuation lines, so the population is believed empty, but it is not
proven empty.

## The four exceptions

Every other site is a mechanical substitution. These four are not, and each
needs a named decision before it is touched.

**1. `site_detail.html:472`, reload hazard.**
`if (data.geocoded) { alert('Pinned at ' + data.lat.toFixed(4) + ', ' + data.lng.toFixed(4)); location.reload(); }`
Success. Rule 2 applies. Its else branch at :473 is an instructional warning
("Set the pin manually on the map (Fix flow), or correct the address") and
converts normally, sticky. The two branches ship together.

**Decided in rev 6 (2026-09-10): carry the success message across the
reload, auto-dismiss.** Rev 5 and earlier called this site sticky because
the coordinates could not be recovered. That was false. The geocode
endpoint (`regeocode_site` in `sites.py`) writes `geo_lat` and `geo_lng`
and commits before it responds, and the page's Map line prints both at
four decimals, the same precision as the message. The reload is what shows
the result, so Rule 1's test for sticky is not met.

- Set the `toast` query parameter with `URLSearchParams` and navigate, the
  same mechanism as Exception 2. The message keeps `toFixed(4)` so it
  matches the page.
- Deferring the reload was rejected: for the toast's lifetime the page
  would show "Not located" beside "Pinned at". Dropping it was rejected:
  the page would contradict the toast until a manual refresh.

The limit: the page does not mark the pin as new; `geocoded_at` is not
shown. The handler's hardcoded success (N10) is correct here. The message
is fixed text plus two numbers holding only digits, minus signs and dots,
so the double decode never meets a `%`.

**2. `vendors.html:364`, reload hazard AND a ternary split.**
```
alert(count === 0 ? 'All vendors already have profiles.'
                  : `Created ${count} new profile${count !== 1 ? 's' : ''}.`);
location.reload();
```
One call, two messages, two types. `count === 0` is **info** and its reload is
pointless. `count > 0` is **success** and is the only confirmation the user
gets that the seed did anything. Splits into an if/else under Rule 4. Rule 2
applies to the success branch.

**Decided in rev 5 (2026-09-10): carry the success message across the
reload.** The page's two lists are server-rendered (Jinja loops over
`profiles` and `unlinked_vendors`) and no JS reloads them, so the reload is
what shows the result. Dropping it leaves the unlinked list naming vendors
that now have profiles. Deferring it destroys the toast.

- `count === 0`: `SxToast.info`, auto-dismiss, reload dropped. Nothing
  changed, so the existing page already tells the story.
- `count > 0`: set the `toast` query parameter with `URLSearchParams`
  (existing parameters survive, as they do under `location.reload()`) and
  navigate. The `?toast=` handler in `base.html` renders a success toast at
  the default duration and strips the parameter.

Auto-dismiss, not sticky, for the success half. After the reload the new
profiles are on screen, and the endpoint is admin-only and writes the count
and the first ten names to the audit log, so Rule 1's test for sticky is not
met. The limit: the screen does not mark which profiles are new.

The handler hardcodes `SxToast.success`. Correct here, wrong for most of its
22 server-side callers, which pass failures. Board item N10, outside this
track.

**3. `admin-spreadsheet-sync.js:172`, multi-line message.**
```
alert(`Success!\n${result.stats.added} added, ${result.stats.updated} updated, ${result.stats.skipped} skipped`)
```
Native `alert` renders the newline. The toast will not: `escapeHtml`
(in `toast.js`) sets `textContent` and reads back `innerHTML`, and the
container it builds sets no `white-space` override, so HTML collapses
the newline to a space. It renders as one line. **Accepted.** Success, sticky
under Rule 1 (the counts are unreconstructable). This is Casey's spreadsheet
import path.

**Observed live at 0dc0059.** The toast renders green and sticky, and the
newline renders as a single space under `white-space: normal`, exactly as
accepted above. The quoted call above was corrected in rev 7: the code reads
`${result.stats.added}`, not `${added}`.

**4. `map.html:564`, bare variable inside a then-chain.**
`.then(function (r) { if (r && r.error) alert(r.error); else reloadData(); });`
The runtime type of `r.error` is a **string on every server path** (READ at
0dc0059 in `map.py`: every failure path returns `{"error": "<string>"}`). The
prerequisite guard's coercion clause is therefore not load-bearing here. Note
the else branch calls `reloadData()`, not a page reload, so Rule 2 does not
apply. Converted and shipped in the small-files bundle at 49d468e; see the
closing census for why it was never fired.

**Demoted in rev 2.** `order_detail.html:960` was Exception 4 in rev 1 on the
grounds that `err`'s type was unknown. Read at :950/:951: `err` comes from
`await putSkuLines(lines)` and the sibling function assigns it directly to
`errEl.textContent`, so it is a string or falsy. It is a plain swap, error,
sticky.

## Recorded, not resolved: the error-shape divergence

`order_detail.html` calls `putSkuLines` twice, two functions apart, and
handles the returned error two different ways:

- `saveSkuLine` at :951 writes it into an inline `errEl` element
- `removeSkuLine` at :960 fires a native `alert`

This is board item 5, "two error-shape conventions", appearing inside one
file. **Track 1 converts :960 to a toast as specced.** The divergence stands
and becomes more visible, because one function will show inline text and its
sibling a toast.

That is deliberate. Deciding where an error message belongs is a convention
question, not a mechanical one, and settling it inside a conversion sweep is
exactly what Rule 3 forbids. **A separate board item carries the real fix:**
choose the rule (proposed: inline when the user is mid-form and can correct
it in place, toast when the operation is over), write it into
`DESIGN_SYSTEM.md` next to the Toast archetype row, and close item 5. That
work needs a census of the inline-error sites this sweep never touches, and
it is not a same-session add-on with track 1.

## Site table

Type and duration for all 102 sites. `auto` means pass no duration argument.

### app/templates/fulfillment.html, 26 sites

| Line | Type | Duration |
|---|---|---|
| 1938 | error | 0 |
| 1943 | error | auto |
| 2019 | error | 0 |
| 2248 | error | 0 |
| 2728 | warning | auto |
| 2729 | warning | auto |
| 2730 | warning | auto |
| 2786 | error | 0 |
| 2795 | error | auto |
| 2809 | error | 0 |
| 2815 | error | auto |
| 2882 | warning | auto |
| 2921 | warning | auto |
| 2937 | error | 0 |
| 2945 | error | auto |
| 2980 | error | 0 |
| 2989 | error | auto |
| 3005 | error | 0 |
| 3012 | error | auto |
| 3111 | error | 0 |
| 3126 | error | 0 |
| 3206 | error | 0 |
| 3214 | success | 0 |
| 3218 | info | 0 |
| 3391 | error | 0 |
| 3402 | error | auto |

Five warnings in this file: 2728, 2729, 2730, 2882, 2921. All are
`if (!x) { alert(...); return; }` validation guards.

3214 is a multi-line call: the string continues past the line with a `+`.
3214 and 3218 are the barcode scanner result and miss. The user is holding a
scanner and looking at hardware, not the screen, which is why both are sticky.

### app/templates/c2c.html, 11 sites

All eleven use the `window.alert(` form.

| Line | Type | Duration |
|---|---|---|
| 289 | error | auto |
| 336 | warning | auto |
| 343 | error | 0 |
| 345 | error | auto |
| 353 | error | 0 |
| 355 | error | auto |
| 401 | warning | auto |
| 406 | error | 0 |
| 407 | error | auto |
| 415 | error | 0 |
| 416 | error | auto |

Four then/catch pairs (343/345, 353/355, 406/407, 415/416). **Convert both
halves of each pair or the error handling goes inconsistent inside one
function.** Pair integrity is why this file is its own commit.

### app/templates/vendors.html, 9 sites

| Line | Type | Duration |
|---|---|---|
| 314 | error | 0 |
| 315 | error | 0 |
| 342 | error | 0 |
| 343 | error | 0 |
| 353 | error | 0 |
| 354 | error | 0 |
| 364 | EXCEPTION 2: info, or success via ?toast= | auto, see above |
| 366 | error | 0 |
| 367 | error | 0 |

### app/templates/provisioning_detail.html, 9 sites

All error, all sticky: 658, 659, 668, 669, 678, 679, 714, 715, 800.

800 is a lone catch: HTTP failures and success show no message. See Rule 3.

### app/templates/provisioning.html, 8 sites

All error, all sticky: 1034, 1035, 1044, 1045, 1054, 1055, 1214, 1217.

**Six of the eight have no fallback string** (1034, 1035, 1044, 1045, 1054,
1055). They depend on the prerequisite guard.

### app/templates/site_detail.html, 6 sites

| Line | Type | Duration |
|---|---|---|
| 389 | error | 0 |
| 391 | error | 0 |
| 401 | error | 0 |
| 403 | error | 0 |
| 472 | EXCEPTION 1: success via ?toast= | auto, see above |
| 473 | warning | 0 |

### app/templates/support.html, 4 sites

All error, all sticky: 146, 149, 169, 172.

### app/templates/receive.html, 4 sites

All error, all sticky: 1003, 1297, 1325, 1376.

**The strongest-worded messages in the app.** 1003 "Photo NOT saved", 1297
"the device was NOT submitted", 1376 "the device may not have been saved.
Check the inventory before retrying." This is a receiving workflow: someone
at a bench with hardware in hand. 1376 instructs the user to go verify
something.

1297 and 1376 contain em dashes. See the transport note.

### app/templates/order_detail.html, 4 sites

| Line | Type | Duration |
|---|---|---|
| 732 | error | 0 |
| 793 | error | 0 |
| 822 | error | auto |
| 960 | error | 0 |

960 was an exception in rev 1 and is now a swap. See "Recorded, not
resolved" for the divergence it sits inside.

### app/templates/item_detail.html, 4 sites

| Line | Type | Duration |
|---|---|---|
| 862 | warning | auto |
| 871 | warning | auto |
| 883 | error | 0 |
| 886 | error | auto |

862 and 871 are identical "A reason is required." guards.

### static/js/admin-spreadsheet-sync.js, 3 sites

| Line | Type | Duration |
|---|---|---|
| 12 | warning | auto |
| 172 | EXCEPTION 3 | 0 |
| 177 | error | 0 |

### app/templates/decommissioned.html, 3 sites

| Line | Type | Duration |
|---|---|---|
| 73 | warning | auto |
| 82 | error | 0 |
| 85 | error | auto |

### Remaining files, 11 sites

| File | Line | Type | Duration |
|---|---|---|---|
| warranty.html | 723 | error | 0 |
| warranty.html | 777 | error | 0 |
| vendor_detail_profile.html | 392 | error | 0 |
| vendor_detail_profile.html | 393 | error | 0 |
| sites.html | 287 | error | 0 |
| sites.html | 290 | error | 0 |
| pilots_due_back.html | 74 | error | 0 |
| pilots_due_back.html | 76 | error | auto |
| map.html | 564 | EXCEPTION 4 | 0 |
| map.html | 664 | error | 0 |
| admin-part-numbers.js | 118 | error | 0 |

`warranty.html:723` and `:777` are bare `alert(err.message)` with no
fallback. Guard dependency.

## Totals

| Type | Sites |
|---|---|
| error | 85 |
| warning | 12 |
| success | 4 |
| info | 2 |
| **Total type assignments** | **103** |

**103 = 102 distinct sites + 1**, because `vendors.html:364` is one call site
that becomes two toasts of different types under Rule 4. It is counted once
in success and once in info.

The per-file tables sum to 102 (26+11+9+9+8+6+4+4+4+4+3+3+11). Gate 1 asserts
a 102 to 0 delta on occurrences, which is unaffected by the split.

Rev 1 recorded warnings as 11 and the total as 102, which could not hold
alongside a split. `fulfillment.html` carries five warnings, not four.

## Closing census at 0dc0059

READ at HEAD 0dc0059 on 2026-09-11, on the workstation clone, after the last
track 1 slice shipped. Track 1 is COMPLETE.

| Measure | Value |
|---|---|
| Sweep-target occurrences, `app/` + `static/` | 0 (rc 1, clean no-match) |
| Sweep-target occurrences, whole repo | 27 |
| `SxToast.error(` app-wide | 97 |
| `SxToast.warning(` app-wide | 17 |
| `SxToast.success(` app-wide | 10 |
| `SxToast.info(` app-wide | 3 |

Both the bounded form and the unbounded form return rc 1 against `app/` and
`static/`. Every surviving occurrence is named:

| File | Occurrences |
|---|---|
| `docs/mockups/superdesign/installation_completion.html` | 1 |
| `docs/specs/native-dialogs-track-1-alerts.md` | 26 |

The mockup is the exclusion decided in the Census section. The 26 are this
spec quoting its own sites. Neither is shipped code, and 1 + 26 reconciles
with the whole-repo total.

**These counts are measured at 0dc0059, the parent of the revision that
added this section.** This file is itself 26 of the 27, so any text added
here that quotes a site moves the whole-repo number. The figures above
describe the tree before this revision and do not rot.

The four toast types sum to 127 calls at 0dc0059, against 89 at bd913d4
(error 65, warning 12, success 9, info 3, READ at that commit). The delta is
+38, and it reconciles per type, not merely in total:

| Type | bd913d4 | 0dc0059 | Delta | Predicted by the site table |
|---|---|---|---|---|
| error | 65 | 97 | +32 | 32 |
| warning | 12 | 17 | +5 | 5 |
| success | 9 | 10 | +1 | 1 |
| info | 3 | 3 | 0 | 0 |

The prediction column sums the types this spec assigned to the 39 sites
shipped after bd913d4, counting Exception 4 as the sticky error it was
decided to be and Exception 3 as its success. The 39th site is Exception 1,
which produces no direct call: its success travels through the `toast` query
parameter and is rendered by the handler in `base.html`. Every type matches
independently.

**M1, `map.html:564`, accepted as served-and-parsed only.** By decision, not
by observation. The converted line was served and parsed with a clean
console, but it was never fired: `postJSON` is closure-scoped, so the console
cannot reach it, and all three of its UI paths were closed at gate time. No
needs-location row qualified for a Fix button (all twelve shown are placeless
items), the hidden list was empty, and marker popups need a canvas that
renders blank in a hidden tab. **It becomes observable when an edge box or a
placed item enters the top twelve of the needs-location list:** click Fix,
enter a latitude of 999, Save. The server answers 400 "coordinates out of
range" and both `:664` and `:564` fire, with no write.

**N14, on the board.** Every `set-location` failure is reported twice. The
shared helper at `map.html:664` toasts on any non-OK response and returns the
body; the Fix form's `.then` at `:564` toasts the same error again. Every
failure path in `map.py` is non-OK, so there is no single-report path. Two
native dialogs before, two toasts now: Rule 3 kept both in the sweep and did
not create the duplication. Which line owns the report is a decision for N14,
outside this track.

## Gates

Line numbers drift. **Re-read every anchor immediately before editing.** The
numbers in this table were READ at HEAD 160d339 and are stale the moment any
commit touches these files.

1. **Count.** `grep -ro 'alert(' app/templates/ static/js/ | wc -l` returns
   102 before, 0 after. Assert the delta, not the absolute.
2. **The excluded mockup stays.** The `alert(` count in
   `docs/mockups/superdesign/installation_completion.html` is 1 before and
   after. A whole-repo count cannot serve, because this spec quotes
   `alert(` itself.
3. **Jinja parse** on all 16 templates.
4. **Browser console clean** after a fresh reload on each page touched.
5. **Per-type render.** At least one site of each of the four types
   triggered live and observed. The four barcode and geocode sites
   (`fulfillment.html:3214/3218`, `site_detail.html:472/473`) cover success,
   info and warning between them.
6. **Both reload hazards observed.** Each success toast renders on the
   reloaded page and no `toast` parameter is left in the URL. This gate can
   fail: convert either site naively and the toast is destroyed within a
   frame, which is visible. Exception 1 also: the toast's coordinates match
   the page's Map line.
7. **Suite** predicted before the run. These are template and JS changes with
   no Python, so the expectation is 906 passed / 39 skipped unchanged. The
   suite does not cover this work; it is a tripwire, not a proof.

## Transport

Generalising from three failures this session: **the local SSH heredoc
collapses `\n` escapes inside Python string literals and mangles em dashes
and other non-ASCII.** Checksums prove transport, not validity.

> **Use base64-over-stdin with sha256 at both ends, then `ast.parse` on the
> remote copy, for any generated script carrying escape sequences or
> non-ASCII characters.**

A 102-site sweep hits both hazards: `receive.html:1297/1376` carry em dashes,
`admin-spreadsheet-sync.js:172` carries a literal `\n` in a template literal,
and `vendors.html:358` (track 2) carries an escaped apostrophe and an em dash
together.

## Sweep discipline

- The diff should be 98 near-identical substitutions plus four named
  exceptions plus the guard commit. **Any line that does not look like the
  others is a flag.** Preserving that property is why Rules 3 and 4 exist.
- Account for every remaining `alert(` hit by name before declaring the sweep
  complete.
- Slice by file. **`fulfillment.html`** at 26 sites is a quarter of the work
  and is its own commit. **`c2c.html`** is its own commit for pair integrity,
  not for size.

## Owed before the sweep starts

**Nothing.** Every input is READ.

**Closed in rev 2:** the ternary census (re-run, rc 0, two hits, one split);
`order_detail.html:960`'s `err` type (string or falsy, demoted to a swap);
SxToast availability on the two admin pages (both extend `base.html`).

**Closed in rev 3:** the `show` body (`toast.js:58-98`), settling guard
placement, the duration mechanism, and the fact that an empty message renders
rather than throws; the four default strings; the admin error page
(`error_routes.py:207`), which is what makes the tripwire durable.

**Verified by program at HEAD 160d339.** The site tables parse to 102 rows;
type assignments resolve to 85 error, 12 warning, 4 success, 2 info, summing
to 103 with the one split; and every `file:line` in the spec diffs clean
against `grep -rn 'alert(' app/templates/ static/js/` with rc 0.

## Deferred, recorded

Three items surfaced by this spec that are **not** track 1 work. Each is on the
board; none is a same-session add-on.

**Item 5, the error-shape convention.** See "Recorded, not resolved" above.

**Endpoint error-message audit.** Fourteen sites pass a server value with no
fallback string, which is why the guard exists. Whether those endpoints ever
actually omit a message is **UNREAD**. The `data.error || 'Failed to save'`
pattern at most other sites suggests whoever wrote them expected omission, but
that is inference. **The guard is the cheap way to find out, now that item A
(2026-09-10) has made frontend reporting live.** Read `error_log` for
guard-generated rows once the sweep slices have landed and real traffic has hit
the fourteen sites: no rows meaning no problem, rows carrying the page URL and
a stack that locates the call site. Silence is evidence only after that
traffic, so this audit is sized after the sweep, not before.

**Session-expiry response shape.** When a session expires mid-action, what the
fetch receives is **UNREAD**. If the API answers with an HTML login redirect,
`await res.json()` throws and the user sees a JSON parse error for a mundane
event. Same family as the audit above and settled by the same read of a few
routes; size them together.

## Riders

**Cache-busting on `admin-spreadsheet-sync.js`.**
`admin_spreadsheet_sync.html:63` loads it with a bare `src` and no `js_v()`
helper, unlike `admin-part-numbers.js` at `admin_part_numbers.html:192` and
unlike `toast.js` at `base.html:84`. The sweep edits this file, and a stale
cached copy would make the conversion look like it silently failed. Rides the
commit that touches it. Related to R17.

## Tracks 2 to 4, named not specified

Blocked on board item 9: **there is no shared modal JS helper and no modal
archetype.** Four competing modal class families exist in `fl-restyle.css`
and every open/close function is defined inline per template. A
value-returning modal API has to exist before any of these can be specified.

- **Track 2: `confirm(`, 31 sites.** 29 follow a uniform
  `if (!confirm('...')) return;` shape. `guide.js:810` fires a confirm from
  inside an already-open in-app modal, which is a stacking case.
- **Track 3: `prompt(`, 8 occurrences, 6 real sites.**
- **Track 4: `admin-users-v2.js:642`,** which uses `prompt()` as a credential
  display box. Unique; needs its own decision.

**R43, corrected at 094807d.** The counts above are the census at 160d339,
and two of them did not survive contact with the build. Tracks 2 and 3
were never executed separately: the shipped Track 2 converted the confirm
sites and the prompt sites together, in five slices. Measured at af97f70
and closed at b6b8e03, the true figures are 31 confirm sites, 5 prompt
sites and 1 credential prompt, 37 in all, of which 36 are converted.
Track 3 is therefore not an open track. The authoritative per-site census
lives in `docs/specs/native-dialogs-track-2-dialogs.md` rev 2, in its
section on the census at b6b8e03 by state. Track 4 is closed by 094807d;
see the section at the end of this file.

Three notes carried forward from this census:

- `vendors.html:358` is a track 2 confirm containing an escaped apostrophe
  and an em dash. See the transport note.
- `order_detail.html:957` is a track 2 confirm containing a non-ASCII
  multiplication glyph, in the same function as track 1 site :960.
- `c2c.html:401` is a track 1 warning sitting inside a function that a track
  2 prompt conversion will rewrite. Not a blocker, but the two tracks meet
  here.

Precedent for a multi-slice spec of this shape:
`docs/specs/fl-tail-slices-complete-coverage.md`.

## Track 4: the credential readout, closed at 094807d

`admin-users-v2.js:642` was the last native dialog in the repo. It used
`window.prompt` to display a generated temporary password so an admin
could copy it. That is not a question, so `SxDialog.prompt` was the wrong
replacement: a required input preselected with a secret is a text field
pretending to be a readout, and cancelling it returns null for something
nobody asked.

**Decision (Jus, 2026-09-18).** Add a third kind to SxDialog rather than
build a page-level reveal panel or copy silently to the clipboard. A
page-level panel would hold the secret in the drawer DOM for as long as
the drawer stays open and needs its own clearing path. A silent clipboard
copy gives the admin no sight of what was copied and still needs a visible
fallback for when the clipboard refuses, which is this dialog anyway.

**The contract.**

    SxDialog.reveal({title, message, value, okLabel, copyLabel})
        -> Promise<true>

Defaults are title 'Copy this value', okLabel 'Done', copyLabel 'Copy'.
The value renders in a div, not an input, with `user-select:all` and a
monospace face, so one click takes the whole string. There is no Cancel,
because a readout that has been shown has been shown: Esc, the backdrop
and Done all resolve `true`, and callers do not branch on the result.
Copy calls the clipboard API and, when that is missing or refuses,
selects the value and relabels itself to 'Press Ctrl+C' for a beat. Focus
lands on Copy with the value already selected, so Ctrl+C works before the
mouse moves.

**Threaded, not duplicated.** reveal is a third `kind` inside the existing
`show()`. That edited six lines the other kinds share: the role ternary,
the cancel resolution, the Enter guard, the Tab ring, the listener binding
and the focus block. The role line now reads `confirm` as `alertdialog`
and everything else as `dialog`, which is byte for byte the same output
confirm and prompt had before. A second builder with its own overlay and
focus trap was the alternative and was rejected: two focus traps drift.

**An ordering trap the harness caught.** `focus()` clears the document
selection, so selecting the value and then focusing Copy threw the
selection away and left the readout unselected. The working order is focus
first, then select. That is the order the prompt path already used at
`input.focus(); input.select();`, so the convention was in the file
already.

**Gates.** A jsdom harness ran a 43 case confirm and prompt regression
suite against dialog.js before and after the change: 43 pass both times,
which is the no-regression evidence. A 50 case reveal suite passes after
and fails at its first case before, so the suite can fail. The guarded
patch script pinned all three targets by sha256 and cleared 24 synthetic
cases, every refusal path included, before transport. The live gate on
`/admin/users` drove the real reset flow behind a fetch guard that faked a
success response, so the readout rendered with a known value while no
request reached the server: the resource count was unchanged across the
whole flow and the console was clean against a probe proven live.

**Not verified live.** The clipboard success path relabels Copy to
'Copied' in the jsdom suite. A browser automation tab cannot hold the
focus that `navigator.clipboard.writeText` requires, so the live gate
exercised the refusal branch instead. The success branch is REPORTED, not
READ.

**Left as it is.** The reveal call sits inside the `try` that wraps the
fetch, so a throw inside it would surface as a network error. SxDialog
loads on every page from `base.html`, so that is theoretical; hoisting the
value out of the try to avoid it was judged a worse trade than the one
line it would save.
