"""Fulfillment — unified view of customer orders + provisioning pipeline.

Replaces the separate /orders/ and /provisioning/ list pages with a single
Kanban command center showing the full order-to-deployment pipeline.

Detail pages (/orders/{id}, /provisioning/{id}) remain unchanged.
"""

import io
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from ..auth import require_provisioning_manager, require_provisioning_viewer
from ..config import settings
from ..database import get_db
from ..models import (
    CustomerOrder, DeploymentRecord, DeviceProvisioning, EdgeBox,
    OEMPurchaseOrder, Site, User, TABLE_MODELS,
    BuildCertification,
    STAGE_GROUPS, STAGE_LABELS, STAGE_INDEX, STAGE_TO_GROUP,
)
from ..sku_conversion import is_legacy_sku, is_2026_sku

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

# Active statuses shown as open columns; archived shown collapsed
ACTIVE_STATUSES = ["new", "sourcing", "building", "testing", "shipped"]
ARCHIVED_STATUSES = ["delivered", "installed"]


class ShipDetailsUpdate(BaseModel):
    ship_method: Optional[str] = None
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


class CertComponent(BaseModel):
    type: str
    model: str
    ok: bool


class CertQASubmit(BaseModel):
    qa_checklist: dict          # 5 keys: hardware, pva_events, searches, netplan, registration -> bool
    components: list            # list of CertComponent-shaped dicts, >= 1
    license_assigned: int
    license_ordered: int


def _order_urgency(due_date) -> str:
    """Map a due date to an urgency bucket. Single source of the thresholds,
    shared by the order cards and the Building-board groups."""
    if not due_date:
        return "normal"
    days = (due_date - date.today()).days
    if days < 0:
        return "overdue"
    if days <= 3:
        return "critical"
    if days <= 7:
        return "soon"
    return "normal"


# Building-board grouping (S1). Group key = (order x SKU). Group stage = the
# LEAST-ADVANCED linked device, so a lagging unit holds the whole group back.
# Tab rollup: Queued (no linked devices, card from sku_requirements intent) /
# Ready for Handoff (every linked device build-cert complete) / In Progress.
GROUP_TO_BUILD_LABEL = {
    "new": "Drafting", "sourcing": "Sourcing", "building": "Assembly", "testing": "Testing",
}



# 5-stage Building tracker buckets (display label -> substage names).
# Testing excludes the certified step; Sign-off is certified alone.
BUILD_TRACKER = [
    ("Drafting",  ["po_in", "scoped", "sourced", "ready"]),
    ("Sourcing",  ["ordered", "tracking", "deliver", "received"]),
    ("Assembly",  ["staged", "building", "registered", "licensed"]),
    ("Testing",   ["hw_check", "sw_version", "pva_events"]),
    ("Sign-off",  ["certified"]),
]


def _build_stage_states(gdevs):
    """Per-group rollup of the 5 Building tracker stages to done/current/future,
    derived from each device current_stage (contiguous-completion model)."""
    states = []
    idxs = [STAGE_INDEX.get(d.get("current_stage"), -1) for d in gdevs] or [-1]
    for label, subs in BUILD_TRACKER:
        first = min(STAGE_INDEX[n] for n in subs)
        last = max(STAGE_INDEX[n] for n in subs)
        if label == "Sign-off":
            if all(d.get("build_cert_complete") for d in gdevs):
                st = "done"
            elif max(idxs) < first:
                st = "future"
            else:
                st = "current"
        else:
            if min(idxs) > last:
                st = "done"
            elif max(idxs) < first:
                st = "future"
            else:
                st = "current"
        states.append({"label": label, "state": st})
    return states



_SE_PALETTE = ["#3b82f6", "#a855f7", "#f97316", "#10b981", "#f43f5e", "#f59e0b"]


def _se_color(name):
    """Deterministic per-name color from a fixed 6-color palette."""
    if not name:
        return "var(--text-muted)"
    return _SE_PALETTE[sum(ord(c) for c in name) % len(_SE_PALETTE)]


