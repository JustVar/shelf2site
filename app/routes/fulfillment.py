"""Fulfillment — unified view of customer orders + provisioning pipeline.

Replaces the separate /orders/ and /provisioning/ list pages with a single
Kanban command center showing the full order-to-deployment pipeline.

Detail pages (/orders/{id}, /provisioning/{id}) remain unchanged.
"""

import io
import uuid

import pymupdf as fitz
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_provisioning_manager, require_provisioning_viewer
from ..config import settings
from ..localtime import fmt_local, local_today, register
from ..database import get_db
from ..models import (
    CustomerOrder, DeploymentRecord, DeviceProvisioning,
    Item, OEMPartner, Site, User, BuildCertification,
    BuildCertificationFile, InstallationCertification,
    STAGE_LABELS,
)
from ..order_matching import candidate_items, requirement_lines
from ..order_tracks import (
    COLUMNS, NEXT_STEP, PRE_SHIP, STEP_LABELS, STOCK, TRACKS,
    cert_doc_orders, column_of, flags, mark_units_deployed, track_of, unit_counts,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)

# Full-word stage labels for the WIDE build-cert surfaces (list + detail). The shared
# STAGE_LABELS map stays abbreviated for the narrow Kanban columns; this build-cert-only map is
# preferred by the stage_label filter. Display only - it never mutates the stored stage value.
# hw_check intentionally stays the abbreviated "HW Check" (its permanent form).
_BUILD_STAGE_FULL = {
    "registered": "Registered",
    "certified": "Certified",
    "sw_version": "SW Version",
    "pva_events": "PVA/Events",
}


def _stage_label(value):
    if not value:
        return "-"
    return _BUILD_STAGE_FULL.get(value) or STAGE_LABELS.get(value) or str(value).replace("_", " ").title()


templates.env.filters["stage_label"] = _stage_label

class ShipDetailsUpdate(BaseModel):
    ship_method: Optional[Literal["carrier", "transferred"]] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    shipping_address: Optional[str] = None
    shipped_date: Optional[date] = None
    delivered_date: Optional[date] = None
    recipient_name: Optional[str] = None


class DeploymentCreate(BaseModel):
    customer_order_id: int
    site_id: Optional[int] = None
    address: Optional[str] = None
    scheduled_date: Optional[date] = None
    se_assigned_id: Optional[int] = None
    integrator_name: Optional[str] = None
    integrator_contact: Optional[str] = None
    notes: Optional[str] = None


class DeploymentUnitsAssign(BaseModel):
    provisioning_ids: list[int]


class CertComponent(BaseModel):
    type: str
    model: str
    ok: bool


class CertQASubmit(BaseModel):
    qa_checklist: dict          # 5 keys: hardware, pva_events, searches, netplan, registration -> bool
    components: list            # list of CertComponent-shaped dicts, >= 1
    license_assigned: int
    license_ordered: int


class CertHWSubmit(BaseModel):
    smart_result: str           # "pass" or "fail"


# ---------------------------------------------------------------------------
# Main Fulfillment page
# ---------------------------------------------------------------------------

@router.get("/fulfillment/", response_class=HTMLResponse)
def fulfillment_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """One board, two tracks, one card per order (docs/specs/one-board-two-tracks.md).

    Vendor orders and pilots from stock each get a lane of columns. The
    columns come from app/order_tracks.py; cancelled orders are off the board.
    """
    can_see_sensitive = user.has_sensitive_customers_access
    orders = [
        o for o in db.query(CustomerOrder)
        .filter(CustomerOrder.status != "cancelled")
        .order_by(CustomerOrder.due_date.asc().nullslast(), CustomerOrder.created_at.desc())
        .all()
        if not o.is_sensitive or can_see_sensitive
    ]
    ids = [o.id for o in orders]
    counts = unit_counts(db, ids)
    with_cert = cert_doc_orders(db, ids)
    today = local_today()

    lanes = {track: {key: [] for key, _ in COLUMNS[track]} for track in TRACKS}
    tiles = {"open": 0, "late": 0, "due_back_soon": 0, "docs_missing": 0}
    for o in orders:
        linked, still_out = counts.get(o.id, (0, 0))
        column = column_of(o, linked, still_out)
        if column is None:
            continue
        track = track_of(o)
        f = flags(o, column, still_out, o.id in with_cert, today)
        for k in tiles:
            tiles[k] += 1 if f[k] else 0
        nxt = NEXT_STEP[track].get(column)
        required = sum(int(r.get("qty") or 0) for r in (o.sku_requirements or []))
        lanes[track][column].append({
            "id": o.id,
            "order_number": o.order_number,
            "customer_name": o.customer_name,
            "order_type": o.order_type,
            "type_label": CustomerOrder.ORDER_TYPES.get(o.order_type, o.order_type),
            "partner": (o.oem_partner.name if o.oem_partner else None) if o.owner == "oem" else None,
            "due_date": o.due_date,
            "expected_return": o.expected_return,
            "linked": linked,
            "still_out": still_out,
            "required": required,
            "is_sensitive": o.is_sensitive,
            "flags": f,
            "next": nxt,
            "next_label": STEP_LABELS.get((track, nxt)) if nxt else None,
            "needs_units": track == STOCK and nxt == "shipped" and linked == 0,
        })

    return templates.TemplateResponse(request, "fulfillment.html", {
        "request": request,
        "user": user,
        "lanes": lanes,
        "tracks": TRACKS,
        "columns": COLUMNS,
        "tiles": tiles,
        "today": today,
        "order_types": CustomerOrder.ORDER_TYPES,
        "oem_partners": (db.query(OEMPartner).filter(OEMPartner.active.is_(True))
                         .order_by(OEMPartner.name.asc()).all()),
    })


# ---------------------------------------------------------------------------
# Slide-panel state — fetched fresh on EVERY open
# ---------------------------------------------------------------------------

