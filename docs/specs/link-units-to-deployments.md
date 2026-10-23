# Link provisioned units to deployment visits

Status: built. Commit 1 shipped the migration, the model column and the assign
endpoint; commit 2 shipped the picker feed, the modal and the tests. Amended
after the build; see the amendment log at the end of this file.

Owner note: WHAT and WHY only. Repo facts live in `CLAUDE.md`. Background on the fulfillment model is in
`fulfillment-pipeline-direction.md`.

## Why

Serial is the identifier tracked across inventory and deployments. Today it does
not reach deployments.

Read from the model: only two tables carry `deployment_record_id` -
`UnitPhoto` (line 403) and `InstallationCertification` (line 2100).
`DeviceProvisioning`, which holds the units, does NOT. Units hang off
`customer_order_id`; deployment records hang off `customer_order_id`. They are
siblings and are never joined.

Note, 2026-08-28: three tables carry it now. `DeviceProvisioning` gained the
column in commit 1 of this track. The count above records the state that made
this track necessary and is left as written.

So "which serials did this visit install" is an INFERENCE through the shared
order. It resolves correctly today only because each live order has exactly one
deployment record. `deployment_records.customer_order_id` has no uniqueness
constraint, so an order can have two visits, and the first time that happens
unit to visit attribution becomes undeterminable.

**Telling asymmetry:** `UnitPhoto` DOES carry `deployment_record_id`. The app
already models "this artifact belongs to this visit" for photographs and not for
the units themselves.

**The window is open now.** The three live deployments are test data, so there is
no legacy mapping to preserve and no careful backfill. Clean slate.

Note, 2026-08-28: five deployment records now exist (13, 14, 15, 16, 73). Still
all test data, so the rationale above is unchanged. Record 73 was created by the
item 15 verification gate and is deliberately retained.

## What the reads established

| Question | Answer |
|---|---|
| Where are deployment records created | `POST /fulfillment/deployments` at 818, constructing at 844. Three deployment endpoints total: create, status, certify. No update, no delete, no assignment. |
| What currently joins units to deployments | NOTHING. Every `customer_order_id` hit in the module is units grouped by order. The column is purely additive; there are no read paths to switch. |
| Units per deployment | 2 across all three live deployments. One visit covers multiple serials. |
| Can a deployment span certification subsystems | YES. Order 70 is a camera plus a generic item, neither on the build path. `fulfillment_type` is `build` for only 5 of 13 provisioning rows. |

Figures in this table are as read during discovery, before commit 1.

That last row matters for anything that tries to read unit state from
certification records: build cert covers under half the units.

## Scope, deliberately narrow

**Ship:** the column, an assign endpoint, and a picker modal.

**Defer:** cancellation, as its own track. See below.

### Why cancellation is not in this track

The stated model is that units are never unassigned. A unit pulled from an order
is CANCELLED with a reason, and a new build starts for the replacement.

That cancellation is a fact about the UNIT, not about the assignment. And
`DeviceProvisioning` cannot express it: `current_stage` holds five live values,
measured as `acquired` 8, `certified` 2, `hw_check` 1, `building` 1, `staged` 1.
Four are pipeline positions. `acquired` is NOT: it appears in none of
`DEFAULT_PROVISIONING_STAGES`, `STAGE_GROUPS`, `STAGE_LABELS` or
`STAGE_TO_GROUP`, and the string does not occur anywhere in `models.py`.
`provisioning.py:755` advances and `897` walks back, so movement is
bidirectional, but there is NO terminal cancelled state. There is no cancelled
flag and no replacement pointer.

Correction, 2026-08-28: `returned_date` was not considered by the analysis above
and it does carry return semantics. Row 249 went out on order 78, came back
2026-07-02, and was re-provisioned that same evening as row 254 on order 76.
That is the pull and replace flow this track was scoped around, already
happening in live data through a column the survey missed. Returned is not
necessarily the same concept as cancelled, but "no representation exists" is too
strong and the cancellation track should start from `returned_date` rather than
from nothing.

Caveat on the column: row 250 carries returned_date 2026-06-20 against
created_at 2026-07-02, returned twelve days before the row existed. Nothing
validates it.

So a unit pulled because a PO was cancelled has no representation today, with or
without deployment records. That gap exists independently of this track.

**An append only assignment table was considered and rejected.** Since units are
never unassigned, such a table would record one assignment event per unit and
then have nothing further to append. It adds structure without recording the
cancellation it was proposed to record.

