# RBAC Test Plan - Hardware Asset Tracker

## MANDATORY: E2E & RBAC for Every Feature

**Every new feature MUST include:**
1. **E2E API tests** in `tests/test_e2e_api.py` covering all CRUD operations, edge cases, and cleanup
2. **RBAC verification** — confirm correct access levels for all roles (admin, editor, viewer, sub-admins)
3. **Manual RBAC testing** per the matrix below (Claude Web or browser)
4. **Audit logging** for all create/update/delete operations

No feature is considered complete until all four items above are verified.

---

## Test Users Setup

Create test users for each role and permission combination:

### Core Roles
- **Admin**: Full system access
- **Viewer**: Read-only access to all features
- **Editor**: Can edit devices, map access, no financial/delete access

### Sub-Admin Roles (domain-specific)
- **Warranty Admin**: Full warranty/RMA CRUD including delete
- **Trials Admin**: Full trials CRUD including delete
- **Procurement Admin**: Procurement analytics + financial data access

### Permission Flags (toggleable per user)
- **Editor + Warranty Perm**: Editor with `can_manage_warranty=True`
- **Editor + Trials Perm**: Editor with `can_manage_trials=True`
- **Editor + Procurement Perm**: Editor with `can_manage_procurement=True`
- **Editor + Sites Perm**: Editor with `can_manage_sites=True`
- **Viewer + Warranty Perm**: Viewer with `can_manage_warranty=True`

## Feature Access Matrix

| Feature | Viewer | Editor | Warranty Admin | Trials Admin | Procurement Admin | Admin |
|---------|--------|--------|----------------|--------------|-------------------|-------|
| Dashboard | ✅ View | ✅ View | ✅ View | ✅ View | ✅ View | ✅ View |
| Device CRUD | ✅ View | ✅ Edit | ✅ Edit | ✅ Edit | ✅ Edit | ✅ Full |
| Edge Box Map | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Warranty & RMA | ✅ View | ✅ Edit | ✅ **Delete** | ✅ Edit | ✅ Edit | ✅ **Delete** |
| Try & Buy Trials | ✅ View | ✅ Edit | ✅ Edit | ✅ **Delete** | ✅ Edit | ✅ **Delete** |
| Disposal & EOL | ✅ View | ✅ Edit | ✅ Edit | ✅ Edit | ✅ Edit | ✅ Delete |
| Sites & Ownership | ✅ View | ✅ View | ✅ View | ✅ View | ✅ View | ✅ Full |
| Procurement Analytics | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| User Management | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Spreadsheet Sync | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Storage Monitor | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| OUI Settings | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Audit Log | ❌ | ❌ | ✅ Domain | ✅ Domain | ✅ Domain | ✅ Full |
| Device Credentials | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Map Privacy Controls | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

**Notes:**
- "Domain" audit log = sub-admins can only see logs for their domain (warranty_admin sees warranty logs, etc.)
- Permission flags grant the same access as the corresponding sub-admin role
- Sub-admins see "Management" sidebar section instead of full "Admin" section

## Test Cases

### 1. Map Access Control
**Test as Viewer:**
- [ ] Map link should NOT appear in sidebar
- [ ] Direct access to `/map/` should show permission denied page
- [ ] Permission page should explain "requires Editor or Administrator access"
- [ ] "Go to Dashboard" button should work
- [ ] Current role badge should show "Viewer"

**Test as Editor:**
- [ ] Map link SHOULD appear in sidebar
- [ ] Can access map successfully
- [ ] Can search and filter markers
- [ ] Map loads with correct markers

**Test as Sub-Admin (warranty/trials/procurement):**
- [ ] Map link SHOULD appear in sidebar
- [ ] Full map access same as editor

**Test as Admin:**
- [ ] Full map access
- [ ] Can see "show_on_map" checkbox when editing edge boxes
- [ ] Toggling checkbox hides/shows box on map

---

### 2. Financial Data Access (Procurement Analytics)
**Test as Viewer:**
- [ ] "Procurement Analytics" link should NOT appear in sidebar
- [ ] Direct access to `/admin/procurement` should show permission denied page
- [ ] Error message explains financial access requirement

