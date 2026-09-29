"""Edge box provisioning workflow — track pre-deployment stages for pilots and customer sales."""

import copy
import csv
import io
import json
import logging
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import func
from sqlalchemy.orm import Session
from pathlib import Path

from ..audit import log_event
from ..auth import require_sites_manager, require_provisioning_manager, require_provisioning_viewer, get_current_user, User
from ..config import settings
from ..localtime import fmt_local, local_now, local_today, parse_utc, register
from ..database import get_db
from ..delete_requests import LOCK_MESSAGE, locked_ids
from ..models import (
    AuditLog, CustomerOrder, DeviceProvisioning, DEFAULT_PROVISIONING_STAGES,
    Item, Site,
)
from ..notifications import notify
from ..sku_conversion import convert_legacy_sku, is_legacy_sku
from ..zendesk import get_zendesk_client

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)

VALIDATION_REPORT_DIR = Path("/data/validation-reports")


# ---------------------------------------------------------------------------
# Page view
# ---------------------------------------------------------------------------
@router.get("/provisioning/")
def provisioning_redirect():
    """Redirect to unified Fulfillment page."""
    return RedirectResponse(url=f"{BP}/fulfillment/", status_code=301)


@router.get("/provisioning/queue")
def provisioning_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Render the provisioning queue page (legacy — accessible directly)."""
    # Active (incomplete) provisioning records
    active_records = (
        db.query(DeviceProvisioning)
        .filter(DeviceProvisioning.is_complete.is_(False))
        .order_by(DeviceProvisioning.created_at.desc())
        .all()
    )

    # Completed in last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    completed_records = (
        db.query(DeviceProvisioning)
        .filter(
            DeviceProvisioning.is_complete.is_(True),
            DeviceProvisioning.completed_at >= thirty_days_ago,
        )
        .order_by(DeviceProvisioning.completed_at.desc())
        .all()
    )

    # Stage counts
    stage_counts = {}
    for stage_def in DEFAULT_PROVISIONING_STAGES:
        stage_counts[stage_def["name"]] = 0
    for rec in active_records:
        stage_counts[rec.current_stage] = stage_counts.get(rec.current_stage, 0) + 1

    # Overdue: no activity for 7+ days on incomplete records
    now = datetime.utcnow()
    overdue_count = sum(
        1 for r in active_records
        if r.updated_at and (now - r.updated_at).days >= 7
    )

    # Date-based alerts
    overdue_due_date_count = sum(
        1 for r in active_records
        if r.due_date and r.due_date < local_today()
    )
    due_soon_count = sum(
        1 for r in active_records
        if r.due_date and 0 <= (r.due_date - local_today()).days <= 7
    )

    # Resolve device names, deployment types, and assignee names
    queue_items = []
    for rec in active_records:
        unit = _resolve_unit(db, rec)
        device_name = _resolve_device_name(db, rec)
        display_table = _unit_category_label(unit)
        site_name = rec.site.name if rec.site else "—"
        assignee_name = rec.assignee.display_name if rec.assignee else "Unassigned"
        deployment_type = _unit_deployment_type(unit)

        # Progress calculation
        stages = rec.stages or []
        completed_stages = sum(1 for s in stages if s.get("completed"))
        total_stages = len(stages)
        progress_pct = round((completed_stages / total_stages * 100)) if total_stages > 0 else 0

        # Days since last update
        days_in_stage = (now - rec.updated_at).days if rec.updated_at else 0

        # Date status
        due_soon = False
        is_overdue_due_date = False
        if rec.due_date:
            days_until_due = (rec.due_date - local_today()).days
            is_overdue_due_date = days_until_due < 0
            due_soon = 0 <= days_until_due <= 7

        queue_items.append({
            "id": rec.id,
            "device_name": device_name,
            "display_table": display_table,
            "deployment_type": deployment_type,
            "site_id": rec.site_id,
            "site_name": site_name,
            "assigned_to": rec.assigned_to,
            "current_stage": rec.current_stage,
            "current_stage_label": _get_stage_label(rec.stages, rec.current_stage),
            "assignee_name": assignee_name,
            "priority": rec.priority or "normal",
            "completed_stages": completed_stages,
            "total_stages": total_stages,
            "progress_pct": progress_pct,
            "days_in_stage": days_in_stage,
            "is_overdue": days_in_stage >= 7,
            "notes": rec.notes,
            "stages": rec.stages,
            "due_date": rec.due_date.isoformat() if rec.due_date else None,
            "start_date": rec.start_date.isoformat() if rec.start_date else None,
            "location_note": rec.location_note,
            "deployment_bucket": rec.deployment_bucket,
            "is_overdue_due_date": is_overdue_due_date,
            "due_soon": due_soon,
            "validation_result": rec.validation_result,
            "validation_date": fmt_local(rec.validation_date, "%Y-%m-%d %H:%M %Z") if rec.validation_date else None,
            "has_validation_report": bool(rec.validation_report_path),
            "zendesk_ticket_id": rec.zendesk_ticket_id,
        })

    # Completed items
    completed_items = []
    for rec in completed_records:
        completed_items.append({
            "id": rec.id,
            "device_name": _resolve_device_name(db, rec),
            "display_table": _unit_category_label(_resolve_unit(db, rec)),
            "deployment_type": _resolve_deployment_type(db, rec),
            "site_name": rec.site.name if rec.site else "—",
            "completed_at": fmt_local(rec.completed_at, "%Y-%m-%d") if rec.completed_at else "",
            "deployment_bucket": rec.deployment_bucket,
            "location_note": rec.location_note,
            "validation_result": rec.validation_result,
            "has_validation_report": bool(rec.validation_report_path),
            "zendesk_ticket_id": rec.zendesk_ticket_id,
        })

    # Sites and users for the create modal dropdowns (deploy targets = customer sites)
    sites = db.query(Site).filter(Site.is_active.is_(True), Site.site_type == "customer_site").order_by(Site.name).all()
    from ..models import User as UserModel
    users_q = db.query(UserModel).filter(UserModel.is_active.is_(True))
    if user.role != "justin_admin":
        users_q = users_q.filter(
            ~UserModel.username.like("test_%"),
            ~UserModel.username.like("dbg_%"),
        )
    users = users_q.order_by(UserModel.display_name).all()

    # Open customer orders for the create modal — not yet shipped/delivered/installed
    # cancelled joins the terminal set: a cancelled order is ended and must
    # not offer itself as provisionable (docs/specs/customer-order-cancel.md).
    _terminal = ("shipped", "delivered", "installed", "cancelled")
    open_orders = (
        db.query(CustomerOrder)
        .filter(~CustomerOrder.status.in_(_terminal))
        .order_by(CustomerOrder.created_at.desc())
        .all()
    )

    return templates.TemplateResponse("provisioning.html", {
        "request": request,
        "user": user,
        "can_manage": user.has_provisioning_manage,
        "queue_items": queue_items,
        "completed_items": completed_items,
        "total_active": len(active_records),
        "stage_counts": stage_counts,
        "overdue_count": overdue_count,
        "completed_count": len(completed_records),
        "default_stages": DEFAULT_PROVISIONING_STAGES,
        "sites": sites,
        "users_list": users,
        "open_orders": open_orders,
        "overdue_due_date_count": overdue_due_date_count,
        "due_soon_count": due_soon_count,
        "deployment_buckets": DeviceProvisioning.DEPLOYMENT_BUCKETS,
    })


# ---------------------------------------------------------------------------
# Detail page for a single provisioning record
# ---------------------------------------------------------------------------
@router.get("/provisioning/{prov_id}")
def provisioning_detail_page(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Render the provisioning detail page with visual stage pipeline."""
    from fastapi.responses import RedirectResponse
    from sqlalchemy import desc

    rec = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not rec:
        return RedirectResponse(url=f"{BP}/provisioning/", status_code=302)

    # Resolve device info
    unit = _resolve_unit(db, rec)
    device_name = _resolve_device_name(db, rec)
    deployment_type = _unit_deployment_type(unit)
    display_table = _unit_category_label(unit)

    # Edge box details for the device section (item 30 S4: read off the item)
    edge_box = _edge_box_view(unit)

    # Stage progress
    stages = rec.stages or []
    completed_stages = sum(1 for s in stages if s.get("completed"))
    total_stages = len(stages)
    progress_pct = round((completed_stages / total_stages * 100)) if total_stages else 0

    # Timing
    now = datetime.utcnow()
    days_active = (now - rec.created_at).days if rec.created_at else 0

    # Due date status
    is_overdue_due_date = False
    due_soon = False
    if rec.due_date:
        days_until_due = (rec.due_date - local_today()).days
        is_overdue_due_date = days_until_due < 0
        due_soon = 0 <= days_until_due <= 7

    # Audit log entries for this record
    audit_entries = (
        db.query(AuditLog)
        .filter(
            AuditLog.target_table == "device_provisioning",
            AuditLog.target_id == prov_id,
        )
        .order_by(desc(AuditLog.timestamp))
        .limit(50)
        .all()
    )

    # Map user IDs to display names for the audit timeline
    from ..models import User as UserModel
    audit_user_ids = {e.user_id for e in audit_entries if e.user_id}
    audit_users_map = {}
    if audit_user_ids:
        for u in db.query(UserModel).filter(UserModel.id.in_(audit_user_ids)).all():
            audit_users_map[u.id] = u.display_name or u.username

    # Sites for the edit dropdown: customer sites plus the record's current
    # site if it is another type, so a full-form save never blanks it.
    sites = db.query(Site).filter(Site.is_active.is_(True), Site.site_type == "customer_site").order_by(Site.name).all()
    if rec.site_id and all(s.id != rec.site_id for s in sites):
        cur = db.query(Site).filter(Site.id == rec.site_id).first()
        if cur:
            sites = sorted(sites + [cur], key=lambda s: s.name or "")
    users_q = db.query(UserModel).filter(UserModel.is_active.is_(True))
    if user.role != "justin_admin":
        users_q = users_q.filter(
            ~UserModel.username.like("test_%"),
            ~UserModel.username.like("dbg_%"),
        )
    users_list = users_q.order_by(UserModel.display_name).all()

    return templates.TemplateResponse("provisioning_detail.html", {
        "request": request,
        "user": user,
        "can_manage": user.has_provisioning_manage,
        "rec": rec,
        "device_name": device_name,
        "deployment_type": deployment_type,
        "display_table": display_table,
        "edge_box": edge_box,
        "stages": stages,
        "completed_stages": completed_stages,
        "total_stages": total_stages,
        "progress_pct": progress_pct,
        "days_active": days_active,
        "is_overdue_due_date": is_overdue_due_date,
        "due_soon": due_soon,
        "site_name": rec.site.name if rec.site else "Not assigned",
        "assignee_name": rec.assignee.display_name if rec.assignee else "Unassigned",
        "creator_name": rec.creator.display_name if rec.creator else "System",
        "audit_entries": audit_entries,
        "audit_users_map": audit_users_map,
        "sites": sites,
        "users_list": users_list,
        "deployment_buckets": DeviceProvisioning.DEPLOYMENT_BUCKETS,
        "bucket_label": DeviceProvisioning.DEPLOYMENT_BUCKETS.get(
            rec.deployment_bucket or "", rec.deployment_bucket or "None"
        ),
    })


