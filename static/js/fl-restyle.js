// fl-restyle shared behaviors. Loaded once via base.html <head>; the
// document-level listeners persist across HTMX (hx-boost) navigations, so
// no re-binding is needed. The window sentinel is defensive in case this
// file is ever included a second time from a page template.
(function () {
  "use strict";
  if (window.__flBgSpotBound) return;
  window.__flBgSpotBound = true;

  // ── Cursor spotlight for the animated background (_fl_bg.html). ──
  // Only the spotlight is motion: it alone honors prefers-reduced-motion.
  // (Previously the early return also killed the nav re-marking below.)
  if (!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) {
    document.addEventListener("mousemove", function (e) {
      var el = document.getElementById("fl-bg-spot");
      if (el) {
        el.style.setProperty("--mx", e.clientX + "px");
        el.style.setProperty("--my", e.clientY + "px");
      }
    });
  }

  // ── Re-mark the sidebar active item after hx-boost swaps. ──
  // The active class is server-rendered from the request path and the
  // sidebar is not re-rendered on boosted navigation, so it goes stale
  // without this. Scoped to #sx-nav so flyout clones never compete in the
  // longest-prefix match. Also opens the accordion group containing the new
  // active link (expanded mode), mirroring the DOMContentLoaded auto-expand
  // in base.html which only runs on full page loads.
  function flMarkActiveNav() {
    var links = document.querySelectorAll("#sx-nav .sx-nav__link");
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
    var sub = best.closest(".sx-nav__subgroup");
    if (sub) sub.classList.add("sx-nav__subgroup--expanded");
    var sec = best.closest(".sx-nav__section");
    if (sec) sec.classList.add("sx-nav__section--expanded");
  }

  // ── Collapsed-rail flyout for grouped nav sections (Admin). ──
  // The collapsed rail hides grouped content; hovering or clicking a group
  // header opens a fixed panel cloned from the always-rendered section
  // content. The clone is portaled to <body> to escape the nav overflow
  // clip, carries its own hx-boost attributes (boost does not inherit
  // across the portal), and is rebuilt on every open so active states stay
  // fresh. body carries a zoom on most monitors: getBoundingClientRect
  // reports real viewport px while fixed children of the zoomed body are
  // laid out in zoomed px, so positions divide by the zoom factor.
  var flyout = null, flyoutFor = null, closeTimer = null;

  function flyoutClose() {
    if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
    var stray = document.querySelectorAll(".fl-nav-flyout");
    for (var s = 0; s < stray.length; s++) stray[s].remove();
    flyout = null;
    if (flyoutFor) { flyoutFor.setAttribute("aria-expanded", "false"); flyoutFor = null; }
  }
  function flyoutScheduleClose() {
    if (closeTimer) clearTimeout(closeTimer);
    closeTimer = setTimeout(flyoutClose, 260);
  }
  function flyoutCancelClose() {
    if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
  }
  function flyoutOpen(header) {
    if (!document.body.classList.contains("sx-nav-collapsed")) return;
    if (flyoutFor === header) { flyoutCancelClose(); return; }
    flyoutClose();
    var section = header.closest(".sx-nav__section");
    var content = section ? section.querySelector(".sx-nav__section-content") : null;
    if (!content) return;
    var panel = document.createElement("div");
    panel.className = "fl-nav-flyout";
    panel.setAttribute("hx-boost", "true");
    panel.setAttribute("hx-target", "main");
    panel.setAttribute("hx-select", "main");
    panel.setAttribute("hx-swap", "innerHTML");
    panel.appendChild(content.cloneNode(true));
    var deadBtns = panel.querySelectorAll(".sx-nav__subgroup-header");
    for (var d = 0; d < deadBtns.length; d++) deadBtns[d].setAttribute("tabindex", "-1");
    document.body.appendChild(panel);
    if (window.htmx && window.htmx.process) window.htmx.process(panel);
    var zoom = parseFloat(window.getComputedStyle(document.body).zoom) || 1;
    panel.style.maxHeight = ((window.innerHeight - 16) / zoom) + "px";
    var r = header.getBoundingClientRect();
    var h = panel.offsetHeight * zoom;
    var top = Math.min(Math.max(r.top, 8), Math.max(window.innerHeight - h - 8, 8));
    panel.style.top = (top / zoom) + "px";
    panel.style.left = ((r.right + 8) / zoom) + "px";
    panel.addEventListener("mouseenter", flyoutCancelClose);
    panel.addEventListener("mouseleave", flyoutScheduleClose);
    panel.addEventListener("click", function (e) {
      if (e.target.closest("a")) flyoutClose();
    });
    header.setAttribute("aria-haspopup", "true");
    header.setAttribute("aria-expanded", "true");
    flyout = panel;
    flyoutFor = header;
  }
  function flyoutInit() {
    var headers = document.querySelectorAll("#sx-nav .sx-nav__section-header");
    for (var i = 0; i < headers.length; i++) {
      var h = headers[i];
      if (h.getAttribute("data-fl-flyout") === "1") continue;
      h.setAttribute("data-fl-flyout", "1");
      h.addEventListener("mouseenter", function (e) { flyoutOpen(e.currentTarget); });
      h.addEventListener("mouseleave", flyoutScheduleClose);
      h.addEventListener("click", function (e) { flyoutOpen(e.currentTarget); });
    }
  }

  // Dismissal: Escape, click-out (capture), any scroll outside the panel
  // (simpler than re-anchoring), viewport resize (covers the auto-collapse
  // breakpoint flip), and navigation via htmx:load below.
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") flyoutClose(); });
  document.addEventListener("click", function (e) {
    if (!flyout) return;
    var t = e.target;
    if (t && t.closest && (t.closest(".fl-nav-flyout") || t.closest(".sx-nav__section-header"))) return;
    flyoutClose();
  }, true);
  window.addEventListener("scroll", function (e) {
    if (flyout && e.target instanceof Node && flyout.contains(e.target)) return;
    flyoutClose();
  }, true);
  window.addEventListener("resize", flyoutClose);

  document.addEventListener("htmx:load", function () {
    flMarkActiveNav();
    flyoutInit();
    flyoutClose();
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", flyoutInit);
  } else {
    flyoutInit();
  }
})();
