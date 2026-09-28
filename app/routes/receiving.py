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
from ..auth import get_current_user, require_editor, require_receiving_access, require_scan_access
from ..config import settings
from ..localtime import register
from ..database import get_db
from ..models import (
    AccessControl, Camera, CustomerOrder, EdgeBox, IntakePhoto, Item,
    ItemPartNumber, NASDevice, NASDrive, NUC, OUIAllowlist, PendingDevice,
    ReceivedDevice, ReceivingEvent, ReceivingEventLine, Site,
    TABLE_MODELS, TABLE_DISPLAY_NAMES, UnitPhoto, User,
    compute_completeness, user_can_approve_table,
)
from sqlalchemy.exc import IntegrityError

from ..po_matching import match_oem_lines, norm_sku, oem_line_summary, sync_oem_receipt
from ..scan_routing import classify, mac_from_bare_hex, preprocess
from ..validation import normalize_mac, validate_mac_address, validate_serial_number, validate_required_fields, get_category_required_fields
from ..vendor_defaults import lookup_by_serial_prefix
from .intake import STATUSES as ITEM_INTAKE_STATUSES, _get_locations, create_item
from ..models import HAND_EDITABLE_ITEM_STATUSES

# Pilot-period routing log (SCANNER_AUDIT §8): every miss/unclassified scan
# is logged with its raw payload so misroutes can be diagnosed from journald.
logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


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
    "phones": "phone",
    "cameras": "camera",
    "webcams": "webcam",
    "network_equipment": "network",
    # item 30 S3: phones, webcams, printers and NAS have their own categories
    # (migration 080); a NAS is a unit that holds its drives.
    "nas_devices": "nas",
    "access_control": "access_control",
    "office_equipment": "office_equipment",
    "printers": "printer",
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
# Derived per docs/specs/item-decommission.md: the hand-editable base
# plus receiving's one declared extra, Checked Out (in-house items out
# with a person; checked in on return). Decommissioned is code-mediated
# and not valid receive input.
_ITEM_STATUS_VALUES = set(HAND_EDITABLE_ITEM_STATUSES) | {"Checked Out"}
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

def _maybe_autocomplete(event: ReceivingEvent) -> None:
    """H15/H17: auto-complete an open event when expectation is met — every
    line full when SKU lines exist, else the flat count. Caller commits."""
    if event.status != "open":
        return
    lines = event.lines or []
    if lines:
        if all((l.qty_received or 0) >= (l.qty_expected or 0) for l in lines):
            event.status = "complete"
    elif event.expected_quantity and (event.received_quantity or 0) >= event.expected_quantity:
        event.status = "complete"


def _line_for_sku(event: ReceivingEvent, unit_sku: str | None):
    key = norm_sku(unit_sku)
    if not key:
        return None
    for line in (event.lines or []):
        if norm_sku(line.sku) == key:
            return line
    return None


def _record_received_unit(db, event, unit_sku, serial, item_id=None, pending_device_id=None):
    """H17: one received_devices row per intaken unit + tick its SKU line."""
    line = _line_for_sku(event, unit_sku)
    if line is not None:
        line.qty_received = (line.qty_received or 0) + 1
    db.add(ReceivedDevice(
        receiving_event_id=event.id,
        line_id=line.id if line is not None else None,
        item_id=item_id,
        pending_device_id=pending_device_id,
        serial=serial,
        sku=(unit_sku or "").strip() or None,
    ))


