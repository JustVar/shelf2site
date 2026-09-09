# Triage single role: collapse to hardware, fold in the deploy checks

Status: DECIDED 2026-09-09 (Jus). Not started. Baseline HEAD 9c235f1.

## Why

Triage carries three role tabs (hardware, accounting, deployment), each with
its own required-field list. Deployment is now handled by a third party
except for a few pilots, and accounting uses this tool only for receipt
upload. Only the hardware set matters. Decided 2026-09-09:

- Delete the accounting and deployment roles.
- Fold the two deploy data-integrity checks (place mismatch, containment
  divergence) into the hardware role. They are not field requirements and
  have no other home; they are exactly what a real import needs afterward.
- Delete the two dead field lists in models.py.
- Remove the tab strip and per-gap role chips. One role needs neither.
- Exclude decommissioned items from the queue (backlog F2).

NOT in scope: trimming the hardware field list itself. On the current mock
data the hardware set alone flags 546 of 548 items, driven almost entirely
by vendor_id (546), brand_pn (530), location_id (529) and brand_sku
(500). That is a data question, deferred until the real import lands.

## Ground facts (READ 2026-09-09 at 9c235f1)

- `TRIAGE_ROLES` in `app/routes/triage.py` is the live source. `models.py`
  `Item.REQUIRED_FIELDS_HARDWARE / _ACCOUNTING / _DEPLOYMENT` duplicate it
  verbatim (11 / 13 / 15 fields). ACCOUNTING and DEPLOYMENT have zero
  consumers anywhere. HARDWARE is aliased to `Item.REQUIRED_FIELDS`, which
  the generic dispatcher (`getattr(model_class, 'REQUIRED_FIELDS', [])`)
  reads, so HARDWARE must survive. The comment above the alias calls
  hardware "broadest"; it is the narrowest.
- Deploy checks: `_place_mismatch_ids` and `_containment_divergence_ids`.
  Wired in `triage_page` at four sites, all keyed on the literal `"deploy"`:
  the `role_counts` comprehension, the `gap_cond` OR, and the two
  `all_gaps["deploy"] + [...]` appends. Labels live in `FIELD_LABELS` under
  `place_check` and `containment_check`; those stay.
- `get_triage_total_count` already ORs both check sets into the union
  regardless of role, so the sidebar badge needs no fold.
- Unknown `?role=` values already fall back to `"hw"` at the top of
  `triage_page`, so bookmarks to `?role=acct` degrade to hardware, no 404.
- No decommissioned filter exists anywhere in the counting path. The
  ratified predicate is `Item.item_status.is_distinct_from("Decommissioned")`
  (`inventory.py`, citing `docs/specs/item-decommission.md`). That spec
  mentions triage only for the bulk panel's status options; F2 extends its
  hidden-by-default principle, it does not implement a decision it made.
- Zero references to `acct` or `deploy` in `tests/`.
- Mock data: 548 items, hardware gap 546, three-role union 548, zero
  decommissioned. The data is placeholder pending an import; every count
  below measures code, not completeness.

## Changes

### app/routes/triage.py

1. `TRIAGE_ROLES`: delete the `"acct"` and `"deploy"` entries. Keep `"hw"`
   and point its `"fields"` at `Item.REQUIRED_FIELDS_HARDWARE` so the list
   exists once. `Item` is already imported.
2. Module docstring: rewrite for one role. Drop the rbac TODO and its
   Morgan example. Keep the perf TODO.
3. Rename `deploy_extra_ids` to `check_ids`. In the `role_counts`
   comprehension pass `check_ids` for `"hw"`. Replace
   `if role == "deploy" and check_ids:` with `if check_ids:`. Change both
   `all_gaps["deploy"] + [...]` appends to `all_gaps["hw"]`. Fix the
   comment `# Deploy role also surfaces ...`.
4. F2: add `.filter(Item.item_status.is_distinct_from("Decommissioned"))`
   to the two queue queries: `get_triage_total_count` and `base_query`
   in `triage_page`. Do not touch the per-item gap views; they describe
   one item, they are not the queue. Corrected 2026-09-09: this said
   three queries and named `_count_role_gaps` first. That function was
   deleted with the role_counts plumbing in the same commit as this note,
   having lost its last caller.
5. CSV export: drop the `acct_gaps` and `deploy_gaps` columns. The export
   docstring says it exists for people outside the app, e.g. accounting.
   **Tell Morgan before this ships** in case anything parses that file.
   The export stays fields-only: the two data checks are excluded from
   it by decision 2026-09-09.

### app/models.py

6. Delete `REQUIRED_FIELDS_ACCOUNTING` and `REQUIRED_FIELDS_DEPLOYMENT`.
7. Rewrite the two comments around HARDWARE: it is the triage required set
   and the single source `TRIAGE_ROLES` reads from. Remove "broadest".

### app/templates/triage.html

8. Subtitle: `Items missing role-required fields` becomes
   `Items missing required fields`.
9. Delete the `<!-- Tabs -->` block (`div.trg-tabs`) entirely.
10. Expansion view: delete the role-chip column, its `<th>`, and the
    `role_short` set. One role means every gap would carry the same chip.
11. The SSE updater that writes `data.role_counts[roleKey]` into tab badges
    now has no badges. Read it, then delete it or retarget it to the header
    count. Do not leave it targeting elements that no longer exist.

### app/routes/checkout.py, app/routes/inventory.py

12. Unchanged. Both iterate `TRIAGE_ROLES.keys()` and survive one key.
    Rider candidate, not verified: both compute `role_counts` and pass it to
    templates that a whole-app grep shows never read it. Confirm and delete
    in a separate commit.

### Riders on this commit

- CSS: `.trg-tab*` and `.trg-role-chip--acct / --deploy` are likely dead
  after 9 and 10. Census `static/css/` before deleting; account for every
  hit by name.

## Predictions and gates

- Suite: 906 passed, 39 skipped. No route added or removed, so the auth
  census does not move. Baseline immediately before editing.
- Badge: 545 on the current mock data, pinned by census SQL 2026-09-09.
  Decomposition: 548 at 2ce1720; minus 2 for the two dropped roles
  (hardware alone flags 546); minus 1 for item 1058, decommissioned
  2026-09-09 for the F2 gate. Assert on 545 after the build.
- F2 gate, and it must be able to fail: decommission one mock item from
  its item page. Badge drops by one and the item is absent from the queue.
  Reactivate it. Badge returns and the item reappears. Zero decommissioned
  items exist today, so without this step F2 is unproven.
- Browser (Chrome MCP, console primed and read after a tracked reload):
  no tab strip; no role chips; expansion view still lists gaps with labels,
  including "Place / status mismatch" where applicable; `?role=acct` and
  `?role=deploy` both render the hardware queue; bulk panel and Fix buttons
  unaffected; Inventory and Checkout pages still render.
- CSV export downloads with the two columns gone and nothing else changed.

## Discipline

Anchor on exact strings, never line numbers; re-read every anchor right
before editing. Two files plus a template: validate every anchor across
all three, then write. Guarded patch scripts with count asserts and a
post-check that asserts on deltas. Show the git diff before the commit.
Four-location sync.