**Test as Editor (no financial access):**
- [ ] "Procurement Analytics" link should NOT appear
- [ ] Direct access blocked with permission page
- [ ] Can still edit devices normally

**Test as Warranty Admin:**
- [ ] NO procurement access (warranty domain only)
- [ ] "Procurement Analytics" link does NOT appear
- [ ] Direct access blocked

**Test as Trials Admin:**
- [ ] NO procurement access (trials domain only)
- [ ] "Procurement Analytics" link does NOT appear
- [ ] Direct access blocked

**Test as Procurement Admin:**
- [ ] Sidebar shows "Management" section
- [ ] "Procurement Analytics" link appears under "Management"
- [ ] Can view procurement page with full data
- [ ] Can see pricing, vendor information, analytics
- [ ] Has financial data access

**Test as Editor with Procurement Permission:**
- [ ] Sidebar shows "Management" section
- [ ] "Procurement Analytics" appears under "Management"
- [ ] Full financial data access granted by permission flag

**Test as Admin:**
- [ ] Sidebar shows "Admin" section
- [ ] "Procurement Analytics" appears under "Admin"
- [ ] Full access to all financial data

---

### 3. Warranty & RMA Management
**Test as Viewer:**
- [ ] Can view warranty records
- [ ] Can view RMA claims
- [ ] Cannot create/edit/delete warranties
- [ ] Cannot create/edit/delete RMA claims
- [ ] Delete buttons do NOT appear

**Test as Editor:**
- [ ] Can create/edit warranty records
- [ ] Can create/edit RMA claims
- [ ] Delete buttons do NOT appear
- [ ] Attempting delete via API should return 403

**Test as Warranty Admin:**
- [ ] Can create/edit/delete warranty records
- [ ] Can create/edit/delete RMA claims
- [ ] Delete buttons SHOULD appear
- [ ] Can successfully delete via UI and API
- [ ] Sidebar shows "Management" section with "Warranty & RMA"

**Test as Trials Admin:**
- [ ] Can create/edit warranty records (editor-level access)
- [ ] Delete buttons do NOT appear (not their domain)
- [ ] Cannot delete via API

**Test as Procurement Admin:**
- [ ] Can create/edit warranty records (editor-level access)
- [ ] Delete buttons do NOT appear (not their domain)
- [ ] Cannot delete via API

**Test as Editor with Warranty Permission:**
- [ ] Delete buttons SHOULD appear
- [ ] Can successfully delete warranties and RMA claims
- [ ] Permission flag grants same access as warranty_admin role

**Test as Admin:**
- [ ] Full CRUD access including delete
- [ ] Delete buttons appear
- [ ] Can delete everything

---

### 4. Try & Buy Trials Management
**Test as Viewer:**
- [ ] Can view trials
- [ ] Cannot create/edit/delete trials
- [ ] Delete buttons do NOT appear

**Test as Editor:**
- [ ] Can create/edit trials
- [ ] Delete buttons do NOT appear
- [ ] Attempting delete via API should return 403

**Test as Warranty Admin:**
- [ ] Can create/edit trials (editor-level access)
- [ ] Delete buttons do NOT appear (not their domain)
- [ ] Cannot delete via API

**Test as Trials Admin:**
- [ ] Can create/edit/delete trials
- [ ] Delete buttons SHOULD appear
- [ ] Can successfully delete via UI and API
- [ ] Sidebar shows "Management" section with "Try & Buy"

**Test as Procurement Admin:**
- [ ] Can create/edit trials (editor-level access)
- [ ] Delete buttons do NOT appear (not their domain)
- [ ] Cannot delete via API

**Test as Editor with Trials Permission:**
- [ ] Delete buttons SHOULD appear
- [ ] Can successfully delete trials
- [ ] Permission flag grants same access as trials_admin role

**Test as Admin:**
- [ ] Full CRUD access including delete
- [ ] Delete buttons appear

---

