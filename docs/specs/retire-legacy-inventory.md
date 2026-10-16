# Retire the legacy inventory model (board item 30)

Status: RATIFIED 2026-09-25 by Jus. Draft v2 folded in his answers to the
v1 open questions (section 10). Written at
HEAD 9cdef41. Every code anchor below was read on an LF copy of the
workstation clone at that HEAD (tree clean, four locations confirmed). Every
live count was read on apphost the same day through psql, output returned
as files (i30_cols, i30_deps, i30_links, i30_residue, i30_cams, i30_cam2).
Line numbers age from the commit that lands this file; re-read with grep -n
before editing.

Grounding labels: READ (read this session), REPORTED (from an earlier
session or another document, not re-read), UNREAD (nobody has looked).

## 1. The problem

Two inventory models live side by side.

- `item_schema.items`: 548 rows (READ). The system of record. Inventory,
  item detail, intake, triage, search, decommission, containment and the
  map read it.
- 22 legacy per-category tables in `public` (`edge_boxes`, `computers`,
  `nucs`, ...): 336 rows (READ), registered in `TABLE_MODELS`
  (`models.py:1699`). Warranty, credentials, site assignment, pending
  approval, provisioning's legacy path, build certification, vendor
  analytics and several JSON APIs still dispatch over them, so they cannot
  see items.

Registering `Item` in `TABLE_MODELS` was probed and rejected
(`c2c-catalog-and-accessories.md:252`, option B1: it pollutes about 15
legacy consumers). `CLAUDE.md` recorded retirement as the end state,
blocked on warranty and components; since item 30 S1 it points here.

## 2. Decision (Jus, 2026-09-25)

**Retire the legacy model.** Every live link moves to items, every legacy
reader and writer is switched or retired, then the 22 tables, `TABLE_MODELS`
and the legacy helpers are dropped. One inventory model remains.

## 3. Overlap and residue (READ 2026-09-21, recounted 2026-09-25)

- 243 of 259 distinct legacy serials (94%) exist in items. Legacy and items
  row totals were unchanged between the two reads (336 and 548).
- Serial columns: `serial` on 21 tables, `gpu_serial` on `gpus`;
  `item_sn` on items.
- 16 legacy serials are not in items; 25 legacy rows repeat a serial
  another legacy row carries (11 are NUCs also recorded in `edge_boxes`).
- `nas_devices` has 0 rows.

**Ruling (Jus, 2026-09-21): NUCs are PCs, not edge boxes.** The 11
`edge_boxes` rows that share a serial with `nucs` are leftovers from when
they were edge boxes. Carried NUCs become `computer` items.

## 4. What still points at legacy rows (READ)

Link columns found in the catalog (`information_schema.columns`):

| Table | Link | Rows pointing at legacy | Rows pointing at items |
|---|---|---|---|
| `device_components` | `parent_table/parent_id`, `component_table/component_id` | 31 rows (62 ends) | 0 |
| `device_credentials` | `device_table/device_id` | 40 | 0 |
| `device_provisioning` | `device_table/device_id`, plus `item_id` (migration 056) | 6 | 7 |
| `pending_devices` | `suggested_table` | 1 (a suggestion, not a link) | 0 |
| `device_assignments`, `device_warranties`, `vendor_trials`, `device_dispositions`, `public.intake_photos`, `public.maintenance_log`, `public.receipts` | `device_table/device_id` | 0 | 0 |

`audit_log.target_table` and `delete_requests.target_table` are history,
not dispatch. They keep their stored strings.

### Movability of the 108 link ends (READ, `i30_links.txt`)

| Result | Ends |
|---|---|
| Legacy serial matches exactly one item | 62 |
| Legacy serial matches no item | 29 |
| Legacy row has no serial | 17 |
| Legacy row missing | 0 |
| Serial matches several items | 0 |

The 46 unmatched or unserialled ends sit on 24 legacy rows (READ,
`i30_residue.txt`):

- `computers` 28 `INTERNAL-LLM-01`: parent of 16 components.
- `computers` 29 `INTERNAL-DELL-01`: parent of 8 components, which are
  `hard_drives` 7 to 14, all with no serial.
- `edge_boxes` 117 to 121 (`SEED-GX-1`, `SEED-GX-2`, `SEED-IT-1`,
  `SEED-IT-2`, `SEED-UM-1`): provisioning rows 238 to 242.
