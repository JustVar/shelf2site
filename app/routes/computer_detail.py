"""Computer detail page."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings
from ..models import (
    Computer, DeviceComponent,
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


@router.get("/computers/{computer_id}", response_class=HTMLResponse)
async def computer_detail(
    request: Request,
    computer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    computer = db.query(Computer).filter(Computer.id == computer_id).first()
    if not computer:
        raise HTTPException(status_code=404, detail="Computer not found")

    # Get active component links
    active_links = db.query(DeviceComponent).filter(
        DeviceComponent.parent_table == "computers",
        DeviceComponent.parent_id == computer_id,
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
        DeviceComponent.parent_table == "computers",
        DeviceComponent.parent_id == computer_id,
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
    for field in Computer.REQUIRED_FIELDS:
        val = getattr(computer, field, None)
        if not val:
            missing_fields.append(field.replace("_", " ").title())

    return templates.TemplateResponse(
        "computer_detail.html",
        {
            "request": request,
            "user": user,
            "computer": computer,
            "parent_table": "computers",
            "parent_id": computer_id,
            "components_by_type": components_by_type,
            "component_history": component_history,
            "missing_fields": missing_fields,
            "page_title": f"Computer \u2014 {computer.device_name or computer.serial or computer.id}",
        },
    )
