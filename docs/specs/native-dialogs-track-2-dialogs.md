# Native dialogs, Track 2: SxDialog and the confirm and prompt sites

    STATUS:   post-build record for slice 0, written 2026-09-18 by Chat after
              the helper shipped as e8a282c. Decisions by Jus the same
              morning. There was no spec before the build; this document is
              the record, and from here on it owns Track 2 (slices 1 and up).
    Board:    BACKLOG-TRIAGE.md item N7.
    Taken at: HEAD e8a282c, branch main. Anchors below are at that commit
              and age from the first commit that touches the file. The
              call-site anchors were read at af97f70; e8a282c touched none
              of those files, so they still hold.
    Related:  native-dialogs-track-1-alerts.md owns Track 1 (the alert
              sites, complete). Its Track 2 section (:803-828) named the
              blocker this slice removes, no shared modal helper, and its
              counts at :810-815 are superseded by the census below.
              DESIGN_SYSTEM.md carries the Dialog archetype row.

## What was wrong

Thirty-seven sites call the native window.confirm or window.prompt. They
render in the browser chrome, ignore the theme, block the page and every
extension (a Chrome MCP gate cannot click through one), and cannot be
styled, labelled or tested. Track 1 replaced alert with toasts; confirm and
prompt need an answer back, which a toast cannot give. The app had four
modal class families in CSS and every open and close inline in its own
template, so there was nothing shared to build on.

## Decisions (Jus, 2026-09-18)

1. A new helper, SxDialog, body-mounted like SxToast, styled inline on the
   --flc-* chrome tokens with dark fallbacks, in its own file loaded from
   base.html. No page CSS touched, no existing modal family reused.
2. Built straight from the board as slice 0: the helper alone, with zero
   call sites converted, and documented afterwards here. Slices 1 and up
   convert the sites by file.
3. fulfillment.html and order_detail.html each get their own commit.
   guide.js:810 (a confirm inside an open modal) and admin-users-v2.js:642
   (a prompt that displays a credential, Track 4) are decided separately.
4. Two details Chat added inside that decision, accepted: either call takes
   a plain string as the message, and a call made while a dialog is open
   waits its turn instead of stacking or being dropped.

## What shipped (e8a282c)

- static/js/dialog.js, new, 212 lines, pure ASCII. An IIFE exposing
  window.SxDialog with exactly two functions. Chat wrote it, node checked
  it, a jsdom harness ran 40 cases against it, and the patch script
  embedded it byte for byte under a sha256 assert
  (ba422f8814b489dcdefd69231fcaeda3d28d5c94ba04f55ac40aa4af07f35cc1).
- app/templates/base.html: one script line after toast.js (:85), same
  js_v cache-buster shape. The buster is a sha1 of the file on disk
  (app/main.py _asset_version), so no registration was needed.
- docs/DESIGN_SYSTEM.md: the Dialog archetype row after Toast (:73), and
  the chrome section pointer on :14 corrected from 725 to 719.

## The contract

    SxDialog.confirm({title, message, okLabel, cancelLabel, danger}) -> Promise<boolean>
    SxDialog.prompt({title, message, label, value, placeholder, required}) -> Promise<string|null>
    SxDialog.confirm('Remove this row?')     a string is the message

- confirm resolves true on OK or Enter, false on Cancel, Esc or a click on
  the backdrop. prompt resolves the input value as typed (not trimmed) on
  OK or Enter, null on Cancel, Esc or the backdrop.
- Defaults: title "Please confirm" (confirm) or "Input needed" (prompt),
  okLabel "OK", cancelLabel "Cancel". danger paints the OK button on
  --flc-red and moves initial focus to Cancel; otherwise focus starts on OK
  (confirm) or in the input with its value selected (prompt).
- required keeps OK disabled (and Enter inert) while the trimmed input is
  empty. A message that is blank is omitted from the card when a title (or,
  for prompt, a label) is given; with nothing at all to show, the helper
  falls back to "Are you sure?" or "Enter a value" and warns on the console.
- Every string reaches the page through textContent. Nothing is markup.
  Newlines in a message render as line breaks (white-space: pre-line), so
  the existing multi-line confirm strings carry over unchanged.
- Keyboard: Esc cancels and the keydown is stopped in the capture phase so
  page handlers never see it (READ: the fulfilment New Order modal stayed
  open under a dialog closed by Esc). Enter confirms unless the Cancel
  button has focus. Tab wraps inside the dialog. Focus returns to the
  element that had it when the dialog opened.
- Stacking: overlay z-index 90000. Page modals top out at 2000 in CSS and
  templates, 9999 for the legacy coming-soon toast (base.html:824) and the
  scanner overlay (scanner.css:10); SxToast is 100000. A toast therefore
  renders over an open dialog (READ in the gate), which is the intended
  order: the dialog is asking, the toast is telling.
- Calls serialise on a promise chain: a second call made while one dialog
  is open opens after the first resolves. One overlay at a time, always.
- Element ids: sx-dialog-overlay, sx-dialog, sx-dialog-title,
  sx-dialog-msg, sx-dialog-input, sx-dialog-ok, sx-dialog-cancel. All
  asserted free repo-wide before the build.

## Converting a site (slices 1 and up)