@router.post("/api/receive/events")
async def create_receiving_event(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_receiving_access),
):
    """Create a new receiving event (shipment). H16: the free-text PO is
    matched (case/space-insensitive) against oem_purchase_orders; a match
    prefills expected quantity from what is still outstanding on the PO's
    SKU lines. No match never blocks — the text stays as typed."""
    body = await request.json()
    po_text = (body.get("purchase_order") or "").strip() or None
    expected = body.get("expected_quantity")

    oem_rows = match_oem_lines(db, po_text)
    if oem_rows and not expected:
        expected = sum(
            max((r.qty_ordered or 0) - (r.qty_received or 0), 0) for r in oem_rows
        ) or None

    event = ReceivingEvent(
        vendor=(body.get("vendor") or "").strip() or None,
        purchase_order=po_text,
        tracking_number=(body.get("tracking_number") or "").strip() or None,
        expected_quantity=expected,
        notes=(body.get("notes") or "").strip() or None,
        created_by=user.id,
    )
    db.add(event)
    db.flush()
    # H17: snapshot the PO's outstanding SKU lines as this shipment's
    # check-off expectations (event-local; later OEM edits don't rewrite
    # an in-flight shipment's checklist).
    for r in oem_rows:
        outstanding = max((r.qty_ordered or 0) - (r.qty_received or 0), 0)
        db.add(ReceivingEventLine(
            receiving_event_id=event.id, sku=r.sku, qty_expected=outstanding,
        ))
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
        "expected_quantity": event.expected_quantity,
        "po_matched": bool(oem_rows),
        "po_lines": oem_line_summary(oem_rows),
    })


def _line_state(line: ReceivingEventLine, closed: bool) -> str:
    got, want = line.qty_received or 0, line.qty_expected or 0
    if got > want:
        return "over"
    if got >= want:
        return "full"
    return "short" if closed else "open"


def _event_payload(db: Session, event: ReceivingEvent) -> dict:
    oem_rows = match_oem_lines(db, event.purchase_order)
    closed = event.status != "open"
    return {
        "event_id": event.id,
        "vendor": event.vendor,
        "purchase_order": event.purchase_order,
        "tracking_number": event.tracking_number,
        "expected_quantity": event.expected_quantity,
        "received_quantity": event.received_quantity or 0,
        "status": event.status,
        "po_matched": bool(oem_rows),
        "po_lines": oem_line_summary(oem_rows),
        "photo_count": db.query(UnitPhoto).filter(
            UnitPhoto.receiving_event_id == event.id,
            UnitPhoto.is_hidden.is_(False)).count(),
        "lines": [
            {
                "id": l.id,
                "sku": l.sku,
                "qty_expected": l.qty_expected or 0,
                "qty_received": l.qty_received or 0,
                "state": _line_state(l, closed),
            }
            for l in (event.lines or [])
        ],
    }


@router.get("/api/receive/events/{event_id}")
def get_receiving_event(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_receiving_access),
):
    """Current state of one receiving event — the receive page's event panel."""
    event = db.query(ReceivingEvent).filter(ReceivingEvent.id == event_id).first()
    if not event:
        return JSONResponse(status_code=404, content={"error": "Event not found"})
    return JSONResponse(content=_event_payload(db, event))


@router.post("/api/receive/events/{event_id}/close")
async def close_receiving_event(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_receiving_access),
):
    """Close a receiving event (H15): 'complete' when the received count met
    the expectation, else 'partial'. The open|complete|partial vocabulary
    existed from day one but nothing ever wrote the closed states (audit F14).

    PO provenance decision (H15): no per-device PO column — direct intakes
    already carry the PO on their item receipts (H2), and pending units link
    through received_devices (H17). The event stays the single PO source.
    """
    event = db.query(ReceivingEvent).filter(ReceivingEvent.id == event_id).first()
    if not event:
        return JSONResponse(status_code=404, content={"error": "Event not found"})
    if event.status != "open":
        return JSONResponse(content={**_event_payload(db, event), "already_closed": True})

    received = event.received_quantity or 0
    lines = event.lines or []
    if lines:
        # H17: with SKU lines the verdict is per-line, not the flat count.
        complete = all((l.qty_received or 0) >= (l.qty_expected or 0) for l in lines)
    else:
        complete = bool(event.expected_quantity) and received >= event.expected_quantity
    event.status = "complete" if complete else "partial"
    db.commit()

    log_event(
        db, "receiving_event_closed",
        request=request, user_id=user.id,
        target_table="receiving_events", target_id=event.id,
        action="update",
        details=f"Closed receiving event #{event.id} as {event.status} "
                f"({received}/{event.expected_quantity or '?'} received)",
    )
    return JSONResponse(content=_event_payload(db, event))


