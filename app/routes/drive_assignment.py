"""Drive assignment API — assign/uninstall storage drives to parent devices."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, User
from ..database import get_db
from ..models import StorageDrive, TABLE_MODELS, get_display_name

router = APIRouter()


@router.get("/api/devices/{table_name}/{device_id}/drives")
def list_installed_drives(
    table_name: str,
    device_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all storage drives installed in a specific parent device."""
    model = TABLE_MODELS.get(table_name)
    if not model:
        return JSONResponse(status_code=404, content={"error": f"Unknown table: {table_name}"})

    parent = db.query(model).filter(model.id == device_id).first()
    if not parent:
        return JSONResponse(status_code=404, content={"error": "Parent device not found"})

    drives = (
        db.query(StorageDrive)
        .filter(
            StorageDrive.installed_in_table == table_name,
            StorageDrive.installed_in_id == device_id,
        )
        .order_by(StorageDrive.id)
        .all()
    )

    drive_list = []
    for d in drives:
        drive_list.append({
            "id": d.id,
            "serial": d.serial,
            "manufacturer": d.manufacturer,
            "model": d.model,
            "capacity_gb": d.capacity_gb,
            "drive_type": d.drive_type,
            "form_factor": d.form_factor,
            "interface": d.interface,
            "status": d.status,
        })

    return JSONResponse(content={
        "parent_table": table_name,
        "parent_id": device_id,
        "parent_name": get_display_name(parent),
        "drives": drive_list,
    })


@router.get("/api/drives/lookup")
def lookup_drive(
    serial: str = Query(..., description="Drive serial number"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Look up a storage drive by serial number (case-insensitive)."""
    drive = (
        db.query(StorageDrive)
        .filter(StorageDrive.serial.ilike(serial.strip()))
        .first()
    )

    if not drive:
        return JSONResponse(status_code=404, content={"error": "Drive not found in inventory"})

    return JSONResponse(content={
        "id": drive.id,
        "serial": drive.serial,
        "manufacturer": drive.manufacturer,
        "model": drive.model,
        "capacity_gb": drive.capacity_gb,
        "drive_type": drive.drive_type,
        "form_factor": drive.form_factor,
        "interface": drive.interface,
        "status": drive.status,
        "installed_in": drive.installed_in,
        "installed_in_table": drive.installed_in_table,
        "installed_in_id": drive.installed_in_id,
    })


@router.post("/api/drives/assign")
async def assign_drive(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Assign a storage drive to a parent device."""
    body = await request.json()

    drive_id = body.get("drive_id")
    target_table = body.get("target_table")
    target_id = body.get("target_id")

    if not all([drive_id, target_table, target_id]):
        return JSONResponse(
            status_code=400,
            content={"error": "Missing required fields: drive_id, target_table, target_id"},
        )

    # Validate drive exists
    drive = db.query(StorageDrive).filter(StorageDrive.id == int(drive_id)).first()
    if not drive:
        return JSONResponse(status_code=404, content={"error": "Drive not found"})

    # Validate target device exists
    target_model = TABLE_MODELS.get(target_table)
    if not target_model:
        return JSONResponse(status_code=404, content={"error": f"Unknown table: {target_table}"})

    target_device = db.query(target_model).filter(target_model.id == int(target_id)).first()
    if not target_device:
        return JSONResponse(status_code=404, content={"error": "Target device not found"})

    old_values = model_to_dict(drive)

    # Check if drive is already installed somewhere else
    already_installed = None
    if drive.installed_in_table and drive.installed_in_id:
        if drive.installed_in_table == target_table and drive.installed_in_id == int(target_id):
            return JSONResponse(content={
                "status": "already_assigned",
                "message": "Drive is already assigned to this device",
            })
        already_installed = drive.installed_in

    # Assign the drive
    parent_name = get_display_name(target_device)
    drive.installed_in = parent_name
    drive.installed_in_table = target_table
    drive.installed_in_id = int(target_id)

    # Update status if drive was unassigned
    if drive.status in (None, "", "Spare", "Received", "In Storage"):
        drive.status = "Installed"

    db.commit()
    db.refresh(drive)

    log_event(
        db, "drive_assigned",
        request=request,
        user_id=user.id,
        target_table="storage_drives",
        target_id=drive.id,
        action="update",
        old_values=old_values,
        new_values=model_to_dict(drive),
        details=f"Drive {drive.serial} assigned to {target_table}/{target_id} ({parent_name})",
    )

    return JSONResponse(content={
        "status": "assigned",
        "drive_id": drive.id,
        "installed_in": parent_name,
        "previously_installed": already_installed,
    })


@router.post("/api/drives/uninstall")
async def uninstall_drive(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Uninstall a storage drive from its parent device."""
    body = await request.json()
    drive_id = body.get("drive_id")

    if not drive_id:
        return JSONResponse(status_code=400, content={"error": "Missing required field: drive_id"})

    drive = db.query(StorageDrive).filter(StorageDrive.id == int(drive_id)).first()
    if not drive:
        return JSONResponse(status_code=404, content={"error": "Drive not found"})

    old_values = model_to_dict(drive)
    old_location = drive.installed_in or "unknown"

    drive.installed_in = None
    drive.installed_in_table = None
    drive.installed_in_id = None
    drive.status = "Spare"

    db.commit()
    db.refresh(drive)

    log_event(
        db, "drive_uninstalled",
        request=request,
        user_id=user.id,
        target_table="storage_drives",
        target_id=drive.id,
        action="update",
        old_values=old_values,
        new_values=model_to_dict(drive),
        details=f"Drive {drive.serial} uninstalled from {old_location}",
    )

    return JSONResponse(content={
        "status": "uninstalled",
        "drive_id": drive.id,
    })
