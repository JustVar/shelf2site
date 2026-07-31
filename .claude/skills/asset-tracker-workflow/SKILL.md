---
name: asset-tracker-workflow
description: >-
  Discovery-first patching, verification gates, and four-location sync for the
  Asset Tracker repo. Use when editing, patching, migrating, deploying,
  committing, pushing, or syncing anything in asset_tracker.
---

# Asset Tracker Workflow

The discipline for changing the Asset Tracker safely. The through-line:
**ground every claim in a read before acting on it, patch behind guards, and
prove a change reached all four git locations before calling it done.** A wrong
call costs more than a slow one.

## What this skill owns

**The procedure only.** Three files each own a domain, and none of them restates
another, because a second copy of any fact drifts from the first:

| Owner | Domain |
|---|---|
| `CLAUDE.md` (in the repo) | repo facts: architecture, git topology, deployment, schema, codebase semantics |
| **this skill** | procedure: discovery, guarded patches, gates, sync, commit style, execution gotchas |
| handoff doc (project knowledge) | role, two surfaces, communication style, preferences |

If a fact is about **how the codebase behaves**, it belongs in `CLAUDE.md`. If it
is about **how to make and verify a change**, it belongs here. When they
disagree, the owner wins. Do not paste repo facts into this skill to make it
more self-contained; that is how drift starts.

`docs/` owns subsystem design. Before writing a fact into `CLAUDE.md`, check
whether a file in `docs/` already owns it; if so, point rather than restate. A
CLAUDE.md bullet describing the test suite's files, count, invocation and
cleanup was written while `docs/CONTRACT_TESTS.md` already covered all of it,
in the commit whose purpose was fixing stale documentation.

## Two surfaces

- **Chat** (has Chrome MCP): decide, ground, verify in the browser. Chat cannot
  read apphost directly; it sees the repo only through pasted command output.
- **Code** (Claude Code in VS Code): build, edit, compile against the repo.

At each natural boundary (finished commit, end of slice, fresh decision point),
check whether the next action is a decision or a keystroke. A decision belongs
in Chat; a keystroke against settled design belongs in Code. Flag a switch at
boundaries only, not mid-task.

## 0. Raw output is not optional

**Paste raw command output. A description of bytes is not the bytes.**

When a `cat -A` readback, a `git diff`, or a command result is requested, the
actual output is the deliverable. "The readback confirms it is clean" is not a
readback. "The diff is exactly the scoped change" is not a diff. If a summary
arrives in place of output, ask again before acting on it.

This is load-bearing, not pedantry. In one session it caught three real defects
a summary would have hidden: a row regex that silently dropped a combined table
row and inflated a diff result by two entries; an assert that would have aborted
its own patch script on the first run; and a doc reference an otherwise complete
sweep would have missed.

Never report a gate as passed when its output was not shown. Never write "output
shown above" when nothing is above.

## 1. Read-only discovery before any edit

Never edit from memory or inference. Before changing anything:

- **List `docs/specs/` and read the owning document before specifying work in a
  subsystem.** A ratified decision you have not read looks exactly like an
  absent one. This is the most expensive rule to skip: a commit that added
  multiple certification attempts per deployment record was built, shipped,
  four-way synced, and then reversed, because the APPROVED spec ratifying one
  per record was never opened. A second track was specced on the premise that
  build certification had no audit trail, when its APPROVED spec opens by
  describing one.
- Read the actual code, model, template, or data the change depends on.
- **Distinguish read facts from inference.** State plainly which is which. If a
  claim has not been read, say so and read it before building on it. Presenting
  an inference as grounded is the single most common way these changes go wrong.
- **Read the surrounding context, not just the line.** A route was believed to
  overwrite on re-certification because the upsert at one line was read and the
  guard twenty-six lines above it, which made that path unreachable, was not.
- **Re-read the exact anchor lines immediately before editing.** Line numbers
  drift between discovery and patch time. The pre-edit re-read is what the patch
  anchors on.
- **Widen the search before declaring a sweep complete.** A sweep scoped to one
  directory will miss the repo root. Reconcile with a whole-repo count
  (`git grep -c <term> -- . | sort`) and account for every remaining hit by
  name, including the ones that should legitimately stay.
- **Reconcile counts before trusting them.** If two ways of counting the same
  thing disagree, stop and find the one item that explains the gap. Do not
  proceed on arithmetic that does not close.
