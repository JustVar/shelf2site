// @ts-check
/* Admin — Zendesk Integration */

async function testConnection() {
    const el = document.getElementById('connection-status');
    if (!el) return;
    el.innerHTML = '<span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:500;background:rgba(52,152,219,0.15);color:var(--info);">Testing...</span>';
    try {
        const resp = await fetch(BP + '/api/zendesk/test', {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            el.innerHTML = '<span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:500;background:rgba(39,174,96,0.15);color:var(--success);">Connected</span>' +
                '<span style="margin-left:0.5rem;color:var(--text-muted);font-size:0.85rem;">as ' + sxEsc(data.zendesk_user.name) + ' (' + sxEsc(data.zendesk_user.role) + ')</span>';
        } else {
            el.innerHTML = '<span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:500;background:rgba(231,76,60,0.15);color:var(--danger);">Failed</span>' +
                '<span style="margin-left:0.5rem;color:var(--danger);font-size:0.85rem;">' + sxEsc(data.error) + '</span>';
        }
    } catch (err) {
        el.innerHTML = '<span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:500;background:rgba(231,76,60,0.15);color:var(--danger);">Error</span>' +
            '<span style="margin-left:0.5rem;color:var(--danger);font-size:0.85rem;">' + sxEsc(/** @type {Error} */ (err).message) + '</span>';
    }
}

async function loadOrganizations() {
    const c = document.getElementById('orgs-container');
    if (!c) return;
    c.innerHTML = '<p style="color:var(--text-muted);">Loading...</p>';
    try {
        const resp = await fetch(BP + '/api/zendesk/organizations');
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to load');
        const orgs = data.organizations || [];
        if (!orgs.length) { c.innerHTML = '<p style="color:var(--text-muted);">No organizations found.</p>'; return; }
        let h = '<table><thead><tr><th>Name</th><th>ID</th><th>Domains</th><th>Created</th></tr></thead><tbody>';
        orgs.forEach(/** @param {any} o */ o => {
            h += '<tr><td>' + sxEsc(o.name || '-') + '</td><td>' + sxEsc(o.id) + '</td><td>' +
                sxEsc((o.domain_names || []).join(', ') || '-') + '</td><td>' +
                (o.created_at ? new Date(o.created_at).toLocaleDateString('en-CA', { timeZone: 'America/Chicago' }) : '-') + '</td></tr>';
        });
        h += '</tbody></table>';
        c.innerHTML = h;
    } catch (err) { c.innerHTML = '<p style="color:var(--danger);">' + sxEsc(/** @type {Error} */ (err).message) + '</p>'; }
}

async function loadTickets() {
    const c = document.getElementById('tickets-container');
    if (!c) return;
    c.innerHTML = '<p style="color:var(--text-muted);">Loading...</p>';
    try {
        const resp = await fetch(BP + '/api/zendesk/tickets?per_page=15');
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to load');
        const tickets = data.tickets || [];
        if (!tickets.length) { c.innerHTML = '<p style="color:var(--text-muted);">No tickets found.</p>'; return; }
        /** @type {Record<string, string>} */
        const sc = {open:'rgba(231,76,60,0.15)',pending:'rgba(243,156,18,0.15)',solved:'rgba(39,174,96,0.15)',closed:'rgba(149,165,166,0.15)','new':'rgba(52,152,219,0.15)',hold:'rgba(149,165,166,0.15)'};
        /** @type {Record<string, string>} */
        const tc = {open:'var(--danger)',pending:'var(--warning)',solved:'var(--success)',closed:'var(--text-muted)','new':'var(--info)',hold:'var(--text-muted)'};
        let h = '<table><thead><tr><th>#</th><th>Subject</th><th>Status</th><th>Priority</th><th>Updated</th></tr></thead><tbody>';
        tickets.forEach(/** @param {any} t */ t => {
            const bg = sc[t.status] || 'rgba(149,165,166,0.15)';
            const fg = tc[t.status] || 'var(--text-muted)';
            h += '<tr><td>' + sxEsc(t.id) + '</td><td title="' + sxEsc(t.subject || '') + '">' +
                sxEsc((t.subject || '-').substring(0, 60)) + '</td><td><span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:0.75rem;font-weight:500;background:' +
                bg + ';color:' + fg + ';">' + sxEsc(t.status || '-') + '</span></td><td>' +
                sxEsc(t.priority || '-') + '</td><td>' + (t.updated_at ? t.updated_at.split('T')[0] : '-') + '</td></tr>';
        });
        h += '</tbody></table>';
        c.innerHTML = h;
    } catch (err) { c.innerHTML = '<p style="color:var(--danger);">' + sxEsc(/** @type {Error} */ (err).message) + '</p>'; }
}

async function loadTicketFields() {
    const c = document.getElementById('fields-container');
    if (!c) return;
    c.innerHTML = '<p style="color:var(--text-muted);">Loading...</p>';
    try {
        const resp = await fetch(BP + '/api/zendesk/ticket-fields');
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to load');
        const fields = data.ticket_fields || [];
        if (!fields.length) { c.innerHTML = '<p style="color:var(--text-muted);">No fields found.</p>'; return; }
        let h = '<table><thead><tr><th>Title</th><th>ID</th><th>Type</th><th>Active</th></tr></thead><tbody>';
        fields.forEach(/** @param {any} f */ f => {
            const active = f.active ? 'Yes' : 'No';
            h += '<tr><td>' + sxEsc(f.title || '-') + '</td><td>' + sxEsc(f.id) + '</td><td>' +
                sxEsc(f.type || '-') + '</td><td>' + active + '</td></tr>';
        });
        h += '</tbody></table>';
        c.innerHTML = h;
    } catch (err) { c.innerHTML = '<p style="color:var(--danger);">' + sxEsc(/** @type {Error} */ (err).message) + '</p>'; }
}
