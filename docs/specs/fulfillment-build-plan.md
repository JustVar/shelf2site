# Fulfillment Build Plan (Revision 3)

> Status: F1a shipped. F1b (cert tables) is the next code step. F2 board design locked.
> Revised: 2026-06-18. Supersedes Revision 2.
> Scope: the Fulfillment buildout track for the Hardware Asset Tracker.

This revision folds in the F1a result (migration 049 landed) and the locked F2
board design (tabs + large grouped cards, Fulfillment-scoped mockup palette).

---

## 1. Core abstraction: two gating axes drive stage traversal

One pipeline, expressed as a superset of stages. How far a unit travels depends on
two independent properties:

- `fulfillment_type` shapes the In-House (build) side: how much building a unit
  needs before it ships.
- `deployment_type` shapes the Deployment (post-ship) side: whether Company
  installs it (full granular tracking) or a partner does (confirmation only).

Both are independent of category.

`fulfillment_type` values:

| Type | Examples | In-House path | Cert |
|------|----------|---------------|------|
| build (from components) | Edge Box / Cloud Box built to order | full path | full hardware cert |
| pre-built + software | pre-built EB/CB pulled from inventory | skip component sourcing/assembly chips; software load + testing | software/QA cert |
| pre-built finished | Camera 2 Cloud (own SKU) | skip build; pick from stock then ship | no build cert (light on-device check) |

`deployment_type` values (already on CustomerOrder):

| Deployment | Who installs | Deployment depth |
|------------|--------------|------------------|
| direct | Company internal SE | full granular tracking |
| via_integrator / via_distributor | partner | collapsed: ship-out + single "install confirmed" |

Build the full build-path + direct-deploy path first; it exercises everything.
The other variants are skip-stage subsets of the same engine.

---

## 2. Board model and stage representation (locked)

Two pipelines (Building, Delivery) plus the SE Delivery portal. Each pipeline uses
**status tabs, not stage columns** (the stage-column idea was tried and dropped:
columns squeezed the cards too small).

Tabs:
- Building: In Progress / Ready for Handoff / Queued
- Delivery: In Transit / On-Site Setup / Archived
- SE portal: Awaiting Install / In Transit / On-Site / Completed

Top of each board: metric counts (Active / Ready / Overdue, or In Stock / In
Transit / Awaiting Install / Completed).

**Cards: large grouped cards.** One card = one (order x SKU x current stage) group.
- Header: SKU + `×qty` badge + assignee initials (color map) + priority dot.
- Body: order / PO + customer, dates, an inline stage tracker showing the group's
  shared stage.
- Footer: action button (Build Certification at Sign-off; Finalize at delivery).
- Expanding a card reveals the per-unit list (serial / UUID, assignee, status) for
  per-unit or bulk actions. A 50-unit order is a few cards, not 50.

**Stage tracker labels are display-only, mapped onto existing stored values (no
schema change):**

Building tracker:
| Label | Stored value |
|-------|--------------|
| Drafting | status `new` |
| Sourcing | `sourcing` |
| Assembly | `building` |
| Testing | `testing` |
| Sign-off | build-cert complete (a `DeviceProvisioning.stages` step, pre-`shipped`) |

Delivery tracker:
| Label | Stored value |
|-------|--------------|
| Warehouse / Dispatch | `shipped` |
| Last Mile | `delivered` |
| Site Setup | `installed` |

The fine tracker steps live in `DeviceProvisioning.stages` JSONB; the coarse
`status` is the rollup.

**Per-stage checklists are NOT on the board.** They live in the cert/install modals
(`build_certification.qa_checklist`, `install_certification.site_checklist`, both
JSONB). The install panel's "Verification Tasks" list is exactly this.

"Where at a glance" comes from the top metric counts + tabs + each card's inline
tracker. That is the deliberate trade for dropping stage columns in favor of
readable cards.

---

## 2a. Design system (Fulfillment-scoped)

Adopt the mockup's color scheme, **scoped to Fulfillment pages only**; `main.css`
elsewhere is untouched. Revisit promoting it app-wide later if the whole app should
match.

- Scoped CSS-var set (a `.fulfillment` wrapper or its own stylesheet) defining the
  mockup palette (emerald primary, slate surfaces). Dark and light both, the app is
  dark-first.
- Fulfillment stage-color map: emerald = done, blue = current, slate = future.
- Assignee initials, no avatars: AR = blue, SC = purple, MJ = orange,
  LM = emerald, MA = rose, JS = amber.
- Branding: swap the AssetFlow Pro placeholder for Company in the real templates.

---

## 3. Locked decisions

1. `fulfillment_type`: per-device, with an order-level default. Values
   `build | prebuilt_software | prebuilt_finished`. (Shipped in F1a.)
2. `po_number`: required to enter the pipeline (app-level gate), UNIQUE, nullable,
   on CustomerOrder. (Shipped in F1a.)
