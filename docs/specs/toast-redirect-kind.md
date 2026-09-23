# Toast Redirect Kind: the ?toast= handler learns a type

    STATUS:   rev 2, ratified 2026-09-15, amended 2026-09-16
    Written:  2026-09-15
    Board:    BACKLOG-TRIAGE.md item N10. Commit 2 also closes N15.
    Taken at: HEAD d5f9cfb, branch main
    Scope:    The ?toast= handler in base.html, its 24 callers, and how
              those callers encode the message. Nothing else.
    Anchors:  Every file:line below is at d5f9cfb, except under After
              ratification, and ages from the first commit that touches the file.

## Why

The handler in `base.html` (lines 530 to 543, READ) always calls
`SxToast.success`. It has 24 callers: 22 server-side redirects in
`app/routes/` and 2 client-side navigations. By message wording, 16 of the 24
report a failure, so each of those failures renders as a green success toast.

The handler also decodes the message twice. `URLSearchParams.get` has already
decoded it, and the handler runs `decodeURIComponent` over the result.
Observed through Chrome MCP on `/sites/`, 2026-09-15:

| URL | Shown | Parameter |
|---|---|---|
| `?toast=Checked+in` | "Checked in", green | stripped |
| `?toast=50%25%20off` | nothing | left in the URL |
| `?toast=1%2B1` | "1 1", green | stripped |

In the second case `decodeURIComponent` throws before the parameter is
stripped. The same expression evaluated in the page returned
`URIError: URI malformed`. The load-time console was not primed, so the throw
is READ by in-page evaluation and by elimination, not from the console.

Track 1 (`native-dialogs-track-1-alerts.md`, at the end of Exception 2)
names this defect and places it outside that track. No other doc owns it.

## The contract

- `toast` carries the message. Senders encode it exactly once:
  `URLSearchParams.set` in JavaScript, the redirect helper in Python
  (commit 2).
- `toast_type` is optional. The handler honours it only when it is exactly
  `success`, `error`, `warning` or `info`. Anything else, including a missing
  value, renders as success. The raw value never reaches `SxToast`.
- The handler reads `toast` with `URLSearchParams.get` and does not decode it
  again.
- The handler strips both parameters from the address bar with
  `history.replaceState` and keeps every other parameter.
- No duration travels. Every redirect toast auto-dismisses at the `SxToast`
  default. See Duration below.

## Decisions (ratified 2026-09-15)

### Duration

Track 1 Rule 1 applies: sticky only when the message carries something the
user cannot reconstruct after it fades. Of the 16 failure messages, 14 are
fixed strings.

The other 2 (`item_detail.py:209` and `:298`) name the lock holder. The item
page already shows that name in a persistent lock indicator:

- the indicator element at `item_detail.html:47` sits outside every
  conditional, so it renders on every item page;
- `item_detail.html:709-715` fills it on page load when another user holds the
  lock, before the edit-mode check at `:717`;
- `locks.js` `_showLockIndicator` makes it visible with no timer, and only the
  `lock_released` event hides it.

All READ. The indicator was also exercised in the browser on an item page with
a test name, and it was still visible after 5 seconds. So no redirect toast is
sticky, and the contract has no duration parameter.

### Kind

Follows the global handler in `toast.js`: permission and session problems are
warning, request and server failures are error. A problem the user can fix is
warning, as in track 1's first exception.

| Kind | Caller | Message |
|---|---|---|
| error | `checkout.py:86` | Item not found |
| error | `item_detail.py:202` | Item not found |
| error | `item_detail.py:287` | Item not found |
| error | `item_detail.py:392` | Update failed |
| error | `item_detail.py:416` | Item not found |
| error | `item_detail.py:457` | Receipt upload failed |
| warning | `checkout.py:81` | Not permitted |
| warning | `checkout.py:90` | Already checked out |
| warning | `checkout.py:97` | Item is decommissioned |
| warning | `checkout.py:104` | Pick a recipient |
| warning | `checkout.py:175` | Not permitted |
| warning | `checkout.py:184` | Checkout not found or already returned |
| warning | `item_detail.py:209` | This item is being edited by (holder) |
| warning | `item_detail.py:298` | This item is being edited by (holder) |
| warning | `receipts.py:212` | No file selected |
| warning | `receipts.py:216` | Unsupported file type |
| success | `checkout.py:131` | Checked out |
| success | `checkout.py:207` | Checked in |
| success | `intake.py:365` | Item created successfully |
| success | `item_detail.py:396` | Item updated successfully |
| success | `item_detail.py:461` | Receipt added successfully |
| success | `receipts.py:248` | Receipt file replaced |
| success | `site_detail.html:474` | Pinned at (coordinates) |
| success | `vendors.html:368` | Created (count) new profiles |

