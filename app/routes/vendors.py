"""Vendor Profiles routes — contact info, OEM flags, and per-vendor analytics."""

from datetime import date
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import get_current_user, require_admin, require_viewer, require_receipts
from ..config import settings
from ..database import get_db
from ..delete_requests import LOCK_MESSAGE, locked_ids, pending_for
from ..models import (
    VendorProfile, DeviceWarranty, WarrantyClaim, VendorTrial, User,
    TABLE_MODELS, TABLE_DISPLAY_NAMES, get_display_name, get_serial,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


# ---------------------------------------------------------------------------
# Helper: collect vendor analytics (reused from procurement.py logic)
# ---------------------------------------------------------------------------

def _vendor_analytics(db: Session, vendor_name: str) -> dict:
    """Gather device counts, warranty, trial data for a vendor string."""
    devices = []
    for table_name, model in TABLE_MODELS.items():
        if not hasattr(model, "vendor"):
            continue
        matches = db.query(model).filter(model.vendor.ilike(vendor_name)).all()
        display = TABLE_DISPLAY_NAMES.get(table_name, table_name)
        for d in matches:
            devices.append({
                "id": d.id,
                "table": table_name,
                "category": display,
                "name": get_display_name(d),
                "serial": get_serial(d),
                "status": getattr(d, "status", "-"),
                "purchase_date": (
                    d.purchase_date.strftime("%Y-%m-%d")
                    if hasattr(d, "purchase_date") and d.purchase_date else "-"
                ),
            })

    warranties = db.query(DeviceWarranty).filter(DeviceWarranty.vendor.ilike(vendor_name)).all()
    active_warranties = sum(1 for w in warranties if w.warranty_end and w.warranty_end >= date.today())
    warranty_ids = [w.id for w in warranties]
    claims = (
        db.query(WarrantyClaim).filter(WarrantyClaim.warranty_id.in_(warranty_ids)).all()
        if warranty_ids else []
    )
    claim_rate = (len(claims) / len(devices) * 100) if devices else 0

    trials = db.query(VendorTrial).filter(VendorTrial.vendor.ilike(vendor_name)).all()
    trial_purchased = sum(1 for t in trials if t.trial_status == "approved_purchase")
    trial_returned = sum(1 for t in trials if t.trial_status == "returned")
    trial_active = sum(1 for t in trials if t.trial_status == "active")

    quality_score = 100
    quality_score -= min(claim_rate * 1.5, 30)
    if trial_purchased + trial_returned > 0:
        quality_score += (trial_purchased / (trial_purchased + trial_returned)) * 10
    quality_score = max(0, min(100, int(quality_score)))

    quality_rating = (
        "Excellent" if quality_score >= 90
        else "Good" if quality_score >= 75
        else "Fair" if quality_score >= 60
        else "Poor"
    )

    return {
        "devices": devices,
        "device_count": len(devices),
        "active_warranties": active_warranties,
        "warranty_count": len(warranties),
        "claim_count": len(claims),
        "claim_rate": round(claim_rate, 1),
        "trials": trials,
        "trial_purchased": trial_purchased,
        "trial_returned": trial_returned,
        "trial_active": trial_active,
        "quality_score": quality_score,
        "quality_rating": quality_rating,
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
    """Vendor list page — profiles + vendors from inventory without profiles."""
    profiles = db.query(VendorProfile).order_by(VendorProfile.name).all()
    profiled_names = {p.name.lower() for p in profiles}

    # Collect all vendor strings from inventory that don't have a profile yet
    unlinked_names: set[str] = set()
    for model in TABLE_MODELS.values():
        if not hasattr(model, "vendor"):
            continue
        rows = db.query(model.vendor).filter(model.vendor.isnot(None)).distinct().all()
        for (v,) in rows:
            if v and v.strip() and v.strip().lower() not in profiled_names:
                unlinked_names.add(v.strip())

    return templates.TemplateResponse("vendors.html", {
        "request": request,
        "user": user,
        "profiles": profiles,
        "unlinked_vendors": sorted(unlinked_names),
    })


@router.get("/vendors/{vendor_id}", response_class=HTMLResponse)
def vendor_profile_detail(
    vendor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_viewer),
):
    """Vendor detail: contact profile card + procurement analytics (if permitted)."""
    profile = db.query(VendorProfile).filter(VendorProfile.id == vendor_id).first()
    if not profile:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"{BP}/vendors/", status_code=303)

    analytics = _vendor_analytics(db, profile.name)

    return templates.TemplateResponse("vendor_detail_profile.html", {
        "request": request,
        "user": user,
        "profile": profile,
        "can_edit": user.has_receipts_access,
        "delete_request": pending_for(db, "vendor_profiles", profile.id),
        **analytics,
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


@router.post("/api/vendors/auto-create")
def auto_create_vendors(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Seed vendor profiles for all known vendor strings in inventory that don't have one yet."""
    profiled_names = {p.name.lower() for p in db.query(VendorProfile).all()}
    created = []
    for model in TABLE_MODELS.values():
        if not hasattr(model, "vendor"):
            continue
        rows = db.query(model.vendor).filter(model.vendor.isnot(None)).distinct().all()
        for (v,) in rows:
            if v and v.strip() and v.strip().lower() not in profiled_names:
                name = v.strip()
                profile = VendorProfile(name=name)
                db.add(profile)
                profiled_names.add(name.lower())
                created.append(name)

    db.commit()
    log_event(db, "vendors_auto_created", request=request, user_id=user.id,
              target_table="vendor_profiles", action="create",
              details=f"Auto-created {len(created)} vendor profiles: {', '.join(created[:10])}")

    return JSONResponse(content={"status": "ok", "created": created, "count": len(created)})
