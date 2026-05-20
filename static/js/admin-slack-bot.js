// @ts-check
/* Admin — Slack Bot Configuration */

async function testConnection() {
    const el = document.getElementById('test-result');
    if (!el) return;
    el.textContent = 'Testing...';
    el.style.color = 'var(--text-muted)';
    try {
        const resp = await fetch(`${BP}/api/slack-bot/test`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            el.innerHTML = `<span style="color: var(--success, #27ae60);">✓ Connected — Bot: <strong>${data.bot_name}</strong>, Team: <strong>${data.team}</strong></span>`;
        } else {
            el.innerHTML = `<span style="color: var(--danger, #e74c3c);">✗ ${data.error}</span>`;
        }
    } catch (err) {
        el.innerHTML = `<span style="color: var(--danger, #e74c3c);">Error: ${/** @type {Error} */ (err).message}</span>`;
    }
}

async function testDm() {
    const el = document.getElementById('dm-result');
    if (!el) return;
    el.textContent = 'Sending...';
    el.style.color = 'var(--text-muted)';
    try {
        const resp = await fetch(`${BP}/api/slack-bot/test-dm`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            el.innerHTML = `<span style="color: var(--success, #27ae60);">✓ DM sent to ${data.slack_user_id}</span>`;
        } else {
            el.innerHTML = `<span style="color: var(--danger, #e74c3c);">✗ ${data.error}</span>`;
        }
    } catch (err) {
        el.innerHTML = `<span style="color: var(--danger, #e74c3c);">Error: ${/** @type {Error} */ (err).message}</span>`;
    }
}
