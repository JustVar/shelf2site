> **Note:** This file describes the current rebuilt app at `/opt/asset_tracker/` on apphost (Docker Compose, `asset_tracker` DB). Earlier NUC/`hardware_inventory` deployment notes have been removed; the legacy `hardware_inventory` DB still exists on the host as a read-only backup reference (see the Database port section).

## Deployment

- **Host:** `apphost` (Ubuntu 24.04, 466 GB root LV)
- **LAN IP:** `192.0.2.10` (current, post network migration on 2026-05-01)
- **Prior IP:** `192.0.2.5` (pre 2026-05-01 — historical references in commits and notes)
- **App URL:** `https://192.0.2.10:8443/assettracker/` (HTTPS front door). `http://192.0.2.10:8100/assettracker/` still works — it 301-redirects to HTTPS. See `docs/HTTPS.md`.
- **HTTPS:** host nginx terminates TLS on `:8443` (443 is held by the docker registry). mkcert CA + leaf under `/etc/ssl/asset-tracker/` (off-repo); leaf SANs `192.0.2.10`/`apphost`, expires 2028-10-12, CA 2036-07-12. Secure cookie is set per-request from scheme (`SecureSessionCookieMiddleware`) — keep `HTTPS_ONLY=false` or the in-container contract suite breaks. Devices install `LAN-CA.crt` (see `docs/CA_CERT_DISTRIBUTION.md`).
- **Stack:** Docker Compose at `/opt/asset_tracker/`
- **Containers:** `asset_tracker_db` (postgres:16) + `asset_tracker_app` (gunicorn / 6 uvicorn workers)
- **Gunicorn config:** 6 workers (`uvicorn.workers.UvicornWorker`), bound to `127.0.0.1:8081`, fronted by host nginx (`:8443` HTTPS, `:8100` HTTP→HTTPS redirect).
- **App network:** docker bridge `asset_tracker_asset_tracker_net` (containers resolve each other as `db` and `app`)

### Storage layout (apphost)

- **Root filesystem:** `/dev/mapper/ubuntu--vg-ubuntu--lv` mounted at `/`, 466 GB total, ~22% used (2026-05-04)
- **`/data` is NOT a separate mount** — just a directory on root.
- **Bind mounts (host → container):**
  - `/data/asset-tracker/postgres` → `/var/lib/postgresql/data` (pg cluster — survives `docker compose down`)
  - `/data/asset-tracker/photos` → `/app/data/photos`
  - `/data/asset-tracker/receipts` → `/app/data/receipts`
  - `/opt/asset_tracker/static` → `/app/static`
  - `/opt/asset_tracker/app` → `/app/app` (whole `app/` since 2026-04-23, see below)

### Database port — host 5433, container 5432

- **Inside the docker network:** app talks to `db:5432` — unchanged, never edit this.
- **From the host:** `psql -h localhost -p 5433 -U asset_tracker_user asset_tracker`
- **Reason for the remap (2026-05-04):** apphost's host postgres is `active + enabled` and grabs `5432` on every boot. It holds one non-default database (a second, `asset_tracker`, was dropped 2026-06-16 - see below):
  - `asset_tracker` (host pg) — DROPPED 2026-06-16. Was NOT an empty stub as previously noted: a frozen pre-Docker snapshot, ~16K rows (mostly 13,773 audit_log rows, last write 2026-03-27). Disposable because the tool is being pushed out fresh; archived before drop to `/data/asset-tracker/backups/host_asset_tracker_2026-06-16.sql.gz`. NOTE: this is the HOST pg `asset_tracker` only - the live app uses the separate CONTAINER pg cluster, untouched.
  - `hardware_inventory` — legacy DB from the old NUC, 52 tables in `public`. Left untouched, useful as backup reference.
- **Pre-remap compose backup:** `/opt/asset_tracker/docker-compose.yml.bak.<timestamp>` if rollback ever needed.

### Recovery

| Symptom | Cause | Fix |
|---|---|---|
| Stack down, both containers stopped | Host reboot, daemon restart, or clean compose down | `cd /opt/asset_tracker && docker compose up -d` |
| App container `Restarting`, logs show `could not translate host name "db"` | Containers exist but their network attachment is broken (network removed or container restart raced the network) | `docker compose down && docker compose up -d` (recreates containers AND project network; bind-mounted data survives — `down` does not touch `/data/asset-tracker/postgres/`) |
| db container won't start, port conflict on 5432 | Host postgres reclaimed the port — should not happen post-remap | Verify with `sudo systemctl status postgresql` and `sudo lsof -i :5432`. The remap to host port 5433 should make this self-healing — if you hit a 5432 conflict despite that, something has changed the compose port mapping back. Inspect `/opt/asset_tracker/docker-compose.yml` and restore from `.bak.<timestamp>` if needed. |