def _se_initials(name):
    """Up to two initials from a name, or ? when unassigned."""
    if not name:
        return "?"
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def build_fulfillment_groups(orders, order_devices):
    """orders: list of CustomerOrder ORM rows. order_devices: {order_id: [device dict]}
    each carrying part_number, current_stage, build_cert_complete. Returns Building cards."""
    groups = []
    for o in orders:
        o_meta = {
            "sales_engineer": o.sales_engineer,
            "se_color": _se_color(o.sales_engineer),
            "se_initials": _se_initials(o.sales_engineer),
            "due_date": o.due_date,
            "urgency": _order_urgency(o.due_date),
            "is_sensitive": o.is_sensitive,
        }
        devs = order_devices.get(o.id, [])
        by_sku = {}
        for d in devs:
            sku = (d.get("part_number") or "").strip() or "Unspecified"
            by_sku.setdefault(sku, []).append(d)

        for sku, gdevs in by_sku.items():
            laggard = min(gdevs, key=lambda d: STAGE_INDEX.get(d.get("current_stage"), -1))
            lag_group = STAGE_TO_GROUP.get(laggard.get("current_stage"))
            all_cert = all(d.get("build_cert_complete") for d in gdevs)
            if all_cert:
                tab, stage_label = "ready_for_handoff", "Sign-off"
            else:
                tab = "in_progress"
                stage_label = GROUP_TO_BUILD_LABEL.get(lag_group, lag_group)
            groups.append({
                **o_meta,
                "order_id": o.id, "order_number": o.order_number,
                "customer_name": o.customer_name, "sku": sku,
                "device_count": len(gdevs), "tab": tab, "stage_label": stage_label,
                "stage_states": _build_stage_states(gdevs),
                "source": "devices",
            })

        for req in (o.sku_requirements or []):
            sku = (req.get("sku") or "").strip() or "Unspecified"
            if sku in by_sku:
                continue
            groups.append({
                **o_meta,
                "order_id": o.id, "order_number": o.order_number,
                "customer_name": o.customer_name, "sku": sku,
                "device_count": 0, "intended_qty": int(req.get("qty") or 0),
                "tab": "queued", "stage_label": None, "source": "intent",
            })

        if not devs and not (o.sku_requirements or []):
            groups.append({
                **o_meta,
                "order_id": o.id, "order_number": o.order_number,
                "customer_name": o.customer_name, "sku": "Unspecified",
                "device_count": 0, "intended_qty": 0,
                "tab": "queued", "stage_label": None, "source": "empty",
            })
    return groups


def _build_order_card(order: CustomerOrder, prov_count: int) -> dict:
    """Return a lightweight dict for rendering a Kanban card."""
    days_until_due = (order.due_date - date.today()).days if order.due_date else None
    urgency = _order_urgency(order.due_date)

    total_sku_qty = sum(int(r.get("qty") or 0) for r in (order.sku_requirements or []))

    return {
        "id": order.id,
        "order_number": order.order_number,
        "customer_name": order.customer_name,
        "status": order.status,
        "due_date": order.due_date,
        "days_until_due": days_until_due,
        "urgency": urgency,
        "prov_count": prov_count,
        "total_sku_qty": total_sku_qty,
        "sku_requirements": order.sku_requirements or [],
        "contract_value": order.contract_value,
        "hardware_cost": order.hardware_cost,
        "is_sensitive": order.is_sensitive,
        "sales_engineer": order.sales_engineer,
        "deployment_type": order.deployment_type,
        "po_number": order.po_number,
        "default_fulfillment_type": order.default_fulfillment_type,
        "integrator_name": order.integrator_name or None,
        "distributor_name": order.distributor_name or None,
        # ── Shipping fields (migration 021) ──
        "shipped_date": order.shipped_date,
        "delivered_date": order.delivered_date,
        "carrier": order.carrier,
        "tracking_number": order.tracking_number,
        "shipping_address": order.shipping_address,
        "ship_method": order.ship_method or "carrier",
        "recipient_name": order.recipient_name,
    }


def _is_valid_sku(sku: str) -> bool:
    """Return True if the part_number looks like a real EDGE/PVA SKU."""
    if not sku:
        return False
    return is_2026_sku(sku) or is_legacy_sku(sku)