3. Cert data: dedicated `build_certification` + `install_certification` tables.
   Checklists as JSONB. `install_certification` carries an internal-vs-partner field.
   SUPERSEDED on the install side: that in-app checklist design shipped as
   migration 050 and was retired in migration 054. The owning spec is
   `installation-certification.md`, which ratifies a PDF based certification with
   no in-app checklist and no internal-vs-partner field, in table
   `installation_certification` (migration 053).
4. File uploads (cert/checklist docs): filesystem path, reusing the
   `validation_report_path` volume.
5. Board layout: status tabs + large grouped cards (no stage columns).
6. Card model: grouped by (order x SKU x stage), `×qty` badge, expand to units;
   `CustomerOrder.status` is a derived rollup, not separately maintained.
7. Stage tracker: display labels on existing stored values; fine steps in
   `DeviceProvisioning.stages` JSONB; per-stage checklists live in the modals.
8. Two gating axes: `fulfillment_type` (In-House depth + chip template) and
   `deployment_type` (Deployment depth: internal full vs partner confirm-only).
9. Cert modal attach points: Build Cert at Sign-off (F3); Install at the delivery
   "Finalize / Certify" step (F4).
10. Palette: the mockup scheme, Fulfillment-scoped; emerald/blue/slate stage
    colors; dark and light.

---

## 4. What already exists (reuse, verified during F1a discovery)

`customer_orders` (CustomerOrder): id, order_number(32, unique), salesforce_order_id,
salesforce_opp_id, customer_name, customer_account, sales_engineer (+ _id FK users),
deployment_type(32, default direct), integrator_name, distributor_name, due_date,
status(32, default new) + ORDER_STATUSES + STATUS_COLORS, sku_requirements JSONB
[{model, qty, source}] (model is a free string, not an FK), pre_site_survey,
post_install_notes, notes, is_sensitive, contract_value, hardware_cost, timestamps,
created_by. Shipping (mig 021): shipped_date, delivered_date, carrier,
tracking_number, shipping_address, ship_method, recipient_name. F1a (mig 049):
po_number(64, unique, null), default_fulfillment_type(32, null). Relationships:
provisioning_records, oem_pos, deployment_records.

`device_provisioning` (DeviceProvisioning): id (PK, the cert-table FK target),
device_table(64) + device_id (polymorphic), site_id FK, current_stage(32, default
`po_in`), stages JSONB (not null), assigned_to FK, notes, priority(16),
is_complete, completed_at, due_date, start_date, location_note,
deployment_bucket(32), customer_order_id FK (SET NULL), zendesk_ticket_id,
validation_report_path(512), validation_result(16), validation_date, timestamps,
created_by. F1a (mig 049): fulfillment_type(32, null). 7 provisioning stages already
defined: Staged -> Configured -> Registered -> Licensed -> Certified -> Deployed ->
Active.

`OEMPurchaseOrder`: ordered | in_production | acceptance | receiving | verified |
cancelled.

`fulfillment.py` (657 lines): `_is_valid_sku` (edge-box regex only),
`_stock_snapshot` (reads legacy EdgeBox.part_number), GET /fulfillment/,
ship/deployment/export/technician routes. Plus orders.py (459), provisioning.py
(1408), templates fulfillment.html, orders.html, order_detail.html,
provisioning.html, provisioning_detail.html. Note: `/orders/` and `/provisioning/`
currently redirect into `/fulfillment/`.

---

## 5. Gap: what the new model needs that does not exist

| Feature | Status | Gap |
|---------|--------|-----|
| fulfillment_type (per-device + order default) | DONE (F1a) | shipped, migration 049 |
| po_number + pipeline gate | DONE (F1a) | column + UNIQUE shipped; app-level gate not yet enforced |
| build_certification table | DONE | shipped via migrations 051, 052 and 061; slices S6a through S6f implemented and verified, see `build-certification.md` |
| install_certification table | SUPERSEDED | shipped as `installation_certification` (migration 053) with a different, PDF based design; the checklist model described here was retired in migration 054, see `installation-certification.md` |
| tab + large grouped-card board | PARTIAL | dark mockups exist; need real grouped data binding, scoped palette, expand-to-units |
| read/write of fulfillment_type in routes/UI | MISSING | F2 |
| two gating axes + per-type chip templates | MISSING | F5 |

---

## 6. Phased build order

Each phase is its own commit + 4-location sync, browser-verified before commit.

F1a - Data model: fulfillment_type, default, po_number + UNIQUE. **DONE.**
(migration 049, commit 5e31941, synced across all four endpoints.)

F1b - Cert tables. **SHIPPED, but not as planned.** Migration 050 was retired in
054; the tables arrived as `build_certification` (migrations 051, 052, 061) and
`installation_certification` (053). The install side dropped the in-app checklist
entirely, see `installation-certification.md`.

