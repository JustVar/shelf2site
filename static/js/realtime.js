// realtime.js — shared SSE singleton (window._sseManager) + maintenance banner.
// Loaded in <head> BEFORE locks.js so lock subscribers can attach to _sseManager.
// API: _sseManager.on(type, fn) / .off(type, fn) / .connect() / .disconnect().
// Events: maintenance, force_reload, triage_gap_changed, lock_* (consumed by locks.js).

    // ── Maintenance announcement banner ──────────────────────────────────────
    (function() {
        var BP_M = window.BP;
        let _countdownInterval = null;

        function showBanner(data) {
            if (!data.active) { hideBanner(); return; }
            const banner = document.getElementById('maintenance-banner');
            const msgEl  = document.getElementById('maintenance-msg');
            const cdEl   = document.getElementById('maintenance-countdown');
            if (!banner) return;
            msgEl.textContent = data.message || 'Scheduled maintenance in progress.';
            banner.style.display = 'flex';
            // Start or restart countdown
            clearInterval(_countdownInterval);
            if (data.restart_at) {
                const restartMs = new Date(data.restart_at).getTime();
                function tick() {
                    const rem = Math.max(0, Math.round((restartMs - Date.now()) / 60000));
                    cdEl.textContent = rem > 0
                        ? `Restarting in ${rem} minute${rem === 1 ? '' : 's'}`
                        : 'Restarting now…';
                }
                tick();
                _countdownInterval = setInterval(tick, 60000);
            } else {
                cdEl.textContent = '';
            }
        }

        function hideBanner() {
            clearInterval(_countdownInterval);
            const banner = document.getElementById('maintenance-banner');
            if (banner) banner.style.display = 'none';
        }

        // Fetch current state on page load (polling fallback for reconnects)
        async function checkMaintenance() {
            try {
                const r = await fetch(`${BP_M}/api/maintenance/status`);
                if (r.ok) showBanner(await r.json());
            } catch(e) {}
        }

        // SSE Singleton — one connection per browser tab, shared across all features
        // Exposed as window._sseManager for LockManager and other consumers
        if (!window._sseManager) {
            window._sseManager = {
                _conn: null,
                _listeners: {},
                _retryTimer: null,

                on: function(type, fn) {
                    if (!this._listeners[type]) this._listeners[type] = [];
                    this._listeners[type].push(fn);
                },

                off: function(type, fn) {
                    if (!this._listeners[type]) return;
                    this._listeners[type] = this._listeners[type].filter(function(f) { return f !== fn; });
                },

                _emit: function(type, data) {
                    var fns = this._listeners[type] || [];
                    fns.forEach(function(fn) { try { fn(data); } catch(e) {} });
                    var allFns = this._listeners['*'] || [];
                    allFns.forEach(function(fn) { try { fn(type, data); } catch(e) {} });
                },

                connect: function() {
                    var self = this;
                    if (this._conn && this._conn.readyState !== EventSource.CLOSED) return;
                    try {
                        this._conn = new EventSource(BP_M + '/events/stream');
                        this._conn.addEventListener('update', function(e) {
                            try {
                                var payload = JSON.parse(e.data);
                                self._emit(payload.type, payload);
                            } catch(err) {}
                        });
                        this._conn.onerror = function() {
                            self._conn.close();
                            self._conn = null;
                            if (self._retryTimer) clearTimeout(self._retryTimer);
                            self._retryTimer = setTimeout(function() { self.connect(); }, 10000);
                        };
                    } catch(e) {}
                },

                disconnect: function() {
                    if (this._conn) { this._conn.close(); this._conn = null; }
                    if (this._retryTimer) { clearTimeout(this._retryTimer); this._retryTimer = null; }
                }
            };
        }

        // Register maintenance handlers on the shared SSE manager
        window._sseManager.on('maintenance', showBanner);
        window._sseManager.on('force_reload', function() { window.location.reload(); });

        // Live-update the nav triage badge when any user saves a triage fix.
        // Server emits total_items_with_gaps (union across roles) in the payload.
        window._sseManager.on('triage_gap_changed', function(data) {
            if (!data) return;
            var badge = document.getElementById('sx-nav-triage-badge');
            if (!badge) return;
            var count = data.total_items_with_gaps;
            if (typeof count === 'undefined') return;
            badge.textContent = count;
            badge.style.display = (count > 0) ? '' : 'none';
        });

        document.addEventListener('DOMContentLoaded', function() {
            checkMaintenance();
            window._sseManager.connect();
        });

        // Close SSE on page unload to free server worker immediately
        window.addEventListener('beforeunload', function() {
            if (window._sseManager) window._sseManager.disconnect();
        });
    })();
