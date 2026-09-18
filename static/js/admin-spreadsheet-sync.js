// @ts-check
/* Admin — Spreadsheet Sync */

/** @type {Array<{action: string, serial: string, table_display: string, field_changes?: Array<{field: string, old: string, new: string}>, row_data?: Record<string, string>}>} */
let currentChanges = [];

async function uploadFile() {
    const input = /** @type {HTMLInputElement | null} */ (document.getElementById('file-input'));
    const file = input && input.files ? input.files[0] : null;

    if (!file) {
        SxToast.warning('Please select a file');
        return;
    }

    const status = document.getElementById('upload-status');
    if (status) status.innerHTML = '<p style="color: var(--accent);">Uploading and processing...</p>';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const resp = await fetch(`${BP}/admin/spreadsheet-sync/upload`, {
            method: 'POST',
            body: formData,
        });

        if (!resp.ok) {
            const error = await resp.json();
            throw new Error(error.error || 'Upload failed');
        }

        const result = await resp.json();
        currentChanges = result.changes;

        // Show preview section
        const preview = document.getElementById('preview-section');
        if (preview) preview.style.display = 'block';

        // Update stats
        const addsCount = document.getElementById('adds-count');
        const updatesCount = document.getElementById('updates-count');
        const skipsCount = document.getElementById('skips-count');
        if (addsCount) addsCount.textContent = String(result.stats.adds);
        if (updatesCount) updatesCount.textContent = String(result.stats.updates);
        if (skipsCount) skipsCount.textContent = String(result.stats.skips);

        const statsSummary = document.getElementById('stats-summary');
        if (statsSummary) {
            statsSummary.innerHTML = `
                <div style="background: var(--primary); padding: 1.5rem; border-radius: 4px; line-height: 1.8;">
                    <strong>Total: ${result.stats.total}</strong> devices found <span style="margin: 0 0.5rem;">|</span>
                    <span style="color: var(--success);">${result.stats.adds} new</span> <span style="margin: 0 0.5rem;">|</span>
                    <span style="color: var(--warning);">${result.stats.updates} updates</span> <span style="margin: 0 0.5rem;">|</span>
                    <span style="color: var(--text-muted);">${result.stats.skips} unchanged</span>
                </div>
            `;
        }

        renderChanges();

        if (status) status.innerHTML = '<p style="color: var(--success);">✓ File processed successfully</p>';
    } catch (e) {
        if (status) status.innerHTML = `<p style="color: var(--danger);">Error: ${/** @type {Error} */ (e).message}</p>`;
    }
}

function renderChanges() {
    const adds = currentChanges.filter(c => c.action === 'add');
    const updates = currentChanges.filter(c => c.action === 'update');
    const skips = currentChanges.filter(c => c.action === 'skip');

    const tabAdds = document.getElementById('tab-adds');
    const tabUpdates = document.getElementById('tab-updates');
    const tabSkips = document.getElementById('tab-skips');
    if (tabAdds) tabAdds.innerHTML = renderDeviceList(adds, 'add');
    if (tabUpdates) tabUpdates.innerHTML = renderDeviceList(updates, 'update');
    if (tabSkips) tabSkips.innerHTML = renderDeviceList(skips, 'skip');
}

/**
 * @param {typeof currentChanges} devices
 * @param {string} action
 * @returns {string}
 */
function renderDeviceList(devices, action) {
    if (devices.length === 0) {
        return '<p style="color: var(--text-muted); padding: 1rem;">No devices in this category.</p>';
    }

    let html = '<div class="table-section"><table><thead><tr>';
    html += '<th>Serial</th><th>Category</th>';

    if (action === 'update') {
        html += '<th>Changes</th>';
    } else if (action === 'add') {
        html += '<th>Data</th>';
    }

    html += '</tr></thead><tbody>';

    for (const device of devices) {
        html += '<tr>';
        html += `<td><strong>${device.serial}</strong></td>`;
        html += `<td>${device.table_display}</td>`;

        if (action === 'update' && device.field_changes) {
            const changesList = device.field_changes.map(ch =>
                `<div style="margin: 0.5rem 0; line-height: 1.6;"><strong>${ch.field}:</strong> <span style="color: var(--danger); text-decoration: line-through;">${ch.old || '(empty)'}</span> → <span style="color: var(--success);">${ch.new}</span></div>`
            ).join('');
            html += `<td style="padding: 1rem;">${changesList}</td>`;
        } else if (action === 'add') {
            const fields = Object.entries(device.row_data || {})
                .filter(([k, v]) => v && k !== 'serial')
                .slice(0, 3)
                .map(([k, v]) => `${k}: ${v}`)
                .join(', ');
            html += `<td style="color: var(--text-muted);">${fields}</td>`;
        }

        html += '</tr>';
    }

    html += '</tbody></table></div>';
    return html;
}

/**
 * @param {string} tabName
 * @param {Event} evt
 */
function showTab(tabName, evt) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(t => /** @type {HTMLElement} */ (t).style.display = 'none');
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));

    // Show selected tab
    const tab = document.getElementById(`tab-${tabName}`);
    if (tab) tab.style.display = 'block';
    const btn = /** @type {HTMLElement} */ (evt.target).closest('.tab');
    if (btn) btn.classList.add('active');
}

async function applyChanges() {
    if (!(await SxDialog.confirm({ title: 'Apply changes', message: `Apply ${currentChanges.filter(c => c.action !== 'skip').length} changes to the database?`, okLabel: 'Apply' }))) {
        return;
    }

    const btn = /** @type {HTMLButtonElement | null} */ (document.getElementById('apply-btn'));
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Applying...';
    }

    try {
        // Filter out skipped items
        const changesToApply = currentChanges.filter(c => c.action !== 'skip');

        const resp = await fetch(`${BP}/admin/spreadsheet-sync/apply`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({changes: changesToApply}),
        });

        if (!resp.ok) {
            const error = await resp.json();
            throw new Error(error.error || 'Apply failed');
        }

        const result = await resp.json();

        SxToast.success(`Success!\n${result.stats.added} added, ${result.stats.updated} updated, ${result.stats.skipped} skipped`, 0);

        resetSync();

    } catch (e) {
        SxToast.error(`Error: ${/** @type {Error} */ (e).message}`, 0);
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Apply Changes to Database';
        }
    }
}

function resetSync() {
    const preview = document.getElementById('preview-section');
    const fileInput = /** @type {HTMLInputElement | null} */ (document.getElementById('file-input'));
    const uploadStatus = document.getElementById('upload-status');
    const applyBtn = /** @type {HTMLButtonElement | null} */ (document.getElementById('apply-btn'));
    if (preview) preview.style.display = 'none';
    if (fileInput) fileInput.value = '';
    if (uploadStatus) uploadStatus.innerHTML = '';
    currentChanges = [];
    if (applyBtn) {
        applyBtn.disabled = false;
        applyBtn.textContent = 'Apply Changes to Database';
    }
}
