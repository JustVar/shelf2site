"""C2C camera certification — a separate, lighter fulfillment flow.

C2C cameras (category ``camera_c2c``) are the company's Cloud2 camera product.
Unlike edge boxes there is no build and no parts: acquire the cameras for an
order, then certify each one — powered on, firmware verified, connected to its
virtual site via QR, and registered.

Cert-subject grain is option D (docs/specs/c2c-catalog-and-accessories.md
section 7): the camera is a unified-inventory row (item_schema.items) and the
provisioning row links to it via the item_id FK (migration 056). This is
deliberately its own route surface; the edge-box fulfillment/cert flow is
hardcoded ``device_table == "edge_boxes"`` in ~10 guards, so C2C does NOT ride
those routes, and Item is NOT registered in the shared TABLE_MODELS.

Routes:
  * GET  /fulfillment/c2c                              read-only overview (viewer)
  * POST /fulfillment/c2c/acquire                      provision a cam to an order (manager)
  * POST /fulfillment/c2c/{provisioning_id}/certify    checklist + evidence, all-pass gate (manager)

See docs/specs/c2c-camera-certification.md and
docs/specs/c2c-c1-discovery-handoff.md.
"""

import io
import uuid
from datetime import date, datetime
from pathlib import Path

import fitz

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_provisioning_manager, require_provisioning_viewer
from ..config import settings
from ..localtime import fmt_local, local_today, register
from ..database import get_db
from ..delete_requests import LOCK_MESSAGE, locked_ids
from ..models import (
    C2CCertification, C2CCertificationFile, CustomerOrder, DeviceProvisioning, Item, ItemPartNumber, Site, User,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


# ---------------------------------------------------------------------------
# Read-only C2C board — data feeds (option D, C2 slice 4 / Part A)
# ---------------------------------------------------------------------------

def _c2c_board_data(db: Session) -> dict:
    """Assemble the C2C board data (option D).

    - needed: sum of qty on an order sku_requirements line whose model is a
      camera_c2c catalog SKU (join to part_numbers.item_category).
    - acquired: device_provisioning rows with item_id set (the option-D link),
      split certified vs pending by the linked c2c_certification.status.
    - available: item_schema.items camera_c2c not linked to ANY provisioning row
      (net on has-a-provisioning per the section-9 decision, NOT is_complete).
    - order_complete: acquired == needed (> 0) and every acquired cam certified.

    Live edge case, surfaced not clamped: an order can be needed=0 with
    acquired>0 (a cam linked to an order that has no camera_c2c requirement line)
    -> reported as over_acquired.
    """
    # Catalog SKUs that count as C2C cameras (today: just C2C-GEN1-4MP).
    c2c_skus = {
        sku for (sku,) in db.query(ItemPartNumber.brand_sku)
        .filter(ItemPartNumber.item_category == "camera_c2c").all()
    }

    # Latest cert EVENT per provisioning row (append-only log): status is the newest
    # event's status. id is monotonic, so max(id) = the latest event.
    latest_cert = (
        db.query(
            C2CCertification.device_provisioning_id.label("dpid"),
            func.max(C2CCertification.id).label("cert_id"),
        )
        .group_by(C2CCertification.device_provisioning_id)
        .subquery()
    )

    # All acquired C2C cams (item_id-linked provisioning rows) + cert + order context.
    cam_records = (
        db.query(
            DeviceProvisioning.id.label("provisioning_id"),
            DeviceProvisioning.item_id,
            DeviceProvisioning.customer_order_id,
            Item.item_name, Item.item_sn, Item.brand_sku,
            CustomerOrder.order_number, CustomerOrder.customer_name,
            C2CCertification.status.label("cert_status"),
            C2CCertification.certified_by, C2CCertification.certified_at,
            C2CCertification.checklist, C2CCertification.firmware_evidence,
            C2CCertification.notes,
        )
        .join(Item, Item.id == DeviceProvisioning.item_id)
        .outerjoin(CustomerOrder, CustomerOrder.id == DeviceProvisioning.customer_order_id)
        .outerjoin(latest_cert, latest_cert.c.dpid == DeviceProvisioning.id)
        .outerjoin(C2CCertification, C2CCertification.id == latest_cert.c.cert_id)
        .filter(DeviceProvisioning.item_id.isnot(None))
        .order_by(DeviceProvisioning.id)
        .all()
    )

    pending_cams, certified_cams = [], []
    acquired_by_order, certified_by_order = {}, {}
    for r in cam_records:
        cam = {
            "provisioning_id": r.provisioning_id,
            "item_id": r.item_id,
            "item_name": r.item_name,
            "item_sn": r.item_sn,
            "brand_sku": r.brand_sku,
            "order_id": r.customer_order_id,
            "order_number": r.order_number,
            "customer_name": r.customer_name,
            "cert_status": r.cert_status or "pending",
            "certified_by": r.certified_by or None,
            "certified_at": r.certified_at,
            "checklist": r.checklist or {},
            "firmware_evidence": r.firmware_evidence or {},
            "notes": r.notes or "",
        }
        oid = r.customer_order_id
        acquired_by_order[oid] = acquired_by_order.get(oid, 0) + 1
        if r.cert_status == "certified":
            certified_cams.append(cam)
            certified_by_order[oid] = certified_by_order.get(oid, 0) + 1
        else:
            pending_cams.append(cam)

    # Available (unlinked) camera_c2c inventory. A cam is "linked" (unavailable)
    # only while it has at least one STILL-OUT provisioning row (returned_date
    # IS NULL). A cam whose rows are ALL returned drops out and is assignable
    # again (return-as-ending). Sale cams never get a returned_date, so they
    # stay linked for life.
    linked_item_ids = {
        iid for (iid,) in db.query(DeviceProvisioning.item_id)
        .filter(
            DeviceProvisioning.item_id.isnot(None),
            DeviceProvisioning.returned_date.is_(None),
        ).distinct().all()
    }
    avail_q = db.query(Item).filter(Item.item_category == "camera_c2c")
    if linked_item_ids:
        avail_q = avail_q.filter(~Item.id.in_(linked_item_ids))
    available_items = [
        {"item_id": i.id, "item_name": i.item_name, "item_sn": i.item_sn,
         "brand_sku": i.brand_sku}
        for i in avail_q.order_by(Item.id).all()
    ]

    # Per-order rollup: any order with a camera_c2c need OR an acquired C2C cam.
    order_rollup = []
    total_needed = 0
    for o in db.query(CustomerOrder).order_by(CustomerOrder.id).all():
        need = sum(int(line.get("qty") or 0) for line in (o.sku_requirements or [])
                   if line.get("model") in c2c_skus)
        acq = acquired_by_order.get(o.id, 0)
        if o.status == "cancelled":
            # Ended order: no C2C work remains against it
            # (docs/specs/customer-order-cancel.md).
            continue
        if need == 0 and acq == 0:
            continue
        total_needed += need
        cert = certified_by_order.get(o.id, 0)
        order_rollup.append({
            "order_id": o.id,
            "order_number": o.order_number,
            "customer_name": o.customer_name,
            "needed": need,
            "acquired": acq,
            "certified": cert,
            "pending": acq - cert,
            "shortfall": max(need - acq, 0),
            "over_acquired": max(acq - need, 0),
            "order_complete": need > 0 and acq == need and cert == acq,
            "order_type": o.order_type,
        })

    # Per-cam pre-fill map (keyed by provisioning_id as a string, for the JS map)
    # so the certify modal opens on current stored state, not a blank form.
    cam_cert_map = {
        str(c["provisioning_id"]): {
            "checklist": c["checklist"],
            "firmware_evidence": c["firmware_evidence"],
            "notes": c["notes"],
            "name": c["item_name"],
            "serial": c["item_sn"],
            "sku": c["brand_sku"],
            "order_number": c["order_number"],
        }
        for c in pending_cams + certified_cams
    }

    return {
        "metrics": {
            "needed": total_needed,
            "acquired": len(cam_records),
            "certified": len(certified_cams),
            "pending": len(pending_cams),
            "available": len(available_items),
        },
        "pending_cams": pending_cams,
        "certified_cams": certified_cams,
        "orders": order_rollup,
        "available_items": available_items,
        "cam_cert_map": cam_cert_map,
        # Orders with an unmet C2C need (needed > acquired) - the acquire panel
        # order picker lists only these so the over-acquire block never dead-ends.
        "acquirable_orders": [o for o in order_rollup if o["shortfall"] > 0],
    }


_LOAN_TYPES = ("pilot", "try_and_buy", "demo")


def _pilots_due_back(db: Session) -> dict:
    """Loan-order return rollup (Migration 058). Sale orders never appear; fully-returned
    orders drop off. Status from returned_date + expected_return + today. Backs the
    Pilots Due Back list page and the dashboard count. Derived, nothing stored.

    Covers ANY item-linked loaner unit (C2C cams, edge boxes assigned from the
    fulfillment Assign panel — anything with item_id set). Legacy edge-box
    provisioning rows (item_id NULL, pre-items pipeline) never join here;
    that exclusion goes away with the legacy tables, not with a filter."""
    today = local_today()
    rows = (
        db.query(
            DeviceProvisioning.id.label("provisioning_id"),
            DeviceProvisioning.returned_date,
            Item.item_name, Item.item_sn,
            CustomerOrder.id.label("order_id"),
            CustomerOrder.order_number, CustomerOrder.customer_name,
            CustomerOrder.order_type, CustomerOrder.expected_return,
        )
        .join(Item, Item.id == DeviceProvisioning.item_id)
        .join(CustomerOrder, CustomerOrder.id == DeviceProvisioning.customer_order_id)
        .filter(
            DeviceProvisioning.item_id.isnot(None),
            CustomerOrder.order_type.in_(_LOAN_TYPES),
        )
        .order_by(DeviceProvisioning.id)
        .all()
    )
    by_order = {}
    for r in rows:
        o = by_order.setdefault(r.order_id, {
            "order_id": r.order_id, "order_number": r.order_number,
            "customer_name": r.customer_name, "order_type": r.order_type,
            "expected_return": r.expected_return,
            "acquired": 0, "returned": 0, "still_out": 0, "status": None, "cams": [],
        })
        o["acquired"] += 1
        if r.returned_date is not None:
            o["returned"] += 1
        o["cams"].append({
            "provisioning_id": r.provisioning_id,
            "item_name": r.item_name, "item_sn": r.item_sn,
            "returned_date": r.returned_date,
        })

    orders = []
    counts = {"overdue": 0, "due_soon": 0, "on_loan": 0}
    for o in by_order.values():
        o["still_out"] = o["acquired"] - o["returned"]
        if o["still_out"] == 0:
            continue  # fully returned -> drops off the surface
        er = o["expected_return"]
        if er is None:
            o["status"] = "on-loan"
        else:
            days = (er - today).days
            if days < 0:
                o["status"] = "overdue"
            elif days <= 7:
                o["status"] = "due-soon"
            else:
                o["status"] = "on-loan"
        counts[o["status"].replace("-", "_")] += 1
        orders.append(o)

    rank = {"overdue": 0, "due-soon": 1, "on-loan": 2}
    orders.sort(key=lambda x: (rank[x["status"]], x["expected_return"] or date.max))
    return {
        "orders": orders,
        "counts": counts,
        "total_due_back": len(orders),
        "actionable": counts["overdue"] + counts["due_soon"],
    }


@router.get("/fulfillment/pilots-due-back", response_class=HTMLResponse)
def pilots_due_back_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Loaner units still out, grouped by order (read-only)."""
    ctx = _pilots_due_back(db)
    ctx["request"] = request
    ctx["user"] = user
    ctx["order_types"] = CustomerOrder.ORDER_TYPES
    return templates.TemplateResponse("pilots_due_back.html", ctx)


@router.get("/fulfillment/c2c", response_class=HTMLResponse)
def c2c_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """C2C camera fulfillment/cert overview (read-only)."""
    ctx = _c2c_board_data(db)
    ctx["request"] = request
    ctx["user"] = user
    ctx["order_types"] = CustomerOrder.ORDER_TYPES
    return templates.TemplateResponse("c2c.html", ctx)


# ---------------------------------------------------------------------------
# Cam acquisition path — option D (C2 slice)
# ---------------------------------------------------------------------------
# Provision a C2C camera to a customer order. Under option D (see
# docs/specs/c2c-catalog-and-accessories.md section 7) the camera is a unified
# inventory row (item_schema.items, category camera_c2c), NOT a legacy
# public.cameras row. The provisioning row links to it via the item_id FK
# (migration 056); the per-cam cert (C2) still keys on the provisioning row.
#
# device_table / device_id are NOT NULL on the shared polymorphic table, so an
# items-backed row carries the sentinel device_table="items", device_id=<items.id>
# while item_id is the real, integrity-backed link. Do NOT register Item in the
# shared TABLE_MODELS (it pollutes ~15 legacy consumers). The provisioning
# resolvers (orders.py, provisioning.py, sites.py) all .get(device_table) and
# guard None, so an "items" row shows a plain "items #<id>" label there until an
# item_id-aware name branch is added — non-breaking, cosmetic only.
#
# Cams do not ride the edge-box stage pipeline, so:
#   * stages=[]           — nullable=False; [] is guarded-falsy in every stages
#                           read (_get_stage_label / `rec.stages or []`).
#   * fulfillment_type=NULL — not in the (edge-box) fulfillment pipeline.
#   * current_stage="acquired" — a display label only; no stage machine for cams.

@router.post("/fulfillment/c2c/acquire")
async def c2c_acquire(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Provision a C2C camera (item_schema.items, camera_c2c) to a customer order."""
    body = await request.json()
    device_id = body.get("device_id")
    customer_order_id = body.get("customer_order_id")
    site_id = body.get("site_id")
    notes = (body.get("notes") or "").strip()
    assignment_type = (body.get("assignment_type") or "sale").strip()

    # Camera is required, must exist in item_schema.items, and be a C2C category.
    if not device_id:
        return JSONResponse(status_code=400, content={"error": "device_id (camera) is required"})
    camera = db.query(Item).filter(Item.id == int(device_id)).first()
    if not camera:
        return JSONResponse(status_code=404, content={"error": "Camera not found in inventory (item_schema.items)"})
    if camera.item_category not in ("camera_c2c",):
        return JSONResponse(
            status_code=400,
            content={"error": f"Item {device_id} is category '{camera.item_category}', not a C2C camera (camera_c2c)"},
        )

    if locked_ids(db, "items", [camera.id]):
        return JSONResponse(status_code=409, content={"error": LOCK_MESSAGE})

    if str(camera.item_status) == "Decommissioned":
        # Code-mediated (docs/specs/item-decommission.md): reactivate first.
        return JSONResponse(
            status_code=409,
            content={"error": f"Item {device_id} is decommissioned. Reactivate it before acquiring it onto an order."},
        )

    # Classification is driven by the chosen order's order_type (Migration 058), NOT by a
    # client-sent assignment_type. The body value defaults to "sale" and is only sanity-
    # checked against the vocabulary here; the row's assignment_type is derived from
    # order.order_type below (loans carry no PO and are not blocked).
    if assignment_type not in DeviceProvisioning.ASSIGNMENT_TYPES:
        return JSONResponse(status_code=400, content={"error": f"Invalid assignment_type: {assignment_type}"})

    # Order is required — C2C acquisition provisions cams *to an order*.
    if not customer_order_id:
        return JSONResponse(status_code=400, content={"error": "customer_order_id is required"})
    order = db.query(CustomerOrder).filter(CustomerOrder.id == int(customer_order_id)).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Customer order not found"})
    # PO required only for SALE orders (Migration 058: order_type is the classification
    # source; loans pilot/try_and_buy/demo carry no PO). Mirrors the over-acquire sale-gate.
    if order.order_type == "sale" and not order.po_number:
        return JSONResponse(
            status_code=400,
            content={"error": f"Order {order.order_number} has no Customer PO - add one before assigning cameras"},
        )

    # Over-acquire block - only SALE orders carry a needed quota to enforce. The
    # order's order_type (Migration 058) is the classification source; non-sale
    # (loan) types have no quota and skip this. Gating here is also the spike-
    # identified sale-gate fix - the block is otherwise unconditional and would
    # error / spuriously 409 a loan acquire.
    if order.order_type == "sale":
        c2c_skus = {
            sku for (sku,) in db.query(ItemPartNumber.brand_sku)
            .filter(ItemPartNumber.item_category == "camera_c2c").all()
        }
        needed = sum(int(line.get("qty") or 0) for line in (order.sku_requirements or [])
                     if line.get("model") in c2c_skus)
        acquired = (
            db.query(DeviceProvisioning)
            .filter(DeviceProvisioning.customer_order_id == order.id,
                    DeviceProvisioning.item_id.isnot(None))
            .count()
        )
        if acquired >= needed:
            return JSONResponse(
                status_code=409,
                content={"error": f"Order {order.order_number} already has all needed C2C cameras assigned ({acquired} of {needed})."},
            )

    # Validate site if provided. Deploying places the camera at a customer
    # site, so reject other site types (they would drop it off the map).
    if site_id:
        site = db.query(Site).filter(Site.id == int(site_id)).first()
        if not site:
            return JSONResponse(status_code=404, content={"error": "Site not found"})
        if site.site_type != "customer_site":
            return JSONResponse(status_code=400, content={"error": "Cameras deploy to customer sites only"})

    # One STILL-OUT provisioning per camera, keyed on the item_id link (option D).
    # Under option D a C2C row keeps is_complete=False forever, so the old
    # is_complete gate blocked EVERY cam that was ever acquired - including
    # returned ones. Gate on returned_date instead: only a still-out row
    # (returned_date IS NULL) blocks re-acquire; a returned cam passes and is
    # re-assigned via the unchanged acquire path (new row, fresh cert, old row
    # preserved).
    existing = (
        db.query(DeviceProvisioning)
        .filter(
            DeviceProvisioning.item_id == int(device_id),
            DeviceProvisioning.returned_date.is_(None),
        )
        .first()
    )
    if existing:
        return JSONResponse(status_code=409, content={"error": "Camera already has active provisioning"})

    cam_name = camera.item_name or camera.item_model or f"Camera #{camera.id}"

    rec = DeviceProvisioning(
        device_table="items",       # sentinel; the real link is item_id below
        device_id=int(device_id),   # NOT NULL filler, mirrors item_id
        item_id=int(device_id),     # integrity-backed FK to item_schema.items (option D)
        site_id=int(site_id) if site_id else None,
        current_stage="acquired",   # label only; cams have no stage machine
        stages=[],                  # nullable=False; guarded-falsy everywhere
        fulfillment_type=None,      # NULL = not in the edge-box fulfillment pipeline
        # Classification retired to order.order_type (Migration 058); this column is
        # vestigial (no readers). Stamp "sale" for sale orders, NULL for loans (try_and_buy
        # is not in ASSIGNMENT_TYPES, so order_type is never derived into it directly).
        assignment_type=("sale" if order.order_type == "sale" else None),
        notes=notes or None,
        customer_order_id=order.id,
        created_by=user.id,
    )
    db.add(rec)
    # Lifecycle (Migration 063): deploying a unit sets its place to the
    # customer site, so a geocoded site pins the camera on the map.
    if site_id:
        camera.location_id = int(site_id)
        camera.item_status = "Deployed"  # place and status agree by construction
    db.commit()
    db.refresh(rec)

    log_event(
        db, "c2c_camera_acquired",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="create",
        details=f"Assigned C2C camera item #{device_id} ({cam_name}) to order {order.order_number} [{order.order_type}]",
    )

    return JSONResponse(content={
        "status": "acquired",
        "id": rec.id,
        "camera_name": cam_name,
    })

# ---------------------------------------------------------------------------
# Certify write path — option D (C2 slice 3)
# ---------------------------------------------------------------------------
# Per-camera certification. Submit the four-item checklist + firmware evidence;
# the cam certifies only when ALL four checklist items pass (all-pass gate),
# otherwise it stays pending. One c2c_certification row per provisioning row
# (get-or-create, updated on each submit). Certification is tracked by
# status="certified" on the cert row; it deliberately does NOT touch the
# provisioning is_complete flag (that means "provisioning closed", a different
# lifecycle state).
#
# The four checklist items are manual booleans. qr_site_connected is a manual
# confirmation for now; whether it becomes a real virtual-site API check is
# parked (see docs/specs/c2c-camera-certification.md) - a later enhancement.

CHECKLIST_ITEMS = ("powered_on", "firmware_verified", "qr_site_connected", "registered")


@router.post("/fulfillment/c2c/{provisioning_id}/certify")
async def c2c_certify(
    provisioning_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Submit the C2C checklist + firmware evidence for an acquired cam; gate to certified."""
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == provisioning_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})
    # Must be an option-D C2C cam (linked to item_schema.items via item_id).
    if prov.item_id is None:
        return JSONResponse(status_code=400, content={"error": "Not a C2C camera provisioning (no item_id link)"})
    item = db.query(Item).filter(Item.id == prov.item_id).first()
    if not item:
        return JSONResponse(status_code=404, content={"error": "Linked camera item not found"})

    body = await request.json()
    raw = body.get("checklist") or {}
    checklist = {k: bool(raw.get(k)) for k in CHECKLIST_ITEMS}
    all_pass = all(checklist[k] for k in CHECKLIST_ITEMS)

    # Append-only cert log: attach to the current mutable PENDING draft (shared helper,
    # also used by the file-upload endpoint). Certified/cancelled events are frozen; a
    # non-pending latest event starts a fresh draft.
    cert, created = _get_or_create_pending_c2c_draft(db, provisioning_id, user.display_name)

    # Whole-object assignment for JSONB (SQLAlchemy does not track in-place mutation).
    cert.checklist = checklist
    # Guard firmware_evidence against destructive omission: only overwrite when the
    # key is present, so a submit that omits it leaves stored evidence untouched.
    # Present-but-null/empty is honored as an explicit clear. Whole-object assign.
    if "firmware_evidence" in body:
        cert.firmware_evidence = body["firmware_evidence"]
    # Same present-key-wins guard for notes (a modal field): omit -> untouched,
    # present-but-empty -> explicit clear.
    if "notes" in body:
        cert.notes = (body.get("notes") or "").strip() or None
    cert.camera_serial_snapshot = item.item_sn

    if all_pass:
        cert.status = "certified"
        cert.certified_by = user.display_name
        cert.certified_at = datetime.utcnow()
    else:
        cert.status = "pending"
        cert.certified_by = None
        cert.certified_at = None

    # is_complete stays False (decided): certification is tracked by cert.status,
    # not the provisioning lifecycle flag. Do NOT touch prov.is_complete here.

    db.commit()
    db.refresh(cert)

    if all_pass:
        # Composite PDF for THIS finalized event (5c). AFTER commit so cert.id exists and a
        # render failure cannot roll back the certification. Wrapped so a composite failure
        # never 500s the certify (FailGate) - the cam stays certified; the composite is
        # regenerable and the failure is audited.
        try:
            _generate_c2c_composite(db, cert, item, prov)
        except Exception:
            db.rollback()
            log_event(
                db, "c2c_composite_failed", request=request, user_id=user.id,
                target_table="c2c_certification", target_id=cert.id, action="update",
                details=f"Composite PDF generation failed for C2C cert #{cert.id}",
            )

    passed = sum(1 for k in CHECKLIST_ITEMS if checklist[k])
    log_event(
        db, "c2c_camera_certified" if all_pass else "c2c_camera_cert_updated",
        request=request, user_id=user.id,
        target_table="c2c_certification", target_id=cert.id,
        action="create" if created else "update",
        details=f"C2C cert {cert.status} for cam item #{prov.item_id} "
                f"({item.item_name or item.item_model}) checklist {passed}/4",
    )

    return JSONResponse(content={
        "status": cert.status,
        "cert_id": cert.id,
        "all_pass": all_pass,
        "checklist": checklist,
    })


@router.post("/fulfillment/c2c/{provisioning_id}/return")
async def c2c_mark_returned(
    provisioning_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Mark ONE loaner unit returned (C2C cam or any item-linked unit). Stamps
    returned_date (default today, editable via body). Unit stays linked;
    is_complete is NOT touched."""
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == provisioning_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"error": "Provisioning record not found"})
    if prov.item_id is None:
        # Legacy edge-box rows have no returned_date semantics — their pipeline
        # manages state separately. Return-all already filtered these; the
        # single-unit endpoint now matches it.
        return JSONResponse(status_code=400, content={"error": "Mark returned applies to item-linked units only"})
    order = prov.customer_order
    if order is None or order.order_type not in _LOAN_TYPES:
        return JSONResponse(status_code=400, content={"error": "Mark returned applies to loan orders only (pilot, try_and_buy, demo)"})
    body = await request.json()
    if body.get("returned_date"):
        try:
            new_date = date.fromisoformat(str(body["returned_date"]).strip())
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"error": "returned_date must be YYYY-MM-DD"})
    else:
        new_date = local_today()
    prov.returned_date = new_date  # is_complete intentionally left untouched
    db.commit()
    log_event(
        db, "c2c_camera_returned",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=prov.id,
        action="update",
        details=f"Marked C2C cam prov #{prov.id} returned {new_date} for order {order.order_number} [{order.order_type}]",
    )
    return JSONResponse(content={"status": "returned", "provisioning_id": prov.id, "returned_date": new_date.isoformat()})


