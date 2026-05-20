"""NUC detail page — read-only component view."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings
from ..models import (
    NUC, DeviceComponent,
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


@router.get("/nuc-detail/{nuc_id}", response_class=HTMLResponse)
async def nuc_detail(
    request: Request,
    nuc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    nuc = db.query(NUC).filter(NUC.id == nuc_id).first()
    if not nuc:
        raise HTTPException(status_code=404, detail="NUC not found")

    # Active component links
    active_links = db.query(DeviceComponent).filter(
        DeviceComponent.parent_table == "nucs",
        DeviceComponent.parent_id == nuc_id,
        DeviceComponent.removed_date == None,
    ).order_by(DeviceComponent.component_table,
               DeviceComponent.installed_date).all()

    # Resolve components grouped by type
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

    # Full component history
    history_links = db.query(DeviceComponent).filter(
        DeviceComponent.parent_table == "nucs",
        DeviceComponent.parent_id == nuc_id,
    ).order_by(DeviceComponent.installed_date.desc()).all()

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

    # Missing required fields
    missing_fields = []
    if getattr(nuc, 'deployment_type', None) in NUC.CUSTOMER_DEPLOYMENT_TYPES:
        check_fields = NUC.CUSTOMER_REQUIRED_FIELDS
    else:
        check_fields = NUC.REQUIRED_FIELDS
    for field in check_fields:
        val = getattr(nuc, field, None)
        if not val:
            missing_fields.append(field.replace("_", " ").title())

    return templates.TemplateResponse(
        "nuc_detail.html",
        {
            "request": request,
            "user": user,
            "nuc": nuc,
            "parent_table": "nucs",
            "parent_id": nuc_id,
            "components_by_type": components_by_type,
            "component_history": component_history,
            "missing_fields": missing_fields,
            "page_title": f"NUC \u2014 {nuc.serial or nuc.id}",
        },
    )