`docker compose down` only removes containers and the project network. It does NOT touch host bind mounts. Postgres data at `/data/asset-tracker/postgres/` is safe.

### Volume mounts — what's live-editable, what needs a rebuild

**Live-editable** (host edits visible immediately; restart workers via `docker compose restart app`):
- `/opt/asset_tracker/app/` (whole directory mounted as `/app/app/` since 2026-04-23 — main.py, models.py, sidebar_cache.py, routes/, templates/)
- `/opt/asset_tracker/static/` (mounted as `/app/static/`)

**Requires image rebuild** (`docker compose up -d --build app`):
- `requirements.txt`
- `Dockerfile`
- Anything outside the two mounted paths above (config files in repo root, etc.)

### Volume mount changes need recreate, not restart

`docker compose restart app` is NOT sufficient when adding/removing volume mounts in `docker-compose.yml` — the mount spec is part of the container's creation-time config and only re-evaluates on `docker compose up -d` (which recreates the container). Use `up -d app` after any compose volume change. If a new mount doesn't appear inside the container, this is the most likely cause.

### Permissions schema (post U2d.1, 2026-05-07)

Permission columns on `users` and `departments` use Postgres ENUM types instead of nullable booleans:

- `user_permission_state`: `'inherit' | 'grant' | 'block'` — three-state for users
- `department_permission_state`: `'grant' | 'block'` — two-state for departments (no inherit; departments are the source of truth)

15 user permission columns: 14 use `user_permission_state DEFAULT 'inherit'`. The 15th (`view_sensitive_customers`) uses `DEFAULT 'block'` because it has no department equivalent — `'inherit'` would have nothing to fall back to.

`User._resolve_perm()` reads the user column; if `'inherit'`, falls back to the matching department column. Returns bool. Property layer (`user.has_financial_access`, etc.) calls `_resolve_perm` and OR-merges the role check on top — admin-tier roles always have access regardless of column state.

Application code should never read raw `can_*` columns directly — always go through the property layer. Reading raw columns gives you a string ('grant'/'block'/'inherit'), not a bool.

---

## Stack & Conventions

- **Backend:** FastAPI + Jinja2 + HTMX (no JS frameworks). PostgreSQL (DB `asset_tracker`, user `asset_tracker_user`).
- **Auth:** Starlette SessionMiddleware (signed cookie); session stores user_id, username, role, must_change_password. Roles are a 3-tier hierarchy (9 roles) — see "RBAC / Admin pages" below for the full model.
- **Deployment:** Docker Compose on apphost — `app` (gunicorn, 6 uvicorn workers, bind :8081) + `db` (postgres:16). Host nginx fronts `:8443` (HTTPS) and `:8100` (redirect) → container :8081. `ROOT_PATH=/assettracker` (URL prefix). No systemd; no in-container nginx.

### Adding Features
1. Add route file in `app/routes/`
2. Add template in `app/templates/`
3. **Update tours in `app/tours.py`** for the relevant page

### Migrations
- Sequential numbering: `001_`, `002_`, ... — **the `migrations/` directory is the truth for the next number** (a hardcoded "next" here goes stale immediately; check `ls migrations/ | sort | tail`).
- Run inside the container: `docker compose exec app python migrations/NNN_*.py`
- Always add a migration for schema changes — never modify the DB directly.

### Deploy / sync (four locations)
- apphost has **no GitHub deploy key** — never `git pull` on the server. The flow is: edit + verify on apphost → `~/bin/at-sync-commit.sh <paths>` (commit message via stdin; prints PREV/NEW) → on the workstation `git checkout -- <files>` (drop local copies) then `bash scripts/wsync PREV NEW` → wsync moves a git bundle, fast-forwards the workstation, and pushes `origin` (JustVar) + `company` (employer-org).
- wsync aborts if the workstation tree is dirty; run multi-commit hops sequentially.

### Static Files
- Located at repo root `static/` (bind-mounted to `/app/static` in the container) — NOT `app/static/`.
- CSS variables for dark/light theme in `static/css/main.css`.

### Body zoom inflates 100vh — size fixed full-height elements with calc(100vh / 1.15)

