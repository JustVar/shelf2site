# Order owner split, slice 1: who builds an order

    STATUS:   rev 2, ratified 2026-09-17 by Jus, build reads recorded 2026-09-17
    Written:  2026-09-17 by Chat, from decisions Jus made the same day
    Board:    BACKLOG-TRIAGE.md (item number assigned at board rev 42)
    Taken at: HEAD f2c9064, branch main. Anchors were read at eeb9cc4;
              f2c9064 touched none of the files cited here, so they hold.
              They age from the first commit that touches the file.
    Parents:  fulfillment-vendor-direction.md (ratified 2026-09-01) and
              fulfillment-pipeline-direction.md (direction, not built).
              This spec builds the owner concept those record. It changes
              no decision in either.

## Why

The ratified direction: consumer and C2C orders route through a third-party
hardware vendor that builds, certifies and ships; the company coordinates. Pilots
and one-off builds remain in-house work. The pipeline direction names build
ownership as the routing discriminator and sequences it first, because
routing depends on it (`fulfillment-pipeline-direction.md:39-41`, `:186`).

Today no owner concept exists anywhere in the models (READ, whole-file grep,
clean no-match). Every order renders on the Building board as if the in-house team
builds it.

## Decisions (Jus, 2026-09-17)

1. **Every order gets an owner: `in_house` or `oem`.** Default `in_house` (named `brand` until migration 086).
2. **`oem_partners` is built now, minimal.** Real FK from day one, so the
   partner name can never drift, at the cost of one small table. Columns
   are only what routing needs; contacts, terms and certification defaults
   wait for the handoff process to firm up.
3. **Existing orders stay `in_house`.** Current app orders are mock; when
   live data arrives, existing orders remain fulfilled in-house and
   OEM history starts empty at handoff. So the migration backfills nothing:
   the column default is the correct value for every existing row.
4. **OEM certification records are out of scope**, parked until the vendor
   handoff process is decided (per-unit preferred, undecided upstream).
5. **Recorded deviation from the pipeline direction.** Its line 45 says
   vendor identity is "a name on the certification record", deliberately
   not a foreign key, as a concession to an early-stage roster. Building
   `oem_partners` now supersedes that for ORDERS: identity is a real FK.
   The spec line stays as written there; this paragraph is the record.

## Three vendor identities, kept separate deliberately

The app already carries two OEM-adjacent identities. This slice adds a third
and must not tangle them (all READ):

| Identity | Where | Means | This slice |
|---|---|---|---|
| `vendor_profiles` (+ `is_oem` flag) | `models.py:465-480` | supplier/manufacturer analytics, name-matched to inventory strings | untouched |
| `OEMPurchaseOrder.vendor_name` | `models.py:1289`, free text | who a procurement PO line was placed with | untouched; possible later FK, not here |
| `oem_partners` | new | who builds, certifies and ships an ORDER | created |

Naming collision, called out so it is not re-discovered: on the fulfillment
page today, "OEM" means the PO procurement pipeline (`#board-oem`,
`fulfillment.html:923-1043`). The owner split is about who builds the order.
Same word, different concept, same page. UI labels below keep them apart.

## Schema (one migration; number read from `migrations/` at build time)

New table `oem_partners`:

    id          serial primary key
    name        varchar(128) unique not null
    active      boolean not null default true
    created_at  timestamp default now()
    updated_at  timestamp default now()

Two columns on `customer_orders` (model at `models.py:1192`):

    owner           varchar(16) not null server_default 'in_house'
    oem_partner_id  integer null references oem_partners(id)

One CHECK constraint: `(owner = 'oem') = (oem_partner_id IS NOT NULL)`, so a
partner is set exactly when the OEM owns the order, enforced by the database
rather than trusted. `owner` is a plain varchar with an app-level vocabulary
(`OWNERS = {"in_house": "In-house", "oem": "OEM"}` on the model), matching how
`order_type` is done (`models.py:1276-1281`).

`owner` is orthogonal to `order_type` (sale/pilot/try_and_buy/demo,
migration 058). A pilot is simply an order whose owner is `in_house`; no new
typing, and pilots-due-back keeps working unchanged.

Migration runs BEFORE the app restart, because the new code reads the new
columns (skill, Migrations rule).

