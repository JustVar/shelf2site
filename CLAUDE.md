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

`User._resolve_perm()` reads the user column; if `'inherit'`, falls back to the matching department column. Returns bool. Property layer (`user.has_receipts_access`, etc.) calls `_resolve_perm` and OR-merges the role check on top — admin-tier roles always have access regardless of column state.

Application code should never read raw `can_*` columns directly — always go through the property layer. Reading raw columns gives you a string ('grant'/'block'/'inherit'), not a bool.

### nginx config is a mirror, not a deploy source
`deploy/nginx/asset-tracker.conf` is a REFERENCE COPY of the live file at
`/etc/nginx/sites-available/asset-tracker`, which is root-owned and NOT deployed
from this repo. Editing the repo copy changes nothing — wsync does not touch it.
It exists so the config survives a host rebuild: if apphost is lost, restore
nginx from this file. That only works if it stays current.
To change nginx: edit the live file with sudo, `sudo cp` a timestamped backup to
/tmp first, `sudo nginx -t` (STOP if it fails — never reload a failing config),
then `sudo systemctl reload nginx` (reload, never restart). Then mirror the same
edit into the repo copy and commit, so the two do not drift.
Verify they match after any nginx change:
`sudo diff /etc/nginx/sites-available/asset-tracker /opt/asset_tracker/deploy/nginx/asset-tracker.conf`
(empty output = in sync)

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
- apphost has **no GitHub deploy key** — never `git pull` on the server. The flow is: edit + verify on apphost → `~/bin/at-sync-commit.sh <paths>` (commit message via stdin; prints PREV/NEW) → on the workstation `git checkout -- <files>` (drop local copies) then `~/bin/wsync PREV NEW` (the live copy; `scripts/wsync` is its repo mirror, see the mirroring rule below) → wsync moves a git bundle, fast-forwards the workstation, and pushes `origin` (JustVar) + `company` (employer-org).
- wsync aborts if the workstation tree is dirty; run multi-commit hops sequentially.
- apphost has ZERO git remotes as of 2026-07-27. A remote pointing at the
  employer-org repo through an unresolvable github-asset-tracker SSH alias
  was removed; it never resolved and nothing referenced it, so the one way
  relay is structural. The workstation remote names are LOAD BEARING: wsync
  hardcodes origin and company in both push commands and in the two ls-remote
  calls that build the four HEAD line. Do not rename them.

### git rm + at-sync-commit.sh (fixed 2026-07-24)
at-sync-commit.sh used to fail when passed a path already staged for deletion by
`git rm` — `git add -- "$@"` errored with "pathspec did not match" (bit us on
sw.js and the procurement removal). The script now filters staged-deletion paths
out of the add automatically, so passing a `git rm`'d path alongside modified
files is safe. Kept as history so the symptom is recognizable if it ever recurs.

### Sync scripts are mirrored — keep live and repo copies in lockstep
Each sync script exists twice: the live copy that's actually run, and a repo
mirror under `scripts/` (so it survives a host rebuild). The live copies sit on
DIFFERENT hosts:
- `at-sync-commit.sh` — live `~/bin/at-sync-commit.sh` on **apphost**, mirror `scripts/at-sync-commit.sh`.
- `wsync` — live `~/bin/wsync` on the **workstation**, mirror `scripts/wsync`.
Editing either side means updating the other in the SAME change; a working live
copy is not done until its mirror agrees (a stale mirror rots silently — this bit
us when at-sync-commit.sh was fixed in `~/bin` but not `scripts/`). Verify with
`diff`, run ON THE HOST WHERE THE LIVE COPY LIVES. Compare against the committed
blob, not the working file — `git show HEAD:scripts/wsync | diff - ~/bin/wsync` —
since a CRLF-smudged checkout reads as false drift.

