// @ts-check
/* Admin — Intune Device Sync */

/**
 * @param {string} msg
 * @param {boolean} ok
 */
function showBanner(msg, ok) {
    const el = document.getElementById('action-banner');
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    el.style.background = ok ? 'rgba(39, 174, 96, 0.12)' : 'rgba(231, 76, 60, 0.12)';
    el.style.border = `1px solid ${ok ? 'var(--success, #27ae60)' : 'var(--danger, #e74c3c)'}`;
    el.style.color = ok ? 'var(--success, #27ae60)' : 'var(--danger, #e74c3c)';
}

async function testConnection() {
    showBanner('Testing connection to Microsoft Graph API...', true);
    try {
        const resp = await fetch(`${BP}/api/intune/test`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            showBanner(`✓ ${data.message}`, true);
        } else {
            showBanner(`✗ ${data.error}`, false);
        }
    } catch (err) {
        showBanner(`Error: ${/** @type {Error} */ (err).message}`, false);
    }
}

async function runSync() {
    if (!(await SxDialog.confirm({ title: 'Run Intune sync', message: 'Run Intune device sync now? This will import/update Windows devices from Intune.', okLabel: 'Run sync' }))) return;
    showBanner('Syncing devices from Intune... this may take a moment.', true);
    try {
        const resp = await fetch(`${BP}/api/intune/sync`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            showBanner(`✓ Sync complete — ${data.devices_found} found, ${data.devices_added} added, ${data.devices_updated} updated, ${data.devices_skipped} skipped.`, true);
            setTimeout(() => location.reload(), 1500);
        } else {
            showBanner(`✗ ${data.error}`, false);
        }
    } catch (err) {
        showBanner(`Error: ${/** @type {Error} */ (err).message}`, false);
    }
}

function refreshLog() {
    location.reload();
}
