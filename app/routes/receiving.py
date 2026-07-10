"""Receiving & Intake routes: mobile scanning page, receiving events, photo upload."""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_receiving_access
from ..config import settings
from ..database import get_db
from ..models import (
    IntakePhoto, NASDevice, PendingDevice, ReceivingEvent,
    TABLE_MODELS, TABLE_DISPLAY_NAMES, User, compute_completeness,
)
from ..validation import validate_mac_address, validate_serial_number, validate_required_fields, get_category_required_fields
from ..vendor_defaults import lookup_by_serial_prefix

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@router.get("/receive")
def receive_page(
    request: Request,
    category: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_receiving_access),
):
    """Mobile-first receiving & barcode scanning page."""
    events = (
        db.query(ReceivingEvent)
        .filter(ReceivingEvent.status == "open")
        .order_by(desc(ReceivingEvent.created_at))
        .all()
    )
    return templates.TemplateResponse("receive.html", {
        "request": request,
        "user": user,
        "events": events,
        "table_choices": TABLE_DISPLAY_NAMES,
        "preselect_category": category or "",
    })


# ---------------------------------------------------------------------------
# Receiving event API
# ---------------------------------------------------------------------------

@router.post("/api/receive/events")
async def create_receiving_event(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Create a new receiving event (shipment)."""
    body = await request.json()
    event = ReceivingEvent(
        vendor=(body.get("vendor") or "").strip() or None,
        purchase_order=(body.get("purchase_order") or "").strip() or None,
        expected_quantity=body.get("expected_quantity"),
        notes=(body.get("notes") or "").strip() or None,
        created_by=user.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    log_event(
        db, "receiving_event_created",
        request=request,
        user_id=user.id,
        target_table="receiving_events",
        target_id=event.id,
        action="create",
        details=f"Receiving event: {event.vendor or 'Unknown'} PO:{event.purchase_order or 'N/A'}",
    )

    return JSONResponse(content={
        "status": "created",
        "event_id": event.id,
        "vendor": event.vendor,
        "purchase_order": event.purchase_order,
    })


# ---------------------------------------------------------------------------
# Barcode scan processing
# ---------------------------------------------------------------------------

@router.post("/api/receive/scan")
async def process_scan(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Process a barcode/QR scan. Returns pre-fill data or 'unknown'."""
    body = await request.json()
    barcode = (body.get("barcode") or "").strip()

    if not barcode:
        return JSONResponse(status_code=400, content={"error": "Empty barcode"})

    # Check if serial already exists in any inventory table
    for table_name, model in TABLE_MODELS.items():
        if hasattr(model, "serial"):
            existing = db.query(model).filter(model.serial == barcode).first()
            if existing:
                return JSONResponse(content={
                    "status": "already_exists",
                    "table": table_name,
                    "display_table": TABLE_DISPLAY_NAMES.get(table_name, table_name),
                    "device_id": existing.id,
                    "serial": barcode,
                })

    # Try vendor/model auto-lookup by serial prefix
    defaults = lookup_by_serial_prefix(barcode)
    if defaults:
        return JSONResponse(content={
            "status": "recognized",
            "serial": barcode,
            "prefill": defaults,
        })

    # Not recognized — manual entry
    return JSONResponse(content={
        "status": "unknown",
        "serial": barcode,
        "prefill": {},
    })


# ---------------------------------------------------------------------------
# Duplicate check API
# ---------------------------------------------------------------------------

@router.get("/api/receive/check-duplicate")
def check_duplicate_serial(
    serial: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check if a serial number already exists in any inventory table."""
    serial = serial.strip()
    if not serial:
        return JSONResponse(content={"exists": False})

    for table_name, model in TABLE_MODELS.items():
        if hasattr(model, "serial"):
            existing = db.query(model).filter(model.serial == serial).first()
            if existing:
                return JSONResponse(content={
                    "exists": True,
                    "table": table_name,
                    "display_table": TABLE_DISPLAY_NAMES.get(table_name, table_name),
                    "device_id": existing.id,
                    "serial": serial,
                    "location": getattr(existing, "location", None),
                    "status": getattr(existing, "status", None),
                })

    return JSONResponse(content={"exists": False})


# ---------------------------------------------------------------------------
# Device submission (to inventory or pending queue)
# ---------------------------------------------------------------------------

@router.post("/api/receive/device")
async def submit_device(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Submit a scanned device to inventory (direct) or pending review queue."""
    body = await request.json()
    target_table = body.get("target_table", "")
    serial = (body.get("serial") or "").strip()
    direct = body.get("direct_to_inventory", False)
    event_id = body.get("receiving_event_id")

    if not serial:
        return JSONResponse(status_code=400, content={"error": "Serial is required"})

    # Validate serial number format
    serial_valid, serial_error = validate_serial_number(serial, required=True)
    if not serial_valid:
        return JSONResponse(status_code=400, content={"error": serial_error})

    # Validate MAC addresses if provided
    validation_errors = {}
    for mac_field in ["mac_address", "mac_address_1", "mac_address_2"]:
        mac_value = (body.get(mac_field) or "").strip()
        if mac_value:
            mac_valid, mac_result = validate_mac_address(mac_value)
            if not mac_valid:
                validation_errors[mac_field] = mac_result
            elif mac_result:  # Normalized MAC
                body[mac_field] = mac_result

    if validation_errors:
        return JSONResponse(status_code=400, content={
            "error": "Validation failed",
            "field_errors": validation_errors
        })

    if direct and target_table in TABLE_MODELS:
        model_class = TABLE_MODELS[target_table]

        # Build kwargs from body — only set columns that exist on the model
        kwargs = {"discovered_by": f"intake:{user.username}"}
        field_candidates = [
            "serial", "model", "manufacturer", "location", "status",
            "mac_address_1", "mac_address_2", "bay_count", "ram_gb",
            "firmware_version", "assigned_to", "ip_address",
            "mac_address", "device", "device_name", "notes",
            "purchase_order",
            "capacity_gb", "drive_type", "form_factor", "interface", "installed_in",
            "deployment_type", "part_number", "uuid", "sku_version",
            "org", "customer", "partner", "site_name", "pilot_type",
        ]
        for field in field_candidates:
            val = body.get(field)
            if val is not None and hasattr(model_class, field):
                kwargs[field] = val
        if event_id and hasattr(model_class, "receiving_event_id"):
            kwargs["receiving_event_id"] = event_id

        device = model_class(**kwargs)
        device.data_completeness = compute_completeness(device)
        db.add(device)
        db.commit()
        db.refresh(device)

        # Update receiving event count
        if event_id:
            event = db.query(ReceivingEvent).filter(
                ReceivingEvent.id == event_id
            ).first()
            if event:
                event.received_quantity = (event.received_quantity or 0) + 1
                db.commit()

        log_event(
            db, "device_added",
            request=request,
            user_id=user.id,
            target_table=target_table,
            target_id=device.id,
            action="create",
            new_values=model_to_dict(device),
            details=f"Intake scan: added {serial} to {target_table}",
        )

        from ..sidebar_cache import invalidate_category_stats, invalidate_triage_cache
        invalidate_category_stats()
        invalidate_triage_cache()

        return JSONResponse(content={
            "status": "created",
            "target_table": target_table,
            "device_id": device.id,
        })

    # Route to pending review queue
    pending = PendingDevice(
        mac_address=body.get("mac_address") or body.get("mac_address_1") or f"intake-{serial}",
        hostname=None,  # Hostname is for network-discovered devices only
        manufacturer=body.get("manufacturer", ""),
        suggested_table=target_table or "network_equipment",
        scanner_id=f"intake:{user.username}",
        status="pending",
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)

    # Publish SSE event
    try:
        from .sse import publish_event
        publish_event("device_pending", {"count": 1, "source": "intake"})
    except Exception:
        pass

    log_event(
        db, "device_pending",
        request=request,
        user_id=user.id,
        target_table="pending_devices",
        target_id=pending.id,
        action="create",
        details=f"Intake scan: {serial} -> pending review (suggested: {target_table})",
    )

    from ..sidebar_cache import invalidate_category_stats, invalidate_triage_cache
    invalidate_category_stats()
    invalidate_triage_cache()

    return JSONResponse(content={
        "status": "pending_review",
        "pending_id": pending.id,
    })


# ---------------------------------------------------------------------------
# Photo upload and serving
# ---------------------------------------------------------------------------

@router.post("/api/receive/photo")
async def upload_photo(
    request: Request,
    file: UploadFile = File(...),
    receiving_event_id: int | None = Form(None),
    device_table: str | None = Form(None),
    device_id: int | None = Form(None),
    caption: str = Form(""),
    run_ocr: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Upload a label photo for a receiving event or device, with optional OCR."""
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        return JSONResponse(status_code=400, content={"error": "Only JPEG, PNG, WEBP allowed"})

    # Build storage path
    upload_root = Path(settings.PHOTO_UPLOAD_DIR)
    if receiving_event_id:
        upload_dir = upload_root / f"event_{receiving_event_id}"
    else:
        upload_dir = upload_root / "unlinked"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename
    ext = Path(file.filename).suffix if file.filename else ".jpg"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / stored_name

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # Run OCR if requested
    ocr_data = {}
    if run_ocr:
        try:
            from scanner.ocr_processor import process_photo_for_intake
            ocr_data = process_photo_for_intake(file_path)
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"OCR processing failed: {e}")
            ocr_data = {"_ocr_error": str(e)}

    # Database record
    rel_path = str(file_path.relative_to(upload_root))
    photo = IntakePhoto(
        receiving_event_id=receiving_event_id,
        device_table=device_table,
        device_id=device_id,
        filename=rel_path,
        original_filename=file.filename,
        content_type=file.content_type,
        file_size=len(content),
        caption=caption.strip() or None,
        uploaded_by=user.id,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    log_event(
        db, "photo_uploaded",
        request=request,
        user_id=user.id,
        target_table="intake_photos",
        target_id=photo.id,
        action="create",
        details=f"Photo: {file.filename} ({len(content)} bytes), OCR: {bool(ocr_data)}",
    )

    response_data = {
        "status": "uploaded",
        "photo_id": photo.id,
    }

    # Include OCR results if any
    if ocr_data:
        response_data["ocr"] = ocr_data

    return JSONResponse(content=response_data)


@router.get("/api/receive/photo/{photo_id}")
def serve_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Serve an intake photo by ID."""
    photo = db.query(IntakePhoto).filter(IntakePhoto.id == photo_id).first()
    if not photo:
        return JSONResponse(status_code=404, content={"error": "Photo not found"})

    file_path = Path(settings.PHOTO_UPLOAD_DIR) / photo.filename
    if not file_path.exists():
        return JSONResponse(status_code=404, content={"error": "File missing"})

    return FileResponse(
        path=str(file_path),
        media_type=photo.content_type or "image/jpeg",
        filename=photo.original_filename,
    )
