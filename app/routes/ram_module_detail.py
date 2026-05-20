"""RAM Module detail page."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings
from ..models import RamModule, DeviceComponent, EdgeBox, NUC, Computer

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

PARENT_MAP = {
    "edge_boxes": (EdgeBox, lambda p: p.serial or f"Edge Box #{p.id}", lambda p: f"{BP}/edge-boxes/{p.id}"),
    "nucs":       (NUC,     lambda p: p.serial or f"NUC #{p.id}",      lambda p: f"{BP}/nuc-detail/{p.id}"),
    "computers":  (Computer, lambda p: p.device_name or p.serial or f"Computer #{p.id}", lambda p: f"{BP}/computers/{p.id}"),
}

@router.get("/ram-modules/{item_id}", response_class=HTMLResponse)
async def ram_module_detail(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(RamModule).filter(RamModule.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="RAM module not found")

    active_link = db.query(DeviceComponent).filter(
        DeviceComponent.component_table == "ram_modules",
        DeviceComponent.component_id == item_id,
        DeviceComponent.removed_date == None,
    ).first()

    current_location = None
    if active_link:
        entry = PARENT_MAP.get(active_link.parent_table)
        if entry:
            Model, name_fn, url_fn = entry
            parent = db.query(Model).filter(Model.id == active_link.parent_id).first()
            if parent:
                current_location = {"display_name": name_fn(parent), "url": url_fn(parent), "parent_table": active_link.parent_table, "slot_label": active_link.slot_label, "installed_date": active_link.installed_date}

    history_links = db.query(DeviceComponent).filter(
        DeviceComponent.component_table == "ram_modules",
        DeviceComponent.component_id == item_id,
    ).order_by(DeviceComponent.installed_date.desc()).all()

    installation_history = []
    for link in history_links:
        entry = PARENT_MAP.get(link.parent_table)
        if not entry: continue
        Model, name_fn, url_fn = entry
        parent = db.query(Model).filter(Model.id == link.parent_id).first()
        installation_history.append({"link": link, "display_name": name_fn(parent) if parent else f"Unknown #{link.parent_id}", "url": url_fn(parent) if parent else None})

    missing_fields = [f.replace("_", " ").title() for f in RamModule.REQUIRED_FIELDS if not getattr(item, f, None)]

    return templates.TemplateResponse("ram_module_detail.html", {
        "request": request, "user": user, "item": item,
        "current_location": current_location, "installation_history": installation_history,
        "missing_fields": missing_fields,
        "page_title": f"RAM — {item.model or item.manufacturer or item.id}",
    })