### Static Files
- Located at repo root `static/` (bind-mounted to `/app/static` in the container) — NOT `app/static/`.
- CSS variables for dark/light theme in `static/css/main.css`.
- Page-level `<link>` and `<script>` tags for files under `static/` carry `?v={{ request.state.js_v('css/NAME.css') or '0' }}` (shape: `login.html:8`, `base.html:65-87`). `js_v` is an mtime-keyed sha1 of the file (`_asset_version` in `main.py`), so an edited file is fetched fresh with no restart. An untagged link is served stale by any browser that has it cached, for days: `receive.css` (fixed 726439c) and `scanner.css` (fixed b0f2223) both shipped that way.

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

### Shared CSS classes: add a prefixed class, never edit a shared rule

Board-level CSS classes are shared across several pages. Editing a shared rule
to fix the layout of one board changes every other board that uses it, and the
regression surfaces on a page the change never touched.

To restyle one board, add a new board-prefixed class and apply it alongside the
shared class. Do not edit the shared rule. Before editing any CSS rule, grep the
class name across app/templates and static/css and confirm it is used only by
the page you intend to change.

### Inline event handlers: server data needs |tojson|forceescape

Any server-side value interpolated into an inline handler attribute (onclick,
onchange, oninput) must go through `|tojson|forceescape`. Bare `{{ value }}` or
`'{{ value }}'` is an injection path for any field a user can write, including
serial numbers, SKUs, notes, and names.

`|tojson` renders the value as a valid JS literal and escapes quotes and
backslashes. `|forceescape` then HTML-escapes the double quotes tojson produces,
so they cannot terminate the attribute early. Either filter alone is not
sufficient. Live uses: admin_part_numbers.html and fulfillment.html.

### Tours (app/tours.py)
- 31 tour definitions, 26 currently enabled (see app/tours.py; lint via lint_tour_selectors).
- Each tour: id, name, page_pattern, steps (target selector + title + description). Engine in `static/js/guide.js`.
- See `docs/tour-dev-guide.md` for patterns and gotchas.

### Design Philosophy
"Grandma usable" — every page must be self-explanatory. Guided tours, clear labels, no tribal knowledge required.

---

## Architecture

### Triage system (`app/routes/triage.py`)

