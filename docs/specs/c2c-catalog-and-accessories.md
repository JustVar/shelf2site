# C2C Catalog, Accessories, and Cert-Subject Grain — spec (DRAFT)

Status: **DRAFT for decision.** Structural facts below are read-grounded (this
session). The central cert-subject grain decision (section 7) is deliberately
left open with three options and trade-offs — decide before C2 builds the cert
write path, since migration 055 already commits to one grain.

This spec supersedes the cam-SKU-convention framing in
`c2c-c1-discovery-handoff.md` ("SKU-prefix, no category field"). That note was
explicitly grounded on zero cam-line data. There is data now, and it changes the
answer.

---

## 1. What this covers

The full Camera-2-Cloud (C2C) product as it touches orders and certification:
the camera SKUs, the cloud-storage entitlement, the accessories (brackets,
microSD cards), how a customer order carries them, how cameras are obtained, and
— the crux — which inventory representation is the certification subject.

C1 built the acquire path and cert schema against legacy `public.cameras`. This
spec does not invalidate C1 (see section 8) but decides the grain C2 builds on.

---

## 2. Grounded facts (read this session, with source)

**The catalog exists and is categorized.**
- `item_schema.part_numbers` (`ItemPartNumber`), keyed on `brand_sku` (unique),
  carries an `item_category` enum column. 85 rows.
- Category distribution: `edge_box` 73, `storage_drive` 7, `gpu` 2, `camera` 1,
  `camera_c2c` 1, `cloud_box` 1.
- The canonical C2C camera SKU is **`C2C-GEN1-4MP`** -> `item_category =
  camera_c2c`, "Company C2C Gen1 4MP Camera", not legacy.
- `E2C-25-2TB` is `item_category = edge_box` (legacy, SimplyNUC) — NOT a camera.
- `item_schema.items` FKs to `part_numbers.brand_sku`
  (`items.brand_sku` -> `part_numbers.brand_sku`).

**There are two unlinked camera worlds.** This is the central finding.

| | Legacy `public.cameras` (`Camera`) | Unified `item_schema.items` (`Item`) |
|---|---|---|
| SKU link | none — no `brand_sku`, no `part_number` column | `brand_sku` FK -> `part_numbers`, plus `item_category` |
| Identity | vendor `model` + `serial` | SKU + category + `item_sn` |
| Points here | `TABLE_MODELS["cameras"]`, the acquire path, `DeviceProvisioning`, the cert FK chain | nothing in the provisioning/cert world |
| Sample rows | ids 1-5 (Hanwha/Avigilon, real serials, no SKU) | id 17 = `camera_c2c` / `C2C-GEN1-4MP` / serial `C2C-SX-0001`; id 16 = `camera` / `PVA-CAM-HW8080` |

- `DeviceProvisioning.device_table="cameras"` resolves via `TABLE_MODELS` to
  **legacy `public.cameras`**. `item_schema.items` is **not** in `TABLE_MODELS`,
  so the provisioning/cert chain structurally cannot point at the `camera_c2c`
  item.
