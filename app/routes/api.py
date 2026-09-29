"""JSON API routes. The legacy device, stats and vendor reads retired in item 30 S3;
the global audit log remains."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, User
from ..database import get_db
from ..models import AuditLog, ADMIN_LEVEL_ROLES
from ..table_labels import LEGACY_TABLE_LABELS
from ..validation import validate_mac_address, validate_serial_number

router = APIRouter()


@router.get("/audit-log")
def get_global_audit_log(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str = Query("", description="Search across all fields"),
    table: str = Query("", description="Filter by table name"),
    action: str = Query("", description="Filter by action type"),
    user_id: int = Query(None, description="Filter by user ID"),
    date_from: str = Query("", description="Filter from date (YYYY-MM-DD)"),
    date_to: str = Query("", description="Filter to date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get global audit log across all devices with filtering and pagination."""
    from datetime import datetime
    from sqlalchemy import desc, or_, cast, String

    query = db.query(AuditLog)

    # Apply search filter (full-text search across all fields)
    if search:
        search_term = f"%{search}%"
        search_filters = [
            AuditLog.event_type.ilike(search_term),
            AuditLog.action.ilike(search_term),
            AuditLog.target_table.ilike(search_term),
            AuditLog.details.ilike(search_term),
            AuditLog.ip_address.ilike(search_term),
            # Search within JSON fields (old_values and new_values)
            cast(AuditLog.old_values, String).ilike(search_term),
            cast(AuditLog.new_values, String).ilike(search_term),
        ]
        # Also search by username (requires join)
        from ..models import User as UserModel
        query = query.outerjoin(UserModel, AuditLog.user_id == UserModel.id)
        search_filters.append(UserModel.username.ilike(search_term))
        query = query.filter(or_(*search_filters))

    # Apply other filters
    if table:
        query = query.filter(AuditLog.target_table == table)
    if action:
        query = query.filter(AuditLog.action == action)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if date_from:
        try:
            date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.timestamp >= date_from_dt)
        except ValueError:
            pass  # Invalid date format, skip filter
    if date_to:
        try:
            # Add 1 day to include the entire end date
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d")
            # Set to end of day (23:59:59)
            from datetime import timedelta
            date_to_dt = date_to_dt + timedelta(days=1)
            query = query.filter(AuditLog.timestamp < date_to_dt)
        except ValueError:
            pass  # Invalid date format, skip filter

    # Get total count
    total = query.count()

    # Fetch logs with pagination
    logs = (
        query
        .order_by(desc(AuditLog.timestamp))
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Serialize audit logs
    history = []
    for log in logs:
        entry = {
            "id": log.id,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "user_id": log.user_id,
            "event_type": log.event_type,
            "action": log.action,
            "target_table": log.target_table,
            "target_id": log.target_id,
            "old_values": log.old_values or {},
            "new_values": log.new_values or {},
            "details": log.details,
            "ip_address": log.ip_address,
        }

        # Get username if user_id exists
        if log.user_id:
            from ..models import User as UserModel
            user_obj = db.query(UserModel).filter(UserModel.id == log.user_id).first()
            entry["username"] = user_obj.username if user_obj else "Unknown"
        else:
            entry["username"] = "System"

        # Display name for the target table (legacy names are history strings)
        entry["display_table"] = LEGACY_TABLE_LABELS.get(log.target_table, log.target_table)

        history.append(entry)

    return JSONResponse(content={
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": history,
    })