- One role, `hw`, in the `TRIAGE_ROLES` dict. Its field list is `Item.REQUIRED_FIELDS_HARDWARE` in models.py, and it also carries the two data checks (place mismatch, containment divergence). Owner spec: `docs/specs/triage-single-role.md`.
- **Sidenav badge** = `get_triage_total_count`: items with >=1 required-field gap or a data-check finding, decommissioned items excluded.
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
- **Contract test suite (rebuilt, replaces the retired NUC-era harness):** `tests/` holds 18 `test_*.py` files plus `conftest.py`, 885 passing and 39 skipped (as of 2026-09-02), run in-container with `docker compose exec -T app python -m pytest tests/ -q` in about 6 seconds. They drive httpx against `http://127.0.0.1:8081` and write to the LIVE `asset_tracker` database (no separate test cluster); fixtures prefix their rows `contract-test` and remove them afterwards, so a crashed run leaves obvious debris. There is no runner config file. **Coverage gap worth knowing: the audit page is untested.** No test references `has_audit_access`, `require_audit_viewer`, `can_view_audit_log` or `/admin/audit`, which is why a permanently-false boolean branch in the audit gate survived until 0c0ac31. A green suite says nothing about that surface.
- Vendors table + dropdown — currently free-text input on intake + triage
- **brand_sku managed vocabulary (B1 shipped; B2/B3 DEFERRED to Fulfillment):** Part Numbers admin CRUD (5414fe1), intake datalist (Phase 1), triage strict select (Phase 2) all shipped. The strict-select sweep across intake/item_detail/quick_view + shared macro (B2/B3) is DEFERRED: managed SKUs apply only to sellable categories (Edge Box, Camera 2 Cloud, Cloud Box); internal hardware uses serial number, not SKU. Per-category SKU filtering and the full cross-category SKU list are pending the Fulfillment phase. quick_view was prototyped as a flat select then reverted (would contradict the category model). Resume with the real catalog once Fulfillment defines the rules.
- Multi-viewer lock awareness, when Users page is built
- Mobile barcode-scan flow at `/scan` — explicitly deferred from main app, not yet started
- U2/U3 (Users + Departments UI rebuild) — sweep deferred renames per [docs/U2_U3_RENAME_FOLLOWUPS.md](docs/U2_U3_RENAME_FOLLOWUPS.md). U1 (2026-05-04) renamed the DB table only; cosmetic file/route/identifier renames are listed there.
- **Route migration `public.* -> item_schema` (inventory-display arc complete):** Inventory listing, the unified `/items/{id}` detail page (incl. component-history / maintenance / attributes panels), intake, triage, and the receipts panel all read item_schema. Per-category detail routes+templates were retired (commit 151da9b). Search migrated to a single item_schema.items query in 4136b36 (was iterating 22 per-category public.* tables via TABLE_MODELS), so Casey's imported items are now findable in global search. Warranty moved to items in item 30 S4 and components data in item 30 S2; board item 30 moves every other legacy reader and writer to items (`docs/specs/retire-legacy-inventory.md`).
- **Warranty is basic item tracking (item 30 S4, 2026-09-28):** a warranty hangs off an item through `device_warranties.item_id` and records vendor, start, end and notes (`app/routes/warranty.py`, Warranties link in the sidenav, read-only list on item detail). Scope cut by Jus: internal inventory items only; customer warranties on shipped hardware are tracked by the OEM, not here. RMA claims and internal loaners were retired in the same change (0 rows in every table involved), which supersedes the 2026-06-15 note that loaners kept warranty alive. Migration 082 made `device_table`/`device_id` nullable on warranties and assignments; the unused warranty columns, `warranty_claims` and the legacy pair drop in item 30 S5 (`docs/specs/retire-legacy-inventory.md`). Cardinality is 1:many item to warranty.
- **Sites list placed items (item 30 S4, 2026-09-28):** a site page lists the items whose `location_id` is that site; the sidenav has a Sites link. Device-to-site assignments (ownership type, return-by date) were retired by Jus, with their three routes, the provisioning completion hook that wrote one, and the dead `bulk.py`; `device_assignments` never held a row and drops in item 30 S5. Custody is checkouts; customer pilots coming back are the Fulfillment Pilots Due Back board.

- **Fulfillment buildout (NOT YET STARTED as a focused track; foundation exists):** fulfillment.py (6 routes: page, ship, deployments, status, export, technician-update) + fulfillment.html already exist as a Kanban command-center over the order subsystem. Built on a mature foundation: CustomerOrder model (order_number, Salesforce sync ids, 8-stage status pipeline new->...->installed plus a terminal cancelled, deployment_type, sku_requirements JSONB, shipping fields per migration 021, OEM PO cascade). Reads item_schema-agnostic order models; its TABLE_MODELS and legacy-class touchpoints (_stock_snapshot, the order panel, build certification) are listed in the item 30 census (`docs/specs/retire-legacy-inventory.md` section 8). Scope-later outline for the full buildout:
  - Flesh out the Kanban command-center UX over the order + provisioning pipeline (replaces the old separate /orders/ and /provisioning/ list pages).
  - Fulfillment's legacy-model usage moves to items in item 30 S4 (fulfillment and orders).
