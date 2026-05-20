"""JSON API routes for device data (used by HTMX and external consumers)."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, ADMIN_LEVEL_ROLES, User
from ..database import get_db
from ..models import TABLE_MODELS, compute_completeness, AuditLog
from ..validation import validate_mac_address, validate_serial_number

router = APIRouter()


@router.get("/devices/{table_name}")
def list_devices(
    table_name: str,
    q: str = Query("", description="Search filter"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List devices from a specific inventory table."""
    model = TABLE_MODELS.get(table_name)
    if not model:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown table: {table_name}"},
        )

    query = db.query(model)

    if q:
        from sqlalchemy import or_, String
        string_cols = [
            c for c in model.__table__.columns
            if isinstance(c.type, String)
        ]
        filters = [c.ilike(f"%{q}%") for c in string_cols]
        if filters:
            query = query.filter(or_(*filters))

    total = query.count()
    items = query.order_by(model.id).offset(offset).limit(limit).all()

    # Serialize
    exclude = {"_sa_instance_state"}
    results = []
    for item in items:
        row = {}
        for key, val in item.__dict__.items():
            if key in exclude:
                continue
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            row[key] = val
        results.append(row)

    return JSONResponse(content={
        "table": table_name,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": results,
    })


@router.get("/devices/{table_name}/{device_id}")
def get_device(
    table_name: str,
    device_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single device by ID from a specific table."""
    model = TABLE_MODELS.get(table_name)
    if not model:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown table: {table_name}"},
        )

    device = db.query(model).filter(model.id == device_id).first()
    if not device:
        return JSONResponse(
            status_code=404,
            content={"error": f"Device not found in {table_name}"},
        )

    # Serialize
    exclude = {"_sa_instance_state"}
    result = {}
    for key, val in device.__dict__.items():
        if key in exclude:
            continue
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        result[key] = val

    return JSONResponse(content=result)


@router.put("/devices/{table_name}/{device_id}")
async def update_device(
    request: Request,
    table_name: str,
    device_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Update a device in a specific table."""
    model = TABLE_MODELS.get(table_name)
    if not model:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown table: {table_name}"},
        )

    device = db.query(model).filter(model.id == device_id).first()
    if not device:
        return JSONResponse(
            status_code=404,
            content={"error": f"Device not found in {table_name}"},
        )

    # Store old values for audit log
    old_values = model_to_dict(device)

    # Parse request body
    body = await request.json()

    # Validate serial number if provided
    if "serial" in body and body["serial"]:
        serial_valid, serial_error = validate_serial_number(body["serial"], required=True)
        if not serial_valid:
            return JSONResponse(status_code=400, content={"error": serial_error})

    # Validate MAC addresses if provided
    validation_errors = {}
    for mac_field in ["mac_address", "mac_address_1", "mac_address_2"]:
        if mac_field in body and body[mac_field]:
            mac_valid, mac_result = validate_mac_address(body[mac_field])
            if not mac_valid:
                validation_errors[mac_field] = mac_result
            elif mac_result:  # Normalized MAC
                body[mac_field] = mac_result

    if validation_errors:
        return JSONResponse(status_code=400, content={
            "error": "Validation failed",
            "field_errors": validation_errors
        })

    # Update fields that exist on the model
    updatable_fields = [
        # Common fields
        "serial", "manufacturer", "model", "model_name", "model_number", "model_code",
        "location", "status", "mac_address", "mac_address_1", "mac_address_2",
        "ip_address", "device_name", "device", "assigned_to", "notes", "purpose",
        # Edge box / NUC / Camera / Access Control
        "deployment_type", "part_number", "form_factor", "org", "customer",
        "partner", "site_name", "pilot_type", "incomplete_reason",
        # NUC
        "uuid",
        # Hardware specs
        "bay_count", "ram_gb", "firmware_version", "wattage", "va_rating",
        "capacity_gb", "capacity_tb", "ram_type", "speed_mhz",
        "drive_type", "interface", "cooling_type", "speed_rpm",
        "wattage_rating", "efficiency", "socket", "accessory_type",
        "installed_in", "installed_in_table", "installed_in_id",
        # Procurement fields
        "vendor", "purchase_date", "purchase_price", "purchase_order",
        "supplier_invoice", "procurement_method",
    ]

    # Admin-only fields (privacy controls)
    admin_only_fields = ["show_on_map"]

    for field in updatable_fields:
        if field in body and hasattr(device, field):
            value = body[field]
            # Handle empty strings as None
            if value == "":
                value = None
            setattr(device, field, value)

    # Update admin-only fields (only if user is admin-level)
    if user.role in ADMIN_LEVEL_ROLES:
        for field in admin_only_fields:
            if field in body and hasattr(device, field):
                value = body[field]
                # Convert string "true"/"false" to boolean
                if isinstance(value, str):
                    value = value.lower() == "true"
                setattr(device, field, value)

    # Recompute completeness
    device.data_completeness = compute_completeness(device)

    db.commit()
    db.refresh(device)

    # Audit log
    log_event(
        db, "device_updated",
        request=request,
        user_id=user.id,
        target_table=table_name,
        target_id=device_id,
        action="update",
        old_values=old_values,
        new_values=model_to_dict(device),
        details=f"Updated {table_name} device #{device_id}",
    )

    from ..sidebar_cache import invalidate_category_stats, invalidate_triage_cache
    invalidate_category_stats()
    invalidate_triage_cache()

    return JSONResponse(content={"status": "success", "message": "Device updated"})