- The camera C1 provisioned (row #243) is `public.cameras` id 1 (Hanwha, no SKU).
  The SKU-tagged C2C camera is `items` id 17. They are different rows in
  different tables, unlinked.
- `_sku_availability` (`orders.py`) iterates `TABLE_MODELS` only, matching
  `model.ilike("%model%")` across every legacy table — it never sees
  `item_schema.items`, so it cannot resolve a cam SKU to stock.

**This lands on a known unfinished migration.** CLAUDE.md flags a
legacy-per-category-tables -> `item_schema.items` migration that is in progress
but has not reached cameras (`items` holds ~2 camera rows; real cam stock lives
in `public.cameras`). C2C landed on that seam. Trajectory of that migration is
currently **unsure — not planned, not ruled out** (owner decision).

---

## 3. Product model (structure decided; SKUs + accessory category PROPOSED)

**Same hardware + entitlement.** A `-1` SKU (e.g. `DC-5V-1`) is a camera sold as
a camera. A `-30` SKU (e.g. `DC-5V-30`) is the **same physical camera** plus the
Camera-2-Cloud storage entitlement. They are two distinct orderable SKUs, not two
physical products.

**Two tiers:**
- **Certifiable** — a physical camera fulfilling a C2C (`camera_c2c` / `-30`
  entitlement) line. Rides the cert checklist (powered on, firmware verified, QR
  virtual-site connect, registered).
- **Fulfilled, not certified** — `-1`-only cameras, brackets (`GP02`, `BW10`,
  `BJC07`, ...), microSD cards (`WDD512G1P0C`, `WDD100T1P0C`). They appear on
  orders and get fulfilled; they never touch the cert table or checklist.

**Customer-supplied accessories** = the line is simply absent from the order. No
customer-owned-asset tracking; if they have their own bracket/card, they order
only the camera SKU and no accessory line appears.

### Reality-check note (grounded 2026-07-01)

The **tier structure above is decided.** The **specific SKUs and the accessory
category are NOT yet catalog-grounded** — treat them as proposed:

- None of the example SKUs exist in `item_schema.part_numbers` today —
  `DC-5V-1`, `DC-5V-30`, `GP02`, `BW10`, `BJC07`, `WDD512G1P0C`, `WDD100T1P0C`
  all return 0 rows. Illustrative naming, not catalog entries.
- The `-1`/`-30` (`DC-5V-*`) entitlement naming does not match the one real
  `camera_c2c` SKU, `C2C-GEN1-4MP` (which has no `-1`/`-30` form). Reconcile the
  naming before the catalog is populated.
- `item_categories` (23 values) has **no camera-accessory / bracket / mount
  category.** microSD can map to `consumables` or `storage_drive`; brackets have
  no home. Accessory-as-order-line needs a mapping ruling **or** an
  `ALTER TYPE item_categories ADD VALUE` migration — decide before building the
  accessory fulfillment surface.

Ground the SKUs and the accessory category before treating §3 specifics as
build-ready.

(Intake path confirmed: C2C stock enters `item_schema.items` via the existing
`POST /intake` — the live `camera_c2c` row `C2C-GEN1-4MP` (items id 17) was
created that way. See section 7, option D.)

---

## 4. Order and acquisition flow (grounded — OEM sourcing is manual)

Customer orders cameras -> Company obtains them (from stock, or from OEM with a
delivery lead time) -> Company sends to customer (via engineer, integrator, or
ship).

**OEM sourcing is manual today; `source` drives nothing (grounded this session):**
- The `sku_requirements` line's **`source`** field (`stock | oem | tbd`) is
  **inert**. It appears in exactly two places app-wide (the column comment and a
  display passthrough in `_sku_availability`); there is **no `source == "oem"`
  branch** anywhere. It is a decorative label, not a trigger.
- `OEMPurchaseOrder` rows are created **by hand** via
  `POST /api/orders/{order_id}/oem-pos` (the sole instantiation site, `orders.py`)
  — order-scoped, with **no `sku_requirements` linkage** and no auto-derivation.
- For cams: a `source=oem` line carries the label and does nothing automatically.
  OEM-sourced cams reuse the **same manual, category-agnostic PO API** (it accepts
  any SKU), so no new acquisition mechanism is required — but a human creates the
  PO and nothing ties it to the specific line.

**Open decision (not a blocker for D):** whether C2C cams need any auto-wiring of
`source=oem` -> `OEMPurchaseOrder`, or manual PO creation is sufficient.

---

## 5. Cam-line discriminator (decided, grounded)

A C2C "needed" line is discriminated by a **catalog join**, not a string prefix
or a JSONB `category` field:

> `sku_requirements.model` -> `part_numbers.brand_sku` where
> `item_category = 'camera_c2c'`.

This supersedes the C1 "SKU-prefix" idea and vindicates the C1 "no category field
on the JSONB line" call — the category already lives in `part_numbers`, reachable
by join, so the line stays `{model, qty, source}`.

**Data-quality dependency:** the join only works if order lines carry **canonical
catalog SKUs**. Order 70's line is `model: "EDGE-2000"`, which is NOT in the
catalog (catalog has `EDGE100-NR`, `EDGE25-NR`, ...). So a join-based
discriminator requires intake to constrain `sku_requirements.model` to real
catalog SKUs. The intake form's `list="edge-skus"` datalist already half-does
this for edge boxes; extending it to a catalog-backed picker is spec scope.

---

## 6. The SKU-to-camera bridge (decided direction, grounded in precedent)

Where a physical camera records which SKU it fulfills: a **`fulfillment_sku`
column on the `DeviceProvisioning` row**, set at acquire time, as a **foreign key
to `part_numbers.brand_sku`** (not a bare string).

- Precedent: `items.brand_sku` is already an FK to `part_numbers` — matching
  that pattern keeps the catalog the single source of truth and blocks the
  `EDGE-2000` class of non-catalog typo at write time.
- Double duty: it marks cert-eligibility (a `camera_c2c` SKU) AND is the only
  bridge between the SKU-based order line and the serial-based physical camera.
- Caveat: `DeviceProvisioning` is polymorphic (shared across edge boxes, cameras,
  etc.). Adding `fulfillment_sku` is nullable and edge boxes ignore it, but it is
  a shared-table change — apply the "does this affect adjacent boards" check at
  build time.
- **This bridge only exists for acquired cameras.** It does not make un-acquired
  stock cameras SKU-identifiable — that is the availability problem in section 7.

---

## 7. CENTRAL DECISION — cert-subject grain (DECIDED — option D)

The two halves of the C2C view key off different, unlinked tables: "Needed"
(SKU -> `items`/`part_numbers`) and "Acquired/Certified" (provisioning ->
`public.cameras`). Nothing ties a provisioned legacy camera to the `camera_c2c`
SKU it fulfills. Migration 055 keys the cert on `device_provisioning_id` — i.e.
it already commits to option A's legacy grain. Changing grain is cheap now,
expensive after C2 builds the cert write path.

### Option A — cert on legacy `public.cameras` (what C1 built)
- **Means:** cert stays keyed on `device_provisioning_id` -> `cameras`. View
  shows **needed vs acquired only**; drop "available in stock".
- **055 impact:** none — 055 is built for this.
- **C2 impact:** minimal; cert write path proceeds as designed.
- **Optimizes for:** the legacy world (slated for retirement, unfinished).
- **Right when:** `public.cameras` stays indefinitely and needed-vs-acquired is
  sufficient (it is — the acquirer picks a specific physical camera, so a stock
  count is not required to act).
- **Risk:** builds a new feature on the table being retired. If the migration
  later reaches cameras, C2C needs re-platforming.

### Option B — commit C2C to `item_schema.items` (`camera_c2c`)
- **Means:** cert subject = an `items` row; SKU, category, and availability all
  reconcile with the order line natively.
- **Cost:** `DeviceProvisioning` cannot reference `items` today. Two sub-paths:
  - **B1** — extend the polymorphic link so `device_table` can point at
    `item_schema.items` (schema + `TABLE_MODELS` change; touches every
    polymorphic consumer).
  - **B2** — key the cert directly on `items`, dropping the mirror-build-cert /
    provisioning-row-FK design; rework migration 055's FK from
    `device_provisioning_id` to an `items` id.
- **055 impact:** FK basis reworked (cheap pre-C2, expensive post-C2).
- **Optimizes for:** the unified world (arriving, not yet at cameras).
- **Right when:** cameras are migrating to `items` on a near horizon, or you want
  C2C correct-by-construction against the SKU-aware table.
- **Risk:** more work now; if the migration never reaches cameras, C2C is built
  on a table holding ~2 camera rows while real stock stays in `public.cameras`.

### Option C — bridge legacy `cameras` to its SKU / items id
- **Means:** add a `brand_sku` (FK to `part_numbers`) or an `items` link to
  `public.cameras`. Keep provisioning/cert on `cameras`. SKU becomes reachable
  from the provisioned cam, so availability is computable.
- **Cost:** a migration on `cameras` + a backfill tagging existing cams with
  SKUs + an intake/receiving step that sets the SKU.
- **055 impact:** none (cert stays on `device_provisioning_id`).
- **C2 impact:** minimal; availability becomes computable via the new link.
- **Right when:** you want availability to work AND keep C1's working provisioning
  grain, without betting on the `items` migration either way.
- **Risk:** adds a parallel SKU representation on legacy `cameras` that
  duplicates what `items` already provides — arguably deepens the seam rather
  than closing it.

### Decision — Option D (CHOSEN)

**D = keep the C1 provisioning + cert chain, and point it at an
`item_schema.items` camera via a new nullable `item_id` FK on
`device_provisioning`.** C2C cameras are entered as normal inventory into
`item_schema.items` through the existing `POST /intake` (the live `camera_c2c`
row `C2C-GEN1-4MP`, items id 17, was created that way). Acquisition and
certification stay on the `DeviceProvisioning` chain C1 built; **migration 055
and the cert grain are untouched** (cert still keys on `device_provisioning_id`).
Availability becomes computable natively, because the items row already carries
`brand_sku` + `item_category`.

D is a lighter shape than the original "B" framing: it keeps the provisioning row
(so the order-link and serial-snapshot come along for free) and only adds a link
column; it does not fork cert off the provisioning subsystem.

**Why not the others (the decision record):**
- **A — REJECTED.** The owner requires available-in-stock counting (how many can
  we use vs how many to order); A explicitly drops that.
- **C — DOMINATED.** `item_schema.items` already carries `brand_sku` +
  `item_category`, so per-model counts are native under D; bolting a SKU onto
  legacy `public.cameras` (C) is redundant and deepens the seam.
- **B1 — DEAD.** Probed: registering `Item` in the shared `TABLE_MODELS` pollutes
  ~15 legacy consumers (the label helpers return `-` / an ORM object). Not viable.
- **B2 — OVERKILL.** The need is inventory counting, not cert-on-items; reworking
  055's FK and forking cert off provisioning (losing the order-link +
  serial-snapshot) is disproportionate.