def _stock_snapshot(db: Session) -> tuple[list[dict], list[dict]]:
    """Return (known_skus, unclassified) lists of EdgeBox stock grouped by part_number.

    known_skus   — groups with recognized EDGE*/PVA-* part numbers
    unclassified — groups with missing, blank, or non-SKU part numbers (e.g.
                   vendor hardware IDs like "6VX72", old "E2C-*" codes, or NULL)

    'Available' means: not currently linked to an active (incomplete)
    provisioning record.
    """
    # Collect device IDs that are actively provisioned
    busy_ids = {
        p.device_id
        for p in db.query(DeviceProvisioning.device_id)
        .filter(
            DeviceProvisioning.device_table == "edge_boxes",
            DeviceProvisioning.is_complete.is_(False),
        )
        .all()
    }

    # Query all edge boxes, group by part_number
    all_boxes = db.query(EdgeBox).all()
    groups: dict[str, dict] = {}
    for box in all_boxes:
        raw = (box.part_number or "").strip()
        model_key = raw or "— no SKU —"
        if model_key not in groups:
            groups[model_key] = {
                "model": model_key,
                "total": 0,
                "available": 0,
                "is_valid_sku": _is_valid_sku(raw),
                "raw_part": raw,
            }
        groups[model_key]["total"] += 1
        if box.id not in busy_ids:
            groups[model_key]["available"] += 1

    all_groups = sorted(groups.values(), key=lambda g: g["model"])
    known = [g for g in all_groups if g["is_valid_sku"]]
    unclassified = [g for g in all_groups if not g["is_valid_sku"]]
    return known, unclassified


# ---------------------------------------------------------------------------
# Main Fulfillment page
# ---------------------------------------------------------------------------

