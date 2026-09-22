# Receipts permission and financial field drop

Board item 40. Ratified 2026-09-22 at HEAD 579e3d9. Every anchor below was
read on blob-proven copies at that HEAD; every live count was read on
apphost the same day. Line numbers age from the commit that lands this
file; re-read with grep -n before editing.

## Rulings (Jus, 2026-09-22)

1. The permission is named `can_view_receipts`. Same three-state ENUM,
   same column on `users` (default `inherit`) and `departments` (default
   `block`).
2. Rename in place. Existing `grant` and `block` values carry over. No
   data migration.
3. Admin tier always sees receipts. The property is
   `is_admin_tier OR can_view_receipts` and nothing else.
4. The procurement role and `can_manage_procurement` stop opening
   receipts. Nothing else about procurement changes.
5. Vendor profile create and edit require admin tier OR
   `can_view_receipts`, which is exactly the new property. Delete stays
   admin tier (ruling of 2026-09-22, commit 644c4db).
6. The order money columns `contract_value` and `hardware_cost` are
   dropped, columns and code. The vendor cost display (`show_financials`,
   Total Spend, Cost column) is removed. `purchase_price` columns stay
   until item 30 settles the inventory model; nothing reads them after
   this. `warranty.renewal_cost` stays; it is warranty data.
7. No grants are added for the Hardware department. The two `_e2e` test
   accounts there lose receipts, which matches a viewer and an editor with
   no flag. `rowan` is being deleted through `/admin/users` separately.

## Live state read before the spec (apphost, 2026-09-22)

- Users 26 (22 active). Seven carry an explicit financial or procurement
  setting or the procurement role. All of them keep receipts after the
  rename except through the procurement branch, which nobody relies on
  once `rowan` is gone.
- Departments 6. `Product Management` grants both flags; `Hardware`
  grants `can_manage_procurement` only.
- `customer_orders` 8 rows, 0 with `contract_value`, 0 with
  `hardware_cost`. The drop deletes no data.
- `user_permission_state` is `{inherit,grant,block}`.

## Two slices, two commits, two migrations

Slice A is the rename. Slice B is the drop. A lands first; B does not
depend on A but touches two of the same files, so B's anchors are re-read
after A.

### Slice A: rename `can_view_financial` to `can_view_receipts`

**Migration `migrations/076_rename_financial_to_receipts.py`.** House
shape of 075: single `engine.begin()`, prints before and after, aborts on
any count that moves. Idempotent: each `ALTER TABLE ... RENAME COLUMN` runs
only if `information_schema.columns` shows the old name and not the new.

    ALTER TABLE users       RENAME COLUMN can_view_financial TO can_view_receipts
    ALTER TABLE departments RENAME COLUMN can_view_financial TO can_view_receipts

Before and after: count of users by state on the column, count of
departments by state, total rows of each table. Abort if the totals move
or if the per-state counts differ between old and new name.

**Code, one guarded multi-file script (rev 48 shape).**

