# Slice: hardening sweep — auth census, error-log triage, kickoff security items

Evidence base (2026-07-09): three unauthenticated /api endpoints were found by ACCIDENT in the map review; the admin error log holds 55 errors with ~8 distinct recurring backend defects, all on POST/action paths the GET-only census never exercised.

## A. Endpoint auth census (systematic, not incidental)

Enumerate EVERY route (pages, /api/*, SSE, static-adjacent) with its auth dependency. Output a table: route -> method(s) -> required tier/grant -> verdict. Fix every gap to the least tier that the feature needs. Include the kiosk allowlist interaction (kiosk sessions get JSON 403 on /api, 302 on pages — already the pattern). Deliverable: the census table committed to docs/ so the next endpoint added has a checklist to join.

## B. Error-log triage — fix the recurring defects

From the live log's top recurring list (fingerprints in the admin page):
1. `unhashable type: 'dict'` (8x) — locate and fix.
2. bcrypt `password cannot be longer than 72 bytes` (4x) — enforce a max length at the form/API with a friendly message; never surface the bcrypt internals. (Coordinate with item D.)
3. `type object 'Item' has no attribute 'cog'` (4x) — likely a stale attribute reference.
4. MAC handling family: empty-string macaddr insert AND dash-separated `AA-BB-CC-DD-...` rejected — normalize MAC input (accept colon/dash/bare, store canonical; empty -> NULL) in ONE helper used by receive, intake, item edit. Cousins of the fixed null-MAC bug.
5. `'ItemLocation' object has no attribute 'name'` (3x) — check survivors of the place unification.
6. `'deployed' is undefined` (3x) and `'Item' object has no attribute 'data_completeness'` (3x, /search/results) — template-context bugs.
7. `NoneType has no attribute 'strip'` on /api/receive/device.
8. delete-user FK violation (task 24 folds in here): decide deactivate-as-default (recommended — audit rows are legal history; hard delete only for users with no audit trail) and implement the 409 path with a clear message.
Each fix gets a regression exercise; frontend "Unknown error" (4x) gets better capture (real message/stack) rather than a blind fix.
After triage: prune the log (the page has Prune 30d+) so it starts clean as a signal.

## C. POST/action-path census

The tail census proved every page GETs. Extend it: enumerate every form action and API write path, exercise each with a happy-path and one malformed input on test data (the app's own rejection lifecycles where they exist). Anything 500ing joins B. Deliverable: the exercised list in the commit message; genuinely destructive paths (deletes) exercised on throwaway rows only.

## D. Kickoff security items (both, same session)

1. Password blocklist: place the top-N breached-password list at the security path on apphost (Jus supplies or approves the file source — coordinate in Chat at execution time), verify the NIST breach-rejection flips from fail-open to enforcing: a blocklisted password is rejected on change-password with the proper message, a normal one passes. Pair with the 72-byte max from B2.
2. `justin_editor`: retire the standing test account — deactivate (not delete, it has audit rows), rotate its password to a throwaway first, verify login fails after. If Jus still needs a test editor, create a fresh one with a current password and a note in docs/.

## E. Contract tests (the sweep's lasting artifact)

Minimal pytest suite, run manually (documented command) since no CI exists: auth census assertions (each route class rejects below-tier access — parametrize from the census table), visibility helper (unit/site/customer cascade + sensitive filter), deal-type derivation (order-linked, inferred, unassigned), MAC normalization helper, receive happy-path. Target: fast, no fixtures beyond a test DB schema; the point is that the NEXT sweep starts from `pytest` instead of archaeology.

## Gates

Standard gates per commit; the census table + tests committed; error log shows zero recurrences of the fixed fingerprints after a re-exercise pass; blocklist enforcement demonstrated; justin_editor login rejected.
