"""Audit logging helpers.

Every significant action is recorded in the audit_log table:
  - device_added, device_edited, device_deleted
  - device_approved, device_dismissed
  - credential_viewed
  - user_login, user_logout, user_login_failed
  - oui_added, oui_removed
  - scan_triggered, scan_completed
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog

logger = logging.getLogger(__name__)


def log_event(
    db: Session,
    event_type: str,
    *,
    request: Optional[Request] = None,
    user_id: Optional[int] = None,
    target_table: Optional[str] = None,
    target_id: Optional[int] = None,
    action: Optional[str] = None,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    details: Optional[str] = None,
):
    """Insert an audit log entry. Service accounts (svc_*) are silently skipped."""
    from .models import User as UserModel

    ip = None
    if request:
        ip = request.client.host if request.client else None
        if user_id is None:
            user_id = request.session.get("session_user_id")

    # Skip audit logging for service accounts
    if user_id:
        svc_user = db.query(UserModel).filter(UserModel.id == user_id).first()
        if svc_user and svc_user.username.startswith("svc_"):
            return

    entry = AuditLog(
        timestamp=datetime.utcnow(),
        user_id=user_id,
        event_type=event_type,
        target_table=target_table,
        target_id=target_id,
        action=action,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip,
        details=details,
    )
    db.add(entry)
    db.commit()

    logger.info(
        f"AUDIT: {event_type} | user={user_id} | "
        f"table={target_table} id={target_id} | {action or ''} | {details or ''}"
    )


def model_to_dict(instance) -> dict:
    """Convert a SQLAlchemy model instance to a dict for audit snapshots."""
    result = {}
    for col in instance.__table__.columns:
        val = getattr(instance, col.name)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        elif isinstance(val, Decimal):
            val = float(val)
        elif isinstance(val, bytes):
            val = "<encrypted>"
        result[col.name] = val
    return result