- **Item.data_completeness gap:** the unified Item model (item_schema.items) does NOT have data_completeness - that field lives on InventoryMixin, which Item does not inherit (the 22 legacy per-category models do). Surfaced during the search migration (4136b36) when the search dot-indicator was dropped. If a completeness/quality signal is ever wanted on the unified item, it needs modeling (or wire it to the existing triage-gap logic).
- **Retire the 22 legacy per-category models + public.* tables:** specced and ratified 2026-09-25 as board item 30. `docs/specs/retire-legacy-inventory.md` owns the design and the five slices (S1 schema, S2 data, S3 writers, S4 readers, S5 drop). No longer blocked on warranty or components: both move to items inside item 30.
- **Components data migration (routes retired in f3c379e; data moves in item 30):** the components.py routes (/install, /remove/{id}, /move/{id}, /available/{table}) were retired in f3c379e once the per-category detail templates that called them were deleted (151da9b). The public.device_components rows become item_schema.component_history events under item 30 rule R4 (`docs/specs/retire-legacy-inventory.md` section 5), and the table drops in S5. DeviceComponent has no reader in app/.
- **scanner.js is live (do NOT delete):** static/js/scanner.js defines the BarcodeScanner class, loaded by receive.html, provisioning_detail.html, and fulfillment.html for the receiving/provisioning/fulfillment scan workflows. A prior bullet wrongly flagged it as orphaned from the scanner-architecture removal; that removal was a different surface. Verified loaded 2026-06-15.
- **Casey DB access (done 2026-06-10):** `casey` role created on live cluster, `item_schema`-scoped (DML + CREATE), isolated from `public.*`. External login pending Casey's own verification.

