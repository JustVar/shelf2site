// @ts-check

/**
 * TourEngine — custom vanilla JS guided tour system.
 *
 * Zero external dependencies. Uses clip-path overlay highlighting,
 * positioned tooltip popovers, and server-side progress tracking.
 *
 * Usage:
 *   window._tourEngine = new TourEngine('/inventory');
 *   // Auto-start on page load:
 *   window._tourEngine.checkAndAutoStart('/dashboard');
 *   // Manual start:
 *   window._tourEngine.startTour('dashboard_tour');
 *   // Help menu:
 *   window._tourEngine.showHelpMenu();
 */

/**
 * @typedef {Object} TourStep
 * @property {string} target - CSS selector for the target element
 * @property {string} title - Step title text
 * @property {string} description - Step description HTML
 * @property {string} [wait_for] - CSS selector to wait for before showing step
 * @property {string} [position] - Tooltip position: 'top'|'bottom'|'left'|'right'
 * @property {number} [highlight_padding] - Padding around highlighted element
 * @property {boolean} [optional] - If true, skip when target not found
 */

/**
 * @typedef {Object} Tour
 * @property {string} id
 * @property {string} name
 * @property {string} description
 * @property {string} page_pattern
 * @property {TourStep[]} steps
 * @property {number} [step_count]
 * @property {{ completed: boolean }} [progress]
 */

class TourEngine {

    /** @param {string} basePath - Root path prefix (e.g. '/inventory') */
    constructor(basePath) {
        /** @type {string} */
        this.bp = basePath;
        /** @type {Tour | null} */
        this.activeTour = null;
        /** @type {number} */
        this.currentStep = 0;
        /** @type {HTMLDivElement | null} */
        this.overlay = null;
        /** @type {HTMLDivElement | null} */
        this.tooltip = null;
        /** @type {boolean} */
        this.isRunning = false;
        /** @type {number} */
        this._waitRetries = 0;
        /** @type {ReturnType<typeof setTimeout> | null} */
        this._pendingWait = null;
        /** @type {(() => void) | null} */
        this._resizeHandler = null;
        /** @type {((e: KeyboardEvent) => void) | null} */
        this._keyHandler = null;
        /** @type {(() => void) | null} */
        this._scrollHandler = null;

        this._bindUnload();
    }

    /* ------------------------------------------------------------------ */
    /* Public API                                                          */
    /* ------------------------------------------------------------------ */

    /** @param {string} pagePath - Page path to check for auto-start tours */
    async checkAndAutoStart(pagePath) {
        try {
            // Check for ?tour= parameter (cross-page navigation from Help menu)
            const urlParams = new URLSearchParams(window.location.search);
            const requestedTour = urlParams.get('tour');
            if (requestedTour) {
                // Clean the URL parameter without reload
                const cleanUrl = window.location.pathname + window.location.hash;
                history.replaceState(null, '', cleanUrl);
                setTimeout(() => this.startTour(requestedTour), 800);
                return;
            }

            const resp = await fetch(this.bp + '/api/tours?page=' + encodeURIComponent(pagePath));
            if (!resp.ok) return;
            const data = await resp.json();
            const tours = data.tours || [];

            for (const tour of tours) {
                if (!tour.progress || !tour.progress.completed) {
                    // Small delay to let the page finish rendering
                    setTimeout(() => this._runTour(tour), 800);
                    return;
                }
            }
        } catch (err) {
            // Fail silently — tours are non-critical
        }
    }

    /** @param {string} tourId */
    async startTour(tourId) {
        try {
            const resp = await fetch(this.bp + '/api/tours/' + encodeURIComponent(tourId));
            if (resp.status === 403) {
                this._showToast(
                    'Tour Unavailable',
                    'You don\'t have access to this tour. Some tours are only available to users with specific roles. Contact your administrator if you need access.',
                    'warning',
                );
                return;
            }
            if (resp.status === 404) {
                this._showToast(
                    'Tour Not Found',
                    'This tour doesn\'t exist or may have been removed.',
                    'info',
                );
                return;
            }
            if (!resp.ok) return;
            const tour = await resp.json();
            this._runTour(tour);
        } catch (err) {
            console.error('TourEngine: failed to load tour', err);
        }
    }