**Nothing ships broken.** No unit has ever been swapped, and the deployments are
test data. Swaps become representable when the cancellation track lands, and that
track is better scoped around "a unit can be pulled from an order" than around
assignment.

## Changes

### 1. Migration

Next number from `ls migrations/ | sort | tail`, NOT assumed. Add
`deployment_record_id` to `device_provisioning`: integer, nullable,
`REFERENCES deployment_records(id) ON DELETE SET NULL`.

`SET NULL` rather than `CASCADE`: deleting a visit must not delete the units that
were on it. This mirrors `UnitPhoto`, which uses `SET NULL` for the same reason,
and differs deliberately from `InstallationCertification`, which cascades because
a certification without its visit is meaningless.

**No backfill.** The live deployments are test data. Every row starts NULL.

### 2. Model

Matching column on `DeviceProvisioning`.

### 3. Assign endpoint

New. `POST /fulfillment/deployments/{dep_id}/units` taking a list of provisioning
ids.

**Validation, and it must REJECT rather than silently filter:**

- Every provisioning id must belong to the SAME `customer_order_id` as the
  deployment record. A unit provisioned against order 71 must not be assignable
  to a visit for order 70. Reject with a specific message naming the offending
  id, so a mis-assignment surfaces instead of vanishing.
- A provisioning row already carrying a `deployment_record_id` is not
  reassignable. Reject.
- A provisioning row carrying a `returned_date` is not assignable. Reject,
  naming the offending id. Filtering it out of the feed is not sufficient on its
  own, because the feed shapes the UI while the endpoint is what a crafted post
  reaches.

**Nullable until assigned, then effectively fixed.** Units are provisioned before
visits are planned, so NULL is a normal state and not an error. There is NO
unassign endpoint, by design rather than omission.

### 4. Picker modal

Opened from the deployment card on the fulfillment board. Mock first in the
existing design language and review before building.

**The query the picker needs is the INVERSE of the assignment**, and it is easy
to specify only the forward direction and miss this:

```sql
-- assignable set for a deployment on order N
SELECT * FROM device_provisioning
WHERE customer_order_id = N
  AND deployment_record_id IS NULL
  AND returned_date IS NULL
```

The modal lists that set with checkboxes, shows the serial and current stage for
each, and posts the selected ids.

**Show already assigned units too, read only.** A picker that hides them makes it
impossible to see what the visit already covers, which is the question the user
usually has.

**Show returned units too, read only, for the same reason.** Silently dropping
them produces an empty picker with no explanation on an order whose units all
came back, which is strictly worse than showing two rows marked returned with
their dates. This is the same argument as the paragraph above, not a new one.

### 5. Picker feed endpoint

New. `GET /fulfillment/deployments/{dep_id}/units`, same path and same auth gate
as the assign POST. The modal cannot get the assignable set without it.

Fetched when the modal opens, NOT rendered at page load. A list built at load
goes stale, and since the assign endpoint validates the whole batch before
writing any of it, a unit taken elsewhere since load would 409 the entire
request and fail the good assignments alongside it.

Returns three lists. `available` is the inverse query above. `assigned` is the
same order filtered to this deployment. `returned` is the same order filtered to
rows carrying a `returned_date`, read only, showing the date. Units on a
DIFFERENT visit for the same order appear in none of the three.

A row that is both assigned and returned belongs in `assigned`. That state means
a unit came back after it was placed on a visit, which is the swap case this
track defers. No live row is in it. The cancellation track must define it rather
than leaving it to whichever filter runs first.

**Serial resolution is two paths, and `get_serial()` covers only one.**
`DeviceProvisioning` has no serial column. `item_id IS NOT NULL` resolves
through `item_schema.items.item_sn`; `item_id IS NULL` resolves through
`TABLE_MODELS[device_table]` and then `device_id`. The live split is 7 and 6
across the 13 rows, so both branches carry real data.

`get_serial()` must NOT be called on an `Item`. It checks `serial`,
`gpu_serial` and `part_number`, has no `item_sn` branch, and `Item` declares
`part_number` as a RELATIONSHIP, so `hasattr` is True and the third branch
fires. It returns an `ItemPartNumber` object where a string is expected, and
the failure is silent because an object renders as a repr rather than raising.

**Stage is suppressed when `stages` is an empty array**, which is the same
property the advance path keys on when it bails with "Current stage not found".
Do NOT key on `device_table = 'edge_boxes'` instead: that correlation holds in
the current rows but is asserted nowhere in code. Labels resolve through
`STAGE_LABELS.get(stage, stage)`, never a bare subscript, because `acquired` is
live on 8 rows and absent from the map.

