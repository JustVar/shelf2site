"""Review Queue: pending device review for QA, Hardware, Support, and AR/PR teams."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from ..auth import require_editor, User
from ..config import settings
from ..localtime import register
from ..database import get_db
from ..models import PendingDevice, get_approvable_categories
from .dashboard import category_display

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


@router.get("/review", response_class=HTMLResponse)
def review_queue(
    request: Request,
    status_filter: str = "pending",
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Render the review queue filtered by the categories the user can approve.

    Item 30 S4: filters and offers item categories (suggested_category, set
    by scan intake since S3), not legacy table names.
    """
    approvable = get_approvable_categories(user)

    # Permission-aware filter: only show devices the user can act on
    def _table_filter(query):
        return query.filter(
            or_(
                PendingDevice.suggested_category.in_(approvable),
                PendingDevice.suggested_category.is_(None),
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
        "available_categories": [(c, category_display(c)) for c in approvable],
        "category_display": category_display,
        "user": user,
    })


@router.get("/support")
def support_redirect(request: Request):
    """Redirect old /support URL to /review."""
    return RedirectResponse(f"{BP}/review", status_code=301)
