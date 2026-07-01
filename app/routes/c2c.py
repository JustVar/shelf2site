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

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_provisioning_manager, require_provisioning_viewer
from ..config import settings
from ..database import get_db
from ..models import (
    C2CCertification, CustomerOrder, DeviceProvisioning, Item, Site, User,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


# ---------------------------------------------------------------------------
# Read-only C2C view — SKELETON ONLY (C1)
# ---------------------------------------------------------------------------
# Route + template shell only: renders the section headers on an otherwise empty
# page. The visual layout (dark-token translation from docs/mockups/README.md)
# and the per-section data wiring are a design call handed back to Chat. Do NOT
# build the table/list layout here.

@router.get("/fulfillment/c2c", response_class=HTMLResponse)
def c2c_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    """C2C camera fulfillment/cert overview (read-only skeleton)."""
    return templates.TemplateResponse("c2c.html", {"request": request, "user": user})


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

    # Order is required — C2C acquisition provisions cams *to an order*.
    if not customer_order_id:
        return JSONResponse(status_code=400, content={"error": "customer_order_id is required"})
    order = db.query(CustomerOrder).filter(CustomerOrder.id == int(customer_order_id)).first()
    if not order:
        return JSONResponse(status_code=404, content={"error": "Customer order not found"})
    # Same PO gate as edge-box provisioning: no pipeline entry without a customer PO.
    if not order.po_number:
        return JSONResponse(
            status_code=400,
            content={"error": f"Order {order.order_number} has no Customer PO - add one before acquiring cameras"},
        )

    # Validate site if provided.
    if site_id:
        site = db.query(Site).filter(Site.id == int(site_id)).first()
        if not site:
            return JSONResponse(status_code=404, content={"error": "Site not found"})

    # One active provisioning per camera, keyed on the item_id link (option D).
    existing = (
        db.query(DeviceProvisioning)
        .filter(
            DeviceProvisioning.item_id == int(device_id),
            DeviceProvisioning.is_complete.is_(False),
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
        notes=notes or None,
        customer_order_id=order.id,
        created_by=user.id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    log_event(
        db, "c2c_camera_acquired",
        request=request, user_id=user.id,
        target_table="device_provisioning", target_id=rec.id,
        action="create",
        details=f"Acquired C2C camera item #{device_id} ({cam_name}) to order {order.order_number}",
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
    notes = (body.get("notes") or "").strip() or None
    all_pass = all(checklist[k] for k in CHECKLIST_ITEMS)

    # One cert record per provisioning row: get-or-create.
    cert = (
        db.query(C2CCertification)
        .filter(C2CCertification.device_provisioning_id == provisioning_id)
        .first()
    )
    created = cert is None
    if created:
        cert = C2CCertification(
            device_provisioning_id=provisioning_id,
            created_by=user.display_name,
        )
        db.add(cert)

    # Whole-object assignment for JSONB (SQLAlchemy does not track in-place mutation).
    cert.checklist = checklist
    # Guard firmware_evidence against destructive omission: only overwrite when the
    # key is present, so a submit that omits it leaves stored evidence untouched.
    # Present-but-null/empty is honored as an explicit clear. Whole-object assign.
    if "firmware_evidence" in body:
        cert.firmware_evidence = body["firmware_evidence"]
    cert.notes = notes
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
