"""Sites & Ownership — manage physical locations and device-to-site assignments."""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_sites_manager
from ..config import settings
from ..database import get_db
from ..models import (
    DeviceAssignment, Site, User,
    TABLE_MODELS, TABLE_DISPLAY_NAMES,
    get_display_name, get_serial,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


# ---------------------------------------------------------------------------
# Site list page
# ---------------------------------------------------------------------------

@router.get("/sites/", response_class=HTMLResponse)
def sites_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sites & Ownership main page."""
    sites = db.query(Site).order_by(Site.name).all()

    # Count active assignments per site
    site_counts = dict(
        db.query(DeviceAssignment.site_id, func.count(DeviceAssignment.id))
        .filter(DeviceAssignment.is_active.is_(True))
        .group_by(DeviceAssignment.site_id)
        .all()
    )

    # Count overdue loaners (active assignments with expected_return in the past)
    today = date.today()
    overdue_count = (
        db.query(func.count(DeviceAssignment.id))
        .filter(
            DeviceAssignment.is_active.is_(True),
            DeviceAssignment.expected_return.isnot(None),
            DeviceAssignment.expected_return < today,
        )
        .scalar()
    ) or 0

    site_list = []
    for s in sites:
        site_list.append({
            "site": s,
            "device_count": site_counts.get(s.id, 0),
        })

    return templates.TemplateResponse("sites.html", {
        "request": request,
        "user": user,
        "sites": site_list,
        "site_types": Site.SITE_TYPES,
        "ownership_types": DeviceAssignment.OWNERSHIP_TYPES,
        "table_names": TABLE_DISPLAY_NAMES,
        "total_sites": len(sites),
        "active_sites": sum(1 for s in sites if s.is_active),
        "total_assignments": sum(site_counts.values()),
        "overdue_count": overdue_count,
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
    """Detail page for a single site showing all assigned devices."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return HTMLResponse(status_code=404, content="Site not found")

    assignments = (
        db.query(DeviceAssignment)
        .filter(DeviceAssignment.site_id == site_id)
        .order_by(DeviceAssignment.is_active.desc(), DeviceAssignment.assigned_date.desc())
        .all()
    )

    # Resolve device details for each assignment
    assignment_list = []
    for a in assignments:
        model = TABLE_MODELS.get(a.device_table)
        device = None
        device_label = f"{a.device_table}#{a.device_id}"
        device_serial = "-"
        if model:
            device = db.query(model).filter(model.id == a.device_id).first()
            if device:
                device_label = get_display_name(device)
                device_serial = get_serial(device)

        is_overdue = (
            a.is_active
            and a.expected_return
            and a.expected_return < date.today()
        )

        assignment_list.append({
            "assignment": a,
            "device_label": device_label,
            "device_serial": device_serial,
            "device_table_display": TABLE_DISPLAY_NAMES.get(a.device_table, a.device_table),
            "is_overdue": is_overdue,
        })

    return templates.TemplateResponse("site_detail.html", {
        "request": request,
        "user": user,
        "site": site,
        "assignments": assignment_list,
        "site_types": Site.SITE_TYPES,
        "ownership_types": DeviceAssignment.OWNERSHIP_TYPES,
        "table_names": TABLE_DISPLAY_NAMES,
        "active_count": sum(1 for a in assignment_list if a["assignment"].is_active),
        "returned_count": sum(1 for a in assignment_list if not a["assignment"].is_active),
    })


# ---------------------------------------------------------------------------
# Site CRUD API
# ---------------------------------------------------------------------------

@router.post("/api/sites")
async def create_site(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Create a new site."""
    body = await request.json()

    name = (body.get("name") or "").strip()
    site_type = body.get("site_type", "").strip()

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

    log_event(
        db, "site_created",
        request=request, user_id=user.id,
        target_table="sites", target_id=site.id,
        action="create",
        new_values=model_to_dict(site),
        details=f"Site '{name}' ({Site.SITE_TYPES[site_type]}) created",
    )

    return JSONResponse(content={"status": "created", "site_id": site.id})


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

    log_event(
        db, "site_updated",
        request=request, user_id=user.id,
        target_table="sites", target_id=site.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(site),
    )

    return JSONResponse(content={"status": "updated"})


@router.delete("/api/sites/{site_id}")
def delete_site(
    site_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Delete a site (cascades to assignments)."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return JSONResponse(status_code=404, content={"error": "Site not found"})

    # Check for active assignments
    active = (
        db.query(func.count(DeviceAssignment.id))
        .filter(DeviceAssignment.site_id == site_id, DeviceAssignment.is_active.is_(True))
        .scalar()
    )
    if active:
        return JSONResponse(
            status_code=409,
            content={"error": f"Cannot delete site with {active} active device assignment(s). Return or reassign devices first."},
        )

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
# Device Assignment API
# ---------------------------------------------------------------------------

@router.post("/api/assignments")
async def assign_device(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Assign a device to a site."""
    body = await request.json()

    device_table = body.get("device_table", "").strip()
    device_id = body.get("device_id")
    site_id = body.get("site_id")
    ownership = body.get("ownership", "").strip()

    if not all([device_table, device_id, site_id, ownership]):
        return JSONResponse(status_code=400, content={"error": "Missing required fields: device_table, device_id, site_id, ownership"})

    if ownership not in DeviceAssignment.OWNERSHIP_TYPES:
        return JSONResponse(status_code=400, content={"error": f"Invalid ownership type: {ownership}"})

    # Validate device exists
    model = TABLE_MODELS.get(device_table)
    if not model:
        return JSONResponse(status_code=400, content={"error": f"Unknown device table: {device_table}"})
    device = db.query(model).filter(model.id == int(device_id)).first()
    if not device:
        return JSONResponse(status_code=404, content={"error": "Device not found"})

    # Validate site exists
    site = db.query(Site).filter(Site.id == int(site_id)).first()
    if not site:
        return JSONResponse(status_code=404, content={"error": "Site not found"})

    # Check if device already has an active assignment
    existing = (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.device_table == device_table,
            DeviceAssignment.device_id == int(device_id),
            DeviceAssignment.is_active.is_(True),
        )
        .first()
    )
    if existing:
        if existing.site_id == int(site_id):
            return JSONResponse(content={"status": "already_assigned", "message": "Device is already assigned to this site"})
        return JSONResponse(
            status_code=409,
            content={"error": f"Device is already assigned to site '{existing.site.name}'. Return it first."},
        )

    assignment = DeviceAssignment(
        device_table=device_table,
        device_id=int(device_id),
        site_id=int(site_id),
        ownership=ownership,
        assigned_date=body.get("assigned_date") or date.today(),
        expected_return=body.get("expected_return") or None,
        assigned_by=user.id,
        notes=(body.get("notes") or "").strip() or None,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    device_label = get_display_name(device)
    log_event(
        db, "device_assigned_to_site",
        request=request, user_id=user.id,
        target_table="device_assignments", target_id=assignment.id,
        action="create",
        new_values=model_to_dict(assignment),
        details=f"{device_label} assigned to {site.name} ({DeviceAssignment.OWNERSHIP_TYPES[ownership]})",
    )

    return JSONResponse(content={"status": "assigned", "assignment_id": assignment.id})


@router.post("/api/assignments/{assignment_id}/return")
async def return_device(
    assignment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Mark a device assignment as returned."""
    assignment = db.query(DeviceAssignment).filter(DeviceAssignment.id == assignment_id).first()
    if not assignment:
        return JSONResponse(status_code=404, content={"error": "Assignment not found"})
    if not assignment.is_active:
        return JSONResponse(status_code=400, content={"error": "Assignment is already returned"})

    old_values = model_to_dict(assignment)

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    assignment.returned_date = body.get("returned_date") or date.today()
    assignment.is_active = False
    if body.get("notes"):
        assignment.notes = (assignment.notes or "") + f"\nReturn: {body['notes']}"

    db.commit()
    db.refresh(assignment)

    log_event(
        db, "device_returned_from_site",
        request=request, user_id=user.id,
        target_table="device_assignments", target_id=assignment.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(assignment),
        details=f"Device returned from site #{assignment.site_id}",
    )

    return JSONResponse(content={"status": "returned"})


@router.delete("/api/assignments/{assignment_id}")
def delete_assignment(
    assignment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Delete an assignment record."""
    assignment = db.query(DeviceAssignment).filter(DeviceAssignment.id == assignment_id).first()
    if not assignment:
        return JSONResponse(status_code=404, content={"error": "Assignment not found"})

    old_values = model_to_dict(assignment)
    db.delete(assignment)
    db.commit()

    log_event(
        db, "assignment_deleted",
        request=request, user_id=user.id,
        target_table="device_assignments", target_id=assignment_id,
        action="delete",
        old_values=old_values,
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
