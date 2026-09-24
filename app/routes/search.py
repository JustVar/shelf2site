"""Global search — query the unified item_schema.items table; results grouped by category."""

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, Text, cast
from sqlalchemy.orm import Session

from ..auth import get_current_user, User
from ..config import settings
from ..localtime import register
from ..database import get_db
from ..models import Item, ItemLocation, Site
from .dashboard import FL_CATEGORY_COLORS, category_display
_COLOR_FALLBACK = "#888888"

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


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
    include_decommissioned: bool = Query(False),
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

    # Single query against the unified item_schema.items table.
    # Explicit allowlist of searchable columns; cast each to text so the
    # ILIKE works regardless of native column type (enum, macaddr, etc.).
    SEARCH_COLS = [
        "item_name", "item_sn", "item_model", "item_manufacturer",
        "item_category", "item_status", "item_vendor",
        "brand_sku", "brand_pn", "item_associated_brand_pn",
        "item_mac_address_1", "item_mac_address_2",
        "appliance_uuid", "department_or_owner",
    ]
    filters = [
        cast(getattr(Item, name), Text).ilike(search_term)
        for name in SEARCH_COLS
    ]
    match_q = db.query(Item).filter(or_(*filters))
    if not include_decommissioned:
        # Hidden by default (docs/specs/item-decommission.md).
        match_q = match_q.filter(Item.item_status.is_distinct_from("Decommissioned"))
    matches = match_q.all()

    # Pre-fetch location names in one query
    loc_map = {s.id: s.name for s in db.query(Site).all()}  # Migration 063

    # Effective place (Option A): Installed components show the parent's place
    from ..containment import effective_location_overrides
    loc_overrides = effective_location_overrides(db, [i.id for i in matches])

    for item in matches:
        cat = str(item.item_category) if item.item_category else None
        display_name = category_display(cat) if cat else "-"
        color = FL_CATEGORY_COLORS.get(cat, _COLOR_FALLBACK)
        key = cat or "unknown"
        if key not in category_counts:
            category_counts[key] = {
                "count": 0,
                "display_name": display_name,
                "color": color,
            }
        category_counts[key]["count"] += 1

        all_results.append({
            "table_name": key,
            "category": display_name,
            "color": color,
            "id": item.id,
            "name": item.item_name or "-",
            "serial": item.item_sn or "-",
            "status": item.item_status,
            "mac_address": item.item_mac_address_1 or item.item_mac_address_2 or "-",
            "location": loc_map.get(loc_overrides.get(item.id, item.location_id), "-"),
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