# ---------------------------------------------------------------------------
# Barcode scan processing — §4 routing table (SCANNER_AUDIT, approved)
# ---------------------------------------------------------------------------

# MAC-bearing columns per surface. Legacy columns store the canonical
# AA:BB:CC:DD:EE:FF (validate_mac_address funnels through normalize_mac);
# items' macaddr columns compare against the same normalized text.
_MAC_COLUMNS = [
    ("items", lambda: [Item.item_mac_address_1, Item.item_mac_address_2]),
    ("edge_boxes", lambda: [EdgeBox.mac_address, EdgeBox.mac_address_2]),
    ("cameras", lambda: [Camera.mac_address]),
    ("access_control", lambda: [AccessControl.mac_address]),
    ("nas_devices", lambda: [NASDevice.mac_address_1, NASDevice.mac_address_2]),
    ("nucs", lambda: [NUC.mac_address, NUC.mac_address_2]),
]
_MAC_MODELS = {
    "items": Item, "edge_boxes": EdgeBox, "cameras": Camera,
    "access_control": AccessControl, "nas_devices": NASDevice, "nucs": NUC,
}


def _found(table, device_id, serial, location=None, status=None, matched_on="serial"):
    """already_exists payload — same shape process_scan has always returned,
    plus class/matched_on so clients can say HOW it matched."""
    return {
        "status": "already_exists",
        "matched_on": matched_on,
        "table": table,
        "display_table": TABLE_DISPLAY_NAMES.get(table, table.replace("_", " ").title()),
        "device_id": device_id,
        "serial": serial,
        "location": location,
        "device_status": status,
    }


def _item_found(db, item, matched_on):
    loc = None
    if item.location_id:
        site = db.query(Site).filter(Site.id == item.location_id).first()
        loc = site.name if site else None
    return _found("items", item.id, item.item_sn,
                  location=loc,
                  status=str(item.item_status) if item.item_status else None,
                  matched_on=matched_on)


def find_mac_anywhere(db, mac: str):
    """Case-insensitive MAC lookup over every MAC-bearing column."""
    for table, cols in _MAC_COLUMNS:
        model = _MAC_MODELS[table]
        for col in cols():
            if table == "items":
                row = db.query(model).filter(col == mac).first()
            else:
                row = db.query(model).filter(func.upper(col) == mac).first()
            if row:
                if table == "items":
                    return _item_found(db, row, "mac")
                return _found(
                    table, row.id,
                    getattr(row, "serial", None),
                    location=getattr(row, "location", None),
                    status=getattr(row, "status", None),
                    matched_on="mac",
                )
    return None