**Consequence:** C1's verified acquire (provisioning #243) targets a legacy
`public.cameras` row. Going forward acquire targets `item_schema.items`; #243 is a
legacy test artifact. This reverses which table acquire targets — expected.

---

## 8. Why C1 still stands regardless of the decision

C1's acquire path and cert schema key on the **physical `device_id` + order**,
never on SKU. Provisioning #243 and migration 055 are valid and working under
option A. The seam lives entirely in the unbuilt "available stock" derivation and
the cert-grain choice for C2 — not in acquire or the 055 schema. If A is chosen,
nothing changes. If B is chosen, 055's FK is reworked before C2. If C is chosen,
055 is untouched and a new `cameras` link migration is added.

---

## 9. Availability / quantity model (follows from section 7)

- **Needed** — order `camera_c2c` lines (section 5 join). Computable now.
- **Acquired** — cam `DeviceProvisioning` rows on the order (like #243).
  Computable now.
- **Available in stock** — **now computable under D.** Query `item_schema.items`
  directly, filtered on `item_category = 'camera_c2c'` (and/or `brand_sku`),
  netting out cams already linked to an active `DeviceProvisioning` (via the new
  `item_id`). Do NOT reuse `_sku_availability` for cams — its cross-category
  `ilike` over-matches and it never sees `item_schema.items`.

---

## 10. Parked / open

- **OEM procurement wiring for cams** (section 4 open read) — how a `source=oem`
  cam line becomes an `OEMPurchaseOrder`. Ground before building acquisition.
- **Cameras -> `item_schema.items` migration trajectory** — the fact that flips
  section 7. Currently unsure.
- **Accessory fulfillment surface** — brackets/cards as order lines is decided,
  but their fulfillment/tracking UI is unscoped.
- **QR / virtual-site verification mechanics** — parked in the original C2C spec;
  still C2.
- **`is_complete` coupling** — whether certifying a cam sets provisioning
  `is_complete=true` (which would move it in/out of any availability count).
  Decide deliberately in C2.

---

## 11. Slice impact

- **C1 (shipped):** unaffected. Acquire + 055 stand.
- **C2 (next):** cert write path — **blocked on the section 7 decision.** Under A
  it proceeds as originally specced. Under B it reworks the 055 FK first.
- **Catalog/accessory work:** its own track once section 7 is decided; do not
  fold into C2.
