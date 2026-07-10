// @ts-check
/* Hardware Asset Tracker — Theme & Sidebar */

(function () {
    // Apply theme immediately to prevent flash
    const saved = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
})();

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initSidebar();
});

function initTheme() {
    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    updateThemeIcon(theme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeIcon(next);

    // Dispatch event for pages that need to react (e.g., map tiles)
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme: next } }));
}

/** @param {string} theme - 'dark'|'light' */
function updateThemeIcon(theme) {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    if (theme === 'dark') {
        btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg><span class="btn-label">Light</span>';
        btn.title = 'Switch to light mode';
    } else {
        btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg><span class="btn-label">Dark</span>';
        btn.title = 'Switch to dark mode';
    }
}

function initSidebar() {
    const sidebar = document.getElementById('nav-sidebar');
    if (!sidebar) return;

    // v2 key: forces expanded-by-default for all users, ignoring old 'hover' default
    const mode = localStorage.getItem('nav-mode-v2') || 'pinned';
    applyNavMode(mode, false);
}

/**
 * @param {string} mode - 'pinned'|'hover'|'icon'
 * @param {boolean} [animate] - Whether to animate the transition
 */
function applyNavMode(mode, animate) {
    const sidebar = document.getElementById('nav-sidebar');
    if (!sidebar) return;
    if (animate === false) {
        const orig = sidebar.style.transition;
        sidebar.style.transition = 'none';
        sidebar.dataset.navMode = mode;
        sidebar.offsetHeight; // force reflow
        sidebar.style.transition = orig;
    } else {
        sidebar.dataset.navMode = mode;
    }
    localStorage.setItem('nav-mode-v2', mode);
    updateCollapseButton(mode);
}

// Toggle between expanded (pinned) and minimized (hover-expand)
function toggleCollapseNav() {
    const sidebar = document.getElementById('nav-sidebar');
    if (!sidebar) return;
    const current = sidebar.dataset.navMode || 'pinned';
    applyNavMode(current === 'pinned' ? 'hover' : 'pinned');
}

// Toggle between hover-expand and locked-icon (the outside pin button)
function toggleIconMode() {
    const sidebar = document.getElementById('nav-sidebar');
    if (!sidebar) return;
    const current = sidebar.dataset.navMode || 'pinned';
    if (current === 'pinned') return; // no-op when expanded
    applyNavMode(current === 'icon' ? 'hover' : 'icon');
}

// Thin stroke chevrons for the sidebar edge tab
// Pinned → chevron points left (click to collapse); Minimized → chevron points right (click to expand)
const COLLAPSE_CHEVRON = `<svg viewBox="0 0 6 10" width="6" height="10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="5 1 1 5 5 9"/></svg>`;
const EXPAND_CHEVRON   = `<svg viewBox="0 0 6 10" width="6" height="10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 1 5 5 1 9"/></svg>`;

/** @param {string} mode - 'pinned'|'hover'|'icon' */
function updateCollapseButton(mode) {
    const btn = document.getElementById('nav-collapse-btn');
    if (!btn) return;
    if (mode === 'pinned') {
        btn.title = 'Minimize sidebar';
        btn.innerHTML = COLLAPSE_CHEVRON;
    } else {
        btn.title = 'Expand sidebar';
        btn.innerHTML = EXPAND_CHEVRON;
    }
}

// Keep for any external callers
function togglePinNav() { toggleCollapseNav(); }
function toggleSidebar() { toggleCollapseNav(); }

function toggleMobileSidebar() {
    const sidebar = document.getElementById('sx-nav');
    const overlay = document.getElementById('sidebar-overlay');
    if (!sidebar) return;

    // The drawer always shows the full nav — collapsed-rail state is a
    // desktop concept; clear any that survived a resize into phone width.
    sidebar.classList.remove('sx-nav--collapsed');
    if (document.body) document.body.classList.remove('sx-nav-collapsed');
    document.documentElement.classList.remove('sx-nav-pre-collapsed');

    sidebar.classList.toggle('mobile-open');
    if (overlay) overlay.classList.toggle('active');
}

function closeMobileSidebar() {
    const sidebar = document.getElementById('sx-nav');
    const overlay = document.getElementById('sidebar-overlay');
    if (sidebar) sidebar.classList.remove('mobile-open');
    if (overlay) overlay.classList.remove('active');
}

// Drawer hygiene: close after boosted nav swaps and on Escape; keep htmx
// history snapshots clean (beforeHistorySave) and close on restore —
// htmx:historyRestore does NOT fire afterSwap; and never carry drawer
// state out of phone widths. All are no-ops when the drawer is already
// closed or the nav is absent (kiosk).
document.addEventListener('htmx:afterSwap', closeMobileSidebar);
document.addEventListener('htmx:beforeHistorySave', closeMobileSidebar);
document.addEventListener('htmx:historyRestore', closeMobileSidebar);
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeMobileSidebar();
});
window.addEventListener('resize', function () {
    if (!window.matchMedia('(max-width: 767px)').matches) closeMobileSidebar();
});
