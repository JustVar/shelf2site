"""C2C camera certification — a separate, lighter fulfillment flow.

C2C cameras (category ``camera_c2c``, the ``cameras`` table) are the company's
Cloud2 camera product. Unlike edge boxes there is no build and no parts: acquire
the cameras for an order, then (in a later slice) certify each one — powered on,
firmware verified, connected to its virtual site via QR, and registered.

This is deliberately its own route surface. The edge-box fulfillment/cert flow
is hardcoded ``device_table == "edge_boxes"`` in ~10 guards, so C2C does NOT ride
those routes.

C1 scope (this file today):
  * GET  /fulfillment/c2c          read-only overview — SKELETON only (viewer)
  * POST /fulfillment/c2c/acquire  provision a camera to an order    (manager)

The per-camera certify write path (checklist + firmware-evidence JSONB + the
all-pass gate) is C2 and is intentionally absent here.

See docs/specs/c2c-camera-certification.md and
docs/specs/c2c-c1-discovery-handoff.md.
"""

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
    Camera, CustomerOrder, DeviceProvisioning, Site, User, get_display_name,
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
# Minimal cam acquisition path (C1)
# ---------------------------------------------------------------------------
# Provision a physical camera to a customer order: creates the DeviceProvisioning
# row (device_table="cameras") that the per-cam cert (C2) keys on. Cams do not
# ride the edge-box stage pipeline, so:
#   * stages=[]           — column is nullable=False; [] is safe because every
#                           stages read guards falsy (_get_stage_label /
#                           `rec.stages or []`). The only unguarded indexers are
#                           the edge-box advance/revert routes, which cams never
#                           reach.
#   * fulfillment_type=NULL — "not in the (edge-box) fulfillment pipeline".
#   * current_stage="acquired" — a display label only; there is no stage machine
#                           for cams. Kept human-readable for the read-only view.
#
# The order's cam batch (how many of model X are needed) stays in the existing
# CustomerOrder.sku_requirements JSONB — no new order-line table. "Acquired" is
# then simply the set of cameras DeviceProvisioning rows linked to the order.

@router.post("/fulfillment/c2c/acquire")
async def c2c_acquire(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Provision a camera (device_table='cameras') to a customer order."""
    body = await request.json()
    device_id = body.get("device_id")
    customer_order_id = body.get("customer_order_id")
    site_id = body.get("site_id")
    notes = (body.get("notes") or "").strip()

    # Camera is required and must exist.
    if not device_id:
        return JSONResponse(status_code=400, content={"error": "device_id (camera) is required"})
    camera = db.query(Camera).filter(Camera.id == int(device_id)).first()
    if not camera:
        return JSONResponse(status_code=404, content={"error": "Camera not found"})

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

    # One active provisioning per physical camera.
    existing = (
        db.query(DeviceProvisioning)
        .filter(
            DeviceProvisioning.device_table == "cameras",
            DeviceProvisioning.device_id == int(device_id),
            DeviceProvisioning.is_complete.is_(False),
        )
        .first()
    )
    if existing:
        return JSONResponse(status_code=409, content={"error": "Camera already has active provisioning"})

    rec = DeviceProvisioning(
        device_table="cameras",
        device_id=int(device_id),
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
        details=f"Acquired camera #{device_id} ({get_display_name(camera)}) to order {order.order_number}",
    )

    return JSONResponse(content={
        "status": "acquired",
        "id": rec.id,
        "camera_name": get_display_name(camera),
    })
