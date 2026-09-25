"""
Item Detail page — view, edit, and manage a single inventory item.
"""

from pathlib import Path
import uuid
import os
import logging

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, Query
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth import get_current_user, require_editor, User
from ..config import settings
from ..localtime import local_today, register
from ..toast_redirect import toast_redirect
from ..database import get_db
from ..models import (
    CustomerOrder, Item, ItemLocation, ItemReceipt, ReceiptItem, ItemCheckout,
    DeviceProvisioning, ItemComponentHistory, ItemMaintenanceLog,
    UnitPhoto, UnitPhotoItem, User as UserModel,
)
from ..locks import get_lock
from ..delete_requests import LOCK_MESSAGE, item_blockers, locked_ids, pending_for
from ..audit import log_event
from .dashboard import FL_CATEGORY_COLORS, ALL_CATEGORIES, category_display
from .intake import (
    STATUSES, ALLOWED_RECEIPT_EXTENSIONS, RECEIPT_STORAGE_PATH,
    _get_locations, _get_all_places, _get_categories, _normalize_mac,
    _clean_str, _safe_float, _safe_int, _safe_date, _get_vendors, _vendor_id_or_error,
)
from ..item_fields import attributes_for

_log = logging.getLogger(__name__)

router = APIRouter(tags=["item_detail"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


def _get_item_photos(db, item_id, user):
    """Chronological unit photos for one item (shipment-photos slice).
    Photos on sensitive orders are masked for non-privileged users — the
    same composition the API and dossier apply."""
    photos = (
        db.query(UnitPhoto)
        .join(UnitPhotoItem, UnitPhotoItem.photo_id == UnitPhoto.id)
        .filter(UnitPhotoItem.item_id == item_id, UnitPhoto.is_hidden.is_(False))
        .order_by(UnitPhoto.taken_at.asc(), UnitPhoto.id.asc())
        .all()
    )
    visible = []
    for p in photos:
        if p.customer_order_id and not user.has_sensitive_customers_access:
            o = db.query(CustomerOrder).filter(
                CustomerOrder.id == p.customer_order_id).first()
            if o and o.is_sensitive:
                continue
        visible.append(p)
    names = {u.id: u.display_name for u in db.query(UserModel).filter(
        UserModel.id.in_({p.uploaded_by for p in visible if p.uploaded_by} or {0})).all()}
    return [{
        "id": p.id,
        "thumb_url": f"{BP}/api/photos/{p.id}/thumb",
        "file_url": f"{BP}/api/photos/{p.id}/file",
        "direction": p.direction,
        "caption": p.caption,
        "taken_at": p.taken_at,
        "uploaded_by": names.get(p.uploaded_by),
    } for p in visible]


def _get_item_receipts(db, item_id):
    rows = (
        db.query(ItemReceipt, ReceiptItem)
        .join(ReceiptItem, ReceiptItem.receipt_id == ItemReceipt.id)
        .filter(ReceiptItem.item_id == item_id)
        .order_by(ItemReceipt.transaction_date.desc())
        .all()
    )
    results = []
    for receipt, link in rows:
        results.append({
            "id": receipt.id,
            "record_type": receipt.record_type or "\u2014",
            "transaction_date": receipt.transaction_date,
            "purchase_order": receipt.purchase_order or "\u2014",
            "file_path": receipt.file_path,
            "original_filename": receipt.original_filename,
            "vendor_id": receipt.vendor_id,
            "notes": receipt.notes,
            "created_by": receipt.created_by,
            "created_at": receipt.created_at,
            "quantity": link.quantity,
        })
    return results


def _get_component_history(db, item_id):
    """Both-direction event log, newest first (same-day ties broken by id —
    action_date is DATE), with the counterpart item resolved so the panel
    can say WHICH unit/component each event involved."""
    rows = (
        db.query(ItemComponentHistory)
        .filter(
            (ItemComponentHistory.item_id == item_id) |
            (ItemComponentHistory.parent_item_id == item_id)
        )
        .order_by(ItemComponentHistory.action_date.desc(),
                  ItemComponentHistory.id.desc())
        .all()
    )
    other_ids = set()
    for r in rows:
        other_ids.add(r.parent_item_id if r.item_id == item_id else r.item_id)
    other_ids.discard(None)
    names = {}
    if other_ids:
        for it in db.query(Item).filter(Item.id.in_(list(other_ids))).all():
            names[it.id] = it.item_name or it.item_sn or f"item #{it.id}"
    enriched = []
    for r in rows:
        as_component = (r.item_id == item_id)
        counterpart_id = r.parent_item_id if as_component else r.item_id
        enriched.append({
            "event": r,
            "as_component": as_component,
            "counterpart_id": counterpart_id,
            "counterpart_name": names.get(counterpart_id) if counterpart_id else None,
        })
    return enriched


def _get_containment(db, item):
    """Containment context (Option A): current parent for components,
    current children for units — always via the current_containment view."""
    from ..containment import UNIT_CATEGORIES, get_current_parent, get_current_children
    ctx = {
        "parent": None,
        "children": [],
        "is_unit": str(item.item_category) in UNIT_CATEGORIES if item.item_category else False,
        "is_installed": False,
    }
    parent = get_current_parent(db, item.id)
    if parent:
        ctx["parent"] = parent
        ctx["is_installed"] = True
    if ctx["is_unit"]:
        ctx["children"] = get_current_children(db, item.id)
    return ctx


def _get_maintenance_log(db, item_id):
    rows = (
        db.query(ItemMaintenanceLog)
        .filter(ItemMaintenanceLog.item_id == item_id)
        .order_by(ItemMaintenanceLog.maintenance_date.desc())
        .all()
    )
    return rows


def _get_item_checkouts(db, item_id):
    """Full custody history for an item, newest first, recipient resolved."""
    rows = (
        db.query(ItemCheckout, User)
        .outerjoin(User, User.id == ItemCheckout.checked_out_to_user_id)
        .filter(ItemCheckout.item_id == item_id)
        .order_by(ItemCheckout.checkout_date.desc(), ItemCheckout.id.desc())
        .all()
    )
    out = []
    for co, u in rows:
        out.append({
            "checkout_date": co.checkout_date,
            "checkin_date": co.checkin_date,
            "prior_status": co.prior_status,
            "checked_out_by": co.checked_out_by,
            "recipient": (u.display_name if u else None) or co.checked_out_to_name or "—",
            "is_open": co.checkin_date is None,
            "notes": co.notes,
        })
    return out


@router.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail_page(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    edit: str = Query(default=""),
):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return toast_redirect(f"{BP}/inventory/", "Item not found", "error")

    # Lock check: pass existing_lock to template; gate entry into edit mode.
    existing_lock = get_lock(f"items:{item_id}")
    if edit == "1" and existing_lock and existing_lock.get("user_id") != user.id:
        holder = existing_lock.get("display_name") or "another user"
        return toast_redirect(f"{BP}/items/{item_id}", "This item is being edited by " + holder, "warning")

    locations = _get_all_places(db)
    loc_map = {r["id"]: r["name"] for r in locations}
    categories = _get_categories()
    vendors = _get_vendors(db)
    vendor_name = next((v["name"] for v in vendors if v["id"] == item.vendor_id), None)
    receipts = _get_item_receipts(db, item_id)
    components = _get_component_history(db, item_id)
    maintenance = _get_maintenance_log(db, item_id)
    checkouts = _get_item_checkouts(db, item_id)
    containment = _get_containment(db, item)
    photos = _get_item_photos(db, item_id, user)
    _parent_item = containment["parent"]["parent"] if containment["parent"] else None
    effective_location_id = _parent_item.location_id if _parent_item else item.location_id
    delete_request = pending_for(db, "items", item_id)
    delete_blockers = (item_blockers(db, item_id)
                       if user.is_editor_or_above and not delete_request else [])

    return templates.TemplateResponse("item_detail.html", {
        "request": request,
        "user": user,
        "item": item,
        "containment": containment,
        "location_name": loc_map.get(effective_location_id, "\u2014"),
        "locations": locations,
        "vendors": vendors,
        "vendor_name": vendor_name,
        "categories": categories,
        "statuses": STATUSES,
        "color": FL_CATEGORY_COLORS.get(str(item.item_category), "#888888"),
        "category_display": category_display(item.item_category) if item.item_category else "\u2014",
        "attribute_fields": attributes_for(item.item_category),
        "receipts": receipts,
        "components": components,
        "maintenance": maintenance,
        "checkouts": checkouts,
        "photos": photos,
        "is_checked_out": item.item_status == "Checked Out",
        "edit_mode": edit == "1",
        "existing_lock": existing_lock,
        "delete_request": delete_request,
        "delete_blockers": delete_blockers,
    })


@router.get("/items/{item_id}/edit", response_class=HTMLResponse)
def item_edit_redirect(request: Request, item_id: int):
    return RedirectResponse(f"{BP}/items/{item_id}?edit=1", status_code=303)


@router.post("/items/{item_id}", response_class=HTMLResponse)
async def item_update(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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
    vendor_id: str = Form(default=""),
    item_vendor: str = Form(default=""),
    date_purchased: str = Form(default=""),
    intended_purpose: str = Form(default=""),
    dispatched_date: str = Form(default=""),
    tracking_number: str = Form(default=""),
    notes: str = Form(default=""),
):
    if not user.is_editor_or_above:
        return toast_redirect(f"{BP}/items/{item_id}", "Not permitted: editor access required", "warning")

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return toast_redirect(f"{BP}/inventory/", "Item not found", "error")
    if locked_ids(db, "items", [item_id]):
        return toast_redirect(f"{BP}/items/{item_id}", LOCK_MESSAGE, "warning")

    # Lock enforcement: reject the save if another user currently holds the lock.
    lock = get_lock(f"items:{item_id}")
    if lock and lock.get("user_id") != user.id:
        holder = lock.get("display_name") or "another user"
        _log.warning(
            "Item %d save blocked: locked by %s (user_id=%s), attempted by %s (user_id=%s)",
            item_id, holder, lock.get("user_id"), user.display_name, user.id,
        )
        return toast_redirect(f"{BP}/items/{item_id}", "This item is being edited by " + holder, "warning")

    errors = []
    mac1_clean = None
    mac2_clean = None
    vendor_value, vendor_err = _vendor_id_or_error(db, vendor_id)
    if vendor_err:
        errors.append(vendor_err)
    try:
        mac1_clean = _normalize_mac(item_mac_address_1)
    except ValueError as e:
        errors.append(str(e))
    try:
        mac2_clean = _normalize_mac(item_mac_address_2)
    except ValueError as e:
        errors.append(str(e))

    if errors:
        locations = _get_all_places(db)
        categories = _get_categories()
        vendors = _get_vendors(db)
        loc_map = {r["id"]: r["name"] for r in locations}
        receipts = _get_item_receipts(db, item_id)
        components = _get_component_history(db, item_id)
        maintenance = _get_maintenance_log(db, item_id)
        checkouts = _get_item_checkouts(db, item_id)
        containment = _get_containment(db, item)
        _parent_item = containment["parent"]["parent"] if containment["parent"] else None
        effective_location_id = _parent_item.location_id if _parent_item else item.location_id
        return templates.TemplateResponse("item_detail.html", {
            "request": request,
            "user": user,
            "item": item,
            "containment": containment,
            "location_name": loc_map.get(effective_location_id, "\u2014"),
            "locations": locations,
            "vendors": vendors,
            "categories": categories,
            "statuses": STATUSES,
            "color": FL_CATEGORY_COLORS.get(str(item.item_category), "#888888"),
            "category_display": category_display(item.item_category) if item.item_category else "\u2014",
            "attribute_fields": attributes_for(item.item_category),
            "receipts": receipts,
            "components": components,
            "maintenance": maintenance,
            "checkouts": checkouts,
            "photos": _get_item_photos(db, item_id, user),
            "is_checked_out": item.item_status == "Checked Out",
            "edit_mode": True,
            "existing_lock": None,
            "error": " | ".join(errors),
        })

    # Containment-managed items (Option A): item_status is set by the
    # install/uninstall routes and the stored location is frozen (the
    # effective place follows the parent unit). The edit UI disables these
    # fields; this guard backs it server-side so a form save can never
    # dislodge them.
    if item.item_status == "Installed":
        item_status = item.item_status
        location_id = str(item.location_id) if item.location_id is not None else ""

    # Decommissioned is code-mediated (docs/specs/item-decommission.md):
    # entered and left only through the decommission and reactivate
    # actions. A form save can neither set nor clear it.
    if item.item_status == "Decommissioned" or _clean_str(item_status) == "Decommissioned":
        item_status = str(item.item_status) if item.item_status else ""

    item.item_name = _clean_str(item_name)
    item.item_manufacturer = _clean_str(item_manufacturer)
    item.item_model = _clean_str(item_model)
    item.item_sn = _clean_str(item_sn)
    item.item_category = _clean_str(item_category) or None
    item.item_status = _clean_str(item_status) or None
    item.location_id = _safe_int(location_id)
    item.department_or_owner = _clean_str(department_or_owner)
    item.item_mac_address_1 = mac1_clean
    item.item_mac_address_2 = mac2_clean
    item.item_storage_size_gb = _safe_float(item_storage_size_gb)
    item.appliance_uuid = _clean_str(appliance_uuid)
    item.brand_sku = _clean_str(brand_sku)
    item.brand_pn = _clean_str(brand_pn)
    item.item_associated_brand_pn = _clean_str(item_associated_brand_pn)
    item.vendor_id = vendor_value
    item.item_vendor = _clean_str(item_vendor)
    item.date_purchased = _safe_date(date_purchased)
    item.intended_purpose = _clean_str(intended_purpose)
    item.dispatched_date = _safe_date(dispatched_date)
    item.tracking_number = _clean_str(tracking_number)
    item.notes = _clean_str(notes)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        _log.error(f"Item update failed: {e}", exc_info=True)
        return toast_redirect(f"{BP}/items/{item_id}", "Update failed", "error")

    return toast_redirect(f"{BP}/items/{item_id}", "Item updated successfully")


@router.post("/items/{item_id}/receipt", response_class=HTMLResponse)
async def add_receipt(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    receipt_file: UploadFile = File(default=None),
    record_type: str = Form(default=""),
    purchase_order: str = Form(default=""),
    receipt_notes: str = Form(default=""),
):
    if not user.is_editor_or_above:
        return toast_redirect(f"{BP}/items/{item_id}", "Not permitted: editor access required", "warning")

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return toast_redirect(f"{BP}/inventory/", "Item not found", "error")
    if locked_ids(db, "items", [item_id]):
        return toast_redirect(f"{BP}/items/{item_id}", LOCK_MESSAGE, "warning")

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

    receipt = ItemReceipt(
        vendor_id=item.vendor_id,
        purchase_order=_clean_str(purchase_order),
        record_type=_clean_str(record_type) or "receipt",
        transaction_date=item.date_purchased or local_today(),
        file_path=saved_path,
        original_filename=original_name,
        notes=_clean_str(receipt_notes),
        created_by=user.display_name or user.username,
    )
    db.add(receipt)
    db.flush()

    link = ReceiptItem(
        receipt_id=receipt.id,
        item_id=item_id,
        quantity=1,
    )
    db.add(link)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        _log.error(f"Receipt add failed: {e}", exc_info=True)
        return toast_redirect(f"{BP}/items/{item_id}", "Receipt upload failed", "error")

    return toast_redirect(f"{BP}/items/{item_id}", "Receipt added successfully")


@router.get("/api/receipts/{receipt_id}/download")
def download_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    receipt = db.query(ItemReceipt).filter(ItemReceipt.id == receipt_id).first()
    if not receipt or not receipt.file_path:
        return HTMLResponse("File not found", status_code=404)

    if not os.path.exists(receipt.file_path):
        return HTMLResponse("File not found on disk", status_code=404)

    return FileResponse(
        path=receipt.file_path,
        filename=receipt.original_filename or os.path.basename(receipt.file_path),
        media_type="application/octet-stream",
    )


@router.post("/items/{item_id}/decommission")
def item_decommission(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
    reason: str = Form(default=""),
    decommission_date: str = Form(default=""),
):
    """Decommission an item (docs/specs/item-decommission.md): reason, date
    and the acting user are all required; refused while the item has an
    active order link (a device_provisioning row not yet returned)."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)
    if locked_ids(db, "items", [item_id]):
        return JSONResponse({"error": LOCK_MESSAGE}, status_code=409)
    if str(item.item_status) == "Decommissioned":
        return JSONResponse({"error": "Item is already decommissioned"}, status_code=409)

    if str(item.item_status) in ("Checked Out", "Installed"):
        # Custody and containment own these states: a later checkin or
        # uninstall would silently overwrite Decommissioned otherwise.
        return JSONResponse({
            "error": "Item is checked out or installed. Check it in or uninstall it before decommissioning.",
        }, status_code=409)

    reason = (reason or "").strip()
    if not reason:
        return JSONResponse({"error": "A reason is required to decommission"}, status_code=400)
    dec_date = _safe_date(decommission_date)
    if dec_date is None:
        return JSONResponse(
            {"error": "A valid decommission date (YYYY-MM-DD) is required"},
            status_code=400)

    active_link = db.query(DeviceProvisioning.id).filter(
        DeviceProvisioning.item_id == item_id,
        DeviceProvisioning.returned_date.is_(None),
    ).first()
    if active_link:
        return JSONResponse({
            "error": "Item is on an order. Remove the unit from the order or record its return first.",
        }, status_code=409)

    who = user.display_name or user.username
    item.item_status = "Decommissioned"
    item.decommission_reason = reason
    item.decommission_date = dec_date
    item.decommissioned_by = who
    # Commit before log_event: log_event returns WITHOUT committing for
    # svc_ accounts, and the status change must not depend on it.
    db.commit()
    log_event(
        db, "item_decommissioned", request=request,
        target_table="items", target_id=item.id,
        new_values={"reason": reason, "date": dec_date.isoformat(), "who": who},
    )
    from ..sidebar_cache import invalidate_sidebar_counts
    invalidate_sidebar_counts()
    return JSONResponse({"ok": True})


@router.post("/items/{item_id}/reactivate")
def item_reactivate(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
    reason: str = Form(default=""),
):
    """Reverse a decommission (docs/specs/item-decommission.md). The item
    returns to Pending: neutral, and implies re-triage rather than a
    readiness it does not have."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)
    if locked_ids(db, "items", [item_id]):
        return JSONResponse({"error": LOCK_MESSAGE}, status_code=409)
    if str(item.item_status) != "Decommissioned":
        return JSONResponse({"error": "Item is not decommissioned"}, status_code=409)

    reason = (reason or "").strip()
    if not reason:
        return JSONResponse({"error": "A reason is required to reactivate"}, status_code=400)

    who = user.display_name or user.username
    item.item_status = "Pending"
    item.decommission_reason = None
    item.decommission_date = None
    item.decommissioned_by = None
    db.commit()
    log_event(
        db, "item_reactivated", request=request,
        target_table="items", target_id=item.id,
        new_values={"reason": reason, "who": who},
    )
    from ..sidebar_cache import invalidate_sidebar_counts
    invalidate_sidebar_counts()
    return JSONResponse({"ok": True})