- **Do not assert a range wider than the individual checks cover.** Enumerate
  what was verified, or verify the span. A note reading "F1b through F4 have
  shipped" claimed four facts from two verified endpoints; the gap table two
  sections above the note already said otherwise, and the document contradicted
  itself in the commit whose purpose was removing contradictions. When
  correcting a document, check the correction against the rest of that document,
  not only against reality.
- **A silent-empty failure must be distinguishable from a genuine empty
  result.** When a check can fail by producing nothing, either make the failure
  loud (`echo "rc $?"`, a line count, an explicit end marker) or use a form with
  no silent-empty mode. `git show HEAD:scripts/wsync | diff - ~/bin/wsync` run
  from the wrong directory wrote nothing to stdout, and `diff` compared an empty
  left side against an 80-line file: the output `0a1,80` reads as catastrophic
  drift and is actually zero data. Fixed with `git -C <path>` plus a line count
  on both sides. Likewise, do not guess line ranges: to find the class owning a
  line, list every class declaration before it and `tail -2`, rather than an
  `awk` range that returns nothing when the guess is too narrow.

## 2. Guarded patch scripts

Make edits with a Python patch script, not a freehand edit. Every script has:

- **Exact-count anchor assert.** Count the anchor string; abort unless it
  appears exactly N times (the N you read). A drifted count means the file
  changed under you. Stop, do not write.
- **Idempotency guard.** If the change is already applied, no-op and exit 0.
- **Backup to `/tmp`**, then the replacement, then a **post-check**. Keep backups
  out of the repo tree so a missed cleanup cannot be swept into a commit.
- Write the script to apphost `/tmp` via an **SSH heredoc**, NOT Write+scp
  (Write+scp litters the workstation `/c/tmp`).
- **Verify the written script by reading it back in full (`cat -A`) before
  running it.** The guards are the whole point; a script verified only by
  description is not verified.

**Multi-file patches run in two phases:** validate every anchor across every
file first, stage the results in memory, and only then write. A late assert must
not leave a half-applied change. This is not ceremony: a phase-1 abort caught an
anchor that matched twice because a sibling model carried an identical column
tail, and a single-phase patch would have written new columns into the wrong
class.

**Prefer structural avoidance over escaping.** If an anchor would contain an em
dash, anchor on an ASCII substring that stops before it. For inserted text,
assert `ord(ch) < 128` over the whole string rather than counting em dashes
afterward; that refuses to write anything mangled instead of detecting it later.

### Post-checks: count before writing, assert on the delta

Three post-check failures in one session, all on correct patches, all aborting
after the write so the remaining checks never ran and had to be redone by hand.
Three distinct causes, one fix.

- **Watch for asserts that catch your own insertion.** A post-check searching
  for a substring the patch itself introduces will fire on the new code. Scope
  the post-check so it cannot match what you just added.
- **The mirror case: an assert catching a legitimate pre-existing occurrence.**
  `assert "order_by(UserModel.username)" not in admin.py` fired on an unrelated
  line serving the users admin page. `assert now.count("has_audit_access") == 1`
  fired because an RBAC matrix and a dependency table both reference it.
- **Miscounting your own insertions.** A patch inserted `SUPERSEDED` twice and
  asserted `+3`.

**The fix for all three: count every string BEFORE writing, and assert on the
delta rather than on absence or on a hand-counted total.** Derive the expected
number from the edit list. A check that says "this string is gone" is wrong
whenever the string legitimately lives elsewhere in the file.

```python
pre = {k: src.count(k) for k in ("anchor", "sibling", "marker")}
# ... apply edits ...
assert now.count("marker") == pre["marker"] + len(INSERTIONS)
assert now.count("sibling") == pre["sibling"]   # must survive untouched
```

Template skeleton:

```python
#!/usr/bin/env python3
import shutil, sys
PATH = "/opt/asset_tracker/app/templates/example.html"
BAK  = "/tmp/example.html.bak"
OLD  = "exact anchor string"
NEW  = "replacement string"
EXPECT = 1

src = open(PATH, encoding="utf-8").read()

if OLD not in src and NEW in src:
    print("ALREADY APPLIED. No-op."); sys.exit(0)

got = src.count(OLD)
if got != EXPECT:
    print(f"ABORT: {OLD!r} found {got}x, expected {EXPECT}x. No write."); sys.exit(1)

shutil.copy2(PATH, BAK)
out = src.replace(OLD, NEW)

if OLD in out:
    print("ABORT: old anchor still present after replace. No write."); sys.exit(1)

open(PATH, "w", encoding="utf-8").write(out)
print(f"OK: {EXPECT} replaced. Backup at {BAK}")
```