def _route_scan(db, cls: str, value: str, gs1: dict) -> dict:
    """Per-class lookup + specific not-found guidance (§4 table)."""
    low, up = value.lower(), value.upper()

    def miss(guidance, prefill=None, klass=None):
        return {"status": "unknown", "class": klass or cls, "serial": value,
                "prefill": prefill or {}, "guidance": guidance}

    def recognized(guidance, prefill):
        return {"status": "recognized", "class": cls, "serial": value,
                "prefill": prefill, "guidance": guidance}

    if cls == "mac":
        mac = normalize_mac(value)
        hit = find_mac_anywhere(db, mac)
        if hit:
            hit["class"] = cls
            return hit
        return miss(f"No device with MAC {mac} — receive it with the MAC prefilled?",
                    {"mac_address": mac})

    if cls == "uuid":
        for model, col, table in ((EdgeBox, EdgeBox.uuid, "edge_boxes"),
                                  (NUC, NUC.uuid, "nucs")):
            row = db.query(model).filter(func.lower(col) == low).first()
            if row:
                payload = _found(table, row.id, getattr(row, "serial", None),
                                 location=getattr(row, "location", None),
                                 status=getattr(row, "status", None),
                                 matched_on="uuid")
                payload["class"] = cls
                return payload
        item = db.query(Item).filter(func.lower(Item.appliance_uuid) == low).first()
        if item:
            payload = _item_found(db, item, "uuid")
            payload["class"] = cls
            return payload
        return miss("UUID not linked to any unit — scan the serial instead.")

    if cls == "tracking":
        # H17: an inbound label that matches a receiving event's tracking
        # number selects that event — the scan IS the shipment arriving.
        ev = (
            db.query(ReceivingEvent)
            .filter(func.lower(ReceivingEvent.tracking_number) == low)
            .order_by((ReceivingEvent.status == "open").desc(), ReceivingEvent.id.desc())
            .first()
        )
        if ev:
            return {
                "status": "recognized", "class": cls, "serial": value, "prefill": {},
                "event_id": ev.id,
                "guidance": f"Inbound shipment for receiving event #{ev.id} "
                            f"({ev.vendor or 'Unknown vendor'}) — event selected.",
            }
        item = db.query(Item).filter(func.lower(Item.tracking_number) == low).first()
        if item:
            payload = _item_found(db, item, "tracking")
            payload["class"] = cls
            return payload
        order = db.query(CustomerOrder).filter(
            func.lower(CustomerOrder.tracking_number) == low).first()
        if order:
            payload = _found("customer_orders", order.id, value,
                             status=order.status, matched_on="tracking")
            payload.update({"class": cls, "display_table": "Customer Orders",
                            "order_number": order.order_number,
                            "customer_name": order.customer_name})
            return payload
        return miss("Shipping label — create or select a receiving event for this shipment?",
                    {"tracking_number": value})

    if cls == "order_number":
        order = db.query(CustomerOrder).filter(
            func.upper(CustomerOrder.order_number) == up).first()
        if order:
            payload = _found("customer_orders", order.id, order.order_number,
                             status=order.status, matched_on="order_number")
            payload.update({"class": cls, "display_table": "Customer Orders",
                            "order_number": order.order_number,
                            "customer_name": order.customer_name})
            return payload
        return miss("Order not found.")

    if cls == "unit_pn":
        item = db.query(Item).filter(func.lower(Item.brand_pn) == low).first()
        if item:
            payload = _item_found(db, item, "unit_pn")
            payload["class"] = cls
            return payload
        return miss("Unit PN not in inventory — receive it with the PN prefilled?",
                    {"brand_pn": value})

    if cls == "sku":
        guidance = "That's a SKU, not a unit serial — now scan the unit's serial."
        pn = db.query(ItemPartNumber).filter(
            func.lower(ItemPartNumber.brand_sku) == low).first()
        if pn:
            prefill = {"brand_sku": pn.brand_sku}
            if pn.item_category:
                prefill["item_category"] = str(pn.item_category)
            return recognized(guidance, prefill)
        if db.query(EdgeBox).filter(func.upper(EdgeBox.part_number) == up).first():
            return recognized(guidance, {"brand_sku": value})
        return miss(guidance + " (SKU not in the catalog.)")

    if cls == "hex12":
        hit = find_serial_anywhere(db, value)
        if hit:
            payload = dict(hit)
            payload["device_status"] = payload.pop("status", None)
            payload.update({"status": "already_exists", "class": cls,
                            "matched_on": "serial"})
            return payload
        mac = mac_from_bare_hex(value)
        mac_hit = find_mac_anywhere(db, mac)
        if mac_hit:
            mac_hit["class"] = cls
            return mac_hit
        oui = db.query(OUIAllowlist).filter(
            OUIAllowlist.oui_prefix == mac[:8],
            OUIAllowlist.is_active.is_(True)).first()
        if oui:
            return miss(f"Looks like a {oui.manufacturer} MAC — receive with the MAC prefilled?",
                        {"mac_address": mac}, klass="mac")
        return miss("Serial not found. 12 hex characters — could this be a MAC without separators?")

    if cls == "uscf_serial":
        hit = find_serial_anywhere(db, value)
        if hit:
            payload = dict(hit)
            payload["device_status"] = payload.pop("status", None)
            payload.update({"status": "already_exists", "class": cls,
                            "matched_on": "serial"})
            return payload
        return recognized("New 2026 edge box — confirm intake.",
                          {"target_table": "edge_boxes"})

    if cls == "qnap_candidate":
        hit = find_serial_anywhere(db, value)
        if hit:
            payload = dict(hit)
            payload["device_status"] = payload.pop("status", None)
            payload.update({"status": "already_exists", "class": cls,
                            "matched_on": "serial"})
            return payload
        return recognized("Recognized QNAP serial pattern — confirm before adding.",
                          lookup_by_serial_prefix(value) or
                          {"manufacturer": "QNAP", "target_table": "nas_devices"})

    if cls == "ambiguous_digits":
        hit = find_serial_anywhere(db, value)
        if hit:
            payload = dict(hit)
            payload["device_status"] = payload.pop("status", None)
            payload.update({"status": "already_exists", "class": cls,
                            "matched_on": "serial"})
            return payload
        ev = (
            db.query(ReceivingEvent)
            .filter(func.lower(ReceivingEvent.tracking_number) == low)
            .order_by((ReceivingEvent.status == "open").desc(), ReceivingEvent.id.desc())
            .first()
        )
        if ev:
            return {
                "status": "recognized", "class": cls, "serial": value, "prefill": {},
                "event_id": ev.id,
                "guidance": f"Inbound shipment for receiving event #{ev.id} "
                            f"({ev.vendor or 'Unknown vendor'}) — event selected.",
            }
        item = db.query(Item).filter(func.lower(Item.tracking_number) == low).first()
        if item:
            payload = _item_found(db, item, "tracking")
            payload["class"] = cls
            return payload
        order = db.query(CustomerOrder).filter(
            func.lower(CustomerOrder.tracking_number) == low).first()
        if order:
            payload = _found("customer_orders", order.id, value,
                             status=order.status, matched_on="tracking")
            payload.update({"class": cls, "display_table": "Customer Orders",
                            "order_number": order.order_number,
                            "customer_name": order.customer_name})
            return payload
        return miss("Looks like a product or shipping code (UPC/EAN or carrier tracking) "
                    "— use it as a serial only if the label says so.")

    if cls in ("serial",):
        hit = find_serial_anywhere(db, value)
        if hit:
            payload = dict(hit)
            payload["device_status"] = payload.pop("status", None)
            payload.update({"status": "already_exists", "class": cls,
                            "matched_on": "serial"})
            return payload
        # Deliberately NO lookup_by_serial_prefix here: the loose Q-prefix
        # guess lives exclusively in rule 10 (strict alnum), otherwise a
        # Q-prefixed QR URL sneaks back in as a phantom QNAP (audit F6).
        return miss("Serial not found — fill in the details manually.")

    # empty / unclassified (>100 chars, junk charset)
    return miss("Could not read a usable code from that scan — try manual entry.",
                klass="unclassified")


