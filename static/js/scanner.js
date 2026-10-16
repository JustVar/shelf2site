// @ts-check
/**
 * BarcodeScanner — reusable camera barcode scanner module.
 *
 * Uses the native BarcodeDetector API when available (Chrome Android/desktop,
 * iOS Safari 17.2+). Falls back to html5-qrcode (wraps zxing-js) vendored at
 * static/vendor/ for unsupported browsers (Firefox, older iOS) — the scan
 * path never depends on a CDN (H12).
 *
 * Usage:
 *   const scanner = new BarcodeScanner('/inventory');
 *   scanner.start(result => console.log(result));
 *   scanner.stop();
 */

/** @typedef {'success'|'error'|'warning'|'info'} ToastType */

class BarcodeScanner {
  /** @type {string} */
  #basePath;

  /** @type {boolean} */
  #running = false;

  /** @type {boolean} */
  #useNative;

  /** @type {MediaStream|null} */
  #stream = null;

  /** @type {HTMLElement|null} */
  #overlay = null;

  /** @type {HTMLVideoElement|null} */
  #video = null;

  /** @type {number|null} */
  #animFrame = null;

  /** @type {any} */
  #html5QrCode = null;

  /** @type {number} */
  #scanCount = 0;

  /** @type {boolean} */
  #showCounter = false;

  /** @type {((value: string) => void)|null} */
  #onResult = null;

  /** @type {number|null} */
  #toastTimer = null;

  /** @type {AudioContext|null} */
  #audioCtx = null;

  /** @type {MediaStreamTrack|null} — track that reported torch capability */
  #torchTrack = null;

  /** @type {boolean} */
  #torchOn = false;

  /** @type {boolean} — per-scan trail entries enabled (Quick Mode) */
  #trail = false;

  /** Barcode formats for native BarcodeDetector (H11: DataMatrix, ITF,
   *  PDF417 and UPC-E added — vendor labels use all four). */
  static NATIVE_FORMATS = [
    'qr_code', 'code_128', 'code_39', 'ean_13', 'ean_8', 'upc_a',
    'data_matrix', 'itf', 'pdf417', 'upc_e',
  ];

  /**
   * @param {string} basePath — app root path (e.g. '/inventory')
   */
  constructor(basePath) {
    this.#basePath = basePath.replace(/\/$/, '');
    this.#useNative = 'BarcodeDetector' in window;
  }

  /** @returns {boolean} Whether the native BarcodeDetector API is in use */
  get isNative() {
    return this.#useNative;
  }

  /** @returns {boolean} */
  get running() {
    return this.#running;
  }

  /** @returns {number} */
  get scanCount() {
    return this.#scanCount;
  }

  // ─── Public API ─────────────────────────────────────────────────