    /** @param {boolean} dismissed - Whether the user dismissed (vs completed) */
    stopTour(dismissed) {
        if (!this.isRunning || !this.activeTour) return;

        // Save progress
        this._saveProgress(this.activeTour.id, !!dismissed);

        this._cleanup();
    }

    nextStep() {
        if (!this.isRunning || !this.activeTour) return;
        const next = this.currentStep + 1;
        if (next >= this.activeTour.steps.length) {
            this.stopTour(false);
        } else {
            this._showStep(next);
        }
    }

    prevStep() {
        if (!this.isRunning || !this.activeTour) return;
        if (this.currentStep > 0) {
            this._showStep(this.currentStep - 1);
        }
    }

    async showHelpMenu() {
        // Opening the catalog while a tour is running stacks two overlays --
        // quietly end the tour (no progress write; it stays resumable).
        if (this.isRunning) this._cleanup();
        try {
            // Server-side page matching for "Tour This Page" — the client
            // must not replicate fnmatch (wildcard patterns like /orders/*
            // never matched client-side; that bug shaped the old modal).
            const pagePath = window.location.pathname.replace(this.bp, '') || '/';
            const [allResp, pageResp] = await Promise.all([
                fetch(this.bp + '/api/tours/all'),
                fetch(this.bp + '/api/tours?page=' + encodeURIComponent(pagePath)),
            ]);
            if (!allResp.ok) {
                console.warn('TourEngine: /api/tours/all returned', allResp.status);
                return;
            }
            const data = await allResp.json();
            const pageData = pageResp.ok ? await pageResp.json() : { tours: [] };
            this._renderHelpModal(data.tours || [], pageData.tours || []);
        } catch (err) {
            console.error('TourEngine: failed to load help menu', err);
        }
    }

    /* ------------------------------------------------------------------ */
    /* Internal: Tour lifecycle                                            */
    /* ------------------------------------------------------------------ */

    /** @param {Tour} tour */
    _runTour(tour) {
        if (this.isRunning) this._cleanup();

        this.activeTour = tour;
        this.currentStep = 0;
        this.isRunning = true;

        this._createOverlay();
        this._bindKeyboard();
        this._bindResize();

        this._showStep(0);
    }

