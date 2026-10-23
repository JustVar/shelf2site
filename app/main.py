"""FastAPI application for Shelf2Site."""

import asyncio
import json
import concurrent.futures
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import DataError
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .localtime import register
from .sidebar_cache import get_sidebar_counts
from .database import create_all_tables
from datetime import datetime
from app import csrf
from app.toast_redirect import toast_redirect
from urllib.parse import urlsplit
from .routes import (
    admin, api, auth_routes,
    c2c, checkout, contact_admin, containment as containment_routes, creds,
    dashboard, error_routes, fulfillment,
    intake, inventory, item_detail,
    locks, maintenance_routes, map as map_route,
    mobile, notification_routes, order_flow, orders, pending,
    provisioning, receipts, receiving, search,
    sites, slack_bot_routes, sse, support,
    tours, unit_photos, vendors, warranty,
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
    title="Shelf2Site",
    description="Hardware inventory and fulfillment, from shelf to site",
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


# Static-asset content-hash cache-bust (JS + CSS), delivered via request.state
# (see sidebar_counts_middleware) so it reaches every per-route Jinja2Templates
# instance, not just this module's env.
# Keyed on (rel, mtime_ns): stat() every call, sha1 recomputed only when the file
# changes on disk, so edits are picked up WITHOUT a restart. Returns "0" on any
# error, so a bad path can never raise into a template.
_asset_hash_cache = {}


def _asset_version(rel):
    try:
        p = _static_dir / rel
        mtime = p.stat().st_mtime_ns
        cached = _asset_hash_cache.get(rel)
        if cached is None or cached[0] != mtime:
            import hashlib
            digest = hashlib.sha1(p.read_bytes(), usedforsecurity=False).hexdigest()[:10]
            _asset_hash_cache[rel] = (mtime, digest)
            return digest
        return cached[1]
    except Exception:
        return "0"


if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
templates = Jinja2Templates(directory=str(_base_dir / "app" / "templates"))

# Make base_path available in all templates automatically
templates.env.globals["base_path"] = BP
register(templates.env)


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


# Request hygiene: refuse cross-site writes and NUL bytes before any route runs.
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _cross_site_write(request: Request) -> bool:
    """True when a browser says this write came from another site.

    The session cookie is SameSite=Lax, which already keeps it off most
    cross-site writes; this is the second wall. Sec-Fetch-Site is sent by
    current browsers; Origin covers the rest. A request with neither (curl,
    the test client, server-to-server) is not a browser forgery and passes.
    """
    if request.method not in _UNSAFE_METHODS:
        return False
    if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
        return True
    origin = request.headers.get("origin")
    if origin is None:
        return False
    if origin == "null":
        return True
    allowed = {request.headers.get("host", "")}
    fwd_host = request.headers.get("x-forwarded-host")
    if fwd_host:
        allowed.add(fwd_host.split(",")[0].strip())
    base = urlsplit(settings.APP_BASE_URL or "").netloc
    if base:
        allowed.add(base)
    return urlsplit(origin).netloc not in allowed


@app.middleware("http")
async def request_hygiene_middleware(request: Request, call_next):
    if "\x00" in request.url.path or "%00" in request.url.query.lower() or "\x00" in request.url.query:
        return JSONResponse(status_code=400, content={"detail": "Invalid character in the address"})
    if _cross_site_write(request):
        _app_logger.warning("Refused a cross-site %s to %s from %s", request.method, request.url.path,
                            request.headers.get("origin") or request.headers.get("sec-fetch-site"))
        return JSONResponse(status_code=403, content={"detail": "Cross-site request refused"})
    # Every JSON write route takes an object. Refuse anything else here, once,
    # instead of each route failing on body.get() with a server error.
    if (request.method in _UNSAFE_METHODS
            and request.headers.get("content-type", "").split(";")[0].strip() == "application/json"):
        raw = await request.body()
        if raw.strip():
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            if not isinstance(parsed, dict):
                message = "The request body must be a JSON object"
                return JSONResponse(status_code=400, content={"detail": message, "error": message})
    return await call_next(request)


# Security headers middleware — outermost layer, runs on every response
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    # Prevent MIME-type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    # Limit referrer information sent to other sites
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Disable unnecessary browser features. camera=(self) — NOT camera=() —
    # because the barcode scanner and photo capture call getUserMedia from
    # our own origin (H13); an empty allowlist denies camera even to self,
    # which no amount of HTTPS or CA trust can override.
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    # HSTS — only send when the request arrived over HTTPS (via nginx).
    # Sending on HTTP causes Chrome to cache HSTS for the IP, breaking
    # fetch() calls from HTTP pages (CORS mixed-content failure).
    if request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # No-store on dynamic HTML so a boosted navigation or back-forward cache never
    # serves a stale page after a deploy. Static assets are unaffected (their own
    # ?v= cache-busting and nginx immutable caching handle them). Fixes the class
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
    # Set FIRST, before any early return: js_v is a CALLABLE, and a missing
    # callable raises UndefinedError (->500) rather than degrading to falsy like a
    # missing string would. Unconditional here means every render path -- authed,
    # unauthed, kiosk, static-skip -- carries it.
    request.state.js_v = _asset_version
    path = request.url.path
    rel = path[len(BP):] if path.startswith(BP) else path
    # Skip static + SSE — neither renders a template.
    if rel.startswith("/static") or rel.startswith("/events/stream"):
        return await call_next(request)

    request.state.triage_count = 0
    request.state.pending_count = 0
    request.state.delete_request_count = 0

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
        request.state.delete_request_count = counts.get("delete_request_count", 0)
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


class SecureSessionCookieMiddleware:
    """Add the Secure attribute to the session cookie on HTTPS requests only.

    We keep this DYNAMIC (decided per request from the scheme) rather than a
    static ``https_only`` flag on SessionMiddleware. The in-container contract
    suite drives the app over plain http://127.0.0.1:8081, and httpx refuses to
    send a Secure cookie back over an http origin — a static Secure flag would
    silently log every fixture out. In production a reverse proxy terminates
    TLS and forwards ``X-Forwarded-Proto: https``; uvicorn trusts that header
    from the proxies in FORWARDED_ALLOW_IPS, so ``scope['scheme']`` reads
    'https' and we add the flag. Over plain http the cookie stays non-Secure and the suite passes.

    Registered AFTER SessionMiddleware so it is the outermost middleware and its
    send hook runs last — after SessionMiddleware has appended Set-Cookie.
    """

    def __init__(self, app, cookie_name: str):
        self.app = app
        self._prefix = (cookie_name + "=").encode("latin-1")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("scheme") != "https":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers")
                if headers:
                    message["headers"] = [
                        (k, v + b"; Secure")
                        if (k.lower() == b"set-cookie"
                            and v.startswith(self._prefix)
                            and b"secure" not in v.lower())
                        else (k, v)
                        for k, v in headers
                    ]
            await send(message)

        await self.app(scope, receive, send_wrapper)


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

# Outermost middleware: promote the session cookie to Secure on HTTPS requests.
# See SecureSessionCookieMiddleware — must be added after SessionMiddleware.
app.add_middleware(SecureSessionCookieMiddleware, cookie_name="inventory_session")


def _same_app_referer(request: Request) -> str:
    """Path and query of the Referer when it points inside this app, else the dashboard.

    Only the path is kept, so the redirect never leaves this host. A browser
    sends a normalised Referer; a forged one only redirects the forger.
    """
    parts = urlsplit(request.headers.get("referer", ""))
    path = parts.path
    if path.startswith(BP + "/") and not path.startswith("//"):
        return path + ("?" + parts.query if parts.query else "")
    return f"{BP}/dashboard"


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

        # A stale CSRF token from a browser form: the page was loaded before a
        # login elsewhere replaced the session token (board N10). Nothing ran.
        # Send the user back with a warning; the reloaded page carries the
        # current token, so the next try succeeds.
        if isinstance(exc, csrf.CsrfError):
            return toast_redirect(_same_app_referer(request), csrf.STALE_MESSAGE, "warning")

        user = await _session_user(request)
        return templates.TemplateResponse(
            request, "permission_denied.html",
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

    # Every other code: a 404 for a page gets the not-found page, the rest
    # FastAPI's default JSON shape.
    return await _not_found_or_default(request, exc)


async def _session_user(request: Request):
    """The signed-in user, or None. Read off the session cookie in a worker
    thread, because exception handlers run outside route dependencies."""
    from .auth import get_session_user_id
    from .database import SessionLocal
    from .models import User

    user_id = get_session_user_id(request)
    if not user_id:
        return None

    def _fetch_user():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        finally:
            db.close()
    return await asyncio.to_thread(_fetch_user)


async def _not_found_or_default(request: Request, exc):
    """A browser asking for a page that does not exist gets a page inside the
    app shell (or the login page when signed out). API callers, HTMX swaps and
    every other status keep FastAPI's default JSON response."""
    rel = request.url.path[len(BP):] if request.url.path.startswith(BP) else request.url.path
    wants_page = ("text/html" in request.headers.get("accept", "")
                  and request.headers.get("HX-Request") != "true"
                  and not rel.startswith(("/api/", "/static/")))
    if exc.status_code != 404 or not wants_page:
        return await http_exception_handler(request, exc)
    user = await _session_user(request)
    if user is None:
        return RedirectResponse(url=f"{BP}/login", status_code=303)
    return templates.TemplateResponse(
        request, "not_found.html", {"request": request, "user": user}, status_code=404)


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Unknown paths and wrong methods are raised by the router as Starlette's
    HTTPException, which the handler above does not see."""
    return await _not_found_or_default(request, exc)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """psycopg2 raises ValueError for a NUL byte in a string it is about to
    send. That is bad input, not a server fault. Any other ValueError is a
    real bug: re-raised, so the error log middleware records it as a 500."""
    if isinstance(exc, json.JSONDecodeError):
        message = "The request body must be JSON"
        return JSONResponse(status_code=400, content={"detail": message, "error": message})
    if "NUL (0x00)" in str(exc):
        return JSONResponse(status_code=400, content={"detail": "Invalid character in the input",
                                                      "error": "Invalid character in the input"})
    raise exc


@app.exception_handler(DataError)
async def data_error_handler(request: Request, exc: DataError):
    """A value the database refuses for its column (too long, out of range, not
    a valid date or number) is the caller's mistake, so answer 400 instead of
    a server error. The request's session is rolled back when it closes."""
    _app_logger.warning("Refused a value the database rejected on %s %s: %s",
                        request.method, request.url.path, str(exc.orig).splitlines()[0] if exc.orig else exc)
    message = "A value is too long or not valid for its field."
    return JSONResponse(status_code=400, content={"detail": message, "error": message})


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
app.include_router(receipts.router)
app.include_router(fulfillment.router)
app.include_router(c2c.router)
app.include_router(provisioning.router)
app.include_router(orders.router)
app.include_router(order_flow.router)
app.include_router(sites.router)
app.include_router(search.router)
app.include_router(locks.router, prefix="/api")
app.include_router(tours.router)
app.include_router(zendesk_routes.router)
app.include_router(notification_routes.router)
app.include_router(vendors.router)
app.include_router(slack_bot_routes.router)
app.include_router(maintenance_routes.router)
app.include_router(mobile.router)
app.include_router(containment_routes.router)
app.include_router(error_routes.router)
app.include_router(sse.router, prefix="/events")
app.include_router(contact_admin.router)
from .routes import delete_requests as delete_requests_routes
app.include_router(delete_requests_routes.router)
