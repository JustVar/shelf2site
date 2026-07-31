# Audit log scoping, discovery

Status: SUPERSEDED IN PART by `d4a93a6`. Read the "What shipped" section first;
several findings below are closed and the measurements are historical.

## What shipped

**`d4a93a6`, audit log restricted to admin tier, area scoping removed.**

`has_audit_access` became `is_admin_tier or can_view_audit_log == 'grant'`.
Sub admin roles removed, inherited department grants no longer count.
`PERM_AUDIT_TABLES` and the whole scoping block deleted. Net minus 32 lines.

Closed by it: the null target bypass, the unconditional `add("users")`, the
`PERM_AUDIT_TABLES` misalignment, the dead `if allowed_tables:` guard, both
stale docstrings, and Defect B, which ceased to exist rather than being fixed
since no scoped viewers remain.

Verified live: `test_warranty_adm` went from 166 rows to the access denied page,
with the nav link and activity panel link both gone in lockstep. Admin tier
still sees every row across all 17 target categories.

**`253d6da`, activity panel audit link.** Pointed at `/audit-log`, which no
route serves. Now `/admin/audit`.

**Still true below:** the measurements, the free text `target_table` finding,
the 107 business record rows, the roster exposure, and the zero test coverage.

**Correction to this document.** It called the 500 row cap a SILENT truncation.
That was wrong and was written from the route without reading the template. The
template renders an unconditional "Showing most recent 500 entries" paragraph,
so the page is not silent, it asserts truncation that is not happening. At 272
rows the notice is simply false, and it stays false when a filter narrows the
view to three rows. See the UI findings section.

Traced end to end this session: route gate, property, permission resolution,
table mapping, every call site, and the live data. Everything below is read from
code or measured from the database unless explicitly marked as inference.

## How it actually works

```
require_audit_viewer -> user.has_audit_access
    = role in ADMIN_LEVEL_ROLES + (warranty_admin, trials_admin, procurement_admin)
      OR _resolve_perm("can_view_audit_log")

then, inside the route:
    is_full_admin      = user.role in ADMIN_LEVEL_ROLES
    has_explicit_audit = user.can_view_audit_log == 'grant'   # RAW column, not resolved

    if neither:
        allowed_tables = tables from PERM_AUDIT_TABLES where _resolve_perm(col)
        allowed_tables.add("users")                            # unconditional
        filter: target_table IN allowed_tables OR target_table IS NULL

entries = query.limit(500).all()
```

Note the asymmetry that is clearly deliberate: `has_audit_access` uses the
RESOLVED permission, so a department grant opens the page. `has_explicit_audit`
uses the RAW column, so a department grant does NOT bypass scoping. Someone
thought about this. That makes the rest of the findings more likely to be drift
than design.

## The arithmetic

262 audit rows total. Measured, not estimated.

| Target table | Rows | Reachable by a scoped viewer? |
|---|---|---|
| (null) | 121 | ALWAYS, via the `IS NULL` clause |
| users | 34 | ALWAYS, via the unconditional add |
| customer_orders | 26 | never, unmapped |
| checkouts | 19 | never, unmapped |
| c2c_certification | 12 | never, unmapped |
| map_visibility | 10 | never, unmapped |
| device_provisioning | 7 | only with the provisioning flag |
| item | 6 | never, not a real table name |
| edge_box | 5 | never, not a real table name |
| sites | 4 | only with `can_manage_sites` |
| c2c_certification_files | 4 | never, unmapped |
| receipts | 4 | never, unmapped |
| part_numbers | 3 | never, unmapped |
| oem_purchase_orders | 2 | never, unmapped |
| pending_devices | 2 | never, unmapped |
| items | 2 | never, not a real table name |
| departments | 1 | never, unmapped |

**155 of 262 rows (59%) are visible to every audit viewer regardless of
permissions. 11 rows (4%) are actually governed by permission flags. 96 rows
(37%) are unreachable by any non-full-admin.**

Confirmed live: Warranty Admin saw exactly 166 rows in the browser
(121 + 34 + 7 + 4). The DB grouping and the rendered page agree to the row, and
the 500 cap was not binding, so that is the complete filtered set.

## Who this applies to

`can_view_audit_log` is `grant` at the department level on ALL FIVE original
departments: Product Management, Support, QA, Hardware, Sales Engineering. Only
Management (id 138, created much later) blocks it.

Every editor and viewer sits at `inherit`. So **13 of 15 editor and viewer
accounts have audit access**; only the two departmentless accounts do not.

