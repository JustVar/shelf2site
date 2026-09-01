# Audit log scoping, discovery

Reduced on 2026-09-01 from 428 lines to what survives.

The three UI findings this document described were fixed in `b59f8b4` on
2026-07-30, one day BEFORE this document landed in `6c4c1b7` on 2026-07-31. It
was written against a pre-`b59f8b4` codebase and was never correct in the
repo. `d4a93a6` closed the scoping findings earlier. The full original is
recoverable with: `git show 6c4c1b7:docs/audit-log-scope.md`

## Amendment log

- `d4a93a6` closed the scoping findings. Audit access became admin tier plus an
  explicit user-level grant, and the whole area-scoping block was deleted.
- `b59f8b4` closed the UI findings, one day before this document existed in the
  repo. Event type options and the user list are derived from the log itself,
  and the count notice reports a real total.
- This commit, 2026-09-01: cut to the surviving principle and the two open
  findings. The removed sections included one that described `b59f8b4` as
  future work, which is what a reader would have built.

## Settled principle, what belongs in the audit log

**Application specific items belong in the audit log. Business history belongs
on the domain surfaces that own it.**

Two clauses, not three. A third clause, that compliance and certification
events belong in the audit log even where their target is a business object,
was added and then DROPPED, because it was decided on a false premise: this
document asserted that build certification produced no audit trail, inferring
it from the absence of `log_event` calls in `fulfillment.py`. Both
certification subsystems in fact carry ratified trails of their own.
`docs/specs/build-certification.md` describes an append-only audit trail keyed
to the OEM serial, and `docs/specs/installation-certification.md` ratifies one
certification per deployment record. Adding `log_event` calls beside those
would be a second mechanism for a solved problem. The build certification
audit parity track is therefore DEAD; the zero `log_event` calls in
`fulfillment.py` are the design working, not a gap.

The counter argument, recorded because it is real but was judged thin:
`audit_log` carries `user_id`, an IP address and a server timestamp, while the
certification tables carry `certified_by` as free text that is not reliably
joinable to a user. Genuinely different records; not worth two trails for one
subsystem.

Consequence, also settled: the business record rows already in the log
(orders, checkouts, C2C certifications, receipts, purchase orders, part
numbers, sites, provisioning, map visibility) STAY where they are. Migrating
them means changing `log_event` call sites so those events write to per-domain
history surfaces that do not exist yet. The definition stays aspirational
until a domain surface actually needs its own history, at which point that one
domain moves and the rest stay.

## Open finding: target_table is unvalidated free text

`log_event(..., target_table: Optional[str] = None, ...)`. No enum, no
registry, no validation. Several call sites pass variables, and `map.py:522`
passes `body.get("kind")`, client-supplied, validated only against the map's
two API discriminators (`"edge_box"`, `"item"`). That is the source of the
`edge_box` and `item`/`items` rows in the log, names that match no real
table. There is no single naming authority on the write side: `TABLE_MODELS`
covers only the 22 device tables.

Since `d4a93a6` deleted area scoping, nothing filters on `target_table` at
read time, so the harm is data quality in a permanent record rather than
exposure: junk categories accumulate and cannot be told apart from real ones
afterward.

## Open finding: the audit page has zero test coverage

No test references `has_audit_access`, `require_audit_viewer`,
`can_view_audit_log`, or `/admin/audit`. A permanently false boolean branch in
the audit gate survived until `0c0ac31` because of this. A green suite says
nothing about this surface. Also recorded in the CLAUDE.md known TODOs.