@router.post("/fulfillment/c2c/order/{order_id}/return-all")
async def c2c_mark_all_returned(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Mark all STILL-OUT loaner units of one order returned (today). Already-returned
    units keep their date. is_complete is NOT touched."""
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Customer order not found"})
    if order.order_type not in _LOAN_TYPES:
        return JSONResponse(status_code=400, content={"error": "Mark returned applies to loan orders only (pilot, try_and_buy, demo)"})
    today = local_today()
    still_out = (
        db.query(DeviceProvisioning)
        .filter(
            DeviceProvisioning.customer_order_id == order.id,
            DeviceProvisioning.item_id.isnot(None),
            DeviceProvisioning.returned_date.is_(None),
        )
        .all()
    )
    for p in still_out:
        p.returned_date = today  # is_complete intentionally left untouched
    db.commit()
    log_event(
        db, "c2c_order_cams_returned",
        request=request, user_id=user.id,
        target_table="customer_orders", target_id=order.id,
        action="update",
        details=f"Marked {len(still_out)} C2C cam(s) returned {today} for order {order.order_number} [{order.order_type}]",
    )
    return JSONResponse(content={"status": "returned", "order_id": order.id, "count": len(still_out)})


# ============================================================================
# C2C cert source files (5b): bytes on disk under C2C_CERT_UPLOAD_DIR/<serial>/,
# metadata in c2c_certification_files. Files attach to the current mutable PENDING
# draft (append-only: certified/cancelled events are frozen). Mirrors build-cert.
# ============================================================================
_C2C_FILE_TYPES = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
_C2C_FILE_EXTS = {".pdf", ".png", ".jpg", ".jpeg"}
_C2C_FILE_MAX = 5 * 1024 * 1024  # 5 MB


def _get_or_create_pending_c2c_draft(db, provisioning_id, created_by):
    """Current mutable PENDING cert draft for a provisioning row, or a fresh one. Append-only:
    a certified/cancelled latest event is frozen, so a non-pending (or missing) latest starts a
    new draft. Returns (cert, created)."""
    cert = (
        db.query(C2CCertification)
        .filter(C2CCertification.device_provisioning_id == provisioning_id)
        .order_by(C2CCertification.id.desc())
        .first()
    )
    created = cert is None or cert.status != "pending"
    if created:
        cert = C2CCertification(device_provisioning_id=provisioning_id, created_by=created_by)
        db.add(cert)
    return cert, created


def _c2c_file_path(rec):
    """On-disk path for a cert-file row from its camera_serial + stored_name."""
    return Path(settings.C2C_CERT_UPLOAD_DIR) / (rec.camera_serial or "unknown") / rec.stored_name


@router.get("/fulfillment/c2c/{provisioning_id}/cert-files")
def c2c_cert_files(
    provisioning_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Files (source + composite) on the LATEST cert event of a provisioning row. 'deletable'
    marks source files on a still-pending (mutable) draft."""
    latest = (
        db.query(C2CCertification)
        .filter(C2CCertification.device_provisioning_id == provisioning_id)
        .order_by(C2CCertification.id.desc())
        .first()
    )
    if not latest:
        return {"cert_status": None, "files": []}
    files = (
        db.query(C2CCertificationFile)
        .filter(C2CCertificationFile.c2c_certification_id == latest.id)
        .order_by(C2CCertificationFile.uploaded_at.asc(), C2CCertificationFile.id.asc())
        .all()
    )
    return {
        "cert_status": latest.status,
        "cancel_reason": latest.cancel_reason if latest.status == "cancelled" else None,
        "files": [
            {"id": f.id, "original_name": f.original_name, "kind": f.kind,
             "deletable": f.kind == "source" and latest.status == "pending"}
            for f in files
        ],
    }


@router.post("/fulfillment/c2c/{provisioning_id}/files")
async def c2c_upload_cert_file(
    provisioning_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Upload a source file (PDF/PNG/JPG) onto the current PENDING cert draft. Bytes on disk."""
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == provisioning_id).first()
    if not prov:
        return JSONResponse(status_code=404, content={"detail": "Provisioning record not found"})
    if prov.item_id is None:
        return JSONResponse(status_code=400, content={"detail": "Not a C2C camera provisioning (no item_id link)"})
    item = db.query(Item).filter(Item.id == prov.item_id).first()
    if not item:
        return JSONResponse(status_code=404, content={"detail": "Linked camera item not found"})

    ctype = (file.content_type or "").lower()
    ext = Path(file.filename or "").suffix.lower()
    if ctype not in _C2C_FILE_TYPES or ext not in _C2C_FILE_EXTS:
        return JSONResponse(status_code=400, content={"detail": "Allowed file types: PDF, PNG, JPG"})
    content = await file.read()
    if len(content) > _C2C_FILE_MAX:
        return JSONResponse(status_code=413, content={"detail": "File exceeds 5 MB limit"})
    if len(content) == 0:
        return JSONResponse(status_code=400, content={"detail": "Empty file"})

    cert, _ = _get_or_create_pending_c2c_draft(db, provisioning_id, user.display_name)
    if cert.camera_serial_snapshot is None:
        cert.camera_serial_snapshot = item.item_sn
    db.flush()  # assign cert.id for the child FK

    serial = cert.camera_serial_snapshot or item.item_sn or "unknown"
    serial_dir = Path(settings.C2C_CERT_UPLOAD_DIR) / serial
    serial_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{_C2C_FILE_TYPES[ctype]}"
    with open(serial_dir / stored_name, "wb") as fh:
        fh.write(content)
    rec = C2CCertificationFile(
        c2c_certification_id=cert.id, camera_serial=serial, kind="source",
        original_name=(file.filename or stored_name), stored_name=stored_name,
        content_type=ctype, size_bytes=len(content), uploaded_by=user.display_name,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    log_event(
        db, "c2c_cert_file_uploaded", request=request, user_id=user.id,
        target_table="c2c_certification_files", target_id=rec.id, action="create",
        details=f"Uploaded {rec.original_name} to C2C cert draft #{cert.id} (prov #{provisioning_id})",
    )
    return {"ok": True, "file_id": rec.id, "original_name": rec.original_name}


@router.get("/fulfillment/c2c/files/{file_id}")
def c2c_serve_cert_file(
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """Stream a cert file (source or composite) from disk."""
    rec = db.query(C2CCertificationFile).filter(C2CCertificationFile.id == file_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "File not found"})
    path = _c2c_file_path(rec)
    if not path.exists():
        return JSONResponse(status_code=404, content={"detail": "File missing on disk"})
    return FileResponse(
        path=str(path), filename=rec.original_name,
        media_type=rec.content_type or "application/octet-stream",
        content_disposition_type="inline",
    )


@router.delete("/fulfillment/c2c/files/{file_id}")
def c2c_delete_cert_file(
    file_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Delete a SOURCE file on a still-pending (mutable) draft. Composite files, and any file on
    a frozen certified/cancelled event, cannot be deleted (append-only)."""
    rec = db.query(C2CCertificationFile).filter(C2CCertificationFile.id == file_id).first()
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "File not found"})
    parent = db.query(C2CCertification).filter(C2CCertification.id == rec.c2c_certification_id).first()
    if rec.kind != "source" or (parent is not None and parent.status != "pending"):
        return JSONResponse(status_code=409, content={"detail": "Only source files on a pending draft can be deleted"})
    cert_id = rec.c2c_certification_id
    _c2c_file_path(rec).unlink(missing_ok=True)
    db.delete(rec)
    db.commit()
    log_event(
        db, "c2c_cert_file_deleted", request=request, user_id=user.id,
        target_table="c2c_certification_files", target_id=file_id, action="delete",
        details=f"Deleted cert source file #{file_id} from draft #{cert_id}",
    )
    return {"ok": True}


