"""User authentication: bcrypt password hashing, session management, role checks."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
import bcrypt
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User, ADMIN_LEVEL_ROLES
from .password_blocklist import is_blocked
from .password_rules import check_composition


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

# bcrypt only consumes the first 72 bytes of a password. bcrypt 4.x does NOT
# raise past that — it truncates silently, so two passwords sharing their first
# 72 bytes verify as equal. We therefore reject oversized input where it is SET
# (validate_password_strength), not where it is verified: an existing account
# whose password predates this rule has a hash of its truncated form, and
# rejecting at verify time would lock that user out with "invalid password".
BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def validate_password_strength(password: str, username: str | None = None) -> str | None:
    """Return an error message if the password is too weak, or None if it passes.

    NIST SP 800-63B Rev 4: favor length over character-class composition, and screen against
    a breached/common blocklist plus context-specific words. No upper/lower/digit rules.
    - At least PASSWORD_MIN_LENGTH characters
    - At most 72 bytes — past that bcrypt silently ignores the tail, so a longer
      password would offer no more protection than its first 72 bytes
    - Not in the offline breached/common-password blocklist
    - Not a structural pattern: repetition, a sequence, a keyboard walk, or a
      password containing a context word (see app/password_rules.py)

    `username` is optional so the helper stays callable without an account in hand; pass it
    wherever it is known, or the "must not contain your username" rule cannot fire.
    """
    # Measure the string the blocklist lookup will actually see. is_blocked() normalizes
    # with .strip(), and the loader keeps only entries at least PASSWORD_MIN_LENGTH long,
    # so a raw-length check would let "monkey123      " (nine characters of secret, padded
    # to fifteen) clear the minimum and then miss every short breach entry.
    if len(password.strip()) < settings.PASSWORD_MIN_LENGTH:
        return f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters."
    # The byte cap measures the RAW password: that is what bcrypt hashes.
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        return "Password is too long — use at most 72 characters."
    if is_blocked(password):
        return "This password has appeared in known breaches or is too common. Choose a different one."
    return check_composition(password, username)


# ---------------------------------------------------------------------------
# Session helpers (cookie-based via itsdangerous)
# ---------------------------------------------------------------------------

SESSION_KEY = "session_user_id"


def login_user(request: Request, user: User):
    """Store user ID in the session after successful authentication."""
    # A different user logging in over a live session must not inherit the
    # previous user's mobile desktop-view preference (routes/mobile.py);
    # same-user re-login keeps it (documented: flag lives until logout).
    if request.session.get(SESSION_KEY) not in (None, user.id):
        request.session.pop("desktop_view", None)
    request.session[SESSION_KEY] = user.id
    request.session["username"] = user.username
    request.session["display_name"] = user.display_name
    request.session["role"] = user.role
    request.session["must_change_password"] = user.must_change_password


def logout_user(request: Request):
    """Clear the session."""
    request.session.clear()


def get_session_user_id(request: Request) -> Optional[int]:
    """Return the logged-in user's ID from the session, or None."""
    return request.session.get(SESSION_KEY)


# ---------------------------------------------------------------------------
# FastAPI dependencies for route protection
# ---------------------------------------------------------------------------

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency that returns the logged-in User or raises 401."""
    user_id = get_session_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    # Throttled last_seen_at update — write at most once every 2 minutes to limit DB churn
    now = datetime.utcnow()
    if user.last_seen_at is None or (now - user.last_seen_at) > timedelta(minutes=2):
        user.last_seen_at = now
        db.commit()
    return user


VALID_ROLES = ("super_admin", "system_admin", "ceo", "admin", "warranty_admin", "trials_admin", "procurement_admin", "editor", "viewer", "map_kiosk")
SUB_ADMIN_ROLES = ("warranty_admin", "trials_admin", "procurement_admin")
ROLE_DISPLAY = {
    "super_admin": "Super Admin",
    "system_admin": "System Admin",
    "ceo": "CEO",
    "admin": "Administrator",
    "warranty_admin": "Warranty Admin",
    "trials_admin": "Trials Admin",
    "procurement_admin": "Procurement Admin",
    "editor": "Editor",
    "viewer": "Viewer",
    "map_kiosk": "Map Kiosk",
}
ROLE_TIER = {
    "super_admin": 5, "system_admin": 4, "ceo": 4, "admin": 3,
    "warranty_admin": 2, "trials_admin": 2, "procurement_admin": 2,
    "editor": 1, "viewer": 0, "map_kiosk": 0,
}


def require_role(*roles: str):
    """Dependency factory that checks the user has one of the given roles."""
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            required = " or ".join([ROLE_DISPLAY.get(r, r.title()) for r in roles])
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This feature requires {required} access. Your current role is {ROLE_DISPLAY.get(user.role, user.role.title())}.",
            )
        return user
    return dependency


# Convenience dependencies
require_admin = require_role(*ADMIN_LEVEL_ROLES)
require_editor = require_role(*ADMIN_LEVEL_ROLES, "editor", *SUB_ADMIN_ROLES)
require_viewer = require_role(*ADMIN_LEVEL_ROLES, "editor", "viewer", *SUB_ADMIN_ROLES)


# ---------------------------------------------------------------------------
# Domain-specific admin dependencies (role OR permission flag)
# ---------------------------------------------------------------------------

def require_warranty_manager(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is admin, warranty_admin, or has can_manage_warranty flag."""
    if user.has_warranty_admin:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Warranty Admin access. Contact your administrator to request Warranty Management permission.",
    )


