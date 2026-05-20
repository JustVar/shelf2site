# U2 / U3 — Rename Followups (deferred from U1)

U1 (2026-05-04) renamed the `teams` DB table to `departments` and updated all model / route / template / JS references that affect runtime behaviour. The cosmetic / internal-identifier renames listed below were deliberately deferred so U1's blast radius stayed minimal. Sweep these together when U2 or U3 (full Users + Departments UI rebuild) lands.

## Deferred renames

- [x] Rename file `app/templates/admin_teams.html` → `admin_departments.html` **[done — U3a]**
- [x] Rename file `static/js/admin-teams.js` → `admin-departments.js` **[done — U3a]**
- [x] Rename Jinja block `{% block nav_admin_teams %}` → `{% block nav_admin_departments %}` — **dead code, dropped entirely** (base.html never declared the block; sidenav active-state uses URL match). **[done — U3a]**
- [x] Rename route URLs (legacy paths kept as backward-compat wrappers to drop after U3 stabilizes):
  - `GET  /admin/teams`              → `/admin/departments`
  - `POST /admin/teams/add`          → `/admin/departments/add`
  - `PUT  /api/admin/teams/{id}`     → `/api/admin/departments/{id}`
  - `DELETE /api/admin/teams/{id}`   → `/api/admin/departments/{id}`
  - `POST /api/admin/teams/{id}/permissions` → `/api/admin/departments/{id}/permissions`
  - `POST /api/admin/users/{id}/team` → `/api/admin/users/{id}/department` **[done — U3a]**
- [x] Rename JS function names: `addTeam`, `editTeam`, `deleteTeam`, `toggleTeamPerm`, `removeFromTeam` → `addDepartment` / `editDepartment` / etc. **[done — U3a]** (`changeTeam` in admin-users-v2.js still on old name — drawer-internal handler, intentional defer to a future cleanup.)
- [x] Rename CSS class `.team-badge` → `.department-badge` (incl. selector in `tours.py`). **[done — U3a]**
- [x] Rename DOM ID prefix `id="team-${id}"` → `id="department-${id}"` (in renamed `admin_departments.html`). **[done — U3a]**
- [x] Rename DOM IDs `add-team-form`, `add-team-msg` → `add-department-form`, `add-department-msg` (incl. tour-step selector in `tours.py`). **[done — U3a]**
- [x] Rename inline JS const `TEAMS` → `DEPARTMENTS` in `admin_users.html` (and update the `changeTeam` consumer in `admin-users.js`) **[done — U2b]**
- [x] Rename icon `'teams'` → `'departments'` in `app/templates/partials/icons.html` and the `icon(...)` call in `app/templates/base.html`. **[done — U3a]**
- [x] Update `models.py` `_resolve_perm` docstring: `"inherit from team"` → `"inherit from department"` (the body was updated in U1; the docstring was left for this sweep) **[done — U2d.1]**
- [ ] Audit `admin_users.html` permission tooltip strings: any remaining `"Inherit from team"` after U1 (a single sweep with `grep "from team" app/templates/`) — update to `"from department"`
- [ ] If audit-log read-side filters get added later, prefix `team_*` event_type strings → `department_*` (U1 wrote the new event types; this is a guard for future readers)

## Out-of-scope (stays as-is)

- Old migration `migrations/012_add_teams_rbac.py` — historical record, never edit.
- Existing audit-log rows where `target_table = 'teams'` or `event_type LIKE 'team_%'` — these are point-in-time history and stay as-is.

## Quick verification after the sweep

After applying U2/U3, run:
```bash
grep -rn "team\b\|Team\b" /opt/asset_tracker/app/ /opt/asset_tracker/static/ | grep -v __pycache__
```

Remaining matches should ALL be unrelated concepts:
- `fulfillment.html` — `team_members` / `TEAM_MEMBERS` / Team Coverage (Slack coverage list, distinct concept)
- `warranty.html` — `loaner_from_team` / `loaner_to_team` (free-text internal-loaner inputs, distinct concept)
- `admin-notifications.js`, `admin-slack-bot.js` — `data.team` from Slack API (Slack workspace name)

If any other matches appear, sweep them.

## Permissions schema follow-ups (post U2d.1, 2026-05-05)

These items came out of the U2d.1 migration to ENUM types (`user_permission_state`, `department_permission_state`). All non-blocking, all noted for cleanup passes.

