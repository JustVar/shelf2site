> **Note (2026-05-04):** This file is in transition. The new `## Deployment`, `## Architecture`, and `## Known TODOs` sections at the top describe the current rebuilt app at `/opt/asset_tracker/` on apphost. The legacy sections below (`## Overview`, `## Stack`, `## Project Structure`, `## Migrations`, `## Tests`) describe the OLD `hardware_inventory` app on the original NUC and should be considered historical until rewritten. Don't trust legacy section facts without verification.

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
- **`/data` is NOT a separate mount** — just a directory on root. Differs from CLAUDE.md's documented primary NUC at 192.0.2.174 (which has a 916 GB HDD at `/data`).
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

# Asset Tracker — CLAUDE.md

## Overview
Hardware asset inventory system for Company. FastAPI + Jinja2 + HTMX. Deployed on NUC at `http://192.0.2.174/assettracker/`.

## Stack
- **Backend:** FastAPI, PostgreSQL (DB: `hardware_inventory`, user: `inventory_user`)
- **Frontend:** Jinja2 templates + HTMX (no JS frameworks)
- **Auth:** Session-based, role-based (admin, editor, procurement, viewer, sites_manager)
- **Deployment:** systemd (`hardware.asset.tracker.service`), nginx reverse proxy, `ROOT_PATH=/assettracker`

## Project Structure
```
app/
├── main.py              # FastAPI app, startup, middleware
├── models.py            # SQLAlchemy models
├── database.py          # DB engine, session
├── auth.py              # Auth, RBAC decorators (require_sites_manager, etc.)
├── config.py            # Settings from .env
├── tours.py             # Guided tour definitions (UPDATE when adding features)
├── routes/              # ~59 route files (one per feature/detail page)
│   ├── dashboard.py     # Main dashboard
│   ├── fulfillment.py   # Unified fulfillment Kanban
│   ├── provisioning.py  # Provisioning pipeline
│   ├── orders.py        # Customer orders
│   └── *_detail.py      # Per-device-type detail pages
├── templates/           # Jinja2 HTML templates
├── notifications.py     # Slack bot, email, SSE notifications
├── zendesk.py           # Zendesk async API client
├── locks.py             # In-memory edit locking + SSE
└── validation.py        # Input validation
migrations/              # Sequential numbered (001-044), run on NUC venv
static/                  # CSS, JS, images (at repo root, NOT app/static/)
tests/
├── test_e2e_api.py      # Main E2E test file (~709 tests, 31 sections)
├── test_smoke.py        # Smoke tests
├── CLAUDE_WEB_TESTING_GUIDE.md  # MANDATORY: update after adding features/tests
└── CLAUDE_WEB_SESSION_STRATEGY.md
```

## Key Conventions

### Adding Features
1. Add route file in `app/routes/`
2. Add template in `app/templates/`
3. **Update tours in `app/tours.py`** for the relevant page
4. **Update `tests/CLAUDE_WEB_TESTING_GUIDE.md`** with test instructions
5. Add E2E tests as a new section in `tests/test_e2e_api.py`

### Migrations
- Sequential numbering: `001_`, `002_`, ..., `044_` (next: `045_`)
- Run on NUC: `ssh nuc` then `/opt/hardware_inventory/venv/bin/python3 migrations/NNN_*.py`
- Always add a migration for schema changes — never modify the DB directly

### Tests
- `test_e2e_api.py` is a **standalone script** (not pytest) — run with `python tests/test_e2e_api.py`
- Uses `requests` library, organized in 31 numbered sections
- Creates/cleans up test users per run (`test_admin_e2e`)
- `test_smoke.py` (27 tests) is a quick standalone check (~10 seconds)
- Tests hit the real API (no mocks) — use `hardware_inventory` DB
- **Test isolation:** completely separate from QA Ops and Playwright tests
- Env vars: `BASE_URL` (default: `http://192.0.2.174/assettracker`), `E2E_ADMIN_USER`, `E2E_ADMIN_PASS`

### Static Files
- Located at repo root `static/` — NOT `app/static/`
- CSS variables for dark/light theme in `static/css/main.css`

### RBAC
- Roles: admin (reese/rowan), editor (chris/nico), editor+sites (parker), procurement (morgan), viewer (grant)
- Decorators: `require_admin`, `require_editor`, `require_sites_manager`, `require_procurement`
- `TABLES_REQUIRING_SITES_ADMIN` controls review queue filtering

### Tours (app/tours.py)
- 26 tour definitions, 2 currently enabled (`inventory_tour`, `asset_triage_tour`)
- Each tour: id, name, page_pattern, required_access, steps (CSS selectors + descriptions)
- Tour engine: `static/js/guide.js` — overlay cutout, tooltip positioning, wait_for polling
- Z-index stack: overlay=1100, highlight=1150, QV overlay=1160, tooltip=1200, toast=1300
- See `docs/tour-dev-guide.md` for patterns and gotchas

### Scanner Pipeline
- `scanner/` directory: nmap wrapper, OUI lookup, pending device queue
- Modes: `local` (NUC scans itself) or `remote` (agents POST to `/api/discover`)
- Pending devices: discovered → approved (moves to inventory) or dismissed

### Design Philosophy
"Grandma usable" — every page must be self-explanatory. Guided tours, clear labels, no tribal knowledge required. See workspace CLAUDE.md for full details.

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

- Drop the empty host `asset_tracker` DB on apphost: `sudo -u postgres dropdb asset_tracker` (when convenient — safe, the data is empty)
- SSE listener reconnect logic in `app/routes/sse.py` (reconnect to Postgres after restart instead of requiring app restart)
- Downgrade SSE per-event INFO logs to DEBUG once stable
- Vendors table + dropdown — currently free-text input on intake + triage
- `brand_sku` should render as `<datalist>` / `<select>` sourced from `item_schema.part_numbers`, both on intake and triage
- Multi-viewer lock awareness, when Users page is built
- Receipt download endpoint `/api/receipts/{id}/download` — link exists on item detail, returns 404 (implement as part of Finance page work)
- Mobile barcode-scan flow at `/scan` — explicitly deferred from main app, not yet started
- (Broader) the legacy `## Overview / ## Stack / ## Project Structure / ## Migrations / ## Tests` sections of this CLAUDE.md describe the *old* hardware_inventory app on 192.0.2.174 — pending full rewrite to match the rebuilt /opt/asset_tracker stack
- U2/U3 (Users + Departments UI rebuild) — sweep deferred renames per [docs/U2_U3_RENAME_FOLLOWUPS.md](docs/U2_U3_RENAME_FOLLOWUPS.md). U1 (2026-05-04) renamed the DB table only; cosmetic file/route/identifier renames are listed there.


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
