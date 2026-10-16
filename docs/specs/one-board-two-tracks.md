# Fulfillment: one board, two tracks

    STATUS:   rev 1, 2026-10-16. Shape decided by Jus on 2026-10-16
              (section "Decided"). The details under "Design" are mine
              (Claude) and go to Jus with the final review; they change
              nothing he decided.
    Parents:  fulfillment-vendor-direction.md (vendors build, certify and
              ship) and order-owner-split-slice-1.md (owner and partner).
              This spec replaces the board those two layered onto. It
              keeps their decisions.

## Why

The fulfillment page grew one board per process: an order pipeline grouped
by build stage, a deployment pipeline, an OEM purchase-order pipeline, and
read-only OEM order cards, behind an In-House / OEM toggle. A reader needs
the whole history to know where an order is. A field census on 2026-10-16
found the following (REPORTED by a read-only census agent; the lines cited
here were re-read before this spec relied on them):

- The order cards sit in columns by build stage, not by order status
  (`build_fulfillment_groups`, fulfillment.py).
- Five handlers in the page JS are reachable from no markup: drag and drop,
  the pipeline filter, `jumpToCard`, `setOrderType`, and the card flash.
- The "Build Certification & Close" button only stops event propagation.
- OEM-owned orders leave the in-house columns, so the deployment and PO
  pickers cannot target them.

The direction since 2026-09-01 is that sale orders are built, certified
and shipped by a vendor, and the team's own hands-on work is pilots and
demos lent from stock. The board should show exactly that.

## Decided (Jus, 2026-10-16)

1. **One board, two tracks.** One card per order.
2. **Vendor orders** move through Ordered, Building, Shipped and
   Installed, and carry the vendor's documents.
3. **Pilots and demos from stock** move through Assigned, Shipped, Out at
   site and Returned.
4. **POs, deployments and certifications move onto the order page.**
5. **Filter tabs:** All, Vendor, and Pilots & demos.
6. **Tiles:** Open, Late, Due back in 30 days, and Docs missing.

## Design

### Which track an order is on

The order type picks the track:

| Order type | Track |
|---|---|
| `sale` | Vendor |
| `pilot`, `demo`, `try_and_buy` | Pilots & demos |

Owner and partner keep their meaning: who builds the order. A sale order
built in house is still a sale and still sits on the Vendor track, with
"In-house" where the partner name would be. No data moves.

### Columns come from the stored status

The stored vocabulary (`CustomerOrder.ORDER_STATUSES`) does not change, so
nothing keyed on it breaks. Each track maps it to its columns:

| Stored status | Vendor column | Pilots & demos column |
|---|---|---|
| new, sourcing | Ordered | Assigned |
| building, testing | Building | Assigned |
| shipped | Shipped | Shipped |
| delivered | Shipped | Out at site |
| installed | Installed | Out at site |
| cancelled | off the board | off the board |

**Returned is derived, never stored.** A pilot is Returned when it has at
least one unit and none of them is still out (`returned_date` set on
every item-linked unit). That is the same rule the Pilots Due Back page
already uses to drop an order (c2c.py, `still_out == 0`).

The mapping lives in one module, `app/order_tracks.py`. The board, the
order page and the tests read it from there. A test pins every stored
status to a column on both tracks, so adding a status fails the suite
until it is placed.

### Moving an order: one advance route

`POST /api/orders/{id}/advance` with `{"to": <column key>}` is the only
way the board and order page move a card. It checks that the move is the
next step on the order's track, then makes it:

| Track | Move | What it does |
|---|---|---|
| Vendor | Ordered to Building | status `building` |
| Vendor | Building to Shipped | status `shipped`, `shipped_date` today if unset |
| Vendor | Shipped to Installed | status `installed`, `delivered_date` today if unset |
| Pilots | Assigned to Shipped | needs at least one unit; status `shipped`, `shipped_date` today if unset, units go Deployed |
| Pilots | Shipped to Out at site | status `delivered`, `delivered_date` today if unset |
| Pilots | Out at site to Returned | every still-out unit gets `returned_date` today |

Every move writes an `order_advanced` audit event. The existing gates
still apply:

- A sale order needs a customer PO to leave Ordered.
- A cancelled order cannot move.
- Shipping marks units Deployed through the same code the ship route
  uses, factored into one helper.

