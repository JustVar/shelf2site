<picture>
  <source media="(prefers-color-scheme: dark)" srcset="static/img/logo-horizontal-dark.svg">
  <img src="static/img/logo-horizontal-light.svg" width="300" alt="Shelf2Site">
</picture>

# Shelf2Site: hardware from the shelf to the customer site

[![CI](https://github.com/JustVar/shelf2site/actions/workflows/ci.yml/badge.svg)](https://github.com/JustVar/shelf2site/actions/workflows/ci.yml)

Justin Varughese. [LinkedIn](https://www.linkedin.com/in/justin-var/)

I built this hardware asset tracker for internal use at a hardware startup,
where it tracked every edge server, camera and laptop from the day it arrived
to the day it was installed at a customer site or came back from a pilot. The
company has since closed. The app is published here under a new name,
Shelf2Site, and runs on its own with demo data. I built it with Claude as the coding partner, under rules and checks I
set up so that its work had to prove itself.

> **About the data in this repo.** It holds no passwords, keys, customer data
> or company records. Hosts, addresses and people's names in the history and
> the docs are replaced with placeholders such as `apphost` and `192.0.2.10`.
> Every screenshot and video below comes from the demo data that
> `scripts/seed_demo.py` creates.

**[Watch the 3.5 minute walkthrough](docs/media/proof/shelf2site-walkthrough.mp4)**:
a new pilot is created, units are assigned from stock and shipped, the site
visit is scheduled and certified, and a vendor order gets its certificate.

![The fulfillment board: tiles for open, late, due back and missing documents, tabs for each track, and one card per order](docs/media/clips/board.gif)

| | |
|---|---|
| What it does | Inventory with intake and barcode scanning, data-quality triage, warranties, sites and a deployment map, and a fulfillment board with two tracks: vendor-built orders and pilots or demos lent from stock |
| Size | 258 routes (106 pages and reads, 152 writes), 49 templates, 85 migrations, 26 guided tours |
| Tests | 1,096 contract tests that drive the running app over HTTP against a real Postgres database, including a census that checks every route for an auth gate |
| History | Over 450 commits between May and October 2026, with 52 written specs in `docs/specs/` |
| Stack | Python, FastAPI, Jinja2, HTMX, PostgreSQL 16, SQLAlchemy, server-sent events over Postgres LISTEN/NOTIFY, MapLibre, Docker Compose, GitHub Actions. Built with Claude (chat for design and browser checks, Claude Code for the build) |

## Where to start

1. This page, the walkthrough video and the screenshots below.
2. The two tracks: [app/order_tracks.py](app/order_tracks.py) maps one stored
   status vocabulary onto both boards, and
   [tests/test_order_tracks.py](tests/test_order_tracks.py) checks the map is
   total and walks an order down each track.
3. The auth census: [tests/test_auth_census.py](tests/test_auth_census.py)
   reads the live route table, so a new route without a permission check fails
   the suite even when nobody wrote a test for it.
4. How Claude was kept honest: [CLAUDE.md](CLAUDE.md) and the workflow skill
   in [.claude/skills/asset-tracker-workflow/SKILL.md](.claude/skills/asset-tracker-workflow/SKILL.md).
5. One spec from idea to code:
   [docs/specs/one-board-two-tracks.md](docs/specs/one-board-two-tracks.md).

## Screenshots

| | |
|---|---|
| [![A vendor order: the track stepper at Installed, SKU lines all linked, the purchase order, units, vendor documents and the certified site visit](docs/media/screenshots/order-vendor-dark.png)](docs/media/screenshots/order-vendor-dark.png) | [![A pilot out at a customer site: four units deployed, the due back date and a Mark returned button](docs/media/screenshots/order-pilot-light.png)](docs/media/screenshots/order-pilot-light.png) |
| **A vendor order.** Ordered, Building, Shipped, Installed, with the vendor's certificate and validation report attached and the install certified. | **A pilot from stock.** Assigned, Shipped, Out at site, Returned. Each unit can come back on its own. |
| [![The deployment map with units coloured by deal type, a legend with counts, and the top customers by units](docs/media/screenshots/map-dark.png)](docs/media/screenshots/map-dark.png) | [![The dashboard with inventory totals, a category bar, recent activity and quick actions](docs/media/screenshots/dashboard-light.png)](docs/media/screenshots/dashboard-light.png) |
| **Deployment map.** Every unit at a customer site, coloured by deal type, unit type or status. | **Dashboard.** What is ready to deploy, what is out, and what needs attention. |
| [![The inventory list with category tiles, filters and one row per item](docs/media/screenshots/inventory-dark.png)](docs/media/screenshots/inventory-dark.png) | [![Asset triage: items missing required fields, each fixable in place](docs/media/screenshots/triage-light.png)](docs/media/screenshots/triage-light.png) |
| **Inventory.** Every item with its category, status, place and SKU. | **Asset triage.** Items missing a field a person has to fill, fixed in place. |
| [![Pilots due back, grouped by customer with each unit and its due date](docs/media/screenshots/pilots-due-back-dark.png)](docs/media/screenshots/pilots-due-back-dark.png) | [![The phone launcher: Scan and Receive, Check Out, Check In and Search](docs/media/screenshots/mobile.png)](docs/media/screenshots/mobile.png) |
| **Pilots due back.** What to collect, and when. | **On a phone.** Scanning, check out and in, search and item pages open directly; anything else goes to this launcher. |

All screenshots are in [docs/media/screenshots](docs/media/screenshots), each
page in both themes.

### Short clips

| | |
|---|---|
| ![Creating a pilot, assigning units from stock and shipping it](docs/media/clips/pilot.gif) | ![Attaching a vendor certificate to an order that shipped without one](docs/media/clips/docs.gif) |
| **A pilot, start to ship.** | **A missing certificate, attached.** |

MP4 versions are in [docs/media/clips](docs/media/clips). Every image and
video here is produced by [scripts/capture_media.py](scripts/capture_media.py),
which drives the demo in a headless browser, so they can be made again after
any change.

## What it does

- **Fulfillment, one board with two tracks.** A vendor order moves through
  Ordered, Building, Shipped and Installed while the vendor builds and
  certifies the hardware. A pilot or demo moves through Assigned, Shipped, Out
  at site and Returned, using units from stock. Tiles count what is open,
  late, due back within 30 days and shipped without a certificate. Each order
  has one page for its SKU lines, purchase orders, units, shipping, documents
  and site visits.
- **Inventory and intake.** Receiving against a purchase order, barcode and
  QR scanning from a phone camera, OCR of label photos, and a review queue
  for devices that need an admin's approval.
- **Data quality.** Asset Triage lists every item missing a required field or
  failing a data check, and the sidebar badge updates live as people fix them.
- **Deployment map.** Units at customer sites on a map, filtered by deal type,
  unit type and status, with a kiosk view for a lobby screen.
- **Permissions.** Nine roles in three tiers, per-user grants that override a
  department, sensitive customers hidden from anyone without access, and an
  audit log of every change.
- **Guided tours.** 26 tours explain each page in place. A test checks that
  every step still points at an element on its page.

## Engineering highlights

1. **One vocabulary, two boards.** Orders keep a single stored status.
   [app/order_tracks.py](app/order_tracks.py) maps it onto each track's
   columns, derives Returned from the units that came back, and refuses a step
   that skips a column, a sale with no customer PO, or a pilot shipped with no
   units. A test fails if any stored status has no column on either track.
2. **Routes that cannot ship ungated.** The auth census generates cases from
   the route table: one per read and two per write. Adding a route moves the
   suite total with no test file in the diff, which is the point.
   [tests/test_auth_census.py](tests/test_auth_census.py)
3. **Tests against the real thing.** The suite talks HTTP to the running app
   and checks the database it wrote to. It runs on an empty database and on
   the demo data, in CI on every push.
   [.github/workflows/ci.yml](.github/workflows/ci.yml)
4. **A schema built from code, and migrations that rehearse.** A fresh
   install builds the schema from the models. Each migration is a dry run by
   default, applies with `--apply`, and reports ALREADY APPLIED on a rerun. A
   migrated old database was compared object by object with a fresh build.
   [app/schema.py](app/schema.py), [migrations/](migrations)
5. **Live updates across workers.** Server-sent events fan out through
   Postgres LISTEN/NOTIFY, so every gunicorn worker hears every change.
   [app/routes/sse.py](app/routes/sse.py)
6. **Passwords checked against what attackers try.** Length first, then a
   one-million-entry breach list, context words and repeated patterns, after
   folding look-alike Unicode characters.
   [app/password_rules.py](app/password_rules.py),
   [docs/PASSWORD_POLICY.md](docs/PASSWORD_POLICY.md)

## How I work with Claude

I designed, decided and checked; Claude wrote most of the code. The work ran
on two surfaces: Claude in chat to design, decide and test in the browser,
and Claude Code to build. I set the scope and gave the final approval on
every change. The practices that kept the output honest are written down in
[CLAUDE.md](CLAUDE.md) and the
[workflow skill](.claude/skills/asset-tracker-workflow/SKILL.md):

- **Read before you write.** Discovery commands run before any edit, and a
  line number is re-read right before it is used, because they drift.
- **Raw output, marked.** A claim is marked as read, reported or unread. A
  description of a diff is not the diff, and a gate is not passed until its
  output is shown.
- **A gate must be able to fail.** Every check names something that differs
  between the working and the broken system.
- **Guarded patches.** Patch scripts assert the exact number of anchor
  matches, refuse to run twice, check their own result, and are read back in
  full before they run.
- **The diff before every commit**, and nothing mutating before the checkpoint
  it waits on.
- **Lessons become rules.** Each mistake that cost time became a written rule
  with the reason behind it: the hx-boost script redeclaration, Jinja tags
  inside comments, shared CSS classes, sequence gaps from test fixtures.

The last stretch before publication was done the same way: the two-track
fulfillment board, an audit of every page in both themes, the rename, CI and
the media in this README.

## Running it

### With Docker

```bash
git clone https://github.com/JustVar/shelf2site.git
cd shelf2site
cp .env.template .env     # fill in the three GENERATE values; each line says how
docker compose up -d --build --wait
docker compose exec app python -m scripts.seed_demo
```

Open http://localhost:8081 and sign in as `demo` with the password
`harbor-lantern-quilt-42`. These are demo credentials for a local copy.
To start empty instead, skip the seed and run
`docker compose exec app python -m scripts.create_admin_user admin "Your Name"`.

### Without Docker

Python 3.11 or newer and PostgreSQL 16.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
bash scripts/fetch_password_blocklist.sh
export DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/asset_tracker
export SESSION_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')
export CREDENTIAL_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
python -m scripts.init_db
python -m scripts.seed_demo
python -m uvicorn app.main:app --host 127.0.0.1 --port 8081
```

### Tests

With the app running on port 8081: `python -m pytest tests/ -q`. The suite
writes to the database the app uses and removes its own rows afterwards, so
point it at a demo or scratch database, never a real one. In Docker:
`docker compose exec app python -m pytest tests/ -q`.

## Repository map

| Path | What is there |
|---|---|
| `app/` | The FastAPI app: models, permissions, the order tracks, the schema builder |
| `app/routes/` | One module per area: fulfillment, orders, inventory, intake, triage, map, admin |
| `app/templates/` | Jinja2 pages with HTMX; page scripts use `var` so boosted navigation can re-run them |
| `static/` | CSS, JavaScript, fonts and the vendored HTMX, MapLibre and html5-qrcode |
| `tests/` | The contract suite |
| `migrations/` | Numbered migrations for existing databases |
| `scripts/` | Demo seed, first admin, media capture, and the backup and sync scripts from the production host |
| `docs/` | Specs, runbooks, the schema reference and the media |

## Terms

| Term | Meaning |
|---|---|
| Vendor track | Orders built, certified and shipped by an outside vendor (OEM). |
| Pilots and demos track | Units lent from stock to a customer for a trial, and collected again. |
| SKU line | One line of what an order needs: a model, a quantity and where it comes from. |
| Triage | The list of items missing a required field or failing a data check. |
| Census | A test generated from the live route table or sidebar rather than written by hand. |
| hx-boost | HTMX swapping in the next page without a full reload, which re-runs that page's scripts. |
| Four-location sync | How a commit moved on the production host: host, workstation and two GitHub remotes, all checked to agree. |

## Licence

Published for portfolio review. No licence is granted; see [NOTICE](NOTICE),
which also lists the third-party code, fonts and map data and their licences.

## Contact

Justin Varughese, [LinkedIn](https://www.linkedin.com/in/justin-var/)