### 5. Sites & Ownership Management
**Test as Viewer:**
- [ ] Can view sites list page
- [ ] Can view site detail pages
- [ ] Cannot create sites (no "+ Add Site" button)
- [ ] Cannot assign devices
- [ ] Cannot return/delete assignments
- [ ] POST `/api/sites` returns 403
- [ ] POST `/api/assignments` returns 403

**Test as Editor:**
- [ ] Can view sites list and detail pages
- [ ] Cannot create/edit/delete sites without `can_manage_sites` flag
- [ ] POST `/api/sites` returns 403
- [ ] POST `/api/assignments` returns 403

**Test as Editor with Sites Permission (`can_manage_sites=True`):**
- [ ] "+ Add Site" button appears
- [ ] Can create, edit, delete sites
- [ ] Can assign/return/delete device assignments
- [ ] All CRUD operations work

**Test as Admin:**
- [ ] Full CRUD access to sites and assignments
- [ ] Can manage all site types and ownership types

### 6. User Management & Permission Toggles
**Test as Viewer/Editor/Sub-Admins:**
- [ ] "User Management" link should NOT appear
- [ ] Direct access to `/admin/users` blocked
- [ ] Permission denied page appears

**Test as Admin:**
- [ ] Can access User Management page
- [ ] Can see all users with roles
- [ ] Role dropdown shows all 6 roles (viewer, editor, warranty_admin, trials_admin, procurement_admin, admin)
- [ ] Can toggle user active/inactive status
- [ ] Can reset user passwords
- [ ] Four permission toggle columns appear:
  - [ ] "Warranty Management" column
  - [ ] "Trials Management" column
  - [ ] "Procurement Management" column
  - [ ] "Financial Access" column (legacy, deprecated in favor of procurement permission)
- [ ] Sub-admin roles show "Role (Always)" - cannot toggle their own domain permission
  - [ ] Warranty admin shows "Role (Always)" for warranty permission
  - [ ] Trials admin shows "Role (Always)" for trials permission
  - [ ] Procurement admin shows "Role (Always)" for procurement permission
- [ ] Admin users show "Admin (Always)" for all permissions - cannot toggle
- [ ] Non-admins show toggleable checkboxes

---

### 7. Permission Toggle Functionality
**Test as Admin:**

**Warranty Permission:**
- [ ] Find an editor or viewer user
- [ ] Check "Grant Access" for warranty permission
- [ ] User gains delete access to warranty/RMA features
- [ ] Audit log records the permission grant
- [ ] Uncheck to revoke access
- [ ] User loses delete access
- [ ] Audit log records the revocation

**Trials Permission:**
- [ ] Find an editor or viewer user
- [ ] Check "Grant Access" for trials permission
- [ ] User gains delete access to trials features
- [ ] Audit log records the change
- [ ] Revoke and verify access removed

**Procurement Permission:**
- [ ] Find an editor or viewer user
- [ ] Check "Grant Access" for procurement permission
- [ ] User gains access to Procurement Analytics
- [ ] User gains financial data access
- [ ] Sidebar shows "Management" section for them
- [ ] Audit log records the change
- [ ] Revoke and verify access removed

**Test as User after gaining permission:**
- [ ] Log in as editor with warranty permission
- [ ] Sidebar shows "Management" section
- [ ] Can delete warranty records
- [ ] Cannot delete trials (no trials permission)
- [ ] Cannot access procurement (no procurement permission)

---

### 8. Sidebar Navigation
**Test as each role:**

**Viewer:**
- [ ] No "Edge Box Map" link
- [ ] No "Management" section
- [ ] No "Admin" section
- [ ] No procurement link

**Editor:**
- [ ] Shows "Edge Box Map" link
- [ ] No "Management" section (unless has permission flag)
- [ ] No "Admin" section
- [ ] No procurement link

**Warranty Admin:**
- [ ] Shows "Edge Box Map" link
- [ ] Shows "Management" section (not "Admin")
- [ ] "Management" section contains:
  - [ ] "Warranty & RMA" link
  - [ ] "Audit Log" link
- [ ] No procurement link

**Trials Admin:**
- [ ] Shows "Edge Box Map" link
- [ ] Shows "Management" section (not "Admin")
- [ ] "Management" section contains:
  - [ ] "Try & Buy" link
  - [ ] "Audit Log" link