6 error, 10 warning, 8 success. Kinds were assigned from the message wording.
Re-read each branch when commit 2 edits it.

### Spoofing, accepted

A link can already put any text in a green toast. With `toast_type` it can be
red or amber too. Accepted, because the message stays escaped (`toast.js`
passes it through `escapeHtml`), the type is checked against the four names,
and the app sits behind login. A logged-out visitor lands on `/login` with the
query string gone (observed).

## Commits

### Commit 1: the handler, this spec, one pointer

The handler reads `toast_type`, checks it against the four names, calls the
matching `SxToast` method, stops decoding twice, and strips both parameters.
`DESIGN_SYSTEM.md`'s Toast row points here. Backward compatible: all 24
callers keep working unchanged, and the 8 successes stay correct.

### Commit 2: the callers

One Python helper builds every redirect toast. It encodes the message, adds
`toast_type` when the kind is not success, and always returns 303. The 22
route callers switch to it. The helper is `toast_redirect` in
`app/toast_redirect.py`, tested by `tests/test_toast_redirect.py`.
The 2 JavaScript callers are successes and need no change.

Commit 2 also closes:

- **N15.** `item_detail.py:202`, `:287` and `:416` pass no `status_code`, so
  the framework default applies (307 in Starlette, not read in this repo).
  `:287` and `:416` sit in POST handlers, where a 307 would repeat the POST
  against `/inventory/`.
- **The holder name.** `item_detail.py:209` and `:298` join the name into the
  URL with only spaces replaced. A name containing `&`, `#` or `%` would cut the
  message short or make today's handler throw.

## Gates

### Commit 1, Chrome MCP

On any page that extends `base.html`. Prime the console with a probe, clear,
reload, then read. Read toast text and the `--flc-*` colour from the toast
container's children.

| URL | Must show | Address bar after | Fails before commit 1 |
|---|---|---|---|
| `?toast=Checked+in` | "Checked in", green | query gone | no, control |
| `?toast=50%25%20off` | "50% off", green | query gone | yes, nothing shown |
| `?toast=1%2B1` | "1+1", green | query gone | yes, shows "1 1" |
| `?toast=Oops&toast_type=error` | "Oops", red | query gone | yes, green |
| `?toast=Hi&toast_type=warning` | "Hi", amber | query gone | yes, green |
| `?toast=Hi&toast_type=bogus` | "Hi", green | query gone | no, proves the check |
| `?toast=%3Cb%3Ex%3C%2Fb%3E&toast_type=info` | literal `<b>x</b>`, blue | query gone | no, proves escaping |
| `?toast=Hi&keep=1` | "Hi", green | `?keep=1` stays | no, proves other parameters survive |

Console clean after the tracked reload.

### Commit 2, unit test on the helper

A message containing `&`, `%`, `#` and `+` comes back exact from the
`Location` header after one decode. The status is 303. A kind outside the four
is refused. The suite total rises by exactly the number of tests added, since
no route is added.

## Out of scope, recorded

- **N16.** `locks.js` `_showLockIndicator` writes `displayName` into
  `innerHTML` without escaping. Who can set `display_name` is UNREAD.
- The item routes block on any lock held by another user and always say
  "being edited by", while the indicator may say "is viewing". Whether
  `get_lock` returns viewing-level locks is UNREAD.
- `item_decommission` and `item_reactivate` in `item_detail.py` do not use
  `?toast=`. How they report results is UNREAD.

## After ratification

The anchors above stay pinned at d5f9cfb. Later changes to the callers are
recorded here instead of edited into the tables. Anchors in this section are
at the N19 commit.

- **N17 (eeb9cc4)** added three warning callers on viewer form posts:
  `intake.py:260`, `item_detail.py:278` and `:400`.
- **N19** changed the message on all five permission warnings from
  "Not permitted" to "Not permitted: editor access required":
  `checkout.py:82`, `:166`, `intake.py:260`, `item_detail.py:278`, `:400`.
- **N16 (fe3f118)** closed the first item under Out of scope: only user
  managers can set `display_name`, and `_showLockIndicator` and `showConflict`
  in `locks.js` now insert the name with `textContent`.
- **Logout CSRF (board N10, rev 57)** added one warning caller outside
  `app/routes/`. The 403 handler in `app/main.py` catches `CsrfError` from a
  browser form post and redirects to the referring page inside the app (the
  dashboard otherwise) with "This page was out of date, so nothing was
  changed. Please try again." It covers `POST /logout` and
  `POST /receipts/{receipt_id}/replace-file`. Tested by
  `tests/test_csrf_stale.py`.
