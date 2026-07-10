"""Receiving & Intake routes: mobile scanning page, receiving events, photo upload."""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_receiving_access
from ..config import settings
from ..database import get_db
from ..models import (
    IntakePhoto, Item, NASDevice, NASDrive, PendingDevice, ReceivingEvent,
    Site, TABLE_MODELS, TABLE_DISPLAY_NAMES, User, compute_completeness,
)
from sqlalchemy.exc import IntegrityError

from ..validation import validate_mac_address, validate_serial_number, validate_required_fields, get_category_required_fields
from ..vendor_defaults import lookup_by_serial_prefix
from .intake import STATUSES as ITEM_INTAKE_STATUSES, _get_locations, create_item

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


def find_serial_anywhere(db: Session, serial: str) -> dict | None:
    """Unified serial lookup (audit H1): case-insensitive across
    item_schema.items (the system of record), every legacy TABLE_MODELS
    table (including GPU, whose column is gpu_serial), and
    nas_drives.serial_number.

    Matches on lower() equality, NOT ilike — scanned strings can contain
    % or _ which ilike would treat as wildcards.

    Returns a dict shaped for the scan / check-duplicate responses
    (table, display_table, device_id, serial, location, status), or None.
    """
    serial = (serial or "").strip()
    if not serial:
        return None
    low = serial.lower()

    # item_schema.items first — the system of record.
    item = (
        db.query(Item)
        .filter(Item.item_sn.isnot(None), func.lower(Item.item_sn) == low)
        .first()
    )
    if item:
        location = None
        if item.location_id:
            site = db.query(Site).filter(Site.id == item.location_id).first()
            location = site.name if site else None
        return {
            "table": "items",
            "display_table": "Inventory Items",
            "device_id": item.id,
            "serial": item.item_sn,
            "location": location,
            "status": item.item_status,
        }

    # Legacy per-category tables — still hold most historical serials.
    for table_name, model in TABLE_MODELS.items():
        col = getattr(model, "serial", None)
        if col is None:
            col = getattr(model, "gpu_serial", None)
        if col is None:
            continue
        row = db.query(model).filter(col.isnot(None), func.lower(col) == low).first()
        if row:
            return {
                "table": table_name,
                "display_table": TABLE_DISPLAY_NAMES.get(table_name, table_name),
                "device_id": row.id,
                "serial": getattr(row, "serial", None) or getattr(row, "gpu_serial", None),
                "location": getattr(row, "location", None),
                "status": getattr(row, "status", None),
            }

    # NAS bay drives live outside TABLE_MODELS.
    drive = (
        db.query(NASDrive)
        .filter(NASDrive.serial_number.isnot(None), func.lower(NASDrive.serial_number) == low)
        .first()
    )
    if drive:
        return {
            "table": "nas_drives",
            "display_table": "NAS Drives",
            "device_id": drive.id,
            "serial": drive.serial_number,
            "location": None,
            "status": getattr(drive, "drive_status", None),
        }

    return None


# H2: legacy scan target tables -> item_schema categories. Scan intake now
# lands in item_schema.items (the system of record) — never public.*.
TARGET_TABLE_TO_CATEGORY = {
    "edge_boxes": "edge_box",
    "gpus": "gpu",
    "monitors": "monitor",
    "computers": "computer",
    "nucs": "computer",
    "mobile_devices": "mobile_device",
    "phones": "mobile_device",
    "cameras": "camera",
    "webcams": "camera",
    "network_equipment": "network",
    # Provisional: item_categories has no NAS value — QNAP NAS units land as
    # network appliances until the taxonomy decision (SCANNER_AUDIT H2 note).
    "nas_devices": "network",
    "access_control": "access_control",
    "office_equipment": "office_equipment",
    "printers": "office_equipment",
    "ups": "ups",
    "ram_modules": "ram",
    "cpus": "cpu",
    "psus": "psu",
    "motherboards": "motherboard",
    "pc_cooling": "cpu_cooler",
    "pc_accessories": "pc_accessories",
    "hard_drives": "storage_drive",
}