- **Attribute + checkout editing via forms:** the unified detail page shows per-category `attributes` read-only; check-out recipient/notes are set only on the checkout form. Form-based editing of `items.attributes` is deferred (data enters via Casey's import); revisit with the intake-form work.
## The item category vocabulary is hand-maintained

The app does not read `item_categories` from the database. `ALL_CATEGORIES`
in `app/routes/dashboard.py` is `list(CATEGORY_COLORS.keys())`, and every
category dropdown and the inventory filter use it (intake, triage, item edit,
Part Numbers). A category the list does not carry cannot be picked or
filtered. A new enum value therefore also needs an entry in:

- the `item_categories_enum` list in `app/models.py`;
- `CATEGORY_COLORS` and `CATEGORY_DISPLAY_NAMES` (`app/routes/dashboard.py`);
- `CATEGORY_ATTRIBUTES` (`app/item_fields.py`), which carries every value;
- `UNIT_CATEGORIES` (`app/containment.py`) and its JS copy `CTM_UNIT_CATS`
  (`app/templates/receive.html`), if the category can hold components;
- `TARGET_TABLE_TO_CATEGORY` (`app/routes/receiving.py`), if scan intake
  should create it.

Migration 080 added `phone`, `webcam`, `printer` and `nas` (board item 30
S1); scan intake maps phones, webcams, printers and NAS to them since
item 30 S3.

## RBAC / Admin pages (post U4, 2026-05-18)

The asset tracker has 11 gated admin pages plus the Slack-bot path, which is a public 301 redirect. The matching sidenav link in `base.html` is gated by the same property on the User model. Route gate and nav gate stay in lockstep - change one, change the other.

The lockstep rule pairs the PAGE gate with the nav gate. Mutation gates on the same page may be stricter, so a visible link does not imply the buttons on that page will work - OUI reference and Part Numbers are both editor-readable but system-admin-writable.

### Role × admin-page matrix

| Page | URL | Read gate | Write gate | Nav gate | Property |
|---|---|---|---|---|---|
| Users | /admin/users | require_user_manager | require_user_manager | user.has_user_management | admin tier + can_manage_users |
| Departments | /admin/departments | require_user_manager | require_user_manager | user.has_user_management | admin tier + can_manage_users |
| Audit log | /admin/audit | require_audit_viewer | (read only) | user.has_audit_access | admin tier + explicit user-level can_view_audit_log grant |
| Error log | /admin/errors | require_system_admin | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| OUI reference | /admin/oui | require_editor | require_system_admin | user.is_editor_or_above | editor + sub-admins + admin tier |
| Part Numbers | /admin/part-numbers | require_editor | require_system_admin | user.is_editor_or_above | editor + sub-admins + admin tier |
| Receipts | /receipts | require_receipts | require_receipts | user.has_receipts_access | admin tier + can_view_receipts |
| Storage | /admin/storage | require_system_admin | (read only) | user.has_system_admin | admin tier + can_manage_system |
| Notifications | /admin/notifications | require_system_admin | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Zendesk | /admin/zendesk | require_system_admin | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Maintenance | /admin/maintenance | require_system_admin | require_system_admin | user.has_system_admin | admin tier + can_manage_system |
| Slack-bot redirect | /admin/slack-bot | (none, public 301) | (none) | (no link) | redirects to /admin/notifications |

Footnotes on rows that do not fit the pattern:

- **Receipts** sits at `/receipts`, NOT under `/admin/`, even though its link lives in the Admin > Data & logs subgroup.
- **Notifications** is served by `slack_bot_routes.py` - the same module as the `/admin/slack-bot` redirect - not by `notification_routes.py`. The 12 `/api/notifications/*` endpoints in `notification_routes.py` are the per-user notification feed and are gated by `get_current_user`, not by an admin dependency. Do not read that module and conclude the admin page is ungated.
- **Error log** write is `DELETE /api/errors/prune` (require_system_admin). The ingest endpoint `POST /api/errors/report` is deliberately gated only by `get_current_user` so the browser JS error handler works for any signed-in user.

### No router-level gates - every route carries its own

`admin.py` declares a bare `APIRouter()` with no `dependencies=[...]`, and `main.py` includes it with no prefix. There is no router-level gate anywhere in the admin surface. Every route carries its own dependency, and a missing one fails silently - the route just becomes reachable, with nothing to raise. A per-route audit is the only check that catches it.

### Sidenav structure (post U4b)

The Admin section is a collapsible nested menu (`.sx-nav__section[data-section="admin"]`) containing four subgroups:

- **People** — Users, Departments
- **Data & logs** — Audit log, Error log, OUI reference, Part Numbers, Receipts
- **Integrations** — Notifications, Zendesk (Intune and Spreadsheet sync retired in item 30 S3)
- **System** — Maintenance, Storage

Each subgroup auto-hides if no children inside it are visible to the current user. On page load the JS finds `.sx-nav__link--active` and walks up with `closest()` to expand that link's subgroup and section; it does NOT test the URL. Consequence: `/receipts` expands the Admin section even though its URL is not under `/admin/`.

### Property to require_* dependency mapping

When adding a new admin route, use these pairings:

| `require_*` dependency | Matching User property | Used for |
|---|---|---|
| require_editor | user.is_editor_or_above | broad access - editor + sub-admins + admin tier |
| require_user_manager | user.has_user_management | user/dept admin |
| require_audit_viewer | user.has_audit_access | audit log visibility (admin tier, or an explicit user-level grant) |
| require_system_admin | user.has_system_admin | system operations |
| require_receipts | user.has_receipts_access | receipts and vendor profile edits |
| require_provisioning_viewer | user.has_provisioning_view | fulfillment reads |
| require_provisioning_manager | user.has_provisioning_manage | fulfillment writes |

This table covers the admin-page subset only. `app/auth.py` defines 14 `require_*` dependencies plus a `require_role()` factory; the rest gate non-admin surfaces (map, receiving, scanning, disposal, credentials, warranty, trials, sites).

### 403 handling (post U4c)

The global exception handler in `main.py` intercepts 403s and branches:

1. **HTMX request** (`HX-Request: true` header) — returns 403 with `HX-Refresh: true` header, triggering a full browser navigation (not an in-shell swap) to the same URL, which then hits the handler again as a plain HTML request.
2. **Browser HTML** (`Accept: text/html`) — renders `permission_denied.html` inside the app shell with the per-call `exc.detail` message and a Contact Admin button.
3. **API/JSON** — preserves default `{"detail": ...}` shape for programmatic consumers.

The HTMX branch was added because hx-boost on the sidenav was swallowing 403 redirects and producing in-shell swaps that left the user with a Frankenstein page. Same root cause as the logout bug fixed in U4b.

## Page-level JS and hx-boost script re-execution

An hx-boost swap re-executes every script inside the swapped region. Page-level
JS must declare with `var`, never a top-level `let` or `const`. A top-level
lexical binding survives removal of the old script element, so the second
execution throws a redeclaration `SyntaxError` that aborts the whole block and
leaves every function defined below it undefined. The failure is silent in the
UI: no visible error, handlers simply stop responding. Init hooks must run again
on a boosted entry, but NOT via an htmx event: use `PageInit`, defined in
`base.html` before `<main>`. See
`docs/specs/page-init-on-boosted-navigation.md` for why an event cannot work.

Only top-level declarations. A `let` or `const` inside a function is correctly
scoped and must not be converted; converting one changes semantics. Do not wrap
a page block in an IIFE either, since every inline `onclick` in the templates
resolves against global scope.

This is not hypothetical. `fulfillment.html` opened its main block with
`let currentMode`, so returning to the board through the sidenav left all four
modal openers and every board handler undefined. Loading the URL directly always
worked, which is why it survived so long.

## Jinja parses its delimiters everywhere in a template

Jinja reads a template as text, not as HTML. It expands `{% %}` and `{{ }}`
inside a `<script>` element, inside a JS comment, and inside an HTML comment,
because none of those mean anything to it.

So quoting a Jinja tag to explain it opens a real one. A JS comment reading
"loaded under a not-kiosk conditional" is safe; writing that conditional out
verbatim inside the comment starts a block Jinja then expects to be closed, and
the template fails to parse with an error pointing at a completely unrelated
`endblock` further down the file. That cost one reverted patch during the boosted
navigation track.

Describe Jinja syntax in prose, or build the literal with concatenation. The
jinja parse gate catches it, which is the argument for running that gate before
anything slower.

## The suite total moves when a route is added

`tests/test_auth_census.py` generates cases from the live route table rather than
listing them, so a new route adds cases with no test file in the diff: **2 for a
write route** (gated, plus write-tier) and **1 for a read route**.
`tests/test_nav_boost_census.py` does the same from the sidenav, one case per
boosted link plus two fixed cases.

Predict the expected total before running, and treat a difference from the
prediction as a signal rather than noise. A route added without a test still
moves the number, which is the point.

## The suite writes to the live database

There is no separate test cluster. `tests/` runs against `asset_tracker`, the
same database the app serves. Cleanup is commit-then-DELETE in fixture
teardown; nothing rolls back, and the stray `db.rollback()` calls in fixtures
are defensive resets of an aborted session, not cleanup. Three consequences:

- **Sequences advance even though no row survives**, because rows are committed
  and then deleted, and deletion does not reset a sequence.
  `deployment_records_id_seq` moved 11 across one run: eleven fixture
  instantiations, one committed-then-deleted row each. Gaps are fixture churn,
  not lost data.
- **A run that dies before teardown leaves real rows.** Every fixture commits;
  the teardown DELETE is the only thing that removes the data. Fixtures prefix
  theirs `contract-test` so the debris is identifiable.
- **A teardown DELETE fires foreign-key actions.** Deleting a test
  `deployment_records` row cascades into `installation_certification` and sets
  `device_provisioning.deployment_record_id` to NULL on anything linked to it.
  Fixtures create their own linked rows today, so nothing real is touched, but
  a fixture that ever links a test row to a real one will have its teardown
  mutate real data. Rollback could not do that; DELETE can.

## A spec can be stale on arrival

A spec written on the workstation and committed later can describe a codebase
that has since moved. Re-verify a spec against HEAD before committing it.
docs/audit-log-scope.md described three defects that had been fixed the day
before it landed.
