# Native dialogs, Track 2: SxDialog and the confirm and prompt sites

    STATUS:   COMPLETE at b6b8e03. Rev 2, 2026-09-18, written by Chat after
              the last slice. Rev 1 was the post-build record for slice 0
              (the helper, e8a282c); this revision adds slices 1 to 5, which
              converted all 36 question sites. The one remaining native
              dialog in the app is the credential display at
              admin-users-v2.js:642, which belongs to Track 4.
    Board:    BACKLOG-TRIAGE.md item N7. Rider R44 closed at 85c2565.
    Taken at: HEAD b6b8e03, branch main. Anchors in the slice 0 sections
              below are at e8a282c and age from the first commit that
              touches the file; the line numbers in the census are the ones
              the sites carried when they were converted, not live anchors.
    Related:  native-dialogs-track-1-alerts.md owns Track 1 (the alert
              sites, complete). Its Track 2 section (:803-828) named the
              blocker slice 0 removed, no shared modal helper, and its
              counts at :810-815 are superseded by the census below (R43,
              still open).
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
    SxDialog.prompt({title, message, label, value, placeholder, required, okLabel, danger}) -> Promise<string|null>
    SxDialog.confirm('Remove this row?')     a string is the message

- confirm resolves true on OK or Enter, false on Cancel, Esc or a click on
  the backdrop. prompt resolves the input value as typed (not trimmed) on
  OK or Enter, null on Cancel, Esc or the backdrop.
- Defaults: title "Please confirm" (confirm) or "Input needed" (prompt),
  okLabel "OK", cancelLabel "Cancel". danger paints the OK button on
  --flc-red and moves initial focus to Cancel; otherwise focus starts on OK
  (confirm) or in the input with its value selected (prompt).
- prompt takes okLabel and danger as well; normalise() is shared by both
  kinds (dialog.js:47-68, READ during slice 2). support.html:154 and the
  two item_detail decommission prompts use them.
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
- Keep the existing message text unless it is wrong. One was: vendors.html:348
  promised that deleting a profile leaves inventory untouched, which stopped
  being true at 379ee65 (items and receipts lose the link). Corrected in
  slice 3 to say that items and receipts that referenced it lose the link and
  keep their vendor text. Rider R44 closed at 85c2565.
- Give destructive confirms danger: true and a verb on the OK button
  (Delete, Remove, Reset), not "OK".
- guide.js:810 sat in an async handler; its conversion was one await. It
  opens over the tour help modal, which is body-mounted too, and the dialog's
  90000 clears it (READ in the slice 5 gate: Esc closed the dialog and left
  the tours modal open). Converted in slice 5.
- admin-users-v2.js:642 uses prompt to DISPLAY a generated credential for
  copying. That is not a question; it is Track 4 and is not converted with
  a prompt dialog.
- Until a site is converted, a Chrome MCP gate that reaches it still stalls
  on the native dialog. Each conversion makes that flow gate-able; the
  gate for a converted site should click through the dialog.

## What shipped, slices 1 to 5

Every slice: a brief written by Chat from anchors read in Git Bash, a
guarded Python patch script written by Code and rebuilt from its cat -A in
Chat under a matching sha256, a synthetic harness run against targets built
from the script's own SPEC, then transport, dry run, write, gates, diff,
commit and four-location sync. No slice added a route, so the suite
prediction was 919 / 39 every time and matched every time.

    2d1b481  slice 1  nine confirm sites in seven static/js admin files,
                      plus the js_v cache-buster added to the three admin
                      templates whose script line lacked it (admin_intune,
                      admin_maintenance, admin_oui). 10 files, 12 lines.
    67e8890  slice 2  nine sites in seven single-site templates, seven
                      confirm and two prompt. Four plain functions gained
                      async, so 13 lines in 7 files.
    85c2565  slice 3  nine confirm sites in vendors, site_detail,
                      provisioning and provisioning_detail, all already
                      async. 9 lines in 4 files. Closes R44.
    58c88f4  slice 4  the three item_detail prompts. decOpenModal and
                      decOpenReactivate gained async; their only callers are
                      inline onclick attributes that ignore the return
                      value (READ). 5 lines in 1 file.
    b6b8e03  slice 5  the last six confirm sites: four in order_detail, one
                      in fulfillment, one in guide.js, all already async.
                      6 lines in 3 files.

Wording applied everywhere: the existing message text verbatim (the one
exception is R44), a title, a verb on the OK button, and danger: true on
deletes, dismissals, removals, resets and anything disruptive to every
user. Option keys in the order title, message, okLabel, danger for confirm;
title, message, label, then value, required, okLabel, danger for prompt.

## Census at b6b8e03, by state

37 sites were found at af97f70. 36 are converted; 1 is Track 4.

Converted, with the commit that did it:

    admin-departments-v2.js:468                              2d1b481
    admin-intune.js:34                                       2d1b481
    admin-maintenance.js:61, 77                              2d1b481
    admin-oui.js:88                                          2d1b481
    admin-part-numbers.js:112                                2d1b481
    admin-spreadsheet-sync.js:145                            2d1b481
    admin-users-v2.js:614, 633                               2d1b481
    admin_errors.html:217                                    67e8890
    decommissioned.html:70-71               prompt           67e8890
    sites.html:280                                           67e8890
    triage.html:397, 416                                     67e8890
    warranty.html:772                                        67e8890
    support.html:131, 154                   154 is a prompt  67e8890
    inventory.html:466, 488, 522, 527                        67e8890
    vendors.html:348, 358                   348 is R44       85c2565
    site_detail.html:379, 395                                85c2565
    provisioning.html:1039, 1049                             85c2565
    provisioning_detail.html:653, 663, 673                   85c2565
    item_detail.html:865, 869, 874          three prompts    58c88f4
    order_detail.html:750, 811, 836, 978                     b6b8e03
    fulfillment.html:2923                                    b6b8e03
    guide.js:810                                             b6b8e03

