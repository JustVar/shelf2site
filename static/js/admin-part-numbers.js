// @ts-check
/* Admin — Part Numbers (SKU catalog) */

/** @param {string} groupClass */
function toggleGroup(groupClass) {
    const rows = document.querySelectorAll('.' + groupClass);
    const arrow = document.getElementById('arrow-' + groupClass);
    const isHidden = rows[0] && /** @type {HTMLElement} */ (rows[0]).style.display === 'none';

    rows.forEach(r => /** @type {HTMLElement} */ (r).style.display = isHidden ? '' : 'none');
    if (arrow) /** @type {HTMLElement} */ (arrow).style.transform = isHidden ? 'rotate(90deg)' : 'rotate(0deg)';
}

/** @param {Event} e */
async function addPN(e) {
    e.preventDefault();
    const form = /** @type {HTMLFormElement | null} */ (document.getElementById('add-pn-form'));
    if (!form) return;
    const formData = new FormData(form);
    const msg = document.getElementById('add-pn-msg');
    if (!msg) return;
    try {
        const resp = await fetch(`${BP}/admin/part-numbers/add`, { method: 'POST', body: formData });
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
 * @param {string | null} description
 * @param {string} category
 * @param {boolean} isLegacy
 * @param {boolean} isCustomerPn
 * @param {string | null} notes
 */
function editPN(id, description, category, isLegacy, isCustomerPn, notes) {
    const editId = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-id'));
    const editSku = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-sku'));
    const editDesc = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-desc'));
    const editCategory = /** @type {HTMLSelectElement | null} */ (document.getElementById('pn-edit-category'));
    const editLegacy = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-legacy'));
    const editCustomer = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-customer'));
    const editNotes = /** @type {HTMLTextAreaElement | null} */ (document.getElementById('pn-edit-notes'));
    const editMsg = document.getElementById('pn-edit-msg');
    const modal = document.getElementById('pn-edit-modal');

    // Populate the read-only SKU field by looking up the row we clicked from
    const row = document.getElementById('pn-row-' + id);
    if (editSku && row) {
        const skuSpan = row.querySelector('span[style*="monospace"]');
        if (skuSpan) editSku.value = skuSpan.textContent || '';
    }

    if (editId) editId.value = String(id);
    if (editDesc) editDesc.value = description || '';
    if (editCategory) editCategory.value = category || '';
    if (editLegacy) editLegacy.checked = !!isLegacy;
    if (editCustomer) editCustomer.checked = !!isCustomerPn;
    if (editNotes) editNotes.value = notes || '';
    if (editMsg) editMsg.innerHTML = '';
    if (modal) modal.style.display = 'flex';
}

function closePNEditModal() {
    const modal = document.getElementById('pn-edit-modal');
    if (modal) modal.style.display = 'none';
}

async function savePNEdit() {
    const editId = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-id'));
    const id = editId ? editId.value : '';
    const msg = document.getElementById('pn-edit-msg');
    const editDesc = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-desc'));
    const editCategory = /** @type {HTMLSelectElement | null} */ (document.getElementById('pn-edit-category'));
    const editLegacy = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-legacy'));
    const editCustomer = /** @type {HTMLInputElement | null} */ (document.getElementById('pn-edit-customer'));
    const editNotes = /** @type {HTMLTextAreaElement | null} */ (document.getElementById('pn-edit-notes'));
    const form = new FormData();
    if (editDesc) form.append('sku_description', editDesc.value);
    if (editCategory) form.append('item_category', editCategory.value);
    if (editLegacy && editLegacy.checked) form.append('is_legacy', 'on');
    if (editCustomer && editCustomer.checked) form.append('is_customer_pn', 'on');
    if (editNotes) form.append('notes', editNotes.value);

    try {
        const resp = await fetch(`${BP}/admin/part-numbers/${id}/edit`, { method: 'POST', body: form });
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
 * @param {string} sku
 */
async function deletePN(id, sku) {
    if (!(await SxDialog.confirm({ title: 'Delete SKU', message: `Delete SKU ${sku} from the catalog?\n\nBlocked at server if any item still references it.`, okLabel: 'Delete', danger: true }))) return;
    const resp = await fetch(`${BP}/admin/part-numbers/${id}`, { method: 'DELETE' });
    if (resp.ok) {
        location.reload();
    } else {
        const data = await resp.json().catch(() => ({ error: 'Delete failed' }));
        SxToast.error(data.error || 'Delete failed', 0);
    }
}

// Close modal on backdrop click
const pnEditModal = document.getElementById('pn-edit-modal');
if (pnEditModal) {
    pnEditModal.addEventListener('click', function(e) {
        if (e.target === this) closePNEditModal();
    });
}
