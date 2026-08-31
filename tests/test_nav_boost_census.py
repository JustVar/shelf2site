"""Nav boost census.

hx-select="main" means a boosted navigation keeps ONLY <main> and discards the
rest of the response. A page that renders any script outside main therefore
arrives fully rendered and completely inert when reached through the nav. That
happened to eleven pages and went unnoticed for months, because an inert page
looks identical to a working one until you click something.

These tests make that class of bug fail loud:

  - structural: hx-boost is declared exactly once in the app
  - behavioral: every boosted nav destination contributes no script outside main

The boosted set is ENUMERATED from base.html rather than listed here, so adding
a nav link adds a case and removing an hx-boost="false" puts that href back in
the set. Either way the suite total moves, which is the signal.

See docs/specs/page-init-on-boosted-navigation.md.
"""

import re
from pathlib import Path

import pytest

BASE_TEMPLATE = Path(__file__).resolve().parent.parent / "app" / "templates" / "base.html"
BASE_PATH_TOKEN = "{{ base_path }}"


def _base_html():
    return BASE_TEMPLATE.read_text(encoding="utf-8")


def _nav_region(src):
    """The sidenav element's source, which is the only boosted region."""
    start = src.find('<nav class="sx-nav"')
    assert start != -1, "sidenav element not found in base.html"
    end = src.find("</nav>", start)
    assert end != -1, "sidenav element is not closed"
    return src[start:end]


def _boosted_nav_paths():
    """Nav hrefs that a boosted navigation will handle.

    Enumerated from source at import time so pytest can parametrise over it.
    An anchor is boosted unless it carries hx-boost="false", since hx-boost on
    the nav is inherited by descendants.
    """
    nav = _nav_region(_base_html())
    paths = []
    for tag in re.findall(r"<a\b[^>]*>", nav, re.S):
        m = re.search(r'href="([^"]*)"', tag)
        if not m or not m.group(1).startswith(BASE_PATH_TOKEN):
            continue
        if 'hx-boost="false"' in tag:
            continue
        path = m.group(1)[len(BASE_PATH_TOKEN):]
        if path and path not in paths:
            paths.append(path)
    return paths


BOOSTED_PATHS = _boosted_nav_paths()


def _scripts_outside_main(html):
    """(set of script srcs, count of inline scripts) rendered outside <main>.

    Only base.html contributes here on a correct page, so this value is the
    same for every boosted page. A page that adds its own script outside main
    changes it, which is exactly the defect.
    """
    lo = html.find("<main>")
    hi = html.find("</main>")
    assert lo != -1 and hi != -1, "page has no <main> element"
    outside = html[:lo] + html[hi + len("</main>"):]

    srcs, inline = set(), 0
    for tag, body in re.findall(r"(<script\b[^>]*>)(.*?)</script>", outside, re.S):
        m = re.search(r'src="([^"]*)"', tag)
        if m:
            srcs.add(m.group(1))
        elif body.strip():
            inline += 1
    return srcs, inline


def test_boost_is_declared_exactly_once():
    """Every conclusion in the spec rests on the nav being the only boosted
    element. If a second one appears, the analysis needs redoing."""
    src = _base_html()
    assert src.count('hx-boost="true"') == 1, (
        "hx-boost=\"true\" should appear exactly once, on the sidenav. A second "
        "boosted element changes which pages are subject to the main-only swap."
    )


def test_at_least_one_boosted_path_enumerated():
    assert BOOSTED_PATHS, "no boosted nav paths found; the enumerator is broken"


@pytest.mark.parametrize("path", BOOSTED_PATHS)
def test_boosted_page_renders_no_script_outside_main(admin_client, path, request):
    """A boosted page's JS must survive the main-only swap.

    Compared against a baseline page rather than a hardcoded list, so
    base.html's own scripts can change without touching this test.
    """
    baseline_path = BOOSTED_PATHS[0]
    baseline = admin_client.get(baseline_path)
    assert baseline.status_code == 200, f"baseline {baseline_path}: {baseline.status_code}"
    want_srcs, want_inline = _scripts_outside_main(baseline.text)

    resp = admin_client.get(path)
    assert resp.status_code == 200, f"{path}: HTTP {resp.status_code}"
    got_srcs, got_inline = _scripts_outside_main(resp.text)

    extra = got_srcs - want_srcs
    assert not extra, (
        f"{path} loads {sorted(extra)} outside <main>. A boosted navigation keeps "
        f"only <main>, so those never arrive and the page is inert. Either move "
        f"the script inside <main> or add hx-boost=\"false\" to this nav link."
    )
    assert got_inline <= want_inline, (
        f"{path} renders {got_inline - want_inline} extra inline script(s) outside "
        f"<main> (block head at 87 or block scripts at 837). A boosted navigation "
        f"discards them, leaving the page rendered but inert. Either move them "
        f"inside <main> or add hx-boost=\"false\" to this nav link."
    )