# item_status is a Postgres ENUM — legacy receive/quick-mode strings must be
# translated or the insert fails (audit H2/H6).
_ITEM_STATUS_VALUES = {
    "Deployed", "Ready to Deploy", "Pending", "Un-deployable",
    "Decommissioned", "Unassigned", "Checked Out",
}
_STATUS_TRANSLATION = {
    "received": "Pending",
    "in storage": "Unassigned",
    "testing": "Pending",
    "inventory": "Unassigned",  # old quick-mode hardcode (audit F6)
}


def _resolve_item_status(raw) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if s in _ITEM_STATUS_VALUES:
        return s
    return _STATUS_TRANSLATION.get(s.lower())


def _resolve_location_id(db: Session, body: dict):
    """Resolve the payload's location to a sites row.

    Prefers location_id (the receive form now sends a site select); falls
    back to case-insensitive name match of legacy free text against active
    non-customer sites. Returns (location_id, unmatched_text) — unmatched
    text is preserved in notes by the caller, never silently dropped.
    """
    loc_id = body.get("location_id")
    if loc_id not in (None, ""):
        try:
            return int(loc_id), None
        except (TypeError, ValueError):
            pass
    text = (body.get("location") or "").strip()
    if not text:
        return None, None
    site = (
        db.query(Site)
        .filter(
            Site.is_active == True,  # noqa: E712 — SQLAlchemy comparison
            Site.site_type != "customer_site",
            func.lower(Site.name) == text.lower(),
        )
        .first()
    )
    if site:
        return site.id, None
    return None, text


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
        "locations": _get_locations(db),
        "statuses": ITEM_INTAKE_STATUSES,
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

    # Unified, case-insensitive existence check (items + legacy + nas_drives)
    existing = find_serial_anywhere(db, barcode)
    if existing:
        # The helper's "status" key is the DEVICE status (check-duplicate's
        # shape); rename it so it can't clobber the scan outcome.
        payload = dict(existing)
        payload["device_status"] = payload.pop("status", None)
        payload["status"] = "already_exists"
        return JSONResponse(content=payload)

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

    hit = find_serial_anywhere(db, serial)
    if hit:
        return JSONResponse(content={"exists": True, **hit})

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

    # H4: server-side dedupe — the client pre-check fails open and is
    # user-bypassable; enforce here unless the caller explicitly bypasses.
    if not body.get("bypass_duplicate"):
        existing = find_serial_anywhere(db, serial)
        if existing:
            return JSONResponse(status_code=409, content={
                "error": f"Serial {serial} already exists in {existing['display_table']}",
                "duplicate": existing,
            })

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

    if direct:
        # H2: scan intake lands in item_schema.items — the same destination
        # and create path as the Intake page (audit F2). Legacy public.*
        # writes are retired for this flow.
        item_category = TARGET_TABLE_TO_CATEGORY.get(target_table)
        if not item_category:
            return JSONResponse(status_code=400, content={
                "error": f"Unknown target category '{target_table}'",
            })

        item_status = _resolve_item_status(body.get("status"))
        location_id, unmatched_location = _resolve_location_id(db, body)

        notes = (body.get("notes") or "").strip()
        if unmatched_location:
            notes = (notes + "\n" if notes else "") + f"Location (as scanned): {unmatched_location}"

        # brand_sku is an FK into item_schema.part_numbers — only store a
        # known SKU; unknown scans go to notes instead of failing the insert.
        brand_sku = None
        part_number = (body.get("part_number") or "").strip()
        if part_number:
            from ..models import ItemPartNumber
            known = db.query(ItemPartNumber).filter(
                func.lower(ItemPartNumber.brand_sku) == part_number.lower()
            ).first()
            if known:
                brand_sku = known.brand_sku
            else:
                notes = (notes + "\n" if notes else "") + f"Part number (as scanned): {part_number}"

        # Scan-only extras ride in attributes (keys per app/item_fields.py).
        attributes = {}
        for key in ("deployment_type", "form_factor", "sku_version", "customer",
                    "partner", "capacity_gb", "drive_type", "interface",
                    "bay_count", "ram_gb", "firmware_version", "org",
                    "site_name", "pilot_type"):
            val = body.get(key)
            if val not in (None, ""):
                attributes[key] = val

        event = None
        if event_id:
            event = db.query(ReceivingEvent).filter(
                ReceivingEvent.id == event_id
            ).first()

        receipt = None
        if event:
            receipt = {
                "purchase_order": event.purchase_order,
                "record_type": "packing_slip",
                "notes": "Scan intake — receiving event #" + str(event.id)
                         + (f" ({event.vendor})" if event.vendor else ""),
            }

        manufacturer = (body.get("manufacturer") or "").strip()
        model = (body.get("model") or "").strip()
        item_name = (body.get("device_name") or body.get("device") or "").strip() \
            or f"{manufacturer} {model}".strip() or serial

        try:
            item = create_item(
                db,
                fields={
                    "item_name": item_name,
                    "item_manufacturer": manufacturer,
                    "item_model": model,
                    "item_sn": serial,
                    "item_category": item_category,
                    "item_status": item_status,
                    "location_id": location_id,
                    "department_or_owner": body.get("assigned_to"),
                    "item_mac_address_1": body.get("mac_address_1") or body.get("mac_address"),
                    "item_mac_address_2": body.get("mac_address_2"),
                    "appliance_uuid": body.get("uuid"),
                    "brand_sku": brand_sku,
                    "item_vendor": event.vendor if event else None,
                    "notes": notes,
                },
                created_by=user.display_name or user.username,
                receipt=receipt,
                attributes=attributes or None,
            )
            if event:
                event.received_quantity = (event.received_quantity or 0) + 1
            db.commit()
        except IntegrityError:
            db.rollback()
            return JSONResponse(status_code=409, content={
                "error": f"Database rejected {serial}: a uniqueness constraint "
                         "matched an existing row (duplicate serial or MAC).",
            })
        db.refresh(item)

        log_event(
            db, "device_added",
            request=request,
            user_id=user.id,
            target_table="items",
            target_id=item.id,
            action="create",
            new_values=model_to_dict(item),
            details=f"Intake scan: added {serial} to item_schema.items ({item_category})",
        )

        from ..sidebar_cache import invalidate_category_stats, invalidate_triage_cache
        invalidate_category_stats()
        invalidate_triage_cache()

        return JSONResponse(content={
            "status": "created",
            "target_table": "items",
            "display_table": "Inventory Items",
            "item_category": item_category,
            "device_id": item.id,
            "item_url": f"{BP}/items/{item.id}",
        })

    # Route to pending review queue. H3: preserve everything the scan knew —
    # serial/model/notes/event linkage used to be silently discarded here.
    if event_id and not db.query(ReceivingEvent.id).filter(
            ReceivingEvent.id == event_id).first():
        event_id = None  # a stale event id must not fail the insert
    pending = PendingDevice(
        mac_address=body.get("mac_address") or body.get("mac_address_1") or f"intake-{serial}",
        hostname=None,  # Hostname is for network-discovered devices only
        manufacturer=body.get("manufacturer", ""),
        suggested_table=target_table or "network_equipment",
        scanner_id=f"intake:{user.username}",
        status="pending",
        serial=serial,
        model=(body.get("model") or "").strip() or None,
        notes=(body.get("notes") or "").strip() or None,
        receiving_event_id=event_id,
    )
    db.add(pending)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=409, content={
            "error": f"Database rejected {serial}: a uniqueness constraint "
                     "matched an existing pending row.",
        })
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
