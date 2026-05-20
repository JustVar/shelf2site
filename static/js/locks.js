// @ts-check

/**
 * Edit Lock Manager — handles lock acquisition, escalation, release,
 * heartbeat, and SSE-driven lock indicators.
 *
 * Usage in templates:
 *   // Global instance created in base.html:
 *   // window._lockManager = new LockManager(basePath);
 *
 *   // On modal open:
 *   const result = await window._lockManager.acquire('warranty:42');
 *   // On first field input:
 *   await window._lockManager.escalate('warranty:42');
 *   // On modal close or save:
 *   await window._lockManager.release('warranty:42');
 */

/**
 * @typedef {Object} LockResult
 * @property {boolean} granted
 * @property {boolean} conflict
 * @property {string} [locked_by]
 * @property {string} [lock_level] - 'viewing'|'editing'
 */

class LockManager {
    /** @param {string} basePath - Root path prefix (e.g. '/inventory') */
    constructor(basePath) {
        /** @type {string} */
        this.bp = basePath;
        /** @type {Record<string, boolean>} */
        this.activeLocks = {};
        /** @type {Record<string, ReturnType<typeof setInterval>>} */
        this.heartbeatTimers = {};
        /** @type {Record<string, boolean>} */
        this._escalated = {};
        this._initSSE();
    }

    _initSSE() {
        if (!window._sseManager) return;
        window._sseManager.on('lock_acquired', (data) => {
            this._showLockIndicator(data.resource_key, data.display_name, data.level);
        });
        window._sseManager.on('lock_escalated', (data) => {
            this._showLockIndicator(data.resource_key, data.display_name, data.level);
        });
        window._sseManager.on('lock_released', (data) => {
            this._hideLockIndicator(data.resource_key);
        });
    }

    /** @param {string} resourceKey - e.g. 'warranty:42' @returns {Promise<LockResult>} */
    async acquire(resourceKey) {
        try {
            const resp = await fetch(this.bp + '/api/locks/acquire', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({resource_key: resourceKey}),
            });
            const result = await resp.json();
            if (result.granted && !result.conflict) {
                this.activeLocks[resourceKey] = true;
                this._startHeartbeat(resourceKey);
            }
            return result;
        } catch (err) {
            console.error('Lock acquire failed:', err);
            return {granted: true, conflict: false};
        }
    }

    /** @param {string} resourceKey @returns {Promise<{escalated: boolean}>} */
    async escalate(resourceKey) {
        if (this._escalated[resourceKey]) return {escalated: true};
        try {
            const resp = await fetch(this.bp + '/api/locks/escalate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({resource_key: resourceKey}),
            });
            const result = await resp.json();
            if (result.escalated) {
                this._escalated[resourceKey] = true;
            }
            return result;
        } catch (err) {
            console.error('Lock escalate failed:', err);
            return {escalated: true};
        }
    }

    /** @param {string} resourceKey */
    async release(resourceKey) {
        this._stopHeartbeat(resourceKey);
        delete this.activeLocks[resourceKey];
        delete this._escalated[resourceKey];
        try {
            await fetch(this.bp + '/api/locks/release', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({resource_key: resourceKey}),
            });
        } catch (err) {
            console.error('Lock release failed:', err);
        }
    }

    releaseAll() {
        Object.keys(this.activeLocks).forEach(k => this.release(k));
    }

    /** @param {string} resourceKey */
    _startHeartbeat(resourceKey) {
        this._stopHeartbeat(resourceKey);
        this.heartbeatTimers[resourceKey] = setInterval(() => {
            fetch(this.bp + '/api/locks/heartbeat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({resource_key: resourceKey}),
            }).catch(() => {});
        }, 60000);
    }

    /** @param {string} resourceKey */
    _stopHeartbeat(resourceKey) {
        if (this.heartbeatTimers[resourceKey]) {
            clearInterval(this.heartbeatTimers[resourceKey]);
            delete this.heartbeatTimers[resourceKey];
        }
    }

    /**
     * @param {string} resourceKey
     * @param {string} displayName
     * @param {string} level - 'viewing'|'editing'
     */
    _showLockIndicator(resourceKey, displayName, level) {
        const elId = 'lock-indicator-' + resourceKey.replace(/:/g, '-');
        const el = document.getElementById(elId);
        if (!el) return;

        const icon = level === 'editing' ? LockManager.LOCK_ICON : LockManager.EYE_ICON;
        const msg = level === 'editing'
            ? displayName + ' is currently editing this record'
            : displayName + ' is viewing this record';
        el.className = level === 'editing'
            ? 'lock-indicator lock-hard'
            : 'lock-indicator lock-soft';
        el.innerHTML = icon + '<span>' + msg + '</span>';
        el.style.display = 'flex';
    }

    /** @param {string} resourceKey */
    _hideLockIndicator(resourceKey) {
        const elId = 'lock-indicator-' + resourceKey.replace(/:/g, '-');
        const el = document.getElementById(elId);
        if (el) {
            el.style.display = 'none';
        }
    }

    /**
     * Show lock conflict in a modal. Call after acquire() returns a conflict.
     * @param {string} indicatorId - DOM id of the lock indicator div
     * @param {object} lockResult - result from acquire()
     * @param {string} formId - DOM id of the form to lock (optional)
     */
    showConflict(indicatorId, lockResult, formId) {
        const el = document.getElementById(indicatorId);
        if (!el) return;

        const isHard = lockResult.lock_level === 'editing';
        const icon = isHard ? LockManager.LOCK_ICON : LockManager.EYE_ICON;
        const msg = isHard
            ? lockResult.locked_by + ' is currently editing this record. Please wait.'
            : lockResult.locked_by + ' is also viewing this record.';
        el.className = isHard ? 'lock-indicator lock-hard' : 'lock-indicator lock-soft';
        el.innerHTML = icon + '<span>' + msg + '</span>';
        el.style.display = 'flex';

        if (isHard && formId) {
            const form = document.getElementById(formId);
            if (form) form.classList.add('form-locked');
        }
    }

    /**
     * Clear lock conflict display.
     */
    clearConflict(indicatorId, formId) {
        const el = document.getElementById(indicatorId);
        if (el) el.style.display = 'none';
        if (formId) {
            const form = document.getElementById(formId);
            if (form) form.classList.remove('form-locked');
        }
    }
}

// Inline SVG icons — stroke-based, matching sidebar icon style
LockManager.LOCK_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>';
LockManager.EYE_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';

// Release all locks on page unload
window.addEventListener('beforeunload', () => {
    if (window._lockManager) {
        Object.keys(window._lockManager.activeLocks).forEach(key => {
            navigator.sendBeacon(
                window._lockManager.bp + '/api/locks/release',
                new Blob(
                    [JSON.stringify({resource_key: key})],
                    {type: 'application/json'}
                )
            );
        });
    }
});
