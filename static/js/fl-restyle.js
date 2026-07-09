// Cursor spotlight for the fl-restyle animated background (_fl_bg.html).
// Loaded once via base.html <head>; the listener binds to `document`, which
// persists across HTMX (hx-boost) navigations, so no re-binding is needed.
// The element is re-resolved per event and null-guarded: pages without the
// background layer make this a no-op. The window sentinel is defensive in
// case this file is ever included a second time from a page template.
(function () {
  "use strict";
  if (window.__flBgSpotBound) return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  window.__flBgSpotBound = true;
  document.addEventListener("mousemove", function (e) {
    var el = document.getElementById("fl-bg-spot");
    if (el) {
      el.style.setProperty("--mx", e.clientX + "px");
      el.style.setProperty("--my", e.clientY + "px");
    }
  });

  // Re-mark the sidebar active item after hx-boost swaps. The active class
  // is server-rendered from the request path and the sidebar is not
  // re-rendered on boosted navigation, so it goes stale without this.
  // Longest-matching href prefix mirrors the server-side rules.
  function flMarkActiveNav() {
    var links = document.querySelectorAll(".sx-nav__link");
    if (!links.length) return;
    var path = window.location.pathname;
    var best = null, bestLen = -1;
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute("href") || "";
      var hp = href.split("?")[0].replace(/\/$/, "");
      if (!hp) continue;
      if ((path === hp || path.replace(/\/$/, "") === hp || path.indexOf(hp + "/") === 0) && hp.length > bestLen) {
        best = links[i]; bestLen = hp.length;
      }
    }
    if (!best) return;
    for (var k = 0; k < links.length; k++) links[k].classList.remove("sx-nav__link--active");
    best.classList.add("sx-nav__link--active");
  }
  document.addEventListener("htmx:load", flMarkActiveNav);
})();