# ---------------------------------------------------------------------------
# API: Get provisioning items by bucket (for Kanban board view)
# ---------------------------------------------------------------------------
@router.get("/api/provisioning/by-bucket")
def get_provisioning_by_bucket(
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Return active provisioning items grouped by deployment_bucket."""
    active_records = (
        db.query(DeviceProvisioning)
        .filter(DeviceProvisioning.is_complete.is_(False))
        .order_by(DeviceProvisioning.created_at.desc())
        .all()
    )

    # Group by bucket
    buckets = {bucket_key: [] for bucket_key in DeviceProvisioning.DEPLOYMENT_BUCKETS.keys()}
    buckets["no_bucket"] = []  # For items without a bucket assigned

    now = datetime.utcnow()
    for rec in active_records:
        device_name = _resolve_device_name(db, rec)
        deployment_type = _resolve_deployment_type(db, rec)
        assignee_name = rec.assignee.display_name if rec.assignee else "Unassigned"

        # Progress calculation
        stages = rec.stages or []
        completed_stages = sum(1 for s in stages if s.get("completed"))
        total_stages = len(stages)

        # Date status
        due_soon = False
        is_overdue_due_date = False
        if rec.due_date:
            days_until_due = (rec.due_date - local_today()).days
            is_overdue_due_date = days_until_due < 0
            due_soon = 0 <= days_until_due <= 7

        item = {
            "id": rec.id,
            "device_name": device_name,
            "deployment_type": deployment_type,
            "assignee_name": assignee_name,
            "priority": rec.priority or "normal",
            "due_date": rec.due_date.isoformat() if rec.due_date else None,
            "location_note": rec.location_note,
            "completed_stages": completed_stages,
            "total_stages": total_stages,
            "is_overdue_due_date": is_overdue_due_date,
            "due_soon": due_soon,
            "current_stage": rec.current_stage,
            "zendesk_ticket_id": rec.zendesk_ticket_id,
        }

        bucket_key = rec.deployment_bucket or "no_bucket"
        if bucket_key in buckets:
            buckets[bucket_key].append(item)
        else:
            buckets["no_bucket"].append(item)

    return JSONResponse(content={"buckets": buckets, "bucket_labels": DeviceProvisioning.DEPLOYMENT_BUCKETS})


# ---------------------------------------------------------------------------
# API: Create provisioning record
# ---------------------------------------------------------------------------
@router.post("/api/provisioning")
async def create_provisioning(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Create a new provisioning record for an edge box item."""
    body = await request.json()
    item_id = body.get("item_id")
    site_id = body.get("site_id")
    assigned_to = body.get("assigned_to")
    priority = (body.get("priority") or "normal").strip()
    notes = (body.get("notes") or "").strip()
    deployment_type = (body.get("deployment_type") or "").strip()

    # Pipeline fields
    due_date_str = (body.get("due_date") or "").strip()
    start_date_str = (body.get("start_date") or "").strip()
    location_note = (body.get("location_note") or "").strip()
    deployment_bucket = (body.get("deployment_bucket") or "").strip()

    # Zendesk integration
    zendesk_ticket_id = body.get("zendesk_ticket_id")

    # Customer order linkage
    customer_order_id = body.get("customer_order_id") or None
    if customer_order_id:
        customer_order_id = int(customer_order_id)
        order = db.query(CustomerOrder).filter(CustomerOrder.id == customer_order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Customer order not found"})
        if not order.po_number:
            return JSONResponse(status_code=400, content={"error": f"Order {order.order_number} has no Customer PO - add one before assigning devices"})

    # Validate required fields
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "item_id is required"})

    # Validate the edge box item exists (item 30 S4: provisioning runs on items)
    device = db.query(Item).filter(Item.id == item_id).first()
    if not device:
        return JSONResponse(status_code=404, content={"error": "Edge box not found"})
    if str(device.item_category or "") != "edge_box":
        return JSONResponse(status_code=400, content={"error": "Provisioning is only available for edge boxes"})
    if locked_ids(db, "items", [device.id]):
        return JSONResponse(status_code=409, content={"error": LOCK_MESSAGE})

    # Validate priority
    if priority not in DeviceProvisioning.PRIORITY_TYPES:
        return JSONResponse(status_code=400, content={"error": f"Invalid priority: {priority}"})

    # Check no active provisioning already exists for this device
    existing = (
        db.query(DeviceProvisioning)
        .filter(
            DeviceProvisioning.item_id == item_id,
            DeviceProvisioning.is_complete.is_(False),
        )
        .first()
    )
    if existing:
        return JSONResponse(status_code=409, content={"error": "Device already has active provisioning"})

    # Validate site if provided
    if site_id:
        site = db.query(Site).filter(Site.id == int(site_id)).first()
        if not site:
            return JSONResponse(status_code=404, content={"error": "Site not found"})

    # Update the item's deployment_type attribute if provided (reassign the
    # dict: SQLAlchemy does not track in-place JSONB mutation)
    if deployment_type in ("pilot", "customer"):
        device.attributes = {**(device.attributes or {}), "deployment_type": deployment_type}

    # Parse dates
    parsed_due_date = None
    parsed_start_date = None
    if due_date_str:
        try:
            parsed_due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid due_date format, use YYYY-MM-DD"})
    if start_date_str:
        try:
            parsed_start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid start_date format, use YYYY-MM-DD"})

    # Validate deployment_bucket if provided
    if deployment_bucket and deployment_bucket not in DeviceProvisioning.DEPLOYMENT_BUCKETS:
        return JSONResponse(status_code=400, content={"error": f"Invalid deployment_bucket: {deployment_bucket}"})

    # Create record with default stages
    rec = DeviceProvisioning(
        item_id=item_id,
        site_id=int(site_id) if site_id else None,
        current_stage="staged",
        stages=copy.deepcopy(DEFAULT_PROVISIONING_STAGES),
        assigned_to=int(assigned_to) if assigned_to else None,
        priority=priority,
        notes=notes or None,
        created_by=user.id,
        due_date=parsed_due_date,
        start_date=parsed_start_date,
        location_note=location_note or None,
        deployment_bucket=deployment_bucket or None,
        zendesk_ticket_id=int(zendesk_ticket_id) if zendesk_ticket_id else None,
        customer_order_id=customer_order_id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    log_event(
        db, "provisioning_created",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="create",
        details=f"Created edge box provisioning for item #{item_id} ({deployment_type or 'unspecified'})"
               + (f" → order {customer_order_id}" if customer_order_id else ""),
    )

    return JSONResponse(content={
        "status": "created",
        "id": rec.id,
        "device_name": device.item_name or device.item_sn or f"Item #{item_id}",
    })


# ---------------------------------------------------------------------------
# API: Fetch Zendesk ticket context
# ---------------------------------------------------------------------------
@router.get("/api/provisioning/zendesk-ticket/{ticket_id}")
async def fetch_zendesk_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Fetch Zendesk ticket context for provisioning integration.

    Returns ticket subject, organization, edge box details (serial, UUID, MACs,
    licenses), and auto-matches to existing inventory by serial number.
    """
    client = get_zendesk_client()
    if not client:
        return JSONResponse(
            status_code=503,
            content={"error": "Zendesk not configured. Contact system administrator."}
        )

    try:
        # Fetch ticket
        ticket_data = await client.get_ticket(ticket_id)
        ticket = ticket_data.get("ticket", {})

        # Fetch organization if linked
        org_name = None
        if ticket.get("organization_id"):
            try:
                org_data = await client.get_organization(ticket["organization_id"])
                org_name = org_data.get("organization", {}).get("name")
            except Exception:
                pass  # Org fetch failed, continue without it

        # Extract ticket info
        subject = ticket.get("subject", "No subject")
        status = ticket.get("status", "unknown")
        priority = ticket.get("priority")

        # Parse custom fields for edge box details
        custom_fields = ticket.get("custom_fields", [])

        # Custom field ID mapping
        FIELD_IDS = {
            "customer_site": 35554814009492,
            "serial_number": 36035253226388,
            "partner_org": 39620185153940,
            "uuid": 39804698827028,
            "mac1": 39804720494740,
            "mac2": 39804797179156,
            "licenses": 39804910994708,
            "due_date": 40262749778068,
            "service_type": 26350801370900,  # Legacy SKU field
        }

        # Extract values
        field_values = {}
        for field in custom_fields:
            field_id = field.get("id")
            value = field.get("value")
            if value:
                for name, fid in FIELD_IDS.items():
                    if field_id == fid:
                        field_values[name] = value
                        break

        # Extract specific fields
        serial_number = field_values.get("serial_number")
        uuid = field_values.get("uuid")
        mac1 = field_values.get("mac1")
        mac2 = field_values.get("mac2")
        customer_site = field_values.get("customer_site")
        licenses = field_values.get("licenses")
        due_date = field_values.get("due_date")
        legacy_sku = field_values.get("service_type")

        # Convert legacy SKU if present
        new_sku = None
        if legacy_sku and is_legacy_sku(legacy_sku):
            new_sku = convert_legacy_sku(legacy_sku)

        # Look up the edge box item in inventory by serial number
        inventory_match = None
        if serial_number:
            item = (
                db.query(Item)
                .filter(Item.item_category == "edge_box",
                        func.lower(Item.item_sn) == serial_number.strip().lower())
                .first()
            )
            view = _edge_box_view(item)
            if view:
                inventory_match = {
                    "id": item.id,
                    "serial": view.serial,
                    "part_number": view.part_number or "",
                    "sku_version": view.sku_version or "legacy",
                    "status": view.status,
                    "deployment_type": view.deployment_type,
                    "customer": (item.attributes or {}).get("customer"),
                }

        await client.close()

        return JSONResponse(content={
            "ticket_id": ticket_id,
            "subject": subject,
            "status": status,
            "priority": priority,
            "organization": org_name,
            "edge_box": {
                "serial_number": serial_number,
                "uuid": uuid,
                "mac1": mac1,
                "mac2": mac2,
                "customer_site": customer_site,
                "licenses": licenses,
                "due_date": due_date,
            },
            "legacy_sku": legacy_sku,
            "new_sku": new_sku,
            "inventory_match": inventory_match,
            "url": f"https://example-help.zendesk.com/agent/tickets/{ticket_id}",
        })

    except Exception as e:
        return JSONResponse(
            status_code=404 if "404" in str(e) else 500,
            content={"error": f"Failed to fetch ticket: {str(e)}"}
        )


# ---------------------------------------------------------------------------
# API: List Zendesk organizations (for customer dropdown)
# ---------------------------------------------------------------------------
@router.get("/api/provisioning/zendesk-orgs")
async def list_zendesk_orgs(
    user: User = Depends(require_provisioning_viewer),
):
    """Fetch Zendesk organizations for the customer name dropdown."""
    client = get_zendesk_client()
    if not client:
        return JSONResponse(
            status_code=503,
            content={"error": "Zendesk not configured. Contact system administrator."},
        )
    try:
        result = await client.list_organizations(per_page=100)
        orgs = []
        for o in result.get("organizations", []):
            name = (o.get("name") or "").strip()
            # Skip junk entries: empty, numeric-only, or very short
            if not name or name.replace("-", "").replace(".", "").isdigit() or len(name) < 3:
                continue
            orgs.append({"id": o["id"], "name": name})
        orgs.sort(key=lambda x: x["name"].lower())
        return JSONResponse(content={"organizations": orgs})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch organizations: {str(e)}"},
        )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# API: Advance to next stage
# ---------------------------------------------------------------------------
@router.post("/api/provisioning/{prov_id}/advance")
async def advance_provisioning(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Complete the current stage and advance to the next."""
    rec = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})

    if rec.is_complete:
        return JSONResponse(status_code=400, content={"error": "Provisioning already complete"})

    # Every row links an item (item 30 S4). Two shapes: edge box rows created
    # here carry the stage machine; C2C cameras (c2c.py) and stock units
    # assigned to orders (orders.py) carry stages=[] and current_stage
    # "acquired" as a label only. The label rows never complete through this
    # pipeline, so reject them at the source.
    if not rec.stages:
        return JSONResponse(
            status_code=400,
            content={"error": "This unit has no provisioning stages to advance"},
        )

    stages = copy.deepcopy(rec.stages)  # deep copy for JSONB mutation tracking
    now_str = datetime.utcnow().isoformat()

    # Find current stage and mark completed
    current_idx = None
    for i, stage in enumerate(stages):
        if stage["name"] == rec.current_stage and not stage["completed"]:
            current_idx = i
            break

    if current_idx is None:
        return JSONResponse(status_code=400, content={"error": "Current stage not found or already completed"})

    stages[current_idx]["completed"] = True
    stages[current_idx]["completed_at"] = now_str
    stages[current_idx]["completed_by"] = user.display_name or user.username

    completed_stage_name = stages[current_idx]["label"]

    # Find next incomplete stage
    next_stage = None
    for stage in stages[current_idx + 1:]:
        if not stage["completed"]:
            next_stage = stage["name"]
            break

    # UUID is required before entering registration stage
    unit = _resolve_unit(db, rec)
    if next_stage == "registered" and unit is not None and str(unit.item_category or "") == "edge_box":
        if not unit.appliance_uuid:
            return JSONResponse(
                status_code=400,
                content={"error": "Edge box UUID is required before registration. Update the edge box record with its UUID first."},
            )

    if next_stage:
        rec.current_stage = next_stage
    else:
        # All stages complete
        rec.is_complete = True
        rec.completed_at = datetime.utcnow()

        # Device-to-site assignments were retired in item 30 S4 (sites area);
        # completion no longer writes one. The item's place is its location_id.

        # Auto-update the edge box item to Deployed
        if unit is not None:
            unit.item_status = "Deployed"
            attrs = unit.attributes or {}
            if not attrs.get("deployment_type"):
                unit.attributes = {**attrs, "deployment_type": "customer"}

    rec.stages = stages  # trigger JSONB update
    db.commit()

    log_event(
        db, "provisioning_stage_completed",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="update",
        details=f"Completed stage '{completed_stage_name}' for provisioning #{rec.id}",
    )

    # Send notification
    device_name = _resolve_device_name(db, rec)
    if rec.is_complete:
        await notify(
            db, "provisioning_complete",
            title="Provisioning Complete",
            message=f"{device_name} fully provisioned by {user.display_name}. All stages finished.",
            link=f"{BP}/provisioning/{rec.id}",
            actor_id=user.id,
            resource_type="provisioning",
            resource_id=rec.id,
        )
    else:
        next_label = _get_stage_label(stages, rec.current_stage)
        await notify(
            db, "provisioning_advance",
            title="Stage Advanced",
            message=f"{device_name}: '{completed_stage_name}' completed by {user.display_name}. Now at '{next_label}'.",
            link=f"{BP}/provisioning/{rec.id}",
            actor_id=user.id,
            resource_type="provisioning",
            resource_id=rec.id,
        )

    # Zendesk integration: post stage update or solve ticket on completion
    if rec.zendesk_ticket_id:
        try:
            client = get_zendesk_client()
            if client:
                device_name = _resolve_device_name(db, rec)
                if rec.is_complete:
                    await client.update_ticket_status(
                        rec.zendesk_ticket_id,
                        "solved",
                        comment=(
                            f"Edge box '{device_name}' provisioning complete. "
                            f"All stages finished by {user.display_name or user.username}."
                        ),
                    )
                else:
                    await client.add_ticket_comment(
                        rec.zendesk_ticket_id,
                        (
                            f"Edge box '{device_name}' advanced to stage "
                            f"'{_get_stage_label(stages, rec.current_stage)}' "
                            f"by {user.display_name or user.username}."
                        ),
                        public=False,
                    )
                await client.close()
        except Exception as e:
            logger.warning(
                "Failed to update Zendesk ticket %s: %s",
                rec.zendesk_ticket_id, e,
            )

    return JSONResponse(content={
        "status": "completed" if rec.is_complete else "advanced",
        "current_stage": rec.current_stage,
        "is_complete": rec.is_complete,
        "completed_stage": completed_stage_name,
    })


