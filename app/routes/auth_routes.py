"""Authentication routes: login, logout, password change."""

import time
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Login rate limiting — 5 failed attempts per 60 seconds per IP.
# Uses CF-Connecting-IP (Cloudflare) or X-Forwarded-For (other proxies)
# so the real client IP is tracked, not the tunnel's localhost address.
# ---------------------------------------------------------------------------
_failed_logins: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60   # seconds
_MAX_ATTEMPTS = 5   # failed attempts before lockout


def _client_ip(request: Request) -> str:
    """Return the real client IP, honoring Cloudflare and proxy headers."""
    # Cloudflare sets CF-Connecting-IP to the original client IP
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    # Generic forwarded header (set by uvicorn --proxy-headers)
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW
    _failed_logins[ip] = [t for t in _failed_logins[ip] if t > cutoff]
    return len(_failed_logins[ip]) >= _MAX_ATTEMPTS


def _record_failure(ip: str) -> None:
    _failed_logins[ip].append(time.monotonic())

from ..audit import log_event
from ..auth import (
    authenticate_user, get_current_user, get_session_user_id,
    hash_password, login_user, logout_user, verify_password, validate_password_strength,
)
from ..config import settings
from ..database import get_db
from ..models import User

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Render the login page. Redirect if already logged in."""
    if get_session_user_id(request) is not None:
        return RedirectResponse(f"{BP}/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
    })


@router.post("/login")
async def login_submit(request: Request, db: Session = Depends(get_db)):
    """Validate credentials and create a session."""
    ip = _client_ip(request)
    if _is_rate_limited(ip):
        log_event(db, "user_login_failed", request=request,
                  details=f"Rate-limited login from {ip}")
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Too many failed attempts. Please wait a minute and try again.",
        }, status_code=429)

    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "")

    user = authenticate_user(db, username, password)
    if user is None:
        _record_failure(ip)
        log_event(
            db, "user_login_failed",
            request=request,
            details=f"Failed login attempt for username: {username}",
        )
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password.",
        }, status_code=401)

    login_user(request, user)
    log_event(
        db, "user_login",
        request=request,
        user_id=user.id,
        details=f"{user.display_name} logged in",
    )

    # Redirect to password change if required
    if user.must_change_password:
        return RedirectResponse(f"{BP}/change-password", status_code=302)

    return RedirectResponse(f"{BP}/dashboard", status_code=302)


@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Render the password change page."""
    return templates.TemplateResponse("change_password.html", {
        "request": request,
        "user": user,
        "forced": user.must_change_password,
        "error": None,
        "success": None,
    })


@router.post("/change-password")
async def change_password_submit(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Validate and change the user's password."""
    form = await request.form()
    current_password = form.get("current_password", "")
    new_password = form.get("new_password", "")
    confirm_password = form.get("confirm_password", "")

    # Validate current password
    if not verify_password(current_password, user.password_hash):
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "forced": user.must_change_password,
            "error": "Current password is incorrect.",
            "success": None,
        }, status_code=400)

    # Validate new password strength
    strength_error = validate_password_strength(new_password)
    if strength_error:
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "forced": user.must_change_password,
            "error": strength_error,
            "success": None,
        }, status_code=400)

    if new_password != confirm_password:
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "forced": user.must_change_password,
            "error": "New passwords do not match.",
            "success": None,
        }, status_code=400)

    if verify_password(new_password, user.password_hash):
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "forced": user.must_change_password,
            "error": "New password must be different from your current password.",
            "success": None,
        }, status_code=400)

    # Update password
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.utcnow()
    db.commit()

    # Clear the session flag so middleware stops redirecting
    request.session["must_change_password"] = False

    log_event(
        db, "password_changed",
        request=request,
        user_id=user.id,
        details=f"{user.display_name} changed their password",
    )

    return templates.TemplateResponse("change_password.html", {
        "request": request,
        "user": user,
        "forced": False,
        "error": None,
        "success": "Password changed successfully. You can now continue to the dashboard.",
    })


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    """Clear session and redirect to login."""
    user_id = get_session_user_id(request)
    if user_id:
        log_event(
            db, "user_logout",
            request=request,
            user_id=user_id,
            details="User logged out",
        )
    logout_user(request)
    return RedirectResponse(f"{BP}/login", status_code=302)