@router.get("/devices/{table_name}/{device_id}/history")
def get_device_history(
    table_name: str,
    device_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get audit history for a specific device."""
    from sqlalchemy import desc

    # Verify device exists
    model = TABLE_MODELS.get(table_name)
    if not model:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown table: {table_name}"},
        )

    device = db.query(model).filter(model.id == device_id).first()
    if not device:
        return JSONResponse(
            status_code=404,
            content={"error": f"Device not found in {table_name}"},
        )

    # Fetch audit logs for this device
    logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.target_table == table_name,
            AuditLog.target_id == device_id,
        )
        .order_by(desc(AuditLog.timestamp))
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
            "old_values": log.old_values or {},
            "new_values": log.new_values or {},
            "details": log.details,
        }

        # Get username if user_id exists
        if log.user_id:
            from ..models import User as UserModel
            user_obj = db.query(UserModel).filter(UserModel.id == log.user_id).first()
            entry["username"] = user_obj.username if user_obj else "Unknown"
        else:
            entry["username"] = "System"

        history.append(entry)

    return JSONResponse(content={"history": history})


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

        # Get display table name
        from ..models import TABLE_DISPLAY_NAMES
        entry["display_table"] = TABLE_DISPLAY_NAMES.get(log.target_table, log.target_table)

        history.append(entry)

    return JSONResponse(content={
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": history,
    })


@router.get("/stats")
def inventory_stats(db: Session = Depends(get_db)):
    """Overall inventory statistics."""
    stats = {}
    total = 0
    total_incomplete = 0

    for name, model in TABLE_MODELS.items():
        count = db.query(model).count()
        incomplete = (
            db.query(model)
            .filter(model.data_completeness < 80.0)
            .count()
        )
        stats[name] = {"total": count, "incomplete": incomplete}
        total += count
        total_incomplete += incomplete

    return JSONResponse(content={
        "total_devices": total,
        "total_incomplete": total_incomplete,
        "tables": stats,
    })


@router.get("/vendors")
def get_vendors(db: Session = Depends(get_db)):
    """Get list of unique vendors from all inventory tables."""
    from sqlalchemy import distinct

    vendors = set()

    # Collect distinct vendors from all tables that have the vendor field
    for name, model in TABLE_MODELS.items():
        if hasattr(model, 'vendor'):
            results = db.query(distinct(model.vendor)).filter(model.vendor.isnot(None), model.vendor != '').all()
            vendors.update([v[0] for v in results])

    # Sort alphabetically
    sorted_vendors = sorted(list(vendors))

    return JSONResponse(content={
        "vendors": sorted_vendors,
        "count": len(sorted_vendors)
    })
