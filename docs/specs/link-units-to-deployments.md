# Link provisioned units to deployment visits

Status: specced, not built. Every premise read.

Owner note: WHAT and WHY only. The HOW is the `asset-tracker-workflow` skill.
Repo facts live in `CLAUDE.md`. Background on the fulfillment model is in
`fulfillment-pipeline-direction.md`.

## Why

Serial is the identifier tracked across inventory and deployments. Today it does
not reach deployments.

Read from the model: only two tables carry `deployment_record_id` -
`UnitPhoto` (line 403) and `InstallationCertification` (line 2100).
`DeviceProvisioning`, which holds the units, does NOT. Units hang off
`customer_order_id`; deployment records hang off `customer_order_id`. They are
siblings and are never joined.

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

## What the reads established

| Question | Answer |
|---|---|
| Where are deployment records created | `POST /fulfillment/deployments` at 818, constructing at 844. Three deployment endpoints total: create, status, certify. No update, no delete, no assignment. |
| What currently joins units to deployments | NOTHING. Every `customer_order_id` hit in the module is units grouped by order. The column is purely additive; there are no read paths to switch. |
| Units per deployment | 2 across all three live deployments. One visit covers multiple serials. |
| Can a deployment span certification subsystems | YES. Order 70 is a camera plus a generic item, neither on the build path. `fulfillment_type` is `build` for only 5 of 13 provisioning rows. |

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
`acquired`, `building`, `certified`, `hw_check`, `staged`, all pipeline
positions. `provisioning.py:755` advances and `897` walks back, so movement is
bidirectional, but there is NO terminal cancelled state. There is no cancelled
flag and no replacement pointer.

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
WHERE customer_order_id = N AND deployment_record_id IS NULL
```

The modal lists that set with checkboxes, shows the serial and current stage for
each, and posts the selected ids.

**Show already assigned units too, read only.** A picker that hides them makes it
impossible to see what the visit already covers, which is the question the user
usually has.

## Verification

Gate order is the skill's, section 3, plus the test step.

1. Re run the pytest baseline immediately before editing
2. Migration: column present, nullable, FK to `deployment_records`, `SET NULL`.
   Row count unchanged at 13, all `deployment_record_id` NULL
3. `py_compile` on changed Python, `cfile="/tmp/..."`
4. Restart app, confirm worker up
5. In container import check
6. `pytest tests/ -q`, expect 858 passed, 39 skipped
7. Browser gate, below
8. `git diff` review, then commit, then four location sync

**Browser gate:**

| Check | Expected |
|---|---|
| Board renders unchanged before any assignment | 3 deployments, 2 certified with badges |
| Picker on deployment 15, order 72 | lists provisioning 240 and 241, both NULL |
| Assign one unit | that row gets `deployment_record_id = 15`, picker no longer offers it |
| Picker after assignment | shows the assigned unit read only, offers only the remaining one |
| Attempt to assign a unit from a different order | rejected with a specific message |
| Console | clean |

**Deployment 15 is the right test target.** It is in `installing` status with no
certification, so assigning units to it disturbs nothing certified. Deployments
13 and 14 carry the only live `InstallationCertification` rows and are the test
targets for the re-certification UI track; leave them alone.

## Commit

Two commits, not one.

1. Migration plus model plus assign endpoint. Backend, no UI.
2. Picker modal. Template plus JS.

Split because the modal should be mocked and reviewed before it is built, and the
backend does not wait on that.

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
  deployments. Needed before a swap can be represented.
- **Deployment keyed installation history.** Now cheaper, since units will be
  linked directly rather than inferred. See `fulfillment-pipeline-direction.md`
  for why serial keyed is the wrong primary frame for installation
  certification.

## Incidental, found while reading, not in scope

- `provisioning.py:494` creates rows with `current_stage="staged"`, but the
  model's declared default is `po_in`. Default and actual entry point disagree.
- `datetime.utcnow()` is deprecated on the container's Python 3.12 and is used
  throughout. Codebase wide sweep whenever it matters.
