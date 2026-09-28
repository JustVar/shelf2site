"""Auth census contract tests.

The gap that started the 2026-07 hardening sweep (three unauthenticated /api
endpoints) was found by accident. These tests make that class of bug fail loud:

  - structural: every /api/* route carries an auth dependency
  - structural: every write route requires editor tier (dependency or in-body)
  - behavioral: a viewer cannot reach editor/admin surfaces
  - behavioral: a kiosk session stays confined to the map

The allowlists below are the ONLY sanctioned exceptions. Adding a route to one
is a deliberate act that shows up in review — which is the point. Keep them in
sync with docs/ENDPOINT_AUTH_CENSUS.md.
"""

import pytest
from fastapi.routing import APIRoute

import app.auth as auth_mod
from app.main import app

# require_admin / require_editor / require_viewer are closures produced by
# require_role(), so every one of them is named "dependency". Map the callable
# objects back to their module-level names by identity, or the tier check below
# silently sees no gate where one exists.
_DEP_NAME_BY_ID = {
    id(v): k for k, v in vars(auth_mod).items()
    if callable(v) and not isinstance(v, type)
}

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Routes with no auth dependency, by design. Everything else must have one.
PUBLIC_ROUTES = {
    ("GET", "/"),                         # redirect to /dashboard; target enforces
    ("GET", "/login"),                    # the login page itself
    ("POST", "/login"),                   # login form; per-IP rate limited in handler
    ("GET", "/logout"),                   # clears session only
    ("GET", "/events/stream"),            # self-authenticates: 401 anon, 403 kiosk
    ("GET", "/support"),                  # 301 redirect; target enforces
    ("GET", "/orders/"),                  # 301 redirect; target enforces
    ("GET", "/provisioning/"),            # 301 redirect; target enforces
    ("GET", "/admin/slack-bot"),          # 301 redirect; target enforces
    ("GET", "/items/{item_id}/edit"),     # 303 redirect; target page enforces
}

# Write routes that enforce editor tier INSIDE the handler rather than via a
# require_* dependency. See the census doc, "In-body checks".
IN_BODY_EDITOR_ROUTES = {
    ("POST", "/intake"),
    ("POST", "/items/{item_id}"),
    ("POST", "/items/{item_id}/receipt"),
    ("POST", "/inventory/bulk"),
    ("POST", "/inventory/quick-view/{item_id}"),
    ("POST", "/triage/bulk"),
    ("POST", "/triage/fix/{item_id}/{field_name}"),
    ("POST", "/checkout"),
    ("POST", "/checkin"),
    ("POST", "/checkout/bulk"),
    ("POST", "/checkin/bulk"),
}

# Write routes intentionally available to any authenticated user: they act only
# on the caller's own data, or are read-only exports.
SELF_SCOPED_WRITE_ROUTES = {
    ("POST", "/change-password"),                                  # own password
    ("PATCH", "/api/users/{user_id}"),                             # 403 unless self
    ("POST", "/api/errors/report"),                                # own client errors
    ("POST", "/api/contact-admin"),                                # own message
    ("POST", "/api/tours/progress"),                               # own tour state
    ("DELETE", "/api/tours/progress"),                             # own tour state (reset all)
    ("DELETE", "/api/tours/progress/{tour_id}"),                   # own tour state
    ("POST", "/api/notifications/read-all"),                       # own notifications
    ("POST", "/api/notifications/dismiss-all"),                    # own notifications
    ("POST", "/api/notifications/{notif_id}/read"),                # own notifications
    ("POST", "/api/notifications/{notif_id}/dismiss"),             # own notifications
    ("POST", "/api/notifications/subscriptions"),                  # own subscriptions
    ("PATCH", "/api/notifications/subscriptions/{sub_id}"),        # own subscriptions
    ("DELETE", "/api/notifications/subscriptions/{sub_id}"),       # own subscriptions
    ("POST", "/api/notifications/watch/{resource_type}/{resource_id}"),  # own watch
    ("POST", "/logout"),                                           # own session
}


