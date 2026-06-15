// Global keyboard shortcuts. Loaded once via base.html; the listeners bind to
// `document`, which persists across HTMX (hx-boost) navigations, so shortcuts
// keep working without re-binding on every page swap.
(function () {
  "use strict";

  function isTyping() {
    var el = document.activeElement;
    if (!el) return false;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return true;
    if (el.isContentEditable) return true;
    return false;
  }

  function hasModifier(e) {
    return e.ctrlKey || e.metaKey || e.altKey;
  }

  // Letter shortcuts work on any page.
  var NAV = {
    n: "/intake",
    o: "/checkout",
    i: "/checkin",
    t: "/triage",
    m: "/intake?mode=import",
  };

  document.addEventListener("keydown", function (e) {
    if (isTyping() || hasModifier(e)) return;
    var path = NAV[e.key.toLowerCase()];
    if (path) {
      e.preventDefault();
      window.location.href = window.BP + path;
    }
  });

  // "/" focuses the search box, but only on pages that have one.
  document.addEventListener("keydown", function (e) {
    if (e.key !== "/" || isTyping() || hasModifier(e)) return;
    var input = document.getElementById("db-search-input");
    if (input) {
      e.preventDefault();
      input.focus();
    }
  });

  // Enter inside the dashboard search box runs a search. Delegated so it works
  // regardless of when the input appears in the DOM (incl. after HTMX swaps).
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    var input = e.target;
    if (!input || input.id !== "db-search-input") return;
    var q = input.value.trim();
    if (q) {
      window.location.href = window.BP + "/search?q=" + encodeURIComponent(q);
    }
  });
})();