# ---------------------------------------------------------------------------
# API: Revert last completed stage
# ---------------------------------------------------------------------------
@router.post("/api/provisioning/{prov_id}/revert")
async def revert_provisioning(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Revert the last completed stage."""
    rec = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})

    stages = copy.deepcopy(rec.stages)

    # Find the last completed stage
    last_completed_idx = None
    for i in range(len(stages) - 1, -1, -1):
        if stages[i]["completed"]:
            last_completed_idx = i
            break

    if last_completed_idx is None:
        return JSONResponse(status_code=400, content={"error": "No completed stages to revert"})

    reverted_name = stages[last_completed_idx]["label"]
    stages[last_completed_idx]["completed"] = False
    stages[last_completed_idx]["completed_at"] = None
    stages[last_completed_idx]["completed_by"] = None

    rec.current_stage = stages[last_completed_idx]["name"]
    rec.is_complete = False
    rec.completed_at = None
    rec.stages = stages
    db.commit()

    log_event(
        db, "provisioning_stage_reverted",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="update",
        details=f"Reverted stage '{reverted_name}' for provisioning #{rec.id}",
    )

    # Send notification
    device_name = _resolve_device_name(db, rec)
    await notify(
        db, "provisioning_revert",
        title="Stage Reverted",
        message=f"{device_name}: '{reverted_name}' reverted by {user.display_name}. Back to '{reverted_name}'.",
        link=f"{BP}/provisioning/{rec.id}",
        actor_id=user.id,
        resource_type="provisioning",
        resource_id=rec.id,
    )

    return JSONResponse(content={
        "status": "reverted",
        "current_stage": rec.current_stage,
        "reverted_stage": reverted_name,
    })


# ---------------------------------------------------------------------------
# API: Update provisioning metadata
# ---------------------------------------------------------------------------
@router.put("/api/provisioning/{prov_id}")
async def update_provisioning(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Update provisioning record metadata (site, assignee, priority, notes)."""
    rec = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})

    body = await request.json()
    changed = []

    if "site_id" in body:
        site_id = body["site_id"]
        if site_id:
            site = db.query(Site).filter(Site.id == int(site_id)).first()
            if not site:
                return JSONResponse(status_code=404, content={"error": "Site not found"})
        rec.site_id = int(site_id) if site_id else None
        if rec.item_id:
            item = db.query(Item).filter(Item.id == rec.item_id).first()
            if item:
                item.location_id = rec.site_id  # unit follows its site both ways (Migration 063)
        changed.append("site")

    if "assigned_to" in body:
        rec.assigned_to = int(body["assigned_to"]) if body["assigned_to"] else None
        changed.append("assigned_to")

    if "priority" in body:
        priority = (body["priority"] or "normal").strip()
        if priority not in DeviceProvisioning.PRIORITY_TYPES:
            return JSONResponse(status_code=400, content={"error": f"Invalid priority: {priority}"})
        rec.priority = priority
        changed.append("priority")

    if "notes" in body:
        rec.notes = (body["notes"] or "").strip() or None
        changed.append("notes")

    # Pipeline fields
    if "due_date" in body:
        due_date_str = (body["due_date"] or "").strip()
        if due_date_str:
            try:
                rec.due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid due_date format, use YYYY-MM-DD"})
        else:
            rec.due_date = None
        changed.append("due_date")

    if "start_date" in body:
        start_date_str = (body["start_date"] or "").strip()
        if start_date_str:
            try:
                rec.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid start_date format, use YYYY-MM-DD"})
        else:
            rec.start_date = None
        changed.append("start_date")

    if "location_note" in body:
        rec.location_note = (body["location_note"] or "").strip() or None
        changed.append("location_note")

    if "deployment_bucket" in body:
        deployment_bucket = (body["deployment_bucket"] or "").strip()
        if deployment_bucket and deployment_bucket not in DeviceProvisioning.DEPLOYMENT_BUCKETS:
            return JSONResponse(status_code=400, content={"error": f"Invalid deployment_bucket: {deployment_bucket}"})
        rec.deployment_bucket = deployment_bucket or None
        changed.append("deployment_bucket")

    db.commit()

    log_event(
        db, "provisioning_updated",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="update",
        details=f"Updated provisioning #{rec.id}: {', '.join(changed)}",
    )

    return JSONResponse(content={"status": "updated", "changed": changed})


