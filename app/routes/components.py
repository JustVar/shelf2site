"""Device component management API — install, remove, move."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import date

from ..database import get_db
from ..auth import require_editor
from ..models import (
    DeviceComponent, EdgeBox, NUC,
    GPU, HardDrive, RamModule, CPU, PSU,
    Motherboard, PCCooling, PCAccessory,
)

router = APIRouter(prefix="/api/components")

COMPONENT_MODELS = {
    "gpus":           GPU,
    "hard_drives":    HardDrive,
    "ram_modules":    RamModule,
    "cpus":           CPU,
    "psus":           PSU,
    "motherboards":   Motherboard,
    "pc_cooling":     PCCooling,
    "pc_accessories": PCAccessory,
}

PARENT_MODELS = {
    "edge_boxes": EdgeBox,
    "nucs":       NUC,
}


def _component_display(comp, table_name):
    """Build a human-readable label for a component."""
    parts = []
    vendor = getattr(comp, "vendor", None) or getattr(comp, "manufacturer", None)
    model  = getattr(comp, "model", None)
    serial = getattr(comp, "gpu_serial", None) or getattr(comp, "serial", None)
    cap_tb = getattr(comp, "capacity_tb", None)
    cap_gb = getattr(comp, "capacity_gb", None)
    watt   = getattr(comp, "wattage_rating", None)

    if vendor: parts.append(vendor)
    if model:  parts.append(model)
    if cap_tb:
        parts.append(f"{cap_tb}TB")
    elif cap_gb and table_name == "ram_modules":
        parts.append(f"{cap_gb}GB")
    if watt: parts.append(f"{watt}W")
    if serial: parts.append(f"[{serial}]")
    return " ".join(parts) if parts else f"ID {comp.id}"


@router.get("/available/{component_table}")
async def get_available_components(
    component_table: str,
    db: Session = Depends(get_db),
):
    """Return components of this type not currently installed anywhere."""
    Model = COMPONENT_MODELS.get(component_table)
    if not Model:
        raise HTTPException(status_code=400,
            detail=f"Unknown component table: {component_table}")

    # Find all currently installed component IDs
    installed_ids = [
        row[0] for row in db.query(DeviceComponent.component_id).filter(
            DeviceComponent.component_table == component_table,
            DeviceComponent.removed_date == None,
        ).all()
    ]

    # Query available components
    query = db.query(Model)
    if installed_ids:
        query = query.filter(~Model.id.in_(installed_ids))
    components = query.all()

    return [
        {
            "id": c.id,
            "label": _component_display(c, component_table),
            "serial": getattr(c, "gpu_serial", None) or getattr(c, "serial", None),
        }
        for c in components
    ]


@router.post("/install")
async def install_component(
    request_data: dict,
    db: Session = Depends(get_db),
    user = Depends(require_editor),
):
    """Install a component into a parent device."""
    parent_table    = request_data.get("parent_table")
    parent_id       = request_data.get("parent_id")
    component_table = request_data.get("component_table")
    component_id    = request_data.get("component_id")
    slot_label      = request_data.get("slot_label")
    notes           = request_data.get("notes")

    if not all([parent_table, parent_id, component_table, component_id]):
        raise HTTPException(status_code=400,
            detail="parent_table, parent_id, component_table, component_id required")

    # Validate parent exists
    ParentModel = PARENT_MODELS.get(parent_table)
    if not ParentModel:
        raise HTTPException(status_code=400,
            detail=f"Unknown parent table: {parent_table}")
    parent = db.query(ParentModel).filter(ParentModel.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent device not found")

    # Validate component exists
    CompModel = COMPONENT_MODELS.get(component_table)
    if not CompModel:
        raise HTTPException(status_code=400,
            detail=f"Unknown component table: {component_table}")
    comp = db.query(CompModel).filter(CompModel.id == component_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Component not found")

    # Check component not already installed
    existing = db.query(DeviceComponent).filter(
        DeviceComponent.component_table == component_table,
        DeviceComponent.component_id == component_id,
        DeviceComponent.removed_date == None,
    ).first()
    if existing:
        raise HTTPException(status_code=409,
            detail="Component is already installed in another device")

    # Create link
    link = DeviceComponent(
        parent_table    = parent_table,
        parent_id       = parent_id,
        component_table = component_table,
        component_id    = component_id,
        slot_label      = slot_label or None,
        installed_date  = date.today(),
        installed_by    = getattr(user, "username", "unknown"),
        notes           = notes or None,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    return {"success": True, "link_id": link.id,
            "message": "Component installed successfully"}


@router.post("/remove/{link_id}")
async def remove_component(
    link_id: int,
    request_data: dict,
    db: Session = Depends(get_db),
    user = Depends(require_editor),
):
    """Remove a component — sets removed_date, preserves history."""
    link = db.query(DeviceComponent).filter(
        DeviceComponent.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Component link not found")
    if link.removed_date:
        raise HTTPException(status_code=409,
            detail="Component already removed")

    notes = request_data.get("notes")
    link.removed_date = date.today()
    link.installed_by = getattr(user, "username", "unknown")
    if notes:
        existing_notes = link.notes or ""
        link.notes = f"{existing_notes} | Removed: {notes}".strip(" | ")

    db.commit()
    return {"success": True, "message": "Component removed successfully"}


@router.post("/move/{link_id}")
async def move_component(
    link_id: int,
    request_data: dict,
    db: Session = Depends(get_db),
    user = Depends(require_editor),
):
    """Move component — close current link, open new link on target device."""
    link = db.query(DeviceComponent).filter(
        DeviceComponent.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Component link not found")
    if link.removed_date:
        raise HTTPException(status_code=409,
            detail="Component already removed")

    new_parent_table = request_data.get("parent_table")
    new_parent_id    = request_data.get("parent_id")
    notes            = request_data.get("notes")
    slot_label       = request_data.get("slot_label")

    if not all([new_parent_table, new_parent_id]):
        raise HTTPException(status_code=400,
            detail="parent_table and parent_id required")

    ParentModel = PARENT_MODELS.get(new_parent_table)
    if not ParentModel:
        raise HTTPException(status_code=400,
            detail=f"Unknown parent table: {new_parent_table}")
    new_parent = db.query(ParentModel).filter(
        ParentModel.id == new_parent_id).first()
    if not new_parent:
        raise HTTPException(status_code=404,
            detail="Destination device not found")

    username = getattr(user, "username", "unknown")

    # Close existing link
    link.removed_date = date.today()
    link.installed_by = username
    if notes:
        existing = link.notes or ""
        link.notes = f"{existing} | Moved: {notes}".strip(" | ")

    # Create new link on destination
    new_link = DeviceComponent(
        parent_table    = new_parent_table,
        parent_id       = new_parent_id,
        component_table = link.component_table,
        component_id    = link.component_id,
        slot_label      = slot_label or link.slot_label,
        installed_date  = date.today(),
        installed_by    = username,
        notes           = notes or None,
    )
    db.add(new_link)
    db.commit()

    return {"success": True, "message": "Component moved successfully"}
