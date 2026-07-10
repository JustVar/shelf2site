# Endpoint Auth Census

**Generated 2026-07-09** from live route introspection on apphost (267 routes at commit `b4fcd6c`).
This is the authoritative map of every route and its auth gate. **When you add an endpoint, add
its row here** and make sure it fits one of the gate classes below.

## How to regenerate

```bash
# scripts/route_census.py dumps every route + resolved auth deps as JSON lines
ssh admin@192.0.2.10 "cd /opt/asset_tracker && docker compose exec -T app python - < scripts/route_census.py"
```

## How auth is layered

1. **Session middleware + auth redirect middleware** (`app/main.py`): unauthenticated *browser*
   requests to any non-public path 302 to `/login`. `/api/*` passes through so route
   dependencies return JSON 401 instead. **A route with no dependency under `/api/` is therefore
   fully unauthenticated** — that is the gap class this census exists to prevent.
2. **Kiosk confinement** (middleware, runs BEFORE the `/api/` passthrough): `map_kiosk` sessions
   are allowlisted to `/map`, `/logout`, `/change-password`; kiosk hits on `/api/*` and
   `/events/*` get JSON 403, everything else 302s to the map.
3. **Route dependencies** (`app/auth.py`): `get_current_user` (login required) and the
   `require_*` family (tier/grant). This is the preferred gate for everything.
4. **In-body checks**: the inventory-mutation form posts (intake, item edit, triage, checkout,
   bulk) check `user.is_editor_or_above` inside the handler and answer with a friendly
   redirect + toast instead of a 403 page. Equivalent enforcement, different UX. Marked
   "editor+ (in-body check)" below.

## Gate classes (use these when adding a route)

| Gate | Meaning |
|---|---|
| `get_current_user` | any logged-in active user (including viewers) |
| `require_viewer` | any role except `map_kiosk` |
| `require_editor` | editor, sub-admins, admin tier |
| `require_admin` | admin tier (justin_admin, system_admin, ceo, admin) |
| `require_*` domain deps | admin tier OR the matching permission grant (see `app/auth.py`) |
| in-body `is_editor_or_above` | editor enforcement with redirect+toast UX (form posts only) |
| self-auth | handler checks the session itself (SSE stream only) |
| public | login page/POST, logout, static assets, pure redirects |

## New-endpoint checklist

