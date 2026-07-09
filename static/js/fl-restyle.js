// Cursor spotlight for the fl-restyle animated background (_fl_bg.html).
// Loaded once via base.html <head>; the listener binds to `document`, which
// persists across HTMX (hx-boost) navigations, so no re-binding is needed.
// The element is re-resolved per event and null-guarded: pages without the
// background layer make this a no-op. The window sentinel is defensive in
// case this file is ever included a second time from a page template.
(function () {
  "use strict";
  if (window.__flBgSpotBound) return;
  window.__flBgSpotBound = true;
  document.addEventListener("mousemove", function (e) {
    var el = document.getElementById("fl-bg-spot");
    if (el) {
      el.style.setProperty("--mx", e.clientX + "px");
      el.style.setProperty("--my", e.clientY + "px");
    }
  });
})();
