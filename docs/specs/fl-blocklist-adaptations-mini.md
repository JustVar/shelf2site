# Mini-slice: blocklist adaptations (approved 2026-07-09)

Two approved changes to the shipped password screening; HIBP k-anonymity explicitly declined for now.

1. Length-filtered loading: keep the full 939k blocklist file on disk (checksummed as today); at startup load only entries with length >= PASSWORD_MIN_LENGTH into the in-memory set. Self-adapts when the config changes — no regeneration step. Log the loaded count at startup ("blocklist: 5,532 of 939,466 entries active at min length 15").

2. Composition rules for the long-password regime, applied where passwords are set (same seam as the 72-byte cap):
   - Reject all-repeat and near-repeat strings (single char or short block repeated to length).
   - Reject pure ascending/descending sequences (digits or alphabet) and long keyboard walks (qwerty rows, extended beyond what the list carries).
   - Reject passwords CONTAINING context-specific words (case-insensitive): the username, "shelf2site", "assettracker", "password", the app hostname. Word list as a small config constant so it can grow.
   - Friendly specific messages ("contains your username", "is a repeated pattern") — not a generic rejection.
   - Tests: each rule positive + negative; ensure a strong passphrase with an incidental substring like "sot" does NOT trip the contains rule (match whole configured words only, minimum 5 chars per word).

Placement: rides into any convenient Code session; no dependencies. Standard gates + sync. The bcrypt truncation pin-test stays as is.
