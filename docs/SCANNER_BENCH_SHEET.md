# Scanner Phase 2 — Bench Run Sheet

Operator view derived from SCANNER_AUDIT.md section 8 (the exhaustive spec). This sheet foregrounds hands-only checks; the routing and guidance layer is validated programmatically and referenced here, not re-listed. This file is not source — to change the protocol, edit section 8 in SCANNER_AUDIT.md and regenerate this sheet. Never hand-edit this file.

## Before you start

- The app served over HTTPS, and on a private network the phone trusting its certificate (docs/HTTPS.md, step 4). Hard prerequisite: the phone camera will not open without HTTPS.
- Leave scan-routing-pilot logging ON until every check below is done. It captures routing misses with their raw payloads.

## Covered by machine (do NOT hand-scan these)

The whole routing and guidance layer (every expected status, class, and guidance string in section 8) is post-decode, server-side, and pinned by tests/test_scan_routing.py (part of the 861 pass / 39 skip suite). Chrome MCP can drive /api/receive/scan with each string and assert the JSON response. That includes all four correct-looks-wrong cases (bare MAC becomes hex12, all-digit becomes ambiguous_digits, 12 to 15 digit carrier becomes ambiguous_digits, OUI hint becomes class mac) and the H17 event auto-select. Validate these programmatically. They need no physical scan.

## Hands-only checks (the actual bench work; about 15 min for the CORE rows)

These cannot be reached by the contract tests or Chrome MCP, because the tests inject strings directly and bypass the camera and wedge decode step and the UI gates.

| Tier | Check | Do | Pass |
|---|---|---|---|
| CORE | Phone camera decode | Scan a known serial label with the phone | camera opens (proves CA and HTTPS), decodes to the exact string, routes to already_exists |
| CORE | USB wedge timing | Wedge-scan a 20-char serial then Enter on the receive bench | field clears and refocuses, no SER1SER2 concatenation |
| CORE | F6 QNAP confirm tap | Quick Mode: scan a Q plus 9-alnum serial (response is recognized) | requires a confirm TAP, must NOT auto-insert a phantom NAS |
| CORE | GS1-128 real carton | Camera-scan a real vendor carton (]C1 + AI(01) + AI(21)) | unwraps to the AI-21 serial, finds the item |
| | F6 guard (adversarial) | Scan a Q-prefixed QR URL (QHTTP://...) | class serial, manual-entry guidance, never QNAP |
| | Damaged or partial label | Scan a deliberately damaged label | no decode, camera never fires; wedge or manual fallback usable |
| | F10 non-editor auth | Log in as a non-editor with receiving access (NOT the Admin Chrome MCP session) and scan | page renders AND the scan action works, no 403 |

## On any surprise

Capture the raw scanned string verbatim and note the surface (camera, wedge, or phone). Routing misses are logged server-side with raw payloads while pilot logging is on. That log plus your note is the record.

## Full reference

SCANNER_AUDIT.md section 8: every routing row, verbatim guidance, and the correct-looks-wrong reasoning. This sheet is the run-order subset; section 8 is the source.
