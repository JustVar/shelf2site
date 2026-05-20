"""Review Queue: pending device review for QA, Hardware, Support, and AR/PR teams."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from ..auth import require_editor, User
from ..config import settings
from ..database import get_db
from ..models import (
    PendingDevice, TABLE_DISPLAY_NAMES,
    get_approvable_tables,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


@router.get("/review", response_class=HTMLResponse)
def review_queue(
    request: Request,
    status_filter: str = "pending",
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Render the review queue filtered by the user's approvable tables."""
    approvable = get_approvable_tables(user)

    # Permission-aware filter: only show devices the user can act on
    def _table_filter(query):
        return query.filter(
            or_(
                PendingDevice.suggested_table.in_(approvable),
                PendingDevice.suggested_table.is_(None),
            )
        )

    query = _table_filter(db.query(PendingDevice))
    if status_filter:
        query = query.filter(PendingDevice.status == status_filter)
    devices = query.order_by(desc(PendingDevice.last_seen)).all()

    pending_count = _table_filter(
        db.query(PendingDevice).filter(PendingDevice.status == "pending")
    ).count()
    approved_count = _table_filter(
        db.query(PendingDevice).filter(PendingDevice.status == "approved")
    ).count()
    dismissed_count = _table_filter(
        db.query(PendingDevice).filter(PendingDevice.status == "dismissed")
    ).count()

    return templates.TemplateResponse("support.html", {
        "request": request,
        "devices": devices,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "dismissed_count": dismissed_count,
        "status_filter": status_filter,
        "available_tables": approvable,
        "table_display_names": TABLE_DISPLAY_NAMES,
        "user": user,
    })


@router.get("/support")
def support_redirect(request: Request):
    """Redirect old /support URL to /review."""
    return RedirectResponse(f"{BP}/review", status_code=301)