    _cleanup() {
        this.isRunning = false;
        this.activeTour = null;
        this.currentStep = 0;
        this._waitRetries = 0;

        if (this._pendingWait) {
            clearTimeout(this._pendingWait);
            this._pendingWait = null;
        }
        if (this._waitPoll) { clearInterval(this._waitPoll); this._waitPoll = null; }

        // Remove highlight from any target
        const highlighted = document.querySelector('.tour-highlight-target');
        if (highlighted) highlighted.classList.remove('tour-highlight-target');

        if (this.overlay) { this.overlay.remove(); this.overlay = null; }
        if (this.tooltip) { this.tooltip.remove(); this.tooltip = null; }

        if (this._keyHandler) {
            document.removeEventListener('keydown', this._keyHandler);
            this._keyHandler = null;
        }
        if (this._resizeHandler) {
            window.removeEventListener('resize', this._resizeHandler);
            window.removeEventListener('scroll', this._resizeHandler, true);
            document.removeEventListener('htmx:load', this._resizeHandler);
            document.removeEventListener('modal-closed', this._modalClosedHandler);
            this._resizeHandler = null;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Internal: Step rendering                                            */
    /* ------------------------------------------------------------------ */

    /** @param {number} stepIndex */
    _showStep(stepIndex) {
        const steps = this.activeTour.steps;
        if (stepIndex < 0 || stepIndex >= steps.length) return;

        const step = steps[stepIndex];

        // Centered conceptual step: no target, no highlight, tooltip in viewport center.
        if (step.center) {
            this._showCentered(step, stepIndex);
            return;
        }

        const waitSelector = step.wait_for || step.target;
        const _foundEl = document.querySelector(waitSelector);
        // Horizontal check: vertical off-screen is fixable by scrolling, but
        // an element fully off-screen horizontally (e.g. the mobile nav
        // drawer parked at translateX(-102%)) can never be scrolled to.
        const _fr = _foundEl && _foundEl.getBoundingClientRect();
        const _isVisible = _foundEl &&
            getComputedStyle(_foundEl).display !== 'none' &&
            _fr.width > 0 &&
            _fr.right > 0 && _fr.left < window.innerWidth;
        // When wait_for differs from target, resolve to the actual target element
        const targetEl = _isVisible
            ? (step.wait_for && step.target !== step.wait_for
                ? document.querySelector(step.target) || _foundEl
                : _foundEl)
            : null;

        if (!targetEl) {
            if (step.wait_for && step.wait_prompt) {
                this._showWaitPrompt(step, stepIndex);
                return;
            }
            if (step.optional) {
                // Skip optional steps whose target doesn't exist
                const dir = stepIndex >= this.currentStep ? 1 : -1;
                const next = stepIndex + dir;
                if (next >= 0 && next < steps.length) {
                    this._showStep(next);
                } else {
                    this.stopTour(false);
                }
                return;
            }

            // Retry with backoff
            if (this._waitRetries < 5) {
                this._waitRetries++;
                this._pendingWait = setTimeout(
                    () => this._showStep(stepIndex),
                    500 * this._waitRetries,
                );
                return;
            }

            // Target contract: a step whose selector never resolves falls
            // back to CENTERED with the cutout suppressed — never a
            // mispositioned zone, never a silently vanished step.
            console.debug('[tour] target missing, centering step:',
                this.activeTour.id, 'step', stepIndex, step.target);
            this._showCentered(step, stepIndex);
            return;
        }

        this._waitRetries = 0;
        this.currentStep = stepIndex;
        if (typeof closeQuickView === 'function' && step.target !== '.qv-panel') closeQuickView();

        // Remove previous highlight(s) — querySelectorAll catches stale siblings
        document.querySelectorAll('.tour-highlight-target').forEach(el => {
            el.classList.remove('tour-highlight-target');
        });

        // Draw cutout immediately so fixed elements (bulk bar etc.) are never covered
        this._updateOverlay(targetEl, step.highlight_padding || 8);

        // Scroll target into view BEFORE the final measurement, then reposition
        // once scrolling actually finishes. A fixed timeout races smooth-scroll
        // (positions against a still-moving target), so we wait for scrollend,
        // with a fallback timeout when the target is already in view.
        targetEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        let done = false;
        const finishStep = () => {
            if (done) return;
            done = true;
            window.removeEventListener('scrollend', finishStep, true);
            clearTimeout(fallbackTimer);
            this._scrollHorizontalIntoView(targetEl);
            this._updateOverlay(targetEl, step.highlight_padding || 8);
            this._renderTooltip(step, stepIndex);
            this._positionTooltip(targetEl, step.position || 'bottom');
            this._setShield(true);
        };

        // scrollend fires when scrolling fully stops (Chrome 114+).
        window.addEventListener('scrollend', finishStep, true);
        // Fallback: if the element is already in view, no scroll happens and
        // scrollend never fires — so position anyway after a short delay.
        const fallbackTimer = setTimeout(finishStep, 400);
    }

    /** Centered rendering shared by explicit center steps and the
     *  missing-target fallback — full dim, NO cutout, tooltip centered. */
    _showCentered(step, stepIndex) {
        this._waitRetries = 0;
        this.currentStep = stepIndex;
        document.querySelectorAll('.tour-highlight-target').forEach(el => {
            el.classList.remove('tour-highlight-target');
        });
        this._clearCutout();
        this._setShield(true);
        this._renderTooltip(step, stepIndex);
        if (this.tooltip) {
            this.tooltip.classList.add('tour-tooltip--centered');
            this.tooltip.style.display = 'block';
        }
    }

    _showWaitPrompt(step, stepIndex) {
        const self = this;

        // Clear any existing poll
        if (this._waitPoll) {
            clearInterval(this._waitPoll);
            this._waitPoll = null;
        }
        if (typeof closeQuickView === 'function') closeQuickView();
        // The user must interact with the page to satisfy the wait —
        // no cutout, and the dim must not block clicks.
        this._clearCutout();
        this._setShield(false);

        // Render a prompt tooltip anchored to center of screen
        if (!this.tooltip) {
            this.tooltip = document.createElement('div');
            this.tooltip.className = 'tour-tooltip';
            document.body.appendChild(this.tooltip);
        }

        const prompt = step.wait_prompt || 'Complete the action to continue.';
        this.tooltip.innerHTML =
            '<div class="tour-tooltip-body">' +
                '<p style="margin:0 0 0.75rem;font-size:0.95rem;">' + prompt + '</p>' +
                '<div style="display:flex;justify-content:flex-end;gap:0.5rem;">' +
                    '<button class="tour-btn-skip" id="tour-wait-skip">Skip</button>' +
                '</div>' +
            '</div>';

        // Position in center of viewport
        this.tooltip.style.position = 'fixed';
        this.tooltip.style.top = '50%';
        this.tooltip.style.left = '50%';
        this.tooltip.style.transform = 'translate(-50%, -50%)';
        this.tooltip.style.display = 'block';

        // Bind skip
        const skipBtn = this.tooltip.querySelector('#tour-wait-skip');
        if (skipBtn) {
            skipBtn.addEventListener('click', () => {
                if (this._waitPoll) {
                    clearInterval(this._waitPoll);
                    this._waitPoll = null;
                }
                this.currentStep = stepIndex;
                const next = stepIndex + 1;
                if (next < this.activeTour.steps.length) {
                    this._showStep(next);
                } else {
                    this.stopTour(false);
                }
            });
        }

        // Poll until the target becomes visible
        this._waitPoll = setInterval(() => {
            const el = document.querySelector(step.wait_for);
            const visible = el &&
                getComputedStyle(el).display !== 'none' &&
                el.getBoundingClientRect().width > 0;
            if (visible) {
                clearInterval(this._waitPoll);
                this._waitPoll = null;
                self._showStep(stepIndex);
            }
        }, 300);
    }

    /* ------------------------------------------------------------------ */
    /* Internal: Overlay                                                   */
    /* ------------------------------------------------------------------ */

    _zoom() {
        // body carries zoom 1.15 on most monitors: getBoundingClientRect
        // reports real viewport px while fixed/absolute children of the
        // zoomed body are laid out in zoomed px, so every measured value
        // divides by the factor before it becomes a style px (the nav
        // flyout's established pattern — fl-restyle.js).
        return parseFloat(window.getComputedStyle(document.body).zoom) || 1;
    }

    _createOverlay() {
        // Four dim panels around the cutout plus a blush ring on it. The
        // initial state is one full-cover panel — a targetless step can
        // never show a stray cutout because none exists until a target is
        // actually measured (the old single-div clip-path left a stale
        // mispositioned hole on centered steps).
        this.overlay = document.createElement('div');
        this.overlay.className = 'tour-overlay';
        this.overlay.innerHTML =
            '<div class="tour-dim" data-side="top"></div>' +
            '<div class="tour-dim" data-side="left"></div>' +
            '<div class="tour-dim" data-side="right"></div>' +
            '<div class="tour-dim" data-side="bottom"></div>' +
            '<div class="tour-ring"></div>';
        this.overlay.addEventListener('click', (e) => {
            e.stopPropagation();
        });
        document.body.appendChild(this.overlay);
        this._clearCutout();
    }

    _panels() {
        const q = (s) => this.overlay.querySelector('.tour-dim[data-side="' + s + '"]');
        return {
            top: q('top'), left: q('left'), right: q('right'), bottom: q('bottom'),
            ring: this.overlay.querySelector('.tour-ring'),
        };
    }

    /** Dim the whole page with no cutout (centered / targetless steps). */
    _clearCutout() {
        if (!this.overlay) return;
        const z = this._zoom();
        const W = window.innerWidth / z;
        const H = window.innerHeight / z;
        const p = this._panels();
        Object.assign(p.top.style, { top: '0px', left: '0px', width: W + 'px', height: H + 'px' });
        for (const side of [p.left, p.right, p.bottom]) {
            Object.assign(side.style, { top: '0px', left: '0px', width: '0px', height: '0px' });
        }
        p.ring.style.opacity = '0';
    }

    /** Block or allow page interaction under the dim. */
    _setShield(blocked) {
        if (!this.overlay) return;
        this.overlay.querySelectorAll('.tour-dim').forEach((el) => {
            el.style.pointerEvents = blocked ? '' : 'none';
        });
    }

    /**
     * @param {Element} targetEl
     * @param {number} padding
     */
    _updateOverlay(targetEl, padding) {
        if (!this.overlay) return;
        const z = this._zoom();
        const rect = targetEl.getBoundingClientRect();
        const pad = padding || 8;
        const x = (rect.left - pad) / z;
        const y = (rect.top - pad) / z;
        const w = (rect.width + pad * 2) / z;
        const h = (rect.height + pad * 2) / z;
        const W = window.innerWidth / z;
        const H = window.innerHeight / z;
        const p = this._panels();
        Object.assign(p.top.style, {
            top: '0px', left: '0px', width: W + 'px', height: Math.max(y, 0) + 'px',
        });
        Object.assign(p.left.style, {
            top: y + 'px', left: '0px', width: Math.max(x, 0) + 'px', height: h + 'px',
        });
        Object.assign(p.right.style, {
            top: y + 'px', left: (x + w) + 'px',
            width: Math.max(W - x - w, 0) + 'px', height: h + 'px',
        });
        Object.assign(p.bottom.style, {
            top: (y + h) + 'px', left: '0px',
            width: W + 'px', height: Math.max(H - y - h, 0) + 'px',
        });
        Object.assign(p.ring.style, {
            top: y + 'px', left: x + 'px', width: w + 'px', height: h + 'px', opacity: '1',
        });
    }

    _scrollHorizontalIntoView(targetEl) {
        // scrollIntoView's block:'nearest' does not reliably scroll nested
        // horizontal containers, so far-right targets (e.g. wide table cells)
        // stay off-screen. Find the nearest horizontally-scrollable ancestor
        // and scroll it so the target is centered within it.
        let el = targetEl.parentElement;
        while (el && el !== document.body) {
            const ox = getComputedStyle(el).overflowX;
            if ((ox === 'auto' || ox === 'scroll') && el.scrollWidth > el.clientWidth + 2) {
                const wrapRect = el.getBoundingClientRect();
                const tgtRect = targetEl.getBoundingClientRect();
                const targetOffset = (tgtRect.left - wrapRect.left) + el.scrollLeft;
                const desired = targetOffset - (el.clientWidth / 2) + (tgtRect.width / 2);
                el.scrollTo({ left: Math.max(0, desired), behavior: 'auto' });
                break; // only the nearest horizontal scroller needs adjusting
            }
            el = el.parentElement;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Internal: Tooltip                                                   */
    /* ------------------------------------------------------------------ */

    /**
     * @param {TourStep} step
     * @param {number} stepIndex
     */
    _renderTooltip(step, stepIndex) {
        if (!this.tooltip) {
            this.tooltip = document.createElement('div');
            this.tooltip.className = 'tour-tooltip';
            document.body.appendChild(this.tooltip);
        }

        const total = this.activeTour.steps.length;
        const isFirst = stepIndex === 0;
        const isLast = stepIndex === total - 1;

        let dots = '';
        for (let i = 0; i < total; i++) {
            const cls = i === stepIndex ? 'active' : (i < stepIndex ? 'completed' : '');
            dots += '<span class="tour-dot ' + cls + '"></span>';
        }

        this.tooltip.innerHTML =
            '<div class="tour-tooltip-header">' +
                '<span class="tour-tooltip-title">' + step.title + '</span>' +
                '<button class="tour-close-btn" title="Close tour">&times;</button>' +
            '</div>' +
            '<div class="tour-tooltip-body">' + step.description + '</div>' +
            '<div class="tour-tooltip-footer">' +
                '<div class="tour-progress">' + dots +
                    '<span class="tour-count">' + (stepIndex + 1) + ' of ' + total + '</span>' +
                '</div>' +
                '<div class="tour-nav">' +
                    (!isFirst ? '<button class="tour-btn-back">Back</button>' : '') +
                    (isLast
                        ? '<button class="tour-btn-next">Finish</button>'
                        : '<button class="tour-btn-next">Next</button>') +
                    '<button class="tour-btn-skip">Skip</button>' +
                '</div>' +
            '</div>';

        // Bind buttons
        const closeBtn = this.tooltip.querySelector('.tour-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', () => this.stopTour(true));

        const backBtn = this.tooltip.querySelector('.tour-btn-back');
        if (backBtn) backBtn.addEventListener('click', () => this.prevStep());

        const nextBtn = this.tooltip.querySelector('.tour-btn-next');
        if (nextBtn) nextBtn.addEventListener('click', () => {
            if (isLast) this.stopTour(false);
            else this.nextStep();
        });

        const skipBtn = this.tooltip.querySelector('.tour-btn-skip');
        if (skipBtn) skipBtn.addEventListener('click', () => this.stopTour(true));
    }

    /**
     * @param {Element} targetEl
     * @param {string} position - 'top'|'bottom'|'left'|'right'
     */
    _positionTooltip(targetEl, position) {
        if (!this.tooltip) return;
        this.tooltip.classList.remove('tour-tooltip--centered');

        // Temporarily make visible offscreen to measure
        this.tooltip.style.visibility = 'hidden';
        this.tooltip.style.display = 'block';
        const tooltipRect = this.tooltip.getBoundingClientRect();
        this.tooltip.style.visibility = '';

        const rect = targetEl.getBoundingClientRect();
        const gap = 12;
        const margin = 12;
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const tw = tooltipRect.width;
        const th = tooltipRect.height;

        const calcPos = (pos) => {
            let t, l;
            switch (pos) {
                case 'top':
                    t = rect.top - th - gap;
                    l = rect.left + (rect.width - tw) / 2;
                    break;
                case 'bottom':
                    t = rect.bottom + gap;
                    l = rect.left + (rect.width - tw) / 2;
                    break;
                case 'left':
                    t = rect.top + (rect.height - th) / 2;
                    l = rect.left - tw - gap;
                    break;
                case 'right':
                    t = rect.top + (rect.height - th) / 2;
                    l = rect.right + gap;
                    break;
                default:
                    t = rect.bottom + gap;
                    l = rect.left + (rect.width - tw) / 2;
            }
            // Viewport clamping
            t = Math.max(margin, Math.min(t, vh - th - margin));
            l = Math.max(margin, Math.min(l, vw - tw - margin));
            return { top: t, left: l };
        };

        // Check if tooltip overlaps target after clamping
        const overlaps = (t, l) => {
            return !(l + tw <= rect.left || l >= rect.right ||
                     t + th <= rect.top  || t >= rect.bottom);
        };

        const flipMap = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' };
        let pos = position || 'bottom';
        let { top, left } = calcPos(pos);

        // If clamping caused overlap, try alternates in order:
        //   1. opposite side of the same axis
        //   2. perpendicular sides (the two remaining sides)
        if (overlaps(top, left)) {
            // Build attempt order: opposite first, then the two perpendiculars
            const perpendiculars = (pos === 'top' || pos === 'bottom')
                ? ['left', 'right']
                : ['top', 'bottom'];
            const attempts = [flipMap[pos], ...perpendiculars];

            for (const altPos of attempts) {
                const alt = calcPos(altPos);
                if (!overlaps(alt.top, alt.left)) {
                    top = alt.top;
                    left = alt.left;
                    break;
                }
            }
            // If every alternate still overlaps, keep the clamped primary —
            // user can still drag/scroll, and this matches the prior fallback.
        }

        // All math above is in real viewport px; the tooltip is a fixed
        // child of the zoomed body, so the final write divides by zoom.
        const z = this._zoom();
        this.tooltip.style.top = (top / z) + 'px';
        this.tooltip.style.left = (left / z) + 'px';
    }

    /* ------------------------------------------------------------------ */
    /* Internal: Help Menu Modal                                           */
    /* ------------------------------------------------------------------ */

    /**
     * @param {Tour[]} tours - every enabled tour (role-filtered)
     * @param {Tour[]} pageTours - tours matching the CURRENT page (server fnmatch)
     */
    _renderHelpModal(tours, pageTours) {
        let modal = document.getElementById('tour-help-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'tour-help-modal';
            modal.className = 'modal-overlay';
            document.body.appendChild(modal);
        }
        modal.classList.add('open');

        const self = this;
        pageTours = pageTours || [];
        const pageIds = new Set(pageTours.map(function(t) { return t.id; }));

        const GROUP_LABELS = {
            'onboarding':  'Getting Started',
            'inventory':   'Inventory',
            'fulfillment': 'Fulfillment',
            'operations':  'Operations',
            'procurement': 'Procurement',
            'admin':       'Admin',
        };

        const row = function(t, onThisPage) {
            const completed = t.progress && t.progress.completed;
            const tick = completed
                ? '<span class="tlr-tick tlr-tick--done" title="Completed">✓</span>'
                : '<span class="tlr-tick" title="Not started"></span>';
            const n = t.step_count || (t.steps && t.steps.length) || 0;
            const steps = n ? n + ' steps' : '';
            const wildcard = t.page_pattern.indexOf('*') !== -1 || t.page_pattern.indexOf('?') !== -1;

            let action;
            if (!onThisPage && wildcard) {
                // Detail-page tours (/vendors/*, /provisioning/*) have no single
                // page to navigate to -- tell the user where to find them instead
                // of offering a Start that would land on a target-less page.
                const section = t.page_pattern.replace(/\/[*?].*$/, '');
                action = '<span class="tlr-hint">Open any ' + section.replace(/^\//, '') + ' page first</span>';
            } else {
                action = '<button class="tlr-btn" data-tour-id="' + t.id + '"' +
                    ' data-page="' + (t.page_url || t.page_pattern) + '"' +
                    (completed ? ' data-retake="1"' : '') +
                    (!onThisPage ? ' data-navigate="1"' : '') + '>' +
                    (completed ? 'Retake' : 'Start') +
                '</button>';
            }
            return '<div class="tlr-row">' +
                tick +
                '<div class="tlr-meta">' +
                    '<div class="tlr-name">' + t.name + '</div>' +
                    '<div class="tlr-sub">' + steps + '</div>' +
                '</div>' +
                action +
            '</div>';
        };

        let body = '';

        // "Tour This Page" — the common case is one click, so it leads.
        if (pageTours.length) {
            body += '<div class="tlr-group-label">Tour This Page</div>';
            pageTours.forEach(function(t) { body += row(t, true); });
        }

        // Grouped sections: Getting Started first, then alphabetical.
        const groupMap = {};
        tours.forEach(function(t) {
            if (pageIds.has(t.id)) return; // already shown above
            (groupMap[t.group] = groupMap[t.group] || []).push(t);
        });
        const groupOrder = Object.keys(groupMap).sort(function(a, b) {
            if (a === 'onboarding') return -1;
            if (b === 'onboarding') return 1;
            return (GROUP_LABELS[a] || a).localeCompare(GROUP_LABELS[b] || b);
        });
        groupOrder.forEach(function(group) {
            body += '<div class="tlr-group-label">' + (GROUP_LABELS[group] || group) + '</div>';
            groupMap[group].forEach(function(t) { body += row(t, false); });
        });

        modal.innerHTML =
            '<div class="tour-launcher">' +
                '<div class="tlr-head">' +
                    '<span class="tlr-title">Guided Tours</span>' +
                    '<button class="tlr-close" id="tour-help-close" title="Close">&times;</button>' +
                '</div>' +
                '<div class="tlr-list" id="tour-help-list">' + body + '</div>' +
                '<div class="tlr-foot">' +
                    '<button class="tlr-reset" id="tour-reset-all">Reset all tours</button>' +
                '</div>' +
            '</div>';

        modal.querySelector('#tour-help-close').addEventListener('click', function() {
            modal.classList.remove('open');
        });
        modal.addEventListener('click', function(e) {
            if (e.target === modal) modal.classList.remove('open');
        });

        modal.querySelector('#tour-reset-all').addEventListener('click', async function() {
            if (!(await SxDialog.confirm({ title: 'Reset tours', message: 'Reset every tour to Not started? Completed ticks will clear.', okLabel: 'Reset', danger: true }))) return;
            try {
                await fetch(self.bp + '/api/tours/progress', { method: 'DELETE' });
            } catch (e) { /* non-critical */ }
            modal.classList.remove('open');
            self.showHelpMenu();
        });

        modal.querySelectorAll('[data-tour-id]').forEach(function(btn) {
            btn.addEventListener('click', async function() {
                const tourId = btn.dataset.tourId;
                modal.classList.remove('open');

                if (btn.dataset.retake) {
                    try {
                        await fetch(self.bp + '/api/tours/progress/' + tourId, { method: 'DELETE' });
                    } catch (e) { /* ignore */ }
                }

                if (btn.dataset.navigate) {
                    // Exact patterns only -- wildcard tours never render a
                    // navigate button (see row()).
                    window.location.href = self.bp + btn.dataset.page + '?tour=' + tourId;
                    return;
                }

                self.startTour(tourId);
            });
        });
    }

    /* ------------------------------------------------------------------ */
    /* Internal: Toast notifications                                       */
    /* ------------------------------------------------------------------ */

    /**
     * @param {string} title
     * @param {string} message
     * @param {string} [type] - 'info'|'warning'
     */
    _showToast(title, message, type) {
        const toast = document.createElement('div');
        toast.className = 'tour-toast tour-toast-' + (type || 'info');
        toast.innerHTML =
            '<div class="tour-toast-icon">' + this._toastIcon(type) + '</div>' +
            '<div class="tour-toast-content">' +
                '<div class="tour-toast-title">' + title + '</div>' +
                '<div class="tour-toast-message">' + message + '</div>' +
            '</div>' +
            '<button class="tour-toast-close">&times;</button>';

        document.body.appendChild(toast);

        // Trigger slide-in animation
        requestAnimationFrame(() => toast.classList.add('visible'));

        const dismiss = () => {
            toast.classList.remove('visible');
            setTimeout(() => toast.remove(), 300);
        };

        toast.querySelector('.tour-toast-close').addEventListener('click', dismiss);
        setTimeout(dismiss, 6000);
    }

    /** @param {string} [type] */
    _toastIcon(type) {
        if (type === 'warning') {
            return '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">' +
                '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>' +
                '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
        }
        return '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">' +
            '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/>' +
            '<line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
    }

    /* ------------------------------------------------------------------ */
    /* Internal: Event binding                                             */
    /* ------------------------------------------------------------------ */

    _bindKeyboard() {
        this._keyHandler = (e) => {
            if (!this.isRunning) return;
            switch (e.key) {
                case 'ArrowRight':
                case 'Enter':
                    e.preventDefault();
                    this.nextStep();
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    this.prevStep();
                    break;
                case 'Escape':
                    e.preventDefault();
                    this.stopTour(true);
                    break;
            }
        };
        document.addEventListener('keydown', this._keyHandler);
    }

    _bindResize() {
        this._resizeHandler = () => {
            if (!this.isRunning || !this.activeTour) return;
            const step = this.activeTour.steps[this.currentStep];
            if (!step) return;
            if (step.center || !step.target) {
                // Centered steps only need the full-cover panel re-sized.
                this._clearCutout();
                return;
            }
            const targetEl = document.querySelector(step.target);
            if (targetEl && targetEl.getBoundingClientRect().width > 0) {
                this._updateOverlay(targetEl, step.highlight_padding || 8);
                this._positionTooltip(targetEl, step.position || 'bottom');
            } else if (step.wait_for && step.wait_prompt) {
                this._showWaitPrompt(step, this.currentStep);
            }
        };
        window.addEventListener('resize', this._resizeHandler);
        window.addEventListener('scroll', this._resizeHandler, true);
        // htmx swaps re-render targets in place — re-measure the live step.
        document.addEventListener('htmx:load', this._resizeHandler);
        this._modalClosedHandler = () => {
            if (!this.isRunning || !this.activeTour) return;
            this._showStep(this.currentStep);
        };
        document.addEventListener('modal-closed', this._modalClosedHandler);
    }

    _bindUnload() {
        window.addEventListener('beforeunload', () => {
            if (this.isRunning && this.activeTour) {
                navigator.sendBeacon(
                    this.bp + '/api/tours/progress',
                    new Blob(
                        [JSON.stringify({ tour_id: this.activeTour.id, dismissed: true })],
                        { type: 'application/json' },
                    ),
                );
            }
        });
    }

    /* ------------------------------------------------------------------ */
    /* Internal: Progress                                                  */
    /* ------------------------------------------------------------------ */

    /**
     * @param {string} tourId
     * @param {boolean} dismissed
     */
    _saveProgress(tourId, dismissed) {
        fetch(this.bp + '/api/tours/progress', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tour_id: tourId, dismissed: dismissed }),
        }).catch(() => { /* non-critical */ });
    }
}