Each of those 13 sees all 121 null-target rows and all 34 users rows. That
includes `role_changed`, `user_department_changed` x22, `user_created`,
`user_updated`, password resets, 66 logins, 29 logouts, and 17 failed login
attempts, across every account in the system.

Their own domain events are the only thing scoping restricts.

## Findings

Ordered by how much they matter, not by how easy they are.

### A. Null target_table bypasses scoping entirely

`target_table IS NULL` passes unconditionally. 121 rows, 46% of the log. Every
login, logout, failed login and password change in the system is visible to
every audit viewer.

Whether that is wrong depends on intent. It may be reasonable for staff to see
login activity. It is certainly not what the RBAC test plan asserts.

### B. Unconditional `allowed_tables.add("users")`

34 rows. The comment above it reads "Always include user-related events for
self" and the filter has NO `user_id` or `target_id` clause. The code does not
do what its own comment says.

The comment tells us the intent: each user sees their OWN user events. The fix
is the clause the comment implies.

### C. PERM_AUDIT_TABLES is misaligned with reality

Of its nine mapped table names:

| Mapped name | Rows in data | Written by any call site? |
|---|---|---|
| sites | 4 | yes |
| device_provisioning | 7 | yes |
| device_warranties | 0 | yes, literal exists |
| warranty_claims | 0 | yes, literal exists |
| vendor_trials | 0 | yes, literal exists |
| device_assignments | 0 | yes, literal exists |
| device_dispositions | 0 | yes, literal exists |
| **edge_boxes** | **0** | **NO literal anywhere** |
| **procurement** | **0** | **NO literal anywhere** |

`procurement` is the residue of the removed procurement page. Both financial
permissions map to it, so they grant access to a table name nothing writes. The
rows a financial person would want are logged under `receipts`,
`oem_purchase_orders`, `customer_orders`, `part_numbers` and `vendor_profiles`,
none of which are mapped. Same residue as the Receipts nav link still using
`fl_icon('procurement')`.

Meanwhile roughly 16 table names ARE written and appear in no permission's list.

**The fulfillment case is the concrete one.** QA are viewers for their
department who also do fulfillment work, status updates and document uploads.
That logs to `customer_orders` (26 rows) and `checkouts` (19 rows). Neither is
mapped to any permission. The people doing the work cannot see the audit trail
of their own work, while seeing every login and role change in the company.

### D. target_table is unvalidated free text

`log_event(..., target_table: Optional[str] = None, ...)`. No enum, no
validation, no reference to any registry. Five dynamic call sites pass
variables:

| Site | Variable | Provenance |
|---|---|---|
| `creds.py:48` | `table_name` | unread |
| `bulk.py:104` | `item["table_name"]` | unread |
| **`map.py:522`** | **`kind`** | **`body.get("kind")`, client supplied** |
| `pending.py:121` | `target_table` | unread |
| `spreadsheet_sync.py:283, 311` | `change.table` | unread |

`map.py:481` reads `kind` from the request body, validates it only against
`"edge_box"` and `"item"` (the API discriminators used in the map GeoJSON), and
line 522 passes it straight through as `target_table`. That is the source of all
5 `edge_box` rows and 6 of the 8 `item`/`items` rows.

There is no single naming authority. `TABLE_MODELS` is the 22 device tables and
does NOT contain `users`, `sites`, `device_provisioning`, `customer_orders` or
`checkouts`, so it cannot serve as the registry. Free text on the write side, a
hand maintained map on the read side, nothing covering both.

**Failure direction is safe.** An unrecognised `target_table` makes rows LESS
visible, never more. This is a completeness problem in the audit trail, not an
exposure one. Different severity from A and B; do not merge them.

### Smaller items

- **Dead guard.** `if allowed_tables:` can never be false, because
  `add("users")` runs immediately above it. Reads as though an empty permission
  set means unfiltered; the truth is the opposite.
- **Docstring misdescribes shipped behaviour.** It still says users with
  explicit `can_view_audit_log=True` see everything, describing the identity
  comparison that `0c0ac31` replaced with `== 'grant'`. Its second sentence,
  that non-admins see only entries for their permitted areas, is contradicted by
  the 155 of 262 measurement.
- **500 row silent cap.** `query.limit(500).all()` with no pagination and no
  indication of truncation. Not binding at 262 rows. An audit log that silently
  omits entries is a poor failure mode for the one surface whose job is
  completeness.