| File | Line | Old | New |
|---|---|---|---|
| `app/models.py` | 507 | `"can_view_financial",` | `"can_view_receipts",` |
| `app/models.py` | 524 | `can_view_financial = Column(department_permission_state` | `can_view_receipts = Column(department_permission_state` |
| `app/models.py` | 566 | `can_view_financial = Column(user_permission_state` | `can_view_receipts = Column(user_permission_state` |
| `app/models.py` | 633-636 | `has_financial_access` body (role tuple + procurement_admin, two `_resolve_perm`) | `has_receipts_access`: `return self.role in self._ADMIN_LEVEL_ROLES or self._resolve_perm("can_view_receipts")` |
| `app/models.py` | 649 | `self._resolve_perm("can_view_financial")` | `self._resolve_perm("can_view_receipts")` |
| `app/auth.py` | 296-309 | `require_financial`, docstring, detail text | `require_receipts`; docstring: admin tier or `can_view_receipts`; detail: `This feature requires the Receipts permission. Administrators and users granted Receipts access can view uploaded receipts and manage vendor profiles. Please contact your administrator to request access.` |
| `app/routes/admin.py` | 454 | `"can_view_financial": u.can_view_financial,` | `"can_view_receipts": u.can_view_receipts,` |
| `app/routes/admin.py` | 479 | `"can_view_financial",` | `"can_view_receipts",` |
| `app/routes/admin.py` | 623-661 | route `toggle-financial`, `toggle_financial_permission`, guard `ADMIN_LEVEL_ROLES + ("procurement_admin",)`, message `always have financial access`, column, event `financial_permission_toggled`, details `financial access`, return key | route `toggle-receipts`, `toggle_receipts_permission`, guard `ADMIN_LEVEL_ROLES`, message `always have receipts access`, column `can_view_receipts`, event `receipts_permission_toggled`, details `receipts access`, return key `can_view_receipts` |
| `app/routes/admin.py` | 1396 | `"admin always has financial access"` | `"admin always has receipts access"` |
| `app/routes/receipts.py` | 1-5 | `Finance receipts viewer`, `financial-access users (require_financial)` | `Receipts viewer`, `users with the Receipts permission (require_receipts)` |
| `app/routes/receipts.py` | 20, 56, 129, 177, 202 | `require_financial` | `require_receipts` |
| `app/routes/vendors.py` | 14 | `require_financial` | `require_receipts` |
| `app/routes/vendors.py` | 155 | `user.has_financial_access or user.is_admin_tier` | `user.has_receipts_access` |
| `app/routes/vendors.py` | 169, 208 | `require_financial` | `require_receipts` |
| `app/routes/fulfillment.py` | 1192, 1236 | `user.has_financial_access` | `user.has_receipts_access` (slice B deletes both lines; A keeps them compiling) |
| `app/templates/base.html` | 214, 217, 291 | `user.has_financial_access` | `user.has_receipts_access` |
| `app/templates/vendors.html` | 13, 35, 92, 95, 114, 134 | `user.has_financial_access or user.is_admin_tier` | `user.has_receipts_access` |
| `app/tours.py` | 1815 | `(financial data, provisioning, site management)` | `(receipts, provisioning, site management)` |
| `static/js/admin-users-v2.js` | 9 | key `can_view_financial`, name `Finance`, helper `View prices, receipts, financial fields` | key `can_view_receipts`, name `Receipts`, helper `View uploaded receipts and manage vendor profiles` |
| `static/js/admin-departments-v2.js` | 7 | key `can_view_financial`, name `Finance` | key `can_view_receipts`, name `Receipts` |
| `static/js/admin-departments-v2.js` | 29 | as users-v2.js:9 | as users-v2.js:9 |

Label length: `Receipts` is 8 characters against `Finance` at 7; the
department grid is 2 by 7 fixed cells and the user drawer wraps. Read the
rendered grid on `/admin/users` and `/admin/departments` in the gate.

The 14 other `toggle-*` endpoints and their `_cycle_perm` helper are
untouched. `has_any_admin` (`models.py:647`) has no caller anywhere; the
rename touches its reference and the board records it as dead.

**Docs in the same commit.**

| File | Lines | Change |
|---|---|---|
| `CLAUDE.md` | 69 | `user.has_financial_access` to `user.has_receipts_access` |
| `CLAUDE.md` | 258 | Receipts row: `require_receipts` twice, `user.has_receipts_access`, `admin tier + can_view_receipts` |
| `CLAUDE.md` | 298 | `require_receipts | user.has_receipts_access | receipts and vendor profile edits` |
| `README.md` | 34 | `require_receipts` and `Receipts access` |
| `README.md` | 55-57, 60-65 | `financial data` to `receipts`; column header `Editor+Receipts`; row `Procurement Analytics` becomes `Receipts` |
| `README.md` | 160 | delete the `add_financial_permission.py` bullet |
| `docs/ENDPOINT_AUTH_CENSUS.md` | 113 | `/api/admin/toggle-receipts/{user_id}` |
| `docs/ENDPOINT_AUTH_CENSUS.md` | 421-424, 537, 539 | `financial access` to `receipts access` |
| `docs/RBAC_TEST_PLAN.md` | 22, 27, 87-122, 261, 293, 338, 382, 438-449, 513 | Section 2 rewritten for the two-branch property; procurement_admin no longer listed as a receipts role |
| `docs/SCHEMA_REFERENCE.md` | 821, 844 | column name (the `bool` type on both lines is already stale since 048; corrected to the ENUM name in the same edit) |
| `scripts/add_financial_permission.py` | whole file | deleted; it adds a column that no longer exists by that name |

Not touched: `migrations/012`, `migrations/048`, `migrations/020`
(history), `docs/U2_U3_RENAME_FOLLOWUPS.md` (a dated follow-ups record;
its line 52 is already stale and stays as history).

**Gates, slice A.**
- Python: `python -m py_compile` on the five `.py` files in container.
- Jinja parse on `base.html`, `vendors.html`.
- Census after the write: whole-token `can_view_financial`,
  `has_financial_access`, `require_financial`, `toggle-financial` across
  `app/ static/ tests/ docs/ README.md CLAUDE.md migrations/07*` returns
  zero. Self-test the census on the before-tree first (expect the counts
  in the footprint above).