# ============================================================================
# C2C composite cert PDF (5c): summary cover + this event's source files merged.
# Mirrors build-cert's _build_cert_report_pdf (font tokens hebo/helv verbatim; per-file
# try/except -> red placeholder). Only kind='source' merged (never a prior composite).
# ============================================================================
_C2C_CHECKLIST_LABELS = {
    "powered_on": "Powered on", "firmware_verified": "Firmware verified",
    "qr_site_connected": "Connects to virtual site (QR)", "registered": "Registered",
}


def _build_c2c_composite_pdf(db, cert, item, prov):
    """Composite PDF bytes: a summary page + this cert event's kind='source' files merged."""
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
        page.insert_text((margin, y), str(text), fontsize=size, fontname=font, color=color)
        y += dy

    def gap(dy=10):
        nonlocal y
        y += dy

    serial = cert.camera_serial_snapshot or (item.item_sn if item else None) or "unknown"
    when = fmt_local(cert.certified_at, "%Y-%m-%d %H:%M %Z") or "-"
    line("C2C Camera Certification", size=18, dy=30, bold=True)
    line(f"Camera serial: {serial}", bold=True)
    line(f"Model / SKU: {(item.item_model if item else '') or ''}  {(item.brand_sku if item else '') or ''}")
    line(f"Status: {cert.status}", bold=True,
         color=((0, 0.5, 0.15) if cert.status == "certified" else (0.6, 0.4, 0)))
    line(f"Certified by: {cert.certified_by or '-'}    Date: {when}")
    gap()
    line("Checklist", size=13, dy=22, bold=True)
    cl = cert.checklist or {}
    for k in CHECKLIST_ITEMS:
        mark = "[x]" if cl.get(k) else "[ ]"
        line(f"  {mark} {_C2C_CHECKLIST_LABELS.get(k, k)}")
    gap()
    fw = cert.firmware_evidence or {}
    if fw:
        line("Firmware evidence", size=13, dy=22, bold=True)
        for fk in ("version", "license", "plugins"):
            if fw.get(fk) is not None:
                val = fw[fk]
                if isinstance(val, list):
                    val = ", ".join(str(x) for x in val)
                line(f"  {fk}: {val}")
        gap()
    if cert.notes:
        line("Notes", size=13, dy=22, bold=True)
        line(f"  {cert.notes}")

    files = (
        db.query(C2CCertificationFile)
        .filter(C2CCertificationFile.c2c_certification_id == cert.id)
        .filter(C2CCertificationFile.kind == "source")
        .order_by(C2CCertificationFile.uploaded_at.asc(), C2CCertificationFile.id.asc())
        .all()
    )
    for f in files:
        fpath = Path(settings.C2C_CERT_UPLOAD_DIR) / (f.camera_serial or "unknown") / f.stored_name
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
            ph.insert_text((margin, margin + 20), f"Could not embed file: {f.original_name}",
                           fontsize=12, fontname="hebo", color=(0.8, 0, 0))

    out = doc.tobytes()
    doc.close()
    # Live-render self-check: a bad font token / render error raises HERE, not at py_compile.
    check = fitz.open(stream=out, filetype="pdf")
    if check.page_count < 1:
        check.close()
        raise ValueError("composite has no pages")
    for p in check:
        p.get_text()
    check.close()
    return out