def _walk(routes, prefix=""):
    """Flatten FastAPI 0.138 lazy _IncludedRouter wrappers into (route, prefix, extra_deps)."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield r, prefix, []
        elif type(r).__name__ == "_IncludedRouter":
            ctx = r.include_context
            inc = [d.dependency for d in (ctx.dependencies or [])]
            for sub, pfx, deps in _walk(ctx.included_router.routes, prefix + (ctx.prefix or "")):
                yield sub, pfx, deps + inc


def _name_of(call):
    return _DEP_NAME_BY_ID.get(id(call)) or getattr(call, "__name__", "")


def _dep_names(route, extra_deps):
    names = [_name_of(d) for d in extra_deps]

    def collect(dependant):
        for d in dependant.dependencies:
            if d.call is not None:
                names.append(_name_of(d.call))
            collect(d)

    collect(route.dependant)
    return names


def _has_auth_dep(names):
    return any(n == "get_current_user" or n.startswith("require_") for n in names)


def _has_tier_dep(names):
    """A require_* dependency — i.e. more than just 'be logged in'."""
    return any(n.startswith("require_") for n in names)


def _all_routes():
    out = []
    for route, prefix, extra in _walk(app.routes):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, prefix + route.path, _dep_names(route, extra)))
    return out


ALL_ROUTES = _all_routes()
API_ROUTES = [r for r in ALL_ROUTES if r[1].startswith("/api/")]
WRITE_ROUTES = [r for r in ALL_ROUTES if r[0] in WRITE_METHODS]


def test_route_table_is_not_empty():
    """Guard the guard: if route walking silently breaks, every test below passes vacuously."""
    assert len(ALL_ROUTES) > 200, f"expected the full route table, walked only {len(ALL_ROUTES)}"
    assert len(API_ROUTES) > 50


def test_dependency_names_resolve():
    """require_* deps are closures named 'dependency'; if the identity map breaks,
    the tier test below would see no gate anywhere and fail confusingly."""
    assert _name_of(auth_mod.require_editor) == "require_editor"
    assert _name_of(auth_mod.require_viewer) == "require_viewer"
    assert _name_of(auth_mod.require_system_admin) == "require_system_admin"
    seen = {n for _, _, deps in ALL_ROUTES for n in deps}
    assert "require_editor" in seen and "get_current_user" in seen


@pytest.mark.parametrize("method,path,deps", API_ROUTES, ids=lambda v: v if isinstance(v, str) else None)
def test_every_api_route_has_an_auth_dependency(method, path, deps):
    """The auth-redirect middleware lets /api/* through so routes can answer 401 JSON.

    That makes a dependency the ONLY gate on an /api route. A new /api endpoint
    with no dependency is an unauthenticated data endpoint on the LAN, which is
    exactly how /api/devices/{table}, /api/stats and /api/vendors shipped.
    """
    if (method, path) in PUBLIC_ROUTES:
        pytest.skip("documented public route")
    assert _has_auth_dep(deps), (
        f"{method} {path} has no auth dependency — it is reachable unauthenticated. "
        f"Add require_* (preferred) or get_current_user, then update the census doc."
    )


@pytest.mark.parametrize("method,path,deps", ALL_ROUTES, ids=lambda v: v if isinstance(v, str) else None)
def test_every_route_is_gated_or_explicitly_public(method, path, deps):
    if (method, path) in PUBLIC_ROUTES:
        pytest.skip("documented public route")
    assert _has_auth_dep(deps), f"{method} {path} is neither gated nor in PUBLIC_ROUTES"


@pytest.mark.parametrize("method,path,deps", WRITE_ROUTES, ids=lambda v: v if isinstance(v, str) else None)
def test_write_routes_require_more_than_login(method, path, deps):
    """A write path must require a tier, not merely a session.

    Two sanctioned escapes: handlers that check is_editor_or_above in-body for
    UX reasons, and self-scoped writes that only touch the caller's own rows.
    """
    key = (method, path)
    if key in IN_BODY_EDITOR_ROUTES or key in SELF_SCOPED_WRITE_ROUTES or key in PUBLIC_ROUTES:
        pytest.skip("documented in-body / self-scoped / public write")
    assert _has_tier_dep(deps), (
        f"{method} {path} is a write path gated only by login. Add a require_* dependency, "
        f"or list it in IN_BODY_EDITOR_ROUTES / SELF_SCOPED_WRITE_ROUTES with a reason."
    )


def test_allowlists_have_no_stale_entries():
    """A route removed from the app must not linger in an allowlist and mask a future gap."""
    live = {(m, p) for m, p, _ in ALL_ROUTES}
    for name, allowlist in [
        ("PUBLIC_ROUTES", PUBLIC_ROUTES),
        ("IN_BODY_EDITOR_ROUTES", IN_BODY_EDITOR_ROUTES),
        ("SELF_SCOPED_WRITE_ROUTES", SELF_SCOPED_WRITE_ROUTES),
    ]:
        stale = allowlist - live - {("GET", "/static")}
        assert not stale, f"{name} lists routes that no longer exist: {sorted(stale)}"


# ── Behavioral: the gates actually reject ──────────────────────────────────

def test_unauthenticated_api_is_rejected(anon):
    for path in ["/api/maintenance/status", "/api/audit-log", "/api/errors"]:
        r = anon.get(path)
        assert r.status_code == 401, f"{path} answered {r.status_code} to an anonymous caller"


def test_unauthenticated_page_redirects_to_login(anon):
    r = anon.get("/dashboard")
    assert r.status_code == 302
    assert "/login" in r.headers.get("location", "")


def test_api_docs_are_disabled(anon):
    """The interactive schema exposes the full route map; it must not be served."""
    for path in ["/docs", "/redoc", "/openapi.json"]:
        r = anon.get(path)
        assert r.status_code != 200, f"{path} is being served"


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/locks/acquire"),
    ("POST", "/api/locks/escalate"),
    ("POST", "/api/locks/heartbeat"),
    ("POST", "/api/receive/device"),
    ("GET", "/api/errors"),
    ("DELETE", "/api/admin/delete-user/999999"),
])
def test_viewer_is_rejected_from_editor_and_admin_routes(viewer_client, method, path):
    r = viewer_client.request(method, path, json={"resource_key": "items:1", "serial": "x"})
    assert r.status_code == 403, f"viewer got {r.status_code} on {method} {path}"


def test_kiosk_is_confined_to_the_map(kiosk_client):
    r = kiosk_client.get("/dashboard")
    assert r.status_code == 302 and "/map" in r.headers.get("location", "")

    # The kiosk gate must run BEFORE the /api/ passthrough, or a wall display
    # can read the full audit trail.
    r = kiosk_client.get("/api/audit-log")
    assert r.status_code == 403
    r = kiosk_client.get("/api/errors")
    assert r.status_code == 403

    # Scanner reads sit behind the same wall (audit F15 cross-check: the
    # middleware 403s kiosks before get_current_user ever runs — pin it).
    r = kiosk_client.get("/api/receive/check-duplicate?serial=CONTRACT-TEST")
    assert r.status_code == 403
    r = kiosk_client.get("/api/receive/photo/1")
    assert r.status_code == 403

    r = kiosk_client.get("/events/stream")
    assert r.status_code == 403

    r = kiosk_client.get("/map/data")
    assert r.status_code == 200


def test_map_data_answers_json_401_not_a_redirect(anon):
    """Wall displays parse JSON; a 302 to an HTML login page strands them."""
    r = anon.get("/map/data")
    assert r.status_code == 401
    assert r.json()["detail"]