Not converted:

    admin-users-v2.js:642   window.prompt displaying a generated temporary
                            password for copying. Not a question. Track 4.

Not sites, and still present by design:

    order_detail.html:720   a comment mentioning prompt()
    dialog.js:3             the helper's own doc comment

Closing grep at b6b8e03, READ: across app/templates and static/js, the only
hits for confirm(, bare prompt( or window.prompt outside SxDialog calls are
those three lines. hx-confirm appears in no template or script (READ at
817992c, rc=1), so the sizing read rev 1 left UNREAD is answered: there was
none to convert.

## Gates run

Slice 0 (2026-09-18). Chat's harness before transport: node --check; jsdom,
40 cases; the patch script rebuilt from Code's cat -A, hash matched, run
against synthetic targets built from its own SPEC, 17 cases. On apphost:
transport by base64 with sha256 at both ends and ast.parse; dry run matching
the synthetic figures line for line; write with post-check; jinja parse of
base.html in the container; restart, three workers up; dialog.js 200 with
8913 bytes over the front door; suite 919 passed, 39 skipped (prediction
matched; no route). Browser, Chrome MCP on the live app: dialog.js requested
once at its sha1 buster; SxDialog present with exactly confirm and prompt;
danger confirm rendered on the dark tokens and cancelled by a real Esc;
plain-string confirm resolved true by a real click; required prompt with a
preselected value, OK disabled when emptied, typed and confirmed by a real
Enter; prompt cancelled to null; the New Order modal under the dialog and an
error toast over both, with elementFromPoint agreeing; Esc on the dialog
left the page modal open; light theme card white on dark text with the OK
button on the light accent; the tour help menu opening and closing as
before; zero overlays left; console empty on every read, fetch guard empty;
/orders/70 rendering with the helper present. Nothing was written to the
database.

Slices 1 to 5 (2026-09-18), the same chain each time. Harness case counts
17, 17, 17, 14 and 17, each including a drifted anchor, a changed old line,
an extra or missing token, a CR, a wrong line count, a wrong non-ASCII or
backslash count, a target already carrying SxDialog, a backup already
present, a mixed pending and applied state, and a template broken for the
jinja parse. Every converted JS block also passed node --check, pristine and
applied, since node is not on apphost and the browser console is the real
JS check. On apphost each slice: transport hash matched at both ends, dry
run, write with post-check from disk, jinja parse of every touched template
in the container, restart, suite 919 / 39, backups compared against HEAD and
deleted by name, diff reviewed, guarded commit, wsync and an independent
four-HEAD check.

Browser gates, Chrome MCP, behind a fetch guard answering every non-GET with
a failed fake response and a sendBeacon stub. Every one of the 36 converted
sites was opened on the live app, through the page's own control where one
is reachable and by calling the global directly where it is not. In every
case the dialog carried its title, message and verb; danger sites painted
the OK button on --flc-red and opened with Cancel focused; Cancel, Esc and a
backdrop click sent nothing and returned focus; OK reached the fetch guard
and the page's own error path. Specifics worth keeping: the two-step
decommission flow on item_detail prefilled the date with today and kept OK
disabled while the reason was blank; the multiplication sign in
order_detail:978 rendered as U+00D7 in the live dialog; guide.js:810 opened
at 90000 over the tours modal at 1000 and Esc closed only the dialog. No
non-GET request reached the server in any gate, confirmed against both the
network log and performance.getEntriesByType('resource').

## Observations recorded on the board, not fixed here

- The suite leaks 7 receipts per run (966 to 973 at slice 0, rising by 7 on
  every run since). N21.
- The dialog.js created by the slice 0 patch script was opened in text mode;
  on apphost that is byte-identical and the post-check hashed it. A future
  script should open new files in binary mode for the record.
- Code prefixed its own git log and status reads to several steps despite
  standing instruction 1, and its reported line counts for files it wrote
  ran one high throughout. Harmless, noted.
- pruneErrors (admin_errors.html) does not check resp.ok, so a failed prune
  reports success. Found during the slice 2 gate; not in scope there.
- showBanner on the Intune admin page has no target element when the
  integration is unconfigured. Found during the slice 1 gate.
- events/stream returns 503 on the first page loads after a restart.
- wsync aborted on a missing bundle once with all four HEADs already at the
  new commit, the second occurrence of the double-run signature. Settled
  each time by the independent four-HEAD check.
- Chrome MCP: the first real key press immediately after a javascript_tool
  call is sometimes dropped; a screenshot or click first makes it land. The
  click coordinate frame is the screenshot frame, not CSS pixels, so a
  coordinate taken from getBoundingClientRect must be scaled by
  frameWidth / window.innerWidth before it is clicked. An unscaled click
  lands on the backdrop, which cancels the dialog and looks like a pass.
- A census grep of the form grep -rn ... | grep -v "^.*://" silently drops
  every JS line-comment hit, because the output prefix ends in a colon
  immediately before the two slashes. The first closing census run for
  slice 5 was rerun without it.

## Out of scope, left as it was

admin-users-v2.js:642 (Track 4), the Track 1 spec's stale counts (R43, fix
on the next commit that touches it), CLAUDE.md, the census (no route), the
four page modal families.
