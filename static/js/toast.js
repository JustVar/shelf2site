// @ts-check
/**
 * SxToast — global toast notification system + error capture.
 *
 * Toast types: success, error, warning, info
 * Error capture: window.onerror, unhandledrejection, HTMX errors
 * Reports frontend errors to /api/errors/report (if authenticated).
 *
 * Usage:
 *   SxToast.success('Changes saved');
 *   SxToast.error('Something went wrong');
 *   SxToast.warning('Connection lost');
 *   SxToast.info('Processing...');
 */

(function() {
  'use strict';

  var BP = document.querySelector('meta[name="base-path"]');
  var basePath = BP ? BP.getAttribute('content') || '' : '';

  // ── Toast container ──────────────────────────────────────────────────────

  var container = null;

  function ensureContainer() {
    if (container) return container;
    container = document.createElement('div');
    container.id = 'sx-toast-container';
    container.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:100000;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;max-width:420px;';
    document.body.appendChild(container);
    return container;
  }

  var ICONS = {
    success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#27ae60" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>',
    error:   '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#e74c3c" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f39c12" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3498db" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
  };

  var BORDER_COLORS = {
    success: '#27ae60',
    error: '#e74c3c',
    warning: '#f39c12',
    info: '#3498db'
  };

  /**
   * Show a toast notification.
   * @param {string} message
   * @param {'success'|'error'|'warning'|'info'} type
   * @param {number} duration — ms before auto-dismiss (0 = sticky)
   */
  function show(message, type, duration) {
    type = type || 'info';
    duration = duration !== undefined ? duration : (type === 'error' ? 6000 : 4000);

    var c = ensureContainer();
    var toast = document.createElement('div');
    toast.style.cssText = 'pointer-events:auto;display:flex;align-items:flex-start;gap:0.5rem;padding:0.65rem 1rem;border-radius:6px;font-size:0.82rem;line-height:1.4;'
      + 'background:var(--card-bg, #1a2332);color:var(--text, #ecf0f1);border:1px solid ' + BORDER_COLORS[type] + ';'
      + 'box-shadow:0 4px 12px rgba(0,0,0,0.3);opacity:0;transform:translateX(20px);transition:opacity 0.25s, transform 0.25s;'
      + 'max-width:100%;word-break:break-word;';

    toast.innerHTML = '<span style="flex-shrink:0;margin-top:1px;">' + (ICONS[type] || '') + '</span>'
      + '<span style="flex:1;">' + escapeHtml(message) + '</span>'
      + '<button style="background:none;border:none;color:var(--text-muted,#95a5a6);cursor:pointer;font-size:1rem;line-height:1;padding:0 0 0 0.5rem;flex-shrink:0;" title="Dismiss">&times;</button>';

    toast.querySelector('button').addEventListener('click', function() { dismiss(toast); });

    c.appendChild(toast);

    // Animate in
    requestAnimationFrame(function() {
      toast.style.opacity = '1';
      toast.style.transform = 'translateX(0)';
    });

    // Auto-dismiss
    if (duration > 0) {
      setTimeout(function() { dismiss(toast); }, duration);
    }

    return toast;
  }

  function dismiss(toast) {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    setTimeout(function() {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
  }

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ── Public API ───────────────────────────────────────────────────────────

  window.SxToast = {
    show: show,
    success: function(msg, dur) { return show(msg, 'success', dur); },
    error: function(msg, dur) { return show(msg, 'error', dur); },
    warning: function(msg, dur) { return show(msg, 'warning', dur); },
    info: function(msg, dur) { return show(msg, 'info', dur); }
  };


  // ── Error capture & reporting ────────────────────────────────────────────

  // Rate limiting: max 5 reports per minute to avoid flooding
  var _reportCount = 0;
  var _reportWindow = Date.now();
  var MAX_REPORTS = 5;
  var WINDOW_MS = 60000;

  function canReport() {
    var now = Date.now();
    if (now - _reportWindow > WINDOW_MS) {
      _reportCount = 0;
      _reportWindow = now;
    }
    return _reportCount < MAX_REPORTS;
  }

  function reportError(message, stack, url, level) {
    if (!canReport()) return;
    _reportCount++;

    // Only report if we appear to be authenticated (session cookie exists)
    if (!document.cookie.includes('inventory_session')) return;

    try {
      var payload = JSON.stringify({
        message: (message || 'Unknown error').substring(0, 2000),
        stack: (stack || '').substring(0, 4000),
        url: url || window.location.pathname,
        level: level || 'error'
      });

      // Use sendBeacon for reliability (works even during page unload)
      if (navigator.sendBeacon) {
        navigator.sendBeacon(basePath + '/api/errors/report', new Blob([payload], {type: 'application/json'}));
      } else {
        fetch(basePath + '/api/errors/report', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: payload,
          keepalive: true
        }).catch(function() {});
      }
    } catch(e) {
      // Silently fail — don't create error loops
    }
  }


  // ── Global error handlers ───────────────────────────────────────────────

  window.addEventListener('error', function(event) {
    var msg = event.message || 'Uncaught error';
    // Skip errors from browser extensions or cross-origin scripts
    if (event.filename && (event.filename.includes('extension') || event.filename === '')) return;

    reportError(msg, event.error ? event.error.stack : '', event.filename, 'error');
  });

  window.addEventListener('unhandledrejection', function(event) {
    var reason = event.reason;
    var msg = reason instanceof Error ? reason.message : String(reason || 'Unhandled promise rejection');
    var stack = reason instanceof Error ? reason.stack : '';
    reportError(msg, stack, window.location.pathname, 'error');
  });


  // ── HTMX error handlers ─────────────────────────────────────────────────

  document.addEventListener('htmx:responseError', function(event) {
    var detail = event.detail || {};
    var status = detail.xhr ? detail.xhr.status : 0;
    var url = detail.pathInfo ? detail.pathInfo.requestPath : '';

    if (status === 401) {
      SxToast.warning('Session expired. Please log in again.');
      setTimeout(function() { window.location.href = basePath + '/login'; }, 2000);
      return;
    }
    if (status === 403) {
      SxToast.warning('You do not have permission for this action.');
      return;
    }
    if (status >= 500) {
      SxToast.error('Server error. Please try again or contact an administrator.');
      reportError('HTMX server error ' + status, '', url, 'error');
      return;
    }

    SxToast.error('Request failed (HTTP ' + status + ')');
  });

  document.addEventListener('htmx:sendError', function(event) {
    SxToast.warning('Network error. Check your connection and try again.');
  });

  document.addEventListener('htmx:timeout', function(event) {
    SxToast.warning('Request timed out. Please try again.');
  });

})();