  /**
   * Open the camera and start scanning.
   * @param {(value: string) => void} onResult — called with the decoded barcode string
   * @param {{ showCounter?: boolean, trail?: boolean }} [opts]
   */
  async start(onResult, opts = {}) {
    if (this.#running) return;
    // Claim the slot BEFORE any await — two rapid start() calls used to both
    // pass the guard and stack two overlays (F17 double-start TOCTOU).
    this.#running = true;
    this.#onResult = onResult;
    this.#showCounter = opts.showCounter ?? false;
    this.#trail = opts.trail ?? false;
    this.#scanCount = 0;

    this.#buildOverlay();
    document.body.appendChild(/** @type {HTMLElement} */ (this.#overlay));
    document.body.style.overflow = 'hidden';

    // Honest insecure-origin message: on http:// there is no mediaDevices at
    // all — that is not "denied", it needs HTTPS (F17).
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      this.#showToast('Camera needs a secure (HTTPS) connection — use manual entry.', 'error');
      setTimeout(() => this.stop(), 2500);
      return;
    }

    try {
      this.#stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      });
    } catch (err) {
      const name = err && err.name || '';
      const msg = (name === 'NotFoundError' || name === 'DevicesNotFoundError' ||
                   name === 'OverconstrainedError')
        ? 'No camera found on this device — use manual entry.'
        : (name === 'NotAllowedError' || name === 'PermissionDeniedError')
          ? 'Camera access denied. Use manual entry.'
          : 'Camera unavailable (' + (name || 'unknown error') + ') — use manual entry.';
      this.#showToast(msg, 'error');
      setTimeout(() => this.stop(), 2500);
      return;
    }

    if (this.#useNative) {
      this.#startNative();
    } else {
      try {
        await this.#startFallback();
      } catch (err) {
        // Engine load/start failure used to be an unhandled rejection with a
        // dead overlay and no message (F17).
        this.#showToast('Scanner engine failed to load — use manual entry.', 'error');
        setTimeout(() => this.stop(), 2500);
        return;
      }
    }
  }

  /** Stop scanning and tear down the overlay. */
  stop() {
    this.#running = false;

    if (this.#animFrame != null) {
      cancelAnimationFrame(this.#animFrame);
      this.#animFrame = null;
    }

    if (this.#html5QrCode) {
      try {
        this.#html5QrCode.stop().catch(() => {});
      } catch { /* ignore */ }
      this.#html5QrCode = null;
    }

    if (this.#stream) {
      this.#stream.getTracks().forEach(t => t.stop());
      this.#stream = null;
    }

    if (this.#overlay && this.#overlay.parentNode) {
      this.#overlay.parentNode.removeChild(this.#overlay);
    }
    this.#overlay = null;
    this.#video = null;
    document.body.style.overflow = '';

    if (this.#toastTimer != null) {
      clearTimeout(this.#toastTimer);
      this.#toastTimer = null;
    }

    // Torch dies with its track; just drop our handle.
    this.#torchTrack = null;
    this.#torchOn = false;
  }

  /** Reset the scan counter to zero. */
  resetCount() {
    this.#scanCount = 0;
    this.#updateCounter();
  }

  /**
   * Show a toast notification on the scanner overlay.
   * @param {string} message
   * @param {ToastType} type
   * @param {{ action?: string, onAction?: () => void, duration?: number }} [opts]
   */
  showToast(message, type, opts = {}) {
    this.#showToast(message, type, opts);
  }

  // ─── Native BarcodeDetector ─────────────────────────────────────

  /** Start scanning using the native BarcodeDetector API. */
  #startNative() {
    const video = /** @type {HTMLVideoElement} */ (this.#video);
    video.srcObject = this.#stream;
    video.play();

    // @ts-ignore — BarcodeDetector is not in TS lib yet
    const detector = new BarcodeDetector({
      formats: BarcodeScanner.NATIVE_FORMATS,
    });

    /** @type {string} */
    let lastResult = '';
    let lastResultTime = 0;

    const scan = async () => {
      if (!this.#running) return;
      try {
        const barcodes = await detector.detect(video);
        if (barcodes.length > 0) {
          const value = barcodes[0].rawValue;
          const now = Date.now();
          // Debounce: ignore same barcode within 2 seconds
          if (value !== lastResult || now - lastResultTime > 2000) {
            lastResult = value;
            lastResultTime = now;
            this.#handleResult(value);
          }
        }
      } catch { /* frame not ready */ }
      this.#animFrame = requestAnimationFrame(scan);
    };

    video.addEventListener('loadeddata', () => {
      this.#animFrame = requestAnimationFrame(scan);
      // Capabilities are only trustworthy once the track is live.
      const track = this.#stream && this.#stream.getVideoTracks()[0];
      if (track) this.#setupTorch(track, null);
    }, { once: true });
  }

  // ─── html5-qrcode Fallback ─────────────────────────────────────

  /** Start scanning using html5-qrcode (vendored, loaded on first use). */
  async #startFallback() {
    // Stop the native video — html5-qrcode manages its own stream
    if (this.#video) {
      this.#video.style.display = 'none';
    }
    if (this.#stream) {
      this.#stream.getTracks().forEach(t => t.stop());
      this.#stream = null;
    }

    // Lazy-load html5-qrcode if not already loaded — vendored locally
    // (static/vendor), the scan path never depends on a CDN (H12).
    if (typeof Html5Qrcode === 'undefined') {
      await this.#loadScript(
        this.#basePath + '/static/vendor/html5-qrcode-2.3.8/html5-qrcode.min.js'
      );
    }

    // Create reader container inside the overlay
    const readerId = 'scanner-fallback-' + Date.now();
    const readerDiv = document.createElement('div');
    readerDiv.id = readerId;
    readerDiv.className = 'scanner-fallback-reader';
    this.#overlay?.insertBefore(readerDiv, this.#overlay.firstChild);

    // @ts-ignore — Html5Qrcode loaded dynamically
    this.#html5QrCode = new Html5Qrcode(readerId);

    /** @type {string} */
    let lastResult = '';
    let lastResultTime = 0;

    await this.#html5QrCode.start(
      { facingMode: 'environment' },
      {
        fps: 10,
        qrbox: { width: 280, height: 180 },
        formatsToSupport: [
          // @ts-ignore
          Html5QrcodeSupportedFormats.QR_CODE,
          // @ts-ignore
          Html5QrcodeSupportedFormats.CODE_128,
          // @ts-ignore
          Html5QrcodeSupportedFormats.CODE_39,
          // @ts-ignore
          Html5QrcodeSupportedFormats.EAN_13,
          // @ts-ignore
          Html5QrcodeSupportedFormats.EAN_8,
          // @ts-ignore
          Html5QrcodeSupportedFormats.UPC_A,
          // H11: same four extra formats as the native engine
          // @ts-ignore
          Html5QrcodeSupportedFormats.DATA_MATRIX,
          // @ts-ignore
          Html5QrcodeSupportedFormats.ITF,
          // @ts-ignore
          Html5QrcodeSupportedFormats.PDF_417,
          // @ts-ignore
          Html5QrcodeSupportedFormats.UPC_E,
        ],
      },
      /** @param {string} decoded */
      (decoded) => {
        const now = Date.now();
        if (decoded !== lastResult || now - lastResultTime > 2000) {
          lastResult = decoded;
          lastResultTime = now;
          this.#handleResult(decoded);
        }
      },
      () => {} // ignore errors
    );

    // Torch (fallback engine): html5-qrcode owns the stream, so capability
    // and control both go through its API. Feature-detect everything —
    // hidden unless the running track really reports torch.
    try {
      if (typeof this.#html5QrCode.getRunningTrackCapabilities === 'function' &&
          typeof this.#html5QrCode.applyVideoConstraints === 'function') {
        const caps = this.#html5QrCode.getRunningTrackCapabilities();
        if (caps && caps.torch) this.#setupTorch(null, this.#html5QrCode);
      }
    } catch { /* capability probe failed — leave torch hidden */ }
  }

  // ─── Result handling ────────────────────────────────────────────

  /** @param {string} value */
  #handleResult(value) {
    this.#scanCount++;
    this.#updateCounter();
    this.#decodeFeedback();
    if (this.#onResult) {
      this.#onResult(value);
    }
  }

  /**
   * Sensory confirmation that a decode landed: viewfinder flash, short beep,
   * and a vibration pulse where the device supports it. All three are
   * best-effort — a blocked AudioContext or missing vibrate API must never
   * break the scan loop.
   */
  #decodeFeedback() {
    // Flash
    const flash = this.#overlay && this.#overlay.querySelector('.scanner-flash');
    if (flash) {
      flash.classList.remove('active');
      // restart the animation even on rapid consecutive decodes
      void (/** @type {HTMLElement} */ (flash)).offsetWidth;
      flash.classList.add('active');
    }

    // Beep — a tiny WebAudio blip; no audio asset, nothing to load. The
    // context is created lazily on the first decode (scanner start came from
    // a user gesture, so autoplay policy allows it).
    try {
      const Ctx = window.AudioContext || /** @type {any} */ (window).webkitAudioContext;
      if (Ctx) {
        if (!this.#audioCtx) this.#audioCtx = new Ctx();
        if (this.#audioCtx.state === 'suspended') this.#audioCtx.resume();
        const osc = this.#audioCtx.createOscillator();
        const gain = this.#audioCtx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.15, this.#audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, this.#audioCtx.currentTime + 0.12);
        osc.connect(gain).connect(this.#audioCtx.destination);
        osc.start();
        osc.stop(this.#audioCtx.currentTime + 0.12);
      }
    } catch { /* audio blocked — silent scan is fine */ }

    // Vibrate
    try {
      if (navigator.vibrate) navigator.vibrate(40);
    } catch { /* not supported */ }
  }

  // ─── Torch ──────────────────────────────────────────────────────

  /**
   * Wire up the torch button if the camera supports it; stays hidden
   * otherwise. Exactly one of track / engine is non-null: the native path
   * controls the MediaStreamTrack directly, the fallback goes through
   * html5-qrcode's constraint API.
   * @param {MediaStreamTrack|null} track
   * @param {any} engine — html5-qrcode instance (fallback path)
   */
  #setupTorch(track, engine) {
    const btn = this.#overlay && /** @type {HTMLElement} */ (this.#overlay.querySelector('.scanner-torch'));
    if (!btn) return;

    if (track) {
      const caps = typeof track.getCapabilities === 'function' ? track.getCapabilities() : null;
      if (!caps || !(/** @type {any} */ (caps).torch)) return; // stays hidden
      this.#torchTrack = track;
    }
    // engine path: capability was already confirmed by the caller

    btn.style.display = '';
    btn.addEventListener('click', async () => {
      const want = !this.#torchOn;
      try {
        if (this.#torchTrack) {
          await this.#torchTrack.applyConstraints({ advanced: [/** @type {any} */ ({ torch: want })] });
        } else if (engine) {
          await engine.applyVideoConstraints({ advanced: [{ torch: want }] });
        }
        this.#torchOn = want;
        btn.classList.toggle('scanner-torch--on', want);
      } catch {
        // Honest failure: capability said yes but the toggle failed.
        this.#showToast('Torch not available on this camera.', 'error');
        btn.style.display = 'none';
      }
    });
  }

  // ─── DOM Construction ───────────────────────────────────────────

  /** Build the fullscreen overlay DOM. */
  #buildOverlay() {
    const overlay = document.createElement('div');
    overlay.className = 'scanner-overlay';

    // Video element (native path)
    const video = document.createElement('video');
    video.className = 'scanner-video';
    video.setAttribute('playsinline', '');
    video.setAttribute('autoplay', '');
    video.muted = true;
    overlay.appendChild(video);
    this.#video = video;

    // Viewfinder frame
    const frame = document.createElement('div');
    frame.className = 'scanner-frame';
    const line = document.createElement('div');
    line.className = 'scanner-line';
    frame.appendChild(line);
    const bottom = document.createElement('div');
    bottom.className = 'scanner-frame-bottom';
    frame.appendChild(bottom);
    overlay.appendChild(frame);

    // Instructions
    const inst = document.createElement('div');
    inst.className = 'scanner-instructions';
    inst.textContent = 'Point camera at barcode';
    overlay.appendChild(inst);

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'scanner-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.title = 'Close scanner';
    closeBtn.addEventListener('click', () => this.stop());
    overlay.appendChild(closeBtn);

    // Counter (hidden by default)
    if (this.#showCounter) {
      const counter = document.createElement('div');
      counter.className = 'scanner-counter';
      counter.innerHTML = 'Scanned: <span class="scanner-counter-num">0</span>';
      overlay.appendChild(counter);
    }

    // Decode flash (brief green pulse over the whole viewfinder)
    const flash = document.createElement('div');
    flash.className = 'scanner-flash';
    overlay.appendChild(flash);

    // Torch toggle — hidden until a live track reports the capability
    const torch = document.createElement('button');
    torch.className = 'scanner-torch';
    torch.style.display = 'none';
    torch.title = 'Toggle flashlight';
    torch.setAttribute('aria-label', 'Toggle flashlight');
    torch.textContent = '🔦';
    overlay.appendChild(torch);

    // Per-scan trail (Quick Mode): recent outcomes stack here while the
    // camera keeps running, so a batch of scans stays reviewable at a glance.
    if (this.#trail) {
      const trail = document.createElement('div');
      trail.className = 'scanner-trail';
      overlay.appendChild(trail);
    }

    // Toast container
    const toast = document.createElement('div');
    toast.className = 'scanner-toast';
    overlay.appendChild(toast);

    this.#overlay = overlay;
  }

  /**
   * Push an entry onto the Quick Mode trail. No-op unless the scanner was
   * started with { trail: true }. Callers pass PRE-ESCAPED html (same
   * contract as showToast).
   * @param {string} html
   * @param {ToastType} type
   */
  addTrail(html, type) {
    if (!this.#overlay) return;
    const trail = this.#overlay.querySelector('.scanner-trail');
    if (!trail) return;

    const entry = document.createElement('div');
    entry.className = `scanner-trail-entry scanner-trail-entry--${type}`;
    entry.innerHTML = html;
    trail.insertBefore(entry, trail.firstChild);

    // Keep the trail short — newest 4 entries only.
    while (trail.children.length > 4) {
      trail.removeChild(/** @type {Node} */ (trail.lastChild));
    }

    // Entries age out on their own; the sticky confirm toast does not.
    setTimeout(() => {
      entry.classList.add('scanner-trail-entry--fading');
      setTimeout(() => entry.remove(), 400);
    }, 6000);
  }

  /** Update the scan counter display. */
  #updateCounter() {
    if (!this.#showCounter || !this.#overlay) return;
    const num = this.#overlay.querySelector('.scanner-counter-num');
    if (num) num.textContent = String(this.#scanCount);
  }

  /**
   * Show a toast on the scanner overlay.
   * @param {string} message
   * @param {ToastType} type
   * @param {{ action?: string, onAction?: () => void, duration?: number }} [opts]
   */
  #showToast(message, type, opts = {}) {
    if (!this.#overlay) return;
    const toast = this.#overlay.querySelector('.scanner-toast');
    if (!toast) return;

    // Clear existing timer
    if (this.#toastTimer != null) clearTimeout(this.#toastTimer);

    // Reset classes
    toast.className = `scanner-toast scanner-toast--${type}`;

    // Build content
    let html = `<span class="scanner-toast-text">${message}</span>`;
    if (opts.action) {
      html += `<button class="scanner-toast-action">${opts.action}</button>`;
    }
    toast.innerHTML = html;

    if (opts.action && opts.onAction) {
      const btn = toast.querySelector('.scanner-toast-action');
      btn?.addEventListener('click', opts.onAction, { once: true });
    }

    // Animate in
    requestAnimationFrame(() => {
      toast.classList.add('visible');
    });

    // Auto-hide
    const duration = opts.duration ?? 3000;
    if (duration > 0) {
      this.#toastTimer = window.setTimeout(() => {
        toast.classList.remove('visible');
      }, duration);
    }
  }

  // ─── Utilities ──────────────────────────────────────────────────

  /**
   * Dynamically load a script from URL.
   * @param {string} src
   * @returns {Promise<void>}
   */
  #loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(s);
    });
  }
}

// Export for use in other scripts
// @ts-ignore
window.BarcodeScanner = BarcodeScanner;
