# Delete request queue

    STATUS:   RATIFIED 2026-09-23 by Jus
    Written:  2026-09-23
    Board:    BACKLOG-TRIAGE.md item 41
    Taken at: HEAD 8097422, branch main
    Scope:    Delete requests for items (item_schema.items) and vendor
              profiles (vendor_profiles). Nothing else can be requested.
    Anchors:  Every file:line below is at 8097422 and ages from the first
              commit that touches the file. Re-read before editing.

## Why

Editors cannot delete anything. Vendors have an admin-only delete
(`vendors.py:234`, 644c4db). Items have no delete at all, only decommission
(`item_detail.py:478`), and the decommission spec says decommission is
not deletion. Mistaken and duplicate records have no way out except a
direct database edit. Jus, 2026-09-22: editors request a delete, admins
act on it from a queue.

## Rulings (Jus, 2026-09-23)

1. **Targets.** Items and vendor profiles.
2. **Who requests.** Editor tier and above.
3. **Where the queue lives.** An admin page, plus an admin-only badge. The
   badge is mocked in the browser before it is built (slice C).
4. **A pending request locks its target.** Every change to the target is
   refused while the request is pending, for every role, admins included.
   Admins change a locked target only by approving or rejecting.
5. **Withdraw.** The requester may withdraw their own pending request.
6. **Reason.** Required, free text, not empty.
7. **Rejection is one way.** The requester is told nothing. The target
   simply stops being locked. The rejection is written to the audit log.
8. **What an approved item delete does.** A hard delete, and only for a
   clean item (defined below). An item with history is decommissioned
   instead. The request is refused at request time with a message that
   says so.
9. **The CSV import map.** On an approved item delete the item's
   `item_schema.csv_import_map` row is kept, its `item_id` set to NULL and
   its `action` set to `deleted_by_request`. Migration 067 skips any
   `csv_id` already in the map whatever its action
   (`067_import_casey_inventory_csv.py:263`, READ), so a re-run does not
   bring the item back.

## What "clean" means for an item

Read from the live catalog, 2026-09-23. An item is clean when it has zero
rows in every one of these:

| Table | Column | On delete | Why it must be empty |
|---|---|---|---|
| item_schema.checkouts | item_id | no action | the delete would fail |
| item_schema.component_history | item_id | no action | the delete would fail |
| item_schema.component_history | parent_item_id | no action | the delete would fail |
| item_schema.receipt_items | item_id | no action | the delete would fail |
| item_schema.maintenance_log | item_id | no action | the delete would fail |
| item_schema.intake_photos | item_id | no action | the delete would fail |
| public.device_provisioning | item_id | set null | order history would lose its unit silently |
| public.received_devices | item_id | set null | receiving history would lose its unit silently |
| public.unit_photo_items | item_id | cascade | photo links would vanish silently |

`item_schema.csv_import_map.item_id` has no foreign key and is handled by
ruling 9, not by the clean check.

At 8097422, 7 of 548 items are clean by every table above including the
import map, and 525 are clean once the import map is set aside (READ).
Links in use: component history 8 child and 8 parent, device
provisioning 6, checkouts 2, receipt items 1, the rest 0.

The clean check runs twice: when the request is filed, and again inside the
approve transaction. A link can still appear between the two through a
route the lock does not cover (see Open reads), and the second check is
what stops the delete in that case.

## Vendors

Both references to `vendor_profiles.id` are ON DELETE SET NULL
(`items.vendor_id`, `receipts.vendor_id`, READ from the catalog), and the
existing delete keeps each row's vendor text (`vendors.py:241-242`). No
clean check. An approved vendor request runs the same delete the admin
button runs today. The admin button stays as it is.

## Data model: migration 078

One new table, `public.delete_requests`:

| Column | Type | Notes |
|---|---|---|
| id | serial | primary key |
| target_table | varchar(32) | `items` or `vendor_profiles`, CHECK constraint |
| target_id | integer | no foreign key: the target is gone after approval |
| target_label | varchar(256) | name and serial (item) or name (vendor) at request time, so the history reads after the target is deleted |
| reason | text | NOT NULL, CHECK length(trim(reason)) > 0 |
| status | varchar(16) | `pending`, `approved`, `rejected`, `withdrawn`, CHECK constraint |
| requested_by | integer | FK users.id ON DELETE SET NULL |
| requested_at | timestamptz | default now() |
| decided_by | integer | FK users.id ON DELETE SET NULL |
| decided_at | timestamptz | null while pending |

A partial unique index on `(target_table, target_id) WHERE status =
'pending'` allows one pending request per target.

Both user foreign keys are SET NULL on purpose. Eleven tables already
reference `users.id` with no ON DELETE clause, which is why deleting a user
through a raw DELETE fails (board, `rowan`). This table does not add a
twelfth.