- **Full roster exposure.** `all_users` is queried unfiltered and passed to the
  template for the filter dropdown, so every audit viewer can enumerate every
  account. `/admin/users` itself requires `require_user_manager`. Asymmetry
  rather than a hole, and the same shape as finding B.
- **Defect B (role does not imply domain tables).** Test fixtures only, and
  `vendor_trials` has zero rows, so even the fix would surface nothing. Real in
  code, unobservable in data. Lowest priority of anything here.

## What is NOT wrong

Worth stating so the list is not read as alarming.

- Nothing here is reachable without authentication.
- The unvalidated column fails closed, not open.
- The raw versus resolved asymmetry in the two audit gates is deliberate and
  correct.
- No production user is currently blocked from anything by any of this.
- The five departments granting `can_view_audit_log` may well be intended.

## UI findings, added after the gate work

The audit page template is 111 lines and nothing tests it. Three defects, none
of them access control, all of them affecting whether the page is usable for
watching the application.

### Event type filter has drifted badly

40 distinct event types in the data. The dropdown hardcodes 13. The overlap is
FOUR.

| | Count |
|---|---|
| Dropdown options matching zero rows | 9 of 13 |
| Event types with no dropdown option | 36 of 40 |
| Rows reachable through the dropdown | 121 of 272, 44% |

Dead options: `device_added`, `device_edited`, `device_deleted`,
`device_approved`, `credential_viewed`, `oui_added`, `oui_removed`,
`scan_triggered`, `scan_completed`. Several correspond to features that exist,
so they may log under different strings now; unverified.

Unfilterable includes every `c2c_*` event, all order and part number activity,
`role_changed`, and `user_department_changed` at 22 rows. Those last two are
exactly the application specific events the audit log now exists to show.

**This is the item that most undermines the stated purpose.** The 500 cap does
not bind at 272 rows; the filter fails today.

### Count notice is unconditional and wrong

Lines 92 to 94 are a plain `<p>` with no condition. Always reads "Showing most
recent 500 entries" regardless of what is displayed.

### Roster in the user filter is unfiltered

`all_users` queries every `User` row and renders `display_name` for each.
Narrowed by `d4a93a6` to admin tier only, but still every account rather than
the ones that appear in the log.

### Vestigial block

`admin_audit.html:4` declares `{% block nav_admin_audit %}active{% endblock %}`.
`base.html` never defines that block, so Jinja ignores it. A fossil of an
earlier nav design; the current one marks active state by URL test. Harmless.
Other templates may carry the same fossil; one `grep -rn "block nav_"` would
tell, not run.

## Decided, specced separately

**Audit page UI track.** Derive the event type options from the data with
`SELECT DISTINCT event_type`, grouped by prefix into `optgroup`s. Derive the
user list the same way, from users who actually appear in the log. Make the
count notice conditional and accurate.

Chosen over refreshing the hardcoded list, because a hand maintained list drifts
again with every new `log_event` call site. Same principle as Track C applied to
a dropdown instead of a tuple. This session found the identical drift class in
role tuples, audit table names, and now event types.

Pagination and the 500 cap are deliberately NOT in that track. The cap does not
bind at 272 rows, the notice fix makes the page honest about what it shows, and
pagination is a larger change that deserves its own track when the log is big
enough to need it.

## Settled principle, what belongs in the audit log

**Application specific items belong in the audit log. Business history belongs
on the domain surfaces that own it.**

Two clauses, not three.

### Clause 3 was added and then dropped

An earlier version added: "compliance and certification events belong in the
audit log even where their target is a business object." It was **dropped**, and
the reason matters.

That clause was decided on a false premise. This document asserted that the
fulfillment surface produced no audit trail, inferring it from the absence of
`log_event` calls in `fulfillment.py`. Both certification subsystems in fact
carry ratified trails:

- **Build certification.** `docs/specs/build-certification.md`, status APPROVED
  and implemented, opens by describing "a per-device build certification system
  with an append-only audit trail keyed to the OEM serial number," and its schema
  table names `oem_serial` the "audit spine, snapshotted at cert time." Every
  certification including failures is retained. It has `certified_by`,
  `co_certified_by`, `cancelled_by`, append-only rows, and a history endpoint at
  `fulfillment.py:2165`.
- **Installation certification.** `docs/specs/installation-certification.md`,
  status APPROVED, ratifies one certification per deployment record, with a
  re-install handled as a NEW deployment record. The history lives across
  deployment records by design.

So the question clause 3 was meant to answer was already answered, twice, by
ratified design. Adding `log_event` calls beside those trails would be a second
mechanism for a solved problem, which is exactly the reasoning that produced
`92bc60d` and had to be reversed.