The full edit form keeps its status field for corrections. It now shows
the track's column names.

### Vendor documents

New table `order_documents`, the files-only record the pipeline direction
asked for (no parsing):

    id, customer_order_id (FK, CASCADE), kind, original_name, stored_name,
    content_type, size_bytes, note, uploaded_by, uploaded_at

`kind` is one of `certification`, `validation`, `shipping`, `other`.

- Files are stored under `ORDER_DOC_UPLOAD_DIR/<order id>/`. The default
  is `data/order-docs`.
- Allowed types are PDF, images, text and Office files, up to 25 MB.
- Routes: upload `POST /api/orders/{id}/documents`, download
  `GET /orders/documents/{doc_id}`, delete
  `DELETE /api/orders/documents/{doc_id}`. Uploads and deletes are
  audited.

**Docs missing** means a Vendor order at Shipped or Installed with no
`certification` document. It is the board tile, and a badge on the card
and on the order page. Pilots never count.

### The board

- **Header:** search, scan to find a serial, export, and New Order.
- **Tiles:**
  - Open: on the board and not finished. Vendor orders finish at
    Installed; pilots finish at Returned.
  - Late: a Vendor order past its due date and not Installed, or a pilot
    past its due date and not shipped, or a pilot with units still out
    past its expected return.
  - Due back in 30 days: pilots with units still out and an expected
    return within the next 30 days.
  - Docs missing: as defined above.
- **Tabs:** All, Vendor, and Pilots & demos. All shows both tracks as two
  lanes.
- **Card:** order number, customer, type badge, partner (Vendor) or return
  date (pilots), units out or required, due date with a late flag, a docs
  badge on Vendor cards, and one next-step button that calls the advance
  route.
- **Removed:**
  - the In-House / OEM toggle;
  - the build-stage board and its SKU groups;
  - the deployment kanban, the OEM PO kanban and the read-only OEM cards;
  - the coverage and stock panels;
  - the slide panel;
  - the unreachable JS listed above.

  Build certification and the provisioning queue stay where they are for
  internal and legacy builds; the order page links to them per unit.

### The order page

New or moved sections, top to bottom:

1. **Progress:** the track's steps, the current one marked, and the
   next-step button.
2. **Units:**
   - The linked units: serial, SKU, state, and returned date.
   - Per-unit links to their build or C2C certification history.
   - Assign from stock: the candidates the slide panel used, through the
     same assign-items route.
   - Return per unit, and Return all on loan orders.
3. **Shipping:** the ship form that was in the slide panel.
4. **Vendor documents** (Vendor track): upload, list, download and delete.
5. **Deployments:**
   - The order's site visits: create, change status and assign units,
     moved from the board's deployment pipeline.
   - Installation certification: upload the PDF and record who certified
     and who installed.
6. **Purchase orders:** the existing table. Its status choices become the
   model's six values: the page offered `partial` and `received`, which
   the database CHECK rejects.

### Gaps closed on the way

- The ship route refuses a cancelled order, and audits what it changes.
  Today it would mark a cancelled order's units Deployed and write no
  event.
- The OEM PO create and update routes check the status against the
  model's vocabulary, so a bad value gets a 400 rather than an
  IntegrityError.

## Out of scope

- An OEM certification record with a per-unit or per-order scope. The
  pipeline direction keeps it open; vendor documents are files on the
  order until that is decided.
- OEM partner editing. Partners are still created from the order form.

## Slices and gates

1. **Model and rules.** `order_tracks.py`, the `order_documents` model and
   migration 087, and the advance and document routes, with tests.
   - Every stored status maps to a column on both tracks.
   - Each advance step does what the table says, and every illegal step
     is refused.
   - A Returned pilot derives from its units.
   - A document round-trips.
   - Each test must fail on the previous commit.
2. **Order page.** Progress, units, shipping, documents, deployments, PO
   vocabulary.
   - Gate: Chromium smoke of each section on both tracks, console clean.
3. **Board.** The new template and route, the tour updated, the
   tests that pinned old markup moved to the order page.
   - Gate: tiles match counts computed in SQL on the demo data.
   - Gate: each tab shows only its track.
   - Gate: console clean in both themes.