F2 - Board: the tab + large grouped-card board for Building, Delivery, and the SE
portal. Grouped cards (order x SKU x stage, `×qty`, expand to units), inline stage
tracker, Fulfillment-scoped palette, assignee-initials filter. Compute
`CustomerOrder.status` as a rollup. Read-only first, verify live.

F3 - Build Certification modal: UUID, hardware validation, Appliance version, license
counts, signers, QA checklist, file upload. "Mark Complete" -> build_certification
-> advance to Sign-off. Verify live.

F4 - Delivery + Install panel. **SHIPPED, but not as planned.** The install side
is a PDF based certification, not the SE checklist upload and verification-task
checklist described here. See `installation-certification.md`.

F5 - Type + deployment gating: fulfillment_type chip templates per (type x
category), pre-built skips; deployment_type partner collapse. **STILL UNBUILT:**
`prebuilt_software` and `prebuilt_finished` appear in `models.py` and nowhere
else, an enum nothing consumes. The C2C portion has LEFT this track and shipped
under its own specs (`c2c-camera-certification.md`, `c2c-cert-pdf-history.md`,
`c2c-return-ending.md`), so the missing C2C mockup is no longer this blocker.

Deferred (not this track): legacy public.* -> item_schema migration (section 7),
warranty model, components migration.

---

## 7. Legacy-schema question (not a blocker for this track)

Fulfillment reads EdgeBox from legacy public.*, while the rest of the app uses
item_schema. Two SKU systems coexist (new: item_schema.part_numbers +
Item.brand_sku; old: EdgeBox.part_number + regex `_is_valid_sku`). This does not
block the pipeline UX + modals. Fully unblocking strict SKU select (B2/B3) is a
separate later track: migrate public.edge_boxes -> item_schema.items; rewire
`_is_valid_sku` to query part_numbers; promote sku_requirements.model from free
string to a part_numbers SKU; per-category SKU filtering in the select macro.
Managed SKUs are sellable-category only (Edge Box, C2C, Cloud Box). Documented as
deferred in CLAUDE.md.

---

## 8. Migration tooling / house style

- Numbered migration files in migrations/ (not Alembic). Canonical style is the
  self-executing 048 pattern: `from app.database import engine`, single
  `engine.begin()` transaction, `if __name__ == "__main__"` block, idempotent DDL
  (IF NOT EXISTS). 044 of 046 migrations use this; only 045/046 use the
  upgrade()/downgrade() style and have no runner (a latent issue, not chased).
- Type/status columns are VARCHAR(32) + inline comment + app-level validation, not
  Postgres ENUM (matches deployment_type, status, priority). Avoids re-introducing
  the orphan SAEnum drift.
- Migrations are bind-mounted (`/opt/asset_tracker/migrations`), so no rebuild.
  Run on apphost: `docker compose exec app python migrations/NNN.py`.
- Latest migration is 049. F1b is 050.

---

## 9. Open questions

Resolved this track: fulfillment_type granularity (per-device + default); po_number
uniqueness (UNIQUE nullable); file storage (filesystem); stage reconciliation
(labels on existing values); board layout (tabs + large grouped cards); card model
(grouped, expand); palette (mockup scheme, Fulfillment-scoped).

Still open:
- Full build-cert field list: the Build Cert mockup is a stub (UUID / Customer /
  PO# only). Pin the full fields (hardware validation, Appliance version, license
  counts, signers, QA checklist) from this plan or a fuller mockup before F1b/F3.
- C2C mockup: needed for F5 only.
- CustomerOrder.status rollup rule: define the exact rollup (least-advanced device
  stage, or "mixed") at F2.
- Partner install_certification minimal shape: confirm exact fields at F4.

---

## 10. Deferred / not this track

- B2/B3 strict SKU select everywhere (blocked on the public.* -> item_schema
  migration).
- Warranty model (design alongside fulfillment; hangs off CustomerOrder /
  shipped-line, not item; likely surfaces during the F-track).
- Components migration (public.device_components -> item_schema event-log).
- Retire 22 legacy per-category models + public.* tables.
- Test harness rebuild (TestClient cannot reach routes due to middleware-auth
  path-prefix).
- SSE missed-event replay (NOTIFY is fire-and-forget).

---

## 11. Status snapshot (2026-06-18)

> Point in time and overtaken. Kept as history. Do not read the next-code line
> below as a live instruction: migrations are past 070, and F1b through F4 have
> shipped. See sections 3, 5 and 6 above for what actually landed.

- F1a shipped: migration 049 (fulfillment_type, default_fulfillment_type,
  po_number + unique index), models patched, ORM smoke-tested, commit 5e31941
  synced across local / apphost / origin / company.
- F2 board design locked (this revision).
- Next code: F1b cert tables (migration 050), pending the full build-cert field
  list.
- Roadmap (separate brand-internal-dashboards repo, QA project): F1a row
  deferred, to be batched when F1b lands.
