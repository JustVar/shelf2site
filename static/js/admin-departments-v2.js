(function () {
  'use strict';

  // 14 department permissions in display order — drives the heatmap grid on cards.
  // 2 cols × 7 rows fills exactly 14 cells with no empty slots.
  const DEPT_PERM_LABELS = [
    { key: 'can_view_receipts',      name: 'Receipts' },
    { key: 'can_manage_warranty',    name: 'Warranty' },
    { key: 'can_manage_trials',      name: 'Trials' },
    { key: 'can_manage_procurement', name: 'Procurement' },
    { key: 'can_manage_sites',       name: 'Sites' },
    { key: 'can_manage_users',       name: 'User mgmt' },
    { key: 'can_manage_system',      name: 'Admin tools' },
    { key: 'can_view_audit_log',     name: 'Audit log' },
    { key: 'can_access_receiving',   name: 'Receiving' },
    { key: 'can_access_map',         name: 'Map' },
    { key: 'can_access_disposal',    name: 'Disposal' },
    { key: 'can_access_credentials', name: 'Credentials' },
    { key: 'can_manage_provisioning',name: 'Prov. mgmt' },
    { key: 'can_view_provisioning',  name: 'Prov. view' },
  ];

  // Drawer's permission grid groups — mirrors PERMISSION_GROUPS in admin-users-v2.js
  // but excludes view_sensitive_customers (no department equivalent).
  const DEPT_PERMISSION_GROUPS = [
    {
      label: 'Domain admin',
      perms: [
        { key: 'can_view_receipts',      name: 'Receipts',    helper: 'View uploaded receipts and manage vendor profiles' },
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
        { key: 'can_manage_users',   name: 'User mgmt',   helper: 'Add, edit, disable users' },
        { key: 'can_manage_system',  name: 'Admin tools', helper: 'Access system admin operations' },
        { key: 'can_view_audit_log', name: 'Audit log',   helper: 'View the audit log' },
      ],
    },
    {
      label: 'Provisioning',
      perms: [
        { key: 'can_manage_provisioning', name: 'Prov. mgmt', helper: 'Advance pipeline stages, edit provisioning workflows' },
        { key: 'can_view_provisioning',   name: 'Prov. view', helper: 'View provisioning pipeline status (read-only)' },
      ],
    },
  ];

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---- Card rendering ----
  function renderCards(depts) {
    const grid = document.getElementById('depts-grid');
    const empty = document.getElementById('depts-empty');
    grid.innerHTML = '';

    if (depts.length === 0) {
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';

    for (const d of depts) {
      const card = document.createElement('div');
      card.className = 'dept-card';
      card.dataset.deptId = d.id;

      const heatCells = DEPT_PERM_LABELS.map(perm => {
        const state = d[perm.key];   // 'grant' | 'block'
        const cls = state === 'grant' ? 'dept-card__heat-pill--grant' : 'dept-card__heat-pill--block';
        return `<span class="dept-card__heat-pill ${cls}" title="${escapeHtml(perm.name)}">${escapeHtml(perm.name)}</span>`;
      }).join('');

      const memberCount = (d.members || []).length;
      const memberLabel = memberCount === 1 ? '1 member' : `${memberCount} members`;
      const desc = d.description ? escapeHtml(d.description) : '<span style="color:var(--sx-border);">No description</span>';

      card.innerHTML = `
        <div class="dept-card__head">
          <span class="dept-card__name">${escapeHtml(d.name)}</span>
          <span class="dept-card__meta">${memberLabel}</span>
        </div>
        <div class="dept-card__desc">${desc}</div>
        <div class="dept-card__heat">${heatCells}</div>
      `;
      card.addEventListener('click', () => openDrawerForEdit(d.id));
      grid.appendChild(card);
    }
  }

  // ---- Filtering ----
  function applyFilters() {
    const q = document.getElementById('depts-search').value.trim().toLowerCase();
    const filtered = DEPARTMENTS_PAYLOAD.filter(d => {
      if (!q) return true;
      const haystack = ((d.name || '') + ' ' + (d.description || '')).toLowerCase();
      return haystack.includes(q);
    });
    renderCards(filtered);
  }

  // ---- Drawer state ----
  let currentEditDeptId = null;  // null = add mode; number = edit mode
  // Map of {column_name: 'grant' | 'block'} reflecting current toggle positions.
  let drawerPermState = {};

  function openDrawerForEdit(deptId) {
    currentEditDeptId = deptId;
    const d = DEPARTMENTS_PAYLOAD.find(x => x.id === deptId);
    if (!d) return;
    document.getElementById('dept-drawer-title').textContent = 'Edit department';
    const memberCount = d.members.length;
    document.getElementById('dept-drawer-subtitle').textContent = `${d.name} · ${memberCount} member${memberCount === 1 ? '' : 's'}`;
    document.getElementById('dept-drawer-delete').style.display = '';
    populateDrawerForEdit(d);
    showDrawer();
  }

  function openDrawerForAdd() {
    currentEditDeptId = null;
    document.getElementById('dept-drawer-title').textContent = 'Add department';
    document.getElementById('dept-drawer-subtitle').textContent = 'New department';
    document.getElementById('dept-drawer-delete').style.display = 'none';
    populateDrawerForAdd();
    showDrawer();
  }

  function showDrawer() {
    document.getElementById('dept-drawer-overlay').classList.add('sx-drawer-overlay--open');
    document.getElementById('dept-drawer').classList.add('sx-drawer--open');
    document.getElementById('dept-drawer').setAttribute('aria-hidden', 'false');
    document.getElementById('dept-drawer').inert = false;  // closed drawers take no focus
  }

  function closeDrawer() {
    document.getElementById('dept-drawer-overlay').classList.remove('sx-drawer-overlay--open');
    document.getElementById('dept-drawer').classList.remove('sx-drawer--open');
    document.getElementById('dept-drawer').setAttribute('aria-hidden', 'true');
    document.getElementById('dept-drawer').inert = true;
    currentEditDeptId = null;
  }

  // ---- Drawer body population ----
  function populateDrawerForEdit(d) {
    document.getElementById('dd-name').value = d.name || '';
    document.getElementById('dd-description').value = d.description || '';
    document.getElementById('dept-drawer-delete').textContent = 'Delete department';
    document.getElementById('dd-members-section').style.display = '';
    renderPermissionGrid(d);
    renderMembersList(d);
    clearDrawerError();
  }

  function populateDrawerForAdd() {
    document.getElementById('dd-name').value = '';
    document.getElementById('dd-description').value = '';
    // Synthetic empty dept — all perms default 'block'
    const emptyDept = {};
    for (const group of DEPT_PERMISSION_GROUPS) {
      for (const perm of group.perms) {
        emptyDept[perm.key] = 'block';
      }
    }
    renderPermissionGrid(emptyDept);
    document.getElementById('dd-members-section').style.display = 'none';
    clearDrawerError();
  }

  // ---- Permission grid rendering and click-to-toggle ----
  function renderPermissionGrid(dept) {
    const container = document.getElementById('dd-permissions-groups');
    container.innerHTML = '';
    drawerPermState = {};

    // Toggle grid: built exactly as before, but into a collapsed container.
    // Every row keeps its data-perm-key, toggle span, aria-pressed and click
    // handler, and drawerPermState is populated here whether or not the grid is
    // visible, so the save path (which reads drawerPermState) is unchanged.
    const grid = document.createElement('div');
    grid.className = 'ud-perm-grid';

    for (const group of DEPT_PERMISSION_GROUPS) {
      const groupEl = document.createElement('div');
      groupEl.className = 'ud-perm-group';
      groupEl.innerHTML = `<div class="ud-perm-group-label">${escapeHtml(group.label)}</div>`;

      for (const perm of group.perms) {
        const state = dept[perm.key] || 'block';     // 'grant' or 'block'
        drawerPermState[perm.key] = state;

        const row = document.createElement('div');
        row.className = 'ud-perm-row';
        row.dataset.permKey = perm.key;
        row.innerHTML = `
          <div class="ud-perm-text">
            <div class="ud-perm-name">${escapeHtml(perm.name)}</div>
            <div class="ud-perm-helper">${escapeHtml(perm.helper)}</div>
          </div>
          <span class="ud-perm-toggle ${state === 'grant' ? 'ud-perm-toggle--on' : ''}" aria-pressed="${state === 'grant'}"></span>
        `;
        row.addEventListener('click', () => togglePermissionRow(perm.key, row));
        groupEl.appendChild(row);
      }
      grid.appendChild(groupEl);
    }

    // Collapsed summary: chips derived from drawerPermState + DEPT_PERMISSION_GROUPS.
    const grantedNames = [];
    let offCount = 0;
    for (const group of DEPT_PERMISSION_GROUPS) {
      for (const perm of group.perms) {
        if (drawerPermState[perm.key] === 'grant') grantedNames.push(perm.name);
        else offCount += 1;
      }
    }
    const totalPerms = DEPT_PERMISSION_GROUPS.reduce((n, g) => n + g.perms.length, 0);
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
  }

  function togglePermissionRow(permKey, rowEl) {
    const current = drawerPermState[permKey];
    const next = current === 'grant' ? 'block' : 'grant';
    drawerPermState[permKey] = next;
    const toggle = rowEl.querySelector('.ud-perm-toggle');
    toggle.classList.toggle('ud-perm-toggle--on', next === 'grant');
    toggle.setAttribute('aria-pressed', String(next === 'grant'));
  }

  // ---- Members list ----
  function renderMembersList(dept) {
    const container = document.getElementById('dd-members-list');
    const members = dept.members || [];
    if (members.length === 0) {
      container.innerHTML = '<div class="dd-members-empty">No members in this department.</div>';
      return;
    }
    const chips = members.map(m => `
      <span class="dd-members-chip" data-user-id="${m.id}" title="Edit ${escapeHtml(m.display_name || m.username)}">
        ${escapeHtml(m.display_name || m.username)}
        <span class="dd-members-chip__role">${escapeHtml(m.role)}</span>
      </span>
    `).join('');
    container.innerHTML = `<div class="dd-members-chips">${chips}</div>`;

    // Wire click-through — navigate to /admin/users?user_id=N where the page auto-opens that user's drawer.
    container.querySelectorAll('.dd-members-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const uid = chip.dataset.userId;
        window.location.href = `${BP}/admin/users?user_id=${uid}`;
      });
    });
  }

  // ---- Error display ----
  function showDrawerError(msg) {
    const el = document.getElementById('dept-drawer-error');
    el.textContent = msg;
    el.classList.add('sx-drawer-error--visible');
  }
  function clearDrawerError() {
    const el = document.getElementById('dept-drawer-error');
    el.textContent = '';
    el.classList.remove('sx-drawer-error--visible');
  }

  // ---- Lock acquisition / release ----
  async function acquireLock(deptId) {
    const r = await fetch(`${BP}/api/admin/departments/${deptId}/lock`, { method: 'POST' });
    if (r.status === 409) {
      const data = await r.json();
      throw new Error(data.error + (data.held_by ? ` (${data.held_by})` : ''));
    }
    if (!r.ok) throw new Error('Could not acquire lock');
  }
  async function releaseLock(deptId) {
    try {
      await fetch(`${BP}/api/admin/departments/${deptId}/unlock`, { method: 'POST' });
    } catch (e) { /* idempotent — ignore */ }
  }

  // ---- Save (edit mode) ----
  async function saveDrawerEdit() {
    const deptId = currentEditDeptId;
    if (deptId == null) return;
    const original = DEPARTMENTS_PAYLOAD.find(d => d.id === deptId);
    if (!original) return;

    const name = document.getElementById('dd-name').value.trim();
    const description = document.getElementById('dd-description').value.trim();

    if (!name) {
      showDrawerError('Name cannot be empty.');
      return;
    }

    const identityDiff = {};
    if (name !== (original.name || '')) identityDiff.name = name;
    if (description !== (original.description || '')) identityDiff.description = description;

    const permDiff = {};
    for (const group of DEPT_PERMISSION_GROUPS) {
      for (const perm of group.perms) {
        const drawerVal = drawerPermState[perm.key];
        const origVal = original[perm.key];
        if (drawerVal !== origVal) permDiff[perm.key] = drawerVal;
      }
    }

    const hasChanges = Object.keys(identityDiff).length > 0 || Object.keys(permDiff).length > 0;
    if (!hasChanges) {
      closeDrawer();
      return;
    }

    const saveBtn = document.getElementById('dept-drawer-save');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';

    try {
      await acquireLock(deptId);
    } catch (e) {
      showDrawerError(e.message);
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
      return;
    }

    const calls = [];
    if (Object.keys(identityDiff).length > 0) {
      calls.push(fetch(`${BP}/api/admin/departments/${deptId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(identityDiff),
      }).then(r => r.json().then(j => ({ kind: 'identity', ok: r.ok, data: j }))));
    }
    if (Object.keys(permDiff).length > 0) {
      calls.push(fetch(`${BP}/api/admin/departments/${deptId}/permissions`, {
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
        await releaseLock(deptId);
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
        return;
      }
      await releaseLock(deptId);
      window.location.reload();
    } catch (e) {
      await releaseLock(deptId);
      showDrawerError('Network error: ' + e.message);
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }
  }

  // ---- Save (add mode) ----
  async function saveDrawerAdd() {
    const name = document.getElementById('dd-name').value.trim();
    const description = document.getElementById('dd-description').value.trim();

    if (!name) {
      showDrawerError('Name is required.');
      return;
    }

    const saveBtn = document.getElementById('dept-drawer-save');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Creating…';

    try {
      const r = await fetch(`${BP}/admin/departments/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description }),
      });
      const j = await r.json();
      if (!r.ok) {
        showDrawerError(j.error || 'Failed to create department');
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
        return;
      }
      const newDeptId = j.department_id || j.id;
      const initialPerms = {};
      for (const group of DEPT_PERMISSION_GROUPS) {
        for (const perm of group.perms) {
          if (drawerPermState[perm.key] === 'grant') {
            initialPerms[perm.key] = 'grant';
          }
        }
      }
      if (Object.keys(initialPerms).length > 0 && newDeptId) {
        await fetch(`${BP}/api/admin/departments/${newDeptId}/permissions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(initialPerms),
        });
      }
      window.location.reload();
    } catch (e) {
      showDrawerError('Network error: ' + e.message);
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }
  }

  // ---- Delete ----
  async function deleteDrawerDepartment() {
    if (currentEditDeptId == null) return;
    const d = DEPARTMENTS_PAYLOAD.find(x => x.id === currentEditDeptId);
    if (!d) return;
    const memberCount = (d.members || []).length;
    const warn = memberCount > 0
      ? `Delete department "${d.name}"? Its ${memberCount} member${memberCount === 1 ? '' : 's'} will become unassigned.`
      : `Delete department "${d.name}"?`;
    if (!(await SxDialog.confirm({ title: 'Delete department', message: warn, okLabel: 'Delete', danger: true }))) return;

    try {
      const r = await fetch(`${BP}/api/admin/departments/${d.id}`, { method: 'DELETE' });
      if (!r.ok) {
        const j = await r.json();
        showDrawerError(j.error || 'Could not delete department');
        return;
      }
      window.location.reload();
    } catch (e) {
      showDrawerError('Network error: ' + e.message);
    }
  }

  function updateCounts() {
    document.getElementById('depts-count').textContent = DEPARTMENTS_PAYLOAD.length;
  }

  // ---- Init (boost-aware, idempotent): mirrors admin-users-v2.js ----
  function initDeptsPage() {
    const grid = document.getElementById('depts-grid');
    if (!grid) return;
    if (grid.dataset.deptsInit === '1') return;
    if (typeof DEPARTMENTS_PAYLOAD === 'undefined') {
      console.error('DEPARTMENTS_PAYLOAD global not defined - admin_departments.html template did not inject it.');
      return;
    }
    grid.dataset.deptsInit = '1';
    updateCounts();
    renderCards(DEPARTMENTS_PAYLOAD);

    document.getElementById('depts-search').addEventListener('input', applyFilters);
    document.getElementById('depts-add-btn').addEventListener('click', openDrawerForAdd);
    document.getElementById('dept-drawer-close').addEventListener('click', closeDrawer);
    document.getElementById('dept-drawer-overlay').addEventListener('click', closeDrawer);
    document.getElementById('dept-drawer-cancel').addEventListener('click', closeDrawer);
    document.getElementById('dept-drawer-save').addEventListener('click', () => {
      if (currentEditDeptId == null) saveDrawerAdd();
      else saveDrawerEdit();
    });
    document.getElementById('dept-drawer-delete').addEventListener('click', deleteDrawerDepartment);
  }

  // Document-level listeners bind exactly once: document is NOT replaced by a boost swap.
  function bindDeptsGlobalOnce() {
    if (window.__adminDeptsGlobalBound) return;
    window.__adminDeptsGlobalBound = true;
    document.addEventListener('keydown', (ev) => {
      const drawer = document.getElementById('dept-drawer');
      if (ev.key === 'Escape' && drawer && drawer.classList.contains('sx-drawer--open')) {
        closeDrawer();
      }
    });
    document.addEventListener('htmx:load', initDeptsPage);
  }

  bindDeptsGlobalOnce();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDeptsPage);
  } else {
    initDeptsPage();
  }
})();
