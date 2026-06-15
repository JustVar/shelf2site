> **Note:** This file describes the current rebuilt app at `/opt/asset_tracker/` on apphost (Docker Compose, `asset_tracker` DB). Earlier NUC/`hardware_inventory` deployment notes have been removed; the legacy `hardware_inventory` DB still exists on the host as a read-only backup reference (see the Database port section).

## Deployment

- **Host:** `apphost` (Ubuntu 24.04, 466 GB root LV)
- **LAN IP:** `192.0.2.10` (current, post network migration on 2026-05-01)
- **Prior IP:** `192.0.2.5` (pre 2026-05-01 — historical references in commits and notes)
- **App URL:** `http://192.0.2.10:8100/assettracker/`
- **Stack:** Docker Compose at `/opt/asset_tracker/`
- **Containers:** `asset_tracker_db` (postgres:16) + `asset_tracker_app` (gunicorn / 6 uvicorn workers)
- **Gunicorn config:** 6 workers (`uvicorn.workers.UvicornWorker`), bound to `127.0.0.1:8081`, fronted by host nginx on `:8100`.
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
- **Reason for the remap (2026-05-04):** apphost's host postgres is `active + enabled` and grabs `5432` on every boot. It holds two non-default databases:
  - `asset_tracker` — empty stub, owner `asset_tracker_user`. Flagged for cleanup (`sudo -u postgres dropdb asset_tracker`), not yet dropped.
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
- **Deployment:** Docker Compose on apphost — `app` (gunicorn, 6 uvicorn workers, bind :8081) + `db` (postgres:16). Host nginx fronts :8100 → container :8081. `ROOT_PATH=/assettracker` (URL prefix). No systemd; no in-container nginx.

### Adding Features
1. Add route file in `app/routes/`
2. Add template in `app/templates/`
3. **Update tours in `app/tours.py`** for the relevant page

### Migrations
- Sequential numbering: `001_`, `002_`, ... (next: `046_`)
- Run inside the container: `docker compose exec app python migrations/NNN_*.py`
- Always add a migration for schema changes — never modify the DB directly.

### Static Files
- Located at repo root `static/` (bind-mounted to `/app/static` in the container) — NOT `app/static/`.
- CSS variables for dark/light theme in `static/css/main.css`.

### Tours (app/tours.py)
- 28 tour definitions, 23 currently enabled.
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
- Open TODO: listener reconnect when Postgres restarts (workers lose events until app restart).

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
- Drop the empty host `asset_tracker` DB on apphost: `sudo -u postgres dropdb asset_tracker` (when convenient — safe, the data is empty)
- SSE listener reconnect logic in `app/routes/sse.py` (reconnect to Postgres after restart instead of requiring app restart)
- Downgrade SSE per-event INFO logs to DEBUG once stable
- Vendors table + dropdown — currently free-text input on intake + triage
- `brand_sku` should render as `<datalist>` / `<select>` sourced from `item_schema.part_numbers`, both on intake and triage
- Multi-viewer lock awareness, when Users page is built
- Receipt download endpoint `/api/receipts/{id}/download` — link exists on item detail, returns 404 (implement as part of Finance page work)
- Mobile barcode-scan flow at `/scan` — explicitly deferred from main app, not yet started
- U2/U3 (Users + Departments UI rebuild) — sweep deferred renames per [docs/U2_U3_RENAME_FOLLOWUPS.md](docs/U2_U3_RENAME_FOLLOWUPS.md). U1 (2026-05-04) renamed the DB table only; cosmetic file/route/identifier renames are listed there.
- **Route migration `public.* -> item_schema` (G1+G2 shipped; remainder is per-feature):** Inventory listing + the unified `/items/{id}` detail page read item_schema.items; the unified page's component-history / maintenance / attributes panels read item_schema. Per-category detail routes+templates were retired (commit 151da9b). NOT yet re-audited: intake, triage, search, and the receipts panel (public.item_receipts) - verify whether they still hit public.* (Casey imports land in item_schema, so anything still reading public.* misses imported data). The warranty + components subsystems are SEPARATE migration tracks, not part of this bullet - see their own bullets.
- **Warranty migration (separate track):** 5 routes (warranty, vendors, procurement, admin, lifecycle) use public.device_warranties (0 rows but a live, fully-built feature; 30 cols incl. loaner + procurement + claim metadata; per-category device_table+device_id linkage). No item_schema equivalent exists. Decision needed: design item_schema.device_warranties and migrate the 5 routes, OR accept warranty stays on public.* permanently.
- **Components page migration (separate track):** components.py uses public.device_components (31 rows: edge_box -> GPU linkage records from a 2026-03-05 import; parent_table+parent_id / component_table+component_id). item_schema.component_history exists but is a DIFFERENT shape - an event log (action enum + action_date), not a current-state linkage record (installed_date/removed_date). Decision needed before migrating: keep public.device_components as the canonical linkage store, OR design a linkage table in item_schema and backfill the 31 rows.
- **Dead static asset audit:** static/js/scanner.js (~12KB) likely orphaned after the scanner architecture removal. Confirm it's loaded nowhere, then delete.
- **base.html inline-JS extraction (low priority):** notifications (~L684) and maintenance-status (~L944) blocks are large inline scripts; same extraction pattern as the shortcuts.js fix would make them cleaner and HTMX-swap-safe.
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
