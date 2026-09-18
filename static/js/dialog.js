/**
 * SxDialog - confirm, prompt and reveal dialogs that replace window.confirm
 * and window.prompt on every page.
 *
 * Body-mounted like SxToast and styled inline on the --flc-* chrome tokens
 * with dark-theme fallbacks. z-index 90000: above every page modal (2000 at
 * most in templates and CSS, 9999 for the legacy coming-soon toast and the
 * scanner overlay) and below SxToast at 100000, so a toast still shows over
 * an open dialog.
 *
 * Usage (all three return a Promise; await it or chain .then):
 *   if (await SxDialog.confirm({ title: 'Delete order', message: 'This cannot be undone.', okLabel: 'Delete', danger: true })) { ... }
 *   var name = await SxDialog.prompt({ title: 'Rename', label: 'New name', value: current, required: true });
 *   if (name === null) return;   // cancelled
 *   await SxDialog.reveal({ title: 'Temp password', message: 'Copy it now.', value: secret });
 *
 * A plain string is accepted in place of the options object and becomes the
 * message:
 *   SxDialog.confirm('Remove this row?')
 *
 * confirm resolves true or false. prompt resolves the entered string as
 * typed (not trimmed) or null. reveal is a readout rather than a question: it
 * shows o.value in a selectable block with a Copy button, has no Cancel, and
 * resolves true however it is dismissed, so callers do not branch on it. Esc,
 * the Cancel button and a click on the backdrop cancel. Enter confirms unless
 * the Cancel or Copy button has focus. Focus returns to the element that had
 * it before the dialog opened. A call made while a dialog is open waits its
 * turn instead of stacking.
 *
 * Every string reaches the page through textContent, never as markup.
 */

