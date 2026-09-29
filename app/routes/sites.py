"""Sites: manage physical places and see the items placed at each one.

Item 30 S4 (docs/specs/retire-legacy-inventory.md): an item's place is
item_schema.items.location_id, so a site lists the items placed there.
Device-to-site assignments (ownership type, return-by date) were retired in
the same change; device_assignments dropped in migration 083 (item 30 S5).
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_sites_manager
from ..config import settings
from ..localtime import register
from ..geocoding import geocode, compose_address
from ..database import get_db
from ..models import Item, Site, User
from .dashboard import category_display

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


# ---------------------------------------------------------------------------
# Site list page
# ---------------------------------------------------------------------------

@router.get("/sites/", response_class=HTMLResponse)
def sites_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sites main page."""
    sites = db.query(Site).order_by(Site.name).all()

    # Items placed at each site
    site_counts = dict(
        db.query(Item.location_id, func.count(Item.id))
        .filter(Item.location_id.isnot(None))
        .group_by(Item.location_id)
        .all()
    )

    site_list = [{"site": s, "item_count": site_counts.get(s.id, 0)} for s in sites]

    return templates.TemplateResponse("sites.html", {
        "request": request,
        "user": user,
        "sites": site_list,
        "site_types": Site.SITE_TYPES,
        "total_sites": len(sites),
        "active_sites": sum(1 for s in sites if s.is_active),
        "placed_items": sum(site_counts.get(s.id, 0) for s in sites),
    })


# ---------------------------------------------------------------------------
# Site detail page
# ---------------------------------------------------------------------------

