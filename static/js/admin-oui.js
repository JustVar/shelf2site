// @ts-check
/* Admin — OUI Reference */

/** @param {string} groupClass */
function toggleGroup(groupClass) {
    const rows = document.querySelectorAll('.' + groupClass);
    const arrow = document.getElementById('arrow-' + groupClass);
    const isHidden = rows[0] && /** @type {HTMLElement} */ (rows[0]).style.display === 'none';

    rows.forEach(r => /** @type {HTMLElement} */ (r).style.display = isHidden ? '' : 'none');
    if (arrow) /** @type {HTMLElement} */ (arrow).style.transform = isHidden ? 'rotate(90deg)' : 'rotate(0deg)';
}

/** @param {Event} e */
async function addOUI(e) {
    e.preventDefault();
    const form = /** @type {HTMLFormElement | null} */ (document.getElementById('add-oui-form'));
    if (!form) return;
    const formData = new FormData(form);
    const msg = document.getElementById('add-oui-msg');
    if (!msg) return;
    try {
        const resp = await fetch(`${BP}/admin/oui/add`, { method: 'POST', body: formData });
        const data = await resp.json();
        if (resp.ok) {
            msg.innerHTML = '<span style="color: var(--success);">Added successfully.</span>';
            setTimeout(() => location.reload(), 500);
        } else {
            msg.innerHTML = `<span style="color: var(--danger);">${data.error}</span>`;
        }
    } catch (err) {
        msg.innerHTML = `<span style="color: var(--danger);">Error: ${/** @type {Error} */ (err).message}</span>`;
    }
}

/**
 * @param {number} id
 * @param {string} manufacturer
 * @param {string} table
 */
function editOUI(id, manufacturer, table) {
    const editId = /** @type {HTMLInputElement | null} */ (document.getElementById('edit-id'));
    const editMfr = /** @type {HTMLInputElement | null} */ (document.getElementById('edit-manufacturer'));
    const editTable = /** @type {HTMLSelectElement | null} */ (document.getElementById('edit-table'));
    const editMsg = document.getElementById('edit-msg');
    const modal = document.getElementById('edit-modal');
    if (editId) editId.value = String(id);
    if (editMfr) editMfr.value = manufacturer;
    if (editTable) editTable.value = table || 'network_equipment';
    if (editMsg) editMsg.innerHTML = '';
    if (modal) modal.style.display = 'flex';
}

function closeEditModal() {
    const modal = document.getElementById('edit-modal');
    if (modal) modal.style.display = 'none';
}

async function saveEdit() {
    const editId = /** @type {HTMLInputElement | null} */ (document.getElementById('edit-id'));
    const id = editId ? editId.value : '';
    const msg = document.getElementById('edit-msg');
    const editMfr = /** @type {HTMLInputElement | null} */ (document.getElementById('edit-manufacturer'));
    const editTable = /** @type {HTMLSelectElement | null} */ (document.getElementById('edit-table'));
    const form = new FormData();
    if (editMfr) form.append('manufacturer', editMfr.value);
    if (editTable) form.append('maps_to_table', editTable.value);

    try {
        const resp = await fetch(`${BP}/admin/oui/${id}/edit`, { method: 'POST', body: form });
        const data = await resp.json();
        if (resp.ok) {
            if (msg) msg.innerHTML = '<span style="color: var(--success);">Updated.</span>';
            setTimeout(() => location.reload(), 500);
        } else {
            if (msg) msg.innerHTML = `<span style="color: var(--danger);">${data.error}</span>`;
        }
    } catch (err) {
        if (msg) msg.innerHTML = `<span style="color: var(--danger);">Error: ${/** @type {Error} */ (err).message}</span>`;
    }
}

/**
 * @param {number} id
 * @param {string} prefix
 */
async function deleteOUI(id, prefix) {
    if (!(await SxDialog.confirm({ title: 'Delete OUI', message: `Delete OUI ${prefix} from the catalog?`, okLabel: 'Delete', danger: true }))) return;
    const resp = await fetch(`${BP}/admin/oui/${id}`, { method: 'DELETE' });
    if (resp.ok) location.reload();
}

// Close modal on backdrop click
const editModal = document.getElementById('edit-modal');
if (editModal) {
    editModal.addEventListener('click', function(e) {
        if (e.target === this) closeEditModal();
    });
}