# ---------------------------------------------------------------------------
# API: Delete provisioning record
# ---------------------------------------------------------------------------
@router.delete("/api/provisioning/{prov_id}")
def delete_provisioning(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Delete a provisioning record."""
    rec = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})

    log_event(
        db, "provisioning_deleted",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="delete",
        details=f"Deleted provisioning #{rec.id} (item {rec.item_id})",
    )

    db.delete(rec)
    db.commit()

    return JSONResponse(content={"status": "deleted"})


# ---------------------------------------------------------------------------
# API: Upload validation report
# ---------------------------------------------------------------------------
@router.post("/api/provisioning/{prov_id}/validation-report")
async def upload_validation_report(
    prov_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Upload a validate.py JSON report for this provisioning record."""
    rec = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})

    # Validate file type (JSON only)
    if file.content_type not in ("application/json", "text/json", "text/plain"):
        return JSONResponse(status_code=400, content={"error": "Only JSON files allowed"})

    # Read and validate JSON content
    content = await file.read()
    try:
        report_data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON file"})

    # Validate it looks like a validate report
    if "report_version" not in report_data or "result" not in report_data:
        return JSONResponse(status_code=400, content={
            "error": "Not a valid validate report (missing report_version or result)"
        })

    overall_result = report_data.get("result", {}).get("overall", "UNKNOWN")
    validation_date_str = report_data.get("timestamp")

    # Store file
    VALIDATION_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"validate_{prov_id}_{uuid.uuid4().hex[:8]}.json"
    file_path = VALIDATION_REPORT_DIR / stored_name

    with open(file_path, "wb") as f:
        f.write(content)

    # Remove old report if replacing
    if rec.validation_report_path:
        old_path = Path(rec.validation_report_path)
        if old_path.exists():
            old_path.unlink()

    # Update record
    rec.validation_report_path = str(file_path)
    rec.validation_result = overall_result
    parsed = parse_utc(validation_date_str)
    rec.validation_date = parsed if parsed is not None else datetime.utcnow()

    db.commit()

    log_event(
        db, "validation_report_uploaded",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="update",
        details=(
            f"Validation report uploaded: {file.filename} "
            f"({len(content)} bytes, result={overall_result})"
        ),
    )

    return JSONResponse(content={
        "status": "uploaded",
        "result": overall_result,
        "device": report_data.get("device", {}),
        "checks": report_data.get("result", {}),
    })