def _generate_c2c_composite(db, cert, item, prov):
    """Build + persist the composite PDF for a finalized cert event as a kind='composite' row
    (bytes on disk). Idempotent: drops any prior composite for this event first."""
    for old in (db.query(C2CCertificationFile)
                .filter(C2CCertificationFile.c2c_certification_id == cert.id,
                        C2CCertificationFile.kind == "composite").all()):
        _c2c_file_path(old).unlink(missing_ok=True)
        db.delete(old)
    pdf_bytes = _build_c2c_composite_pdf(db, cert, item, prov)
    serial = cert.camera_serial_snapshot or (item.item_sn if item else None) or "unknown"
    serial_dir = Path(settings.C2C_CERT_UPLOAD_DIR) / serial
    serial_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    with open(serial_dir / stored_name, "wb") as fh:
        fh.write(pdf_bytes)
    db.add(C2CCertificationFile(
        c2c_certification_id=cert.id, camera_serial=serial, kind="composite",
        original_name=f"c2c_composite_{serial}_{cert.id}.pdf", stored_name=stored_name,
        content_type="application/pdf", size_bytes=len(pdf_bytes),
        uploaded_by=cert.certified_by or "system",
    ))
    db.commit()


# ============================================================================
# C2C cancel-certification + copy-forward re-cert (5d). Append-only: a cancel INSERTS a new
# 'cancelled' event (the prior certified event + its files/composite stay frozen); a re-cert
# INSERTS a fresh PENDING draft that inherits the prior certified event's source files, which
# the user may remove/replace (via the delete endpoint) before certifying. is_complete never
# touched (option D).
# ============================================================================
def _copy_forward_c2c_sources(db, new_cert, prior_cert):
    """Duplicate a prior event's kind='source' files onto a fresh draft: copy the on-disk bytes
    to a NEW stored_name + insert a new child row, so each event OWNS its files (the old event
    stays frozen; removing an inherited file from the draft never touches the old event)."""
    sources = (
        db.query(C2CCertificationFile)
        .filter(C2CCertificationFile.c2c_certification_id == prior_cert.id,
                C2CCertificationFile.kind == "source")
        .order_by(C2CCertificationFile.uploaded_at.asc(), C2CCertificationFile.id.asc())
        .all()
    )
    serial = new_cert.camera_serial_snapshot or prior_cert.camera_serial_snapshot or "unknown"
    serial_dir = Path(settings.C2C_CERT_UPLOAD_DIR) / serial
    for f in sources:
        src_path = _c2c_file_path(f)
        if not src_path.exists():
            continue  # skip a missing source; never abort the re-cert
        serial_dir.mkdir(parents=True, exist_ok=True)
        new_stored = f"{uuid.uuid4().hex}{Path(f.stored_name).suffix or '.bin'}"
        with open(src_path, "rb") as rfh, open(serial_dir / new_stored, "wb") as wfh:
            wfh.write(rfh.read())
        db.add(C2CCertificationFile(
            c2c_certification_id=new_cert.id, camera_serial=serial, kind="source",
            original_name=f.original_name, stored_name=new_stored,
            content_type=f.content_type, size_bytes=f.size_bytes, uploaded_by=f.uploaded_by,
        ))


