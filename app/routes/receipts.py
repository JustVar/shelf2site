"""Receipts viewer (read-only).

Browse the procurement receipts captured at intake, filter them, open a receipt to see its line
items, and view or download the uploaded receipt file. Every route is gated to users with the
Receipts permission (require_receipts). Read-only: no create/edit/delete, no customer invoicing/pricing.
"""

import os
import uuid
from datetime import date as _date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_receipts, User
from ..config import settings
from ..toast_redirect import toast_redirect
from ..csrf import require_csrf
from ..database import get_db
from ..models import Item, ItemReceipt, ReceiptItem, VendorProfile
from .intake import ALLOWED_RECEIPT_EXTENSIONS, RECEIPT_STORAGE_PATH

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


def _vendor_map(db: Session) -> dict:
    """vendor_profiles.id -> display name (display_name preferred, else name)."""
    return {v.id: (v.display_name or v.name) for v in db.query(VendorProfile).all()}


def _parse_date(s: str):
    try:
        return _date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


@router.get("/receipts", response_class=HTMLResponse)
def receipts_list(
    request: Request,
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    vendor: str = Query(default=""),
    record_type: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_receipts),
):
    """List procurement receipts (newest first) with server-side filters."""
    vmap = _vendor_map(db)

    q = db.query(ItemReceipt)
    df, dt = _parse_date(date_from), _parse_date(date_to)
    if df:
        q = q.filter(ItemReceipt.transaction_date >= df)
    if dt:
        q = q.filter(ItemReceipt.transaction_date <= dt)
    if vendor == "unknown":
        q = q.filter(ItemReceipt.vendor_id.is_(None))
    elif vendor:
        try:
            q = q.filter(ItemReceipt.vendor_id == int(vendor))
        except ValueError:
            pass
    if record_type:
        q = q.filter(ItemReceipt.record_type == record_type)

    receipts = q.order_by(ItemReceipt.transaction_date.desc(), ItemReceipt.id.desc()).all()

    # line-item counts in one query
    rids = [r.id for r in receipts]
    counts = {}
    if rids:
        for rid, c in (
            db.query(ReceiptItem.receipt_id, func.count(ReceiptItem.id))
            .filter(ReceiptItem.receipt_id.in_(rids))
            .group_by(ReceiptItem.receipt_id)
            .all()
        ):
            counts[rid] = c

    rows = [{
        "id": r.id,
        "transaction_date": r.transaction_date,
        "vendor_name": (vmap.get(r.vendor_id) if r.vendor_id else None),
        "record_type": r.record_type,
        "purchase_order": r.purchase_order,
        "line_count": counts.get(r.id, 0),
        "has_file": bool(r.file_path),
        "created_by": r.created_by,
    } for r in receipts]

    # filter dropdown options from ALL receipts (not just the filtered set)
    all_rows = db.query(ItemReceipt.vendor_id, ItemReceipt.record_type).all()
    present_vendor_ids = sorted({v for (v, _) in all_rows if v is not None})
    vendor_options = [
        {"value": str(vid), "label": vmap.get(vid, "Vendor %d" % vid)} for vid in present_vendor_ids
    ]
    has_unknown_vendor = any(v is None for (v, _) in all_rows)
    record_type_options = sorted({rt for (_, rt) in all_rows if rt})

    ctx = {
        "request": request,
        "user": user,
        "rows": rows,
        "total": len(rows),
        "vendor_options": vendor_options,
        "has_unknown_vendor": has_unknown_vendor,
        "record_type_options": record_type_options,
        "f": {"date_from": date_from, "date_to": date_to, "vendor": vendor, "record_type": record_type},
    }
    return templates.TemplateResponse("receipts_list.html", ctx)