@router.get("/api/provisioning/{prov_id}/validation-report")
def download_validation_report(
    prov_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download the validation report for a provisioning record."""
    rec = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not rec or not rec.validation_report_path:
        return JSONResponse(status_code=404, content={"error": "Validation report not found"})

    file_path = Path(rec.validation_report_path)
    if not file_path.exists():
        return JSONResponse(status_code=404, content={"error": "Report file missing from disk"})

    return FileResponse(path=str(file_path), filename=file_path.name, media_type="application/json")


@router.delete("/api/provisioning/{prov_id}/validation-report")
def delete_validation_report(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Remove the validation report from a provisioning record."""
    rec = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})

    if rec.validation_report_path:
        old_path = Path(rec.validation_report_path)
        if old_path.exists():
            old_path.unlink()

    rec.validation_report_path = None
    rec.validation_result = None
    rec.validation_date = None
    db.commit()

    log_event(
        db, "validation_report_deleted",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="update",
        details=f"Validation report removed from provisioning #{rec.id}",
    )

    return JSONResponse(content={"status": "deleted"})


# ---------------------------------------------------------------------------
# API: Get devices for a category (HTMX dropdown helper)
# ---------------------------------------------------------------------------
@router.get("/api/provisioning/devices/{table_name}")
def get_devices_for_category(
    table_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Return edge box items for the create modal dropdown.

    Item 30 S4: the path keeps its edge_boxes segment for the page's fetch,
    and the list is edge_box items. Filters out items with no serial and
    items already in an active (non-complete) provisioning workflow.
    """
    if table_name != "edge_boxes":
        return JSONResponse(status_code=400, content={"error": f"Invalid category: {table_name}"})

    already_provisioned = {
        row[0]
        for row in db.query(DeviceProvisioning.item_id)
        .filter(
            DeviceProvisioning.item_id.isnot(None),
            DeviceProvisioning.is_complete.is_(False),
        )
        .all()
    }
    devices = (
        db.query(Item)
        .filter(
            Item.item_category == "edge_box",
            Item.item_sn.isnot(None),
            Item.item_sn != "",
        )
        .order_by(Item.item_sn)
        .all()
    )

    result = []
    for d in devices:
        if d.id in already_provisioned:
            continue
        view = _edge_box_view(d)
        display = f"{view.serial} ({view.part_number})" if view.part_number else view.serial
        owner = (d.attributes or {}).get("customer") or d.department_or_owner
        if owner:
            display = f"{display} — {owner}"
        result.append({
            "id": d.id,
            "name": display,
            "sku_version": view.sku_version or "legacy",
        })

    return JSONResponse(content={"devices": result})


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@router.get("/api/provisioning/export")
def export_provisioning(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Export all provisioning records to CSV or Excel."""
    records = (
        db.query(DeviceProvisioning)
        .order_by(DeviceProvisioning.created_at.desc())
        .all()
    )

    rows = []
    for rec in records:
        device_name = _resolve_device_name(db, rec)
        site_name = rec.site.name if rec.site else ""
        assignee_name = rec.assignee.display_name if rec.assignee else ""
        deployment_type = _resolve_deployment_type(db, rec)
        stages = rec.stages or []
        completed_stages = sum(1 for s in stages if s.get("completed"))
        stage_label = _get_stage_label(stages, rec.current_stage)
        bucket_label = DeviceProvisioning.DEPLOYMENT_BUCKETS.get(
            rec.deployment_bucket or "", rec.deployment_bucket or ""
        )

        rows.append({
            "Edge Box": device_name,
            "Deployment Type": deployment_type,
            "Target Site": site_name,
            "Current Stage": stage_label,
            "Progress": f"{completed_stages}/{len(stages)}",
            "Priority": (rec.priority or "normal").capitalize(),
            "Assigned To": assignee_name,
            "Pipeline Bucket": bucket_label,
            "Start Date": str(rec.start_date) if rec.start_date else "",
            "Due Date": str(rec.due_date) if rec.due_date else "",
            "Location": rec.location_note or "",
            "Zendesk Ticket": str(rec.zendesk_ticket_id) if rec.zendesk_ticket_id else "",
            "Status": "Completed" if rec.is_complete else "In Progress",
            "Completed At": fmt_local(rec.completed_at, "%Y-%m-%d"),
            "Validation": rec.validation_result or "",
            "Notes": rec.notes or "",
        })

    timestamp = local_now().strftime("%Y%m%d_%H%M%S")

    if format == "csv":
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="provisioning_{timestamp}.csv"'},
        )

    # Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Provisioning"
    if rows:
        headers = list(rows[0].keys())
        hfill = PatternFill(start_color="157ca4", end_color="157ca4", fill_type="solid")
        hfont = Font(bold=True, color="FFFFFF")
        for ci, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=ci, value=h)
            cell.fill = hfill
            cell.font = hfont
        for ri, rd in enumerate(rows, 2):
            for ci, h in enumerate(headers, 1):
                ws.cell(row=ri, column=ci, value=rd[h])
        for col in ws.columns:
            ml = max((len(str(c.value or "")) for c in col), default=0)
            ws.column_dimensions[col[0].column_letter].width = min(ml + 2, 50)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="provisioning_{timestamp}.xlsx"'},
    )


