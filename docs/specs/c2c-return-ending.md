# C2C Return-as-Ending + Assign Rename

Status: DECIDED (Chat), building. Baseline `c46aa7f`.
Scope: C2C (Camera-2-Cloud) surface only. Edge/cloud boxes inherit this
vocabulary and lifecycle when their assign flow is built (future).

## Problem

A returned pilot/loan camera is recorded as back (`returned_date` set) but is
**not** freed for reuse: it stays out of `available_items` and is blocked from
re-assignment. "Return" currently means "recorded as returned", not "back in
inventory, ready to assign again". This slice makes **return = ending**: a
returned camera goes back to inventory and can be assigned to a new order,
re-certified fresh, while the original order keeps its history.

## Grounded facts (already read; do not re-derive)

- **Cert is keyed on `device_provisioning_id`, never `item_id`** (`c2c.py`:
  `C2CCertification.device_provisioning_id == DeviceProvisioning.id`; the certify
  handler upserts by `device_provisioning_id`). So a new provisioning row gets a
  fresh blank cert automatically. **No cert-model change is needed** for
  re-certification — it falls out of the existing option-D grain.
- **Two barriers currently keep a returned cam out of inventory:**
  1. `available_items` / `linked_item_ids` (`_c2c_board_data`) nets on
     "has ANY provisioning row with `item_id`" — no `returned_date`/`is_complete`
     filter.
  2. Acquire dedup (`c2c_acquire`) nets on `is_complete = False`.
- **"acquire" as camera-assignment is C2C-only.** The other `.acquire()` hits are
  `window._lockManager.acquire()` (a client-side edit-lock concurrency util) in
  `item_detail` / `warranty` / `disposal` / `site_detail` / `trials` — **unrelated,
  must not be touched**.

## Availability state model (DECIDED)

A C2C camera's assignability is determined by its provisioning rows. Two signals:
`returned_date` (physically back?) and `is_complete` (order closed?).

| `returned_date` | `is_complete` | state | assignable? |
|---|---|---|---|
| NULL | False | out in the field | NO (in use) |
| set | False | returned | **YES** |
| NULL | True | ANOMALY (complete, not back) | NO (blocked) |
| set | True | returned + closed | YES |

**Rule:** a camera is available **only when it has no provisioning row with
`returned_date IS NULL`.** The `NULL + is_complete=True` anomaly is prevented at
the source (below), so it can never exist going forward.

## Change 1 — free a returned cam (two filters, key on `returned_date IS NULL`)

Both key on `returned_date IS NULL` = "not physically back":

1. **`available_items` / `linked_item_ids`** (`_c2c_board_data`): a camera is
   excluded from availability only if it has a provisioning row with
   `returned_date IS NULL`. So `linked_item_ids` becomes the set of `item_id`s
   that have **at least one row still out** (`returned_date IS NULL`). A camera
   whose rows are all returned — or that has no rows — is available.
2. **Assign dedup** (`c2c_acquire`): block assigning a camera that has **any** row
   with `returned_date IS NULL`. This replaces the current `is_complete=False`-only
   check.

`is_complete` is **not** set to `True` on return — C2C rows keep
`is_complete=False` forever (option D). Return sets `returned_date` only (already
the case; unchanged).

## Change 2 — anomaly prevention at source

Block setting `is_complete=True` on a C2C provisioning row (`item_id` set /
`device_table="items"`) that has **no** `returned_date`. This keeps the
`NULL + is_complete=True` state (which would silently make a still-out camera
un-assignable *and* un-freeable) from ever being created.

C2C's own handlers never set `is_complete=True` (acquire defaults it False;
certify and both mark-returned endpoints explicitly leave it untouched). The
guard is therefore placed defensively wherever `is_complete=True` could be set on
a row a C2C provisioning could reach (verified during the build).

## Change 3 — re-assign = same flow, fresh row, fresh cert (no new code)

A freed (returned) camera simply reappears in `available_items`. Assigning it runs
the **existing** acquire path → mints a new provisioning row (new `item_id` link,
new order) → a fresh blank cert follows the new row. The old row + old cert persist
as history. Multiple provisioning rows accumulate per `item_id` over the camera's
life (the per-serial history is a later slice).

## Invariant — shortfall / old-order preservation

The old (returned) provisioning row keeps its `item_id`, `customer_order_id`, and
`returned_date`. The original pilot order still shows the camera as historically
acquired-then-returned; **returning a camera does not re-open the original order's
shortfall.** This is already the behavior (return does not delete or re-link the
old row); the build confirms the rollup still counts a returned row toward the old
order's acquired count.

## Change 4 — Assign rename (DISPLAY TEXT ONLY)

Rename user-facing **display text** from "Acquire" to "Assign" on the C2C surface:

- `c2c.html`: "+ Acquire camera" → "+ Assign camera"; per-order "Acquire" →
  "Assign"; panel heading/labels; any visible copy; JS-built button labels.
- Audit-log text that is user-facing.
- **One label everywhere: just "Assign".** No context-aware "Reassign" this slice
  (revisited later).

**Do NOT rename code identifiers:** `openC2cAcquire`, `c2cAcquireSubmit`,
`c2c_acquire`, the `/fulfillment/c2c/acquire` route, `c2c-acquire-*` /
`c2c-acq-*` CSS classes and element ids. Churn + risk, no user benefit.

**Do NOT touch `_lockManager.acquire()`** anywhere (unrelated concept).

## Scope boundaries

- C2C only. Edge/cloud boxes have no assign flow yet; they inherit Assign/Reassign
  vocabulary when built.
- Behavior + rename bundled in one build (owner's call), kept as clean separable
  diffs (Change 1+2 = return-as-ending behavior; Change 4 = rename).

## Verification (browser gate, Chat)

1. Mark a still-out cam returned → it reappears in `available_items` (the assign
   picker) and can be assigned to a **new** order → new provisioning row + fresh
   (pending) cert; the old order still shows it acquired-then-returned.
2. A still-out (not returned) cam does **not** appear in available / cannot be
   assigned.
3. Anomaly guard: attempting to set `is_complete=True` on a C2C row with no
   `returned_date` is blocked.
4. All "Acquire" display text now reads "Assign"; `_lockManager` untouched;
   console clean; no regression to the C2C board, fulfillment board, or
   pilots-due-back page.
5. DB reads confirm: freed cam gets a **new** provisioning row on re-assign; old
   row intact (`item_id` / `customer_order_id` / `returned_date` preserved).

## Do NOT

- Change the cert model (fresh cert already follows a new row).
- Set `is_complete=True` on C2C return.
- Rename code identifiers or `_lockManager`.
- Delete or re-link the old provisioning row on return.
- Chain the two remote pushes.
