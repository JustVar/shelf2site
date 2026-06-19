"""Customer Order management routes.

Tracks customer orders from Salesforce opportunity through delivery and install.
Links to provisioning records and OEM purchase orders.
"""

import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func as sqlfunc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import get_current_user, require_editor, require_provisioning_viewer, require_provisioning_manager
from ..config import settings
from ..database import get_db
from ..models import (
    CustomerOrder, OEMPurchaseOrder, DeviceProvisioning,
    User, TABLE_MODELS, get_display_name, get_serial,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


# ---------------------------------------------------------------------------
# Order number generator
# ---------------------------------------------------------------------------

def _next_order_number(db: Session) -> str:
    """Generate the next AT-XXXX order number."""
    last = (
        db.query(CustomerOrder)
        .order_by(CustomerOrder.id.desc())
        .first()
    )
    if not last or not last.order_number:
        return "AT-1001"
    m = re.search(r"(\d+)$", last.order_number)
    n = int(m.group(1)) + 1 if m else 1001
    return f"AT-{n}"


# ---------------------------------------------------------------------------
# SKU availability helper
# ---------------------------------------------------------------------------

def _sku_availability(db: Session, sku_requirements: list) -> list:
    """For each {model, qty, source} requirement, count unprovisioned inventory."""
    results = []
    for req in sku_requirements:
        model = (req.get("model") or "").strip()
        needed = int(req.get("qty") or 0)
        if not model:
            continue

        # Count devices matching this model that are NOT in an active provisioning record
        provisioned_device_ids_by_table: dict[str, list[int]] = {}
        active_prov = (
            db.query(DeviceProvisioning)
            .filter(DeviceProvisioning.is_complete.is_(False))
            .all()
        )
        for p in active_prov:
            provisioned_device_ids_by_table.setdefault(p.device_table, []).append(p.device_id)

        available = 0
        for table_name, model_cls in TABLE_MODELS.items():
            if not hasattr(model_cls, "model"):
                continue
            busy_ids = provisioned_device_ids_by_table.get(table_name, [])
            q = db.query(model_cls).filter(model_cls.model.ilike(f"%{model}%"))
            if busy_ids:
                q = q.filter(~model_cls.id.in_(busy_ids))
            available += q.count()

        if available >= needed:
            status = "ok"
        elif available > 0:
            status = "partial"
        else:
            status = "none"

        results.append({
            "model": model,
            "qty": needed,
            "source": req.get("source", "tbd"),
            "available": available,
            "status": status,
        })
    return results


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@router.get("/orders/", response_class=HTMLResponse)
def orders_redirect():
    """Redirect to unified Fulfillment page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{BP}/fulfillment/", status_code=301)


@router.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return RedirectResponse(f"{BP}/fulfillment/", status_code=303)

    availability = _sku_availability(db, order.sku_requirements or [])

    # Linked provisioning records
    prov_records = (
        db.query(DeviceProvisioning)
        .filter(DeviceProvisioning.customer_order_id == order_id)
        .order_by(DeviceProvisioning.created_at.desc())
        .all()
    )
    prov_enriched = []
    for p in prov_records:
        device_label = f"{p.device_table} #{p.device_id}"
        model_cls = TABLE_MODELS.get(p.device_table)
        if model_cls:
            device = db.query(model_cls).filter(model_cls.id == p.device_id).first()
            if device:
                device_label = get_display_name(device)
        prov_enriched.append({"record": p, "device_label": device_label})

    se_names = sorted(
        n[0] for n in db.query(CustomerOrder.sales_engineer)
        .filter(CustomerOrder.sales_engineer.isnot(None), CustomerOrder.sales_engineer != "")
        .distinct().all()
    )

    return templates.TemplateResponse("order_detail.html", {
        "request": request,
        "user": user,
        "order": order,
        "availability": availability,
        "prov_records": prov_enriched,
        "oem_pos": order.oem_pos,
        "ORDER_STATUSES": CustomerOrder.ORDER_STATUSES,
        "STATUS_COLORS": CustomerOrder.STATUS_COLORS,
        "se_names": se_names,
    })


# ---------------------------------------------------------------------------
# API — Customer Orders CRUD
# ---------------------------------------------------------------------------

@router.post("/api/orders/")
async def create_order(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    body = await request.json()
    customer_name = (body.get("customer_name") or "").strip()
    if not customer_name:
        return JSONResponse(status_code=400, content={"error": "Customer name is required"})

    # Numeric fields — safe parse
    def _to_dec(val):
        try:
            return float(val) if val not in (None, "", "0", 0) else None
        except (TypeError, ValueError):
            return None

    order = CustomerOrder(
        order_number=_next_order_number(db),
        salesforce_order_id=(body.get("salesforce_order_id") or "").strip() or None,
        salesforce_opp_id=(body.get("salesforce_opp_id") or "").strip() or None,
        customer_name=customer_name,
        customer_account=(body.get("customer_account") or "").strip() or None,
        sales_engineer=(body.get("sales_engineer") or "").strip() or None,
        sales_engineer_id=body.get("sales_engineer_id") or None,
        deployment_type=body.get("deployment_type") or "direct",
        integrator_name=(body.get("integrator_name") or "").strip() or None,
        distributor_name=(body.get("distributor_name") or "").strip() or None,
        due_date=body.get("due_date") or None,
        status=body.get("status") or "new",
        sku_requirements=body.get("sku_requirements") or [],
        notes=(body.get("notes") or "").strip() or None,
        is_sensitive=bool(body.get("is_sensitive", False)),
        contract_value=_to_dec(body.get("contract_value")),
        hardware_cost=_to_dec(body.get("hardware_cost")),
        po_number=(body.get("po_number") or "").strip() or None,
        default_fulfillment_type=(body.get("default_fulfillment_type") or "").strip() or None,
        created_by=user.id,
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=400, content={"error": "That PO number is already used by another order"})
    db.refresh(order)

    log_event(db, "order_created", request=request, user_id=user.id,
              target_table="customer_orders", target_id=order.id, action="create",
              details=f"Created order {order.order_number} for {customer_name}")

    return JSONResponse(content={"status": "ok", "id": order.id, "order_id": order.id, "order_number": order.order_number})


@router.put("/api/orders/{order_id}")
async def update_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Order not found"})

    body = await request.json()
    str_fields = [
        "salesforce_order_id", "salesforce_opp_id", "customer_name", "customer_account",
        "sales_engineer", "deployment_type", "integrator_name", "distributor_name",
        "status", "notes", "pre_site_survey", "post_install_notes",
        "po_number", "default_fulfillment_type",
    ]
    for field in str_fields:
        if field in body:
            setattr(order, field, (body[field] or "").strip() or None)

    if "due_date" in body:
        order.due_date = body["due_date"] or None
    if "sales_engineer_id" in body:
        order.sales_engineer_id = body["sales_engineer_id"] or None
    if "sku_requirements" in body:
        order.sku_requirements = body["sku_requirements"] or []
    if "is_sensitive" in body:
        order.is_sensitive = bool(body["is_sensitive"])
    if "contract_value" in body:
        try:
            v = body["contract_value"]
            order.contract_value = float(v) if v not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            pass
    if "hardware_cost" in body:
        try:
            v = body["hardware_cost"]
            order.hardware_cost = float(v) if v not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            pass

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=400, content={"error": "That PO number is already used by another order"})
    log_event(db, "order_updated", request=request, user_id=user.id,
              target_table="customer_orders", target_id=order_id, action="update",
              details=f"Updated order {order.order_number}")

    return JSONResponse(content={"status": "ok"})


@router.delete("/api/orders/{order_id}")
def delete_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Order not found"})

    order_number = order.order_number
    db.delete(order)
    db.commit()
    log_event(db, "order_deleted", request=request, user_id=user.id,
              target_table="customer_orders", target_id=order_id, action="delete",
              details=f"Deleted order {order_number}")
    return JSONResponse(content={"status": "ok"})


@router.get("/api/orders/{order_id}/availability")
def order_availability(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Return live SKU availability check for this order."""
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Order not found"})
    return JSONResponse(content={"availability": _sku_availability(db, order.sku_requirements or [])})


# ---------------------------------------------------------------------------
# API — OEM Purchase Orders
# ---------------------------------------------------------------------------

@router.post("/api/orders/{order_id}/oem-pos")
async def create_oem_po(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Order not found"})

    body = await request.json()
    vendor_name = (body.get("vendor_name") or "").strip()
    sku = (body.get("sku") or "").strip()
    if not vendor_name or not sku:
        return JSONResponse(status_code=400, content={"error": "vendor_name and sku are required"})

    po = OEMPurchaseOrder(
        customer_order_id=order_id,
        vendor_name=vendor_name,
        po_number=(body.get("po_number") or "").strip() or None,
        sku=sku,
        qty_ordered=int(body.get("qty_ordered") or 1),
        qty_received=int(body.get("qty_received") or 0),
        order_date=body.get("order_date") or None,
        expected_delivery=body.get("expected_delivery") or None,
        status=body.get("status") or "ordered",
        notes=(body.get("notes") or "").strip() or None,
    )
    db.add(po)
    db.commit()
    db.refresh(po)

    log_event(db, "oem_po_created", request=request, user_id=user.id,
              target_table="oem_purchase_orders", target_id=po.id, action="create",
              details=f"OEM PO: {vendor_name} × {sku} ({po.qty_ordered} units) for {order.order_number}")

    return JSONResponse(content={"status": "ok", "po_id": po.id})


@router.put("/api/orders/{order_id}/oem-pos/{po_id}")
async def update_oem_po(
    order_id: int,
    po_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    po = db.query(OEMPurchaseOrder).filter(
        OEMPurchaseOrder.id == po_id,
        OEMPurchaseOrder.customer_order_id == order_id,
    ).first()
    if not po:
        return JSONResponse(status_code=404, content={"error": "PO not found"})

    body = await request.json()
    for field in ["vendor_name", "po_number", "sku", "status", "notes"]:
        if field in body:
            setattr(po, field, (body[field] or "").strip() or None)
    for field in ["qty_ordered", "qty_received"]:
        if field in body:
            setattr(po, field, int(body[field] or 0))
    for field in ["order_date", "expected_delivery", "received_date"]:
        if field in body:
            setattr(po, field, body[field] or None)

    db.commit()
    log_event(db, "oem_po_updated", request=request, user_id=user.id,
              target_table="oem_purchase_orders", target_id=po_id, action="update",
              details=f"Updated OEM PO #{po_id}")

    return JSONResponse(content={"status": "ok"})


@router.delete("/api/orders/{order_id}/oem-pos/{po_id}")
def delete_oem_po(
    order_id: int,
    po_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    po = db.query(OEMPurchaseOrder).filter(
        OEMPurchaseOrder.id == po_id,
        OEMPurchaseOrder.customer_order_id == order_id,
    ).first()
    if not po:
        return JSONResponse(status_code=404, content={"error": "PO not found"})

    db.delete(po)
    db.commit()
    log_event(db, "oem_po_deleted", request=request, user_id=user.id,
              target_table="oem_purchase_orders", target_id=po_id, action="delete",
              details=f"Deleted OEM PO #{po_id} from order {order_id}")

    return JSONResponse(content={"status": "ok"})


# ---------------------------------------------------------------------------
# API — Link/unlink provisioning record to an order
# ---------------------------------------------------------------------------

@router.post("/api/provisioning/{prov_id}/link-order")
async def link_order(
    prov_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Link or unlink a provisioning record to a customer order.

    Body: { order_id: int|null }  — null to unlink
    """
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == prov_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})

    body = await request.json()
    order_id = body.get("order_id")

    if order_id:
        order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        prov.customer_order_id = order_id
        detail = f"Linked provisioning #{prov_id} to order {order.order_number}"
    else:
        prov.customer_order_id = None
        detail = f"Unlinked provisioning #{prov_id} from order"

    db.commit()
    log_event(db, "provisioning_order_linked", request=request, user_id=user.id,
              target_table="device_provisioning", target_id=prov_id, action="update",
              details=detail)

    return JSONResponse(content={"status": "ok"})


@router.get("/api/orders/open")
def open_orders_list(
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Lightweight list of open orders for the bulk-assign picker.

    Excludes orders with status 'installed' or 'cancelled'.
    Returns only the fields needed for the picker UI.
    """
    excluded = {"installed", "cancelled"}
    orders = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.status.notin_(excluded))
        .order_by(CustomerOrder.created_at.desc())
        .all()
    )
    return JSONResponse(content=[
        {
            "id": o.id,
            "order_number": o.order_number,
            "customer_name": o.customer_name,
            "status": o.status,
            "due_date": str(o.due_date) if o.due_date else None,
        }
        for o in orders
    ])