@router.post("/api/receive/scan")
async def process_scan(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_scan_access),
):
    """Classify a scan via the §4 routing table, look it up, and answer with
    pre-fill data plus class-specific guidance. GS1-128 wrappers are unwrapped
    before classification (AI 21 serial / 01 GTIN / 00 SSCC)."""
    body = await request.json()
    raw = (body.get("barcode") or "").strip()

    if not raw:
        return JSONResponse(status_code=400, content={"error": "Empty barcode"})

    value, gs1 = preprocess(raw)
    if not value:
        return JSONResponse(status_code=400, content={"error": "Empty barcode"})

    cls = classify(value)
    payload = _route_scan(db, cls, value, gs1)
    if gs1:
        payload["gs1"] = {k: v for k, v in gs1.items() if k != "ais"}

    # Pilot-period logging: every non-hit with its raw payload (§8).
    if payload.get("status") != "already_exists":
        logger.warning(
            "scan-routing-pilot: class=%s status=%s raw=%r value=%r user=%s",
            payload.get("class", cls), payload.get("status"),
            raw[:200], value[:120], user.username,
        )
    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# Duplicate check API
# ---------------------------------------------------------------------------

@router.get("/api/receive/check-duplicate")
def check_duplicate_serial(
    serial: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_receiving_access),
):
    """Check if a serial number already exists in any inventory table.

    H14: was any-authenticated — a serial-enumeration oracle for bare
    viewers (audit F15). Only the receive page calls it."""
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
    user: User = Depends(require_receiving_access),
):
    """Submit a scanned device to inventory (direct) or pending review queue.

    Flag-only receiving users can submit (their intake goes to the review
    queue); direct-to-inventory is additionally gated per target table below
    (F9) — same permission as approving the device out of the queue."""
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

        # F9: skipping the review queue is an approval decision — gate it on
        # the same permission approving this device out of pending requires.
        if not user_can_approve_table(user, target_table):
            return JSONResponse(status_code=403, content={
                "error": "Adding this category directly to inventory needs approval rights — "
                         "uncheck 'Add directly to inventory' and submit it to the review queue.",
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
                # H16/H17: tick the event's SKU line + the matching OEM PO
                # line, record the unit↔event link. Never blocks: no match,
                # no SKU, no PO — all silent no-ops.
                unit_sku = part_number or brand_sku
                _record_received_unit(db, event, unit_sku, serial, item_id=item.id)
                sync_oem_receipt(db, event.purchase_order, unit_sku)
                _maybe_autocomplete(event)
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
    pending_event = None
    if event_id:
        pending_event = db.query(ReceivingEvent).filter(
            ReceivingEvent.id == event_id).first()
        if not pending_event:
            event_id = None  # a stale event id must not fail the insert
    pending = PendingDevice(
        mac_address=body.get("mac_address") or body.get("mac_address_1") or f"intake-{serial}",
        hostname=None,  # Hostname is for network-discovered devices only
        manufacturer=body.get("manufacturer", ""),
        suggested_table=target_table or "network_equipment",
        suggested_category=TARGET_TABLE_TO_CATEGORY.get(target_table or "network_equipment"),
        scanner_id=f"intake:{user.username}",
        status="pending",
        serial=serial,
        model=(body.get("model") or "").strip() or None,
        notes=(body.get("notes") or "").strip() or None,
        receiving_event_id=event_id,
    )
    db.add(pending)
    # H15: receiving counts at SUBMIT time for BOTH paths — a pending unit
    # has physically arrived at the dock. Approve no longer increments
    # (double-count) and dismiss gives the count back (pending.py).
    if pending_event:
        pending_event.received_quantity = (pending_event.received_quantity or 0) + 1
        db.flush()  # pending.id for the received_devices link
        unit_sku = (body.get("part_number") or "").strip() or None
        _record_received_unit(db, pending_event, unit_sku, serial,
                              pending_device_id=pending.id)
        sync_oem_receipt(db, pending_event.purchase_order, unit_sku)
        _maybe_autocomplete(pending_event)
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
    user: User = Depends(require_receiving_access),
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
    # H14/F15: intake photos were served to ANY authenticated session by
    # sequential id — now receiving users only.
    user: User = Depends(require_receiving_access),
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