## Routing

- **Building board shows only in-house orders.** `fulfillment_page`
  fetches all orders at `fulfillment.py:377-381`; the owner filter lands
  there, before `build_fulfillment_groups` (`:201`) and the card builders,
  so groups, counts and stage cards all follow without further edits.
  Verify at build time which of the other context numbers (`total_active`,
  `overdue_count`, `due_soon_count`) should count OEM orders, and read
  their build sites before deciding.
- **OEM-owned orders render in the existing OEM mode** (`#board-oem`) as a
  new "OEM Orders" section above the PO pipeline: coordination cards with
  order number, customer, partner name, order status, due date and unit
  count. No build stages, no certification affordances. Read-only in slice
  1 except a link to the existing order panel (decided, Jus 2026-09-17).
- Shared CSS rule applies: `.pfb-*`, `.kanban-grid`, `.k-col` span boards.
  The new section adds its own classes and edits no shared rule.
- New top-level JS function names asserted free before adding.
- Other order surfaces (`/orders/` list, search, dashboards) keep showing
  all orders regardless of owner. Only the fulfillment board routes.

## Create and edit

- The order create modal gains an owner toggle, default In-house, and a
  partner `<select>` (active partners) that appears when OEM is chosen.
  The create handler (`orders.py:268-294`) passes both through with the
  same validation shape as its other fields; the CHECK backstops it.
- Order edit gains the same pair wherever order fields are edited (read
  the edit surface before speccing the exact placement; UNREAD).
- Partner management (decided, Jus 2026-09-17): partners are created from
  the order modal itself, a small "new partner" input beside the select,
  posting to one new endpoint. No admin page until the roster grows.

## Auth and tests

- New endpoints (partner create, and partner list if not inlined into the
  page context) carry an explicit gate and census rows. Gate: the same
  tier as order creation (read the create route's gate at build time;
  UNREAD here).
- The suite total MOVES: the auth census generates cases per route, so
  each new route shifts the count. Predict the exact number in the build
  brief before running the suite.

## Gates

1. Baseline suite before editing.
2. Migration on apphost, row counts before and after (`oem_partners`
   created empty; `customer_orders` gains columns, every row `in_house`).
3. Jinja parse, `py_compile`, restart, in-container import.
4. Suite at the predicted new total.
5. Chrome MCP: In-House board shows no OEM-owned order and all existing
   orders unchanged; OEM mode shows the new section (empty state first,
   then with a test order flipped to OEM through the UI); create modal
   toggle shows and requires the partner select; console clean after a
   tracked reload. Every non-GET fetch blocked during gates, database
   fingerprints before and after.
6. Diff review, commit, four-location sync.

## Out of scope, recorded

- OEM certification records, documents and their tab section (parked on
  the handoff process; cardinality undecided upstream).
- Re-owning any existing order.
- `OEMPurchaseOrder.vendor_name` as an FK to `oem_partners`.
- N11 (`Item.vendor_id` / receipt vendor linkage): separate board item,
  separate identity (`vendor_profiles`), unaffected by this slice.
- Any change to `sku_requirements` `source: oem`, which is SKU sourcing,
  not build ownership.

## Resolved questions (Jus, 2026-09-17)

1. **Partner creation UI**: inline from the order modal. No admin page in
   slice 1.
2. **OEM order cards**: read-only coordination cards, with a link to the
   existing order panel. Status edits stay where they are today.

## After build (rev 2)

Six reads resolved while building N20, recorded here rather than edited into
the sections above. Anchors in this section are at the N20 commit 2.

- The edit surface is the Edit Order modal in `order_detail.html`, beside the
  order type select.
- The create route gate is `require_provisioning_manager`, and the new partner
  route `POST /api/oem-partners/` carries the same gate.
- The three In-House counters are in-house only by structure: the card list is
  built after the owner split, and the columns and counters read it. The OEM
  board carries its own OEM Orders count tile.
- The SE coverage panel is not owner-filtered and stays as it is.
- An OEM order card links to the order page, `/orders/{id}`, which is what the
  In-House card does. There is no panel link.
- The migration number is 074. The create handler starts at `orders.py:228`
  and its constructor spans `:268-294`.