`body { zoom: 1.15 }` (static/css/main.css, on every monitor ≤2560px; reset to
1 on phones <768px) scales the whole app up 15% for readability. Side effect:
any `position: fixed` element sized `height: 100vh` renders at 115% of the real
viewport, pushing its bottom (e.g. a pinned footer) off-screen. Fix by dividing
the zoom out — `height: calc(100vh / 1.15)` inside `@media (max-width: 2560px)`,
plain `100vh` on phones. Precedents: `.sx-nav` sidebar (main.css:2866) and the
`.sx-drawer` edit drawer (2026-07). Viewport-measuring JS already compensates by
reading `getComputedStyle(document.body).zoom` (fl-restyle.js, guide.js). A
shared `--viewport-h` token would be the real cure.

### Tours (app/tours.py)
- 33 tour definitions, 29 currently enabled (see app/tours.py; lint via lint_tour_selectors).
- Each tour: id, name, page_pattern, steps (target selector + title + description). Engine in `static/js/guide.js`.
- See `docs/tour-dev-guide.md` for patterns and gotchas.

### Design Philosophy
"Grandma usable" — every page must be self-explanatory. Guided tours, clear labels, no tribal knowledge required.

---

## Architecture

### Triage system (`app/routes/triage.py`)

- Three roles defined in `TRIAGE_ROLES` dict: `hw` (hardware inventory), `acct` (accounting/auditing), `deploy` (deployment tracking). Each lists the fields required for that role.
- **Per-tab badge** = items with ≥1 gap *for that role*.
- **Sidenav badge** = items with ≥1 gap across *any* role (UNION across roles, NOT a sum).
- Live updates via SSE event `triage_gap_changed` published from any save (single-field fix or bulk action) on either Triage or Inventory pages.

### SSE fan-out (`app/routes/sse.py`)

- Multi-worker fan-out via Postgres LISTEN/NOTIFY on channel `asset_tracker_events`.
- Listener + publisher asyncpg connections per gunicorn worker.
- 7500-byte payload limit; oversize messages dropped with WARNING log.
- Lifecycle managed via FastAPI lifespan in `main.py` — `start_sse_pubsub()` / `stop_sse_pubsub()`.

### Sidebar count cache (`app/sidebar_cache.py`)

- Caches triage count + per-user pending count, 15s TTL.
- Invalidated by any write that could change those numbers via `invalidate_sidebar_counts()`.
- Injected on every authenticated request via `sidebar_counts_middleware` in `main.py`. Available in templates as `request.state.triage_count` / `request.state.pending_count`.
- The previous `_patched_template_response` monkey-patch was removed 2026-04-24. Use the middleware / `request.state` pattern; do NOT add new template-context injection.

### Edit locks (`app/locks.py`)

- Any item edit takes a lock under key `items:{id}`.
- Bulk save endpoints (`/triage/bulk`, `/inventory/bulk`) skip locked items and return `skipped_ids` in the JSON response — clients show "N skipped (locked by other users)".
- Open TODO: multi-viewer awareness (single-holder for now).

