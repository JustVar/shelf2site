"""Edge Box detail page — read-only component view (Phase 1)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings
from ..models import (
    EdgeBox, DeviceComponent,
    GPU, HardDrive, RamModule, CPU, PSU,
    Motherboard, PCCooling, PCAccessory,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

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

COMPONENT_LABELS = {
    "gpus":           "GPUs",
    "hard_drives":    "Hard Drives",
    "ram_modules":    "RAM Modules",
    "cpus":           "CPUs",
    "psus":           "PSUs",
    "motherboards":   "Motherboards",
    "pc_cooling":     "PC Cooling",
    "pc_accessories": "PC Accessories",
}


@router.get("/edge-boxes/{edge_box_id}",
            response_class=HTMLResponse)
async def edge_box_detail(
    request: Request,
    edge_box_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    box = db.query(EdgeBox).filter(EdgeBox.id == edge_box_id).first()
    if not box:
        raise HTTPException(status_code=404, detail="Edge box not found")

    # Get active component links
    active_links = db.query(DeviceComponent).filter(
        DeviceComponent.parent_table == "edge_boxes",
        DeviceComponent.parent_id == edge_box_id,
        DeviceComponent.removed_date == None,
    ).order_by(DeviceComponent.component_table,
               DeviceComponent.installed_date).all()

    # Resolve component objects grouped by type
    components_by_type = {}
    for link in active_links:
        Model = COMPONENT_MODELS.get(link.component_table)
        if not Model:
            continue
        comp = db.query(Model).filter(Model.id == link.component_id).first()
        if not comp:
            continue
        label = COMPONENT_LABELS.get(link.component_table, link.component_table)
        if label not in components_by_type:
            components_by_type[label] = []
        components_by_type[label].append({
            "link": link,
            "component": comp,
        })

    # Get full component history (including removed)
    history_links = db.query(DeviceComponent).filter(
        DeviceComponent.parent_table == "edge_boxes",
        DeviceComponent.parent_id == edge_box_id,
    ).order_by(DeviceComponent.installed_date.desc()).all()

    # Resolve history with component details
    component_history = []
    for link in history_links:
        Model = COMPONENT_MODELS.get(link.component_table)
        if not Model:
            continue
        comp = db.query(Model).filter(Model.id == link.component_id).first()
        label = COMPONENT_LABELS.get(link.component_table, link.component_table)
        component_history.append({
            "link": link,
            "component": comp,
            "type_label": label,
        })

    # Check missing required fields
    missing_fields = []
    if getattr(box, 'deployment_type', None) in EdgeBox.CUSTOMER_DEPLOYMENT_TYPES:
        check_fields = EdgeBox.CUSTOMER_REQUIRED_FIELDS
    else:
        check_fields = EdgeBox.REQUIRED_FIELDS
    for field in check_fields:
        val = getattr(box, field, None)
        if not val:
            missing_fields.append(field.replace("_", " ").title())

    return templates.TemplateResponse(
        "edge_box_detail.html",
        {
            "request": request,
            "user": user,
            "box": box,
            "parent_table": "edge_boxes",
            "parent_id": edge_box_id,
            "components_by_type": components_by_type,
            "component_history": component_history,
            "missing_fields": missing_fields,
            "page_title": f"Edge Box \u2014 {box.serial or box.id}",
        },
    )
