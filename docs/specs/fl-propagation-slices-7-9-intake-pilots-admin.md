# Propagation slices 7-9: Intake, Pilots Due Back, Admin section

The last content pages. After these, only the chrome slice (sidebar/topbar) remains. Order: 7 -> 8 -> 9. Slices 7 and 8 are small; 9 is a section and splits into three commits.

## Slice 7: Intake (`/assettracker/intake`)

Form page — composes entirely from the item-detail edit treatment. Opt-in recipe as always.

| Live element (2026-07-09) | Treatment |
|---|---|
| Section cards (Basic Information, Location & Ownership, Identifiers & Part Numbers, Vendor, Deployment Details, Notes) | Body cards, tracked muted headers, inputs/selects/textarea/date fields with the focus-ring form treatment |
| Attach Receipt (optional) collapsible | Body card with the triage chevron pattern (muted duotone caret, rotate on open); inner upload zone = dashed border, blush tint on dragover |
| Back to Inventory (top right) + Cancel (footer) | Tint buttons |
| Create Item (blue solid, footer) | The page's ONE solid blush CTA |

Contracts: full create round trip on a throwaway item (then delete it), receipt attach expansion, category/status/location selects populate, any client-side validation states (style invalid = red tint border + red helper text if such states exist — discovery).

Suggested commit: `Opt intake into the fl restyle language`

## Slice 8: Pilots Due Back (`/assettracker/fulfillment/pilots-due-back`)

Small page, part of the fulfillment family that was never opted in.

| Live element | Treatment |
|---|---|
| Title + "0 OVERDUE" / "0 DUE SOON" chips | Red tint / amber tint badges (fl-banner chip pattern); Title Case ("0 Overdue", "0 Due Soon") |
| Empty state text | Muted, inside a body card |
| Populated state (loaner camera list — not visible in my session) | DISCOVERY REQUIRED: if tabular -> fl-table; if cards -> body-card anatomy with due-date urgency badge (amber due soon / red overdue) |

Contracts: whatever links each row carries (likely to items or orders), dashboard Pilots banner counts stay consistent.

Suggested commit: `Opt pilots due back into the fl restyle language`

## Slice 9: Admin section — three commits

Nav groups: PEOPLE (Users, Departments), DATA & LOGS (Audit log, Error log, OUI reference, Part Numbers, Procurement, Receipts, Storage), INTEGRATIONS, SYSTEM (contents undiscovered — inventory them first).

### 9a. People

| Live element | Treatment |
|---|---|
| Users card grid (avatar initials, name, dept, permission chips, active dot, inactive grayed) | Body cards. DESIGN CALL: initials avatars STAY here — people are the card's subject, unlike the assignee metadata we removed from asset cards. Avatar = flat single-hue circle (no gradients), hue stable per user. Permission chips = tint chips (role-colored: admin red tint, editor blush tint, viewer muted, feature grants green tint). Active dot = green; inactive card at reduced opacity with muted chip |
| Search + All Roles select + "+ Add user" | Search archetype, select treatment; Add User = the page's solid blush CTA |
| Departments page | Discovery; likely list/table -> fl-table |

Contracts: add/edit user modals (modal archetype), role filtering, active/inactive display, the `justin_editor` standing test account renders like any user.

Suggested commit: `Opt admin people pages into the fl restyle language`

### 9b. Data and logs (7 table pages)

All are filter-bar + table pages -> select treatment + fl-table. Audit log specifics: event chips (user_login, oem_po_created...) = mono muted chips (info tint at most — they are taxonomy, not alerts); failed/error events (user_login_failed) = red tint; timestamps + IP mono muted; details column wraps. Error log: severity chips red/amber tint. Others (OUI, Part Numbers, Procurement, Receipts, Storage): fl-table + their action buttons as tints, one solid blush max per page.

Contracts: filter selects reload correctly, pagination if any, receipt file links open, no bulk-op regressions.

Suggested commit: `Opt admin data and log pages into the fl restyle language`

### 9c. Integrations + System

Undiscovered — inventory first, map to archetypes, and if anything has no archetype STOP and bring it back to Chat for a mock before building. Danger zone actions (deletes, resets, integration keys) follow the tint rule with red tint for destructive; never a solid red.

Suggested commit: `Opt admin integrations and system pages into the fl restyle language`

## Discipline and gates

As established: discovery-first per page, `.fl-restyle` scope, guarded patches, `var` + idempotent `htmx:load`, `|tojson|forceescape`, no shared legacy edits. Gates per commit: jinja parse -> restart -> Chrome smoke both themes -> adjacent pages unaffected -> console clean -> diff -> commit -> four-location sync.

After slice 9 ships: the chrome slice (sidebar, topbar, footer, login page if any) is the finale — it needs its own spec since chrome spans every page and the z-lift/body:has scaffolding interacts with it. Flag readiness and we will spec it in Chat.
