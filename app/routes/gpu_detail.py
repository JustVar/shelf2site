"""GPU detail page."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings
from ..models import GPU, DeviceComponent, EdgeBox, NUC, Computer

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

# Maps parent_table → (Model, display_name_fn, detail_url_pattern)
PARENT_MAP = {
    "edge_boxes": (
        EdgeBox,
        lambda p: p.serial or f"Edge Box #{p.id}",
        lambda p: f"{BP}/edge-boxes/{p.id}",
    ),
    "nucs": (
        NUC,
        lambda p: p.serial or f"NUC #{p.id}",
        lambda p: f"{BP}/nuc-detail/{p.id}",
    ),
    "computers": (
        Computer,
        lambda p: p.device_name or p.serial or f"Computer #{p.id}",
        lambda p: f"{BP}/computers/{p.id}",
    ),
}


@router.get("/gpus/{gpu_id}", response_class=HTMLResponse)
async def gpu_detail(
    request: Request,
    gpu_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    gpu = db.query(GPU).filter(GPU.id == gpu_id).first()
    if not gpu:
        raise HTTPException(status_code=404, detail="GPU not found")

    # Find active installation
    active_link = db.query(DeviceComponent).filter(
        DeviceComponent.component_table == "gpus",
        DeviceComponent.component_id == gpu_id,
        DeviceComponent.removed_date == None,
    ).first()

    # Resolve parent device if installed
    current_location = None
    if active_link:
        entry = PARENT_MAP.get(active_link.parent_table)
        if entry:
            Model, name_fn, url_fn = entry
            parent = db.query(Model).filter(
                Model.id == active_link.parent_id
            ).first()
            if parent:
                current_location = {
                    "display_name": name_fn(parent),
                    "url": url_fn(parent),
                    "parent_table": active_link.parent_table,
                    "slot_label": active_link.slot_label,
                    "installed_date": active_link.installed_date,
                }

    # Full installation history
    history_links = db.query(DeviceComponent).filter(
        DeviceComponent.component_table == "gpus",
        DeviceComponent.component_id == gpu_id,
    ).order_by(DeviceComponent.installed_date.desc()).all()

    installation_history = []
    for link in history_links:
        entry = PARENT_MAP.get(link.parent_table)
        if not entry:
            continue
        Model, name_fn, url_fn = entry
        parent = db.query(Model).filter(Model.id == link.parent_id).first()
        installation_history.append({
            "link": link,
            "display_name": name_fn(parent) if parent else f"Unknown #{link.parent_id}",
            "url": url_fn(parent) if parent else None,
        })

    # Missing required fields
    missing_fields = []
    for field in GPU.REQUIRED_FIELDS:
        val = getattr(gpu, field, None)
        if not val:
            missing_fields.append(field.replace("_", " ").title())

    return templates.TemplateResponse(
        "gpu_detail.html",
        {
            "request": request,
            "user": user,
            "gpu": gpu,
            "current_location": current_location,
            "installation_history": installation_history,
            "missing_fields": missing_fields,
            "page_title": f"GPU \u2014 {gpu.model or gpu.gpu_serial or gpu.id}",
        },
    )
