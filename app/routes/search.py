"""Global search — search across all 16 device categories simultaneously."""

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, String, Text
from sqlalchemy.orm import Session

from ..auth import get_current_user, User
from ..config import settings
from ..database import get_db
from ..models import (
    TABLE_MODELS, TABLE_DISPLAY_NAMES,
    get_display_name, get_serial, get_status, get_mac,
)
from .dashboard import CATEGORY_COLORS
_COLOR_FALLBACK = "#888888"

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


@router.get("/search")
def search_page(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Render the global search page."""
    return templates.TemplateResponse("search.html", {
        "request": request,
        "user": user,
    })


@router.get("/search/results")
def search_results_partial(
    request: Request,
    q: str = Query("", description="Search term"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """HTMX partial: render search results as HTML rows grouped by category."""
    if len(q.strip()) < 2:
        return templates.TemplateResponse("partials/search_results.html", {
            "request": request,
            "results": [],
            "total": 0,
            "categories": {},
            "query": q,
            "user": user,
        })

    search_term = f"%{q.strip()}%"
    all_results = []
    category_counts = {}

    for table_name, model in TABLE_MODELS.items():
        # Build ilike filters for all String and Text columns
        string_cols = [
            c for c in model.__table__.columns
            if isinstance(c.type, (String, Text))
        ]
        filters = [c.ilike(search_term) for c in string_cols]
        if not filters:
            continue

        matches = db.query(model).filter(or_(*filters)).all()

        if not matches:
            continue

        color = CATEGORY_COLORS.get(
            table_name,
            _COLOR_FALLBACK
        )
        display_name = TABLE_DISPLAY_NAMES.get(table_name, table_name)
        category_counts[table_name] = {
            "count": len(matches),
            "display_name": display_name,
            "color": color,
        }

        for item in matches:
            all_results.append({
                "table_name": table_name,
                "category": display_name,
                "color": color,
                "id": item.id,
                "name": get_display_name(item),
                "serial": get_serial(item),
                "status": get_status(item),
                "mac_address": get_mac(item),
                "location": getattr(item, "location", None)
                            or getattr(item, "site_name", None)
                            or "-",
                "completeness": item.data_completeness or 0.0,
            })

    total = len(all_results)
    all_results = all_results[:limit]

    return templates.TemplateResponse("partials/search_results.html", {
        "request": request,
        "results": all_results,
        "total": total,
        "categories": category_counts,
        "query": q.strip(),
        "user": user,
    })