## Verification

Gate order is the skill's, section 3, plus the test step. The numbered steps
below record the gate as run for commits 1 and 2. Step assertions describe what
was true at the time each ran, not current state.

1. Re run the pytest baseline immediately before editing
2. Migration: column present, nullable, FK to `deployment_records`, `SET NULL`.
   Row count unchanged at 13, all `deployment_record_id` NULL
3. `py_compile` on changed Python, `cfile="/tmp/..."`
4. Restart app, confirm worker up
5. In container import check
6. `pytest tests/ -q`. Pre-track baseline was 858 passed, 39 skipped. After
   commit 2 the figure is 871 passed, 39 skipped.
7. Browser gate, below
8. `git diff` review, then commit

**Browser gate:**

Recorded as run at commit 2. Rows below describe the board state at that time.
Deployment 15 now carries rows 240 and 241, so this gate is not re-runnable as
written without the reset discussed below.

| Check | Expected |
|---|---|
| Board renders unchanged before any assignment | 3 deployments, 2 certified with badges |
| Picker on deployment 15, order 72 | lists provisioning 240 and 241, both NULL |
| Assign one unit | that row gets `deployment_record_id = 15`, picker no longer offers it |
| Picker after assignment | shows the assigned unit read only, offers only the remaining one |
| Attempt to assign a unit from a different order | rejected with a specific message |
| Console | clean |

**Two picker opens, not one.** Deployment 15 alone exercises one of the two
serial resolution branches, because order 72 carries no items-path rows.

| Target | Serial paths | Stage chips |
|---|---|---|
| Deployment 15, order 72 (rows 240, 241) | legacy only | both present, `Cert'd` |
| Deployment 16, order 70 (rows 243, 244) | items and legacy, one each | both suppressed |

Deployment 16 already exists on order 70 in `scheduled` status, so it renders in
the active block and needs no setup. Order 70's rows are `cameras` and `items`,
both with `stages = []`, so neither shows a chip; order 72's are `edge_boxes`
with 40 stages, so both do. Neither target alone covers both axes, and either
alone would look like a bug.

Also verify the boosted path: leave fulfillment through the sidenav, return
through it, then open the picker. It must still work.

**Deployments 13 and 14 carry the only live `InstallationCertification` rows**
and are the test targets for the re-certification UI track; leave them alone.

**Tests.** Five cases are required, modelled on `tests/test_order_sku_flow.py`:
happy path, cross-order reject, re-assign reject, a batch carrying one
already-assigned id, and a returned unit reject. The batch case is the one that
matters, since it is what proves validate-all-before-write; a refactor to a
per-item loop would break it silently and nothing else would catch it. Cover the
feed endpoint at the same time, including both serial branches: a returned row
must appear in `returned` and must NOT appear in `available`. Order 79 carries
two returned rows and is the natural fixture.

**The gate is not repeatable without a reset**, because assignment is one way by
design. `UPDATE device_provisioning SET deployment_record_id = NULL;` restores
the pre-gate state.

Not run, deliberately, and it should stay unrun. The three live assignments
(240 and 241 to deployment 15, 243 to deployment 16) are the only evidence this
column has ever been exercised. Resetting would restore repeatability at the
cost of the only proof the feature works. If a fresh multi-unit picker is needed
for a future gate, reimport the master inventory spreadsheet instead. Owner
decision, 2026-08-28.

**Gate for the returned_date filter.** Reproduce before fixing, so the gate
proves something.

| Step | Expected |
|---|---|
| Create a deployment record on order 79, before the code change | Picker offers rows 250 and 251, both returned. This is the defect |
| Apply the change | |
| Picker on that order 79 deployment | `available` empty, `returned` lists 250 and 251 with their dates, read only |
| Picker on order 73, deployment 73 | Its one unit is STILL offered. This is the control and it must not regress |
| Post an assign for row 250 directly | Rejected, message names 250 |
| Console | clean |

Order 73 is the control because its single unassigned unit has `returned_date`
NULL. Orders 78 and 80 are additional negative cases if wanted, one unit each,
both returned.

## Commit

Two commits, not one.

1. Migration plus model plus assign endpoint. Backend, no UI.
2. Picker modal. Template plus JS.

Split because the modal should be mocked and reviewed before it is built, and the
backend does not wait on that.

Note, 2026-08-31: the track ran to five commits, not two. The plan above was
correct as far as it went; the extra three came from findings the build itself
surfaced, and each was split for the same reason the original two were.

