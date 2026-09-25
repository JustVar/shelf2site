"""
Intake page — manual item entry form with optional receipt upload.
Phase 1: Manual form, no barcode scanning.
"""

from pathlib import Path
from datetime import date
import uuid
import os

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from ..auth import get_current_user, User
from ..config import settings
from ..localtime import local_today, register
from ..toast_redirect import toast_redirect
from ..database import get_db
from ..models import Item, ItemLocation, ItemReceipt, ReceiptItem, ItemPartNumber, Site, VendorProfile, HAND_EDITABLE_ITEM_STATUSES
from .dashboard import ALL_CATEGORIES, category_display

router = APIRouter(tags=["intake"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)

# Derived from the item_statuses enum (docs/specs/item-decommission.md):
# the hand-editable vocabulary, the enum minus code-managed statuses.
STATUSES = list(HAND_EDITABLE_ITEM_STATUSES)

ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".pdf", ".eml", ".msg", ".html"}
RECEIPT_STORAGE_PATH = "/app/data/receipts"


def _get_locations(db: Session) -> list[dict]:
    # Migration 063: places live in sites. In-stock items sit at OFFICE
    # places (never a customer_site), so the intake/receive stock select
    # excludes customer sites.
    rows = (
        db.query(Site)
        .filter(Site.is_active == True, Site.site_type != "customer_site")
        .order_by(Site.name)
        .all()
    )
    return [{"id": r.id, "name": r.name} for r in rows]


def _get_all_places(db: Session) -> list[dict]:
    """All places (offices + customer sites). For surfaces that must show a
    unit's CURRENT place regardless of type (item detail, exports) - a
    type-filtered list would drop a deployed unit's customer site and a
    full-form save would then blank location_id."""
    rows = db.query(Site).order_by(Site.name).all()
    return [{"id": r.id, "name": r.name} for r in rows]


def _get_vendors(db: Session) -> list[dict]:
    """Vendor profiles for the vendor selects (N11). The pretty name wins
    when display_name is set; the ordering stays on name so the list is
    stable whether or not a profile has one.
    """
    rows = db.query(VendorProfile).order_by(VendorProfile.name).all()
    return [{"id": r.id, "name": r.display_name or r.name} for r in rows]


def _vendor_id_or_error(db: Session, value) -> tuple[int | None, str | None]:
    """Validate a submitted vendor_id against vendor_profiles (migration 075).

    Blank clears the link. Anything that is not an existing profile id is an
    error the user sees, never a silent NULL, which is what the free-text
    input used to do through _safe_int.
    """
    if value is None:
        return (None, None)
    if isinstance(value, str) and not value.strip():
        return (None, None)
    try:
        vendor_id = int(str(value).strip())
    except ValueError:
        return (None, "Vendor must be chosen from the list")
    exists = (db.query(VendorProfile.id)
              .filter(VendorProfile.id == vendor_id)
              .first())
    if not exists:
        return (None, "Vendor must be chosen from the list")
    return (vendor_id, None)


def _get_categories() -> list[dict]:
    cats = [{"value": cat, "display": category_display(cat)} for cat in ALL_CATEGORIES]
    cats.sort(key=lambda c: c["display"])
    return cats


