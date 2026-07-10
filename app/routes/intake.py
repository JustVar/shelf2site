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
from ..database import get_db
from ..models import Item, ItemLocation, ItemReceipt, ReceiptItem, ItemPartNumber, Site
from .dashboard import ALL_CATEGORIES, category_display

router = APIRouter(tags=["intake"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

STATUSES = [
    "Deployed",
    "Ready to Deploy",
    "Pending",
    "Un-deployable",
    "Decommissioned",
    "Unassigned",
]

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


def _get_categories() -> list[dict]:
    cats = [{"value": cat, "display": category_display(cat)} for cat in ALL_CATEGORIES]
    cats.sort(key=lambda c: c["display"])
    return cats


def _safe_float(value: str | None) -> float | None:
    if not value or not value.strip():
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def _safe_int(value: str | None) -> int | None:
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


def _normalize_mac(value: str | None) -> str | None:
    """Normalize MAC address to AA:BB:CC:DD:EE:FF format.
    Accepts: AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, AABB.CCDD.EEFF, AABBCCDDEEFF
    Returns normalized MAC or None if empty. Raises ValueError if invalid.
    """
    if not value or not value.strip():
        return None
    raw = value.strip().upper()
    # Remove all separators
    raw = raw.replace(":", "").replace("-", "").replace(".", "")
    # Should be exactly 12 hex characters
    if len(raw) != 12:
        raise ValueError(f"Invalid MAC address: '{value.strip()}' — must be 6 hex pairs (e.g. AA:BB:CC:DD:EE:FF)")
    # Validate all characters are hex
    try:
        int(raw, 16)
    except ValueError:
        raise ValueError(f"Invalid MAC address: '{value.strip()}' — contains non-hex characters")
    # Format as AA:BB:CC:DD:EE:FF
    return ":".join(raw[i:i+2] for i in range(0, 12, 2))


def _get_part_numbers(db):
    return db.query(ItemPartNumber).order_by(ItemPartNumber.brand_sku).all()


@router.get("/intake", response_class=HTMLResponse)
def intake_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user:
        return RedirectResponse(f"{BP}/login")
    if not user.is_editor_or_above:
        return RedirectResponse(f"{BP}/dashboard")

    locations = _get_locations(db)
    categories = _get_categories()
    part_numbers = _get_part_numbers(db)

    return templates.TemplateResponse("intake.html", {
        "request": request,
        "user": user,
        "locations": locations,
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
    # TODO(vendor-ui): Align vendor_id input with triage fix panel pattern —
    # use type="number" input + hint text. When a vendors table is built, swap
    # both intake and triage to a <select> populated from the table.
    # Currently both accept free text; _safe_int silently coerces non-numeric
    # input to None, causing "saved" toasts with no actual DB change.
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
    if not user or not user.is_editor_or_above:
        return RedirectResponse(f"{BP}/login")

    import logging
    _log = logging.getLogger(__name__)

    # --- Validate MAC addresses ---
    errors = []
    mac1_clean = None
    mac2_clean = None
    try:
        mac1_clean = _normalize_mac(item_mac_address_1)
    except ValueError as e:
        errors.append(str(e))
    try:
        mac2_clean = _normalize_mac(item_mac_address_2)
    except ValueError as e:
        errors.append(str(e))

    if errors:
        locations = _get_locations(db)
        categories = _get_categories()
        return templates.TemplateResponse("intake.html", {
            "request": request,
            "user": user,
            "locations": locations,
            "categories": categories,
            "statuses": STATUSES,
            "part_numbers": _get_part_numbers(db),
            "error": " | ".join(errors),
        })

    # --- Create Item ---
    new_item = Item(
        item_name=_clean_str(item_name),
        item_manufacturer=_clean_str(item_manufacturer),
        item_model=_clean_str(item_model),
        item_sn=_clean_str(item_sn),
        item_category=_clean_str(item_category) or None,
        item_status=_clean_str(item_status) or None,
        location_id=_safe_int(location_id),
        department_or_owner=_clean_str(department_or_owner),
        item_mac_address_1=mac1_clean,
        item_mac_address_2=mac2_clean,
        item_storage_size_gb=_safe_float(item_storage_size_gb),
        appliance_uuid=_clean_str(appliance_uuid),
        brand_sku=_clean_str(brand_sku),
        brand_pn=_clean_str(brand_pn),
        item_associated_brand_pn=_clean_str(item_associated_brand_pn),
        vendor_id=_safe_int(vendor_id),
        item_vendor=_clean_str(item_vendor),
        date_purchased=_safe_date(date_purchased),
        intended_purpose=_clean_str(intended_purpose),
        dispatched_date=_safe_date(dispatched_date),
        tracking_number=_clean_str(tracking_number),
        notes=_clean_str(notes),
    )
    db.add(new_item)
    db.flush()  # get new_item.id before receipt

    # --- Optional Receipt ---
    has_receipt_data = any([
        _clean_str(record_type),
        receipt_file and receipt_file.filename,
    ])

    if has_receipt_data:
        # Save uploaded file if present
        saved_path = None
        original_name = None
        if receipt_file and receipt_file.filename:
            ext = Path(receipt_file.filename).suffix.lower()
            if ext in ALLOWED_RECEIPT_EXTENSIONS:
                unique_name = f"receipt_{date.today().isoformat()}_{uuid.uuid4().hex[:8]}{ext}"
                saved_path = os.path.join(RECEIPT_STORAGE_PATH, unique_name)
                os.makedirs(RECEIPT_STORAGE_PATH, exist_ok=True)
                content = await receipt_file.read()
                with open(saved_path, "wb") as f:
                    f.write(content)
                original_name = receipt_file.filename

        receipt = ItemReceipt(
            vendor_id=_safe_int(vendor_id),
            purchase_order=_clean_str(purchase_order),
            record_type=_clean_str(record_type) or "receipt",
            transaction_date=_safe_date(date_purchased) or date.today(),
            file_path=saved_path,
            original_filename=original_name,
            notes=_clean_str(receipt_notes),
            created_by=user.display_name or user.username,
        )
        db.add(receipt)
        db.flush()

        receipt_link = ReceiptItem(
            receipt_id=receipt.id,
            item_id=new_item.id,
            quantity=1,
        )
        db.add(receipt_link)

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
            "categories": categories,
            "statuses": STATUSES,
            "part_numbers": _get_part_numbers(db),
            "error": f"Failed to save: {e}",
        }, status_code=500)

    # Redirect to inventory with success message via query param
    return RedirectResponse(
        f"{BP}/inventory/?toast=Item+created+successfully",
        status_code=303,
    )