1. `15f0220` migration, model, assign endpoint.
2. `3f3c0f7` picker feed, modal, tests.
3. `0e8973c` date the historical figures in this file.
4. `cd12da3` amend the spec to exclude returned units.
5. this commit, implement that exclusion.

Commits 4 and 5 were deliberately split so the design could be reviewed before
it was built, which is the same rule as the original split. `af344a0`, which
sets `created_by` on deployment creation, is NOT part of this track.

## Name collision, read before using `deployment_type`

`fulfillment-build-plan.md` locked decision 8 defines a `deployment_type` axis
meaning **deployment depth**: internal full versus partner confirm-only. That
axis is NOT built. `prebuilt_software` and `prebuilt_finished` appear in
`models.py` and nowhere else, and F5 which would consume them is unbuilt.

A `deployment_type` column DOES exist and is used widely, but it is a different
concept: a **deal classification**. `map.py:310` filters it on
`["customer", "pilot", "demo"]`, and there is inference logic across `map.py`,
`receiving.py` and `provisioning.py`. `CustomerOrder.deployment_type` and
`EdgeBox.deployment_type` both exist.

**Same name, different vocabulary.** Anyone grepping `deployment_type` after
reading locked decision 8 will find the deal classification and conclude the
depth axis is implemented. It is not.

`CustomerOrder.deployment_type`'s value set has NOT been read, so it cannot be
ruled out that the order level column carries the depth semantics. Read it
before this track branches on either.

**For this spec:** assignment behaviour should NOT branch on `deployment_type`
until the above is resolved. Assign units to visits uniformly.

## Follow up tracks this creates

- **Unit cancellation.** `DeviceProvisioning` has no terminal state. Scope it
  around "a unit can be pulled from an order, with a reason" rather than around
  deployments. Needed before a swap can be represented. See the correction in
  the cancellation section: `returned_date` is partial existing representation
  and this track should begin there.
- **Deployment keyed installation history.** Now cheaper, since units will be
  linked directly rather than inferred. See `fulfillment-pipeline-direction.md`
  for why serial keyed is the wrong primary frame for installation
  certification.
- **Page init does not re-run on a boosted navigation.** Owned by
  `page-init-on-boosted-navigation.md`, which specs it across all eight affected
  templates. Surfaced by this track rather than caused by it: before the
  top-level `let` fix in `3f3c0f7` the whole script threw on a boosted return,
  so total failure masked it.
- **Two error-shape conventions coexist.** `fulfillment.py` returns
  `JSONResponse(content={"detail": ...})`, 60 sites against 2; `provisioning.py`
  returns `content={"error": ...}`. Both are hand-built `JSONResponse` bodies
  rather than raised `HTTPException`, so the key name was a free choice each
  time and nothing owns it. Clients that hedge both keys already exist in
  `fulfillment.html`. Pick one and sweep, or document the split.

## Incidental, found while reading, not in scope

- `provisioning.py:494` creates rows with `current_stage="staged"`, but the
  model's declared default is `po_in`. Default and actual entry point disagree.
- `datetime.utcnow()` is deprecated on the container's Python 3.12 and is used
  throughout. Codebase wide sweep whenever it matters.

## Amendment log

This file has been amended twice since it was first committed. Commit 1 of the
track (`15f0220`) did NOT touch it; it changed only `models.py`,
`fulfillment.py` and migration 072.

**`3f3c0f7`, 2026-08-28, commit 2 of the track.** Five changes, not the four the
header previously claimed:

1. Status line, from specced-not-built to built.
2. Cancellation section, `current_stage` values replaced with measured counts,
   and `acquired` identified as absent from every stage structure.
3. New section 5, the picker feed endpoint, with the two path serial resolution
   and the stage suppression rule.
4. Verification, single deployment 15 target replaced with a two target gate,
   and the test requirement added.
5. Follow up tracks, page init not re-running on a boosted navigation, and the
   two error shape conventions.

**This commit, 2026-08-31.** Dated the historical figures rather than
overwriting them, so the record of what was true at each gate survives. Marked
the browser gate as run at commit 2. Labelled which baseline the pytest figure
describes: 858 was the correct PRE-TRACK number, not an error. Commit 1 added no
test files, but its new POST route generated 2 endpoint-census cases, giving the
860 measured before commit 2; commit 2 then added 10 contract tests plus 1
census case for its GET route, giving 871. Annotated the reset statement as
deliberately not run. Replaced the header clause that pointed at marked
paragraphs which were never marked.