- Deploy order, one ssh line: write the patched files, run 076, restart
  the app. The window between 076 and the restart is seconds; during it
  the old code cannot load a User. Do not spread the three across turns.
- Post-076 read: `\d users` and `\d departments` show `can_view_receipts`
  and no `can_view_financial`; per-state counts equal the pre-076 read.
- Browser, console primed, as Jus (admin): `/receipts` loads; `/vendors/`
  Add Vendor, Edit, Delete present; `/admin/users` drawer shows `Receipts`
  with its helper and the grid does not wrap or clip; `/admin/departments`
  grid shows `Receipts` in its cell. Parse-every-handler probe on each.
- Browser as `testviewer`: `/receipts` is refused with the new message;
  `/vendors/` 0 Add, 0 Edit, 0 Delete; nav has no Receipts link.
- Suite: 919 passed / 39 skipped. No route added or removed; the toggle
  route is renamed, so the census total holds.
- Diff pasted and matched hunk for hunk. Four HEADs.

### Slice B: drop `contract_value` and `hardware_cost`, remove the vendor cost display

**Migration `migrations/077_drop_order_money_columns.py`.** Same shape.
Before: row count and `count(contract_value)`, `count(hardware_cost)`.
Abort if either non-null count is above zero. Then

    ALTER TABLE customer_orders DROP COLUMN IF EXISTS contract_value
    ALTER TABLE customer_orders DROP COLUMN IF EXISTS hardware_cost

After: row count unchanged; `information_schema.columns` shows neither
name. A `pg_dump -t customer_orders` to `/tmp` runs before 077 in the
same ssh line and is deleted after the suite passes.

**Code, one guarded multi-file script. Line numbers are pre-A and will
shift by A's edits in `vendors.py` and `fulfillment.py`; re-read.**

| File | Line | Change |
|---|---|---|
| `app/models.py` | 1229-1230 | delete both column lines |
| `app/routes/fulfillment.py` | 291-292 | delete both dict keys |
| `app/routes/fulfillment.py` | 1192-1193 | delete the `if` and the `headers.extend` |
| `app/routes/fulfillment.py` | 1236-1240 | delete the `if` block |
| `app/routes/orders.py` | 285-? | delete `_to_dec` (its only callers are 310-311); read its full extent first |
| `app/routes/orders.py` | 310-311 | delete both kwargs |
| `app/routes/orders.py` | 410-421 | delete both `if "..." in body` blocks |
| `app/routes/vendors.py` | 37, 44-45, 53, 90 | delete `total_cost` and `price`; the `devices` dict keeps id, table, category, name, serial, status, purchase_date |
| `app/routes/vendors.py` | 156 | delete `"show_financials"` |
| `app/templates/vendor_detail_profile.html` | 190-195 | delete the Total Spend stat box |
| `app/templates/vendor_detail_profile.html` | 227 | delete the Cost `<th>` |
| `app/templates/vendor_detail_profile.html` | 244-246 | delete the Cost `<td>` block |
| `CLAUDE.md` | 230 | rider: drop `contract_value/hardware_cost,` from the CustomerOrder prose |

`migrations/020` stays as history. `_vendor_analytics` keeps its
docstring minus `costs`.

**Gates, slice B.**
- Census after the write: whole-token `contract_value`, `hardware_cost`,
  `show_financials`, `total_cost` across `app/ static/ tests/ CLAUDE.md`
  returns zero (`migrations/` excluded by design).
- Python compile on the four `.py` files; Jinja parse on
  `vendor_detail_profile.html`.
- Deploy order: write files, dump, 077, restart, one ssh line.
- Browser as Jus: `/vendors/{id}` renders with Total Devices and no Total
  Spend, device table has no Cost column; `/fulfillment/` loads; the
  fulfillment export downloads and its header row has 9 columns.
- Suite: 919 passed / 39 skipped. No route change.
- Diff, four HEADs, `/tmp` dump removed.

## Out of scope, recorded for the board

- The 15 legacy `toggle-*` endpoints have no caller (JS uses the bulk
  permissions endpoint). Deleting them is its own item; it moves the auth
  census total by 15.
- `has_any_admin` is dead code.
- `purchase_price` on three models rides with item 30.
- `docs/U2_U3_RENAME_FOLLOWUPS.md:52` cites a `dashboard.html:172` bug
  that no longer exists at this HEAD.
