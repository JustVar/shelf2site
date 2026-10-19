"""Mobile launcher page + phone routing helpers.

Decision (2026-07-09): mobile support is scoped to the FIELD PAGES —
Receive & Scan, Check Out, Check In, Global Search, Item Detail. Phones
are routed to a simple launcher (/mobile) for everything else; tablets
(>=768px viewports / non-phone user agents) are treated as desktop.

This is UX ROUTING ONLY, not access control. The map_kiosk confinement in
auth_redirect_middleware (app/main.py) remains the only access-enforcement
mechanism and is unaffected by the desktop-view flag.

Pieces:
- is_phone_ua() / path_is_mobile_allowed(): shared classifiers used by
  mobile_launcher_middleware (app/main.py) and the login redirect
  (app/routes/auth_routes.py).
- GET /mobile: the launcher page (any logged-in user; fine on desktop too).
- GET /mobile/desktop: the escape hatch — sets session["desktop_view"] so
  the redirect stands down until logout (logout_user() clears the session).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import get_current_user
from ..config import settings
from ..localtime import register
from ..models import User

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)

# BP-stripped path prefixes phones may open directly; anything else GET-HTML
# redirects to the launcher. Field pages and their fragments only — static,
# /api/*, SSE, and auth paths are skipped by earlier checks in the middleware.
MOBILE_ALLOWED_PREFIXES = (
    "/mobile",    # the launcher itself + /mobile/desktop
    "/receive",   # Receive & Scan
    "/checkout",  # Check Out
    "/checkin",   # Check In
    "/search",    # Global Search (+ /search/results fragment)
    "/items",     # Item Detail (deep links work directly)
)


def is_phone_ua(ua: str) -> bool:
    """True for phone-class user agents.

    Tablets deliberately count as desktop: iPads report Macintosh (or
    'iPad', which is not matched) and Android tablets lack the 'Mobile'
    token that Android phones carry.
    """
    ua = ua.lower()
    if "iphone" in ua or "ipod" in ua or "windows phone" in ua:
        return True
    return "android" in ua and "mobile" in ua


def path_is_mobile_allowed(rel: str) -> bool:
    """True when the BP-stripped path is a field page phones keep as-is."""
    return any(rel == p or rel.startswith(p + "/") for p in MOBILE_ALLOWED_PREFIXES)


def path_is_mobile_exempt(rel: str) -> bool:
    """File/export GET endpoints reachable by deep link from a phone.

    These return FileResponse/StreamingResponse, not pages — redirecting
    them to the launcher would silently eat the download. (Field-page
    downloads live under /api and are already skipped wholesale.)
    """
    if rel.startswith("/receipts/") and rel.endswith("/file"):
        return True
    return rel.startswith((
        "/fulfillment/certifications/files/",
        "/fulfillment/install-cert/",
        "/fulfillment/c2c/files/",
        "/inventory/export",
        "/triage/export",
    ))


@router.get("/mobile", response_class=HTMLResponse)
def mobile_launcher(request: Request, user: User = Depends(get_current_user)):
    """Field-action launcher for phones."""
    return templates.TemplateResponse(request, "mobile_launcher.html", {
        "request": request,
        "user": user,
    })


@router.get("/mobile/desktop")
def mobile_desktop_escape(request: Request, user: User = Depends(get_current_user)):
    """'View desktop version' — disable the phone redirect until logout."""
    request.session["desktop_view"] = True
    return RedirectResponse(f"{BP}/dashboard", status_code=302)