**The counter argument, recorded because it is real but was judged thin.**
`audit_log` carries `user_id`, an IP address and a server timestamp; the
certification tables carry `certified_by` as a free text display name, which is
not reliably joinable to a user. Those are genuinely different records. The
judgement was that the distinction does not outweigh running two trails for one
subsystem.

Consequences:

- The 107 business record rows stay where they are, per the standing decision.
- **`oem_purchase_orders` stays under clause 2**, and needs no audit trail of
  its own. The PO is a REFERENCE NUMBER carried on a certification, not a tracked
  order.
- The build certification audit parity track is DEAD. See below.

**Closed.** `oem_purchase_orders` is supplier procurement and is unrelated to the
fulfillment PO text field. Both exist, neither is being deprecated.

## DEAD track, build certification audit parity

**Requested: replicate the C2C certification audit events for Edge Box and Cloud
Box certifications. This track is dead and should not be built.**

The request was made on the strength of this document's claim that build
certification produced no audit trail. It produces a ratified one, described in
`docs/specs/build-certification.md` as an append-only audit trail keyed to the
OEM serial. The zero `log_event` calls in `fulfillment.py` are the design
working, not a gap.

What remains true from that discovery, kept because it is grounded:

| Surface | Domain tables | `log_event` calls | Audit rows |
|---|---|---|---|
| Build certification | `build_certification`, `build_certification_files` | 0 | 0 |
| C2C certification | `c2c_certification`, `c2c_certification_files` | 10 | 24 |

C2C writes to both its domain tables and the audit log. Under the two clause
principle that duplication is arguably wrong, but it is shipped, harmless, and
NOT worth a removal track.

### Four attribution shapes, why a uniform migration would be wrong

- The nine `c2c_*` event types stay, and Edge Box and Cloud Box certification
  should log equivalently. See the build certification parity track.
- It does NOT reopen the other 107 business record rows. Orders, checkouts, map
  visibility, receipts and part numbers are not compliance records. They stay
  where they are, per the decision to leave them.
- **`oem_purchase_orders` stays under clause 2, and needs no audit trail of its
  own.** The PO is a REFERENCE NUMBER carried on a certification, not a tracked
  order. Neither the order nor its line items are tracked. The compliance
  relevant fact is which PO number was recorded against which certification, and
  that is captured by the certification event, not by a PO entity event.
- Any future certification or compliance surface logs to `audit_log` by default
  rather than only to its own domain history.

**Closed.** `oem_purchase_orders` is supplier procurement and is unrelated to the
fulfillment PO text field. Both exist, neither is being deprecated. See the
parity track section.

## Decisions, all settled

Nothing open. All four were settled during this arc.

**Do the 107 business record rows belong in `audit_log`?**

The settled definition is that the audit log is for application specific items:
who is getting in, who is changing permissions, what is failing. Business record
history belongs on the domain surfaces that own it, the way build certification
already works, writing only to its own tables.

DECIDED: leave them. Migrating is not moving rows, it is changing `log_event`
call sites so business events write somewhere else, and that somewhere has to
exist per domain. Orders, checkouts, sites and receipts have no history surface
today. They cost nothing where they are, the log is admin only after `d4a93a6`,
so the definition stays aspirational until a domain surface actually needs
history, at which point that one domain moves and the rest stay.

Under that definition, 107 of 272 rows are in the wrong place: orders,
checkouts, C2C certifications, receipts, purchase orders, part numbers, sites,
provisioning, map visibility.

They are harmless where they are. But over time either those `log_event` calls
redirect to domain history, or the definition stays aspirational and the log
stays mixed. Worth deciding eventually, not urgent.

**Questions 1 through 3 in the original version of this document were settled
during the arc** and are recorded in the shipped section: null target and
`users` scoping both became moot when scoping was deleted, and
`PERM_AUDIT_TABLES` was deleted rather than realigned. The department grants
question also resolved itself, since inherited grants no longer convey access.

## Sequencing note

A and B change what a scoped viewer sees. The docstring and the RBAC test plan
section 9 both describe scoping. **Writing either before A and B are decided
means writing them twice.** The stale `=True` sentence in the docstring is the
exception; it has no dependency on those decisions.

Gates for any of this: the test suite is the right gate. 858 tests, 6 seconds,
green baseline at `7d95fba`. Plus a live browser check as a scoped identity,
since `testviewer` and `test_warranty_adm` credentials are both available and
the before-state is captured above.