- `cameras` 12, 13, 21, 23, 24, 25, 26, 35, 40: one credential each
  (credential ids 16, 17, 23, 25, 26, 27, 28, 35, 39). Seven are blank
  spreadsheet rows (no manufacturer, model, serial, MAC or IP). Cameras 23
  (Hanwha WDA320) and 24 (Hanwha WBS534) carry model and IP only; their
  model-only candidates, items 672 and 673, disagree on manufacturer.

## 5. Data rules (decisions, Jus, 2026-09-25)

The migration applies RULES to whatever data exists when it runs. The
spreadsheet re-upload timing is unknown, so nothing below is keyed on a
hard-coded id except the two named drop sets, and the dry run must
reproduce the section 4 snapshot on today's data.

**R1. Re-point by serial.** A link end whose legacy row has a serial that
matches exactly one item (`upper(trim())`, ignoring NULL, empty and `-`)
re-points to that item.

**R2. Carry in, then re-point by mapping.** These legacy rows become new
items, and the migration records a legacy (table, id) to item id map that
their links re-point through:

| Legacy rows | New item category | Why |
|---|---|---|
| `computers` 28, 29 | `computer` | internal PCs with component history |
| `hard_drives` 7 to 14 | `storage_drive` | components of computers 29; carried without a serial |
| `edge_boxes` 41 (`4NVWQ54`) | `edge_box` | real-looking, unlinked |
| `hard_drives` 19 (`BC0DD8DJ`) | `storage_drive` | real-looking, unlinked |
| `nucs` 12 to 15 | `computer` | real-looking, unlinked; NUCs are PCs |

16 new items (migration 081). Each carries a note naming its legacy
origin (`migrated from legacy <table>:<id>`) and attributes
`import_source` `legacy-item30`, `legacy_table`, `legacy_id`.
`public.legacy_item_map` records every legacy row a link needed, rule
R1 or R2; it has no FK to items, like `csv_import_map`. **Amended at
build (Jus, 2026-09-28):** `cameras` 45 and 73 were dropped from the
carry-in list. Camera 45 (`9147404`) is item 700 (`09147404`) and camera
73 carries the MAC of item 613 (READ), so both are already items. Field
mapping (READ and ratified 2026-09-28): computers take `device_name`,
`device`, `assigned_to`, `purpose`; drives take maker and model, 10000
GB, `drive_type`; edge box 41 takes SKU `PVA-16-30NR`, `uuid`, form
factor; NUCs are named `NUC` with MAC and purpose. Location resolves to
a non-customer site by name, else stays in notes. Status: computers,
`In Use` and `Customer Lab` to Deployed; `In-house Inventory` and `In
Packaging` to Unassigned; the Dell drives to Installed through R4.

**R3. Drop.** Deleted, by statements handed to Jus, never run by Chat or
Code:

- provisioning rows 238 to 242 (the SEED fixtures);
- the 9 camera credentials in section 4. Camera logins are shared per
  vendor; any needed are re-entered by hand after the re-upload;
- **added at build (Jus, 2026-09-28):** customer orders 72 (`AT-9003`)
  and 73 (`AT-9004`), the fixture orders of provisioning 240 to 242.

Committed 2026-09-28 after a preview and a backup
(`asset_tracker_2026-09-28_1646.dump`). The cascades removed every
`build_certification` row (5) and file row (7) and 2
`deployment_records`. The certificate files on disk are now orphaned.

Legacy rows with no links and no carry-in (`edge_boxes` 22 serial `777`,
the SEED edge boxes, the duplicate rows) go with their tables.

**R4. Components become containment events.** Each `device_components` row
becomes `item_schema.component_history` events on the re-pointed ids:
`installed` with `slot_label`, `installed_date` as `action_date`,
`installed_by` as `performed_by`, `notes`; plus `uninstalled` on
`removed_date` when set. No row has `removed_date` set (READ
2026-09-28). Migration 066 already applied R4 to rows 1 to 7 (edge box
to GPU) and records them in `component_migration_map`; migration 081
does rows 8 to 31 in the 066 event format and map, so either one skips
the other's rows on a re-run.
`DeviceComponent` has no references in `app/` outside `models.py` (READ),
so the legacy table has no live reader.

