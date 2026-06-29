# C2C Camera Certification — schema and model spec

Status: **APPROVED (structure).** The structural decisions below are ratified.
The *contents* of the firmware evidence and the exact checklist items are
expected to iterate as the OEM firmware matures — that churn is absorbed by JSONB
by design and does not change the schema. Not yet built.

## What this feature is

C2C cameras (`camera_c2c` category, the `cameras` table) are the company's Cloud2
camera product. Unlike edge boxes, there is no build and no parts. The flow is:
acquire the cameras for an order, then certify each one — powered on, firmware
verified, connected to its virtual site via QR code, and properly registered.

This is a separate, lighter flow from build cert (which is hardcoded
edge-boxes-only) and from installation cert. The certificate is the in-app
verification record, not an uploaded document.

## Relationship to the other cert flows (all distinct)

| | Build Cert (SHIPPED) | Installation Cert (APPROVED) | C2C Camera Cert (this doc) |
|---|---|---|---|
| Subject | Edge box (device) | A deployment at a site | C2C camera |
| Build/parts | Yes | No | No |
| Verification | In-app, two-person | In the uploaded PDF | In-app, per-camera |
| Capture | QA + SMART + components | PDF + installer name | Checklist + firmware evidence |
| Gate | All checks, both halves | PDF present | All checklist items pass |
| Grain | Per device | Per deployment record | **Hybrid (see below)** |

## What already exists (the prerequisite is small)

Grounded in the current model — no new device representation is needed:

- **Category**: `camera_c2c` is already in `item_categories_enum`. (Confirmed:
  `camera_c2c` IS the Cloud2 cam.)
- **Table**: the `cameras` table / `Camera` model already exists and is the
  product. It is bare inventory (manufacturer, model, serial, location, IP/MAC,
  deployment_type) and carries **no** firmware/plugin/license fields. It stays
  untouched — firmware evidence does not live here.
- **Provisioning**: `DeviceProvisioning` already supports
  `device_table="cameras"` via `TABLE_MODELS`; nothing provisions cams through
  fulfillment yet (the slot exists, unused).
- **The gap**: (1) the entire fulfillment / cert flow is hardcoded
  `device_table == "edge_boxes"` (10+ guards in `fulfillment.py`), so C2C needs
  its own minimal path, not a reuse of those routes; (2) no cert table for cams.

## Ratified decisions

- **Hybrid grain.** The order tracks the batch (model + quantity of cams needed);
  each camera certifies **individually** (by serial); the order's C2C portion is
  done when **all** its cams are certified. Per-cam cert rows; order completion is
  a rollup over them.
- **Firmware/plugin/license as a JSONB blob on the cert record.** Volatile,
  point-in-time evidence — what was on the cam at certification — not durable
  inventory. JSONB absorbs early OEM iteration with zero migrations. The `cameras`
  table is not touched. (JSONB in-place mutation needs whole-dict reassignment —
  known build-cert gotcha.)
- **Fixed checklist (initial set, may evolve).** Powered on, firmware verified,
  connects to virtual site via QR, registered. Stored as booleans in JSONB
  alongside the evidence.
- **Gate.** A cam certifies only when all checklist items pass. Any false leaves
  it pending (or failed, if you later want a terminal-failed state — parked).
- **Separate flow.** New routes and a new table; does not ride the edge-box-only
  build-cert routes.
- **Role gating.** Read: provisioning viewer. Write/certify: provisioning manage.

## Acquisition (minimal fulfillment) — FRAMED, grounded at build time

"Very minimal." An order line for C2C is model + quantity ("this order needs N
cams of model X"). As physical cams are acquired, each is provisioned as a
`DeviceProvisioning` row (`device_table="cameras"`, `device_id -> cameras.id`),
giving the per-cam identity the cert keys on.

The exact order-line representation (how a C2C model+quantity line is stored on
the order) is **not yet read** and must be grounded at C1 build time before this
section is final. Two shapes to resolve then: an explicit C2C order-line table, or
deriving the batch from the set of cam provisioning rows linked to the order.

## Cert layer (the firmed-up part)

### Schema — `c2c_certification` (new table, migration 054)

Per-camera. Keys on the provisioning row (mirrors build cert) so the order link
and a serial snapshot come along.

| column | type | role |
|---|---|---|
| id | int PK | |
| device_provisioning_id | int FK -> device_provisioning, CASCADE, not null | the cam's provisioning row (device_table=cameras) |
| camera_serial_snapshot | varchar(64) null | snapshot for lifetime history |
| status | varchar(16) not null, default 'pending' | `pending \| certified` (optional `failed` parked) |
| checklist | JSONB null | `{powered_on, firmware_verified, qr_site_connected, registered}` booleans |
| firmware_evidence | JSONB null | flexible blob: firmware version, plugins, license — shape iterates |
| notes | text null | optional |
| certified_by | varchar(128) null | internal certifier display_name |
| certified_at | datetime null | server timestamp at certify |
| created_at | datetime not null | |
| created_by | varchar(128) null | |

Indexes: `(device_provisioning_id)`, `(status)`.

### Order rollup

The order's C2C portion is "complete" when every cam provisioned to it has a
`c2c_certification` row with `status = certified`. Derived, not a stored flag
(parallels how build-cert board-close was layered as a separate concern). The
exact rollup query depends on the acquisition representation resolved above.

### Routes (proposed)

| method + path | gate | purpose |
|---|---|---|
| GET `/fulfillment/c2c` | viewer | C2C orders: cams needed / acquired / cert status |
| POST `/fulfillment/c2c/{provisioning_id}/certify` | manage | submit checklist + firmware evidence, gate, certify |
| (acquisition routes) | manage | provision cams to an order — shape TBD at C1 |

### UI

Translate the dark tokens in `docs/mockups/README.md`. No dedicated Superdesign
mockup for C2C yet — design intent is the lighter analog of the build-cert detail
page. A C2C order shows model x quantity needed, acquired/provisioned count, and a
per-cam list with cert status. The certify control is a small modal: the four
checklist toggles plus the firmware evidence inputs (rendered from whatever the
current JSONB shape is). No components, no SMART, no two-person sign-off.

## Slice plan

- **C1** — ground the acquisition representation (read the order line-item model),
  then migration 054 (`c2c_certification` table + indexes) and the minimal
  acquisition path: provision cams (`device_table="cameras"`) to an order, plus a
  read-only C2C view. No certify write path yet.
- **C2** — per-cam certify modal + write path: the four-item checklist, the
  firmware-evidence JSONB capture, the all-pass gate, cam -> certified, and the
  order rollup (done when all cams pass).
- **C3** — polish: acquired-vs-needed counts, completed-order state, per-cam cert
  history.

## Parked / evolving (by design)

- Exact `firmware_evidence` JSONB keys and the exact checklist items — expected to
  change through early OEM firmware iterations; JSONB makes this migration-free.
- The QR / virtual-site registration verification mechanics (manual confirmation
  vs an API check) — undecided.
- A terminal `failed` state and retry semantics — parked; `pending` covers the
  not-yet-passed case for now.
- The acquisition order-line shape — resolved at C1 build time.

## Out of scope

- Cloud Box certification (will most likely reuse the Edge Box build cert) and the
  Cloud Box -> Edge Boxes "Neurosen" private-cloud labeling — tracked as a
  separate future TODO.
- Any change to the `cameras` inventory table.