- **Permissions-constants DRY.** `USER_PERMISSION_COLUMNS` (15 names) lives in `app/routes/admin.py`. `USER_INHERITED_PERMS` (14) + `USER_NON_INHERITED_PERMS` (1) live in `migrations/048_permission_columns_to_enum.py`. Identical content, two homes. Move canonical to `app/models.py` and import from both. Bundle with the next code change that touches permissions handling.

- **dashboard.html line 172 — pre-existing bug.** Reads raw `user.can_view_financial` instead of going through `user.has_financial_access`. Effect: COG-by-category section is hidden from admin / CEO / system_admin / justin_admin / procurement_admin users unless they have an explicit per-user grant. Fix is a one-line template change. Pre-dates U2d.1; not introduced by the migration.

- **Legacy `app/static/js/admin-users.js` — orphaned, kept for rollback.** No template references it after U2b. Safe to delete after U2d.2 verifies. (See item below for rollback consideration.)

- **U2d.2 deferred — drawer permissions grid.** B3c.2 layout (toggle row + helper text + group sections). Two-state UI on top of the new tri-state ENUM schema. Drawer never sends `'inherit'` — only `'grant'` or `'block'`. The "department-move notification" idea (alert admin when a user's effective permissions change due to a dept move or role change) is a separate U6 step.

- **Role-tier guards on the new bulk endpoint.** The 15 legacy `/api/admin/toggle-{name}/{id}` endpoints have per-permission role-tier guards (e.g. `toggle_financial_permission` rejects toggling `can_view_financial` on admin / CEO / procurement_admin users). The new `POST /api/admin/users/{id}/permissions` endpoint does NOT replicate them — the property layer's role check makes column overrides no-ops at read time. If we want strict guards, replicate them in the new endpoint (~30 LOC).

- **Department permissions endpoint accepts both legacy boolean and new enum string.** This is dual-mode for transition safety. When U3's Departments rebuild lands, it can send `'grant'` / `'block'` directly. The legacy boolean branch can be removed when the legacy `admin_teams.html` is deleted.

- **Migrations dir now bind-mounted (post-U2d.1 cleanup, 2026-05-05).** `./migrations:/app/migrations` added to docker-compose.yml. Future migrations run via `docker compose exec app python migrations/NNN.py` directly — no more `docker cp` + `PYTHONPATH=/app` workaround needed.


## U3d cleanup pass (2026-05-15)

- [x] Delete `app/` `.bak.*` files accumulated during U2b→U2d→U3 migrations (38 files, ~1.5 MB). **[done — U3d]**
- [x] Drop the U1.6 alias route `GET /admin/departments → /admin/teams`. **[already done during U3a]** — the canonical `department_management_page` replaced the alias when `/admin/departments` became the real page route. Verified post-U3d: exactly one GET handler at that path.

## Still outstanding (post-U3d)

- [ ] **Drop U3a legacy URL wrappers** (6 routes). After one release cycle, remove the `_legacy` wrapper handlers for:
  - `GET /admin/teams` (302 redirect to `/admin/departments`)
  - `POST /admin/teams/add`
  - `PUT /api/admin/teams/{id}`
  - `DELETE /api/admin/teams/{id}`
  - `POST /api/admin/teams/{id}/permissions`
  - `POST /api/admin/users/{id}/team`

  Until then they preserve external bookmark compat. **Target removal date: 2026-06-01 or later.**

- [x] **Delete `static/` `.bak.*` files** (19 files, ~1 MB — same cruft pattern as `app/` but outside U3d's strict scope). Cosmetic; not blocking. — done 2026-05-18 (21 files removed)

- [ ] **`.team-badge` / `.department-badge` tour-step targets in `tours.py`** still point at a selector with no matching DOM element after U2b's user-card rewrite. Pre-existing tour-step rot. Fix during a tours-definitions audit.

- [ ] **CSRF guard on `GET /logout`.** Pre-existing risk — any third-party page can log a user out via `<img src="…/logout">`. Standard remediation is moving logout to POST-only with a CSRF token. Behavior change for any bookmarks; not in scope of nav work. Surfaced during U4b logout-link diagnosis.

- [ ] **Audit service worker caching of auth-state-changing routes.** Check `/static/sw.js` does not cache `/logout` or `/login` (or any response that mutates session state). Should not, but worth verifying. Surfaced during U4b logout-link diagnosis.