@router.post("/fulfillment/c2c/{provisioning_id}/cancel-cert")
async def c2c_cancel_cert(
    provisioning_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Cancel a CERTIFIED cam: append a new 'cancelled' event (reason + who + when). The prior
    certified event + its files/composite are frozen and untouched."""
    latest = (
        db.query(C2CCertification)
        .filter(C2CCertification.device_provisioning_id == provisioning_id)
        .order_by(C2CCertification.id.desc())
        .first()
    )
    if latest is None or latest.status != "certified":
        return JSONResponse(status_code=400, content={"detail": "Only a currently-certified camera can be cancelled"})
    body = await request.json()
    reason = (body.get("reason") or "").strip()
    if not reason:
        return JSONResponse(status_code=400, content={"detail": "A cancellation reason is required"})
    event = C2CCertification(
        device_provisioning_id=provisioning_id,
        camera_serial_snapshot=latest.camera_serial_snapshot,
        status="cancelled",
        cancel_reason=reason,
        cancelled_by=user.display_name,
        cancelled_at=datetime.utcnow(),
        created_by=user.display_name,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    log_event(
        db, "c2c_cert_cancelled", request=request, user_id=user.id,
        target_table="c2c_certification", target_id=event.id, action="create",
        details=f"Cancelled C2C cert for prov #{provisioning_id}: {reason}",
    )
    return {"status": "cancelled", "cert_id": event.id}


@router.post("/fulfillment/c2c/{provisioning_id}/recertify")
async def c2c_recertify(
    provisioning_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Start a re-certification after a cancel: append a fresh PENDING draft inheriting the prior
    certified event's checklist/evidence + source files (removable/replaceable before certify)."""
    latest = (
        db.query(C2CCertification)
        .filter(C2CCertification.device_provisioning_id == provisioning_id)
        .order_by(C2CCertification.id.desc())
        .first()
    )
    if latest is None or latest.status != "cancelled":
        return JSONResponse(status_code=400, content={"detail": "Re-certification only applies after a cancellation"})
    prior_certified = (
        db.query(C2CCertification)
        .filter(C2CCertification.device_provisioning_id == provisioning_id,
                C2CCertification.status == "certified")
        .order_by(C2CCertification.id.desc())
        .first()
    )
    cert, created = _get_or_create_pending_c2c_draft(db, provisioning_id, user.display_name)
    if created and prior_certified is not None:
        cert.camera_serial_snapshot = prior_certified.camera_serial_snapshot
        cert.checklist = prior_certified.checklist
        cert.firmware_evidence = prior_certified.firmware_evidence
        cert.notes = prior_certified.notes
        db.flush()  # assign cert.id for the copied child rows
        _copy_forward_c2c_sources(db, cert, prior_certified)
    db.commit()
    db.refresh(cert)
    log_event(
        db, "c2c_cert_recertify_started", request=request, user_id=user.id,
        target_table="c2c_certification", target_id=cert.id, action="create",
        details=f"Started re-certification draft #{cert.id} for prov #{provisioning_id} (inherited files)",
    )
    return {"status": "pending", "cert_id": cert.id}


# ============================================================================
# Per-camera certification history (5e). A single physical camera (one item_schema.items row,
# one serial) may be provisioned many times; each provisioning row carries an append-only cert
# log. This view gathers every event across ALL of a camera's provisioning rows into one
# timeline (newest first), each event linking to its composite PDF + source files.
# ============================================================================
@router.get("/fulfillment/c2c/history/{item_id}", response_class=HTMLResponse)
def c2c_history(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    item = db.query(Item).filter(Item.id == item_id).first()
    if item is None:
        return HTMLResponse("Camera not found", status_code=404)
    provs = db.query(DeviceProvisioning).filter(DeviceProvisioning.item_id == item_id).all()
    prov_ids = [p.id for p in provs]
    order_map = {}
    order_ids = [p.customer_order_id for p in provs if p.customer_order_id]
    if order_ids:
        for o in db.query(CustomerOrder).filter(CustomerOrder.id.in_(order_ids)).all():
            order_map[o.id] = o
    prov_ctx = {}
    for p in provs:
        o = order_map.get(p.customer_order_id)
        prov_ctx[p.id] = {
            "order_number": (o.order_number if o else None),
            "customer_name": (o.customer_name if o else None),
        }
    events = []
    if prov_ids:
        certs = (
            db.query(C2CCertification)
            .filter(C2CCertification.device_provisioning_id.in_(prov_ids))
            .order_by(C2CCertification.id.asc())
            .all()
        )
        cert_ids = [c.id for c in certs]
        files_by_cert = {}
        if cert_ids:
            for f in (
                db.query(C2CCertificationFile)
                .filter(C2CCertificationFile.c2c_certification_id.in_(cert_ids))
                .order_by(C2CCertificationFile.uploaded_at.asc(), C2CCertificationFile.id.asc())
                .all()
            ):
                files_by_cert.setdefault(f.c2c_certification_id, []).append(f)
        for c in certs:
            cfiles = files_by_cert.get(c.id, [])
            composite = next((f for f in cfiles if f.kind == "composite"), None)
            sources = [f for f in cfiles if f.kind == "source"]
            cl = c.checklist or {}
            octx = prov_ctx.get(c.device_provisioning_id, {})
            events.append({
                "id": c.id,
                "status": c.status,
                "provisioning_id": c.device_provisioning_id,
                "order_number": octx.get("order_number"),
                "customer_name": octx.get("customer_name"),
                "certified_by": c.certified_by,
                "certified_at": c.certified_at,
                "cancelled_by": c.cancelled_by,
                "cancelled_at": c.cancelled_at,
                "cancel_reason": c.cancel_reason,
                "created_at": c.created_at,
                "created_by": c.created_by,
                "checklist_passed": sum(1 for k in CHECKLIST_ITEMS if cl.get(k)),
                "checklist_total": len(CHECKLIST_ITEMS),
                "composite": ({"id": composite.id, "name": composite.original_name} if composite else None),
                "sources": [{"id": f.id, "name": f.original_name} for f in sources],
            })
        events.reverse()  # newest first
    ctx = {
        "request": request,
        "user": user,
        "item": {"id": item.id, "item_name": item.item_name, "item_sn": item.item_sn,
                 "brand_sku": item.brand_sku},
        "events": events,
    }
    return templates.TemplateResponse("c2c_history.html", ctx)