def _safe_float(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not value or not value.strip():
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def _safe_int(value) -> int | None:
    if isinstance(value, int):
        return value
    if not value or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _safe_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _clean_str(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    return value.strip()


# Canonical implementation lives in app.validation; the old local name is kept
# because item_detail, triage and inventory import _normalize_mac from here.
from ..validation import normalize_mac as _normalize_mac


def _get_part_numbers(db):
    return db.query(ItemPartNumber).order_by(ItemPartNumber.brand_sku).all()


def create_item(
    db: Session,
    *,
    fields: dict,
    created_by: str,
    receipt: dict | None = None,
    attributes: dict | None = None,
) -> Item:
    """Shared item_schema create path — the intake form and scan intake
    (app/routes/receiving.py, audit H2) both land here so every item is
    normalized identically and gets the same receipt paper trail.

    ``fields`` holds raw values keyed by Item column names; normalization
    (_clean_str / _safe_* / normalize_mac) happens HERE. Flushes but does
    NOT commit — callers own the transaction. Raises ValueError listing
    every invalid MAC (matching the old intake behavior of showing both).
    """
    mac_errors = []
    mac1 = mac2 = None
    try:
        mac1 = _normalize_mac(fields.get("item_mac_address_1"))
    except ValueError as e:
        mac_errors.append(str(e))
    try:
        mac2 = _normalize_mac(fields.get("item_mac_address_2"))
    except ValueError as e:
        mac_errors.append(str(e))
    if mac_errors:
        raise ValueError(" | ".join(mac_errors))

    _status = _clean_str(fields.get("item_status")) or None
    if _status == "Decommissioned":
        # Code-mediated (docs/specs/item-decommission.md): never on create.
        _status = None

    new_item = Item(
        item_name=_clean_str(fields.get("item_name")),
        item_manufacturer=_clean_str(fields.get("item_manufacturer")),
        item_model=_clean_str(fields.get("item_model")),
        item_sn=_clean_str(fields.get("item_sn")),
        item_category=_clean_str(fields.get("item_category")) or None,
        item_status=_status,
        location_id=_safe_int(fields.get("location_id")),
        department_or_owner=_clean_str(fields.get("department_or_owner")),
        item_mac_address_1=mac1,
        item_mac_address_2=mac2,
        item_storage_size_gb=_safe_float(fields.get("item_storage_size_gb")),
        appliance_uuid=_clean_str(fields.get("appliance_uuid")),
        brand_sku=_clean_str(fields.get("brand_sku")),
        brand_pn=_clean_str(fields.get("brand_pn")),
        item_associated_brand_pn=_clean_str(fields.get("item_associated_brand_pn")),
        vendor_id=_safe_int(fields.get("vendor_id")),
        item_vendor=_clean_str(fields.get("item_vendor")),
        date_purchased=_safe_date(fields.get("date_purchased")),
        intended_purpose=_clean_str(fields.get("intended_purpose")),
        dispatched_date=_safe_date(fields.get("dispatched_date")),
        tracking_number=_clean_str(fields.get("tracking_number")),
        notes=_clean_str(fields.get("notes")),
        attributes=attributes or None,
    )
    db.add(new_item)
    db.flush()  # id needed for the receipt link

    if receipt:
        receipt_row = ItemReceipt(
            vendor_id=_safe_int(receipt.get("vendor_id")),
            purchase_order=_clean_str(receipt.get("purchase_order")),
            record_type=_clean_str(receipt.get("record_type")) or "receipt",
            transaction_date=receipt.get("transaction_date") or local_today(),
            file_path=receipt.get("file_path"),
            original_filename=receipt.get("original_filename"),
            notes=_clean_str(receipt.get("notes")),
            created_by=created_by,
        )
        db.add(receipt_row)
        db.flush()
        db.add(ReceiptItem(
            receipt_id=receipt_row.id,
            item_id=new_item.id,
            quantity=1,
        ))

    return new_item


@router.get("/intake", response_class=HTMLResponse)
def intake_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_editor_or_above:
        return RedirectResponse(f"{BP}/dashboard")

    locations = _get_locations(db)
    categories = _get_categories()
    part_numbers = _get_part_numbers(db)

    return templates.TemplateResponse("intake.html", {
        "request": request,
        "user": user,
        "locations": locations,
        "vendors": _get_vendors(db),
        "categories": categories,
        "statuses": STATUSES,
        "part_numbers": part_numbers,
    })


@router.post("/intake", response_class=HTMLResponse)
async def intake_submit(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    # --- Item fields ---
    item_name: str = Form(default=""),
    item_manufacturer: str = Form(default=""),
    item_model: str = Form(default=""),
    item_sn: str = Form(default=""),
    item_category: str = Form(default=""),
    item_status: str = Form(default=""),
    location_id: str = Form(default=""),
    department_or_owner: str = Form(default=""),
    item_mac_address_1: str = Form(default=""),
    item_mac_address_2: str = Form(default=""),
    item_storage_size_gb: str = Form(default=""),
    appliance_uuid: str = Form(default=""),
    brand_sku: str = Form(default=""),
    brand_pn: str = Form(default=""),
    item_associated_brand_pn: str = Form(default=""),
    # vendor_id is a vendor_profiles id from a select, validated by _vendor_id_or_error.
    vendor_id: str = Form(default=""),
    item_vendor: str = Form(default=""),
    date_purchased: str = Form(default=""),
    intended_purpose: str = Form(default=""),
    dispatched_date: str = Form(default=""),
    tracking_number: str = Form(default=""),
    notes: str = Form(default=""),
    # --- Receipt fields ---
    receipt_file: UploadFile = File(default=None),
    record_type: str = Form(default=""),
    purchase_order: str = Form(default=""),
    receipt_notes: str = Form(default=""),
):
    if not user.is_editor_or_above:
        return toast_redirect(f"{BP}/dashboard", "Not permitted: editor access required", "warning")

    import logging
    _log = logging.getLogger(__name__)

    # N11: validate the vendor before anything is built, so the receipt payload
    # and the item both carry a real vendor_profiles id or nothing.
    vendor_value, vendor_err = _vendor_id_or_error(db, vendor_id)

    # --- Optional receipt upload (async read stays in the route) ---
    has_receipt_data = any([
        _clean_str(record_type),
        receipt_file and receipt_file.filename,
    ])

    receipt_payload = None
    if has_receipt_data:
        saved_path = None
        original_name = None
        if receipt_file and receipt_file.filename:
            ext = Path(receipt_file.filename).suffix.lower()
            if ext in ALLOWED_RECEIPT_EXTENSIONS:
                unique_name = f"receipt_{local_today().isoformat()}_{uuid.uuid4().hex[:8]}{ext}"
                saved_path = os.path.join(RECEIPT_STORAGE_PATH, unique_name)
                os.makedirs(RECEIPT_STORAGE_PATH, exist_ok=True)
                content = await receipt_file.read()
                with open(saved_path, "wb") as f:
                    f.write(content)
                original_name = receipt_file.filename

        receipt_payload = {
            "vendor_id": vendor_value,
            "purchase_order": purchase_order,
            "record_type": record_type,
            "transaction_date": _safe_date(date_purchased) or local_today(),
            "file_path": saved_path,
            "original_filename": original_name,
            "notes": receipt_notes,
        }

    # --- Create Item (+ optional receipt) via the shared path ---
    try:
        # Minimum required fields: an empty submit must not create a row.
        # This was the "ghost item" class — all-NULL name/category/serial
        # rows (e.g. item 39) that only the triage page ever surfaced.
        if not (item_name or "").strip() or not (item_category or "").strip():
            raise ValueError("Item name and category are required")
        if vendor_err:
            raise ValueError(vendor_err)
        create_item(
            db,
            fields={
                "item_name": item_name,
                "item_manufacturer": item_manufacturer,
                "item_model": item_model,
                "item_sn": item_sn,
                "item_category": item_category,
                "item_status": item_status,
                "location_id": location_id,
                "department_or_owner": department_or_owner,
                "item_mac_address_1": item_mac_address_1,
                "item_mac_address_2": item_mac_address_2,
                "item_storage_size_gb": item_storage_size_gb,
                "appliance_uuid": appliance_uuid,
                "brand_sku": brand_sku,
                "brand_pn": brand_pn,
                "item_associated_brand_pn": item_associated_brand_pn,
                "vendor_id": vendor_value,
                "item_vendor": item_vendor,
                "date_purchased": date_purchased,
                "intended_purpose": intended_purpose,
                "dispatched_date": dispatched_date,
                "tracking_number": tracking_number,
                "notes": notes,
            },
            created_by=user.display_name or user.username,
            receipt=receipt_payload,
        )
    except ValueError as e:
        locations = _get_locations(db)
        categories = _get_categories()
        return templates.TemplateResponse("intake.html", {
            "request": request,
            "user": user,
            "locations": locations,
            "vendors": _get_vendors(db),
            "categories": categories,
            "statuses": STATUSES,
            "part_numbers": _get_part_numbers(db),
            "error": str(e),
        }, status_code=400)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        _log.error(f"Intake submit failed: {e}", exc_info=True)
        locations = _get_locations(db)
        categories = _get_categories()
        return templates.TemplateResponse("intake.html", {
            "request": request,
            "user": user,
            "locations": locations,
            "vendors": _get_vendors(db),
            "categories": categories,
            "statuses": STATUSES,
            "part_numbers": _get_part_numbers(db),
            "error": f"Failed to save: {e}",
        }, status_code=500)

    # Redirect to inventory with success message via query param
    return toast_redirect(f"{BP}/inventory/", "Item created successfully")
