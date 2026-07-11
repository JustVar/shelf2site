"""FastAPI application for the Asset Tracker."""

import asyncio
import concurrent.futures
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .sidebar_cache import get_sidebar_counts
from .database import create_all_tables
from datetime import datetime
from app import csrf
from .routes import (
    admin, api, auth_routes, bulk,
    c2c, checkout, contact_admin, containment as containment_routes, creds,
    dashboard, disposal, error_routes, fulfillment,
    intake, intune_routes, inventory, item_detail,
    lifecycle, locks, maintenance_routes, map as map_route,
    mobile, nas_drives, notification_routes, orders, pending,
    procurement, provisioning, receipts, receiving, search,
    sites, slack_bot_routes, sse, support,
    tours, trials, unit_photos, vendors, warranty,
    zendesk_routes,
)

# ── Logging: surface INFO-level messages from app.* modules to stdout ────────
# Uvicorn configures its own loggers but doesn't propagate our app loggers.
# We attach a dedicated StreamHandler to the 'app' logger so logger.info()
# calls in any app.* module (sse, locks, intake, etc.) reach docker logs.
# Narrow scope avoids enabling debug spam from sqlalchemy/asyncpg/etc.
import logging as _logging
_app_logger = _logging.getLogger("app")
if not any(isinstance(h, _logging.StreamHandler) for h in _app_logger.handlers):
    _app_handler = _logging.StreamHandler()
    _app_handler.setFormatter(_logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _app_logger.addHandler(_app_handler)
    _app_logger.setLevel(_logging.INFO)
    _app_logger.propagate = False  # prevent double-logging via uvicorn's root handler

# Root path for reverse proxy sub-path deployment (e.g. "/inventory")
BP = settings.ROOT_PATH.rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: create tables on startup."""
    create_all_tables()

    # Size the thread pool for the expected concurrent user count.
    # def route handlers run here; 40 threads handles 20+ users with bursts.
    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=40, thread_name_prefix="at-worker")
    loop.set_default_executor(executor)



    # Start lock cleanup background task
    from .locks import start_lock_cleanup
    lock_cleanup_task = start_lock_cleanup()

    # Start SSE pub/sub over Postgres LISTEN/NOTIFY so events fan out to all workers.
    from .routes.sse import start_sse_pubsub, stop_sse_pubsub
    await start_sse_pubsub()

    yield

    await stop_sse_pubsub()

    lock_cleanup_task.cancel()
    try:
        await lock_cleanup_task
    except asyncio.CancelledError:
        pass

    executor.shutdown(wait=False)


app = FastAPI(
    title="Asset Tracker",
    description="Hardware asset tracker for Company",
    version="2.0.0",
    lifespan=lifespan,
    # No interactive API docs in production — /docs, /redoc and /openapi.json
    # would expose the full route map to any logged-in user (2026-07 auth census).
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Static files and templates
_base_dir = Path(__file__).resolve().parent.parent
_static_dir = _base_dir / "static"

# Derive the stylesheet cache-bust from main.css content so it updates
# automatically on any CSS change. Computed once at startup; a redeploy (restart)
# recomputes it. Kills the manual ?v= bump that silently broke returning users.
_main_css_path = _static_dir / "css" / "main.css"
_fl_css_path = _static_dir / "css" / "fl-restyle.css"


def _compute_css_version():
    try:
        import hashlib
        return hashlib.sha1(_main_css_path.read_bytes()).hexdigest()[:10]
    except Exception:
        return "0"


CSS_VERSION = _compute_css_version()


def _compute_fl_css_version():
    try:
        import hashlib
        return hashlib.sha1(_fl_css_path.read_bytes()).hexdigest()[:10]
    except Exception:
        return "0"


FL_CSS_VERSION = _compute_fl_css_version()

_mobile_css_path = _static_dir / "css" / "mobile.css"


def _compute_mobile_css_version():
    try:
        import hashlib
        return hashlib.sha1(_mobile_css_path.read_bytes()).hexdigest()[:10]
    except Exception:
        return "0"


MOBILE_CSS_VERSION = _compute_mobile_css_version()
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
templates = Jinja2Templates(directory=str(_base_dir / "app" / "templates"))

# Make base_path available in all templates automatically
templates.env.globals["base_path"] = BP


# Error logging middleware — captures unhandled exceptions and logs to error_log table
@app.middleware("http")
async def error_logging_middleware(request: Request, call_next):
    import traceback
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        # Log to DB
        try:
            from .routes.error_routes import log_error
            from .auth import get_session_user_id
            user_id = get_session_user_id(request)
            log_error(
                source="backend",
                message=str(exc),
                stack=traceback.format_exc(),
                url=str(request.url.path),
                user_id=user_id,
                browser=request.headers.get("user-agent", ""),
            )
        except Exception:
            pass  # Never let error logging break the request
        raise


# Security headers middleware — outermost layer, runs on every response
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    # Prevent MIME-type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    # Limit referrer information sent to other sites
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Disable unnecessary browser features
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # HSTS — only send when the request arrived over HTTPS (via nginx).
    # Sending on HTTP causes Chrome to cache HSTS for the IP, breaking
    # fetch() calls from HTTP pages (CORS mixed-content failure).
    if request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Allow the service worker (at /static/sw.js) to claim the full app scope.
    # Without this header the browser restricts SW scope to /inventory/static/ only.
    if path.endswith("/sw.js"):
        response.headers["Service-Worker-Allowed"] = f"{BP}/"
    # No-store on dynamic HTML so a boosted navigation or back-forward cache never
    # serves a stale page after a deploy. Static assets are unaffected (their own
    # ?v= cache-busting + SW stale-while-revalidate handle them). Fixes the class
    # where an HTML change rides in but the browser reuses the old document.
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Sidebar counts middleware — injects triage_count + pending_count into
# request.state on every authenticated page request. Used by base.html nav badge
# and support.html review-queue cards. Falls back to zeros on any error so a
# bad DB query can never block a page load.
@app.middleware("http")
async def sidebar_counts_middleware(request: Request, call_next):
    path = request.url.path
    rel = path[len(BP):] if path.startswith(BP) else path
    # Skip static + SSE — neither renders a template.
    if rel.startswith("/static") or rel.startswith("/events/stream"):
        return await call_next(request)

    request.state.triage_count = 0
    request.state.pending_count = 0
    request.state.asset_v = CSS_VERSION
    request.state.flcss_v = FL_CSS_VERSION
    request.state.mobilecss_v = MOBILE_CSS_VERSION

    from .auth import get_session_user_id
    user_id = get_session_user_id(request)
    if user_id is None:
        # Unauthenticated (login, etc.) — leave counts at 0, skip DB work.
        return await call_next(request)

    from .database import SessionLocal
    from .models import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        counts = get_sidebar_counts(db, user)
        request.state.triage_count = counts.get("triage_count", 0)
        request.state.pending_count = counts.get("pending_count", 0)
    except Exception as e:
        _app_logger.warning("sidebar_counts middleware failed: %s", e)
    finally:
        db.close()

    return await call_next(request)


# Mobile launcher middleware — phones get the field-action launcher instead
# of desktop-dense pages (decision 2026-07-09; see app/routes/mobile.py).
# UX ROUTING ONLY: access control (incl. map_kiosk confinement) lives in
# auth_redirect_middleware below, which runs BEFORE this one — Starlette
# middleware is LIFO, so being DEFINED earlier makes this one run LATER.
# Never touches: non-GET, HTMX fragments, non-HTML requests, static/API/SSE,
# auth + kiosk paths, kiosk sessions, unauthenticated requests (already
# bounced to /login upstream), or the field pages themselves. The launcher's
# "View Desktop Version" sets session["desktop_view"], which stands this
# middleware down until logout (logout_user() clears the session).
@app.middleware("http")
async def mobile_launcher_middleware(request: Request, call_next):
    if request.method != "GET":
        return await call_next(request)
    path = request.url.path
    rel = path[len(BP):] if path.startswith(BP) else path
    if rel.startswith(("/static", "/api", "/events", "/login", "/logout",
                       "/change-password", "/map")):
        return await call_next(request)
    sess = request.session
    if (not sess.get("session_user_id")
            or sess.get("desktop_view")
            or sess.get("role") == "map_kiosk"):
        return await call_next(request)
    if request.headers.get("HX-Request") == "true":
        return await call_next(request)
    if "text/html" not in request.headers.get("accept", ""):
        return await call_next(request)
    if not mobile.is_phone_ua(request.headers.get("user-agent", "")):
        return await call_next(request)
    if mobile.path_is_mobile_allowed(rel) or mobile.path_is_mobile_exempt(rel):
        return await call_next(request)
    return RedirectResponse(f"{BP}/mobile", status_code=302)


# Auth redirect middleware: redirect unauthenticated requests to /login
@app.middleware("http")
async def auth_redirect_middleware(request: Request, call_next):
    """Redirect to login for unauthenticated browser requests.

    Exceptions: /login, /static, /events/stream
    """
    path = request.url.path
    # Strip ROOT_PATH prefix so checks work for both direct and proxied requests
    rel = path[len(BP):] if path.startswith(BP) else path
    public_prefixes = ("/login", "/static")
    if any(rel.startswith(p) for p in public_prefixes):
        return await call_next(request)

    # Check session
    user_id = request.session.get("session_user_id")

    # Map kiosk confinement runs BEFORE the API and SSE passthroughs - the
    # lock is only as strong as its position in this chain. A kiosk session
    # may reach the map, its data feed, logout and the forced password
    # change flow; API paths answer 403 JSON, everything else bounces to
    # the map. Reads the session role set at login (stale until re-login on
    # role change, the same trade-off the forced-change gate makes).
    if user_id and request.session.get("role") == "map_kiosk":
        _kiosk_allowed = ("/map", "/logout", "/change-password")
        if not any(rel == a or rel.startswith(a + "/") for a in _kiosk_allowed):
            if rel.startswith("/api/") or rel.startswith("/events/"):
                return JSONResponse(status_code=403, content={"detail": "Map kiosk sessions are restricted to the map"})
            return RedirectResponse(f"{BP}/map/", status_code=302)
        # Sliding session for wall displays: mutating the session re-issues
        # the cookie with a fresh max_age. Throttled to once per hour.
        _hour = int(datetime.utcnow().timestamp() // 3600)
        if request.session.get("kiosk_ts") != _hour:
            request.session["kiosk_ts"] = _hour

    # SSE endpoint authenticates its own session (and rejects kiosks)
    if rel.startswith("/events/stream"):
        return await call_next(request)

    # Let API endpoints return 401 instead of redirect
    if rel.startswith("/api/"):
        return await call_next(request)

    # The map data feed behaves like an API for session expiry: JSON 401 so
    # the client can prompt re-login instead of parsing a redirected HTML
    # page (wall-mounted kiosk displays hit this after cookie expiry).
    if rel.startswith("/map/data") and user_id is None:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    if user_id is None and rel not in ("/", "/login"):
        return RedirectResponse(f"{BP}/login", status_code=302)

    # Issue a CSRF token for any authenticated session (covers live sessions too).
    if user_id:
        csrf.ensure_token(request)

    # Password expiry (session-anchored, no DB per request). password_expires_at is set at
    # login; when it passes, flag the session so the forced-change redirect below fires, and
    # expose the remaining days to the warning banner.
    if settings.PASSWORD_MAX_AGE_DAYS > 0 and user_id and not request.session.get("must_change_password"):
        _pexp = request.session.get("password_expires_at")
        if _pexp:
            try:
                _secs = (datetime.fromisoformat(_pexp) - datetime.utcnow()).total_seconds()
                if _secs <= 0:
                    request.session["must_change_password"] = True
                else:
                    _days = (int(_secs) + 86399) // 86400
                    if _days <= settings.PASSWORD_WARN_DAYS:
                        request.state.pwd_warn_days = _days
            except (ValueError, TypeError):
                pass

    # Force password change redirect: only allow /change-password and /logout
    if user_id and request.session.get("must_change_password"):
        allowed = ("/change-password", "/logout")
        if not any(rel.startswith(a) for a in allowed):
            return RedirectResponse(f"{BP}/change-password", status_code=302)

    return await call_next(request)


# Session middleware — added AFTER auth middleware so it processes requests FIRST
# (Starlette middleware stack is LIFO: last added = outermost = runs first)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    session_cookie="inventory_session",
    max_age=86400,  # 24 hours
    same_site="lax",
    https_only=settings.HTTPS_ONLY,  # True when behind Cloudflare/HTTPS; False for LAN HTTP & tests
)


# Exception handlers for better UX
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """Custom handler for HTTP exceptions to provide user-friendly error pages."""
    # For 403 Forbidden errors, show a nice permission denied page
    if exc.status_code == 403:
        # U4c — HTMX branch. Returning HX-Refresh forces the browser to do a
        # full navigation to the current URL, which then hits this handler
        # again as a plain HTML request, falling through to the template
        # render below. Without this, hx-boost'd nav links would swap the 403
        # page into <main>, leaving the rest of the app shell intact — same
        # broken pattern that hit the logout link in U4b.
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=403, headers={"HX-Refresh": "true"})

        # U4c — JSON branch. If the caller wants JSON (API consumer, fetch
        # with Accept: application/json, or no Accept at all), preserve the
        # default FastAPI shape so programmatic consumers keep getting clean
        # errors.
        accept = request.headers.get("accept", "")
        if "text/html" not in accept:
            return JSONResponse(
                status_code=403,
                content={"detail": exc.detail},
            )

        # Get user from session for displaying current role
        from .auth import get_session_user_id
        from .database import SessionLocal
        from .models import User

        user = None
        user_id = get_session_user_id(request)
        if user_id:
            def _fetch_user():
                db = SessionLocal()
                try:
                    return db.query(User).filter(User.id == user_id).first()
                finally:
                    db.close()
            import asyncio
            user = await asyncio.to_thread(_fetch_user)

        return templates.TemplateResponse(
            "permission_denied.html",
            {
                "request": request,
                "user": user,
                "message": exc.detail,
                "required_permission": getattr(exc, "required_permission", None),
                "show_contact_admin": True,
            },
            status_code=403,
        )

    # For 401 Unauthorized — API calls get JSON, pages get a redirect
    if exc.status_code == 401:
        req_path = request.url.path
        rel = req_path[len(BP):] if req_path.startswith(BP) else req_path
        if rel.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )
        return RedirectResponse(url=f"{BP}/login", status_code=303)

    # For other HTTP exceptions, re-raise to use default handler
    raise exc


# Routes
@app.get("/")
def root_redirect():
    return RedirectResponse(url=f"{BP}/dashboard", status_code=302)

app.include_router(auth_routes.router)
app.include_router(dashboard.router)
app.include_router(inventory.router)
app.include_router(intake.router)
app.include_router(checkout.router)
app.include_router(item_detail.router)
from .routes.triage import router as triage_router
app.include_router(triage_router)
app.include_router(support.router)
app.include_router(map_route.router, prefix="/map")
app.include_router(api.router, prefix="/api")
app.include_router(creds.router, prefix="/api/credentials")
app.include_router(pending.router, prefix="/api")
app.include_router(admin.router)
app.include_router(receiving.router)
app.include_router(unit_photos.router)
app.include_router(warranty.router)
app.include_router(trials.router)
app.include_router(disposal.router)
app.include_router(nas_drives.router)
app.include_router(procurement.router)
app.include_router(receipts.router)
app.include_router(fulfillment.router)
app.include_router(c2c.router)
app.include_router(provisioning.router)
app.include_router(orders.router)
app.include_router(sites.router)
app.include_router(search.router)
app.include_router(bulk.router)
app.include_router(locks.router, prefix="/api")
app.include_router(tours.router)
app.include_router(zendesk_routes.router)
app.include_router(lifecycle.router)
app.include_router(notification_routes.router)
app.include_router(vendors.router)
app.include_router(slack_bot_routes.router)
app.include_router(intune_routes.router)
app.include_router(maintenance_routes.router)
app.include_router(mobile.router)
app.include_router(containment_routes.router)
app.include_router(error_routes.router)
app.include_router(sse.router, prefix="/events")
app.include_router(contact_admin.router)
