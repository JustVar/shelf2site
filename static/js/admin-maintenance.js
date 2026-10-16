// @ts-check
/* Admin — Service Maintenance */

const minutesSelect = document.getElementById('minutes-select');
if (minutesSelect) {
    minutesSelect.addEventListener('change', function() {
        const customEl = document.getElementById('custom-minutes');
        if (customEl) customEl.style.display =
            /** @type {HTMLSelectElement} */ (this).value === 'custom' ? 'inline-block' : 'none';
    });
}

/** @returns {number | null} */
function getMinutes() {
    const sel = /** @type {HTMLSelectElement | null} */ (document.getElementById('minutes-select'));
    if (!sel || !sel.value) return null;
    if (sel.value === 'custom') {
        const custom = /** @type {HTMLInputElement | null} */ (document.getElementById('custom-minutes'));
        const v = custom ? parseInt(custom.value) : NaN;
        return isNaN(v) || v < 1 ? null : v;
    }
    return parseInt(sel.value);
}

/**
 * @param {string} elId
 * @param {string} msg
 * @param {boolean} ok
 */
function setResult(elId, msg, ok) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? 'var(--success, #27ae60)' : 'var(--danger, #e74c3c)';
}

async function announce() {
    const msgInput = /** @type {HTMLInputElement | null} */ (document.getElementById('msg-input'));
    const message = msgInput ? msgInput.value.trim() : '';
    if (!message) { setResult('announce-result', 'Message is required.', false); return; }
    const minutes = getMinutes();
    try {
        const resp = await fetch(`${BP}/api/maintenance/announce`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message, minutes}),
        });
        const data = await resp.json();
        if (resp.ok) {
            setResult('announce-result', '✓ Announced — banner is now live for all users.', true);
            setTimeout(() => location.reload(), 1000);
        } else {
            setResult('announce-result', `✗ ${data.error}`, false);
        }
    } catch (err) {
        setResult('announce-result', `Error: ${/** @type {Error} */ (err).message}`, false);
    }
}

async function clearAnnouncement() {
    if (!(await SxDialog.confirm({ title: 'Clear announcement', message: 'Clear the maintenance announcement? The banner will disappear for all users.', okLabel: 'Clear' }))) return;
    try {
        const resp = await fetch(`${BP}/api/maintenance/clear`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            setResult('announce-result', '✓ Cleared — banner removed for all users.', true);
            setTimeout(() => location.reload(), 800);
        } else {
            setResult('announce-result', `✗ ${data.error || 'Failed'}`, false);
        }
    } catch (err) {
        setResult('announce-result', `Error: ${/** @type {Error} */ (err).message}`, false);
    }
}

async function forceReload() {
    if (!(await SxDialog.confirm({ title: 'Force reload', message: 'This will immediately reload the page for all active users. Proceed?', okLabel: 'Reload all users', danger: true }))) return;
    try {
        const resp = await fetch(`${BP}/api/maintenance/force-reload`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            setResult('reload-result', '✓ Reload broadcast sent to all connected clients.', true);
        } else {
            setResult('reload-result', `✗ ${data.error || 'Failed'}`, false);
        }
    } catch (err) {
        setResult('reload-result', `Error: ${/** @type {Error} */ (err).message}`, false);
    }
}

// ---------------------------------------------------------------------------
// Active users panel
// ---------------------------------------------------------------------------

/** @type {Set<string>} */
const ADMIN_ROLES = new Set(['super_admin', 'system_admin', 'admin', 'ceo']);

/** @type {Record<string, string>} */
const ROLE_LABELS = {
    super_admin: 'Super Admin', system_admin: 'System Admin', ceo: 'CEO',
    admin: 'Administrator', warranty_admin: 'Warranty Admin',
    trials_admin: 'Trials Admin', procurement_admin: 'Procurement Admin',
    editor: 'Editor', viewer: 'Viewer',
};

/** @param {string} s @returns {string} */
function escHtml(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/**
 * @param {{ count: number, sse_clients: number, users: Array<{ display_name?: string, username: string, role: string, minutes_ago: number }> }} data
 */
function renderActiveUsers(data) {
    const safeBadge = document.getElementById('safe-badge');
    const el = document.getElementById('active-users-content');
    const sseEl = document.getElementById('session-count');
    if (sseEl) sseEl.textContent = String(data.sse_clients);

    if (!el || !safeBadge) return;

    if (data.count === 0) {
        safeBadge.style.display = 'inline-block';
        el.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem; padding: 0.25rem 0;">No active users — safe to restart without an announcement.</div>';
        return;
    }

    const nonAdmins = data.users.filter(u => !ADMIN_ROLES.has(u.role));
    safeBadge.style.display = nonAdmins.length === 0 ? 'inline-block' : 'none';

    const rows = data.users.map(u => `
        <tr>
            <td>${escHtml(u.display_name || u.username)}</td>
            <td style="color: var(--text-muted); font-size: 0.85rem;">@${escHtml(u.username)}</td>
            <td>${escHtml(ROLE_LABELS[u.role] || u.role)}</td>
            <td style="color: var(--text-muted);">${u.minutes_ago === 0 ? 'just now' : u.minutes_ago + ' min ago'}</td>
        </tr>`).join('');

    el.innerHTML = `
        <table class="data-table" style="margin-top: 0.25rem;">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Last Activity</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
        <div style="margin-top: 0.4rem; font-size: 0.82rem; color: var(--text-muted);">
            ${data.count} active user${data.count === 1 ? '' : 's'} &middot; ${data.sse_clients} SSE client${data.sse_clients === 1 ? '' : 's'} connected
        </div>`;
}

async function loadActiveUsers() {
    const btn = /** @type {HTMLButtonElement | null} */ (document.getElementById('refresh-users-btn'));
    if (btn) btn.disabled = true;
    try {
        const resp = await fetch(`${BP}/api/maintenance/active-users`);
        if (!resp.ok) {
            const el = document.getElementById('active-users-content');
            if (el) el.innerHTML =
                '<div style="color: var(--danger, #e74c3c); font-size: 0.85rem;">Failed to load active users.</div>';
            return;
        }
        renderActiveUsers(await resp.json());
        const updated = document.getElementById('users-last-updated');
        if (updated) updated.textContent = `Last checked: ${new Date().toLocaleTimeString()}`;
    } catch (e) {
        const el = document.getElementById('active-users-content');
        if (el) el.innerHTML =
            `<div style="color: var(--danger, #e74c3c); font-size: 0.85rem;">Error: ${escHtml(/** @type {Error} */ (e).message)}</div>`;
    } finally {
        if (btn) btn.disabled = false;
    }
}

// Load immediately + auto-refresh every 30 s
loadActiveUsers();
setInterval(loadActiveUsers, 30000);
