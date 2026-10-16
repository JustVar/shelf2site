"""Vendor Profiles routes: contact info, OEM flags, and the items linked to each vendor.

Item 30 S4 (docs/specs/retire-legacy-inventory.md): the legacy per-category
device lists, the unlinked-vendor strings and the auto-create seeding read
the legacy tables and are retired. A profile now lists the items whose
vendor_id points at it. The quality score, RMA and trial stats went with
them (RMA claims and trials are retired features); N2 owns any richer
vendor analytics.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_admin, require_viewer, require_receipts
from ..config import settings
from ..localtime import local_today, register
from ..database import get_db
from ..delete_requests import LOCK_MESSAGE, locked_ids, pending_for
from ..models import DeviceWarranty, Item, User, VendorProfile
from .dashboard import category_display

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


# ---------------------------------------------------------------------------
# Helper: items and warranties linked to a vendor
# ---------------------------------------------------------------------------

def _vendor_items(db: Session, profile: VendorProfile) -> dict:
    """Items whose vendor_id is this profile, and warranties naming the vendor."""
    items = (
        db.query(Item)
        .filter(Item.vendor_id == profile.id)
        .order_by(Item.item_category, Item.item_name, Item.id)
        .all()
    )
    rows = [
        {"item": i, "category": category_display(i.item_category) if i.item_category else "-"}
        for i in items
    ]
    warranties = db.query(DeviceWarranty).filter(DeviceWarranty.vendor.ilike(profile.name)).all()
    today = local_today()
    return {
        "items": rows,
        "item_count": len(rows),
        "warranty_count": len(warranties),
        "active_warranties": sum(1 for w in warranties if w.warranty_end and w.warranty_end >= today),
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@router.get("/vendors/", response_class=HTMLResponse)
def vendors_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_viewer),
):
    """Vendor list page."""
    profiles = db.query(VendorProfile).order_by(VendorProfile.name).all()
    return templates.TemplateResponse("vendors.html", {
        "request": request,
        "user": user,
        "profiles": profiles,
    })


@router.get("/vendors/{vendor_id}", response_class=HTMLResponse)
def vendor_profile_detail(
    vendor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_viewer),
):
    """Vendor detail: contact card plus the items linked to this vendor."""
    profile = db.query(VendorProfile).filter(VendorProfile.id == vendor_id).first()
    if not profile:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"{BP}/vendors/", status_code=303)

    linked = _vendor_items(db, profile)

    return templates.TemplateResponse("vendor_detail_profile.html", {
        "request": request,
        "user": user,
        "profile": profile,
        "can_edit": user.has_receipts_access,
        "delete_request": pending_for(db, "vendor_profiles", profile.id),
        **linked,
    })


# ---------------------------------------------------------------------------
# API — CRUD
# ---------------------------------------------------------------------------

@router.post("/api/vendors/")
async def create_vendor(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_receipts),
):
    """Create a new vendor profile."""
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Vendor name is required"})

    existing = db.query(VendorProfile).filter(VendorProfile.name.ilike(name)).first()
    if existing:
        return JSONResponse(status_code=409, content={"error": f"Vendor profile '{name}' already exists"})

    profile = VendorProfile(
        name=name,
        display_name=(body.get("display_name") or "").strip() or None,
        contact_name=(body.get("contact_name") or "").strip() or None,
        contact_email=(body.get("contact_email") or "").strip() or None,
        contact_phone=(body.get("contact_phone") or "").strip() or None,
        website=(body.get("website") or "").strip() or None,
        is_oem=bool(body.get("is_oem", False)),
        categories_supplied=(body.get("categories_supplied") or "").strip() or None,
        notes=(body.get("notes") or "").strip() or None,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    log_event(db, "vendor_created", request=request, user_id=user.id,
              target_table="vendor_profiles", target_id=profile.id, action="create",
              details=f"Created vendor profile: {name}")

    return JSONResponse(content={"status": "ok", "vendor_id": profile.id})


@router.put("/api/vendors/{vendor_id}")
async def update_vendor(
    vendor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_receipts),
):
    """Update an existing vendor profile."""
    profile = db.query(VendorProfile).filter(VendorProfile.id == vendor_id).first()
    if not profile:
        return JSONResponse(status_code=404, content={"error": "Vendor profile not found"})
    if locked_ids(db, "vendor_profiles", [vendor_id]):
        return JSONResponse(status_code=409, content={"error": LOCK_MESSAGE})

    body = await request.json()
    fields = ["display_name", "contact_name", "contact_email", "contact_phone",
              "website", "categories_supplied", "notes"]
    for field in fields:
        if field in body:
            setattr(profile, field, (body[field] or "").strip() or None)
    if "is_oem" in body:
        profile.is_oem = bool(body["is_oem"])
    if "name" in body:
        new_name = (body["name"] or "").strip()
        if new_name and new_name.lower() != profile.name.lower():
            clash = db.query(VendorProfile).filter(
                VendorProfile.name.ilike(new_name), VendorProfile.id != vendor_id
            ).first()
            if clash:
                return JSONResponse(status_code=409, content={"error": f"Vendor '{new_name}' already exists"})
            profile.name = new_name

    db.commit()
    log_event(db, "vendor_updated", request=request, user_id=user.id,
              target_table="vendor_profiles", target_id=vendor_id, action="update",
              details=f"Updated vendor profile: {profile.name}")

    return JSONResponse(content={"status": "ok"})


@router.delete("/api/vendors/{vendor_id}")
def delete_vendor(
    vendor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Delete a vendor profile. Items and receipts that referenced it lose the
    link (FK ON DELETE SET NULL, migration 075) and keep their vendor text."""
    profile = db.query(VendorProfile).filter(VendorProfile.id == vendor_id).first()
    if not profile:
        return JSONResponse(status_code=404, content={"error": "Vendor profile not found"})
    if locked_ids(db, "vendor_profiles", [vendor_id]):
        return JSONResponse(status_code=409, content={"error": LOCK_MESSAGE})

    name = profile.name
    db.delete(profile)
    db.commit()

    log_event(db, "vendor_deleted", request=request, user_id=user.id,
              target_table="vendor_profiles", target_id=vendor_id, action="delete",
              details=f"Deleted vendor profile: {name}")

    return JSONResponse(content={"status": "ok"})
