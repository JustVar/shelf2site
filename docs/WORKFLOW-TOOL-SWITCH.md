# Workflow — Chat vs Code tool switching

**Chat = decide, ground, verify-in-browser. Code = build, edit, compile.**

This project runs across two surfaces: Claude Chat (this design/verification
interface, with Chrome MCP browser access) and Claude Code in VS Code (direct
repo edits, no paste loop). They are different tools for different phases of the
same work. Neither can switch you automatically; this doc is the shared rule so
whichever tool you are in flags a switch at the right moment.

## The rule

At each natural boundary — a finished commit, the end of a slice, or a fresh
decision point — ask: is the next action a decision or a keystroke?

- Next action is a design/architecture choice, a read-fact-vs-inference
  grounding call, or live browser verification -> Chat.
- Next action is writing or editing files against a settled design, or
  compiling and iterating until it runs -> Code.

Flag at boundaries only, not mid-task. The point is to catch drift when you
surface for air, not to interrupt a build.

## Stay in Chat when the work is judgment

- Deciding what to build or which approach (design forks, schema shape,
  discriminator choices)
- Grounding before building: is this a read fact or an inference?
- Browser verification via Chrome MCP — Code cannot drive the live app
- Reviewing whether a result is correct, not just whether it ran
- Anything where a wrong call costs more than a wrong line of code

## Switch to Code when the work is mechanical execution

- Writing a migration, model, routes, or template once the design is settled
- Multi-file edits where the paste-back loop is pure tax
- Applying a known change across N files
- Running the build, reading tracebacks, iterating until it compiles

## Drift tells (you are in the wrong tool)

- In Chat and pasting raw file output back and forth just so it can edit
  -> go to Code.
- In Code and it is making a design/architecture call without grounding it,
  or you need to see it in the live app -> come back to Chat.

## Tool surfaces (do not run duplicates)

- Use one Claude Code surface. The VS Code extension is the fit for this repo
  (you already work there; it keeps git and diff review in view). Code Desktop
  is the same Claude Code in a separate window — no extra capability, do not run
  both.
- Build commits from Code use the same on-disk helpers as Chat:
  apphost ~/bin/at-sync-commit.sh <paths> (message on stdin) -> emits
  PREV/NEW; workstation ~/bin/wsync PREV NEW -> ff-merge, push both remotes,
  verify four HEADs, clean up.

## When Code drives a build, hand it the guards

Code has direct repo access and will not default to the discovery-first,
count-asserted-patch, show-the-diff discipline unless told. Point it at
docs/specs/c2c-c1-discovery-handoff.md, docs/specs/c2c-camera-certification.md,
and CLAUDE.md so it inherits the project guardrails.