House shape of 075 to 077: `engine.begin()`, prints before and after,
idempotent per statement, proven on a local Postgres through fresh, rerun,
half state and bad state before transport.

## Routes

| Method and path | Gate | Does |
|---|---|---|
| POST /api/delete-requests | require_editor | file a request: target, reason. 409 if one is pending, 409 with the blocking links if the item is not clean |
| POST /api/delete-requests/{id}/withdraw | require_editor, requester only in body | pending to withdrawn |
| POST /api/delete-requests/{id}/approve | require_admin | clean check again, delete the target, pending to approved, one transaction |
| POST /api/delete-requests/{id}/reject | require_admin | pending to rejected |
| GET /admin/delete-requests | require_admin | the queue page |

The census grows by the rows these routes generate, and
`docs/ENDPOINT_AUTH_CENSUS.md` gains five rows. Withdraw goes in the
census's in-body list with its reason. The suite total is predicted at
build time from the census parametrisation, not guessed here.

Every action writes one audit row through `log_event`:
`delete_requested`, `delete_request_withdrawn`, `delete_request_rejected`,
`delete_request_approved`, plus the existing `vendor_deleted` for a vendor
and a new `item_deleted` for an item. Target table and id ride on each row.

## The lock

One helper, in a new module, answers whether a target has a pending
request. Every route that changes an existing item or vendor calls it before
it writes, and refuses with 409 JSON or a warning toast, whichever that
route already uses for its errors. The message names no one:
"A delete request is pending for this record. It cannot be changed until an
admin decides."

A structural test lists the guarded routes and fails if any listed handler
stops calling the helper, in the manner of `tests/test_auth_census.py`.
A new write route that touches items or vendors has to be added to the list
deliberately, which is the point.

Candidate routes, from the path names at 8097422 (READ as a list, each
handler UNREAD): the item page (edit, receipt, decommission, reactivate),
inventory quick view and bulk, triage fix and bulk, checkout and checkin
single and bulk, containment install, uninstall and move, order item
assignment, receiving device, photo linking, `bulk.py` status and assign,
vendor edit and delete. About 24. Slice B reads every handler before it is
listed; a route that turns out not to write an existing item or vendor is
dropped with the reason recorded.

## Admin page and badge

`/admin/delete-requests`: pending requests first, oldest at the top, each
with target (linked while it exists), label, requester, reason, age, and
Approve and Reject. Below, the last 50 decided requests, read only. Approve
on an item that has become unclean shows the blocking links and leaves the
request pending.

Badge: an admin-only count of pending requests on the admin nav link,
computed in `sidebar_cache.get_sidebar_counts` beside `pending_count`
(`sidebar_cache.py:65`), same 15 second cache, invalidated on every
request write. Mocked first: slice C starts by injecting the badge into
the live page in the browser only, and is built only after Jus has seen it.

## Requester side

The item page and the vendor list get a Request delete control for editors
and above, opening a small form for the reason. While a request is pending
the target shows a notice, and the requester sees a Withdraw control. An
item that is not clean shows the control disabled with the reason: it has
history, decommission it instead.

## Slices

- **A.** Migration 078, the model, the five routes, the audit rows, the
  admin page, the requester controls. No lock yet: a pending request is
  visible but not enforced.
- **B.** The lock helper, every guarded route, the structural test.
- **C.** The badge, after the mock.

A lands first because B's test needs something to guard, and C needs
requests to count.

## Gates

Per slice: the migration proven on a local Postgres, the script harness,
the suite with a predicted total, the diff matched by sha, four HEADs. In
the browser, as an editor and as an admin:

- A: file a request with a blank reason (refused), file one on an unclean
  item (refused, links named), file one on a clean test item, see it on the
  admin page, withdraw it, file again, reject it, file again, approve it:
  the item is gone, its import map row reads `deleted_by_request` with a
  NULL item id, and five audit rows exist. The same for a vendor created
  for the test.
- B: with a pending request, every guarded route refuses, admin included;
  after reject, the same routes work.
- C: the badge count matches the pending rows, as admin only.

Every test record is created for the test and prefixed `contract-test`, so
no real item or vendor is touched.

## Open reads

1. Each of the ~24 candidate handlers, for slice B.
2. `bulk.py` status and assign: which tables they write.
3. Writes to items outside `app/routes/`, if any (services, scripts, the
   Slack bot). A write the lock cannot see is covered only by the second
   clean check at approve time.
4. The admin nav markup where the badge goes.
5. The confirm convention for Approve and Reject: the native dialogs
   track owns it (`native-dialogs-track-2-dialogs.md`). Read before
   slice A builds the page.

## Out of scope

- Requests for any other record type.
- Telling the requester the outcome.
- Bulk requests.
- Undo after approval. A deleted item is gone; the audit row and the
  `target_label` are what remain.
