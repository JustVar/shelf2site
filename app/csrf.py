"""CSRF token helpers.

Tokens live in request.session under the key 'csrf_token'. They are issued
lazily by the auth middleware on first request after login, and rotated by
auth_routes.login on successful login.

Protected POST endpoints declare `csrf_token: str = Depends(require_csrf)`
or use `Depends(verify_csrf)` directly; mismatches raise 403.
"""

import secrets

from fastapi import Form, HTTPException, Request

_SESSION_KEY = "csrf_token"


def ensure_token(request: Request) -> str:
    """Return the session's CSRF token, generating one if absent."""
    token = request.session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_SESSION_KEY] = token
    return token


def rotate_token(request: Request) -> str:
    """Generate a fresh token, replacing any existing one. Call on login."""
    token = secrets.token_urlsafe(32)
    request.session[_SESSION_KEY] = token
    return token


def clear_token(request: Request) -> None:
    """Remove the token. Call on logout (session is cleared anyway, but explicit)."""
    request.session.pop(_SESSION_KEY, None)


def verify(request: Request, submitted: str) -> bool:
    """Constant-time compare submitted token against session token."""
    expected = request.session.get(_SESSION_KEY) or ""
    if not expected or not submitted:
        return False
    return secrets.compare_digest(expected, submitted)


def require_csrf(request: Request, csrf_token: str = Form(default="")) -> str:
    """FastAPI dependency: validates the `csrf_token` form field. 403 on missing or mismatched."""
    if not verify(request, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")
    return csrf_token