@router.get("/fulfillment/", response_class=HTMLResponse)
def fulfillment_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Unified Kanban showing order pipeline + stock health."""

    # Fetch all orders, apply sensitive filter
    all_orders = (
        db.query(CustomerOrder)
        .order_by(CustomerOrder.due_date.asc().nullslast(), CustomerOrder.created_at.desc())
        .all()
    )
    can_see_sensitive = user.has_sensitive_customers_access
    orders = [o for o in all_orders if not o.is_sensitive or can_see_sensitive]

    # Provisioning counts per order
    prov_counts: dict[int, int] = {}
    for p in db.query(DeviceProvisioning.customer_order_id).filter(
        DeviceProvisioning.customer_order_id.isnot(None),
        DeviceProvisioning.is_complete.is_(False),
    ).all():
        oid = p.customer_order_id
        prov_counts[oid] = prov_counts.get(oid, 0) + 1

    # Device details per order (for slide panel)
    device_rows = (
        db.query(
            DeviceProvisioning.id,
            DeviceProvisioning.customer_order_id,
            DeviceProvisioning.assigned_to,
            DeviceProvisioning.validation_result,
            DeviceProvisioning.is_complete,
            DeviceProvisioning.current_stage,
            DeviceProvisioning.fulfillment_type,
            DeviceProvisioning.stages,
            EdgeBox.serial,
            EdgeBox.part_number,
            User.display_name,
        )
        .outerjoin(
            EdgeBox,
            (DeviceProvisioning.device_id == EdgeBox.id)
            & (DeviceProvisioning.device_table == "edge_boxes"),
        )
        .outerjoin(User, DeviceProvisioning.assigned_to == User.id)
        .filter(
            DeviceProvisioning.customer_order_id.isnot(None),
            DeviceProvisioning.device_table == "edge_boxes",
        )
        .all()
    )
    order_devices: dict[int, list[dict]] = {}
    for row in device_rows:
        order_devices.setdefault(row.customer_order_id, []).append({
            "prov_id": row.id,
            "serial": row.serial,
            "part_number": row.part_number,
            "assigned_to_id": row.assigned_to,
            "assigned_to_name": row.display_name,
            "validation_result": row.validation_result,
            "is_complete": row.is_complete,
            "current_stage": row.current_stage,
            "fulfillment_type": row.fulfillment_type,
            "build_cert_complete": any(
                s.get("name") == "certified" and s.get("completed")
                for s in (row.stages or [])
            ),
        })

    # OEM purchase orders — all, linked and unlinked
    oem_pos = db.query(OEMPurchaseOrder).order_by(
        OEMPurchaseOrder.expected_delivery.asc().nullslast()
    ).all()

    # Group into status columns for the OEM board
    oem_columns: dict[str, list] = {s: [] for s in OEMPurchaseOrder.OEM_STATUSES}
    for po in oem_pos:
        status = po.status if po.status in oem_columns else "ordered"
        oem_columns[status].append({
            "id": po.id,
            "vendor_name": po.vendor_name,
            "po_number": po.po_number,
            "sku": po.sku,
            "qty_ordered": po.qty_ordered,
            "qty_received": po.qty_received,
            "order_date": po.order_date,
            "expected_delivery": po.expected_delivery,
            "received_date": po.received_date,
            "status": po.status,
            "notes": po.notes,
            "customer_order_id": po.customer_order_id,
            "customer_order_number": po.customer_order.order_number if po.customer_order else None,
            "customer_name": po.customer_order.customer_name if po.customer_order else None,
        })

    # Active sales engineers for coverage panel
    team_rows = (
        db.query(CustomerOrder.sales_engineer)
        .filter(
            CustomerOrder.status.in_(ACTIVE_STATUSES),
            CustomerOrder.sales_engineer.isnot(None),
            CustomerOrder.sales_engineer != "",
        )
        .distinct()
        .all()
    )
    team_members = sorted(r.sales_engineer for r in team_rows)

    # Edge box counts per SE via DeviceProvisioning → CustomerOrder
    eb_counts_raw = (
        db.query(CustomerOrder.sales_engineer, sqlfunc.count(DeviceProvisioning.id))
        .join(DeviceProvisioning, DeviceProvisioning.customer_order_id == CustomerOrder.id)
        .filter(DeviceProvisioning.device_table == 'edge_boxes')
        .filter(CustomerOrder.sales_engineer.isnot(None))
        .group_by(CustomerOrder.sales_engineer)
        .all()
    )
    edge_box_counts = {name: count for name, count in eb_counts_raw}

    # Deployment records — active only (exclude cancelled)
    deployment_records = db.query(DeploymentRecord).filter(
        DeploymentRecord.status.notin_(["cancelled"])
    ).order_by(
        DeploymentRecord.scheduled_date.asc().nullslast()
    ).all()

    # Group into status columns for deployment pipeline
    deploy_columns: dict[str, list] = {
        s: [] for s in DeploymentRecord.DEPLOYMENT_STATUSES
        if s != "cancelled"
    }
    for dr in deployment_records:
        status = dr.status if dr.status in deploy_columns else "scheduled"
        deploy_columns[status].append({
            "id": dr.id,
            "customer_order_id": dr.customer_order_id,
            "order_number": dr.customer_order.order_number if dr.customer_order else None,
            "customer_name": dr.customer_order.customer_name if dr.customer_order else None,
            "site_id": dr.site_id,
            "site_name": dr.site.name if dr.site else None,
            "address": dr.address,
            "status": dr.status,
            "scheduled_date": dr.scheduled_date,
            "installed_date": dr.installed_date,
            "se_assigned_id": dr.se_assigned_id,
            "se_name": dr.se_assigned.display_name if dr.se_assigned else None,
            "integrator_name": dr.integrator_name,
            "integrator_contact": dr.integrator_contact,
            "notes": dr.notes,
        })

    # Sites for deployment modal dropdown
    sites = db.query(Site).filter(Site.is_active.is_(True)).order_by(Site.name.asc()).all()
    site_list = [{"id": s.id, "name": s.name, "address": s.address, "type": s.site_type} for s in sites]

    # SEs for deployment modal dropdown
    se_users = db.query(User).filter(User.is_active.is_(True)).order_by(User.display_name.asc()).all()
    se_list = [{"id": u.id, "name": u.display_name} for u in se_users]

    # Build card dicts
    cards = [_build_order_card(o, prov_counts.get(o.id, 0)) for o in orders]

    # S1: order x SKU grouped cards for the Building board (least-advanced rollup)
    fulfillment_groups = build_fulfillment_groups(orders, order_devices)

    # Group by status
    columns: dict[str, list] = {s: [] for s in ACTIVE_STATUSES + ARCHIVED_STATUSES}
    for card in cards:
        status = card["status"] if card["status"] in columns else "new"
        columns[status].append(card)

    # Summary counts
    total_active = sum(len(columns[s]) for s in ACTIVE_STATUSES)
    overdue_count = sum(1 for c in cards if c["urgency"] == "overdue")
    due_soon_count = sum(1 for c in cards if c["urgency"] in ("critical", "soon"))

    # Stock snapshot — split into known SKUs and unclassified entries
    stock_known, stock_unclassified = _stock_snapshot(db)
    stock_total = sum(g["total"] for g in stock_known) + sum(g["total"] for g in stock_unclassified)
    stock_available = sum(g["available"] for g in stock_known) + sum(g["available"] for g in stock_unclassified)
    unclassified_count = sum(g["total"] for g in stock_unclassified)

    # Unlinked active provisioning records (not tied to any order)
    unlinked_prov = (
        db.query(DeviceProvisioning)
        .filter(
            DeviceProvisioning.is_complete.is_(False),
            DeviceProvisioning.customer_order_id.is_(None),
        )
        .count()
    )

    return templates.TemplateResponse("fulfillment.html", {
        "request": request,
        "user": user,
        "columns": columns,
        "active_statuses": ACTIVE_STATUSES,
        "archived_statuses": ARCHIVED_STATUSES,
        "order_statuses": CustomerOrder.ORDER_STATUSES,
        "status_colors": CustomerOrder.STATUS_COLORS,
        "total_active": total_active,
        "overdue_count": overdue_count,
        "due_soon_count": due_soon_count,
        "stock_known": stock_known,
        "stock_unclassified": stock_unclassified,
        "unclassified_count": unclassified_count,
        "stock_total": stock_total,
        "stock_available": stock_available,
        "unlinked_prov": unlinked_prov,
        "can_see_sensitive": can_see_sensitive,
        "order_devices": order_devices,
        "fulfillment_groups": fulfillment_groups,
        "team_members": team_members,
        "edge_box_counts": edge_box_counts,
        "current_user_name": user.display_name,
        "oem_columns": oem_columns,
        "oem_status_labels": OEMPurchaseOrder.OEM_STATUS_LABELS,
        "oem_statuses": OEMPurchaseOrder.OEM_STATUSES,
        "oem_total": len(oem_pos),
        "oem_active": sum(1 for p in oem_pos if p.status not in ("verified", "cancelled")),
        "oem_dot_colors": {
            "ordered": "var(--accent-blue)",
            "in_production": "var(--fl-amber)",
            "acceptance": "var(--fl-purple)",
            "receiving": "var(--fl-orange)",
            "verified": "var(--fl-green)",
            "cancelled": "var(--text-muted)",
        },
        "today": date.today(),
        "stage_groups": STAGE_GROUPS,
        "stage_labels": STAGE_LABELS,
        "deploy_columns": deploy_columns,
        "deploy_status_labels": DeploymentRecord.DEPLOYMENT_STATUS_LABELS,
        "deploy_statuses": [s for s in DeploymentRecord.DEPLOYMENT_STATUSES if s != "cancelled"],
        "deploy_total": len(deployment_records),
        "deploy_active": sum(1 for d in deployment_records
                             if d.status not in ("complete", "cancelled")),
        "deploy_dot_colors": {
            "scheduled": "var(--text-muted)",
            "in_transit": "var(--accent-blue)",
            "on_site": "var(--fl-amber)",
            "installing": "var(--fl-purple)",
            "complete": "var(--fl-green)",
        },
        "site_list": site_list,
        "se_list": se_list,
    })


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
    if not order:
        return JSONResponse(status_code=404, content={"detail": "Order not found"})

    update_data = payload.dict(exclude_none=True)
    for field, value in update_data.items():
        setattr(order, field, value)

    # If shipped_date is being set and order is not yet shipped, advance status
    if payload.shipped_date and order.status in ("building", "testing"):
        order.status = "shipped"

    db.commit()

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
    )
    db.add(dr)
    db.commit()
    db.refresh(dr)

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
    new_status = body.get("status", "").strip()
    valid = [s for s in DeploymentRecord.DEPLOYMENT_STATUSES if s != "cancelled"]
    if new_status not in valid:
        return JSONResponse(status_code=400, content={"detail": f"Invalid status: {new_status}"})

    old_status = dr.status
    dr.status = new_status

    # Auto-set installed_date when completing
    if new_status == "complete" and not dr.installed_date:
        dr.installed_date = date.today()

    db.commit()
    return {"ok": True, "id": dr.id, "old_status": old_status, "status": new_status}


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
    if user.has_financial_access:
        headers.extend(["Contract Value", "Hardware Cost"])

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
            order.created_at.strftime("%Y-%m-%d") if order.created_at else "",
        ]
        if user.has_financial_access:
            row_data.extend([
                float(order.contract_value) if order.contract_value else None,
                float(order.hardware_cost) if order.hardware_cost else None,
            ])
        for col_idx, value in enumerate(row_data, 1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-fit column widths
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"fulfillment_export_{date.today().isoformat()}.xlsx"
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
    """Read-only certification index: every edge-box device with an order link,
    organized by date / customer / SKU, decorated with latest cert status.

    build_certification is append-only and may hold multiple rows per device;
    the status shown reflects the latest cert row (max created_at) per device.
    No writes occur here.
    """
    # All edge-box devices with an order link, joined to their order.
    rows = (
        db.query(
            DeviceProvisioning.id.label("prov_id"),
            DeviceProvisioning.current_stage,
            DeviceProvisioning.is_complete,
            EdgeBox.serial,
            EdgeBox.part_number,
            CustomerOrder.order_number,
            CustomerOrder.customer_name,
            CustomerOrder.due_date,
        )
        .join(
            EdgeBox,
            (DeviceProvisioning.device_id == EdgeBox.id)
            & (DeviceProvisioning.device_table == "edge_boxes"),
        )
        .join(CustomerOrder, DeviceProvisioning.customer_order_id == CustomerOrder.id)
        .filter(DeviceProvisioning.device_table == "edge_boxes")
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

    return templates.TemplateResponse("certifications.html", {
        "request": request,
        "user": user,
        "groups": sorted_groups,
        "total_devices": total_devices,
    })


# ---------------------------------------------------------------------------
# Build Certification - the QA half (F3/S6b), first write path
# ---------------------------------------------------------------------------

_QA_KEYS = {'hardware', 'pva_events', 'searches', 'netplan', 'registration'}
_COMP_TYPES = {'cpu', 'gpu', 'ram', 'hdd', 'ssd'}


@router.post("/fulfillment/certifications/{prov_id}/qa")
async def submit_cert_qa(
    prov_id: int,
    payload: CertQASubmit,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Create a new build_certification row with the QA half.

    Single-step: this POST CREATES the row (never updates). Sets qa_status
    complete; hw_status and cert_status stay pending (the all-pass gate is
    S6c). Append-only: a new attempt is always a new row.
    """
    # Resolve the provisioning row + its edge box + order.
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})
    if prov.device_table != "edge_boxes":
        return JSONResponse(status_code=400, content={"detail": "Certification is edge-box only"})

    eb = db.query(EdgeBox).filter(EdgeBox.id == prov.device_id).first()
    if not eb:
        return JSONResponse(status_code=404, content={"detail": "Edge box not found"})

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

    # --- soft-guard: block a duplicate QA-pending submit for this serial ---
    # Look at the LATEST cert row for this serial; block only if it is
    # qa_status complete AND cert_status pending (someone is mid-attempt).
    latest = (
        db.query(BuildCertification)
        .filter(BuildCertification.oem_serial == eb.serial)
        .order_by(BuildCertification.created_at.desc())
        .first()
    )
    if latest is not None and latest.qa_status == "complete" and latest.cert_status == "pending":
        return JSONResponse(status_code=409, content={
            "detail": "QA already submitted for this serial, awaiting hardware sign-off"
        })

    # --- construct + insert (route sets all status fields, not the payload) ---
    cert = BuildCertification(
        device_provisioning_id=prov_id,
        oem_serial=eb.serial,
        device_uuid=eb.uuid,
        sku=eb.part_number,
        customer_name=(co.customer_name if co else None),
        order_number=(co.order_number if co else None),
        qa_checklist={k: {"checked": bool(v)} for k, v in payload.qa_checklist.items()},
        hardware_validation={"components": norm_components},
        license_counts={"assigned": payload.license_assigned, "ordered": payload.license_ordered},
        certified_by=user.display_name,
        certified_at=datetime.utcnow(),
        qa_status="complete",
        hw_status="pending",
        cert_status="pending",
        reason="initial",
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)

    return {
        "ok": True,
        "cert_id": cert.id,
        "qa_status": cert.qa_status,
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
    if not prov or prov.device_table != "edge_boxes":
        return RedirectResponse(url=f"{BP}/fulfillment/certifications", status_code=302)

    eb = db.query(EdgeBox).filter(EdgeBox.id == prov.device_id).first()
    if not eb:
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
        "certified_at": (h.certified_at.isoformat(sep=" ", timespec="minutes") if h.certified_at else "-"),
    } for h in history_rows]

    # Soft-guard state: is the latest row QA-done-but-pending (mid-attempt)?
    awaiting_hw = bool(
        history_rows
        and history_rows[0].qa_status == "complete"
        and history_rows[0].cert_status == "pending"
    )

    # The 5 QA checks, in display order, with labels (labels live in code).
    qa_checks = [
        ("hardware", "Hardware"),
        ("pva_events", "PVA events"),
        ("searches", "Searches"),
        ("netplan", "Netplan"),
        ("registration", "Registration"),
    ]
    comp_types = ["cpu", "gpu", "ram", "hdd", "ssd"]

    return templates.TemplateResponse("certification_detail.html", {
        "request": request,
        "user": user,
        "device": device,
        "history": history,
        "awaiting_hw": awaiting_hw,
        "qa_checks": qa_checks,
        "comp_types": comp_types,
    })
