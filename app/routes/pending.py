"""Pending device review queue: approve or dismiss discovered devices."""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor
from ..database import get_db
from ..models import (
    PendingDevice, TABLE_MODELS, User, compute_completeness,
    user_can_approve_table,
)

router = APIRouter()


@router.post("/pending/{device_id}/approve")
async def approve_device(
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Approve a pending device: move it to the chosen inventory table."""
    pending = db.query(PendingDevice).filter(PendingDevice.id == device_id).first()
    if not pending:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    if pending.status != "pending":
        return JSONResponse(status_code=400, content={"error": f"Already {pending.status}"})

    # Accept optional target_table override from JSON body
    target_table = pending.suggested_table or "network_equipment"
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        body = await request.json()
        override = (body.get("target_table") or "").strip()
        if override and override in TABLE_MODELS:
            target_table = override

    model_class = TABLE_MODELS.get(target_table)
    if model_class is None:
        model_class = TABLE_MODELS["network_equipment"]
        target_table = "network_equipment"

    # RBAC: check user has permission for this target table
    if not user_can_approve_table(user, target_table):
        return JSONResponse(
            status_code=403,
            content={"error": f"You don't have permission to approve devices into {target_table.replace('_', ' ').title()}. Sites Manager access required."},
        )

    # Build the new inventory device
    new_device_kwargs = {
        "discovered_by": f"scanner:{pending.scanner_id or 'unknown'}",
        "network_segment": pending.network_segment,
        "last_seen": pending.last_seen,
    }
    if (hasattr(model_class, "mac_address") and pending.mac_address
            and not pending.mac_address.startswith("intake-")):
        # the intake-<serial> placeholder is a NOT NULL hack, not a real MAC
        new_device_kwargs["mac_address"] = pending.mac_address
    if hasattr(model_class, "ip_address"):
        new_device_kwargs["ip_address"] = pending.ip_address
    if hasattr(model_class, "manufacturer"):
        new_device_kwargs["manufacturer"] = pending.manufacturer
    if hasattr(model_class, "device"):
        new_device_kwargs["device"] = pending.manufacturer or "Auto-discovered"
    if hasattr(model_class, "device_name"):
        new_device_kwargs["device_name"] = pending.hostname
    if hasattr(model_class, "model_name"):
        new_device_kwargs["model_name"] = pending.hostname

    # H3: scan-intake fields preserved on the pending row (migration 064)
    if pending.serial and hasattr(model_class, "serial"):
        new_device_kwargs["serial"] = pending.serial
    if pending.serial and hasattr(model_class, "gpu_serial"):
        new_device_kwargs["gpu_serial"] = pending.serial
    if pending.model and hasattr(model_class, "model"):
        new_device_kwargs["model"] = pending.model
    if pending.model and hasattr(model_class, "model_name"):
        new_device_kwargs["model_name"] = pending.model
    if pending.notes and hasattr(model_class, "notes"):
        new_device_kwargs["notes"] = pending.notes

    new_device = model_class(**new_device_kwargs)
    new_device.data_completeness = compute_completeness(new_device)
    db.add(new_device)

    # Auto-add OUI to allowlist if not present
    if pending.mac_address:
        from app.oui_utils import auto_add_oui
        auto_add_oui(
            db,
            mac_address=pending.mac_address,
            manufacturer=pending.manufacturer,
            table_name=target_table,
        )

    # Update pending record
    pending.status = "approved"
    pending.reviewed_by = user.id
    pending.reviewed_at = datetime.utcnow()

    # H3: approval is the receive moment for pending units — count it toward
    # the receiving event (the submit path doesn't increment for pending).
    if pending.receiving_event_id:
        from app.models import ReceivingEvent
        event = db.query(ReceivingEvent).filter(
            ReceivingEvent.id == pending.receiving_event_id
        ).first()
        if event:
            event.received_quantity = (event.received_quantity or 0) + 1

    db.commit()
    db.refresh(new_device)

    log_event(
        db, "device_approved",
        request=request,
        user_id=user.id,
        target_table=target_table,
        target_id=new_device.id,
        action="approve",
        new_values={"mac": pending.mac_address, "manufacturer": pending.manufacturer},
        details=f"Approved pending device {pending.mac_address} -> {target_table}",
    )

    return JSONResponse(content={
        "status": "approved",
        "target_table": target_table,
        "device_id": new_device.id,
    })


@router.post("/pending/{device_id}/dismiss")
async def dismiss_device(
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Dismiss a pending device (ignore it, never prompt again for this MAC)."""
    pending = db.query(PendingDevice).filter(PendingDevice.id == device_id).first()
    if not pending:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    if pending.status != "pending":
        return JSONResponse(status_code=400, content={"error": f"Already {pending.status}"})

    # RBAC: check user has permission for this device's target table
    device_table = pending.suggested_table or "network_equipment"
    if not user_can_approve_table(user, device_table):
        return JSONResponse(
            status_code=403,
            content={"error": f"You don't have permission to dismiss {device_table.replace('_', ' ').title()} devices. Sites Manager access required."},
        )

    form = await request.form() if request.headers.get("content-type", "").startswith("application/x-www-form") else None
    reason = ""
    if form:
        reason = form.get("reason", "")
    else:
        # Also accept JSON body
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            body = await request.json()
            reason = body.get("reason", "")

    pending.status = "dismissed"
    pending.reviewed_by = user.id
    pending.reviewed_at = datetime.utcnow()
    pending.dismiss_reason = reason
    db.commit()

    log_event(
        db, "device_dismissed",
        request=request,
        user_id=user.id,
        target_table="pending_devices",
        target_id=device_id,
        action="dismiss",
        details=f"Dismissed {pending.mac_address}: {reason or 'no reason given'}",
    )

    return JSONResponse(content={"status": "dismissed"})