Delete the backup before committing. Always show the `git diff` before the
commit, as actual diff output.

### Reversals: restore from the parent blob, do not invert edits

For a pure reversal where no other commit has touched the files, verify with
`git log <parent>..HEAD -- <paths>` that only the target commit touched them,
then `git show <parent>:<path> > <path>`. An empty `git diff` against the parent
is a byte-level proof, stronger than any anchor-based inverse patch.

Note `git revert` is the wrong tool when the commit added a migration: reverting
deletes the migration file from the tree without undoing what it already did to
the live schema. Go forward instead, with a new migration that undoes the old
one.

## 3. Verification gates

Scale the gates to what the change can actually break. Run in order, stop on any
failure, and state openly when a gate is skipped as inapplicable rather than
skipping it silently.

**Python or templates imported by the running app:**

1. **Baseline the test suite immediately before editing** (see below). A
   baseline only makes a later failure attributable if nothing moved in between.
2. **Jinja parse** for templates (proves syntax).
3. **`py_compile`** with `cfile="/tmp/..."` so a root-owned `__pycache__` cannot
   cause a false failure.
4. **Restart app** (`docker compose restart app`), then confirm the worker came
   up (`docker compose ps` showing `Up <seconds>`, not a restart loop).
5. **In-container import check**
   (`docker compose exec -T app python -c "import app.main"`). Catches what
   `py_compile` cannot: a broken module graph.
6. **Test suite**:
   `docker compose exec -T app python -m pytest tests/ -q`. Roughly six seconds.
7. **Chrome MCP browser gate**: render, interact, console clean after a tracked
   reload, no regression to adjacent boards.
8. **`git diff` review**, then commit, then four-location sync.

**The test suite, and its caveats.** It is cheaper than the container restart
already in this list and it is the right gate for any refactor whose claim is
"behaviour is preserved." Two things must ship with that:

- It writes to the LIVE database. Fixtures create and update rows in `users`,
  prefix them `contract-test`, and clean up after themselves. A crashed run
  leaves prefixed rows behind, which are obvious and safe to delete.
- **Coverage is not uniform.** A green suite says nothing about an untested
  surface. No test references the audit gate, which is why a permanently-false
  boolean branch there survived undetected. Check whether the suite covers what
  you changed before treating green as evidence.

**Migrations.** Run the migration BEFORE restarting when it adds columns the new
code reads; run the restart BEFORE migrating when it drops columns the running
code reads. Restarting first removes the window where a live worker queries
columns that no longer exist. Always report row counts before and after.

**Standalone scripts (not imported by the app):** `py_compile` plus a live run
comparing real output against known values. Compile proves nothing about output
correctness.

**Docs-only changes:** the `git diff` review IS the gate. Jinja parse,
`py_compile`, restart, and the browser gate have nothing to act on. Run the test
suite anyway as a cheap tripwire proving nothing outside `docs/` moved.

**"Compiles" is never "renders."** Syntax and import checks cannot catch stale
HTML, a template block missing from the DOM, a worker still serving old code, or
a bad font token in generated output. Only the live gate catches those.

**A gate that cannot be exercised is not a passed gate.** Adding a code path
nothing calls proves only that it compiles. If the feature is unreachable from
the UI, say so plainly rather than reporting the browser gate as passed.

## 4. Four-location sync

The four locations are **apphost / workstation / origin / company**. A commit
is not done until all four report the same HEAD, shown as actual command output
rather than asserted.

- On **apphost**: `~/bin/at-sync-commit.sh <paths>` with the commit message
  piped on stdin via heredoc. It stages, commits, bundles `PREV..main`, asserts
  the bundle tip, and emits `PREV` / `NEW` / `BUNDLE`.
- On the **workstation**: `~/bin/wsync PREV NEW`. It scp's the bundle, runs the
  preflight guards (tree clean, HEAD == PREV, bundle tip == NEW, bundle verify),
  does an ff-only merge, pushes origin, pushes company, verifies all four HEADs,
  and cleans up the bundles.

`~/bin/wsync` is the live copy and the one that runs. `scripts/wsync` is its
repo mirror. Reaching for the mirror is a recurring error.

Run the pre-stage cleanup and `git status` BEFORE committing, not after. The
point is to catch a stray path before it is swept in; running it against an
already-committed tree proves nothing.

Both pushes inside `wsync` are **separate commands, never `&&`-chained**, each
with its own exit check. Cleanup runs only after the four-HEAD verify passes, so
a mismatch aborts with the bundles left in place for diagnosis.