- [ ] No procurement link

**Procurement Admin:**
- [ ] Shows "Edge Box Map" link
- [ ] Shows "Management" section (not "Admin")
- [ ] "Management" section contains:
  - [ ] "Procurement Analytics" link
  - [ ] "Audit Log" link

**Admin:**
- [ ] Shows all main navigation links
- [ ] Shows full "Admin" section (not "Management")
- [ ] "Admin" section contains all admin features

**Editor with Warranty Permission:**
- [ ] Shows "Edge Box Map" link
- [ ] Shows "Management" section
- [ ] "Warranty & RMA" appears under "Management"

---

### 9. Audit Log Access
**Test as Viewer/Editor:**
- [ ] "Audit Log" link does NOT appear
- [ ] Direct access to `/admin/audit-log` blocked
- [ ] Permission denied page appears

**Test as Warranty Admin:**
- [ ] "Audit Log" link appears under "Management"
- [ ] Can access audit log page
- [ ] Sees only warranty/RMA related events:
  - [ ] warranty_created, warranty_updated, warranty_deleted
  - [ ] rma_created, rma_updated, rma_deleted
  - [ ] warranty_permission_toggled
- [ ] Does NOT see trial or procurement events
- [ ] Does NOT see user management events

**Test as Trials Admin:**
- [ ] "Audit Log" link appears under "Management"
- [ ] Sees only trial related events:
  - [ ] trial_created, trial_updated, trial_deleted
  - [ ] trials_permission_toggled
- [ ] Does NOT see warranty or procurement events

**Test as Procurement Admin:**
- [ ] "Audit Log" link appears under "Management"
- [ ] Sees only procurement related events:
  - [ ] procurement_permission_toggled
  - [ ] financial_permission_toggled (legacy)
- [ ] Does NOT see warranty or trial events

**Test as Admin:**
- [ ] "Audit Log" link appears under "Admin"
- [ ] Sees ALL audit log events
- [ ] No filtering applied

---

### 10. Edge Box Privacy Controls
**Test as Viewer/Editor/Sub-Admins:**
- [ ] Cannot see "show_on_map" checkbox in edit modal
- [ ] Cannot toggle map visibility

**Test as Admin:**
- [ ] "Admin Privacy Controls" section appears in edge box edit modal
- [ ] Can toggle "Show this device on the deployment map" checkbox
- [ ] Unchecking hides box from map immediately
- [ ] Re-checking shows box on map again
- [ ] Warning box explains privacy purpose

---

### 11. Permission Denied Page UX
**Test with various blocked features:**
- [ ] Page has clean design (no icons per requirements)
- [ ] Shows "Access Denied" heading in warning color
- [ ] Displays clear, specific error message
- [ ] Shows required permission if applicable
- [ ] Displays user's current role (with proper display names):
  - [ ] "Viewer" for viewer
  - [ ] "Editor" for editor
  - [ ] "Warranty Admin" for warranty_admin
  - [ ] "Trials Admin" for trials_admin
  - [ ] "Procurement Admin" for procurement_admin
  - [ ] "Administrator" for admin
- [ ] "Go to Dashboard" button works
- [ ] "Contact Admin" button shows alert message

---

### 12. API Endpoints Protection
**Test API protection:**

**Warranty Endpoints:**
- [ ] `/api/warranty/delete/{id}` - requires warranty_admin OR can_manage_warranty
- [ ] `/api/rma/delete/{id}` - requires warranty_admin OR can_manage_warranty
- [ ] Editor without permission gets 403
- [ ] Trials admin gets 403 (wrong domain)

**Trials Endpoints:**
- [ ] `/api/trials/delete/{id}` - requires trials_admin OR can_manage_trials
- [ ] Editor without permission gets 403
- [ ] Warranty admin gets 403 (wrong domain)

**Procurement Endpoints:**
- [ ] `/admin/procurement` - requires procurement_admin OR can_manage_procurement OR admin
- [ ] Editor without permission gets 403
- [ ] Warranty/trials admins get 403 (wrong domain)