## Known TODOs / hygiene
- **Test harness rebuild:** the previous E2E/smoke suite (tests/) targeted the retired NUC host (sudo psql on hardware_inventory, /opt/hardware_inventory paths, 192.0.2.174) and was removed. Rebuild against the apphost/Docker stack: add pytest to the image and write HTTP-based tests against http://192.0.2.10:8100/assettracker (or a container-internal URL).
- Vendors table + dropdown — currently free-text input on intake + triage
- **brand_sku managed vocabulary (B1 shipped; B2/B3 DEFERRED to Fulfillment):** Part Numbers admin CRUD (5414fe1), intake datalist (Phase 1), triage strict select (Phase 2) all shipped. The strict-select sweep across intake/item_detail/quick_view + shared macro (B2/B3) is DEFERRED: managed SKUs apply only to sellable categories (Edge Box, Camera 2 Cloud, Cloud Box); internal hardware uses serial number, not SKU. Per-category SKU filtering and the full cross-category SKU list are pending the Fulfillment phase. quick_view was prototyped as a flat select then reverted (would contradict the category model). Resume with the real catalog once Fulfillment defines the rules.
- Multi-viewer lock awareness, when Users page is built
- Mobile barcode-scan flow at `/scan` — explicitly deferred from main app, not yet started
- U2/U3 (Users + Departments UI rebuild) — sweep deferred renames per [docs/U2_U3_RENAME_FOLLOWUPS.md](docs/U2_U3_RENAME_FOLLOWUPS.md). U1 (2026-05-04) renamed the DB table only; cosmetic file/route/identifier renames are listed there.
- **Route migration `public.* -> item_schema` (inventory-display arc complete):** Inventory listing, the unified `/items/{id}` detail page (incl. component-history / maintenance / attributes panels), intake, triage, and the receipts panel all read item_schema. Per-category detail routes+templates were retired (commit 151da9b). Search migrated to a single item_schema.items query in 4136b36 (was iterating 22 per-category public.* tables via TABLE_MODELS), so Casey's imported items are now findable in global search. The warranty + components subsystems are SEPARATE migration tracks, still on public.* - see their own bullets below.
- **Warranty migration (DEFERRED - design alongside Fulfillment, see below):** 5 routes (warranty, vendors, procurement, admin, lifecycle) use public.device_warranties. Decision made 2026-06-15: do NOT migrate standalone; design the warranty data model once, when Fulfillment is built, because the highest-value form (customer warranty periods we honor on shipped hardware) hangs off the order/fulfillment side. Audit findings from this session:
  - 0 rows in both device_warranties AND warranty_claims (warranty_claims FK-references device_warranties.id, ON DELETE CASCADE).
  - Currently NON-FUNCTIONAL for new items: intake writes only to item_schema.items, but warranty._resolve_device_label() resolves via the per-category public.* tables (TABLE_MODELS by device_table+device_id), so a warranty can never attach to an intake-created item. The 0 rows reflect this break, not disuse.
  - Cardinality is already 1:many item->warranty (no unique constraint on device_table+device_id; only registration_number is unique). So the eventual customer-warranty extension is an EXTENSION, not a cardinality rework - an item can carry vendor + customer warranties.
  - Dual-purpose via warranty_scope: 'external' = vendor/manufacturer warranty tracking; 'internal' = a loaner-accountability subsystem (loaner_from_team, loaner_to_team, loaner_contact, loaner_agreement). The internal-loaner feature is DISTINCT from the C1-C3 checkout/checkin custody feature (checkout = per-event physical custody; loaner = team-level lending contract). Deprecating warranty would also kill loaner tracking - so deprecation is off the table.
  - DeviceWarranty inherits InventoryMixin (gets data_completeness/incomplete_reason). Decide on migration whether those belong on warranty.
  - Migration shape when undertaken: replace (device_table, device_id) -> item_id FK to item_schema.items; warranty_claims FK on device_warranties.id stays valid.

- **Fulfillment buildout (NOT YET STARTED as a focused track; foundation exists):** fulfillment.py (6 routes: page, ship, deployments, status, export, technician-update) + fulfillment.html already exist as a Kanban command-center over the order subsystem. Built on a mature foundation: CustomerOrder model (order_number, Salesforce sync ids, 8-stage status pipeline new->...->installed, deployment_type, sku_requirements JSONB, contract_value/hardware_cost, shipping fields per migration 021, OEM PO cascade). Reads item_schema-agnostic order models; only TABLE_MODELS touchpoint is _stock_snapshot() for per-category stock counts. Scope-later outline for the full buildout:
  - Customer warranty periods we honor on shipped hardware (edge boxes, C2C cams, cloud boxes) - this is where the deferred warranty model gets designed (see above). Likely hangs off CustomerOrder / a shipped-line record, not directly off item.
  - Flesh out the Kanban command-center UX over the order + provisioning pipeline (replaces the old separate /orders/ and /provisioning/ list pages).
  - Decide warranty modeling: one scope-discriminated table (vendor + loaner + customer) vs. separate tables, resolved here.
  - Re-audit fulfillment's TABLE_MODELS usage (_stock_snapshot) once the per-category tables are retired (see legacy-models bullet).
