"""Camera detail page."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings
from ..models import Camera

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

@router.get("/cameras/{item_id}", response_class=HTMLResponse)
async def camera_detail(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(Camera).filter(Camera.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Camera not found")
    missing_fields = []
    if getattr(item, 'deployment_type', None) in Camera.CUSTOMER_DEPLOYMENT_TYPES:
        check_fields = Camera.CUSTOMER_REQUIRED_FIELDS
    else:
        check_fields = Camera.REQUIRED_FIELDS
    for field in check_fields:
        val = getattr(item, field, None)
        if not val:
            missing_fields.append(field.replace("_", " ").title())
    return templates.TemplateResponse("camera_detail.html", {
        "request": request, "user": user, "item": item,
        "missing_fields": missing_fields,
        "page_title": f"Camera — {item.device_name or item.model or item.serial or item.id}",
    })