The remote names `origin` and `company` are **fixed identifiers that `wsync`
hardcodes**, in both push commands and in the two `ls-remote` calls that build
the four-HEAD line. Renaming either silently breaks the push and the
verification. See the deploy section of `CLAUDE.md` for the full topology and
which host holds which remotes.

**The helpers are mirrored; keep them in lockstep.** Each sync script exists
twice: the live copy that runs, and a repo mirror under `scripts/`. Editing
either side means updating the other in the SAME change. Verify with
`git -C <repo> show HEAD:scripts/wsync | diff - ~/bin/wsync`, run on the host
where the live copy lives, comparing against the committed blob rather than the
working file (a CRLF-smudged checkout reads as false drift). Use `git -C` rather
than relying on the working directory, and print a line count on both sides, so
an empty left side is obvious rather than reading as total drift.

**This skill is mirrored too.** It exists in the repo at
`.claude/skills/asset-tracker-workflow/SKILL.md` and in the Chat environment.
The same rule applies to itself: editing either side means updating the other in
the same change. Verify by downloading the Chat-side copy and diffing it against
the committed blob.

## 5. Commit message style

No apostrophes. Human-voiced imperative. No AI attribution. No em dashes. Pipe
the body via a quoted heredoc (`<< 'MSGEOF'`). One commit per logical track for
rollback granularity.

A commit message describes its own change. Corrections to an earlier commit
belong in the message of the commit that makes them, in context, not as a note
appended to an unrelated one.

## 6. Execution gotchas

These decide whether a patch or commit runs correctly, so they live with the
procedure. Codebase semantics (JSONB mutation, shared CSS scope, hx-boost, the
polymorphic device link, template context propagation) are repo facts and live
in `CLAUDE.md`.

- **The `&&`-chain trap.** A failed verification step exits non-zero and
  silently skips the rest of the chain. Separate verification from mutation and
  join steps with `;` not `&&`. Note `grep -c` exits 1 on a zero count, which is
  a pass, not a failure.
- **There is a transmission ceiling on SSH heredocs.** Two failures in one
  session at roughly 139 and 182 lines; anything under about 130 went through.
  Split long patch scripts into appended parts (`cat >`, then `cat >>`) rather
  than switching to Write+scp, which section 2 rules out. Read the assembled
  file back in full before running it.
- **SSH-heredoc does not preserve literal backslash escapes.** `\u2715`,
  `\u00b7`, `\x27` and friends mangle across the boundary. Embed the real glyph
  or build it with `chr(...)`.
- **Em dashes also mangle across the heredoc.** Build with `chr(8212)` only if
  unavoidable; prefer avoiding it structurally per section 2.
- **Quote the heredoc delimiter** (`<< "PYEOF"` or `<< 'PYEOF'`) so backticks
  and `$` in the script body are not expanded in transit. Note that backslash
  escapes inside a double-quoted `ssh "..."` argument are processed by the local
  shell before sending.
- **New top-level JS function names must be asserted free** (`count == 0`)
  before adding one; duplicates silently clobber.
- **Root-owned `__pycache__`.** A root `docker exec` importing from a
  bind-mounted path leaves root-owned bytecode dirs that break host-side
  `py_compile`. Compile with `cfile="/tmp/..."`, or `chown` the directory.
- **`migrations/` is the truth for the next number.** Check
  `ls migrations/ | sort | tail` rather than assuming; a hardcoded next number
  goes stale immediately.

## 7. Chrome MCP notes

- Tools drop between turns and must be reloaded via tool search each pass.
- If no tab group exists, create one with `createIfEmpty` before navigating.
- Console tracking starts at the first `read_console_messages` call. Prime it,
  reload, then read, or the result is meaningless. An unprimed empty read cannot
  distinguish a clean console from an unwatched one: emit a probe, confirm it is
  captured, clear, then reload.
- `javascript_exec` structural checks (element found, class present, dataset
  values, active-link count) are the substantive pass/fail gate. Screenshots are
  supplementary.
- Some `href` values come back redacted as `[BLOCKED: Base64 encoded data]`.
  Work around it with other attributes rather than assuming the link is broken.

## When Code runs this without the project loaded

This skill is the procedure and is self-contained for patching and syncing. For
repo facts, point Code at `CLAUDE.md`. For subsystem design, LIST `docs/specs/`
and read the owning spec for the current feature rather than assuming an
attached document is the only one. Do not default to
`c2c-c1-discovery-handoff.md`; it is a C2C-era guard doc and is usually the
wrong spec.
