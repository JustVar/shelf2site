"""NAS Drive / Component tracking API routes."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_admin
from ..config import settings
from ..localtime import local_today
from ..database import get_db
from ..models import NASDrive, NASDevice, User

router = APIRouter()
BP = settings.ROOT_PATH.rstrip("/")


# ---------------------------------------------------------------------------
# NAS Drive API
# ---------------------------------------------------------------------------

@router.get("/api/nas-drives/{nas_device_id}")
def list_drives(
    nas_device_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all drives for a NAS device."""
    nas = db.query(NASDevice).filter(NASDevice.id == nas_device_id).first()
    if not nas:
        return JSONResponse(status_code=404, content={"error": "NAS device not found"})

    drives = (
        db.query(NASDrive)
        .filter(NASDrive.nas_device_id == nas_device_id, NASDrive.drive_status != "removed")
        .order_by(NASDrive.bay_number)
        .all()
    )

    drive_list = []
    for d in drives:
        drive_list.append({
            "id": d.id,
            "bay_number": d.bay_number,
            "serial_number": d.serial_number,
            "manufacturer": d.manufacturer,
            "model": d.model,
            "capacity_gb": d.capacity_gb,
            "drive_type": d.drive_type,
            "interface": d.interface,
            "drive_status": d.drive_status,
            "health_status": d.health_status,
            "install_date": d.install_date.isoformat() if d.install_date else None,
            "warranty_end": d.warranty_end.isoformat() if d.warranty_end else None,
        })

    return JSONResponse(content={
        "nas_device_id": nas_device_id,
        "bay_count": nas.bay_count or 0,
        "drives": drive_list,
    })


@router.post("/api/nas-drives/")
async def add_drive(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Add a drive to a NAS bay."""
    body = await request.json()

    required = ["nas_device_id", "bay_number", "serial_number"]
    for field in required:
        if not body.get(field):
            return JSONResponse(status_code=400, content={"error": f"Missing required field: {field}"})

    nas_id = int(body["nas_device_id"])
    bay = int(body["bay_number"])

    # Verify NAS exists
    nas = db.query(NASDevice).filter(NASDevice.id == nas_id).first()
    if not nas:
        return JSONResponse(status_code=404, content={"error": "NAS device not found"})

    # Check bay limit
    if nas.bay_count and bay > nas.bay_count:
        return JSONResponse(status_code=400, content={"error": f"Bay {bay} exceeds bay count ({nas.bay_count})"})

    # Check bay occupancy
    existing = (
        db.query(NASDrive)
        .filter(NASDrive.nas_device_id == nas_id, NASDrive.bay_number == bay, NASDrive.drive_status != "removed")
        .first()
    )
    if existing:
        return JSONResponse(status_code=409, content={"error": f"Bay {bay} is already occupied"})

    drive = NASDrive(
        nas_device_id=nas_id,
        bay_number=bay,
        serial_number=body["serial_number"],
        manufacturer=body.get("manufacturer"),
        model=body.get("model"),
        capacity_gb=body.get("capacity_gb"),
        drive_type=body.get("drive_type"),
        interface=body.get("interface"),
        drive_status="active",
        health_status="good",
        install_date=body.get("install_date") or local_today().isoformat(),
        warranty_end=body.get("warranty_end") or None,
    )
    db.add(drive)
    db.commit()
    db.refresh(drive)

    log_event(
        db, "drive_added",
        request=request, user_id=user.id,
        target_table="nas_drives", target_id=drive.id,
        action="create",
        new_values=model_to_dict(drive),
        details=f"Drive {body['serial_number']} added to NAS#{nas_id} bay {bay}",
    )

    return JSONResponse(content={"status": "created", "drive_id": drive.id})


@router.put("/api/nas-drives/{drive_id}")
async def update_drive(
    drive_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Update a drive's status or health."""
    drive = db.query(NASDrive).filter(NASDrive.id == drive_id).first()
    if not drive:
        return JSONResponse(status_code=404, content={"error": "Drive not found"})

    body = await request.json()
    old_values = model_to_dict(drive)

    updatable = [
        "drive_status", "health_status", "smart_data", "manufacturer",
        "model", "capacity_gb", "drive_type", "interface", "warranty_end",
    ]
    for field in updatable:
        if field in body:
            setattr(drive, field, body[field] if body[field] != "" else None)

    # Auto-set removal_date when marked as removed
    if body.get("drive_status") == "removed" and not drive.removal_date:
        drive.removal_date = local_today()

    db.commit()
    db.refresh(drive)

    log_event(
        db, "drive_updated",
        request=request, user_id=user.id,
        target_table="nas_drives", target_id=drive.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(drive),
    )

    return JSONResponse(content={"status": "updated"})


@router.delete("/api/nas-drives/{drive_id}")
def delete_drive(
    drive_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Delete a drive record (admin only)."""
    drive = db.query(NASDrive).filter(NASDrive.id == drive_id).first()
    if not drive:
        return JSONResponse(status_code=404, content={"error": "Drive not found"})

    old_values = model_to_dict(drive)
    db.delete(drive)
    db.commit()

    log_event(
        db, "drive_deleted",
        request=request, user_id=user.id,
        target_table="nas_drives", target_id=drive_id,
        action="delete",
        old_values=old_values,
        details=f"Drive {old_values.get('serial_number')} deleted from NAS#{old_values.get('nas_device_id')}",
    )

    return JSONResponse(content={"status": "deleted"})
