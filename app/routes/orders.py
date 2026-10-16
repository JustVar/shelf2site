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
from ..auth import require_provisioning_viewer, require_provisioning_manager
from ..config import settings
from ..localtime import register
from ..database import get_db
from ..delete_requests import LOCK_MESSAGE, locked_ids
from ..models import (
    CustomerOrder, DeploymentRecord, OEMPartner, OEMPurchaseOrder, DeviceProvisioning,
    Item, ItemPartNumber,
    User,
    AuditLog,
)
from ..order_matching import candidate_items, requirement_lines

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


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
        # Tolerant read: legacy hand-written rows used a 'sku' key; the
        # editor writes the canonical 'model' key only.
        model = (req.get("model") or req.get("sku") or "").strip()
        needed = int(req.get("qty") or 0)
        if not model:
            continue

        # Ready item stock, via the same matcher the Assign panel uses.
        # Item 30 S4: the legacy per-table count is gone.
        available = len(candidate_items(db, model))

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
    # Sensitive-order gate (shipment-photos slice): the board, panel API,
    # map and export all masked sensitive orders — this page did not.
    if order.is_sensitive and not user.has_sensitive_customers_access:
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
        device_label = f"Provisioning #{p.id}"
        if p.item_id:
            # Every unit is item-linked since item 30 S4 — label from items.
            item = db.query(Item).filter(Item.id == p.item_id).first()
            if item:
                device_label = item.item_name or item.item_model or device_label
                if item.item_sn:
                    device_label = f"{device_label} ({item.item_sn})"
        prov_enriched.append({"record": p, "device_label": device_label})

    se_names = sorted(
        n[0] for n in db.query(CustomerOrder.sales_engineer)
        .filter(CustomerOrder.sales_engineer.isnot(None), CustomerOrder.sales_engineer != "")
        .distinct().all()
    )

    # Catalog for the SKU-requirements editor typeahead (same pattern as intake).
    part_numbers = db.query(ItemPartNumber).order_by(ItemPartNumber.brand_sku).all()

    # Unit photos across this order, grouped by direction (shipment-photos).
    from ..models import UnitPhoto
    _photos = (db.query(UnitPhoto)
               .filter(UnitPhoto.customer_order_id == order.id,
                       UnitPhoto.is_hidden.is_(False))
               .order_by(UnitPhoto.taken_at.asc(), UnitPhoto.id.asc()).all())
    photos_by_direction = {"inbound": [], "outbound": []}
    for p in _photos:
        photos_by_direction.setdefault(p.direction, []).append({
            "id": p.id,
            "thumb_url": f"{BP}/api/photos/{p.id}/thumb",
            "file_url": f"{BP}/api/photos/{p.id}/file",
            "caption": p.caption,
            "taken_at": p.taken_at,
        })

    # The cancel reason has no column by design; it lives only in the
    # order_cancelled audit event (docs/specs/customer-order-cancel.md).
    cancel_reason = None
    if order.status == "cancelled":
        _ev = (db.query(AuditLog.new_values)
                 .filter(AuditLog.event_type == "order_cancelled",
                         AuditLog.target_table == "customer_orders",
                         AuditLog.target_id == order.id)
                 .order_by(AuditLog.id.desc()).first())
        if _ev and isinstance(_ev[0], dict):
            cancel_reason = _ev[0].get("reason")

    return templates.TemplateResponse("order_detail.html", {
        "request": request,
        "user": user,
        "order": order,
        "availability": availability,
        "sku_lines": requirement_lines(order),
        "prov_records": prov_enriched,
        "oem_pos": order.oem_pos,
        "part_numbers": part_numbers,
        # Plain list usable in BOTH template blocks — a {% set %} in the
        # content block cannot cross into the scripts block (Jinja scoping).
        "catalog_skus": [pn.brand_sku for pn in part_numbers],
        "photos_by_direction": photos_by_direction,
        "ORDER_STATUSES": CustomerOrder.ORDER_STATUSES,
        "ORDER_TYPES": CustomerOrder.ORDER_TYPES,
        "OWNERS": CustomerOrder.OWNERS,
        "oem_partners": (db.query(OEMPartner).filter(OEMPartner.active.is_(True))
                        .order_by(OEMPartner.name.asc()).all()),
        "STATUS_COLORS": CustomerOrder.STATUS_COLORS,
        "cancel_reason": cancel_reason,
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

    # Order type classification (Migration 058) - whitelist-validate; default sale.
    # Sale orders require a Customer PO (pipeline gate); loan types (pilot/try_and_buy/
    # demo) carry no PO and instead may set an expected_return loan due date. The
    # client hides/disables the irrelevant fields, but re-validate here - never trust
    # the client to have omitted them.
    order_type = (body.get("order_type") or "sale").strip()
    if order_type not in CustomerOrder.ORDER_TYPES:
        return JSONResponse(status_code=400, content={"error": "Invalid order type"})

    # Build ownership (migration 074, docs/specs/order-owner-split-slice-1.md):
    # whitelist the owner and couple the partner. Validate here and never lean
    # on the CHECK: the IntegrityError catch below reports every integrity
    # failure as a duplicate PO.
    owner = (body.get("owner") or "brand").strip()
    if owner not in CustomerOrder.OWNERS:
        return JSONResponse(status_code=400, content={"error": "Invalid owner"})
    oem_partner_id = None
    if owner == "oem":
        try:
            oem_partner_id = int(body.get("oem_partner_id"))
        except (TypeError, ValueError):
            oem_partner_id = None
        partner = (db.query(OEMPartner)
                   .filter(OEMPartner.id == oem_partner_id, OEMPartner.active.is_(True))
                   .first()) if oem_partner_id else None
        if not partner:
            return JSONResponse(status_code=400, content={
                "error": "Choose an OEM partner for an OEM-owned order"})

    po_number = (body.get("po_number") or "").strip() or None
    expected_return = None
    if order_type == "sale":
        if not po_number:
            return JSONResponse(status_code=400, content={"error": "Customer PO is required for sale orders"})
    else:
        po_number = None  # loans carry no PO regardless of what the client sent
        raw_return = (body.get("expected_return") or "").strip()
        if raw_return:
            try:
                expected_return = date.fromisoformat(raw_return)
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid loan due date, use YYYY-MM-DD"})

    # Only the known pipeline statuses are stored; an unknown string would
    # silently fall into the board's New column.
    _create_status = (body.get("status") or "").strip()
    if _create_status and _create_status not in CustomerOrder.ORDER_STATUSES:
        return JSONResponse(status_code=400, content={"error": "Unknown order status: " + _create_status})

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
        # Code-mediated: cancelled is reachable only through the cancel
        # route (docs/specs/customer-order-cancel.md), never on create.
        status=("new" if _create_status == "cancelled"
                else (_create_status or "new")),  # vocabulary checked above
        sku_requirements=body.get("sku_requirements") or [],
        notes=(body.get("notes") or "").strip() or None,
        is_sensitive=bool(body.get("is_sensitive", False)),
        po_number=po_number,
        default_fulfillment_type=(body.get("default_fulfillment_type") or "").strip() or None,
        order_type=order_type,
        expected_return=expected_return,
        owner=owner,
        oem_partner_id=oem_partner_id,
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
    old_status = order.status
    str_fields = [
        "salesforce_order_id", "salesforce_opp_id", "customer_name", "customer_account",
        "sales_engineer", "deployment_type", "integrator_name", "distributor_name",
        "status", "notes", "pre_site_survey", "post_install_notes",
        "po_number", "default_fulfillment_type",
    ]
    # Cancelled is code-mediated (docs/specs/customer-order-cancel.md): it is
    # entered only through the cancel route, which requires a reason, unlinks
    # the units and writes the audit event. It is also terminal, so a status
    # edit can neither set it nor clear it.
    if "status" in body:
        _new_status = (body["status"] or "").strip()
        # A blank status would store NULL and drop the order off every board;
        # an unknown one would land in the New column. Neither is a status.
        if _new_status not in CustomerOrder.ORDER_STATUSES:
            return JSONResponse(status_code=400, content={
                "error": "Unknown order status: " + (_new_status or "(blank)"),
            })
        if _new_status == "cancelled":
            return JSONResponse(status_code=400, content={
                "error": "Use the Cancel action to cancel an order; it requires a reason",
            })
        if order.status == "cancelled" and _new_status and _new_status != "cancelled":
            return JSONResponse(status_code=409, content={
                "error": "Cancelled is terminal. Create a new order rather than reopening this one",
            })

    for field in str_fields:
        if field in body:
            setattr(order, field, (body[field] or "").strip() or None)

    if "due_date" in body:
        order.due_date = body["due_date"] or None
    if "sales_engineer_id" in body:
        order.sales_engineer_id = body["sales_engineer_id"] or None
    if "sku_requirements" in body:
        # The requirements editor PUTs the full array. Validate shape and
        # normalize every line to the canonical {model, qty, source} —
        # free-text models are allowed (catalog gaps are real), but blank
        # models, non-positive quantities and unknown sources are not.
        raw = body["sku_requirements"] or []
        if not isinstance(raw, list):
            db.rollback()
            return JSONResponse(status_code=400, content={"error": "sku_requirements must be a list"})
        cleaned = []
        for line in raw:
            if not isinstance(line, dict):
                db.rollback()
                return JSONResponse(status_code=400, content={"error": "Each SKU requirement must be an object"})
            model = (line.get("model") or line.get("sku") or "").strip()
            if not model:
                db.rollback()
                return JSONResponse(status_code=400, content={"error": "Each SKU requirement needs a SKU/model"})
            try:
                qty = int(line.get("qty"))
            except (TypeError, ValueError):
                qty = 0
            if not 1 <= qty <= 9999:
                db.rollback()
                return JSONResponse(status_code=400, content={"error": f"Quantity for '{model}' must be between 1 and 9999"})
            source = (line.get("source") or "tbd").strip()
            if source not in ("stock", "oem", "tbd"):
                db.rollback()
                return JSONResponse(status_code=400, content={"error": f"Source for '{model}' must be stock, oem or tbd"})
            cleaned.append({"model": model, "qty": qty, "source": source})
        order.sku_requirements = cleaned
    if "is_sensitive" in body:
        order.is_sensitive = bool(body["is_sensitive"])

    # Order-type coupling, parity with create_order. Only when the full edit form submits
    # an order_type: whitelist it, and couple the PO / loan-due-date invariant. Loans carry
    # no PO (forced null); sale requires one. Never trust the client to have omitted fields.
    if "order_type" in body:
        order_type = (body.get("order_type") or "sale").strip()
        if order_type not in CustomerOrder.ORDER_TYPES:
            db.rollback()
            return JSONResponse(status_code=400, content={"error": "Invalid order type"})
        order.order_type = order_type
        if order_type == "sale":
            if not order.po_number:
                db.rollback()
                return JSONResponse(status_code=400, content={"error": "Customer PO is required for sale orders"})
            order.expected_return = None
        else:
            order.po_number = None
            raw_return = (body.get("expected_return") or "").strip()
            if raw_return:
                try:
                    order.expected_return = date.fromisoformat(raw_return)
                except ValueError:
                    db.rollback()
                    return JSONResponse(status_code=400, content={"error": "Invalid loan due date, use YYYY-MM-DD"})
            else:
                order.expected_return = None

    # Build ownership, parity with create_order (migration 074). The partner is
    # read only when owner is in the body; the edit form always sends both.
    if "owner" in body:
        owner = (body.get("owner") or "brand").strip()
        if owner not in CustomerOrder.OWNERS:
            db.rollback()
            return JSONResponse(status_code=400, content={"error": "Invalid owner"})
        if owner == "oem":
            try:
                new_partner_id = int(body.get("oem_partner_id"))
            except (TypeError, ValueError):
                new_partner_id = None
            partner = (db.query(OEMPartner)
                       .filter(OEMPartner.id == new_partner_id, OEMPartner.active.is_(True))
                       .first()) if new_partner_id else None
            if not partner:
                db.rollback()
                return JSONResponse(status_code=400, content={
                    "error": "Choose an OEM partner for an OEM-owned order"})
            order.owner = owner
            order.oem_partner_id = partner.id
        else:
            order.owner = owner
            order.oem_partner_id = None

    if old_status == "new" and order.status != "new" and order.order_type == "sale" and not order.po_number:
        db.rollback()
        return JSONResponse(status_code=400, content={"error": "Add a Customer PO before advancing this order past Approved PO"})

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

    # Refuse deletion of a cancelled order: cancelled orders are retained as
    # the historical record (docs/specs/customer-order-cancel.md). Hiding the
    # button is not retention, because the route stays reachable by URL and
    # from any stale open tab. Note the asymmetry this closes: the deployment
    # record guard below incidentally protects delivered and installed orders,
    # which usually carry records, while cancelled orders ended early and were
    # the least protected.
    if order.status == "cancelled":
        return JSONResponse(status_code=409, content={
            "error": f"Order {order.order_number} is cancelled and is kept as a "
                     "historical record. Cancelled orders are not deleted.",
        })

    # Refuse while any deployment record exists. Ratified in
    # docs/specs/fulfillment-vendor-direction.md: no route deletes a deployment
    # record directly, and without this guard the CASCADE took the visits and
    # their installation certifications with the order.
    n = db.query(DeploymentRecord).filter(
        DeploymentRecord.customer_order_id == order_id).count()
    if n:
        return JSONResponse(status_code=409, content={
            "error": f"Order {order.order_number} has {n} deployment record(s) - "
                     "remove or complete handling before deleting",
        })

    order_number = order.order_number
    db.delete(order)
    db.commit()
    log_event(db, "order_deleted", request=request, user_id=user.id,
              target_table="customer_orders", target_id=order_id, action="delete",
              details=f"Deleted order {order_number}")
    return JSONResponse(content={"status": "ok"})


@router.post("/api/orders/{order_id}/assign-items")
async def assign_items_to_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Assign inventory items (item_schema) to an order — the fulfillment
    board's Assign panel posts here. Mirrors the C2C acquire invariants,
    generic over category: item-linked DeviceProvisioning row, one still-out
    row per item, PO gate for sale orders. All-or-nothing: any bad item
    rolls the whole batch back.
    """
    body = await request.json()
    item_ids = body.get("item_ids") or []
    if not isinstance(item_ids, list) or not item_ids:
        return JSONResponse(status_code=400, content={"error": "item_ids is required"})

    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Order not found"})
    if order.order_type == "sale" and not order.po_number:
        return JSONResponse(
            status_code=400,
            content={"error": f"Order {order.order_number} has no Customer PO - add one before assigning units"},
        )

    assigned = []
    for raw_id in item_ids:
        try:
            raw_id = int(raw_id)
        except (TypeError, ValueError):
            db.rollback()
            return JSONResponse(status_code=400, content={"error": f"Invalid item id: {raw_id!r}"})
        item = db.query(Item).filter(Item.id == raw_id).first()
        if not item:
            db.rollback()
            return JSONResponse(status_code=404, content={"error": f"Item {raw_id} not found"})
        label = item.item_sn or item.item_name or f"item #{item.id}"
        if locked_ids(db, "items", [item.id]):
            db.rollback()
            return JSONResponse(status_code=409, content={"error": f"{label}: {LOCK_MESSAGE}"})
        if item.item_status != "Ready to Deploy":
            db.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": f"{label} is '{item.item_status}', not Ready to Deploy"},
            )
        still_out = (
            db.query(DeviceProvisioning)
            .filter(
                DeviceProvisioning.item_id == item.id,
                DeviceProvisioning.returned_date.is_(None),
            )
            .first()
        )
        if still_out:
            db.rollback()
            return JSONResponse(status_code=409, content={"error": f"{label} is already assigned to an order"})
        rec = DeviceProvisioning(
            item_id=item.id,
            site_id=None,
            current_stage="acquired",  # label only; stock units have no stage machine
            stages=[],
            fulfillment_type=None,     # NULL = not in the edge-box build pipeline
            assignment_type=("sale" if order.order_type == "sale" else None),
            notes=None,
            customer_order_id=order.id,
            created_by=user.id,
        )
        db.add(rec)
        assigned.append(label)
    db.commit()

    log_event(
        db, "order_items_assigned",
        request=request, user_id=user.id,
        target_table="customer_orders", target_id=order.id,
        action="update",
        details=f"Assigned {len(assigned)} unit(s) to order {order.order_number}: {', '.join(assigned)}",
    )

    return JSONResponse(content={"assigned": len(assigned), "order_number": order.order_number})


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
        if not order.po_number:
            return JSONResponse(status_code=400, content={"error": f"Order {order.order_number} has no Customer PO - add one before linking devices"})
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


@router.post("/api/orders/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Cancel an order (docs/specs/customer-order-cancel.md).

    Terminal: there is no un-cancel. Linked units are HARD-UNLINKED
    (customer_order_id set to NULL); the provisioning rows themselves
    survive as the device history. The unit list is captured in the audit
    event BEFORE unlinking, because afterwards the DB cannot reconstruct
    the tie.
    """
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Order not found"})
    if order.status == "cancelled":
        return JSONResponse(status_code=409, content={
            "error": f"Order {order.order_number} is already cancelled",
        })

    body = await request.json()
    reason = (body.get("reason") or "").strip()
    if not reason:
        return JSONResponse(status_code=400, content={
            "error": "A reason is required to cancel an order",
        })

    # Rows are found by customer_order_id: every unit on the order, whatever
    # its item.
    units = db.query(DeviceProvisioning).filter(
        DeviceProvisioning.customer_order_id == order_id).all()
    unit_list = [{
        "provisioning_id": u.id,
        "item_id": u.item_id,
    } for u in units]

    who = user.display_name or user.username
    prior_status = order.status
    for u in units:
        u.customer_order_id = None
    order.status = "cancelled"
    # Commit before log_event: log_event returns WITHOUT committing for svc_
    # accounts, and neither the unlink nor the status change may depend on it.
    db.commit()

    log_event(db, "order_cancelled", request=request, user_id=user.id,
              target_table="customer_orders", target_id=order_id, action="update",
              new_values={
                  "reason": reason,
                  "who": who,
                  "prior_status": prior_status,
                  "units": unit_list,
              },
              details=f"Cancelled order {order.order_number}, "
                      f"{len(unit_list)} unit(s) unlinked")
    return JSONResponse(content={"status": "ok", "units_unlinked": len(unit_list)})


@router.post("/api/oem-partners/")
async def create_oem_partner(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Create an OEM build partner inline from the order modals.

    Slice 1 of docs/specs/order-owner-split-slice-1.md. There is no admin
    page, no partner list route (the page context carries the roster), and
    no edit or deactivate route yet.
    """
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Partner name is required"})
    if len(name) > 128:
        return JSONResponse(status_code=400, content={
            "error": "Partner name is too long, 128 characters maximum"})

    existing = db.query(OEMPartner).filter(
        sqlfunc.lower(OEMPartner.name) == name.lower()).first()
    if existing:
        return JSONResponse(status_code=409, content={"error": "That partner already exists"})

    partner = OEMPartner(name=name, active=True)
    db.add(partner)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=409, content={"error": "That partner already exists"})
    db.refresh(partner)

    log_event(db, "oem_partner_created", request=request, user_id=user.id,
              target_table="oem_partners", target_id=partner.id, action="create",
              details=f"Created OEM partner {partner.name}")

    return JSONResponse(content={"status": "ok", "id": partner.id, "name": partner.name})
