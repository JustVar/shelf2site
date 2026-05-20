"""Printer detail page."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings
from ..models import Printer

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

@router.get("/printers/{item_id}", response_class=HTMLResponse)
async def printer_detail(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(Printer).filter(Printer.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Printer not found")
    missing_fields = [f.replace("_", " ").title() for f in Printer.REQUIRED_FIELDS if not getattr(item, f, None)]
    return templates.TemplateResponse("printer_detail.html", {
        "request": request, "user": user, "item": item,
        "missing_fields": missing_fields,
        "page_title": f"Printer — {item.device or item.serial or item.id}",
    })