@router.get("/receipts/{receipt_id}", response_class=HTMLResponse)
def receipt_detail(
    receipt_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_receipts),
):
    """One receipt: header, line items, and the uploaded file inline."""
    rec = db.query(ItemReceipt).filter(ItemReceipt.id == receipt_id).first()
    if not rec:
        return HTMLResponse("Receipt not found.", status_code=404)

    vmap = _vendor_map(db)
    lines = []
    for ri in (
        db.query(ReceiptItem).filter(ReceiptItem.receipt_id == rec.id)
        .order_by(ReceiptItem.id.asc()).all()
    ):
        item = db.query(Item).filter(Item.id == ri.item_id).first()
        lines.append({
            "item_id": ri.item_id,
            "item_name": (item.item_name if item and item.item_name else None),
            "brand_sku": (item.brand_sku if item else None),
            "item_sn": (item.item_sn if item else None),
            "quantity": ri.quantity,
            "notes": ri.notes,
        })

    fp = str(rec.file_path).lower() if rec.file_path else ""
    header = {
        "id": rec.id,
        "vendor_name": (vmap.get(rec.vendor_id) if rec.vendor_id else None),
        "purchase_order": rec.purchase_order,
        "record_type": rec.record_type,
        "transaction_date": rec.transaction_date,
        "original_filename": rec.original_filename,
        "notes": rec.notes,
        "created_by": rec.created_by,
        "created_at": rec.created_at,
        "has_file": bool(rec.file_path),
        "file_is_pdf": fp.endswith(".pdf"),
        "file_is_image": fp.endswith((".png", ".jpg", ".jpeg")),
    }
    return templates.TemplateResponse(
        "receipt_detail.html", {"request": request, "user": user, "r": header, "lines": lines}
    )


@router.get("/receipts/{receipt_id}/file")
def receipt_file(
    receipt_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_receipts),
):
    """Serve the uploaded receipt file inline. Friendly 404 (never 500) when absent/missing."""
    rec = db.query(ItemReceipt).filter(ItemReceipt.id == receipt_id).first()
    if not rec or not rec.file_path:
        return HTMLResponse("No file is attached to this receipt.", status_code=404)
    path = Path(rec.file_path)
    if not path.exists():
        return HTMLResponse("The receipt file is missing on disk.", status_code=404)
    # Preview PDF + web images inline; force download for everything else (heic that browsers
    # cannot render, and .eml/.msg/.html which must never render inside the app origin).
    disposition = "inline" if path.suffix.lower() in (".pdf", ".jpg", ".jpeg", ".png") else "attachment"
    return FileResponse(
        path=str(path),
        filename=(rec.original_filename or path.name),
        content_disposition_type=disposition,
    )


@router.post("/receipts/{receipt_id}/replace-file")
async def receipt_replace_file(
    receipt_id: int,
    request: Request,
    receipt_file: UploadFile = File(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_receipts),
    _csrf: str = Depends(require_csrf),
):
    """Replace a receipt's uploaded file (overwrite). Finance + CSRF gated. Mirrors intake's save
    and validation, deletes the old file AFTER commit (containment-guarded), and writes one
    audit-log entry. The old file is discarded - the audit line records the event, not the file."""
    rec = db.query(ItemReceipt).filter(ItemReceipt.id == receipt_id).first()
    if not rec:
        return HTMLResponse("Receipt not found.", status_code=404)

    if not (receipt_file and receipt_file.filename):
        return toast_redirect(f"{BP}/receipts/{receipt_id}", "No file selected", "warning")

    ext = Path(receipt_file.filename).suffix.lower()
    if ext not in ALLOWED_RECEIPT_EXTENSIONS:
        return toast_redirect(f"{BP}/receipts/{receipt_id}", "Unsupported file type", "warning")

    # save the new file with the intake naming scheme
    unique_name = f"receipt_{_date.today().isoformat()}_{uuid.uuid4().hex[:8]}{ext}"
    saved_path = os.path.join(RECEIPT_STORAGE_PATH, unique_name)
    os.makedirs(RECEIPT_STORAGE_PATH, exist_ok=True)
    content = await receipt_file.read()
    with open(saved_path, "wb") as fh:
        fh.write(content)

    old_path = rec.file_path
    rec.file_path = saved_path
    rec.original_filename = receipt_file.filename
    db.commit()

    # delete the old file AFTER commit, only when it resolves inside the storage root and exists
    if old_path:
        try:
            op = Path(old_path).resolve()
            root = Path(RECEIPT_STORAGE_PATH).resolve()
            if root in op.parents and op.exists():
                op.unlink(missing_ok=True)
        except Exception:
            pass  # a stale old file is harmless - never fail the request on cleanup

    log_event(
        db, "receipt_file_replaced",
        request=request, user_id=user.id,
        target_table="receipts", target_id=rec.id, action="update",
        details=f"Replaced file for receipt #{rec.id}: {rec.original_filename}",
    )

    return toast_redirect(f"{BP}/receipts/{receipt_id}", "Receipt file replaced")
