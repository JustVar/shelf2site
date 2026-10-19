// @ts-check
/* Admin — Notification Channels */

async function testSlackConnection() {
    const el = document.getElementById('slack-test-result');
    if (!el) return;
    el.textContent = 'Testing...';
    el.style.color = 'var(--text-muted)';
    try {
        const resp = await fetch(`${BP}/api/slack-bot/test`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            el.innerHTML = `<span style="color: var(--success, #27ae60);">&#x2713; Connected &mdash; Bot: <strong>${sxEsc(data.bot_name)}</strong>, Team: <strong>${sxEsc(data.team)}</strong></span>`;
        } else {
            el.innerHTML = `<span style="color: var(--danger, #e74c3c);">&#x2717; ${sxEsc(data.error)}</span>`;
        }
    } catch (err) {
        el.innerHTML = `<span style="color: var(--danger, #e74c3c);">Error: ${/** @type {Error} */ (err).message}</span>`;
    }
}

async function testSlackDm() {
    const el = document.getElementById('slack-dm-result');
    if (!el) return;
    el.textContent = 'Sending...';
    el.style.color = 'var(--text-muted)';
    try {
        const resp = await fetch(`${BP}/api/slack-bot/test-dm`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            el.innerHTML = `<span style="color: var(--success, #27ae60);">&#x2713; DM sent to ${sxEsc(data.slack_user_id)}</span>`;
        } else {
            el.innerHTML = `<span style="color: var(--danger, #e74c3c);">&#x2717; ${sxEsc(data.error)}</span>`;
        }
    } catch (err) {
        el.innerHTML = `<span style="color: var(--danger, #e74c3c);">Error: ${/** @type {Error} */ (err).message}</span>`;
    }
}

async function testEmail() {
    const el = document.getElementById('email-test-result');
    if (!el) return;
    el.textContent = 'Sending...';
    el.style.color = 'var(--text-muted)';
    try {
        const resp = await fetch(`${BP}/api/notifications/test-email`, {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            el.innerHTML = `<span style="color: var(--success, #27ae60);">&#x2713; Email sent to <strong>${sxEsc(data.to)}</strong></span>`;
        } else {
            el.innerHTML = `<span style="color: var(--danger, #e74c3c);">&#x2717; ${sxEsc(data.error)}</span>`;
        }
    } catch (err) {
        el.innerHTML = `<span style="color: var(--danger, #e74c3c);">Error: ${/** @type {Error} */ (err).message}</span>`;
    }
}