- **Item.data_completeness gap:** the unified Item model (item_schema.items) does NOT have data_completeness - that field lives on InventoryMixin, which Item does not inherit (the 22 legacy per-category models do). Surfaced during the search migration (4136b36) when the search dot-indicator was dropped. If a completeness/quality signal is ever wanted on the unified item, it needs modeling (or wire it to the existing triage-gap logic).
- **Retire the 22 legacy per-category models + public.* tables (eventual end-state):** the per-category models (EdgeBox, GPU, Camera, ... + InventoryMixin) and their public.* tables persist only because warranty + components still depend on them, and they hold legacy read-only data. Once warranty (via Fulfillment) and components are migrated off public.*, the 22 models, TABLE_MODELS, and the public.* device tables can be retired. Blocked on those two tracks.
- **Components data migration (DEFERRED; routes already retired):** The components.py routes (/install, /remove/{id}, /move/{id}, /available/{table}) were retired in f3c379e - orphaned post-G2 once the per-category detail templates that called them were deleted (151da9b); they were reachable only by direct API POST. Kept: the DeviceComponent model + public.device_components (31 legacy linkage rows from the 2026-03-05 import - 7 edge_box->GPU, 24 various computer->component; parent_table+parent_id / component_table+component_id). Future migration to item_schema.component_history (an event-log: action enum + action_date, vs. the legacy single-row installed_date/removed_date) is blocked on: (a) item_schema.items has only ~10 rows, so the per-category PKs in those 31 rows cannot map to items.id until Casey imports the parent + component devices (serial JOIN); (b) shape transform - each legacy row emits 1 install event, plus a 2nd uninstall event if removed_date is set. Revisit alongside the warranty + Fulfillment design work (same deferral pattern - see those bullets above).
- **scanner.js is live (do NOT delete):** static/js/scanner.js defines the BarcodeScanner class, loaded by receive.html, provisioning_detail.html, and fulfillment.html for the receiving/provisioning/fulfillment scan workflows. A prior bullet wrongly flagged it as orphaned from the scanner-architecture removal; that removal was a different surface. Verified loaded 2026-06-15.
- **Casey DB access (done 2026-06-10):** `casey` role created on live cluster, `item_schema`-scoped (DML + CREATE), isolated from `public.*`. External login pending Casey's own verification.

- **Attribute + checkout editing via forms:** the unified detail page shows per-category `attributes` read-only; check-out recipient/notes are set only on the checkout form. Form-based editing of `items.attributes` is deferred (data enters via Casey's import); revisit with the intake-form work.
## RBAC / Admin pages (post U4, 2026-05-18)

The asset tracker has 13 admin routes. Each route is gated by a `require_*` dependency in the route signature; the matching sidenav link in `base.html` is gated by the same property on the User model. Route gate and nav gate stay in lockstep — change one, change the other.

### Role × admin-page matrix

| Page | URL | Route gate | Nav gate | Property |
|---|---|---|---|---|
| Users | /admin/users | require_user_manager | user.has_user_management | admin tier + can_manage_users |
| Departments | /admin/departments | require_user_manager | user.has_user_management | admin tier + can_manage_users |
| Audit log | /admin/audit | require_audit_viewer | user.has_audit_access | admin tier + sub-admins + can_view_audit_log |
| Error log | /admin/errors | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| OUI reference | /admin/oui | require_editor | user.is_editor_or_above | editor + sub-admins + admin tier |
| Procurement | /admin/procurement | require_financial | user.has_financial_access | admin tier + procurement_admin + can_view_financial |
| Storage | /admin/storage | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Intune | /admin/intune | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Notifications | /admin/notifications | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Spreadsheet sync | /admin/spreadsheet-sync | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Zendesk | /admin/zendesk | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Maintenance | /admin/maintenance | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Slack-bot redirect | /admin/slack-bot | (none — public 301) | (no link) | redirects to /admin/notifications |

### Sidenav structure (post U4b)

The Admin section is a collapsible nested menu (`.sx-nav__section[data-section="admin"]`) containing four subgroups:

- **People** — Users, Departments
- **Data & logs** — Audit log, Error log, OUI reference, Procurement, Storage
- **Integrations** — Intune, Notifications, Spreadsheet sync, Zendesk
- **System** — Maintenance

Each subgroup auto-hides if no children inside it are visible to the current user. The Admin section + matching subgroup auto-expand on page load when the URL is `/admin/*`; otherwise everything collapses.

### Property to require_* dependency mapping

When adding a new admin route, use these pairings:

| `require_*` dependency | Matching User property | Used for |
|---|---|---|
| require_editor | user.is_editor_or_above | broad access — editor + sub-admins + admin tier |
| require_user_manager | user.has_user_management | user/dept admin |
| require_audit_viewer | user.has_audit_access | audit log visibility (broader than admin tier) |
| require_system_admin | user.has_system_admin | system operations |
| require_financial | user.has_financial_access | finance & procurement views |

### 403 handling (post U4c)

The global exception handler in `main.py` intercepts 403s and branches:

1. **HTMX request** (`HX-Request: true` header) — returns 403 with `HX-Refresh: true` header, triggering a full browser navigation (not an in-shell swap) to the same URL, which then hits the handler again as a plain HTML request.
2. **Browser HTML** (`Accept: text/html`) — renders `permission_denied.html` inside the app shell with the per-call `exc.detail` message and a Contact Admin button.
3. **API/JSON** — preserves default `{"detail": ...}` shape for programmatic consumers.

The HTMX branch was added because hx-boost on the sidenav was swallowing 403 redirects and producing in-shell swaps that left the user with a Frankenstein page. Same root cause as the logout bug fixed in U4b.