**User Management Endpoints:**
- [ ] `/api/admin/users/*` - requires admin only
- [ ] `/api/admin/toggle-warranty/*` - requires admin only
- [ ] `/api/admin/toggle-trials/*` - requires admin only
- [ ] `/api/admin/toggle-procurement/*` - requires admin only
- [ ] Sub-admins get 403 for all user management endpoints

**Sites & Ownership Endpoints:**
- [ ] `GET /sites/` - all authenticated users can view
- [ ] `GET /sites/{id}` - all authenticated users can view
- [ ] `POST /api/sites` - requires admin OR can_manage_sites
- [ ] `PUT /api/sites/{id}` - requires admin OR can_manage_sites
- [ ] `DELETE /api/sites/{id}` - requires admin OR can_manage_sites
- [ ] `POST /api/assignments` - requires admin OR can_manage_sites
- [ ] `POST /api/assignments/{id}/return` - requires admin OR can_manage_sites
- [ ] `DELETE /api/assignments/{id}` - requires admin OR can_manage_sites
- [ ] `GET /api/sites/list` - all authenticated users (JSON lookup)
- [ ] Editor/viewer without can_manage_sites gets 403 on write endpoints

**Map Endpoints:**
- [ ] `/map/` - requires editor+ (including all sub-admins)
- [ ] `/map/data` - requires editor+ (including all sub-admins)
- [ ] Viewer gets 403

---

### 13. Role Display Names
**Test role display consistency:**
- [ ] User management page shows correct role names
- [ ] Permission denied pages show correct role names
- [ ] Sidebar role badges show correct names
- [ ] All display names match:
  - viewer → "Viewer"
  - editor → "Editor"
  - warranty_admin → "Warranty Admin"
  - trials_admin → "Trials Admin"
  - procurement_admin → "Procurement Admin"
  - admin → "Administrator"

---

## Critical Security Checks

### 1. Authorization Bypass Attempts
- [ ] Cannot access `/admin/*` routes as non-admin
- [ ] Cannot access `/map/*` as viewer
- [ ] Cannot modify `show_on_map` via API as non-admin
- [ ] Cannot toggle permissions via API as non-admin
- [ ] Cannot delete warranty records via API as non-warranty-admin
- [ ] Cannot delete trial records via API as non-trials-admin
- [ ] Sub-admins cannot access admin-only features

### 2. Domain Isolation
- [ ] Warranty admin cannot delete trials
- [ ] Trials admin cannot delete warranties
- [ ] Procurement admin cannot delete warranties or trials
- [ ] Permission flags only grant their specific domain access
- [ ] Audit log filtering properly isolates domain events

### 3. UI Leaks
- [ ] No hidden admin controls visible in HTML for non-admins
- [ ] No map data loaded for viewers (check network tab)
- [ ] No financial data exposed in API responses for unauthorized users
- [ ] Delete buttons only appear for authorized users
- [ ] Permission checkboxes only appear for admins

### 4. Session Handling
- [ ] Role changes require fresh login to take effect
- [ ] Permission flag changes require fresh login to take effect
- [ ] Deactivated users cannot access system
- [ ] Permission revocation is immediate (after re-login)

---

## Testing Notes

**How to test:**
1. Create test users via User Management page
2. Use incognito/private browsing windows for each user
3. Test both UI and direct URL access
4. Verify API responses in browser DevTools
5. Check audit log after permission changes
6. Test permission flags by toggling them for test users
7. Verify domain isolation by cross-testing sub-admins

**Expected Behaviors:**
- Blocked features return HTTP 403 with custom error page
- No "404 Not Found" for protected features (reveals feature existence)
- All error pages are branded and user-friendly
- Role badges and permission indicators are accurate
- Sub-admins see "Management" section, not "Admin"
- Permission flags grant same access as corresponding sub-admin role

---

## Pass/Fail Criteria

**Pass:** All checkboxes above are checked, no unauthorized access possible, proper domain isolation

**Fail:** Any unauthorized access, role confusion, or cross-domain access

---

## Known Issues / Notes

_Document any RBAC gaps or edge cases discovered during testing here._

### Testing Session: [Date]
**Tester:**
**Results:**
