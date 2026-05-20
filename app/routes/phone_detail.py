"""Phone detail page."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings
from ..models import Phone

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

@router.get("/phones/{item_id}", response_class=HTMLResponse)
async def phone_detail(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(Phone).filter(Phone.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Phone not found")
    missing_fields = [f.replace("_", " ").title() for f in Phone.REQUIRED_FIELDS if not getattr(item, f, None)]
    return templates.TemplateResponse("phone_detail.html", {
        "request": request, "user": user, "item": item,
        "missing_fields": missing_fields,
        "page_title": f"Phone — {item.device or item.model or item.serial or item.id}",
    })