def require_trials_manager(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is admin, trials_admin, or has can_manage_trials flag."""
    if user.has_trials_admin:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Trials Admin access. Contact your administrator to request Trials Management permission.",
    )


def require_sites_manager(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is admin or has can_manage_sites flag."""
    if user.has_sites_admin:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Sites Management access. Contact your administrator to request Sites Management permission.",
    )


def require_provisioning_manager(user: User = Depends(get_current_user)) -> User:
    """Full provisioning CRUD: admin, CEO, or can_manage_provisioning/can_manage_sites flag."""
    if user.has_provisioning_manage:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Provisioning Management access. Contact your administrator.",
    )


def require_provisioning_viewer(user: User = Depends(get_current_user)) -> User:
    """Read-only provisioning: manage access OR can_view_provisioning flag."""
    if user.has_provisioning_view:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Provisioning access. Contact your administrator.",
    )


def require_user_manager(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is admin or has can_manage_users flag."""
    if user.has_user_management:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires User Management access. Contact your administrator.",
    )


def require_system_admin(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is admin or has can_manage_system flag."""
    if user.has_system_admin:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires System Administration access. Contact your administrator.",
    )


def require_audit_viewer(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is admin tier or has an explicit can_view_audit_log grant."""
    if user.has_audit_access:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Audit Log access. Contact your administrator.",
    )


def require_map_access(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is editor+ or has can_access_map flag."""
    if user.has_map_access:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Map access. Contact your administrator.",
    )


def require_receiving_access(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is editor+ or has can_access_receiving flag."""
    if user.has_receiving_access:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Receiving access. Contact your administrator.",
    )


def require_scan_access(user: User = Depends(get_current_user)) -> User:
    """Barcode lookup (/api/receive/scan): receiving users AND fulfillment
    board users may scan-to-find (H14). Bare viewers may not — the lookup
    reveals table/location/status per serial (the F15 enumeration oracle)."""
    if user.has_receiving_access or user.has_provisioning_view:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Receiving or Fulfillment access. Contact your administrator.",
    )


def require_disposal_access(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is editor+ or has can_access_disposal flag."""
    if user.has_disposal_access:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Disposal access. Contact your administrator.",
    )


def require_credentials_access(user: User = Depends(get_current_user)) -> User:
    """Grants access if user is editor+ or has can_access_credentials flag."""
    if user.has_credentials_access:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires Credentials access. Contact your administrator.",
    )


def require_receipts(user: User = Depends(get_current_user)) -> User:
    """Dependency that checks user has the Receipts permission.

    Grants access if:
    - User is admin tier
    - User has can_view_receipts (directly or inherited from the department)
    """
    if user.has_receipts_access:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This feature requires the Receipts permission. Administrators and users granted Receipts access can view uploaded receipts and manage vendor profiles. Please contact your administrator to request access.",
    )


# ---------------------------------------------------------------------------
# Role hierarchy helpers
# ---------------------------------------------------------------------------

def get_assignable_roles(actor_role: str) -> list[str]:
    """Return roles this actor can assign (their tier and below, excluding super_admin)."""
    actor_tier = ROLE_TIER.get(actor_role, 0)
    return [r for r in VALID_ROLES
            if ROLE_TIER[r] <= actor_tier and r != "super_admin"]


def can_manage_user(actor: User, target: User) -> bool:
    """Check if actor can modify target (must be strictly higher tier, and target != actor)."""
    if actor.id == target.id:
        return False
    return ROLE_TIER.get(actor.role, 0) > ROLE_TIER.get(target.role, 0)


# ---------------------------------------------------------------------------
# User CRUD helpers
# ---------------------------------------------------------------------------

def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Validate credentials. Returns User on success, None on failure."""
    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.utcnow()
    db.commit()
    return user


def create_user(db: Session, username: str, display_name: str, password: str, role: str = "viewer") -> User:
    """Create a new user with a bcrypt-hashed password. Forces password change on first login."""
    user = User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
