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
   * @param {{ showCounter?: boolean }} [opts]
   */
  async start(onResult, opts = {}) {
    if (this.#running) return;
    // Claim the slot BEFORE any await — two rapid start() calls used to both
    // pass the guard and stack two overlays (F17 double-start TOCTOU).
    this.#running = true;
    this.#onResult = onResult;
    this.#showCounter = opts.showCounter ?? false;
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
    }, { once: true });
  }

  // ─── html5-qrcode Fallback ─────────────────────────────────────

  /** Start scanning using html5-qrcode (CDN lazy-load). */
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
        this.#basePath + '/static/vendor/html5-qrcode.min.js'
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
  }

  // ─── Result handling ────────────────────────────────────────────

  /** @param {string} value */
  #handleResult(value) {
    this.#scanCount++;
    this.#updateCounter();
    if (this.#onResult) {
      this.#onResult(value);
    }
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

    // Toast container
    const toast = document.createElement('div');
    toast.className = 'scanner-toast';
    overlay.appendChild(toast);

    this.#overlay = overlay;
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