(function() {
  'use strict';

  var Z_INDEX = 90000;
  var _chain = Promise.resolve();

  // Fallbacks are the dark-theme values: a body-mounted element cannot
  // rely on a page layer being present. Same rule as toast.js.
  var C = {
    card: 'var(--flc-card, #151821)',
    edge: 'var(--flc-card-edge, rgba(255,255,255,0.10))',
    text: 'var(--flc-text, #EDF0F6)',
    muted: 'var(--flc-text-muted, #97A3B6)',
    accent: 'var(--flc-accent, #C29E9B)',
    accentBorder: 'var(--flc-accent-border, rgba(194,158,155,0.45))',
    onAccent: 'var(--flc-on-accent, #17222E)',
    red: 'var(--flc-red, #FF6B6B)'
  };

  function normalise(opts, kind) {
    if (typeof opts === 'string') opts = { message: opts };
    opts = opts || {};
    var message = (opts.message === null || opts.message === undefined) ? '' : String(opts.message);
    var value = (opts.value === null || opts.value === undefined) ? '' : String(opts.value);
    // A blank message is fine when a title (or, for prompt, a label; for
    // reveal, the value itself) carries the question. With nothing at all to
    // show, fall back and say so.
    if (message.trim() === '' && !opts.title && !(kind === 'prompt' && opts.label) && !(kind === 'reveal' && value !== '')) {
      console.warn('SxDialog.' + kind + ' called with nothing to show');
      message = kind === 'prompt' ? 'Enter a value' : (kind === 'reveal' ? 'Nothing to show' : 'Are you sure?');
    }
    if (kind === 'reveal' && value === '') console.warn('SxDialog.reveal called with no value');
    return {
      title: opts.title ? String(opts.title) : (kind === 'prompt' ? 'Input needed' : (kind === 'reveal' ? 'Copy this value' : 'Please confirm')),
      message: message,
      okLabel: opts.okLabel ? String(opts.okLabel) : (kind === 'reveal' ? 'Done' : 'OK'),
      cancelLabel: opts.cancelLabel ? String(opts.cancelLabel) : 'Cancel',
      copyLabel: opts.copyLabel ? String(opts.copyLabel) : 'Copy',
      danger: !!opts.danger,
      label: opts.label ? String(opts.label) : '',
      value: value,
      placeholder: opts.placeholder ? String(opts.placeholder) : '',
      required: !!opts.required
    };
  }

  function el(tag, css, text) {
    var node = document.createElement(tag);
    if (css) node.style.cssText = css;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function button(label, primary, danger) {
    var b = el('button',
      'font:inherit;font-size:0.85rem;font-weight:500;padding:0.45rem 0.9rem;border-radius:6px;cursor:pointer;line-height:1.2;'
      + (primary
        ? 'border:1px solid transparent;background:' + (danger ? C.red : C.accent) + ';color:' + C.onAccent + ';'
        : 'border:1px solid ' + C.accentBorder + ';background:transparent;color:' + C.text + ';'),
      label);
    b.type = 'button';
    return b;
  }

  // Build, show and resolve one dialog. Never runs while another is open;
  // open() serialises calls on _chain.
  function show(kind, o) {
    return new Promise(function(resolve) {
      var opener = document.activeElement;

      var overlay = el('div',
        'position:fixed;inset:0;z-index:' + Z_INDEX + ';background:rgba(0,0,0,0.55);'
        + 'display:flex;align-items:center;justify-content:center;padding:1rem;');
      overlay.id = 'sx-dialog-overlay';

      var box = el('div',
        'background:' + C.card + ';color:' + C.text + ';border:1px solid ' + C.edge + ';border-radius:10px;'
        + 'box-shadow:0 20px 60px rgba(0,0,0,0.5);width:min(440px, 100%);padding:1.1rem 1.25rem;'
        + 'font-size:0.9rem;line-height:1.45;box-sizing:border-box;');
      box.id = 'sx-dialog';
      box.setAttribute('role', kind === 'confirm' ? 'alertdialog' : 'dialog');
      box.setAttribute('aria-modal', 'true');
      box.setAttribute('aria-labelledby', 'sx-dialog-title');

      var title = el('div', 'font-size:1rem;font-weight:600;margin:0 0 0.5rem 0;', o.title);
      title.id = 'sx-dialog-title';
      box.appendChild(title);
      if (o.message.trim() !== '') {
        var msg = el('div', 'white-space:pre-line;word-break:break-word;margin:0 0 1rem 0;', o.message);
        msg.id = 'sx-dialog-msg';
        box.setAttribute('aria-describedby', 'sx-dialog-msg');
        box.appendChild(msg);
      }

      var input = null;
      if (kind === 'prompt') {
        var field = el('label', 'display:block;margin:0 0 1rem 0;');
        if (o.label) field.appendChild(el('span', 'display:block;font-size:0.78rem;color:' + C.muted + ';margin-bottom:0.3rem;', o.label));
        input = el('input',
          'display:block;width:100%;box-sizing:border-box;font:inherit;padding:0.5rem 0.6rem;border-radius:6px;'
          + 'border:1px solid ' + C.accentBorder + ';background:transparent;color:' + C.text + ';outline:none;');
        input.id = 'sx-dialog-input';
        input.type = 'text';
        input.value = o.value;
        if (o.placeholder) input.placeholder = o.placeholder;
        field.appendChild(input);
        box.appendChild(field);
      }

      // reveal shows a value instead of asking for one. A div, not an input:
      // nothing here is editable and nothing is submitted. user-select:all
      // makes one click take the whole string.
      var readout = null;
      if (kind === 'reveal') {
        readout = el('div',
          'display:block;width:100%;box-sizing:border-box;margin:0 0 1rem 0;padding:0.5rem 0.6rem;border-radius:6px;'
          + 'border:1px solid ' + C.accentBorder + ';background:rgba(255,255,255,0.04);color:' + C.text + ';'
          + 'font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;font-size:0.9rem;'
          + 'word-break:break-all;user-select:all;-webkit-user-select:all;',
          o.value);
        readout.id = 'sx-dialog-value';
        box.setAttribute('aria-describedby',
          box.hasAttribute('aria-describedby') ? 'sx-dialog-msg sx-dialog-value' : 'sx-dialog-value');
        box.appendChild(readout);
      }

      var row = el('div', 'display:flex;justify-content:flex-end;gap:0.5rem;');
      var cancelBtn = null;
      var copyBtn = null;
      if (kind === 'reveal') {
        copyBtn = button(o.copyLabel, false, false);
        copyBtn.id = 'sx-dialog-copy';
        row.appendChild(copyBtn);
      } else {
        cancelBtn = button(o.cancelLabel, false, false);
        cancelBtn.id = 'sx-dialog-cancel';
        row.appendChild(cancelBtn);
      }
      var okBtn = button(o.okLabel, true, o.danger);
      okBtn.id = 'sx-dialog-ok';
      row.appendChild(okBtn);
      box.appendChild(row);
      overlay.appendChild(box);

      function okAllowed() {
        return !(input && o.required && input.value.trim() === '');
      }
      function syncOk() {
        var on = okAllowed();
        okBtn.disabled = !on;
        okBtn.style.opacity = on ? '1' : '0.5';
        okBtn.style.cursor = on ? 'pointer' : 'not-allowed';
      }

      // Selecting the readout is both the manual copy path and the fallback
      // when the clipboard API is missing or refuses.
      function selectValue() {
        if (!readout) return;
        try {
          var sel = window.getSelection();
          var range = document.createRange();
          range.selectNodeContents(readout);
          sel.removeAllRanges();
          sel.addRange(range);
        } catch (e) { /* no selection API */ }
      }
      function flashLabel(text) {
        if (!copyBtn) return;
        copyBtn.textContent = text;
        setTimeout(function() { if (copyBtn) copyBtn.textContent = o.copyLabel; }, 1400);
      }
      function doCopy() {
        selectValue();
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(o.value).then(
            function() { flashLabel('Copied'); },
            function() { flashLabel('Press Ctrl+C'); });
        } else {
          flashLabel('Press Ctrl+C');
        }
      }

      var done = false;
      function finish(result) {
        if (done) return;
        done = true;
        document.removeEventListener('keydown', onKey, true);
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        if (opener && typeof opener.focus === 'function' && document.contains(opener)) {
          try { opener.focus(); } catch (e) { /* not focusable any more */ }
        }
        resolve(result);
      }
      function cancel() { finish(kind === 'prompt' ? null : (kind === 'reveal' ? true : false)); }
      function ok() {
        if (!okAllowed()) return;
        finish(kind === 'prompt' ? input.value : true);
      }

      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancel(); return; }
        if (e.key === 'Enter') {
          if (e.target === cancelBtn || e.target === copyBtn) return;
          e.preventDefault(); e.stopPropagation(); ok(); return;
        }
        if (e.key === 'Tab') {
          var items = input ? [input, cancelBtn, okBtn] : (copyBtn ? [copyBtn, okBtn] : [cancelBtn, okBtn]);
          var i = items.indexOf(document.activeElement);
          if (i === -1) { e.preventDefault(); items[0].focus(); return; }
          if (!e.shiftKey && i === items.length - 1) { e.preventDefault(); items[0].focus(); }
          else if (e.shiftKey && i === 0) { e.preventDefault(); items[items.length - 1].focus(); }
        }
      }

      if (cancelBtn) cancelBtn.addEventListener('click', cancel);
      if (copyBtn) copyBtn.addEventListener('click', doCopy);
      okBtn.addEventListener('click', ok);
      overlay.addEventListener('mousedown', function(e) { if (e.target === overlay) cancel(); });
      if (input) input.addEventListener('input', syncOk);
      document.addEventListener('keydown', onKey, true);

      document.body.appendChild(overlay);
      syncOk();
      if (input) { input.focus(); input.select(); }
      else if (readout) { copyBtn.focus(); selectValue(); }
      else if (o.danger) cancelBtn.focus();
      else okBtn.focus();
    });
  }

  function open(kind, opts) {
    var o = normalise(opts, kind);
    var p = _chain.then(function() { return show(kind, o); });
    _chain = p.then(function() {}, function() {});
    return p;
  }

  // Public API
  window.SxDialog = {
    confirm: function(opts) { return open('confirm', opts); },
    prompt: function(opts) { return open('prompt', opts); },
    reveal: function(opts) { return open('reveal', opts); }
  };

})();