- [ ] Route has a `require_*` / `get_current_user` dependency (or a documented reason it doesn't)
- [ ] `/api/` routes: remember middleware does NOT protect these — the dependency is the only gate
- [ ] Write paths need editor+ (dependency or in-body); reads may be viewer
- [ ] Kiosk: if the route must be kiosk-reachable, extend the middleware allowlist deliberately
- [ ] Nav link gating in `base.html` matches the route gate (lockstep rule)
- [ ] Add the row to this census

## 2026-07-09 findings (fixed in `1686503`)

- `/api/maintenance/status` was fully unauthenticated → now `get_current_user`
- `/api/locks/{acquire,escalate,release,heartbeat}` allowed viewers to hold edit locks → now `require_editor`
- `/docs`, `/redoc`, `/openapi.json` exposed the API schema to all users → disabled in production

## Census table


### StaticFiles

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/static` | MOUNT | — | public static assets by design |

### main

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/` | GET | — | redirect to /dashboard; target enforces |

### admin

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/admin/audit` | GET | audit viewer | OK |
| `/admin/departments` | GET | user manager | OK |
| `/admin/departments/add` | POST | user manager | OK |
| `/admin/oui` | GET | editor+ (incl. sub-admins) | OK |
| `/admin/oui/add` | POST | system admin | OK |
| `/admin/oui/{entry_id}` | DELETE | system admin | OK |
| `/admin/oui/{entry_id}/edit` | POST | system admin | OK |
| `/admin/oui/{entry_id}/toggle` | POST | system admin | OK |
| `/admin/part-numbers` | GET | editor+ (incl. sub-admins) | OK |
| `/admin/part-numbers/add` | POST | system admin | OK |
| `/admin/part-numbers/{pn_id}` | DELETE | system admin | OK |
| `/admin/part-numbers/{pn_id}/edit` | POST | system admin | OK |
| `/admin/spreadsheet-sync` | GET | system admin | OK |
| `/admin/spreadsheet-sync/apply` | POST | system admin | OK |
| `/admin/spreadsheet-sync/upload` | POST | system admin | OK |
| `/admin/storage` | GET | system admin | OK |
| `/admin/users` | GET | user manager | OK |
| `/admin/users/add` | POST | user manager | OK |
| `/admin/users/{user_id}/toggle` | POST | user manager | OK |
| `/api/admin/change-role/{user_id}` | POST | user manager | OK |
| `/api/admin/delete-user/{user_id}` | DELETE | user manager | OK |
| `/api/admin/departments/{department_id}` | PUT | user manager | OK |
| `/api/admin/departments/{department_id}` | DELETE | user manager | OK |
| `/api/admin/departments/{department_id}/lock` | POST | user manager | OK |
| `/api/admin/departments/{department_id}/permissions` | POST | user manager | OK |
| `/api/admin/departments/{department_id}/unlock` | POST | user manager | OK |
| `/api/admin/reset-password/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-audit/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-credentials/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-disposal/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-financial/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-map/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-procurement/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-provisioning-manage/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-provisioning-view/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-receiving/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-sensitive-customers/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-sites/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-system/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-trials/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-users/{user_id}` | POST | user manager | OK |
| `/api/admin/toggle-warranty/{user_id}` | POST | user manager | OK |
| `/api/admin/users/{user_id}` | PATCH | user manager | OK |
| `/api/admin/users/{user_id}/department` | POST | user manager | OK |
| `/api/admin/users/{user_id}/lock` | POST | user manager | OK |
| `/api/admin/users/{user_id}/permissions` | POST | user manager | OK |
| `/api/admin/users/{user_id}/unlock` | POST | user manager | OK |
| `/api/users/{user_id}` | PATCH | any authenticated | self-scoped: 403 unless user_id == session user |

### api

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/audit-log` | GET | any authenticated | OK |
| `/api/devices/{table_name}` | GET | viewer+ (kiosk excluded) | OK |
| `/api/stats` | GET | viewer+ (kiosk excluded) | OK |
| `/api/vendors` | GET | viewer+ (kiosk excluded) | OK |

### auth_routes

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/change-password` | GET | any authenticated | OK |
| `/change-password` | POST | any authenticated | OK |
| `/login` | GET | — | public by design (rate-limited POST partner) |
| `/login` | POST | — | public by design: the login form itself; per-IP rate limiting in handler |
| `/logout` | POST | +CSRF token | OK |
| `/logout` | GET | — | public by design (clears session only) |

### bulk

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/bulk/assign` | POST | sites manager | OK |
| `/api/bulk/export` | POST | any authenticated | read-only export, all authenticated by design |
| `/api/bulk/status` | POST | editor+ (incl. sub-admins) | OK |

### c2c

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/fulfillment/c2c` | GET | provisioning viewer | OK |
| `/fulfillment/c2c/acquire` | POST | provisioning manager | OK |
| `/fulfillment/c2c/files/{file_id}` | GET | provisioning viewer | OK |
| `/fulfillment/c2c/files/{file_id}` | DELETE | provisioning manager | OK |
| `/fulfillment/c2c/history/{item_id}` | GET | provisioning viewer | OK |
| `/fulfillment/c2c/order/{order_id}/return-all` | POST | provisioning manager | OK |
| `/fulfillment/c2c/{provisioning_id}/cancel-cert` | POST | provisioning manager | OK |
| `/fulfillment/c2c/{provisioning_id}/cert-files` | GET | provisioning viewer | OK |
| `/fulfillment/c2c/{provisioning_id}/certify` | POST | provisioning manager | OK |
| `/fulfillment/c2c/{provisioning_id}/files` | POST | provisioning manager | OK |
| `/fulfillment/c2c/{provisioning_id}/recertify` | POST | provisioning manager | OK |
| `/fulfillment/c2c/{provisioning_id}/return` | POST | provisioning manager | OK |
| `/fulfillment/pilots-due-back` | GET | provisioning viewer | OK |

### checkout

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/checkin` | GET | any authenticated | OK |
| `/checkin` | POST | any authenticated / editor+ (in-body check) | OK |
| `/checkin/bulk` | POST | any authenticated / editor+ (in-body check) | OK |
| `/checkout` | GET | any authenticated | OK |
| `/checkout` | POST | any authenticated / editor+ (in-body check) | OK |
| `/checkout/bulk` | POST | any authenticated / editor+ (in-body check) | OK |

### contact_admin

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/contact-admin` | POST | any authenticated | OK |

### creds

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/credentials/{table_name}/{device_id}` | GET | credentials access | OK |

### dashboard

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/dashboard` | GET | any authenticated | OK |

### disposal

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/disposition` | POST | editor+ (incl. sub-admins) | OK |
| `/api/disposition/export` | GET | any authenticated | OK |
| `/api/disposition/{disposition_id}` | PUT | editor+ (incl. sub-admins) | OK |
| `/api/disposition/{disposition_id}` | DELETE | admin tier | OK |
| `/api/disposition/{disposition_id}/certificate` | POST | editor+ (incl. sub-admins) | OK |
| `/api/disposition/{disposition_id}/certificate` | GET | any authenticated | OK |
| `/api/disposition/{disposition_id}/data` | GET | any authenticated | OK |
| `/disposal/` | GET | disposal access | OK |

### error_routes

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/admin/errors` | GET | system admin | OK |
| `/api/errors` | GET | system admin | OK |
| `/api/errors/prune` | DELETE | system admin | OK |
| `/api/errors/report` | POST | any authenticated | OK |
| `/api/errors/{error_id}` | GET | system admin | OK |

### fulfillment

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/fulfillment/export` | GET | provisioning viewer | OK |
| `/api/provisioning/{prov_id}/technician` | PUT | provisioning manager | OK |
| `/fulfillment/` | GET | provisioning viewer | OK |
| `/fulfillment/certifications` | GET | provisioning viewer | OK |
| `/fulfillment/certifications/files/{file_id}` | GET | provisioning viewer | OK |
| `/fulfillment/certifications/history/{serial}` | GET | provisioning viewer | OK |
| `/fulfillment/certifications/{cert_id}/report` | GET | provisioning viewer | OK |
| `/fulfillment/certifications/{prov_id}` | GET | provisioning viewer | OK |
| `/fulfillment/certifications/{prov_id}/cancel` | POST | provisioning manager | OK |
| `/fulfillment/certifications/{prov_id}/close` | POST | provisioning manager | OK |
| `/fulfillment/certifications/{prov_id}/files` | POST | provisioning manager | OK |
| `/fulfillment/certifications/{prov_id}/hw` | POST | provisioning manager | OK |
| `/fulfillment/certifications/{prov_id}/qa` | POST | provisioning manager | OK |
| `/fulfillment/certifications/{prov_id}/recertify` | POST | provisioning manager | OK |
| `/fulfillment/deployments` | POST | provisioning manager | OK |
| `/fulfillment/deployments/{dep_id}/install/certify` | POST | provisioning manager | OK |
| `/fulfillment/deployments/{dep_id}/status` | POST | provisioning manager | OK |
| `/fulfillment/install-cert/{cert_id}/pdf` | GET | provisioning viewer | OK |
| `/fulfillment/{order_id}/ship` | POST | provisioning manager | OK |

### intake

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/intake` | GET | any authenticated / editor+ (in-body check) | OK |
| `/intake` | POST | any authenticated / editor+ (in-body check) | OK |

### intune_routes

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/admin/intune` | GET | system admin | OK |
| `/api/intune/sync` | POST | system admin | OK |
| `/api/intune/sync-log` | GET | system admin | OK |
| `/api/intune/test` | POST | system admin | OK |

### inventory

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/inventory/` | GET | any authenticated | OK |
| `/inventory/bulk` | POST | any authenticated / editor+ (in-body check) | OK |
| `/inventory/export` | GET | any authenticated | OK |
| `/inventory/quick-view/{item_id}` | GET | any authenticated | OK |
| `/inventory/quick-view/{item_id}` | POST | any authenticated / editor+ (in-body check) | OK |

### item_detail

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/receipts/{receipt_id}/download` | GET | any authenticated | OK |
| `/items/{item_id}` | GET | any authenticated | OK |
| `/items/{item_id}` | POST | any authenticated / editor+ (in-body check) | OK |
| `/items/{item_id}/edit` | GET | — | 303 redirect; target page enforces edit gating |
| `/items/{item_id}/receipt` | POST | any authenticated / editor+ (in-body check) | OK |

### lifecycle

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/device/{table_name}/{device_id}/lifecycle` | GET | any authenticated | OK |
| `/device/{table_name}/{device_id}/lifecycle` | GET | any authenticated | OK |

### locks

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/locks` | GET | admin tier | OK |
| `/api/locks/acquire` | POST | editor+ (incl. sub-admins) | OK |
| `/api/locks/escalate` | POST | editor+ (incl. sub-admins) | OK |
| `/api/locks/heartbeat` | POST | editor+ (incl. sub-admins) | OK |
| `/api/locks/release` | POST | editor+ (incl. sub-admins) | OK |
| `/api/locks/{resource_key:path}` | GET | any authenticated | OK |

### maintenance_routes

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/admin/maintenance` | GET | system admin | OK |
| `/api/maintenance/active-users` | GET | system admin | OK |
| `/api/maintenance/announce` | POST | system admin | OK |
| `/api/maintenance/clear` | POST | system admin | OK |
| `/api/maintenance/force-reload` | POST | system admin | OK |
| `/api/maintenance/status` | GET | any authenticated | OK |

### map

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/map/` | GET | map access | OK |
| `/map/data` | GET | map access | OK |
| `/map/set-location` | POST | editor+ (incl. sub-admins) | OK |
| `/map/visibility` | POST | editor+ (incl. sub-admins) | OK |

### nas_drives

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/nas-drives/` | POST | editor+ (incl. sub-admins) | OK |
| `/api/nas-drives/{drive_id}` | PUT | editor+ (incl. sub-admins) | OK |
| `/api/nas-drives/{drive_id}` | DELETE | admin tier | OK |
| `/api/nas-drives/{nas_device_id}` | GET | any authenticated | OK |

### notification_routes

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/notifications` | GET | any authenticated | OK |
| `/api/notifications/dismiss-all` | POST | any authenticated | OK |
| `/api/notifications/read-all` | POST | any authenticated | OK |
| `/api/notifications/subscriptions` | GET | any authenticated | OK |
| `/api/notifications/subscriptions` | POST | any authenticated | OK |
| `/api/notifications/subscriptions/{sub_id}` | PATCH | any authenticated | OK |
| `/api/notifications/subscriptions/{sub_id}` | DELETE | any authenticated | OK |
| `/api/notifications/watch/{resource_type}/{resource_id}` | GET | any authenticated | OK |
| `/api/notifications/watch/{resource_type}/{resource_id}` | POST | any authenticated | OK |
| `/api/notifications/{notif_id}/dismiss` | POST | any authenticated | OK |
| `/api/notifications/{notif_id}/read` | POST | any authenticated | OK |

### orders

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/orders/` | POST | provisioning manager | OK |
| `/api/orders/open` | GET | provisioning manager | OK |
| `/api/orders/{order_id}` | PUT | provisioning manager | OK |
| `/api/orders/{order_id}` | DELETE | provisioning manager | OK |
| `/api/orders/{order_id}/availability` | GET | provisioning viewer | OK |
| `/api/orders/{order_id}/oem-pos` | POST | provisioning manager | OK |
| `/api/orders/{order_id}/oem-pos/{po_id}` | PUT | provisioning manager | OK |
| `/api/orders/{order_id}/oem-pos/{po_id}` | DELETE | provisioning manager | OK |
| `/api/provisioning/{prov_id}/link-order` | POST | provisioning manager | OK |
| `/orders/` | GET | — | 301 redirect; target enforces |
| `/orders/{order_id}` | GET | provisioning viewer | OK |

### pending

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/pending/{device_id}/approve` | POST | editor+ (incl. sub-admins) | OK |
| `/api/pending/{device_id}/dismiss` | POST | editor+ (incl. sub-admins) | OK |

### procurement

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/admin/procurement` | GET | financial access | OK |
| `/admin/procurement/export` | GET | financial access | OK |
| `/admin/vendors/{vendor_name}` | GET | financial access | OK |

### provisioning

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/provisioning` | POST | provisioning manager | OK |
| `/api/provisioning/bulk-assign-order` | POST | provisioning manager | OK |
| `/api/provisioning/by-bucket` | GET | provisioning viewer | OK |
| `/api/provisioning/devices/{table_name}` | GET | provisioning manager | OK |
| `/api/provisioning/export` | GET | provisioning viewer | OK |
| `/api/provisioning/zendesk-orgs` | GET | provisioning viewer | OK |
| `/api/provisioning/zendesk-ticket/{ticket_id}` | GET | provisioning viewer | OK |
| `/api/provisioning/{prov_id}` | PUT | provisioning manager | OK |
| `/api/provisioning/{prov_id}` | DELETE | provisioning manager | OK |
| `/api/provisioning/{prov_id}/advance` | POST | provisioning manager | OK |
| `/api/provisioning/{prov_id}/revert` | POST | provisioning manager | OK |
| `/api/provisioning/{prov_id}/validation-report` | POST | provisioning manager | OK |
| `/api/provisioning/{prov_id}/validation-report` | GET | any authenticated | OK |
| `/api/provisioning/{prov_id}/validation-report` | DELETE | provisioning manager | OK |
| `/provisioning/` | GET | — | 301 redirect; target enforces |
| `/provisioning/queue` | GET | provisioning viewer | OK |
| `/provisioning/{prov_id}` | GET | provisioning viewer | OK |

### receipts

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/receipts` | GET | financial access | OK |
| `/receipts/{receipt_id}` | GET | financial access | OK |
| `/receipts/{receipt_id}/file` | GET | financial access | OK |
| `/receipts/{receipt_id}/replace-file` | POST | financial access / +CSRF token | OK |

### receiving

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/receive/check-duplicate` | GET | any authenticated | OK |
| `/api/receive/device` | POST | editor+ (incl. sub-admins) | OK |
| `/api/receive/events` | POST | editor+ (incl. sub-admins) | OK |
| `/api/receive/photo` | POST | editor+ (incl. sub-admins) | OK |
| `/api/receive/photo/{photo_id}` | GET | any authenticated | OK |
| `/api/receive/scan` | POST | editor+ (incl. sub-admins) | OK |
| `/receive` | GET | receiving access | OK |

### search

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/search` | GET | any authenticated | OK |
| `/search/results` | GET | any authenticated | OK |

### sites

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/assignments` | POST | sites manager | OK |
| `/api/assignments/{assignment_id}` | DELETE | sites manager | OK |
| `/api/assignments/{assignment_id}/return` | POST | sites manager | OK |
| `/api/sites` | POST | sites manager | OK |
| `/api/sites/list` | GET | any authenticated | OK |
| `/api/sites/{site_id}` | PUT | sites manager | OK |
| `/api/sites/{site_id}` | DELETE | sites manager | OK |
| `/api/sites/{site_id}/geocode` | POST | sites manager | OK |
| `/sites/` | GET | any authenticated | OK |
| `/sites/{site_id}` | GET | any authenticated | OK |

### slack_bot_routes

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/admin/notifications` | GET | system admin | OK |
| `/admin/slack-bot` | GET | — | 301 redirect; target enforces |
| `/api/notifications/test-email` | POST | system admin | OK |
| `/api/slack-bot/test` | POST | system admin | OK |
| `/api/slack-bot/test-dm` | POST | system admin | OK |

### sse

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/events/stream` | GET | — | self-auth in handler: 401 unauthenticated, 403 kiosk |

### support

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/review` | GET | editor+ (incl. sub-admins) | OK |
| `/support` | GET | — | 301 redirect; target enforces |

### tours

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/tours` | GET | any authenticated | OK |
| `/api/tours/all` | GET | any authenticated | OK |
| `/api/tours/progress` | POST | any authenticated | OK |
| `/api/tours/progress/{tour_id}` | DELETE | any authenticated | OK |
| `/api/tours/{tour_id}` | GET | any authenticated | OK |

### triage

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/triage/` | GET | any authenticated | OK |
| `/triage/bulk` | POST | any authenticated / editor+ (in-body check) | OK |
| `/triage/export` | GET | any authenticated | OK |
| `/triage/fix/{item_id}/{field_name}` | GET | any authenticated | OK |
| `/triage/fix/{item_id}/{field_name}` | POST | any authenticated / editor+ (in-body check) | OK |

### trials

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/trial` | POST | editor+ (incl. sub-admins) | OK |
| `/api/trial/export` | GET | any authenticated | OK |
| `/api/trial/{trial_id}` | GET | any authenticated | OK |
| `/api/trial/{trial_id}` | PUT | editor+ (incl. sub-admins) | OK |
| `/api/trial/{trial_id}` | DELETE | trials manager | OK |
| `/api/trial/{trial_id}/decision` | PUT | editor+ (incl. sub-admins) | OK |
| `/api/trial/{trial_id}/return` | PUT | editor+ (incl. sub-admins) | OK |
| `/trials/` | GET | any authenticated | OK |

### vendors

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/vendors/` | POST | financial access | OK |
| `/api/vendors/auto-create` | POST | admin tier | OK |
| `/api/vendors/{vendor_id}` | PUT | financial access | OK |
| `/api/vendors/{vendor_id}` | DELETE | admin tier | OK |
| `/vendors/` | GET | viewer+ (kiosk excluded) | OK |
| `/vendors/{vendor_id}` | GET | viewer+ (kiosk excluded) | OK |

### warranty

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/api/claim` | POST | editor+ (incl. sub-admins) | OK |
| `/api/claim/{claim_id}` | PUT | editor+ (incl. sub-admins) | OK |
| `/api/warranty` | POST | editor+ (incl. sub-admins) | OK |
| `/api/warranty/export` | GET | any authenticated | OK |
| `/api/warranty/{warranty_id}` | PUT | editor+ (incl. sub-admins) | OK |
| `/api/warranty/{warranty_id}` | GET | any authenticated | OK |
| `/api/warranty/{warranty_id}` | DELETE | warranty manager | OK |
| `/warranty/` | GET | any authenticated | OK |

### zendesk_routes

| Route | Methods | Required gate | Verdict / notes |
|---|---|---|---|
| `/admin/zendesk` | GET | system admin | OK |
| `/api/zendesk/organizations` | GET | system admin | OK |
| `/api/zendesk/test` | POST | system admin | OK |
| `/api/zendesk/ticket-fields` | GET | system admin | OK |
| `/api/zendesk/tickets` | GET | system admin | OK |