The native calls are synchronous; SxDialog returns a promise. Every
conversion therefore has two parts: swap the call, and let the caller wait.

    if (!confirm('Delete this order?')) return;
    ->  if (!(await SxDialog.confirm({ title: 'Delete order', message: 'Delete this order?', okLabel: 'Delete', danger: true }))) return;
        and the enclosing function becomes async

    var name = prompt('New name', current); if (name === null) return;
    ->  var name = await SxDialog.prompt({ title: 'Rename', label: 'New name', value: current, required: true }); if (name === null) return;

- An inline onclick attribute cannot await. Move the body into a named
  async function and call it from the attribute, the pattern most of these
  templates already use for their fetch calls.
- A function that becomes async and is used as an event handler needs no
  further change; one whose return value a caller reads does, so read the
  callers before flipping it (check reachability, not existence).
- Keep the existing message text unless it is wrong. vendors.html:348 is
  wrong: it promises that deleting a profile leaves inventory untouched,
  which stopped being true at 379ee65 (items and receipts lose the link).
  Rider R44; convert it with corrected text.
- Give destructive confirms danger: true and a verb on the OK button
  (Delete, Remove, Reset), not "OK".
- guide.js:810 already sits in an async handler; its conversion is one
  await. It opens over the tour help modal, which is body-mounted too; the
  dialog's 90000 clears it. Still its own decision because it lives in the
  tour engine.
- admin-users-v2.js:642 uses prompt to DISPLAY a generated credential for
  copying. That is not a question; it is Track 4 and is not converted with
  a prompt dialog.
- Until a site is converted, a Chrome MCP gate that reaches it still stalls
  on the native dialog. Each conversion makes that flow gate-able; the
  gate for a converted site should click through the dialog.

## Census, READ 2026-09-18 at af97f70, unchanged at e8a282c

37 sites: 31 confirm, 5 prompt, 1 credential prompt. No alert remains
anywhere (rc=1).

Templates (21 confirm, 5 prompt):

    admin_errors.html:217            confirm
    decommissioned.html:71           prompt
    fulfillment.html:2923            confirm
    inventory.html:488, 527          confirm
    item_detail.html:865, 869, 874   prompt (three)
    order_detail.html:750, 811, 836, 978   confirm
    provisioning.html:1039, 1049     confirm
    provisioning_detail.html:653, 663, 673   confirm
    site_detail.html:379, 395        confirm
    sites.html:280                   confirm
    support.html:131 confirm, 154 prompt
    triage.html:416                  confirm
    vendors.html:348, 358            confirm (348 text wrong, R44)
    warranty.html:772                confirm
    order_detail.html:720            a comment that mentions confirm, not a site

static/js (10 confirm, 1 credential prompt):

    admin-departments-v2.js:468      confirm
    admin-intune.js:34               confirm
    admin-maintenance.js:61, 77      confirm
    admin-oui.js:88                  confirm
    admin-part-numbers.js:112        confirm
    admin-spreadsheet-sync.js:145    confirm
    admin-users-v2.js:614, 633       confirm
    admin-users-v2.js:642            prompt, credential display, Track 4
    guide.js:810                     confirm inside the tour help modal

Suggested slicing, by file, smallest blast radius first: the static/js
admin files (one commit, they share a shape); the single-site templates
(admin_errors, decommissioned, sites, triage, warranty, support,
inventory); vendors.html with the R44 correction; site_detail,
provisioning, provisioning_detail; item_detail (three prompts);
order_detail.html alone; fulfillment.html alone; then guide.js:810.

Sizing read owed before slice 1: whether any template uses hx-confirm
(htmx calls window.confirm for it), which the confirm( grep does not see.
UNREAD.

## Gates run (2026-09-18)

Chat's harness before transport: node --check; jsdom, 40 cases; the patch
script rebuilt from Code's cat -A, hash matched, run against synthetic
targets built from its own SPEC, 17 cases. On apphost: transport by
base64 with sha256 at both ends and ast.parse; dry run matching the
synthetic figures line for line; write with post-check; jinja parse of
base.html in the container; restart, three workers up; dialog.js 200 with
8913 bytes over the front door; suite 919 passed, 39 skipped (prediction
matched; no route). Browser, Chrome MCP on the live app: dialog.js
requested once at its sha1 buster; SxDialog present with exactly confirm
and prompt; danger confirm rendered on the dark tokens and cancelled by a
real Esc; plain-string confirm resolved true by a real click; required
prompt with a preselected value, OK disabled when emptied, typed and
confirmed by a real Enter; prompt cancelled to null; the New Order modal
under the dialog and an error toast over both, with elementFromPoint
agreeing; Esc on the dialog left the page modal open; light theme card
white on dark text with the OK button on the light accent; the tour help
menu opening and closing as before; zero overlays left; console empty on
every read, fetch guard empty; /orders/70 rendering with the helper
present. Nothing was written to the database.

## Observations recorded on the board, not fixed here

- The suite leaked 7 receipts again (966 to 973). N21.
- The dialog.js created by the patch script was opened in text mode; on
  apphost that is byte-identical and the post-check hashed it. A future
  script should open new files in binary mode for the record.
- Code prefixed its own git log and status reads to two of its steps
  despite standing instruction 1. Harmless, noted.

## Out of scope, left as it was

Every call site (slices 1 and up), hx-confirm if any, the Track 1 spec's
stale counts (R43, fix on the next commit that touches it), CLAUDE.md, the
census (no route), the four page modal families.
