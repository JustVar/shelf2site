from pathlib import Path
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth import get_current_user, User
from ..config import settings
from ..database import get_db
from ..models import Item, ItemLocation, Site
from .dashboard import CATEGORY_COLORS, FL_CATEGORY_COLORS, ALL_CATEGORIES, PRODUCT_CATEGORIES, category_display
from .intake import _get_locations as _get_locations_active, _get_all_places, _get_categories, _normalize_mac, _clean_str, _safe_float, _safe_int, STATUSES
from .dashboard import category_display as _cat_display
from .checkout import _active_users

router = APIRouter(prefix="/inventory", tags=["inventory"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

ITEMS_PER_PAGE = 50

STATUSES = [
    "Deployed",
    "Ready to Deploy",
    "Pending",
    "Un-deployable",
    "Decommissioned",
    "Unassigned",
]


def _get_tile_stats(db: Session) -> list[dict]:
    """Compute per-category counts for the tile grid."""
    raw = (
        db.query(Item.item_category, func.count(Item.id))
        .group_by(Item.item_category)
        .all()
    )
    counts = {str(cat): cnt for cat, cnt in raw if cat}
    total = sum(counts.values())
    tiles = [{"name": "all", "display": "All Items", "count": total, "color": "#C29E9B"}]
    for cat in ALL_CATEGORIES:
        if counts.get(cat, 0) > 0:
            tiles.append({
                "name": cat,
                "display": category_display(cat),
                "count": counts.get(cat, 0),
                "color": FL_CATEGORY_COLORS.get(cat, "#888888"),
            })
    return tiles


def _get_locations(db: Session) -> list[dict]:
    """All places (offices + customer sites) for the inventory filter."""
    rows = db.query(Site).order_by(Site.name).all()
    return [{"id": r.id, "name": r.name} for r in rows]


import time as _time
import logging
_log = logging.getLogger(__name__)

@router.get("/", response_class=HTMLResponse)
def inventory_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    category: str = Query(default="all"),
    status: str = Query(default=""),
    location: str = Query(default=""),
    q: str = Query(default=""),
    page: int = Query(default=1),
):
    if not user:
        return RedirectResponse(f"{BP}/login")

    _t0 = _time.time()
    tiles = _get_tile_stats(db)
    _log.warning(f"TIMING tiles: {_time.time()-_t0:.3f}s")
    _t1 = _time.time()
    locations = _get_locations(db)
    _log.warning(f"TIMING locations: {_time.time()-_t1:.3f}s")

    query = db.query(Item)

    if category and category != "all":
        query = query.filter(Item.item_category == category)

    if status:
        query = query.filter(Item.item_status == status)

    if location:
        try:
            query = query.filter(Item.location_id == int(location))
        except ValueError:
            pass

    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                Item.item_name.ilike(search),
                Item.item_sn.ilike(search),
                Item.brand_sku.ilike(search),
                Item.brand_pn.ilike(search),
                Item.item_model.ilike(search),
                Item.item_manufacturer.ilike(search),
            )
        )

    total_count = query.count()
    total_pages = max(1, (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * ITEMS_PER_PAGE

    items = (
        query
        .order_by(Item.last_updated.desc())
        .offset(offset)
        .limit(ITEMS_PER_PAGE)
        .all()
    )

    loc_map = {r["id"]: r["name"] for r in locations}

    rows = []
    for item in items:
        rows.append({
            "id":           item.id,
            "name":         item.item_name or "—",
            "sn":           item.item_sn or "—",
            "category":     str(item.item_category) if item.item_category else None,
            "category_display": category_display(item.item_category) if item.item_category else "—",
            "status":       str(item.item_status) if item.item_status else "—",
            "location":     loc_map.get(item.location_id, "—"),
            "sku":          item.brand_sku or "—",
            "last_updated": item.last_updated,
            "color":        FL_CATEGORY_COLORS.get(str(item.item_category), "#888888"),
        })

    _log.warning(f"TIMING total before render: {_time.time()-_t0:.3f}s")
    return templates.TemplateResponse("inventory.html", {
        "request":      request,
        "user":         user,
        "tiles":        tiles,
        "locations":    locations,
        "statuses":     STATUSES,
        "rows":         rows,
        "total_count":  total_count,
        "total_pages":  total_pages,
        "current_page": page,
        "category":     category,
        "status":       status,
        "location":     location,
        "q":            q,
        "page":         "inventory",
        "users":        [{"id": u.id, "display_name": u.display_name} for u in _active_users(db)],
    })


@router.get("/quick-view/{item_id}", response_class=HTMLResponse)
def quick_view(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    edit: str = Query(default=""),
):
    """HTMX partial — Quick View panel for a single item."""
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    locations = _get_locations(db)
    loc_map = {r["id"]: r["name"] for r in locations}

    return templates.TemplateResponse("partials/item_quick_view.html", {
        "request":  request,
        "user":     user,
        "item":     item,
        "location": loc_map.get(item.location_id, "—"),
        "locations": locations,
        "statuses": STATUSES,
        "color":    FL_CATEGORY_COLORS.get(str(item.item_category), "#888888"),
        "category_display": category_display(item.item_category) if item.item_category else "—",
        "edit_mode": edit == "1",
    })


@router.post("/quick-view/{item_id}", response_class=HTMLResponse)
def quick_view_save(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    item_name: str = Form(default=""),
    item_sn: str = Form(default=""),
    item_manufacturer: str = Form(default=""),
    item_model: str = Form(default=""),
    item_status: str = Form(default=""),
    location_id: str = Form(default=""),
    department_or_owner: str = Form(default=""),
    brand_sku: str = Form(default=""),
    brand_pn: str = Form(default=""),
    notes: str = Form(default=""),
):
    """Save Quick View edits and return updated read-mode partial."""
    if not user or not user.is_editor_or_above:
        return HTMLResponse("Unauthorized", status_code=401)

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    # Containment-managed items keep their status + frozen location
    # (see item_detail's identical guard; Option A).
    if item.item_status == "Installed":
        item_status = item.item_status
        location_id = str(item.location_id) if item.location_id is not None else ""

    item.item_name = _clean_str(item_name)
    item.item_sn = _clean_str(item_sn)
    item.item_manufacturer = _clean_str(item_manufacturer)
    item.item_model = _clean_str(item_model)
    item.item_status = _clean_str(item_status) or None
    item.location_id = _safe_int(location_id)
    item.department_or_owner = _clean_str(department_or_owner)
    item.brand_sku = _clean_str(brand_sku)
    item.brand_pn = _clean_str(brand_pn)
    item.notes = _clean_str(notes)

    try:
        db.commit()
    except Exception:
        db.rollback()

    locations = _get_locations(db)
    loc_map = {r["id"]: r["name"] for r in locations}

    return templates.TemplateResponse("partials/item_quick_view.html", {
        "request":  request,
        "user":     user,
        "item":     item,
        "location": loc_map.get(item.location_id, "—"),
        "locations": locations,
        "statuses": STATUSES,
        "color":    FL_CATEGORY_COLORS.get(str(item.item_category), "#888888"),
        "category_display": category_display(item.item_category) if item.item_category else "—",
        "edit_mode": False,
    })


@router.post("/bulk")
async def inventory_bulk_update(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk-apply a single-field update to many inventory items.
    Skips items locked by other users; returns counts. Broadcasts
    triage_gap_changed so triage badges/tabs sync when an edit here
    clears (or introduces) a triage gap."""
    if not user or not user.is_editor_or_above:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

    form = await request.form()
    action = form.get("action", "")
    value = form.get("value", "")
    item_ids = form.getlist("item_ids")

    try:
        item_ids = [int(i) for i in item_ids]
    except ValueError:
        return JSONResponse({"success": False, "error": "Invalid item IDs"}, status_code=400)

    if not item_ids:
        return JSONResponse({"success": False, "error": "No items selected"}, status_code=400)

    action_map = {
        "location": ("location_id", lambda v: _safe_int(v)),
        "department": ("department_or_owner", lambda v: _clean_str(v)),
        "status": ("item_status", lambda v: _clean_str(v) or None),
    }
    if action not in action_map:
        return JSONResponse({"success": False, "error": "Unknown action"}, status_code=400)

    field_name, coerce = action_map[action]
    try:
        new_value = coerce(value)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

    if new_value is None or (isinstance(new_value, str) and new_value == ""):
        return JSONResponse({"success": False, "error": "Value cannot be empty"}, status_code=400)

    # Lazy imports to avoid circular risk (locks/sse/triage pull from models too)
    from ..locks import get_lock
    from .sse import publish_event
    from ..sidebar_cache import invalidate_sidebar_counts
    from .triage import TRIAGE_ROLES, _count_role_gaps, get_triage_total_count

    items = db.query(Item).filter(Item.id.in_(item_ids)).all()
    updated = 0
    skipped = 0
    skipped_ids = []

    for item in items:
        lock = get_lock(f"items:{item.id}")
        if lock and lock.get("user_id") != user.id:
            skipped += 1
            skipped_ids.append(item.id)
            continue
        # Installed items: status is containment-managed and the stored
        # location is frozen — bulk writes would break the invariant /
        # create silent divergence, so they are skipped like locked rows.
        if item.item_status == "Installed" and field_name in ("item_status", "location_id"):
            skipped += 1
            skipped_ids.append(item.id)
            continue
        setattr(item, field_name, new_value)
        updated += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        _log.error("Inventory bulk update failed: %s", e, exc_info=True)
        return JSONResponse({"success": False, "error": "Save failed"}, status_code=500)

    _log.info(
        "Inventory bulk: user=%s(id=%d) action=%s updated=%d skipped=%d",
        user.display_name, user.id, action, updated, skipped,
    )

    # Broadcast — any bulk change can move items in/out of triage gaps.
    invalidate_sidebar_counts()
    role_counts_global = {k: _count_role_gaps(db, k) for k in TRIAGE_ROLES.keys()}
    total_items_with_gaps = get_triage_total_count(db)
    publish_event("triage_gap_changed", {
        "item_id": None,
        "field_name": field_name,
        "user_id": user.id,
        "role_counts": role_counts_global,
        "total_items_with_gaps": total_items_with_gaps,
    })

    return JSONResponse({
        "success": True,
        "updated_count": updated,
        "skipped_count": skipped,
        "skipped_ids": skipped_ids,
    })


@router.get("/export")
def inventory_export_csv(
    request: Request,
    ids: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream a CSV of selected items (full asset list, not gap-focused)."""
    if not user:
        return RedirectResponse(f"{BP}/login")

    try:
        item_ids = [int(i) for i in ids.split(",") if i.strip()]
    except ValueError:
        return JSONResponse({"error": "Invalid IDs"}, status_code=400)

    if not item_ids:
        return JSONResponse({"error": "No IDs provided"}, status_code=400)

    items = db.query(Item).filter(Item.id.in_(item_ids)).all()

    # Resolve location_id -> name using the same helper the page uses.
    loc_map = {r["id"]: r["name"] for r in _get_all_places(db)}  # all places incl customer sites

    def row_for(item):
        return {
            "id": item.id,
            "name": item.item_name or "",
            "serial": item.item_sn or "",
            "manufacturer": item.item_manufacturer or "",
            "model": item.item_model or "",
            "category": str(item.item_category) if item.item_category else "",
            "status": str(item.item_status) if item.item_status else "",
            "location_name": loc_map.get(item.location_id, ""),
            "department_or_owner": item.department_or_owner or "",
            "brand_sku": item.brand_sku or "",
            "brand_pn": item.brand_pn or "",
            "last_updated": item.last_updated.isoformat() if item.last_updated else "",
        }

    import io, csv
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "id", "name", "serial", "manufacturer", "model",
        "category", "status", "location_name", "department_or_owner",
        "brand_sku", "brand_pn", "last_updated",
    ])
    writer.writeheader()
    for item in items:
        writer.writerow(row_for(item))

    from fastapi.responses import Response
    from datetime import datetime
    filename = f"inventory-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