# ---------------------------------------------------------------------------
# Bulk assign provisioning records to a customer order
# ---------------------------------------------------------------------------

@router.post("/api/provisioning/bulk-assign-order")
async def bulk_assign_order(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Link or unlink multiple provisioning records to a customer order.

    Body: { "prov_ids": [1, 2, 3], "order_id": 42 }
          { "prov_ids": [1, 2, 3], "order_id": null }  — to unlink
    """
    body = await request.json()
    prov_ids = body.get("prov_ids") or []
    order_id = body.get("order_id")  # None = unlink

    if not prov_ids:
        return JSONResponse(status_code=400, content={"error": "No provisioning IDs provided"})

    # Validate order if linking
    order = None
    if order_id is not None:
        order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        if not order.po_number:
            return JSONResponse(status_code=400, content={"error": f"Order {order.order_number} has no Customer PO - add one before assigning devices"})

    records = (
        db.query(DeviceProvisioning)
        .filter(DeviceProvisioning.id.in_(prov_ids))
        .all()
    )

    updated = 0
    for rec in records:
        rec.customer_order_id = order_id
        detail = (
            f"Bulk linked to order {order.order_number}"
            if order else
            "Bulk unlinked from order"
        )
        log_event(db, "provisioning_order_linked", request=request, user_id=user.id,
                  target_table="device_provisioning", target_id=rec.id,
                  action="update", details=detail)
        updated += 1

    db.commit()

    return JSONResponse(content={
        "updated": updated,
        "order_number": order.order_number if order else None,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_unit(db: Session, row: DeviceProvisioning):
    """The item a provisioning row links, or None."""
    if row.item_id is None:
        return None
    return db.query(Item).filter(Item.id == row.item_id).first()


def _resolve_device_name(db: Session, row: DeviceProvisioning) -> str:
    """Human-readable name for a provisioning row.

    SIBLING of _resolve_unit_serial in fulfillment.py: same item_id link,
    DELIBERATELY different accessor. This one feeds provisioning lists and
    notification prose, which want a name. That one feeds the deployment picker,
    which wants a serial. Do not unify them. A merge would have to pick one
    accessor and would silently put serials into "X fully provisioned by Y"
    messages, with nothing failing.

    item_name over serial. Item 30 S4 retired the legacy per-table path.
    """
    item = _resolve_unit(db, row)
    if item is None:
        return f"Provisioning #{row.id}"
    return item.item_name or item.item_sn or f"Item #{item.id}"


def _unit_deployment_type(item) -> str:
    """The deployment_type attribute of an item, or ''."""
    if item is None:
        return ""
    return (item.attributes or {}).get("deployment_type") or ""


def _resolve_deployment_type(db: Session, row: DeviceProvisioning) -> str:
    """Resolve the deployment_type for a provisioning row's item."""
    return _unit_deployment_type(_resolve_unit(db, row))


def _unit_category_label(item) -> str:
    """Category label for the queue and detail pages."""
    if item is None or not item.item_category:
        return "Unknown"
    return str(item.item_category).replace("_", " ").title()


def _edge_box_view(item):
    """Edge box fields for the detail page and the Zendesk match, read off an
    edge_box item. None for any other unit."""
    if item is None or str(item.item_category or "") != "edge_box":
        return None
    attrs = item.attributes or {}
    return SimpleNamespace(
        serial=item.item_sn,
        part_number=item.brand_sku or item.brand_pn,
        sku_version=attrs.get("sku_version"),
        status=str(item.item_status) if item.item_status else None,
        deployment_type=attrs.get("deployment_type"),
        mac1=item.item_mac_address_1,
        mac2=item.item_mac_address_2,
        uuid=item.appliance_uuid,
    )


def _get_stage_label(stages, stage_name: str) -> str:
    """Get the display label for a stage name."""
    if stages:
        for s in stages:
            if s.get("name") == stage_name:
                return s.get("label", stage_name)
    return stage_name