@router.get("/api/fulfillment/panel/{order_id}")
def fulfillment_panel_state(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Everything the board's Assign/View/Ship panel needs for ONE order.

    The panel previously rendered from whatever state the last order left
    behind (stale ship fields, leftover search text); openPanelFor() calls
    this per open so the panel can never show another order's data.
    """
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Order not found"})
    if order.is_sensitive and not user.has_sensitive_customers_access:
        return JSONResponse(status_code=404, content={"error": "Order not found"})

    reqs = requirement_lines(order)

    site_names = {s.id: s.name for s in db.query(Site).all()}

    # Units already on the order get their identity from item_schema
    # (item 30 S4: the legacy edge-box branch is gone).
    devices = []
    prov_rows = (
        db.query(DeviceProvisioning)
        .filter(DeviceProvisioning.customer_order_id == order.id)
        .order_by(DeviceProvisioning.id)
        .all()
    )
    tech_names = {
        u.id: u.display_name
        for u in db.query(User).filter(User.id.in_(
            [p.assigned_to for p in prov_rows if p.assigned_to] or [0])).all()
    }
    for p in prov_rows:
        entry = {
            "prov_id": p.id,
            "serial": None,
            "part_number": None,
            "assigned_to_name": tech_names.get(p.assigned_to),
            "validation_result": p.validation_result,
            "is_complete": p.is_complete,
            "current_stage": p.current_stage,
            "fulfillment_type": p.fulfillment_type,
            "returned_date": p.returned_date.isoformat() if p.returned_date else None,
            "kind": "legacy",
        }
        if p.item_id:
            item = db.query(Item).filter(Item.id == p.item_id).first()
            if item:
                entry.update({
                    "serial": item.item_sn,
                    "part_number": item.item_sku,
                    "kind": "item",
                })
        devices.append(entry)

    # Assignable stock, matched per requirement line (shared matcher — the
    # availability card counts with the same definition).
    candidates, seen = [], set()
    for line in reqs:
        for item in candidate_items(db, line["model"]):
            if item.id in seen:
                continue
            seen.add(item.id)
            candidates.append({
                "item_id": item.id,
                "serial": item.item_sn,
                "name": item.item_name or item.item_model,
                "sku": item.item_sku,
                "status": str(item.item_status) if item.item_status else "—",
                "location": site_names.get(item.location_id),
            })

    return {
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "status": order.status,
            "order_type": order.order_type,
        },
        "requirements": reqs,
        "devices": devices,
        "candidates": candidates,
        "ship": {
            "ship_method": order.ship_method,
            "carrier": order.carrier,
            "tracking_number": order.tracking_number,
            "shipping_address": order.shipping_address,
            "shipped_date": order.shipped_date.isoformat() if order.shipped_date else None,
            "delivered_date": order.delivered_date.isoformat() if order.delivered_date else None,
            "recipient_name": order.recipient_name,
        },
    }


# ---------------------------------------------------------------------------
# Ship details update
# ---------------------------------------------------------------------------

@router.post("/fulfillment/{order_id}/ship")
async def update_ship_details(
    order_id: int,
    payload: ShipDetailsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Save shipping / transfer details for a customer order."""
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order or (order.is_sensitive and not user.has_sensitive_customers_access):
        return JSONResponse(status_code=404, content={"detail": "Order not found"})

    if order.status == "cancelled":
        return JSONResponse(status_code=409, content={"detail": "A cancelled order cannot ship"})

    update_data = payload.dict(exclude_none=True)
    shipped = update_data.get("shipped_date", order.shipped_date)
    delivered = update_data.get("delivered_date", order.delivered_date)
    if shipped and delivered and delivered < shipped:
        return JSONResponse(status_code=400, content={"detail": "Delivered date is before the shipped date"})
    old_values = {k: (str(getattr(order, k)) if getattr(order, k) is not None else None)
                  for k in update_data}
    old_status = order.status
    for field, value in update_data.items():
        setattr(order, field, value)

    # If shipped_date is being set and order is not yet shipped, advance status.
    # Any pre-ship status advances; orders assigned straight from stock skip
    # sourcing and building entirely.
    if payload.shipped_date and order.status in PRE_SHIP:
        order.status = "shipped"

    # Shipping moves the order's still-out units out the door (shared with the
    # advance route, app/order_tracks.py).
    units_deployed = mark_units_deployed(db, order) if payload.shipped_date else 0

    db.commit()
    log_event(
        db, "order_ship_details_updated", request=request, user_id=user.id,
        target_table="customer_orders", target_id=order.id, action="update",
        old_values={**old_values, "status": old_status},
        new_values={**{k: str(v) for k, v in update_data.items()}, "status": order.status,
                    "units_deployed": units_deployed},
        details=f"Updated shipping for {order.order_number}",
    )

    return {
        "ok": True,
        "order_number": order.order_number,
        "status": order.status,
    }


# ---------------------------------------------------------------------------
# Create deployment record
# ---------------------------------------------------------------------------

@router.post("/fulfillment/deployments")
async def create_deployment(
    payload: DeploymentCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Create a new deployment record linked to a customer order."""
    order = db.query(CustomerOrder).filter(
        CustomerOrder.id == payload.customer_order_id
    ).first()
    if not order:
        return JSONResponse(status_code=404, content={"detail": "Customer order not found"})

    # Validate site if provided
    if payload.site_id:
        site = db.query(Site).filter(Site.id == payload.site_id).first()
        if not site:
            return JSONResponse(status_code=404, content={"detail": "Site not found"})

    # Validate SE if provided
    if payload.se_assigned_id:
        se = db.query(User).filter(User.id == payload.se_assigned_id).first()
        if not se:
            return JSONResponse(status_code=404, content={"detail": "Sales engineer not found"})

    dr = DeploymentRecord(
        customer_order_id=payload.customer_order_id,
        site_id=payload.site_id,
        address=payload.address,
        scheduled_date=payload.scheduled_date,
        se_assigned_id=payload.se_assigned_id,
        integrator_name=payload.integrator_name,
        integrator_contact=payload.integrator_contact,
        notes=payload.notes,
        status="scheduled",
        created_by=user.id,
    )
    db.add(dr)
    db.commit()
    db.refresh(dr)
    log_event(
        db, "deployment_created", request=request, user_id=user.id,
        target_table="deployment_records", target_id=dr.id, action="create",
        new_values={"customer_order_id": dr.customer_order_id, "site_id": dr.site_id,
                    "scheduled_date": str(dr.scheduled_date) if dr.scheduled_date else None},
        details=f"Scheduled deployment #{dr.id} for order {dr.customer_order_id}",
    )

    return {
        "ok": True,
        "id": dr.id,
        "status": dr.status,
    }


# ---------------------------------------------------------------------------
# Update deployment status
# ---------------------------------------------------------------------------

@router.post("/fulfillment/deployments/{dep_id}/status")
async def update_deployment_status(
    dep_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Move a deployment record to a new status."""
    dr = db.query(DeploymentRecord).filter(DeploymentRecord.id == dep_id).first()
    if not dr:
        return JSONResponse(status_code=404, content={"detail": "Deployment not found"})

    body = await request.json()
    new_status = (body.get("status") or "").strip()
    valid = [s for s in DeploymentRecord.DEPLOYMENT_STATUSES if s != "cancelled"]
    if new_status not in valid:
        return JSONResponse(status_code=400, content={"detail": f"Invalid status: {new_status}"})

    old_status = dr.status

    # Lock: a certified installation cannot be reverted out of complete
    if old_status == "complete" and new_status != "complete":
        locked = (
            db.query(InstallationCertification)
            .filter(
                InstallationCertification.deployment_record_id == dep_id,
                InstallationCertification.status == "certified",
            )
            .first()
        )
        if locked is not None:
            return JSONResponse(status_code=409, content={
                "detail": "Certified installation cannot be reverted"
            })

    dr.status = new_status

    # Auto-set installed_date when completing
    if new_status == "complete" and not dr.installed_date:
        dr.installed_date = local_today()

    db.commit()
    log_event(
        db, "deployment_status_changed", request=request, user_id=user.id,
        target_table="deployment_records", target_id=dr.id, action="update",
        old_values={"status": old_status}, new_values={"status": new_status},
        details=f"Deployment #{dr.id}: {old_status} to {new_status}",
    )
    return {"ok": True, "id": dr.id, "old_status": old_status, "status": new_status}


# ---------------------------------------------------------------------------
# Assign provisioned units to a deployment record
# ---------------------------------------------------------------------------

@router.post("/fulfillment/deployments/{dep_id}/units")
async def assign_units_to_deployment(
    dep_id: int,
    payload: DeploymentUnitsAssign,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Link provisioned units to the deployment visit that installs them.

    Validation rejects the whole batch rather than silently filtering it, so a
    mis-assignment surfaces instead of vanishing. There is no unassign endpoint,
    by design rather than omission: a unit pulled from an order is cancelled
    with a reason, which DeviceProvisioning cannot express yet. See
    docs/specs/link-units-to-deployments.md.
    """
    dr = db.query(DeploymentRecord).filter(DeploymentRecord.id == dep_id).first()
    if not dr:
        return JSONResponse(status_code=404, content={"detail": "Deployment not found"})

    ids = list(dict.fromkeys(payload.provisioning_ids or []))
    if not ids:
        return JSONResponse(status_code=400, content={"detail": "No provisioning ids supplied"})

    found = {
        row.id: row
        for row in db.query(DeviceProvisioning).filter(DeviceProvisioning.id.in_(ids)).all()
    }

    # Phase 1: validate every id before writing any of them.
    for pid in ids:
        row = found.get(pid)
        if row is None:
            return JSONResponse(status_code=404, content={
                "detail": f"Provisioning {pid} not found",
            })
        if row.customer_order_id != dr.customer_order_id:
            return JSONResponse(status_code=400, content={
                "detail": (
                    f"Provisioning {pid} belongs to order {row.customer_order_id}, "
                    f"but deployment {dep_id} is for order {dr.customer_order_id}"
                ),
            })
        if row.deployment_record_id is not None:
            return JSONResponse(status_code=409, content={
                "detail": (
                    f"Provisioning {pid} is already assigned to deployment "
                    f"{row.deployment_record_id} and cannot be reassigned"
                ),
            })
        # Checked here as well as filtered out of the feed. The feed shapes the
        # modal; this is what a request that did not come from the modal hits.
        if row.returned_date is not None:
            return JSONResponse(status_code=409, content={
                "detail": (
                    f"Provisioning {pid} was returned on {row.returned_date} "
                    f"and cannot be assigned to a deployment"
                ),
            })

    # Phase 2: every id checked out, so assign them.
    for pid in ids:
        found[pid].deployment_record_id = dep_id

    db.commit()
    log_event(
        db, "deployment_units_assigned", request=request, user_id=user.id,
        target_table="deployment_records", target_id=dep_id, action="update",
        new_values={"provisioning_ids": ids},
        details=f"Assigned {len(ids)} unit(s) to deployment #{dep_id}",
    )
    return {
        "ok": True,
        "deployment_record_id": dep_id,
        "assigned": ids,
        "count": len(ids),
    }


# ---------------------------------------------------------------------------
# Assignable units for a deployment record
# ---------------------------------------------------------------------------

def _resolve_unit_serial(db: Session, row: DeviceProvisioning) -> str:
    """Serial for a provisioning row, read off its item.

    SIBLING of _resolve_device_name in provisioning.py: same item_id link,
    DELIBERATELY different accessor. This one feeds the deployment picker, which
    wants a serial. That one feeds provisioning lists and notification prose,
    which want a name. Do not unify them.

    DeviceProvisioning carries no serial column; the item does (item_sn).
    Item 30 S4 retired the legacy per-table path, so a row with no item falls
    back to its provisioning id.
    """
    fallback = f"Provisioning #{row.id}"
    if row.item_id is None:
        return fallback
    item = db.query(Item).filter(Item.id == row.item_id).first()
    if item is None:
        return fallback
    return item.item_sn or fallback


def _unit_stage_label(row: DeviceProvisioning):
    """Stage label for a provisioning row, or None when it has no stage machine.

    Suppressed on an empty stages array, which is the same property the advance
    path keys on when it bails with "Current stage not found". Do NOT key on
    the unit's category instead: that correlation holds in the current rows but
    is asserted nowhere in code, so it would be a second hand maintained
    mapping to drift.

    STAGE_LABELS.get, never a bare subscript. "acquired" is live on most rows
    and is absent from STAGE_LABELS.
    """
    if not row.stages or not row.current_stage:
        return None
    return STAGE_LABELS.get(row.current_stage, row.current_stage)


@router.get("/fulfillment/deployments/{dep_id}/units")
def list_deployment_units(
    dep_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Assignable, already assigned, and returned units for a deployment visit.

    Fetched when the picker opens rather than rendered at page load. A list
    built at load goes stale, and since assignment validates the whole batch
    before writing any of it, one unit taken elsewhere since load would 409 the
    entire request and fail good assignments alongside it.

    Returned units are listed separately rather than dropped. On an order whose
    units have all come back, hiding them yields an empty picker with no
    explanation, which is strictly worse than showing why it is empty.

    Units assigned to a DIFFERENT visit on the same order appear in none of the
    three lists. They are not assignable and they are not on this visit.
    """
    dr = db.query(DeploymentRecord).filter(DeploymentRecord.id == dep_id).first()
    if not dr:
        return JSONResponse(status_code=404, content={"detail": "Deployment not found"})

    rows = (
        db.query(DeviceProvisioning)
        .filter(DeviceProvisioning.customer_order_id == dr.customer_order_id)
        .order_by(DeviceProvisioning.id)
        .all()
    )

    available = []
    assigned = []
    returned = []
    for row in rows:
        entry = {
            "id": row.id,
            "serial": _resolve_unit_serial(db, row),
            "stage": _unit_stage_label(row),
            "returned_date": row.returned_date.isoformat() if row.returned_date else None,
        }
        # Order matters. A row that is both assigned and returned belongs in
        # assigned: it came back after it was placed on a visit, which is the
        # swap case this track defers. Deciding it by whichever filter ran
        # first would make the answer an accident.
        if row.deployment_record_id == dep_id:
            assigned.append(entry)
        elif row.deployment_record_id is not None:
            continue
        elif row.returned_date is not None:
            returned.append(entry)
        else:
            available.append(entry)

    return {
        "deployment_record_id": dep_id,
        "customer_order_id": dr.customer_order_id,
        "available": available,
        "assigned": assigned,
        "returned": returned,
    }


# ---------------------------------------------------------------------------
# Export fulfillment data as Excel
# ---------------------------------------------------------------------------

@router.get("/api/fulfillment/export")
def export_fulfillment(
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Download all orders as an XLSX spreadsheet."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return JSONResponse(status_code=500, content={"detail": "openpyxl not installed"})

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"

    # Header row
    headers = [
        "Order #", "Customer", "Status", "Sales Engineer",
        "Due Date", "Deployment Type", "SKUs", "Prov. Count",
        "Created",
    ]

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="127CA3")
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    # Fetch all orders
    can_see_sensitive = user.has_sensitive_customers_access
    orders = (
        db.query(CustomerOrder)
        .order_by(CustomerOrder.due_date.asc().nullslast(), CustomerOrder.created_at.desc())
        .all()
    )
    if not can_see_sensitive:
        orders = [o for o in orders if not o.is_sensitive]

    # Prov counts
    prov_counts: dict[int, int] = {}
    for p in db.query(DeviceProvisioning.customer_order_id).filter(
        DeviceProvisioning.customer_order_id.isnot(None),
    ).all():
        prov_counts[p.customer_order_id] = prov_counts.get(p.customer_order_id, 0) + 1

    for row_idx, order in enumerate(orders, 2):
        sku_str = ", ".join(
            f"{r.get('qty', '?')}x {r.get('sku', '?')}"
            for r in (order.sku_requirements or [])
        )
        row_data = [
            order.order_number,
            order.customer_name,
            order.status,
            order.sales_engineer,
            order.due_date.isoformat() if order.due_date else "",
            order.deployment_type,
            sku_str,
            prov_counts.get(order.id, 0),
            fmt_local(order.created_at, "%Y-%m-%d"),
        ]
        for col_idx, value in enumerate(row_data, 1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-fit column widths
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"fulfillment_export_{local_today().isoformat()}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Assign technician to a provisioning record
# ---------------------------------------------------------------------------

@router.put("/api/provisioning/{prov_id}/technician")
async def assign_technician(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Assign or change the technician on a provisioning record."""
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})

    body = await request.json()
    technician_name = (body.get("technician_name") or "").strip()

    if technician_name:
        # Look up user by display_name
        tech_user = db.query(User).filter(
            User.display_name == technician_name,
            User.is_active.is_(True),
        ).first()
        if tech_user:
            prov.assigned_to = tech_user.id
        else:
            prov.assigned_to = None
    else:
        prov.assigned_to = None

    db.commit()
    return {
        "ok": True,
        "prov_id": prov.id,
        "assigned_to": prov.assigned_to,
        "technician_name": technician_name or None,
    }


# ---------------------------------------------------------------------------
# Build Certification index (F3/S6a) - read-only
# ---------------------------------------------------------------------------

@router.get("/fulfillment/certifications", response_class=HTMLResponse)
def certifications_index(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Read-only certification index: every edge-box item with an order link,
    organized by date / customer / SKU, decorated with latest cert status.

    build_certification is append-only and may hold multiple rows per device;
    the status shown reflects the latest cert row (max created_at) per device.
    No writes occur here.
    """
    # All edge-box items with an order link, joined to their order
    # (item 30 S4: the legacy edge_boxes join is gone).
    rows = (
        db.query(
            DeviceProvisioning.id.label("prov_id"),
            DeviceProvisioning.current_stage,
            DeviceProvisioning.is_complete,
            Item.item_sn.label("serial"),
            sqlfunc.coalesce(Item.item_sku, Item.item_pn).label("part_number"),
            CustomerOrder.order_number,
            CustomerOrder.customer_name,
            CustomerOrder.due_date,
        )
        .join(Item, DeviceProvisioning.item_id == Item.id)
        .join(CustomerOrder, DeviceProvisioning.customer_order_id == CustomerOrder.id)
        .filter(Item.item_category == "edge_box")
        .all()
    )

    # Latest cert row per device_provisioning_id (append-only -> pick max created_at).
    cert_by_prov: dict[int, str] = {}
    prov_ids = [r.prov_id for r in rows]
    if prov_ids:
        certs = (
            db.query(
                BuildCertification.device_provisioning_id,
                BuildCertification.cert_status,
                BuildCertification.created_at,
            )
            .filter(BuildCertification.device_provisioning_id.in_(prov_ids))
            .order_by(BuildCertification.created_at.asc())
            .all()
        )
        # asc order -> last write per prov_id wins (the latest cert row).
        for c in certs:
            cert_by_prov[c.device_provisioning_id] = c.cert_status

    _STATUS_LABELS = {
        "certified": "Certified",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "pending": "In progress",
    }

    # Group date -> customer -> sku -> [device dicts]
    groups: dict = {}
    for r in rows:
        cert_status = cert_by_prov.get(r.prov_id)
        status_key = cert_status if cert_status else "needs"
        status_label = _STATUS_LABELS.get(cert_status, "Needs cert")
        date_key = r.due_date.isoformat() if r.due_date else "No date"
        cust_key = r.customer_name or "Unknown customer"
        sku_key = r.part_number or "No SKU"
        device = {
            "prov_id": r.prov_id,
            "serial": r.serial or "-",
            "order_number": r.order_number,
            "current_stage": r.current_stage,
            "status_key": status_key,
            "status_label": status_label,
        }
        groups.setdefault(date_key, {}).setdefault(cust_key, {}).setdefault(
            sku_key, []
        ).append(device)

    total_devices = len(rows)

    # Sort: date groups soonest-due first ("No date" last), then customer and
    # SKU alphabetically. dict preserves insertion order, so rebuild in order.
    def _cert_date_sort_key(date_key: str):
        # "No date" sorts last; real ISO dates sort chronologically.
        return (1, "") if date_key == "No date" else (0, date_key)

    sorted_groups: dict = {}
    for date_key in sorted(groups, key=_cert_date_sort_key):
        customers = groups[date_key]
        sorted_customers: dict = {}
        for cust_key in sorted(customers):
            skus = customers[cust_key]
            sorted_customers[cust_key] = {
                sku_key: skus[sku_key] for sku_key in sorted(skus)
            }
        sorted_groups[date_key] = sorted_customers

    return templates.TemplateResponse(request, "certifications.html", {
        "request": request,
        "user": user,
        "groups": sorted_groups,
        "total_devices": total_devices,
    })


# ---------------------------------------------------------------------------
# Build Certification - shared constants (QA keys, component vocab)
# ---------------------------------------------------------------------------

_QA_KEYS = {'hardware', 'pva_events', 'searches', 'netplan', 'registration'}
_COMP_TYPES = {'cpu', 'gpu', 'ram', 'hdd', 'ssd'}


# ---------------------------------------------------------------------------
# Build Certification - shared half-apply + all-pass gate (F3/S6c)
# ---------------------------------------------------------------------------

def _cert_edge_box(db, prov):
    """The edge box fields a build certification reads (serial, uuid,
    part_number), off the provisioning row's item. None unless the row links
    an edge_box item. Item 30 S4: certification no longer reads edge_boxes."""
    if prov is None or prov.item_id is None:
        return None
    item = db.query(Item).filter(Item.id == prov.item_id).first()
    if item is None or str(item.item_category or "") != "edge_box":
        return None
    return SimpleNamespace(
        id=item.id,
        serial=item.item_sn,
        uuid=item.platform_uuid,
        part_number=item.item_sku or item.item_pn,
    )


def _compute_cert_gate(cert):
    """All-pass gate: returns 'certified' or 'failed' (both halves complete).

    certified iff every QA check true AND every component ok AND smart pass.
    """
    qa = cert.qa_checklist or {}
    qa_all = all(bool((qa.get(k) or {}).get("checked")) for k in _QA_KEYS)
    hv = cert.hardware_validation or {}
    comps = hv.get("components") or []
    comps_ok = bool(comps) and all(bool(c.get("ok")) for c in comps)
    smart = (hv.get("smart_test") or {}).get("result")
    smart_ok = smart == "pass"
    return "certified" if (qa_all and comps_ok and smart_ok) else "failed"


def _open_attempt(db, serial):
    """Latest cert row for serial that is still pending (the open attempt).

    Independence model: a half attaches to this row regardless of which
    half is already on it. Returns None if no row or the latest is terminal.
    """
    latest = (
        db.query(BuildCertification)
        .filter(BuildCertification.oem_serial == serial)
        .order_by(BuildCertification.created_at.desc())
        .first()
    )
    if latest is not None and latest.cert_status == "pending":
        return latest
    return None


def _apply_cert_half(db, prov, eb, co, half, fields, signer):
    """Create-or-update the open attempt with one half, then maybe gate.

    half: 'qa' or 'hw'. fields: the validated payload data for that half.
    Returns (cert_row, error_response_or_None). On per-half duplicate -> 409.
    JSONB writes use whole-dict reassignment (no in-place mutation).
    """
    now = datetime.utcnow()
    cert = _open_attempt(db, eb.serial)

    if cert is None:
        # whichever half goes first creates the row
        cert = BuildCertification(
            device_provisioning_id=prov.id,
            oem_serial=eb.serial,
            device_uuid=eb.uuid,
            sku=eb.part_number,
            customer_name=(co.customer_name if co else None),
            order_number=(co.order_number if co else None),
            qa_status="pending",
            hw_status="pending",
            cert_status="pending",
            reason="initial",
        )
        db.add(cert)

    # per-half 409: do not submit the same half twice on the open attempt
    if half == "qa" and cert.qa_status == "complete":
        return None, JSONResponse(status_code=409, content={
            "detail": "QA already submitted for this attempt"
        })
    if half == "hw" and cert.hw_status == "complete":
        return None, JSONResponse(status_code=409, content={
            "detail": "Hardware already submitted for this attempt"
        })

    if half == "qa":
        cert.qa_checklist = {k: {"checked": bool(v)} for k, v in fields["qa_checklist"].items()}
        # preserve any existing smart_test; (re)set components
        hv = dict(cert.hardware_validation or {})
        hv["components"] = fields["components"]
        cert.hardware_validation = hv
        cert.license_counts = {"assigned": fields["license_assigned"], "ordered": fields["license_ordered"]}
        cert.certified_by = signer
        cert.qa_status = "complete"
    else:  # hw
        hv = dict(cert.hardware_validation or {})
        hv["smart_test"] = {"result": fields["smart_result"], "by": signer, "at": now.isoformat()}
        cert.hardware_validation = hv  # reassign -> tracked
        cert.co_certified_by = signer
        cert.co_certified_at = now
        cert.hw_status = "complete"

    # gate: if both halves now complete, compute terminal cert_status
    if cert.qa_status == "complete" and cert.hw_status == "complete":
        cert.cert_status = _compute_cert_gate(cert)
        # certified_at means finalize/certification time (C2C-mimic), set only when the
        # attempt actually certifies; a 'failed' attempt carries no certification timestamp.
        cert.certified_at = now if cert.cert_status == "certified" else None

    db.commit()
    db.refresh(cert)

    # persist the composite report PDF for a finalized+certified attempt (B4). AFTER commit so a
    # render failure cannot roll back the sign-off; wrapped so a composite failure never 500s the
    # sign-off - the attempt stays certified and the composite is regenerable.
    if cert.cert_status == "certified":
        try:
            _generate_build_composite(db, cert, eb)
        except Exception:
            db.rollback()
    return cert, None


# ---------------------------------------------------------------------------
# Build Certification - QA half (F3/S6b, revised S6c for independence)
# ---------------------------------------------------------------------------

@router.post("/fulfillment/certifications/{prov_id}/qa")
async def submit_cert_qa(
    prov_id: int,
    payload: CertQASubmit,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Apply the QA half to the open cert attempt (create-or-update).

    Independence: either half may go first. The gate computes terminal
    cert_status once both halves are complete (S6c).
    """
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})
    eb = _cert_edge_box(db, prov)
    if eb is None:
        return JSONResponse(status_code=400, content={"detail": "Certification is edge-box only"})

    co = None
    if prov.customer_order_id:
        co = db.query(CustomerOrder).filter(CustomerOrder.id == prov.customer_order_id).first()

    # --- validation ---
    if set(payload.qa_checklist.keys()) != _QA_KEYS:
        return JSONResponse(status_code=400, content={
            "detail": "qa_checklist must contain exactly: " + ", ".join(sorted(_QA_KEYS))
        })
    if not all(isinstance(v, bool) for v in payload.qa_checklist.values()):
        return JSONResponse(status_code=400, content={"detail": "qa_checklist values must be true/false"})
    if not payload.components:
        return JSONResponse(status_code=400, content={"detail": "At least one component is required"})
    norm_components = []
    for c in payload.components:
        ctype = (c.get("type") or "").strip().lower()
        cmodel = (c.get("model") or "").strip()
        cok = bool(c.get("ok"))
        if ctype not in _COMP_TYPES:
            return JSONResponse(status_code=400, content={
                "detail": f"Invalid component type '{ctype}'; allowed: " + ", ".join(sorted(_COMP_TYPES))
            })
        if not cmodel:
            return JSONResponse(status_code=400, content={"detail": "Component model cannot be empty"})
        norm_components.append({"type": ctype, "model": cmodel, "ok": cok})
    if payload.license_assigned < 0 or payload.license_ordered < 0:
        return JSONResponse(status_code=400, content={"detail": "License counts must be >= 0"})

    cert, err = _apply_cert_half(
        db, prov, eb, co, "qa",
        {
            "qa_checklist": payload.qa_checklist,
            "components": norm_components,
            "license_assigned": payload.license_assigned,
            "license_ordered": payload.license_ordered,
        },
        user.display_name,
    )
    if err:
        return err
    return {
        "ok": True,
        "cert_id": cert.id,
        "qa_status": cert.qa_status,
        "hw_status": cert.hw_status,
        "cert_status": cert.cert_status,
    }

# ---------------------------------------------------------------------------
# Build Certification - per-device detail view (F3/S6b), read
# ---------------------------------------------------------------------------

@router.get("/fulfillment/certifications/{prov_id}", response_class=HTMLResponse)
def certification_detail(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Per-device cert detail: device context, QA capture form, and the
    box's lifetime cert history (by serial). Route key is prov_id (the FK);
    history is shown by oem_serial (display lens, append-only trail).
    """
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    eb = _cert_edge_box(db, prov)
    if eb is None:
        return RedirectResponse(url=f"{BP}/fulfillment/certifications", status_code=302)

    co = None
    if prov.customer_order_id:
        co = db.query(CustomerOrder).filter(CustomerOrder.id == prov.customer_order_id).first()

    device = {
        "prov_id": prov.id,
        "serial": eb.serial or "-",
        "uuid": eb.uuid or "-",
        "sku": eb.part_number or "-",
        "customer_name": (co.customer_name if co else "-"),
        "order_number": (co.order_number if co else "-"),
        "due_date": (co.due_date.isoformat() if co and co.due_date else "-"),
        "current_stage": prov.current_stage,
    }

    # Lifetime history for this box, by serial (display lens; newest first).
    history_rows = []
    if eb.serial:
        history_rows = (
            db.query(BuildCertification)
            .filter(BuildCertification.oem_serial == eb.serial)
            .order_by(BuildCertification.created_at.desc())
            .all()
        )
    history = [{
        "id": h.id,
        "reason": h.reason,
        "qa_status": h.qa_status,
        "hw_status": h.hw_status,
        "cert_status": h.cert_status,
        "certified_by": h.certified_by or "-",
        "certified_at": (fmt_local(h.certified_at, "%Y-%m-%d %H:%M %Z") if h.certified_at else "-"),
        "co_certified_by": h.co_certified_by or "-",
        "co_certified_at": (h.co_certified_at.isoformat(sep=" ", timespec="minutes") if h.co_certified_at else "-"),
    } for h in history_rows]

    # Per-half open-attempt state (lockstep with the POST routes via _open_attempt).
    open_cert = _open_attempt(db, eb.serial)
    qa_done = bool(open_cert and open_cert.qa_status == "complete")
    hw_done = bool(open_cert and open_cert.hw_status == "complete")
    # No open attempt + a terminal latest row -> a finished device (gate re-cert behind a button).
    latest_terminal = bool(
        open_cert is None and history_rows and history_rows[0].cert_status in ("certified", "failed", "cancelled")
    )
    latest_cert_status = history_rows[0].cert_status if history_rows else None
    # Signers for the open attempt panels (done-by-X states).
    qa_signer = (open_cert.certified_by if (open_cert and open_cert.qa_status == "complete") else None)
    hw_signer = (open_cert.co_certified_by if (open_cert and open_cert.hw_status == "complete") else None)

    # Files for the CURRENT attempt only (per-attempt lens; B3). Source uploads only; a
    # persisted composite (B4, kind='composite') is surfaced separately, not in this list.
    cert_files = []
    current_cert = history_rows[0] if history_rows else None
    if current_cert is not None:
        for f in (db.query(BuildCertificationFile)
                  .filter(BuildCertificationFile.build_certification_id == current_cert.id)
                  .filter(BuildCertificationFile.kind == "source")
                  .order_by(BuildCertificationFile.uploaded_at.desc()).all()):
            cert_files.append({
                "id": f.id,
                "original_name": f.original_name,
                "size_kb": round((f.size_bytes or 0) / 1024, 1),
                "uploaded_by": f.uploaded_by or "-",
                "uploaded_at": (fmt_local(f.uploaded_at, "%Y-%m-%d %H:%M %Z") if f.uploaded_at else "-"),
            })
    has_cert = bool(history_rows)

    # The 5 QA checks, in display order, with labels (labels live in code).
    qa_checks = [
        ("hardware", "Hardware"),
        ("pva_events", "PVA events"),
        ("searches", "Searches"),
        ("netplan", "Netplan"),
        ("registration", "Registration"),
    ]
    comp_types = ["cpu", "ram", "gpu", "hdd", "ssd"]

    return templates.TemplateResponse(request, "certification_detail.html", {
        "request": request,
        "user": user,
        "device": device,
        "history": history,
        "qa_done": qa_done,
        "hw_done": hw_done,
        "latest_terminal": latest_terminal,
        "latest_cert_status": latest_cert_status,
        "qa_signer": qa_signer,
        "hw_signer": hw_signer,
        "qa_checks": qa_checks,
        "comp_types": comp_types,
        "qa_prefill": {
            "checklist": (open_cert.qa_checklist if open_cert else None) or {},
            "comp_by_type": {
                (c.get("type") or ""): c
                for c in (((open_cert.hardware_validation or {}).get("components")) if open_cert else None) or []
            },
            "license": (open_cert.license_counts if open_cert else None) or {},
        },
        "cert_files": cert_files,
        "has_cert": has_cert,
        "is_complete": bool(prov.is_complete),
        "completed_at": (fmt_local(prov.completed_at, "%Y-%m-%d %H:%M %Z") if prov.completed_at else None),
    })


# ---------------------------------------------------------------------------
# Build Certification - Hardware/SMART half + gate (F3/S6c)
# ---------------------------------------------------------------------------

@router.post("/fulfillment/certifications/{prov_id}/hw")
async def submit_cert_hw(
    prov_id: int,
    payload: CertHWSubmit,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Apply the Hardware/SMART half to the open cert attempt (create-or-update).

    Independence: may go before or after QA. When both halves are complete
    the all-pass gate computes terminal cert_status.
    """
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})
    eb = _cert_edge_box(db, prov)
    if eb is None:
        return JSONResponse(status_code=400, content={"detail": "Certification is edge-box only"})

    co = None
    if prov.customer_order_id:
        co = db.query(CustomerOrder).filter(CustomerOrder.id == prov.customer_order_id).first()

    # --- validation ---
    smart = (payload.smart_result or "").strip().lower()
    if smart not in ("pass", "fail"):
        return JSONResponse(status_code=400, content={"detail": "smart_result must be 'pass' or 'fail'"})

    cert, err = _apply_cert_half(
        db, prov, eb, co, "hw",
        {"smart_result": smart},
        user.display_name,
    )
    if err:
        return err
    return {
        "ok": True,
        "cert_id": cert.id,
        "qa_status": cert.qa_status,
        "hw_status": cert.hw_status,
        "cert_status": cert.cert_status,
    }


# ---------------------------------------------------------------------------
# Build Certification - report file uploads (F3/S6d)
# ---------------------------------------------------------------------------

_CERT_FILE_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}
_CERT_FILE_EXTS = {".pdf", ".png", ".jpg", ".jpeg"}
_CERT_FILE_MAX = 5 * 1024 * 1024  # 5 MB


@router.post("/fulfillment/certifications/{prov_id}/files")
async def upload_cert_file(
    prov_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Attach a report file to the latest cert attempt for this device's serial.

    Requires an existing cert row (400 if none). Files anchor to both the
    cert row (CASCADE) and the serial (lifetime). Stored under CERT_UPLOAD_DIR
    with a uuid name; dual type-check (content-type + extension); 5 MB cap.
    """
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})
    eb = _cert_edge_box(db, prov)
    if eb is None:
        return JSONResponse(status_code=404, content={"detail": "Edge box not found"})

    # latest cert row for this serial (the attempt files attach to)
    cert = (
        db.query(BuildCertification)
        .filter(BuildCertification.oem_serial == eb.serial)
        .order_by(BuildCertification.created_at.desc())
        .first()
    )
    if cert is None:
        return JSONResponse(status_code=400, content={
            "detail": "Start a certification for this device before uploading files"
        })

    # validate type: content-type AND extension must both be allowed
    ctype = (file.content_type or "").lower()
    ext = Path(file.filename or "").suffix.lower()
    if ctype not in _CERT_FILE_TYPES or ext not in _CERT_FILE_EXTS:
        return JSONResponse(status_code=400, content={
            "detail": "Allowed file types: PDF, PNG, JPG"
        })

    # read with size cap
    content = await file.read()
    if len(content) > _CERT_FILE_MAX:
        return JSONResponse(status_code=413, content={"detail": "File exceeds 5 MB limit"})
    if len(content) == 0:
        return JSONResponse(status_code=400, content={"detail": "Empty file"})

    # save under CERT_UPLOAD_DIR/<serial>/<uuid><ext>
    safe_ext = _CERT_FILE_TYPES[ctype]  # canonical ext from content-type
    serial_dir = Path(settings.CERT_UPLOAD_DIR) / (eb.serial or "unknown")
    serial_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{safe_ext}"
    stored_path = serial_dir / stored_name
    with open(stored_path, "wb") as fh:
        fh.write(content)

    rec = BuildCertificationFile(
        build_certification_id=cert.id,
        oem_serial=eb.serial,
        original_name=(file.filename or stored_name),
        stored_name=stored_name,
        content_type=ctype,
        size_bytes=len(content),
        uploaded_by=user.display_name,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    return {"ok": True, "file_id": rec.id, "original_name": rec.original_name}


@router.get("/fulfillment/certifications/files/{file_id}")
def download_cert_file(
    file_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Serve a cert report file by id (viewer-gated)."""
    rec = db.query(BuildCertificationFile).filter(BuildCertificationFile.id == file_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "File not found"})
    path = Path(settings.CERT_UPLOAD_DIR) / (rec.oem_serial or "unknown") / rec.stored_name
    if not path.exists():
        return JSONResponse(status_code=404, content={"detail": "File missing on disk"})
    return FileResponse(
        path=str(path),
        filename=rec.original_name,
        media_type=rec.content_type or "application/octet-stream",
        content_disposition_type="inline",
    )


# ---------------------------------------------------------------------------
# Installation Certification (I2): atomic Complete & Certify + inline PDF serve
# ---------------------------------------------------------------------------

_INSTALL_PDF_MAX = 20 * 1024 * 1024  # 20 MB (post-install PDFs embed photos)


@router.post("/fulfillment/deployments/{dep_id}/install/certify")
async def certify_installation(
    dep_id: int,
    request: Request,
    file: UploadFile = File(...),
    installer_name: str = Form(""),
    installer_company: str = Form(""),
    notes: str = Form(""),
    completion_date: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Atomic Complete & Certify for a deployment installation.

    One request: stores the required post-install PDF, creates the
    installation_certification row (or reuses an existing pending one), records
    installer + notes, marks it certified, and flips the deployment record to
    complete. PDF only, 20 MB cap. Nothing commits unless all steps succeed.
    """
    dr = db.query(DeploymentRecord).filter(DeploymentRecord.id == dep_id).first()
    if not dr:
        return JSONResponse(status_code=404, content={"detail": "Deployment not found"})

    existing = (
        db.query(InstallationCertification)
        .filter(InstallationCertification.deployment_record_id == dep_id)
        .first()
    )
    if existing and existing.status == "certified":
        return JSONResponse(status_code=400, content={
            "detail": "This deployment is already certified"
        })

    # validate type: PDF only, content-type AND extension
    ctype = (file.content_type or "").lower()
    ext = Path(file.filename or "").suffix.lower()
    if ctype != "application/pdf" or ext != ".pdf":
        return JSONResponse(status_code=400, content={"detail": "A PDF is required"})

    content = await file.read()
    if len(content) > _INSTALL_PDF_MAX:
        return JSONResponse(status_code=413, content={"detail": "PDF exceeds 20 MB limit"})
    if len(content) == 0:
        return JSONResponse(status_code=400, content={"detail": "Empty file"})

    # parse optional completion date
    comp_date = None
    if completion_date.strip():
        try:
            comp_date = date.fromisoformat(completion_date.strip())
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid completion date"})

    # store PDF under INSTALL_CERT_UPLOAD_DIR/<dep_id>/<uuid>.pdf
    dep_dir = Path(settings.INSTALL_CERT_UPLOAD_DIR) / str(dep_id)
    dep_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    with open(dep_dir / stored_name, "wb") as fh:
        fh.write(content)

    cert = existing or InstallationCertification(deployment_record_id=dep_id)
    cert.installer_name = installer_name.strip() or None
    cert.installer_company = installer_company.strip() or None
    cert.notes = notes.strip() or None
    cert.completion_date = comp_date
    cert.pdf_original_name = file.filename or "post-install.pdf"
    cert.pdf_stored_name = stored_name
    cert.pdf_content_type = "application/pdf"
    cert.pdf_size_bytes = len(content)
    cert.status = "certified"
    cert.certified_by = user.display_name
    cert.certified_at = datetime.utcnow()
    if not cert.created_by:
        cert.created_by = user.display_name
    if cert.id is None:
        db.add(cert)

    dr.status = "complete"
    if not dr.installed_date:
        dr.installed_date = local_today()

    db.commit()
    log_event(
        db, "installation_certified", request=request, user_id=user.id,
        target_table="deployment_records", target_id=dep_id, action="update",
        new_values={"cert_id": cert.id, "installer_name": cert.installer_name,
                    "installer_company": cert.installer_company},
        details=f"Certified installation for deployment #{dep_id} ({cert.pdf_original_name})",
    )
    return {"ok": True, "deployment_id": dep_id, "cert_id": cert.id, "status": "certified"}


@router.get("/fulfillment/install-cert/{cert_id}/pdf")
def serve_install_pdf(
    cert_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Serve the post-install PDF inline (viewer-gated)."""
    rec = db.query(InstallationCertification).filter(
        InstallationCertification.id == cert_id
    ).first()
    if not rec or not rec.pdf_stored_name:
        return JSONResponse(status_code=404, content={"detail": "PDF not found"})
    path = Path(settings.INSTALL_CERT_UPLOAD_DIR) / str(rec.deployment_record_id) / rec.pdf_stored_name
    if not path.exists():
        return JSONResponse(status_code=404, content={"detail": "PDF missing on disk"})
    return FileResponse(
        path=str(path),
        filename=rec.pdf_original_name or "post-install.pdf",
        media_type="application/pdf",
        content_disposition_type="inline",
    )


# ---------------------------------------------------------------------------
# Build Certification - composite report PDF (F3/S6e)
# ---------------------------------------------------------------------------

_QA_LABELS = {
    "hardware": "Hardware",
    "pva_events": "PVA events",
    "searches": "Searches",
    "netplan": "Netplan",
    "registration": "Registration",
}


def _build_cert_report_pdf(db, cert, eb):
    """Build a self-contained composite cert report PDF (bytes).

    Page 1+: structured summary from the cert row. Then this attempt's
    uploaded files appended (PDF pages inserted; images rendered onto a
    page). Each file embed is isolated: a failure becomes a placeholder
    page, never breaks the report. Summary always generates.
    """
    doc = fitz.open()
    page = doc.new_page()
    margin = 56
    y = margin

    def line(text, size=11, dy=18, bold=False, color=(0, 0, 0)):
        nonlocal y, page
        if y > page.rect.height - margin:
            page = doc.new_page()
            y = margin
        font = "hebo" if bold else "helv"
        page.insert_text((margin, y), text, fontsize=size, fontname=font, color=color)
        y += dy

    def gap(dy=10):
        nonlocal y
        y += dy

    # header
    status = (cert.cert_status or "pending").upper()
    line("Build Certification Report", size=18, dy=28, bold=True)
    line(f"Serial: {eb.serial or '-'}    Status: {status}", size=12, dy=22, bold=True)
    gap()

    # device
    line("Device", size=13, dy=20, bold=True)
    line(f"Serial: {eb.serial or '-'}")
    line(f"UUID: {eb.uuid or '-'}")
    line(f"SKU: {eb.part_number or '-'}")
    line(f"Customer: {cert.customer_name or '-'}")
    line(f"Order: {cert.order_number or '-'}")
    gap()

    # QA half
    line("QA Sign-off", size=13, dy=20, bold=True)
    qa = cert.qa_checklist or {}
    for k in ["hardware", "pva_events", "searches", "netplan", "registration"]:
        checked = bool((qa.get(k) or {}).get("checked"))
        mark = "[x]" if checked else "[ ]"
        line(f"  {mark} {_QA_LABELS.get(k, k)}")
    line(f"QA status: {cert.qa_status or '-'}  by {cert.certified_by or '-'}"
         f"  {fmt_local(cert.certified_at, '%Y-%m-%d %H:%M %Z') or '-'}")
    gap()

    # hardware half
    line("Hardware Sign-off", size=13, dy=20, bold=True)
    hv = cert.hardware_validation or {}
    smart = (hv.get("smart_test") or {})
    line(f"SMART result: {smart.get('result', '-')}")
    line(f"HW status: {cert.hw_status or '-'}  by {cert.co_certified_by or '-'}"
         f"  {fmt_local(cert.co_certified_at, '%Y-%m-%d %H:%M %Z') or '-'}")
    gap()

    # components
    line("Components", size=13, dy=20, bold=True)
    comps = hv.get("components") or []
    if comps:
        for c in comps:
            ok = "OK" if c.get("ok") else "NOT OK"
            line(f"  {c.get('type', '?').upper()}: {c.get('model', '-')}  [{ok}]")
    else:
        line("  (none recorded)")
    gap()

    # licenses
    lc = cert.license_counts or {}
    line("Licenses", size=13, dy=20, bold=True)
    line(f"  Assigned: {lc.get('assigned', '-')}    Ordered: {lc.get('ordered', '-')}")
    gap()

    line(f"Reason: {cert.reason or '-'}    Generated from cert id {cert.id}", size=9, dy=14)

    # --- append this attempt's files (per-file isolation) ---
    files = (
        db.query(BuildCertificationFile)
        .filter(BuildCertificationFile.build_certification_id == cert.id)
        .filter(BuildCertificationFile.kind == "source")
        .order_by(BuildCertificationFile.uploaded_at.asc())
        .all()
    )
    for f in files:
        fpath = Path(settings.CERT_UPLOAD_DIR) / (f.oem_serial or "unknown") / f.stored_name
        try:
            ctype = (f.content_type or "").lower()
            if "pdf" in ctype and fpath.exists():
                src = fitz.open(str(fpath))
                doc.insert_pdf(src)
                src.close()
            elif ("png" in ctype or "jpeg" in ctype or "jpg" in ctype) and fpath.exists():
                ipage = doc.new_page()
                rect = ipage.rect + (margin, margin, -margin, -margin)
                ipage.insert_image(rect, filename=str(fpath), keep_proportion=True)
            else:
                raise FileNotFoundError("missing or unsupported")
        except Exception:
            ph = doc.new_page()
            ph.insert_text((margin, margin + 20),
                           f"Could not embed file: {f.original_name}",
                           fontsize=12, fontname="hebo", color=(0.8, 0, 0))

    out = doc.tobytes()
    doc.close()
    return out


def _generate_build_composite(db, cert, eb):
    """Build + persist the composite report PDF for a finalized attempt as a kind='composite'
    BuildCertificationFile (bytes on disk under CERT_UPLOAD_DIR). Idempotent: drops any prior
    composite for this attempt first. Includes a live-render self-check so a bad font token or
    render error raises HERE, not at py_compile."""
    for old in (db.query(BuildCertificationFile)
                .filter(BuildCertificationFile.build_certification_id == cert.id,
                        BuildCertificationFile.kind == "composite").all()):
        try:
            (Path(settings.CERT_UPLOAD_DIR) / (old.oem_serial or "unknown") / old.stored_name).unlink(missing_ok=True)
        except Exception:
            pass
        db.delete(old)
    pdf_bytes = _build_cert_report_pdf(db, cert, eb)
    # live-render self-check: re-open the bytes and touch every page
    check = fitz.open(stream=pdf_bytes, filetype="pdf")
    if check.page_count < 1:
        check.close()
        raise ValueError("composite has no pages")
    for p in check:
        p.get_text()
    check.close()
    serial = (eb.serial if eb else None) or cert.oem_serial or "unknown"
    serial_dir = Path(settings.CERT_UPLOAD_DIR) / serial
    serial_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    with open(serial_dir / stored_name, "wb") as fh:
        fh.write(pdf_bytes)
    db.add(BuildCertificationFile(
        build_certification_id=cert.id,
        oem_serial=serial,
        kind="composite",
        original_name=f"cert_composite_{serial}_{cert.id}.pdf",
        stored_name=stored_name,
        content_type="application/pdf",
        size_bytes=len(pdf_bytes),
        uploaded_by=cert.certified_by or "system",
    ))
    db.commit()


@router.get("/fulfillment/certifications/{cert_id}/report")
def cert_report(
    cert_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Generate + serve a composite cert report PDF for one cert attempt."""
    cert = db.query(BuildCertification).filter(BuildCertification.id == cert_id).first()
    if not cert:
        return JSONResponse(status_code=404, content={"detail": "Certification not found"})
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == cert.device_provisioning_id).first()
    eb = _cert_edge_box(db, prov)
    if eb is None:
        # fall back to a minimal eb-less render using the cert snapshot
        class _EB:
            serial = cert.oem_serial
            uuid = cert.device_uuid
            part_number = cert.sku
        eb = _EB()

    pdf_bytes = _build_cert_report_pdf(db, cert, eb)
    fname = f"cert_{(cert.oem_serial or 'device')}_{cert.id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )



# ---------------------------------------------------------------------------
# Build Certification - board close (F3/S6f)
# ---------------------------------------------------------------------------

@router.post("/fulfillment/certifications/{prov_id}/close")
async def close_cert_device(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Close a certified device: set is_complete + completed_at.

    Gated to certified-only (the latest cert row for the serial must be
    cert_status == certified). The device then drops off the Building
    board via the existing is_complete filter. Idempotent: re-closing an
    already-complete device is a no-op.
    """
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})
    eb = _cert_edge_box(db, prov)
    if eb is None:
        return JSONResponse(status_code=400, content={"detail": "Certification is edge-box only"})

    # idempotent: already closed -> no-op success
    if prov.is_complete:
        return {"ok": True, "prov_id": prov.id, "already_complete": True,
                "completed_at": (prov.completed_at.isoformat() if prov.completed_at else None)}

    # gate: the latest cert row for this serial must be certified
    latest = (
        db.query(BuildCertification)
        .filter(BuildCertification.oem_serial == eb.serial)
        .order_by(BuildCertification.created_at.desc())
        .first()
    )
    if latest is None or latest.cert_status != "certified":
        return JSONResponse(status_code=409, content={
            "detail": "Device must be certified before it can be closed"
        })

    prov.is_complete = True
    prov.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(prov)

    return {"ok": True, "prov_id": prov.id,
            "completed_at": (prov.completed_at.isoformat() if prov.completed_at else None)}


@router.post("/fulfillment/certifications/{prov_id}/cancel")
async def cancel_cert_device(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Cancel a certified build: append a NEW cancelled attempt (reason + who + when).

    Append-only: the prior certified attempt stays frozen (never mutated). cert_status is a
    free varchar, so 'cancelled' needs no schema change. The close-gate (latest must be
    certified) then blocks re-closing until a re-certification opens a fresh attempt.
    """
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})
    eb = _cert_edge_box(db, prov)
    if eb is None:
        return JSONResponse(status_code=400, content={"detail": "Certification is edge-box only"})

    body = await request.json()
    reason = (body.get("reason") or "").strip()
    if not reason:
        return JSONResponse(status_code=400, content={"detail": "A cancellation reason is required"})

    # gate: only a currently-certified build (latest attempt certified) can be cancelled
    latest = (
        db.query(BuildCertification)
        .filter(BuildCertification.oem_serial == eb.serial)
        .order_by(BuildCertification.created_at.desc())
        .first()
    )
    if latest is None or latest.cert_status != "certified":
        return JSONResponse(status_code=409, content={
            "detail": "Only a currently-certified build can be cancelled"
        })

    # append a NEW cancelled attempt; the prior certified attempt stays frozen
    event = BuildCertification(
        device_provisioning_id=prov.id,
        oem_serial=eb.serial,
        device_uuid=latest.device_uuid,
        sku=latest.sku,
        customer_name=latest.customer_name,
        order_number=latest.order_number,
        qa_status=latest.qa_status,
        hw_status=latest.hw_status,
        cert_status="cancelled",
        reason=latest.reason or "initial",
        cancel_reason=reason,
        cancelled_by=user.display_name,
        cancelled_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return {"ok": True, "cert_id": event.id, "cert_status": "cancelled"}


@router.post("/fulfillment/certifications/{prov_id}/recertify")
async def recertify_device(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Start a re-certification: append a fresh PENDING attempt that inherits the prior completed
    attempt's checklist/evidence and copy-forwards its source files under new stored_names, with
    reason='recert'. Applies after a failed or cancelled latest attempt. The QA/HW forms then let
    the user re-submit (which overwrites the inherited checklist); files carry forward visibly."""
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})
    eb = _cert_edge_box(db, prov)
    if eb is None:
        return JSONResponse(status_code=400, content={"detail": "Certification is edge-box only"})

    latest = (
        db.query(BuildCertification)
        .filter(BuildCertification.oem_serial == eb.serial)
        .order_by(BuildCertification.created_at.desc())
        .first()
    )
    if latest is None or latest.cert_status not in ("failed", "cancelled"):
        return JSONResponse(status_code=409, content={
            "detail": "Re-certification applies after a failed or cancelled attempt"
        })

    # inherit from the most recent COMPLETED attempt (has checklist/evidence); skips a cancel marker
    source = (
        db.query(BuildCertification)
        .filter(BuildCertification.oem_serial == eb.serial)
        .filter(BuildCertification.cert_status.in_(("certified", "failed")))
        .order_by(BuildCertification.created_at.desc())
        .first()
    )

    new_cert = BuildCertification(
        device_provisioning_id=prov.id,
        oem_serial=eb.serial,
        device_uuid=(source.device_uuid if source else eb.uuid),
        sku=(source.sku if source else eb.part_number),
        customer_name=(source.customer_name if source else None),
        order_number=(source.order_number if source else None),
        qa_checklist=(source.qa_checklist if source else None),
        hardware_validation=(source.hardware_validation if source else None),
        license_counts=(source.license_counts if source else None),
        qa_status="pending",
        hw_status="pending",
        cert_status="pending",
        reason="recert",
    )
    db.add(new_cert)
    db.flush()  # assign new_cert.id for the copied file rows

    if source is not None:
        srcs = (
            db.query(BuildCertificationFile)
            .filter(BuildCertificationFile.build_certification_id == source.id)
            .filter(BuildCertificationFile.kind == "source")
            .order_by(BuildCertificationFile.uploaded_at.asc(), BuildCertificationFile.id.asc())
            .all()
        )
        serial_dir = Path(settings.CERT_UPLOAD_DIR) / (eb.serial or "unknown")
        for f in srcs:
            src_path = serial_dir / f.stored_name
            if not src_path.exists():
                continue  # skip a missing source file; never abort the re-cert
            serial_dir.mkdir(parents=True, exist_ok=True)
            new_stored = f"{uuid.uuid4().hex}{Path(f.stored_name).suffix or '.bin'}"
            with open(src_path, "rb") as rfh, open(serial_dir / new_stored, "wb") as wfh:
                wfh.write(rfh.read())
            db.add(BuildCertificationFile(
                build_certification_id=new_cert.id,
                oem_serial=eb.serial,
                kind="source",
                original_name=f.original_name,
                stored_name=new_stored,
                content_type=f.content_type,
                size_bytes=f.size_bytes,
                uploaded_by=f.uploaded_by,
            ))

    db.commit()
    db.refresh(new_cert)

    return {"ok": True, "cert_id": new_cert.id, "cert_status": "pending"}


@router.get("/fulfillment/certifications/history/{serial}", response_class=HTMLResponse)
def cert_history(
    serial: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Per-serial build-certification timeline: every attempt for one Edge Box serial, newest
    first, each linking to its composite report + source files, with both signers and reason."""
    attempts = (
        db.query(BuildCertification)
        .filter(BuildCertification.oem_serial == serial)
        .order_by(BuildCertification.created_at.desc())
        .all()
    )
    att_ids = [a.id for a in attempts]
    files_by_cert = {}
    if att_ids:
        for f in (
            db.query(BuildCertificationFile)
            .filter(BuildCertificationFile.build_certification_id.in_(att_ids))
            .order_by(BuildCertificationFile.uploaded_at.asc(), BuildCertificationFile.id.asc())
            .all()
        ):
            files_by_cert.setdefault(f.build_certification_id, []).append(f)
    events = []
    for a in attempts:
        afiles = files_by_cert.get(a.id, [])
        composite = next((f for f in afiles if f.kind == "composite"), None)
        sources = [f for f in afiles if f.kind == "source"]
        events.append({
            "id": a.id,
            "cert_status": a.cert_status,
            "qa_status": a.qa_status,
            "hw_status": a.hw_status,
            "reason": a.reason,
            "qa_signer": a.certified_by,
            "hw_signer": a.co_certified_by,
            "certified_at": a.certified_at,
            "cancelled_by": a.cancelled_by,
            "cancelled_at": a.cancelled_at,
            "cancel_reason": a.cancel_reason,
            "created_at": a.created_at,
            "customer_name": a.customer_name,
            "order_number": a.order_number,
            "composite": ({"id": composite.id, "name": composite.original_name} if composite else None),
            "sources": [{"id": f.id, "name": f.original_name} for f in sources],
        })
    back_prov_id = attempts[0].device_provisioning_id if attempts else None
    return templates.TemplateResponse(request, "build_cert_history.html", {
        "request": request,
        "user": user,
        "serial": serial,
        "events": events,
        "back_prov_id": back_prov_id,
    })
