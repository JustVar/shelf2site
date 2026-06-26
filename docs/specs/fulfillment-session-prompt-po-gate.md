# Fulfillment F2 — PO Gate (next session)

## Your task
Implement the **PO gate**: an order must have a `po_number` (Customer PO) before any device can be linked to it (i.e. before a device enters the fulfillment pipeline). This is the last route-logic piece of F2.

## How to work (read first)
- Be concise. Minimal chatter, no recaps of what you just did, short status lines. Gate each risky step and wait for confirmation.
- **Settle the edit/deploy workflow before touching code.** Prior sessions edited and committed *on apphost* over ssh, then bundled to the workstation and pushed. You are now in Claude Code / VS Code on the workstation, which changes that. Do NOT assume a flow. Confirm one of:
  - (recommended, proven) keep editing + committing on apphost over ssh, bundle back to the workstation, push both remotes — you run the ssh/scp/git yourself instead of the user pasting output; or
  - edit locally then deploy to apphost — only if you first resolve the sync direction explicitly, because local-edit + scp-to-host has twice caused repo/server divergence here.
  Get this right before the first edit.
- Prefer **guarded patches**: a small Python script that validates each anchor matches exactly once, backs up the file(s) to `/tmp/*.bak`, then applies. Review `git diff` (only the intended hunks) and run a syntax check before restart.
- For files/commit messages with quotes, use Write+scp (a real file), not an inline heredoc with `'...'`. Commit messages: no apostrophes, no em dashes; pass via `-F /tmp/msg`.
- **Verify each change live with data before committing**, not after. The gate is behavioral, so a data test is mandatory (see below).
- New or restructured UI must follow the **new design mockups** (emerald/slate, Fulfillment-scoped; AssetFlow Pro Build-Cert / Install-Panel). Ask the user to paste the relevant mockup at the start of any UI work. (The gate itself is route logic; its only UI surface is an error message.)

## Environment
- App: FastAPI + Jinja2 + HTMX + Postgres, Docker Compose, on **apphost (192.0.2.10)** at `/opt/asset_tracker/`, served `http://192.0.2.10:8100/assettracker/`. SSH: `ssh -i ~/.ssh/id_ed25519 admin@192.0.2.10`.
- `app/` changes need `docker compose restart app`; templates re-read per request. Run scripts in-container: `docker compose exec -T app python < /tmp/x.py`.
- Migrations are numbered self-executing scripts (048 pattern), not Alembic. Type/status columns are `VARCHAR(32)` + app validation, not Postgres ENUM.
- Git: two remotes, `origin` (JustVar) + `company` (employer-org). The **workstation is the only push node**; apphost has no push creds (hence the bundle flow). After every commit, confirm all four HEADs (local / apphost / origin / company) match **before** cleanup.
- Do not persist any secrets the user shares; they are operational only.

## Current state (HEAD `dc8dbef`)
Shipped and synced this session, F1a → F2 edit modal:
- `5e31941` F1a — `device_provisioning.fulfillment_type`, `customer_orders.default_fulfillment_type` + `po_number` (UNIQUE), migration 049.
- `4d938cc` F1b — `build_certification` + `install_certification` tables + models, migration 050.
- `c825ed1` F2 S1 — `create_order`/`update_order` accept `po_number` + `default_fulfillment_type`; UNIQUE violation returns a clean 400, not a 500.
- `d80bbe5` F2 S2 — order card "Cust PO" chip; `_build_order_card` + `order_devices` carry the new fields.
- `e75bfb5` F2 S3 — per-device build-method label in the slide-panel device rows.
- `9fbf1d3` F2 — Customer PO + Default Fulfillment Type fields on the create-order form; create handler now reads the `error` key (dup PO shows the real message).
- `dc8dbef` F2 — real edit-order modal on `order_detail.html` (was a stub alert); prefilled, SE datalist from `se_names`, dup-PO error surfaced in the modal.

`customer_orders` is empty (all test data self-cleaned). The full create → card-chip → edit-modal → save loop is verified live.

## The gate — scope
A device "enters the pipeline" when its provisioning record gets a `customer_order_id`. Three entry points set that; all three need the guard:
1. `create_provisioning` — `app/routes/provisioning.py` ~line 391 (POST `/api/provisioning`). Already validates the order exists (~417–420). Add the PO check right after that.
2. `bulk_assign_order` — `app/routes/provisioning.py` ~line 1328 (POST `/api/provisioning/bulk-assign-order`); sets `rec.customer_order_id = order_id` ~1361. Check the order's PO **once, before assigning any record**, so it never partially assigns then fails.
3. `link_order` — `app/routes/orders.py` ~line 397 (POST `/api/provisioning/{prov_id}/link-order`). It already fetches the `order` object inside the `if order_id:` branch. Add the check there.

Rule, precisely:
- Linking a device to an order **without** a `po_number` → block with **400** and a clear message, e.g. `"This order needs a Customer PO before devices can enter the pipeline."`
- Linking to an order **with** a `po_number` → allowed.
- **Unlinking** (`link_order` with `order_id` null) → always allowed; do not gate it.
- The gate applies at link time only; pre-existing links are untouched.

Re-read the three handlers' raw source before writing anything (line numbers drift). Note this is the first slice that changes existing flow rather than adding to it — a misplaced guard can block legitimate links or fail to block, so placement and the data test matter more than usual.

## Verification (mandatory data test, self-cleaning)
With real (throwaway) data, prove the gate blocks the right thing and only the right thing, then delete the test data:
- Order **without** a PO + a provisioning record → attempt link via each of the three paths → expect **400** + the message; the record stays unlinked.
- Add a PO to that order → retry the link → expect success.
- Unlink → expect success regardless of PO.
- `bulk_assign_order` with a no-PO order → expect it blocks before any record is assigned (no partial state).
Use whatever the environment supports for an authed request (a logged-in browser session, or an in-container script that calls the handlers' logic). Clean up all test orders/records and confirm counts return to baseline.

## After the gate (remaining F2/F3, not this session)
- F2 board restructure + scoped palette (tabs + large grouped cards, strip the MOCK scaffold) — uses the new mockups.
- Expand-to-units; per-device `fulfillment_type` write endpoint + control; assignee filter.
- F3/F4 cert modals → `build_certification` / `install_certification` (Build-Cert mockup is still a stub; get the full field list first).
- Parked: remove `contract_value`/`hardware_cost` columns + route params (the user's "no cost/contract anywhere" call — its own migration + route slice); roadmap rows for F1a/F1b/F2 in the separate dashboards repo; `/c/tmp` debris cleanup (~400 files from old Write+scp leftovers); align the create-order SE field to a datalist for consistency with edit.
