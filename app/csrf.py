"""CSRF token helpers.

Tokens live in request.session under the key 'csrf_token'. They are issued
lazily by the auth middleware on first request after login, and rotated by
auth_routes.login on successful login.

Protected POST endpoints declare `_csrf: str = Depends(require_csrf)`.
A mismatch raises CsrfError, a 403. The 403 handler in app/main.py sends a
browser form post back to the page it came from with a warning toast
(STALE_MESSAGE), so a page left open across a login elsewhere recovers on
the next try instead of showing Access denied.
"""

import secrets

from fastapi import Form, HTTPException, Request

_SESSION_KEY = "csrf_token"

STALE_MESSAGE = "This page was out of date, so nothing was changed. Please try again."


class CsrfError(HTTPException):
    """A missing or mismatched CSRF token. Still a 403 for every caller."""

    def __init__(self):
        super().__init__(status_code=403, detail="CSRF token invalid")


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
        raise CsrfError()
    return csrf_token
