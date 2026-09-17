# Item vendor link: vendor_id as a real foreign key

    STATUS:   post-build record, written 2026-09-17 by Chat after the build
              shipped as 379ee65. Decisions by Jus the same day. There was
              no spec before the build; this document is the record.
    Board:    BACKLOG-TRIAGE.md item N11.
    Taken at: HEAD 379ee65, branch main. Anchors below are at that commit
              and age from the first commit that touches the file.
    Related:  fulfillment-vendor-direction.md is NOT the owner of this
              subject; that spec is about the fulfilment build partner.
              vendor_profiles had no owning document before this one.

## What was wrong

Item.vendor_id and ItemReceipt.vendor_id were bare integers with no foreign
key. Three surfaces disagreed about what the number meant: the triage Fix
panel showed a number box with the hint "Vendor lookup is coming in a later
update", intake and item edit took free text that _safe_int silently turned
into NULL while the user saw a success toast, and the receipts page read it
as a vendor_profiles id. Two items carried values (7 and 42) that matched no
profile; no receipt carried one. The code's own TODO(vendor-ui) said to swap
to a select when a vendors table existed, and vendor_profiles had existed
since migration 013.

## Decisions (Jus, 2026-09-17)

1. Both columns become real foreign keys to public.vendor_profiles(id) with
   ON DELETE SET NULL. Orphan values are nulled by the migration first.
2. Intake, item edit and the Fix panel pick the vendor from the profile
   list. The server refuses anything that is not blank or an existing
   profile id; the user sees the refusal.
3. item_vendor, the free text name, is untouched. The spreadsheet import
   (migration 067) still skips vendor_id. The receipts page, already id
   based, is untouched.
4. Built from the board with no spec, and documented afterwards here.

## What shipped (379ee65)

- migrations/075_item_vendor_fk.py: nulls orphans on both tables, then adds
  items_vendor_id_fkey and receipts_vendor_id_fkey, each ON DELETE SET
  NULL, each dropped before it is added so the script is idempotent. Prints
  row counts, orphan counts and the constraint definitions, and aborts on
  any mismatch. On apphost: items 548, receipts 952, orphans 2 and 0
  before, 0 and 0 after.
- models.py: the two Column lines carry ForeignKey("vendor_profiles.id",
  ondelete="SET NULL"). No relationship was added; names come from a
  helper, the way receipts.py already did it.
- intake.py: _get_vendors(db) returns [{id, name}] ordered by name, with
  display_name preferred. _vendor_id_or_error(db, value) returns
  (None, None) for blank, (id, None) for an existing profile id, and
  (None, "Vendor must be chosen from the list") for anything else. The POST
  handler validates before the receipt payload is built and raises inside
  its existing try so the existing 400 re-render reports the message; the
  validated id reaches both the item and the receipt row.
- item_detail.py: the same helpers; the GET context carries vendors and
  vendor_name; the update handler appends the refusal to its existing
  errors list, which re-renders the form (status 200, the handler's
  existing shape for MAC errors as well).
- triage.py: label "Vendor"; the Fix panel GET passes vendors for the
  vendor type; the save splits the old ("location", "vendor") branch and
  returns 400 with the helper's message for a bad vendor.
- Templates: intake.html and item_detail.html render a select with the
  blank option "Select vendor..." in the wording of their location selects;
  the Fix panel renders a select in the shape of its location branch with
  the em dash blank option; item_detail.html's read-only row is labelled
  "Vendor profile" and shows the name.
- vendors.py: delete_vendor's docstring now says items and receipts lose
  the link and keep their text.

## Behaviour to know

- The Fix panel can set a vendor but not clear one, because _is_missing
  still rejects a blank. Clearing is done on the item edit form, where a
  blank now clears the column rather than being coerced.
- Deleting a vendor profile nulls vendor_id on every item and receipt that
  referenced it. There is no usage check on the delete route.
- The triage badge rose from 546 to 548 when the two orphan ids were
  nulled: those items had a non-NULL value that hid a real vendor gap.
- No new route, so the auth census and the suite total (919 / 39) did not
  move.

## Gates run (2026-09-17)

Compile and Jinja parse in the container; migration 075 with its counts;
restart, worker up, in-container import showing both ForeignKey objects;
suite 919 passed, 39 skipped. Browser, through Chrome MCP: intake renders
11 profiles; a POST with vendor_id 999 re-renders 400 with the message and
creates nothing; the Fix panel refuses 999 and abc with the message and a
blank with the existing "cannot be empty" message, and saves 3; the item
page shows "Vendor profile BCD", its edit form preselects BCD, a manipulated
999 is refused and the vendor kept, a blank clears it. Console empty on
every page. Database fingerprint: item 11 back to NULL, 548 items, nothing
created, audit_log unchanged.

## Observations recorded on the board, not fixed here

- The suite leaks 7 rows into item_schema.receipts per run: 948 of 952
  receipts were created by "Contract test admin" and only one receipt is
  linked to an item.
- Fix panel saves and item edit saves write no audit_log rows.
- vendor_profiles carries a row named "Nexcom; Velasea" beside separate
  Nexcom and Velasea rows, and no profile has contact details.

## Out of scope, left as it was

item_vendor text, the receipts page, the spreadsheet import, bulk edit,
receipt vendor display on the item page, an admin usage check before
profile deletion.