**R5. Provisioning.** The one surviving legacy row (#243, `cameras` 1)
matches one item by serial (READ) and gets `item_id` under R1.

## 6. Link shape (decision, Jus, 2026-09-25)

**Real `item_id` foreign keys to `item_schema.items`**, the migration 056
pattern. After the data moves, `device_table` and `device_id` are dropped.

| Table | End state |
|---|---|
| `device_credentials` | `item_id` FK |
| `device_warranties` | `item_id` FK (0 rows; the feature must work on items) |
| `device_assignments` | `item_id` FK (0 rows; keeps Sites assign and return). **Superseded 2026-09-28 (Jus):** assignments retired in S4, the table drops in S5 |
| `device_provisioning` | `item_id` FK (exists); `device_table`, `device_id` dropped |
| `pending_devices` | `suggested_table` replaced by a suggested item category |
| `device_components` | dropped after R4 |
| `nas_drives` | dropped after R6 (not in `TABLE_MODELS`; FK to `nas_devices`, `models.py:906`) |
| `vendor_trials`, `device_dispositions` | dropped (trials and disposal retired as item 29) |
| `public.intake_photos`, `public.maintenance_log`, `public.receipts` | dropped (0 rows; items has its own copies) |

## 6a. Categories (decisions, Jus, 2026-09-25)

`item_categories` (23 values, READ at `models.py:1901`) gains four values
by `ALTER TYPE ... ADD VALUE`: **`phone`, `webcam`, `printer`, `nas`.**

- Legacy `phones` (7), `webcams` (8) and `printers` (2) have their own
  categories from now on.
- **A NAS is a system**, the parent unit, category `nas`. **Its drives are
  `storage_drive` items contained in it** through `component_history`, the
  same way PC and edge box components are.
- **R6. NAS drives.** Each `nas_drives` row becomes a `storage_drive` item
  (matched by `serial_number` under R1 where one exists) plus an
  `installed` event on its NAS item, with `bay_number` as `slot_label`.
  `nas_devices` has 0 rows (READ), and `nas_drives.nas_device_id` is a NOT
  NULL FK to it (READ in the model), so `nas_drives` should be empty too.
  That is an inference from the model; the S2 dry run counts it. READ
  2026-09-28: 0 rows, so R6 has nothing to move.
- **Pre-read for S2 (done 2026-09-28).** No phone, webcam or printer serial is
  among the 16 legacy-only serials (READ 2026-09-21), so every serialled
  row in those tables has an item twin under some existing category.
  Five legacy webcams lack a serial (READ 2026-09-28). List the twins
  and their current category, and the unserialled rows; S2 recategorises
  the twins to the new values after Jus confirms the list.
- **Confirmed list (Jus, 2026-09-28), moved by migration 081:** phones,
  items 882 to 888 (from `office_equipment`); printers, items 924 and
  925 plus 926 (HP MFP 3301fdw); webcams, items 916 to 923 (from
  `pc_accessories`; the five unserialled legacy webcams matched by model
  and owner) plus 929 (Owl); NAS, the four QNAP TS-264 items 773, 774,
  775 and 946 (from `computer`).

## 7. Writers (decisions, Jus, 2026-09-25)

Three code paths still CREATE legacy rows (READ):

| Writer | Anchor | Decision |
|---|---|---|
| Pending approve | `pending.py:88`, `POST /pending/{device_id}/approve` | **retarget**: approval creates an item |
| Intune sync | `intune_routes.py:194`, `POST /api/intune/sync` | **retire**: not used here |
| Spreadsheet sync | `spreadsheet_sync.py:275`, `:303`, admin page | **retire** |

**Gap recorded, not solved here.** No code in the repo bulk-loads rows into
items (READ: the only `Item(` constructor in `app/` is `intake.py:181`; the
four import scripts in `scripts/` write legacy tables). The 548 items came
from Casey's CSV through a one-time migration (067, REPORTED). The planned
spreadsheet re-upload therefore needs a new items importer, matching by
serial and keeping ids stable so re-pointed links survive. **New board
item, spec-first, not part of item 30.**

## 8. Code census (READ, name-based, at 9cdef41)

`TABLE_MODELS` is referenced in 16 files outside `models.py`. Counting
legacy device classes, link classes and the legacy helpers (`get_serial`,
`get_display_name`, `compute_completeness`), the census covers 19 files, 51
route functions (25 GET, 22 POST, 3 DELETE, 1 PUT) and 17 helpers. Full
list in the appendix. By area:

- **Credentials:** `creds.py` `GET /{table_name}/{device_id}`, mounted at
  `/api/credentials` (`main.py:521`). Its only caller is
  `showCredentials` (`base.html:830`), and nothing calls `showCredentials`
  (READ, all 56 templates and 19 JS files), so credentials have no UI
  today. **Decision: a credentials section on item detail**, shown to users
  with `User.has_credentials_access` (`models.py:683`), reading
  `/api/credentials/items/{id}` or an item-native equivalent. The dead
  modal and `showCredentials` go.
- **Warranty:** `warranty.py` (7 routes, `_resolve_device_label`).
  `CLAUDE.md:223` records it as non-functional for items today.
- **Site assignment:** `sites.py` (6 routes), `bulk.py` assign and export.
- **Lifecycle page:** `lifecycle.py`, `GET /device/{table}/{id}/lifecycle`
  and `GET /api/device/{table}/{id}/lifecycle`, rendering
  `partials/lifecycle_panel.html`. No template, JS or Python links to either
  (READ, grep rc=1); its entry points were the per-category detail pages
  retired in 151da9b. **Decision: retire** both routes and the partial.
- **Receiving and pending:** `pending.py` approve and dismiss,
  `receiving.py` `find_serial_anywhere`, `_route_scan`, `submit_device`;
  `support.py` review queue, `sidebar_cache.py` counts.
- **Provisioning:** `provisioning.py` (6 routes plus `_resolve_device_name`,
  `_resolve_deployment_type`).
- **Build certification:** `fulfillment.py` certification routes (9) join
  `EdgeBox` on `device_table == "edge_boxes"`; `submit_cert_qa` refuses any
  other table (`fulfillment.py:1545`). **Decision: retarget to items**
  (category `edge_box`).
- **Fulfillment and orders:** `_stock_snapshot`, `fulfillment_page`,
  `fulfillment_panel_state`, `_resolve_unit_serial`; `orders.py`
  `_sku_availability` (matches `model.ilike` across every legacy table) and
  `order_detail`.
- **Map:** `_collect_units`, `_needs_location`, `map_set_location`. The map
  is already items-first; legacy edge boxes load only to hide their items
  twins and pass on order linkage (`map.py:193-228`).
- **Vendors:** `_vendor_analytics`, `vendors_list`, `auto_create_vendors`.
  **Decision: item 30 removes the legacy half only; N2 owns the items
  rebuild of vendor analytics.**
- **Admin:** `admin.py` `oui_reference` (MACs from six legacy classes)
  switches to the item MAC columns.
- **Legacy JSON APIs:** `api.py` (mounted at `/api`, `main.py:520`)
  `GET /api/devices/{table}` (legacy rows of one table), `GET /api/stats`
  (legacy counts), `GET /api/vendors` (distinct legacy vendor strings; not
  the `/api/vendors/...` routes the Vendors page calls). No caller in the
  app (READ). Outside consumers UNREAD. **Decision: retire all three.**
  `GET /api/audit-log` in the same file is not legacy and stays.
- **NAS:** `nas_drives.py` over `NASDevice` and `NASDrive`. **Decision:
  retire**; NAS drives become containment (R6), managed with the existing
  install, move and remove flow.
- **Retired with their writers:** `intune_routes.py`, `spreadsheet_sync.py`
  and the admin spreadsheet sync routes.

## 9. Slices (proposed, for review)

Each slice ships alone with the full gate set. Order matters: schema before
data, data before readers, readers before drops.

1. **S1 schema, additive.** Nullable `item_id` FKs on `device_credentials`,
   `device_warranties`, `device_assignments`; suggested category on
   `pending_devices`; the four new `item_categories` values (section 6a).
   Migration 080. Suite total unchanged. **Amended at build (Jus,
   2026-09-28):** the app's hand-kept category lists gain the four values
   in the same commit (`CATEGORY_COLORS`, `CATEGORY_DISPLAY_NAMES`,
   `CATEGORY_ATTRIBUTES`; `nas` joins `UNIT_CATEGORIES` and receive's
   `CTM_UNIT_CATS`), so the new values appear in category dropdowns. The
   three new links join `ITEM_LINKS` in `app/delete_requests.py`, so an
   item they point at cannot be deleted. Receiving's
   `TARGET_TABLE_TO_CATEGORY` (phones, webcams, printers, NAS) is a
   writer and moves in S3.
2. **S2 data.** First the 6a pre-read (phone, webcam, printer twins and
   their categories), confirmed by Jus. Then one re-runnable, rule-driven
   migration script: R2 carry-ins, R1 and R2 re-points, R4 and R6
   containment events, R5, the confirmed recategorisations, and
   `pending_devices.suggested_category` from `suggested_table`. Dry run
   prints the section 4 counts and the `nas_drives` count and must match
   before the write. R3 deletes are handed to Jus as statements, run before
   the write. Built as migration 081 (dry run by default, `--apply` to
   commit, one transaction).
3. **S3 writers and dead routes.** Pending approve creates items; scan
   intake maps phones, webcams, printers and NAS to their new categories
   (`TARGET_TABLE_TO_CATEGORY`). Retire
   Intune sync, spreadsheet sync, the lifecycle page and its JSON twin, the
   three legacy JSON APIs and `nas_drives.py` (routes, templates, JS, tours,
   admin nav). Suite total drops by the retired routes through the endpoint
   auth census; predict it from the census before running. **Built
   2026-09-28:** approve creates an `Unassigned` item through the shared
   `create_item` path and links the receiving unit row to it; the pending
   path also stores `suggested_category`. 16 routes retired (Intune 4,
   spreadsheet sync 3, lifecycle 2, legacy JSON 3, NAS drives 4), with
   their templates, JS, nav links, the dashboard import action and two
   tours. Suite 1074 to 1038 passed, 39 skipped (34 census cases, 2
   template-module cases). `docs/ENDPOINT_AUTH_CENSUS.md` reconciled in the
   same commit. Left for S5: the `IntuneSyncLog` model and table, the
   `INTUNE_*` and `SPREADSHEET_PATH` settings, and receiving's NAS drive
   serial lookup.
4. **S4 readers, one area per commit:** credentials (item detail section,
   dead modal removed); warranty; sites and bulk assign; receiving and
   review queue; provisioning; build certification; fulfillment and
   orders; map (pre-read first, then drop the legacy branch); vendors
   (legacy half removed) and admin OUI. **Credentials built 2026-09-28:**
   `GET /api/credentials/items/{item_id}` replaces the per-table route;
   item detail shows a Credentials section to users with credentials
   access, only when the item has any, and loads them on demand (each load
   audit-logged). Values render as text, never HTML; the retired modal
   injected them unescaped. The dead modal and `showCredentials` are gone.
   The vault stays read-only in the app: there is no create or edit route.
   **Warranty built 2026-09-28, scope cut by Jus:** warranty is basic
   tracking for internal inventory items (item, vendor, start, end,
   notes). Customer warranties on shipped hardware are tracked by the OEM,
   not in the tracker, so the Fulfillment warranty design is dropped. RMA
   claims and internal loaners are retired, superseding the 2026-06-15
   note that loaners kept warranty alive (all their tables held 0 rows,
   READ 2026-09-28). Migration 082 drops NOT NULL on `device_table` and
   `device_id` for `device_warranties` and `device_assignments` (0 rows
   each; sites is the next area and needs the same) and adds
   `device_warranties.notes`. `POST /api/warranty` takes `item_id` and
   requires start and end; the form fills end from a term in months, and
   end stays editable. A warranty is a delete blocker, so create refuses an
   item with a pending delete request (`locked_ids`, listed in
   `tests/test_delete_request_lock.py`). A new `GET /api/warranty/item-search` (editor)
   feeds the item picker; `POST /api/claim` and `PUT /api/claim/{id}` are
   retired. Item detail lists an item's warranties read-only, and the
   sidenav gains a Warranties link (nothing linked the page before, READ).
   The vendor profile still counts warranties and claims; that moves with
   the vendors area.
   **Sites built 2026-09-28, scope cut by Jus:** device-to-site
   assignments are retired, superseding the section 6 decision to keep
   assign and return. The assign form had been dead since S3 (it loaded
   devices from the retired legacy JSON APIs) and `device_assignments`
   never held a row; an item's place is already `items.location_id`, and
   checkouts cover custody. A site page now lists the items placed there
   (name, category, serial, status) and the sites list counts them. The
   three assignment routes and the provisioning completion hook that
   auto-created an assignment are gone. `bulk.py` (status, assign, export)
   had no caller anywhere (READ on apphost) and is retired with its
   allowlist entry. The sidenav gains a Sites link (nothing linked the
   page before, READ on apphost).
   **Vendors and admin OUI built 2026-09-28 (Jus):** the legacy half is
   removed as decided, and a profile now lists the items whose `vendor_id`
   points at it (0 today: no item carries a vendor, READ). The quality
   score, RMA and trial stats are dropped with it: they were computed only
   from claims and trials, both retired features, and with no legacy
   devices the score read a constant 100. Vendor auto-create (seeded from
   legacy vendor strings) is retired with its route and button. The OUI
   reference counts items by either item MAC column instead of six legacy
   MAC tables. N2 still owns any richer vendor analytics.
   Left for S5, not legacy data readers: the OUI `maps_to_table` dropdown
   and the audit-log label lookup in `api.py` still use
   `TABLE_DISPLAY_NAMES` as a vocabulary, and need a replacement before it
   drops.
   **Receiving, review half, built 2026-09-28:** the review queue and the
   sidebar pending count filter on `suggested_category` through new
   `get_approvable_categories` / `user_can_approve_category` (edge_box keeps
   the sites-admin gate the edge_boxes table had). The queue offers item
   categories; approve takes `item_category` and still maps a legacy
   `target_table`, and dismiss uses the same category gate. The scan-lookup
   half waits on the Lab_Network.xlsx reconcile: 8 legacy serials (the two
   skipped cameras, test edge box 22 and SEED fixtures 117 to 121), 2 MACs
   (items 910, 634) and 1 UUID (item 570) that items lack, 3 duplicate MACs
   among items, and 5 uncatalogued edge box part numbers (let go, Jus).
   **Receiving, scan-lookup half, built 2026-09-29, scope cut by Jus:**
   the reconcile workbook is skipped; data is re-imported later, so the
   findings above carry no data fixes. Serial, MAC, UUID and SKU scan
   lookups and the duplicate check read items only (the legacy tables,
   `nas_drives` and the edge box part number fallback are gone from them).
   The receive form keeps its target keys, now labelled by
   `RECEIVE_TARGET_LABELS` in `receiving.py` instead of
   `TABLE_DISPLAY_NAMES`, and direct intake uses the category approval
   gate. Left for S5: `POST /api/receive/photo` and its serve route still
   write and read `public.intake_photos` (0 rows, no caller in the app,
   READ 2026-09-29); retire them before that table drops.
   **Map pre-read dropped (Jus, 2026-09-29):** data is re-imported later,
   so section 10 item 6 is not run before the map commit.
   **Map built 2026-09-29:** the map reads items only. `_collect_units`,
   `_needs_location` and the deal lookup drop the legacy edge box branch,
   the `device_table` linkage and the `deployment_type` inference (and
   its popup note); `POST /map/set-location` takes `kind` item only. On a
   restore of the 2026-09-29 02:15 dump (READ locally), the admin map goes
   from 7 units to 2 and the needs-location list from 63 to 50: the 5 and
   13 that leave are legacy edge boxes, which the re-import brings back as
   items.
   **Provisioning built 2026-09-29:** provisioning runs on edge box items.
   Create takes `item_id` (category `edge_box`, refused while the item has
   a pending delete request) and writes the `items` sentinel row with the
   stage machine; the create dropdown
   (`GET /api/provisioning/devices/edge_boxes`, path kept) lists edge box
   items with a serial and no active record. Queue, detail, board, export
   and the Zendesk match read the item: serial, SKU, `sku_version` and
   `deployment_type` attributes, MACs and `platform_uuid`. The registration
   UUID check and the completion update (status Deployed) act on the item.
   Advance now refuses rows with no stages (the C2C and order label rows)
   instead of every row with an `item_id`. Nothing in `provisioning.py`
   reads `device_table` or `device_id` any more; the sentinel writes in
   `provisioning.py`, `c2c.py` and `orders.py` go in S5 with the columns.
   **Build certification built 2026-09-29:** the index, detail page,
   report and the QA, hardware, files, close, cancel and recertify routes
   resolve the unit through `device_provisioning.item_id` to an
   `edge_box` item (`_cert_edge_box`: serial, `platform_uuid`, SKU), never
   `edge_boxes`. The index lists every order-linked edge box item, so
   stock edge boxes assigned to an order appear there too. Certification
   rows still key on `oem_serial` and the provisioning id, unchanged.
   **Fulfillment and orders built 2026-09-29:** the stock snapshot counts
   `edge_box` items by SKU (`item_sku`, else `item_pn`), busy when
   an active record links them. The Building board's devices are edge box
   item rows WITH stages (the stage machine), and the unit count adds
   still-out item rows WITHOUT stages, so no row counts twice. The SE
   counts, the order panel, `_resolve_unit_serial` (fallback now
   `Provisioning #id`), the order page label and `_sku_availability`
   (ready item stock through `candidate_items` only) read items. S4 is
   complete: no route module reads `TABLE_MODELS`, a legacy device class
   or `get_serial`/`get_display_name` any more. Left for S5 besides the
   list above: `api.py` imports `compute_completeness` and labels audit
   rows with `TABLE_DISPLAY_NAMES`; `admin.py` passes `TABLE_DISPLAY_NAMES`
   to the OUI page; the order cancel audit and the `items` sentinel writes
   still name `device_table` and `device_id`.
5. **S5 drop.** The 22 tables and their models, `TABLE_MODELS`,
   `TABLE_DISPLAY_NAMES`, `InventoryMixin`, the legacy helpers,
   `device_table`/`device_id` columns, `device_components`, `nas_drives`,
   `vendor_trials`, `device_dispositions` and the three empty `public`
   copies. From the S4 sites cut: `device_assignments`, the
   `Site.assignments` relationship and `DeviceAssignment.OWNERSHIP_TYPES`.
   From the S4 warranty cut: `warranty_claims`, and the
   `device_warranties` columns the basic form no longer writes (scope,
   tier, type, holder, registration, coverage, renewal, purchase date and
   the four loaner columns). `DeviceWarranty` inherits `InventoryMixin`, so
   dropping the mixin needs its columns resolved on that model too. `purchase_price` on legacy models goes with them
   (`receipts-permission-and-financial-drop.md:195`). A backup is taken
   first (`scripts/at-backup.sh`); the legacy `hardware_inventory` DB on the
   host stays as the older reference (`CLAUDE.md:32`).
   **Built 2026-09-29 in two commits, after apphost was retired (Jus).**
   There is no live host, so both were built and tested against a restore
   of the 2026-09-29 02:15 UTC dump; the drop runs on the new host after
   that dump is restored. **S5a, code:** the legacy models,
   `InventoryMixin`, `TABLE_MODELS`, `TABLE_DISPLAY_NAMES`, the site-admin
   table set and the legacy helpers (`compute_completeness`,
   `get_serial`, `get_display_name`, `get_status`, `get_mac`,
   `user_can_approve_table`, `get_approvable_tables`) are gone, with
   `IntuneSyncLog`, `DeviceComponent`, `DeviceAssignment`,
   `WarrantyClaim`, `VendorTrial`, `DeviceDisposition` and `NASDrive`.
   `DeviceWarranty` maps its id and timestamps itself. The legacy table
   names survive only as a label vocabulary in `app/table_labels.py`
   (audit history and the OUI `maps_to_table` hint). The `INTUNE_*` and
   `SPREADSHEET_PATH` settings and eleven scripts that wrote or read the
   legacy tables are removed (the importers, completeness backfills,
   custom-build linker, NAS seed, camera manufacturer fix, show-on-map
   add, inventory reset), with `tests/test_model_accessors.py`.
   `migrations/001_add_procurement_fields.py` still imports
   `TABLE_MODELS`; it is applied history and is not re-run.
   **S5b, schema:** migration 083 (dry run by default, `--apply` to
   commit, one transaction) drops the 22 legacy tables, `device_components`
   and the empty `public.maintenance_log` that points at it, `nas_drives`,
   `vendor_trials`, `device_dispositions`, `device_assignments`,
   `warranty_claims`, `intune_sync_log` and the empty `public.receipts`;
   the `device_table`/`device_id` pair on provisioning, credentials and
   warranties; the unused warranty columns; and
   `pending_devices.suggested_table`. Guards run first: every provisioning
   and credential row has an `item_id`, every pending row with a table has
   a category, warranties, assignments and claims are empty. On the
   restored dump it dropped 367 rows across 31 tables (READ locally) and
   reports ALREADY APPLIED on a rerun. The code in the same commit stops
   writing the `items` sentinel (`c2c.py`, `orders.py`,
   `provisioning.py`), drops the columns from the models, drops
   `device_assignments` from `ITEM_LINKS`, and the pending category
   fallback is `network`. **Kept on purpose:** `public.intake_photos` (the
   receive photo routes, which have no caller in the app, still write it;
   retiring them is a follow-up), `legacy_item_map` and
   `component_migration_map` (migration history). **Order on the new
   host:** restore the dump, run 083 with `--apply`, then start the app at
   this commit or later. The code does not run against the pre-083 schema
   (provisioning inserts no longer fill the NOT NULL legacy pair).

## 10. Review record (v1 questions, answered by Jus 2026-09-25)

1. **Lifecycle page:** retire (section 8).
2. **NAS:** a NAS is a system, category `nas`; its drives are
   `storage_drive` components (section 6a, R6). `nas_drives.py` retires.
3. **Legacy JSON APIs:** retire all three (section 8). Credentials get an
   item detail section instead of the dead modal.
4. **Phones, webcams, printers:** their own categories (section 6a).
5. **Vendor analytics:** item 30 removes the legacy half; N2 rebuilds.
6. **Map:** S4's map commit opens with a read counting legacy edge boxes
   that show on the map from their own coordinates while their items twin
   has no customer site with coordinates. Those units would drop off the
   map, and the read decides whether their sites need coordinates first.

**Build-time reads, closed 2026-09-28:** the R2 field mapping (section
5, R2) and `removed_date` (none set, R4).

## 11. Out of scope

- The items importer (new board item, section 7).
- N2 vendor rebuild.
- Re-entering dropped camera credentials.
- Any change to audit history strings.

## Appendix: census by function (READ, 9cdef41)

Name-based: any reference to `TABLE_MODELS`, a legacy device class, a
legacy link class or a legacy helper, grouped by enclosing function. Imports
and comments excluded. `c2c.py`, `dashboard.py`, `photo_store.py` and
`tours.py` matched only in prose and are excluded.

```
admin.py        oui_reference            GET /admin/oui
api.py          list_devices             GET /devices/{table_name}
                inventory_stats          GET /stats
                get_vendors              GET /vendors
bulk.py         _validate_device_list    helper
                bulk_status_change       POST /api/bulk/status
                bulk_assign_to_site      POST /api/bulk/assign
                bulk_export_selected     POST /api/bulk/export
creds.py        get_credentials          GET /{table_name}/{device_id}
fulfillment.py  _stock_snapshot, _resolve_unit_serial    helpers
                fulfillment_page         GET /fulfillment/
                fulfillment_panel_state  GET /api/fulfillment/panel/{order_id}
                certifications_index     GET /fulfillment/certifications
                submit_cert_qa, submit_cert_hw, upload_cert_file,
                close_cert_device, cancel_cert_device, recertify_device
                                         POST /fulfillment/certifications/...
                certification_detail, cert_report
                                         GET /fulfillment/certifications/...
intune_routes   trigger_intune_sync      POST /api/intune/sync
lifecycle.py    device_lifecycle         GET /api/device/{t}/{id}/lifecycle
                device_lifecycle_page    GET /device/{t}/{id}/lifecycle
map.py          _collect_units, _needs_location   helpers
                map_set_location         POST /set-location
nas_drives.py   list_drives              GET /api/nas-drives/{nas_device_id}
                add_drive                POST /api/nas-drives/
orders.py       _sku_availability        helper
                order_detail             GET /orders/{order_id}
pending.py      approve_device           POST /pending/{device_id}/approve
                dismiss_device           POST /pending/{device_id}/dismiss
provisioning.py _resolve_device_name, _resolve_deployment_type   helpers
                provisioning_page        GET /provisioning/queue
                provisioning_detail_page GET /provisioning/{prov_id}
                create_provisioning      POST /api/provisioning
                fetch_zendesk_ticket     GET /api/provisioning/zendesk-ticket/{id}
                advance_provisioning     POST /api/provisioning/{prov_id}/advance
                get_devices_for_category GET /api/provisioning/devices/{t}
receiving.py    find_serial_anywhere, _route_scan   helpers
                submit_device            POST /api/receive/device
sites.py        sites_page               GET /sites/
                site_detail_page         GET /sites/{site_id}
                delete_site              DELETE /api/sites/{site_id}
                assign_device            POST /api/assignments
                return_device            POST /api/assignments/{id}/return
                delete_assignment        DELETE /api/assignments/{id}
support.py      review_queue, _table_filter   GET /review
vendors.py      _vendor_analytics        helper
                vendors_list             GET /vendors/
                auto_create_vendors      POST /api/vendors/auto-create
warranty.py     _resolve_device_label    helper
                warranty_page            GET /warranty/
                create_warranty          POST /api/warranty
                update_warranty          PUT /api/warranty/{id}
                create_claim             POST /api/claim
                export_warranties        GET /api/warranty/export
                get_warranty             GET /api/warranty/{id}
                delete_warranty          DELETE /api/warranty/{id}
sidebar_cache   get_sidebar_counts       helper
spreadsheet_sync _map_sheet_to_table, compare_with_database, apply_changes
```
