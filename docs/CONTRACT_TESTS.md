# Contract tests

A small, fast pytest suite that pins the invariants the 2026-07 hardening sweep
established. There is no CI — **run it by hand after any change to auth, routes,
MAC handling, password rules, map visibility, or deal-type derivation.**

## Run it

```bash
ssh admin@192.0.2.10 "cd /opt/asset_tracker && docker compose exec -T app python -m pytest tests/ -q"
```

Verbose, or a single file:

```bash
ssh admin@192.0.2.10 "cd /opt/asset_tracker && docker compose exec -T app python -m pytest tests/test_auth_census.py -v"
```

The suite runs **inside the app container** because it imports `app.*` and talks
to the running worker over `http://127.0.0.1:8081`.

## What it covers

| File | Covers |
|---|---|
| `tests/test_auth_census.py` | every `/api/*` route has an auth dependency; every write route requires a tier; viewers are rejected from editor/admin routes; kiosk stays confined to the map; API docs are disabled |
| `tests/test_helpers.py` | `normalize_mac` (all input formats, empty→NULL, invalid→ValueError); password strength (length, 72-byte cap, breach blocklist); `unit_visible` cascade (unit/site/customer + sensitive); `_classify` deal-type derivation (order / inferred / unassigned) |
| `tests/test_receive.py` | receive happy path, dash-MAC normalization, invalid MAC → 400, null MAC and null serial do not crash, editor tier required |

## The structural tests are the point

`test_every_api_route_has_an_auth_dependency` is the guard that would have caught
the three unauthenticated `/api` endpoints found by accident during the map
review. The auth-redirect middleware deliberately lets `/api/*` through so routes
can answer JSON 401 — which means **a route dependency is the only gate on an API
endpoint**. Add an `/api` route without one and it is readable by anyone on the LAN.

`test_write_routes_require_more_than_login` catches the sibling class: a POST
gated by `get_current_user` alone, so any viewer can write.

Both tests carry explicit allowlists (`PUBLIC_ROUTES`, `IN_BODY_EDITOR_ROUTES`,
`SELF_SCOPED_WRITE_ROUTES`). Adding a route to one is a deliberate, reviewable act
— that is the design. `test_allowlists_have_no_stale_entries` stops a deleted
route from lingering in an allowlist and masking a future gap.

Keep the allowlists in sync with [ENDPOINT_AUTH_CENSUS.md](ENDPOINT_AUTH_CENSUS.md).

## What it writes

There is no separate test database. The suite:

- creates four throwaway users prefixed `contract-test-` and deletes them (and
  their `audit_log` / `error_log` rows) at session end;
- creates `pending_devices` rows via the receive endpoint and deletes them.

Anything left behind by a crashed run is safe to delete:

```sql
DELETE FROM pending_devices WHERE scanner_id LIKE 'intake:contract-test%';
DELETE FROM users WHERE username LIKE 'contract-test-%';
```

## Notes

- The blocklist test skips itself when `data/security/password-blocklist.txt` is
  absent (the check is fail-open there), so the suite stays green on a machine
  without the list.
- `test_oversized_passwords_still_verify_so_legacy_accounts_are_not_locked_out`
  pins bcrypt's silent-truncation behavior. If a future bcrypt restores the
  `ValueError` past 72 bytes, that test fails and tells you to add a guard at the
  verify boundary.
