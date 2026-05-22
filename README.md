# Asset Tracker

Privacy-first hardware inventory tracker with network auto-discovery, encrypted credentials vault, and HTMX dashboard.

**Stack:** FastAPI + PostgreSQL + nmap + SQLAlchemy + HTMX + Jinja2

## Features

- **14 inventory categories** — Edge boxes, cameras, NUCs, network equipment, monitors, phones, GPUs, and more
- **Network auto-discovery** — nmap-based scanning with auto-learning OUI allowlist (discovers ALL devices, OUI catalog grows automatically)
- **Encrypted credentials vault** — Fernet-encrypted storage for device passwords, PINs, and access credentials
- **Pending device queue** — New discoveries go to an approval queue before entering inventory
- **Geographic map view** — Leaflet.js map for edge box locations
- **Role-based access** — Admin, Editor, and Viewer roles with bcrypt password hashing
- **Audit logging** — Full JSONB audit trail for all changes
- **Real-time updates** — Server-sent events (SSE) for live dashboard updates
- **Multi-NUC scanning** — Local scanner (NUC 1) + remote agents (NUC 2+) via API

## RBAC Verification (MANDATORY)

**All new features and edits MUST verify RBAC rules before deployment.**

### When to Verify
- Adding new routes or API endpoints
- Creating new UI features or pages
- Modifying existing features that handle sensitive data
- Adding new database models with restricted fields
- Changing navigation or sidebar links

### What to Check
1. **Route Protection**: Ensure routes use appropriate auth dependencies
   - `Depends(require_admin)` — Admin-only features
   - `Depends(require_editor)` — Editor+ features
   - `Depends(require_financial)` — Financial data access
   - `Depends(require_viewer)` — All authenticated users

2. **UI Conditionals**: Hide/show navigation and controls based on role
   - Check `base.html` sidebar links use `{% if user.role in [...] %}`
   - Verify modals show admin-only controls conditionally
   - Ensure permission-gated features don't leak in HTML

3. **API Field Protection**: Protect admin-only fields in CRUD operations
   - Check `app/routes/api.py` for `admin_only_fields` list
   - Verify sensitive fields can't be modified by non-admins

4. **Permission Errors**: Return proper 403 errors with custom messages
   - HTTPException with status_code=403
   - Include clear detail message explaining required permission
   - Error handler renders `permission_denied.html` template

### Testing
Refer to [docs/RBAC_TEST_PLAN.md](docs/RBAC_TEST_PLAN.md) for comprehensive test scenarios.

Test with three user types:
- **Viewer**: Read-only access, no map, no financial data
- **Editor**: Can edit devices and access map, no financial data (unless granted)
- **Admin**: Full access including user management and financial data

### Current RBAC Rules
| Feature | Viewer | Editor | Editor+Financial | Admin |
|---------|--------|--------|------------------|-------|
| Dashboard | ✅ | ✅ | ✅ | ✅ |
| Device CRUD | View only | Edit | Edit | Full |
| Edge Box Map | ❌ | ✅ | ✅ | ✅ |
| Procurement Analytics | ❌ | ❌ | ✅ | ✅ |
| User Management | ❌ | ❌ | ❌ | ✅ |
| Storage Monitor | ❌ | ❌ | ❌ | ✅ |
| Map Privacy Controls | ❌ | ❌ | ❌ | ✅ |

## Prerequisites

- Python 3.10+
- PostgreSQL 14+
- nmap (for network scanning)

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/employer-org/asset-tracker.git
cd asset-tracker
pip install -r requirements.txt

# 2. Configure
cp .env.template .env
# Edit .env with your database credentials and generate encryption keys

# 3. Create PostgreSQL database
createdb hardware_inventory

# 4. Run the app (tables are created automatically on first start)
uvicorn app.main:app --host 0.0.0.0 --port 8081

# 5. Create initial admin user
python scripts/create_admin_user.py

# 6. Seed OUI allowlist (known manufacturer MAC prefixes)
python scripts/seed_oui_allowlist.py

# 7. (Optional) Import data from Excel spreadsheet
python scripts/import_spreadsheet.py
```

## Project Structure

```
asset-tracker/
  app/                     FastAPI application
    main.py                Entry point
    config.py              Settings from .env
    database.py            SQLAlchemy + PostgreSQL
    models.py              19 ORM tables (14 inventory + 5 system)
    auth.py                Authentication + role checks
    credentials.py         Fernet encryption for vault
    audit.py               Audit log events
    routes/                11 route modules
    templates/             Jinja2 HTML + HTMX templates
  scanner/                 Network discovery pipeline
    network_scanner.py     nmap subnet scanner
    oui_lookup.py          MAC vendor lookup
    discovery_pipeline.py  OUI filtering + pending queue
    scanner_agent.py       Remote agent (NUC 2+)
  scripts/                 Setup and initialization
    create_admin_user.py   Create initial users
    seed_oui_allowlist.py  Seed known OUI prefixes
    import_spreadsheet.py  Import Excel data
  static/                  CSS, JavaScript
  data/                    Spreadsheet import data
```

## Scripts

Operational and setup scripts live in `scripts/`. They run inside the app
container, which has the database connection (`DATABASE_URL`) and app
dependencies available:

```
docker compose exec app python scripts/<name>.py
```

### Setup (run once on a fresh install)

- `create_admin_user.py` — create the initial admin account
- `seed_oui_allowlist.py` — seed the OUI allowlist
- `seed_nas_devices.py` — seed the four QNAP NAS devices

### Imports

These read source files from `scripts/` (CSVs and XLSX) and write to the database. They are **not destructive in the schema sense**, but most of them **delete and re-create rows in their target tables on every run**, so an interrupted import can leave the DB in a partial state. Always run with `--dry-run` first if the script supports it.

- `import_part_numbers.py` — upsert part numbers from XLSX
- `import_edge_boxes.py` — ⚠️ deletes existing edge-box rows before importing
- `import_all_categories.py` — ⚠️ deletes rows across multiple categories before importing
- `import_spreadsheet.py` — legacy full import
- `import_spreadsheet_v2.py` — current full import (supports `--dry-run` and `--validate`)
- `link_custom_builds.py` — creates custom-build Computer records

### Maintenance

- `backfill_completeness.py` — backfill completeness scores
- `recalculate_completeness.py` — recompute completeness scores (ORM-based)
- `fix_camera_manufacturers.py` — fill camera manufacturers by MAC prefix
- `add_financial_permission.py` — one-off migration: add the financial permission column
- `add_show_on_map_field.py` — one-off migration: add the show-on-map field

### 🔴 Destructive

These can cause data loss. Read the script source before running. Do **not** run against the production database without a fresh DB backup.

- `reset_inventory_safe.py` — drops inventory tables (preserves users, audit log, and credentials)

## Scanner Modes

- **Local** (`SCANNER_MODE=local`): Runs a background scan loop, writes directly to the database
- **Remote** (`SCANNER_MODE=remote`): Posts scan results to the central API at `/api/discover`

## Environment Variables

See `.env.template` for all configuration options including database, scanner, encryption keys, and Slack webhook.

---

the company -- Internal Use Only