@router.get("/sites/{site_id}", response_class=HTMLResponse)
def site_detail_page(
    site_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Detail page for a single site: its details and the items placed there."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return HTMLResponse(status_code=404, content="Site not found")

    items = (
        db.query(Item)
        .filter(Item.location_id == site_id)
        .order_by(Item.item_category, Item.item_name, Item.id)
        .all()
    )
    rows = [
        {"item": i, "category": category_display(i.item_category) if i.item_category else "-"}
        for i in items
    ]

    return templates.TemplateResponse("site_detail.html", {
        "request": request,
        "user": user,
        "site": site,
        "items": rows,
        "site_types": Site.SITE_TYPES,
        "item_count": len(rows),
        "checked_out_count": sum(1 for i in items if i.item_status == "Checked Out"),
    })


# ---------------------------------------------------------------------------
# Site CRUD API
# ---------------------------------------------------------------------------

async def _geocode_site(db, site) -> bool:
    """Geocode a site from its address; cached on geocode_query so a
    re-geocode fires only when the address text changes. Graceful: on
    failure the site is saved without coordinates. Returns True when the
    site ends up with coordinates."""
    query = compose_address(site.address, site.city, site.state, site.country)
    if not query:
        return site.geo_lat is not None
    if site.geocode_query == query and site.geo_lat is not None:
        return True
    result = await geocode(query)
    site.geocode_query = query
    site.geocoded_at = datetime.utcnow()
    if result:
        site.geo_lat, site.geo_lng = result["lat"], result["lng"]
        site.show_on_map = True
        return True
    return False


@router.post("/api/sites")
async def create_site(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Create a new site."""
    body = await request.json()

    name = (body.get("name") or "").strip()
    site_type = (body.get("site_type") or "").strip()

    if not name:
        return JSONResponse(status_code=400, content={"error": "Site name is required"})
    if site_type not in Site.SITE_TYPES:
        return JSONResponse(status_code=400, content={"error": f"Invalid site type: {site_type}"})

    # Check for duplicate name
    existing = db.query(Site).filter(func.lower(Site.name) == name.lower()).first()
    if existing:
        return JSONResponse(status_code=409, content={"error": f"Site '{name}' already exists"})

    site = Site(
        name=name,
        site_type=site_type,
        customer=(body.get("customer") or "").strip() or None,
        address=(body.get("address") or "").strip() or None,
        city=(body.get("city") or "").strip() or None,
        state=(body.get("state") or "").strip() or None,
        country=(body.get("country") or "").strip() or None,
        contact_name=(body.get("contact_name") or "").strip() or None,
        contact_email=(body.get("contact_email") or "").strip() or None,
        contact_phone=(body.get("contact_phone") or "").strip() or None,
        notes=(body.get("notes") or "").strip() or None,
    )
    db.add(site)
    db.commit()
    db.refresh(site)

    geocoded = await _geocode_site(db, site)
    db.commit()

    log_event(
        db, "site_created",
        request=request, user_id=user.id,
        target_table="sites", target_id=site.id,
        action="create",
        new_values=model_to_dict(site),
        details=f"Site '{name}' ({Site.SITE_TYPES[site_type]}) created",
    )

    return JSONResponse(content={"status": "created", "site_id": site.id, "geocoded": geocoded, "had_address": bool(site.address or site.city)})


@router.put("/api/sites/{site_id}")
async def update_site(
    site_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Update an existing site."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return JSONResponse(status_code=404, content={"error": "Site not found"})

    body = await request.json()
    old_values = model_to_dict(site)

    updatable = [
        "name", "site_type", "customer", "address", "city", "state",
        "country", "contact_name", "contact_email", "contact_phone",
        "notes", "is_active",
    ]
    for field in updatable:
        if field in body:
            val = body[field]
            if isinstance(val, str):
                val = val.strip() or None
            setattr(site, field, val)

    # Validate site_type if changed
    if site.site_type and site.site_type not in Site.SITE_TYPES:
        return JSONResponse(status_code=400, content={"error": f"Invalid site type: {site.site_type}"})

    db.commit()
    db.refresh(site)

    geocoded = await _geocode_site(db, site)
    db.commit()

    log_event(
        db, "site_updated",
        request=request, user_id=user.id,
        target_table="sites", target_id=site.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(site),
    )

    return JSONResponse(content={"status": "updated", "geocoded": geocoded, "had_address": bool(site.address or site.city)})


@router.post("/api/sites/{site_id}/geocode")
async def regeocode_site(
    site_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Manual re-geocode (retry after a failed auto-geocode)."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return JSONResponse(status_code=404, content={"error": "Site not found"})
    site.geocode_query = None  # force a fresh lookup
    geocoded = await _geocode_site(db, site)
    db.commit()
    log_event(db, "site_geocoded", request=request, user_id=user.id,
              target_table="sites", target_id=site.id, action="update",
              details=(f"geocoded {site.name} to {site.geo_lat}, {site.geo_lng}" if geocoded
                       else f"geocode failed for {site.name}"))
    return JSONResponse(content={"status": "ok", "geocoded": geocoded,
                                 "lat": site.geo_lat, "lng": site.geo_lng})


@router.delete("/api/sites/{site_id}")
def delete_site(
    site_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Delete a site. Refused while any item is placed there."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return JSONResponse(status_code=404, content={"error": "Site not found"})

    # Items placed here would be silently de-located by the ON DELETE SET NULL
    # fk (Migration 063), so refuse and surface the count.
    placed = db.query(func.count(Item.id)).filter(Item.location_id == site_id).scalar()
    if placed:
        return JSONResponse(status_code=409, content={"error": f"Cannot delete place with {placed} item(s) located here. Move them to another place first."})

    old_values = model_to_dict(site)
    db.delete(site)
    db.commit()

    log_event(
        db, "site_deleted",
        request=request, user_id=user.id,
        target_table="sites", target_id=site_id,
        action="delete",
        old_values=old_values,
        details=f"Site '{old_values.get('name')}' deleted",
    )

    return JSONResponse(content={"status": "deleted"})


# ---------------------------------------------------------------------------
# Lookup API (for HTMX-powered forms)
# ---------------------------------------------------------------------------

@router.get("/api/sites/list")
def list_sites_api(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return all active sites as JSON (for dropdowns)."""
    sites = db.query(Site).filter(Site.is_active.is_(True)).order_by(Site.name).all()
    return JSONResponse(content=[
        {"id": s.id, "name": s.name, "site_type": s.site_type, "customer": s.customer}
        for s in sites
    ])
