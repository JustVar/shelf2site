(function () {
  'use strict';

  // ---- Permission tags shown on cards ----
  const PERM_TAGS = [
    { key: 'can_view_financial',     label: 'Finance' },
    { key: 'can_manage_warranty',    label: 'Warranty' },
    { key: 'can_manage_trials',      label: 'Trials' },
    { key: 'can_manage_procurement', label: 'Procurement' },
    { key: 'can_manage_sites',       label: 'Sites' },
    { key: 'can_manage_users',       label: 'User mgmt' },
    { key: 'can_manage_system',      label: 'Admin tools' },
    { key: 'can_view_audit_log',     label: 'Audit log' },
    { key: 'can_access_receiving',   label: 'Receiving' },
    { key: 'can_access_map',         label: 'Map' },
    { key: 'can_access_disposal',    label: 'Disposal' },
    { key: 'can_access_credentials', label: 'Credentials' },
    { key: 'can_manage_provisioning',label: 'Prov. mgmt' },
    { key: 'can_view_provisioning',  label: 'Prov. view' },
    { key: 'view_sensitive_customers', label: 'Sensitive cust.' },
  ];

  // ---- Permission groups + helper text for the drawer grid ----
  const PERMISSION_GROUPS = [
    {
      label: 'Domain admin',
      perms: [
        { key: 'can_view_financial',     name: 'Finance',     helper: 'View prices, receipts, financial fields' },
        { key: 'can_manage_warranty',    name: 'Warranty',    helper: 'Manage warranty claims and tracking' },
        { key: 'can_manage_trials',      name: 'Trials',      helper: 'Manage trial deployments' },
        { key: 'can_manage_procurement', name: 'Procurement', helper: 'Manage procurement records and vendors' },
        { key: 'can_manage_sites',       name: 'Sites',       helper: 'Manage customer sites and locations' },
      ],
    },
    {
      label: 'Page access',
      perms: [
        { key: 'can_access_receiving',   name: 'Receiving',   helper: 'Receive incoming shipments' },
        { key: 'can_access_map',         name: 'Map',         helper: 'View the asset map' },
        { key: 'can_access_disposal',    name: 'Disposal',    helper: 'Dispose of decommissioned items' },
        { key: 'can_access_credentials', name: 'Credentials', helper: 'View device credentials vault' },
      ],
    },
    {
      label: 'System',
      perms: [
        { key: 'can_manage_users',  name: 'User mgmt',   helper: 'Add, edit, disable users' },
        { key: 'can_manage_system', name: 'Admin tools', helper: 'Access system admin operations' },
        { key: 'can_view_audit_log',name: 'Audit log',   helper: 'View the audit log' },
      ],
    },
    {
      label: 'Provisioning',
      perms: [
        { key: 'can_manage_provisioning',   name: 'Prov. mgmt',     helper: 'Advance pipeline stages, edit provisioning workflows' },
        { key: 'can_view_provisioning',     name: 'Prov. view',     helper: 'View provisioning pipeline status (read-only)' },
        { key: 'view_sensitive_customers',  name: 'Sensitive cust.', helper: 'View provisioning records for sensitive customers' },
      ],
    },
  ];

  const ADMIN_TIER_ROLES = new Set(['admin', 'system_admin', 'justin_admin', 'ceo']);

  // ---- Helpers ----
  function initialsFor(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/).filter(p => /^[A-Za-z0-9]/.test(p));
    if (parts.length === 0) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function roleClass(role) {
    if (ADMIN_TIER_ROLES.has(role)) return 'admin';
    if (role === 'editor' || role === 'warranty_admin' || role === 'trials_admin' || role === 'procurement_admin') return 'editor';
    return 'viewer';
  }

  function roleDisplayLabel(role) {
    const map = {
      justin_admin: 'Super admin',
      system_admin: 'System admin',
      ceo: 'CEO',
      admin: 'Admin',
      warranty_admin: 'Warranty admin',
      trials_admin: 'Trials admin',
      procurement_admin: 'Procurement admin',
      editor: 'Editor',
      viewer: 'Viewer',
  map_kiosk: 'Map kiosk',
    };
    return map[role] || role;
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---- Card rendering ----
  function renderCards(users) {
    const grid = document.getElementById('users-grid');
    const empty = document.getElementById('users-empty');
    grid.innerHTML = '';

    if (users.length === 0) {
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';

    for (const u of users) {
      const card = document.createElement('div');
      card.className = 'user-card' + (u.is_active ? '' : ' user-card--inactive');
      card.dataset.userId = u.id;

      const rc = roleClass(u.role);

      const permTags = PERM_TAGS
        .filter(p => u[p.key] === 'grant')
        .map(p => `<span class="user-card__tag user-card__tag--perm">${p.label}</span>`)
        .join('');

      card.innerHTML = `
        <span class="user-card__status-dot user-card__status-dot--${u.is_active ? 'active' : 'inactive'}" title="${u.is_active ? 'Active' : 'Disabled'}"></span>
        <div class="user-card__top">
          <div class="user-card__avatar user-card__avatar--${rc}">${initialsFor(u.display_name || u.username)}</div>
          <div style="flex: 1; min-width: 0;">
            <div class="user-card__name">${escapeHtml(u.display_name || u.username)}</div>
            <div class="user-card__dept">${escapeHtml(u.department_name || '—')}</div>
          </div>
        </div>
        <div class="user-card__tags">
          <span class="user-card__tag user-card__tag--role-${rc}">${roleDisplayLabel(u.role)}</span>
          ${permTags}
        </div>
      `;

      card.addEventListener('click', () => openDrawerForEdit(u.id));
      grid.appendChild(card);
    }
  }

  // ---- Filtering ----
  function applyFilters() {
    const q = document.getElementById('users-search').value.trim().toLowerCase();
    const roleFilter = document.getElementById('users-role-filter').value;

    const filtered = USERS.filter(u => {
      if (q) {
        const haystack = (u.username + ' ' + (u.display_name || '') + ' ' + (u.email || '') + ' ' + (u.department_name || '')).toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (roleFilter) {
        if (roleFilter === 'admin-tier') {
          if (!ADMIN_TIER_ROLES.has(u.role)) return false;
        } else if (roleFilter !== u.role) {
          return false;
        }
      }
      return true;
    });
    renderCards(filtered);
  }

  // ---- Drawer state ----
  let currentEditUserId = null;  // null = add mode; number = edit mode
  // Map of {column_name: 'grant' | 'block'} reflecting current toggle positions.
  // Save reads from this; toggles write to it. Drawer only ever stores binary.
  let drawerPermState = {};
  // True when the drawer rendered toggle rows; false when it took the
  // admin-tier early-return path (showing the role-explanation note instead).
  // Used by saveDrawerEdit to skip the permission diff entirely in note mode,
  // avoiding a no-op POST built from undefined drawerPermState lookups.
  let drawerHasToggles = false;

  function openDrawerForEdit(userId) {
    currentEditUserId = userId;
    const u = USERS.find(x => x.id === userId);
    if (!u) return;
    document.getElementById('user-drawer-title').textContent = 'Edit user';
    document.getElementById('user-drawer-subtitle').textContent = `${u.display_name || u.username} · @${u.username}`;
    document.getElementById('user-drawer-disable').style.display = '';
    populateDrawerForEdit(u);
    showDrawer();
  }

  function openDrawerForAdd() {
    currentEditUserId = null;
    document.getElementById('user-drawer-title').textContent = 'Add user';
    document.getElementById('user-drawer-subtitle').textContent = 'New user';
    document.getElementById('user-drawer-disable').style.display = 'none';
    populateDrawerForAdd();
    showDrawer();
  }

  function showDrawer() {
    document.getElementById('user-drawer-overlay').classList.add('sx-drawer-overlay--open');
    document.getElementById('user-drawer').classList.add('sx-drawer--open');
    document.getElementById('user-drawer').setAttribute('aria-hidden', 'false');
  }

  function closeDrawer() {
    document.getElementById('user-drawer-overlay').classList.remove('sx-drawer-overlay--open');
    document.getElementById('user-drawer').classList.remove('sx-drawer--open');
    document.getElementById('user-drawer').setAttribute('aria-hidden', 'true');
    currentEditUserId = null;
  }

  // ---- Drawer field population ----
  function populateDrawerForEdit(u) {
    document.getElementById('ud-username').value = u.username || '';
    document.getElementById('ud-username').disabled = true;
    document.getElementById('ud-username-hint').style.display = '';
    document.getElementById('ud-display-name').value = u.display_name || '';
    document.getElementById('ud-email').value = u.email || '';
    document.getElementById('ud-role').value = u.role || 'viewer';
    document.getElementById('ud-department').value = u.department_id ?? '';
    document.getElementById('ud-slack-user-id').value = u.slack_user_id || '';
    document.getElementById('ud-slack-auto-match').checked = !!u.slack_auto_match;
    document.getElementById('ud-password-add-mode').style.display = 'none';
    document.getElementById('ud-password-edit-mode').style.display = '';
    document.getElementById('user-drawer-disable').textContent = u.is_active ? 'Disable user' : 'Enable user';
    renderPermissionGrid(u);
    clearDrawerError();
  }

  function populateDrawerForAdd() {
    document.getElementById('ud-username').value = '';
    document.getElementById('ud-username').disabled = false;
    document.getElementById('ud-username-hint').style.display = 'none';
    document.getElementById('ud-display-name').value = '';
    document.getElementById('ud-email').value = '';
    document.getElementById('ud-role').value = 'viewer';
    document.getElementById('ud-department').value = '';
    document.getElementById('ud-slack-user-id').value = '';
    document.getElementById('ud-slack-auto-match').checked = false;
    document.getElementById('ud-password-add-mode').style.display = '';
    document.getElementById('ud-password-edit-mode').style.display = 'none';
    document.getElementById('ud-password-input').value = '';
    // Render grid with synthetic empty user — all 'inherit' so toggles render off.
    const emptyUser = { department_id: null };
    for (const group of PERMISSION_GROUPS) {
      for (const perm of group.perms) {
        emptyUser[perm.key] = 'inherit';
      }
    }
    renderPermissionGrid(emptyUser);
    clearDrawerError();
  }

  function populateDepartmentOptions() {
    const sel = document.getElementById('ud-department');
    while (sel.options.length > 1) sel.remove(1);
    for (const d of DEPARTMENTS) {
      const opt = document.createElement('option');
      opt.value = d.id;
      opt.textContent = d.name;
      sel.appendChild(opt);
    }
  }

  // ---- Permission grid rendering and click-to-toggle ----
  function renderPermissionGrid(user) {
    const container = document.getElementById('ud-permissions-groups');
    container.innerHTML = '';
    drawerPermState = {};
    drawerHasToggles = false;

    // Admin-tier roles get all permissions via the role check in the property
    // layer. Column overrides are no-ops at read time — showing toggles is
    // misleading. Show an explanatory note instead. drawerPermState stays empty
    // and drawerHasToggles stays false so saveDrawerEdit skips the permission
    // diff loop entirely — no stale undefined values, no no-op POST.
    if (ADMIN_TIER_ROLES.has(user.role)) {
      const note = document.createElement('div');
      note.className = 'ud-perm-role-note';
      note.innerHTML = `
        <p><strong>${escapeHtml(roleDisplayLabel(user.role))}</strong> users have all permissions granted by their role.</p>
        <p>To change permissions, change the role above.</p>
      `;
      container.appendChild(note);
      return;
    }

    // Build dept lookup for inherit-resolution
    const dept = user.department_id != null
      ? DEPARTMENTS_FULL.find(d => d.id === user.department_id) || null
      : null;

    // Toggle grid: built exactly as before, but into a collapsed container.
    // Every row keeps its data-perm-key, toggle span, aria-pressed and click
    // handler, and drawerPermState is populated here whether or not the grid is
    // visible, so the save path (which reads drawerPermState) is unchanged.
    const grid = document.createElement('div');
    grid.className = 'ud-perm-grid';

    for (const group of PERMISSION_GROUPS) {
      const groupEl = document.createElement('div');
      groupEl.className = 'ud-perm-group';
      groupEl.innerHTML = `<div class="ud-perm-group-label">${escapeHtml(group.label)}</div>`;

      for (const perm of group.perms) {
        const userVal = user[perm.key];                                        // 'inherit' | 'grant' | 'block'
        const resolved = resolvePermissionState(userVal, dept, perm.key);     // true | false
        drawerPermState[perm.key] = resolved ? 'grant' : 'block';

        const row = document.createElement('div');
        row.className = 'ud-perm-row';
        row.dataset.permKey = perm.key;
        row.innerHTML = `
          <div class="ud-perm-text">
            <div class="ud-perm-name">${escapeHtml(perm.name)}</div>
            <div class="ud-perm-helper">${escapeHtml(perm.helper)}</div>
          </div>
          <span class="ud-perm-toggle ${resolved ? 'ud-perm-toggle--on' : ''}" aria-pressed="${resolved}"></span>
        `;
        row.addEventListener('click', () => togglePermissionRow(perm.key, row));
        groupEl.appendChild(row);
      }
      grid.appendChild(groupEl);
    }

    // Collapsed summary: chips derived from drawerPermState + PERMISSION_GROUPS.
    const grantedNames = [];
    let offCount = 0;
    for (const group of PERMISSION_GROUPS) {
      for (const perm of group.perms) {
        if (drawerPermState[perm.key] === 'grant') grantedNames.push(perm.name);
        else offCount += 1;
      }
    }
    const totalPerms = PERMISSION_GROUPS.reduce((n, g) => n + g.perms.length, 0);
    const chipsHtml = grantedNames.length
      ? grantedNames.map(n => `<span class="ud-perm-chip">${escapeHtml(n)}</span>`).join('')
      : `<span class="ud-perm-chip ud-perm-chip--muted">None granted</span>`;
    const offHtml = offCount ? `<span class="ud-perm-chip ud-perm-chip--muted">+${offCount} off</span>` : '';
    const summary = document.createElement('div');
    summary.className = 'ud-perm-summary';
    summary.innerHTML = `
      <div class="ud-perm-summary-meta">${grantedNames.length} of ${totalPerms} granted</div>
      <div class="ud-perm-chips">${chipsHtml}${offHtml}</div>
      <button type="button" class="ud-perm-edit-btn">Edit permissions</button>
    `;

    // Collapse control at the end of the grid.
    const collapseBtn = document.createElement('button');
    collapseBtn.type = 'button';
    collapseBtn.className = 'ud-perm-collapse-btn';
    collapseBtn.textContent = 'Collapse permissions';
    grid.appendChild(collapseBtn);

    container.appendChild(summary);
    container.appendChild(grid);

    // Progressive disclosure: presentation only; toggles + drawerPermState wired above.
    summary.querySelector('.ud-perm-edit-btn').addEventListener('click', () => {
      summary.style.display = 'none';
      grid.classList.add('ud-perm-grid--open');
    });
    collapseBtn.addEventListener('click', () => {
      grid.classList.remove('ud-perm-grid--open');
      summary.style.display = '';
    });

    drawerHasToggles = true;
  }

  function togglePermissionRow(permKey, rowEl) {
    const current = drawerPermState[permKey];
    const next = current === 'grant' ? 'block' : 'grant';
    drawerPermState[permKey] = next;

    const toggle = rowEl.querySelector('.ud-perm-toggle');
    toggle.classList.toggle('ud-perm-toggle--on', next === 'grant');
    toggle.setAttribute('aria-pressed', String(next === 'grant'));
  }

  function resolvePermissionState(userVal, dept, permKey) {
    // Mirrors the server's _resolve_perm logic for display purposes only.
    // Returns boolean: true = effectively granted, false = effectively blocked.
    if (userVal === 'grant') return true;
    if (userVal === 'block') return false;
    // 'inherit' — fall back to department
    if (!dept) return false;  // no department = no fallback = effectively blocked
    return dept[permKey] === 'grant';
  }

  // ---- Error display ----
  function showDrawerError(msg) {
    const el = document.getElementById('user-drawer-error');
    el.textContent = msg;
    el.classList.add('sx-drawer-error--visible');
  }
  function clearDrawerError() {
    const el = document.getElementById('user-drawer-error');
    el.textContent = '';
    el.classList.remove('sx-drawer-error--visible');
  }

  // ---- Lock acquisition / release ----
  async function acquireLock(userId) {
    const r = await fetch(`${BP}/api/admin/users/${userId}/lock`, { method: 'POST' });
    if (r.status === 409) {
      const data = await r.json();
      throw new Error(data.error + (data.held_by ? ` (${data.held_by})` : ''));
    }
    if (!r.ok) throw new Error('Could not acquire lock');
  }
  async function releaseLock(userId) {
    try {
      await fetch(`${BP}/api/admin/users/${userId}/unlock`, { method: 'POST' });
    } catch (e) { /* idempotent — ignore */ }
  }

  // ---- Save (edit mode) ----
  async function saveDrawerEdit() {
    const userId = currentEditUserId;
    if (userId == null) return;
    const original = USERS.find(u => u.id === userId);
    if (!original) return;

    const formState = {
      display_name: document.getElementById('ud-display-name').value.trim(),
      email: document.getElementById('ud-email').value.trim().toLowerCase() || null,
      role: document.getElementById('ud-role').value,
      department_id: document.getElementById('ud-department').value === '' ? null : parseInt(document.getElementById('ud-department').value, 10),
      slack_user_id: document.getElementById('ud-slack-user-id').value.trim() || null,
      slack_auto_match: document.getElementById('ud-slack-auto-match').checked,
    };

    if (!formState.display_name) {
      showDrawerError('Display name cannot be empty.');
      return;
    }

    const profileDiff = {};
    if (formState.display_name !== (original.display_name || '')) profileDiff.display_name = formState.display_name;
    if ((formState.email || null) !== (original.email || null)) profileDiff.email = formState.email;
    if ((formState.slack_user_id || null) !== (original.slack_user_id || null)) profileDiff.slack_user_id = formState.slack_user_id;
    if (formState.slack_auto_match !== !!original.slack_auto_match) profileDiff.slack_auto_match = formState.slack_auto_match;

    const roleChanged = formState.role !== original.role;
    const deptChanged = (formState.department_id ?? null) !== (original.department_id ?? null);

    // Permission diff: only compute when the drawer was actually showing toggles.
    // For admin-tier users renderPermissionGrid took the early-return and showed
    // a role-explanation note instead — drawerPermState is empty, drawerHasToggles
    // is false, and iterating PERMISSION_GROUPS would produce stale {key: undefined}
    // entries that JSON.stringify drops to {} but still fire a no-op POST.
    //
    // The flag (not formState.role) is intentional: it correctly handles the
    // edit-time edge case "role just changed FROM admin TO non-admin" — drawer
    // was in note mode, so no toggle states are meaningful.
    const permDiff = {};
    if (drawerHasToggles) {
      const dept = (formState.department_id != null)
        ? DEPARTMENTS_FULL.find(d => d.id === formState.department_id) || null
        : null;
      for (const group of PERMISSION_GROUPS) {
        for (const perm of group.perms) {
          const drawerVal = drawerPermState[perm.key];           // 'grant' | 'block'
          const resolvedOriginal = resolvePermissionState(original[perm.key], dept, perm.key);
          const wantOriginal = resolvedOriginal ? 'grant' : 'block';
          if (drawerVal !== wantOriginal) {
            permDiff[perm.key] = drawerVal;
          }
        }
      }
    }

    const hasChanges = Object.keys(profileDiff).length > 0
      || roleChanged || deptChanged
      || Object.keys(permDiff).length > 0;
    if (!hasChanges) {
      closeDrawer();
      return;
    }

    const saveBtn = document.getElementById('user-drawer-save');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';

    try {
      await acquireLock(userId);
    } catch (e) {
      showDrawerError(e.message);
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
      return;
    }

    const calls = [];
    if (Object.keys(profileDiff).length > 0) {
      calls.push(fetch(`${BP}/api/admin/users/${userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profileDiff),
      }).then(r => r.json().then(j => ({ kind: 'profile', ok: r.ok, data: j }))));
    }
    if (roleChanged) {
      calls.push(fetch(`${BP}/api/admin/change-role/${userId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: formState.role }),
      }).then(r => r.json().then(j => ({ kind: 'role', ok: r.ok, data: j }))));
    }
    if (deptChanged) {
      calls.push(fetch(`${BP}/api/admin/users/${userId}/department`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ department_id: formState.department_id }),
      }).then(r => r.json().then(j => ({ kind: 'department', ok: r.ok, data: j }))));
    }
    if (Object.keys(permDiff).length > 0) {
      calls.push(fetch(`${BP}/api/admin/users/${userId}/permissions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(permDiff),
      }).then(r => r.json().then(j => ({ kind: 'permissions', ok: r.ok, data: j }))));
    }

    try {
      const results = await Promise.all(calls);
      const failures = results.filter(r => !r.ok);
      if (failures.length > 0) {
        showDrawerError('Some changes failed: ' + failures.map(f => `${f.kind} (${f.data.error || 'unknown'})`).join(', '));
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
        return;
      }
      await releaseLock(userId);
      window.location.reload();
    } catch (e) {
      await releaseLock(userId);
      showDrawerError('Network error: ' + e.message);
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }
  }

  // ---- Save (add mode) ----
  async function saveDrawerAdd() {
    const username = document.getElementById('ud-username').value.trim();
    const display_name = document.getElementById('ud-display-name').value.trim();
    const password = document.getElementById('ud-password-input').value;
    const role = document.getElementById('ud-role').value;

    if (!username || !display_name || !password) {
      showDrawerError('Username, display name, and password are required.');
      return;
    }
    if (password.length < 12 || !/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/[0-9]/.test(password)) {
      showDrawerError('Password must be ≥12 characters and include upper, lower, and digit.');
      return;
    }

    const saveBtn = document.getElementById('user-drawer-save');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Creating…';

    const fd = new FormData();
    fd.append('username', username);
    fd.append('display_name', display_name);
    fd.append('password', password);
    fd.append('role', role);

    try {
      const r = await fetch(`${BP}/admin/users/add`, { method: 'POST', body: fd });
      const j = await r.json();
      if (!r.ok) {
        showDrawerError(j.error || 'Failed to create user');
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
        return;
      }
      const newUserId = j.id;
      const followUpCalls = [];
      const email = document.getElementById('ud-email').value.trim().toLowerCase();
      const slackId = document.getElementById('ud-slack-user-id').value.trim();
      const slackAuto = document.getElementById('ud-slack-auto-match').checked;
      const profileBody = {};
      if (email) profileBody.email = email;
      if (slackId) profileBody.slack_user_id = slackId;
      if (slackAuto) profileBody.slack_auto_match = slackAuto;
      if (Object.keys(profileBody).length > 0) {
        followUpCalls.push(fetch(`${BP}/api/admin/users/${newUserId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(profileBody),
        }));
      }
      const deptIdRaw = document.getElementById('ud-department').value;
      const deptIdNum = deptIdRaw ? parseInt(deptIdRaw, 10) : null;
      if (deptIdNum != null) {
        followUpCalls.push(fetch(`${BP}/api/admin/users/${newUserId}/department`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ department_id: deptIdNum }),
        }));
      }
      // Send permission overrides only where the drawer toggle differs from the
      // chosen department's default. Skipped keys stay 'inherit' on the user row.
      const newDept = deptIdNum != null
        ? DEPARTMENTS_FULL.find(d => d.id === deptIdNum) || null
        : null;
      const initialPerms = {};
      for (const group of PERMISSION_GROUPS) {
        for (const perm of group.perms) {
          const wantGrant = drawerPermState[perm.key] === 'grant';
          const deptDefault = (newDept && newDept[perm.key] === 'grant') || false;
          if (wantGrant !== deptDefault) {
            initialPerms[perm.key] = wantGrant ? 'grant' : 'block';
          }
        }
      }
      if (Object.keys(initialPerms).length > 0) {
        followUpCalls.push(fetch(`${BP}/api/admin/users/${newUserId}/permissions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(initialPerms),
        }));
      }
      if (followUpCalls.length > 0) await Promise.all(followUpCalls);
      window.location.reload();
    } catch (e) {
      showDrawerError('Network error: ' + e.message);
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }
  }

  // ---- Disable / enable ----
  async function toggleDrawerDisable() {
    if (currentEditUserId == null) return;
    const u = USERS.find(x => x.id === currentEditUserId);
    if (!u) return;
    const action = u.is_active ? 'Disable' : 'Enable';
    if (!confirm(`${action} user '${u.username}'?`)) return;

    try {
      const r = await fetch(`${BP}/admin/users/${u.id}/toggle`, { method: 'POST' });
      if (!r.ok) {
        showDrawerError('Could not toggle user state');
        return;
      }
      window.location.reload();
    } catch (e) {
      showDrawerError('Network error: ' + e.message);
    }
  }

  // ---- Reset password ----
  async function resetDrawerPassword() {
    if (currentEditUserId == null) return;
    const u = USERS.find(x => x.id === currentEditUserId);
    if (!u) return;
    if (!confirm(`Reset password for '${u.username}'? They will be required to change it on next login.`)) return;

    try {
      const r = await fetch(`${BP}/api/admin/reset-password/${u.id}`, { method: 'POST' });
      const j = await r.json();
      if (!r.ok) {
        showDrawerError(j.error || 'Could not reset password');
        return;
      }
      window.prompt(`Temp password for '${u.username}' (copy this — it won't be shown again):`, j.temp_password);
    } catch (e) {
      showDrawerError('Network error: ' + e.message);
    }
  }

  // ---- Counts ----
  function updateCounts() {
    document.getElementById('users-count-active').textContent = USERS.filter(u => u.is_active).length;
    document.getElementById('users-count-inactive').textContent = USERS.filter(u => !u.is_active).length;
  }

  // ---- Init (boost-aware, idempotent) ----
  // hx-boost swaps the <body> without a full reload, so DOMContentLoaded never re-fires and the
  // render/count build never ran on boosted navigation. Run the per-page init on the initial load
  // AND after every htmx swap. The idempotency flag lives on #users-grid, which is fresh on every
  // boost swap: a re-executed script or a full load (where both paths can fire) is deduped, while a
  // newly swapped-in page always re-initializes. var USERS/DEPARTMENTS/DEPARTMENTS_FULL are
  // re-injected by the inline template script before htmx:load fires, so they are in scope here.
  function initUsersPage() {
    const grid = document.getElementById('users-grid');
    if (!grid) return;                          // not the users page (htmx:load fires for any swap)
    if (grid.dataset.usersInit === '1') return; // already initialized this DOM instance
    if (typeof USERS === 'undefined') {
      console.error('USERS global not defined — admin_users.html template did not inject it.');
      return;
    }
    grid.dataset.usersInit = '1';
    updateCounts();
    renderCards(USERS);
    populateDepartmentOptions();

    document.getElementById('users-search').addEventListener('input', applyFilters);
    document.getElementById('users-role-filter').addEventListener('change', applyFilters);
    document.getElementById('users-add-btn').addEventListener('click', openDrawerForAdd);

    document.getElementById('user-drawer-close').addEventListener('click', closeDrawer);
    document.getElementById('user-drawer-overlay').addEventListener('click', closeDrawer);
    document.getElementById('user-drawer-cancel').addEventListener('click', closeDrawer);

    document.getElementById('user-drawer-save').addEventListener('click', () => {
      if (currentEditUserId == null) saveDrawerAdd();
      else saveDrawerEdit();
    });
    document.getElementById('user-drawer-disable').addEventListener('click', toggleDrawerDisable);
    document.getElementById('ud-reset-password-btn').addEventListener('click', resetDrawerPassword);

    // Cross-page handoff: if URL has ?user_id=N, auto-open that user's drawer.
    // Used by the department drawer's member-chip click-through (admin-departments-v2.js).
    const params = new URLSearchParams(window.location.search);
    const handoffUserId = params.get('user_id');
    if (handoffUserId) {
      const uid = parseInt(handoffUserId, 10);
      if (!isNaN(uid) && USERS.find(u => u.id === uid)) {
        history.replaceState({}, '', window.location.pathname);
        openDrawerForEdit(uid);
      }
    }
  }

  // Document-level listeners must bind exactly once: `document` is NOT replaced by a boost swap, so
  // re-running init would stack duplicates. Guard on window so it survives boosts and any
  // re-execution of this script.
  function bindUsersGlobalOnce() {
    if (window.__adminUsersGlobalBound) return;
    window.__adminUsersGlobalBound = true;

    // Esc closes the drawer (null-guarded: the drawer only exists on the users page).
    document.addEventListener('keydown', (ev) => {
      const drawer = document.getElementById('user-drawer');
      if (ev.key === 'Escape' && drawer && drawer.classList.contains('sx-drawer--open')) {
        closeDrawer();
      }
    });

    // Re-init when htmx swaps in new content (hx-boost navigation to the users page).
    document.addEventListener('htmx:load', initUsersPage);
  }

  bindUsersGlobalOnce();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUsersPage);
  } else {
    initUsersPage();
  }
})();
