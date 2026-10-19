"""Warranty tracking routes: basic warranties on internal inventory items.

Item 30 S4 (docs/specs/retire-legacy-inventory.md): a warranty hangs off
item_schema.items through device_warranties.item_id and records vendor,
start, end and notes. Customer warranties on shipped hardware are tracked by
the OEM, not here. RMA claims and internal loaners were retired in the same
change; their columns and the warranty_claims table dropped in migration 083
(item 30 S5).
"""

import csv
import io
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_warranty_manager
from ..config import settings
from ..localtime import local_now, local_today, register
from ..database import get_db
from ..delete_requests import LOCK_MESSAGE, locked_ids
from ..models import DeviceWarranty, Item, User

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)

EXPIRING_DAYS = 30
VENDOR_MAX = 128


def _quarter_label(d: date) -> str:
    """Return 'Q1 2026' style label for a date."""
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"


def _build_quarterly_forecast(warranties, today: date) -> list[dict]:
    """Build a 4-quarter expiration forecast from warranty records."""
    # Determine current quarter start
    q_month = ((today.month - 1) // 3) * 3 + 1
    q_start = date(today.year, q_month, 1)

    # Build 4 quarter boundaries
    quarters = []
    for i in range(4):
        y = q_start.year + (q_start.month + i * 3 - 1) // 12
        m = (q_start.month + i * 3 - 1) % 12 + 1
        start = date(y, m, 1)
        # End is start of next quarter
        ny = y + (m + 2) // 12
        nm = (m + 2) % 12 + 1
        end = date(ny, nm, 1)
        quarters.append({"label": _quarter_label(start), "start": start, "end": end, "count": 0})

    for w in warranties:
        if not w.warranty_end:
            continue
        for q in quarters:
            if q["start"] <= w.warranty_end < q["end"]:
                q["count"] += 1
                break

    return [{"label": q["label"], "count": q["count"]} for q in quarters]


def warranty_status(w, today: date) -> tuple[str, int | None]:
    """(badge, days_left) for one warranty: expired, expiring or active."""
    days_left = (w.warranty_end - today).days if w.warranty_end else None
    if days_left is not None and days_left < 0:
        return "expired", days_left
    if days_left is not None and days_left <= EXPIRING_DAYS:
        return "expiring", days_left
    return "active", days_left


def _items_by_id(db: Session, warranties) -> dict:
    ids = {w.item_id for w in warranties if w.item_id}
    if not ids:
        return {}
    return {i.id: i for i in db.query(Item).filter(Item.id.in_(ids)).all()}


def _parse_date(value, field: str):
    """ISO date string to date. Returns (date or None, error or None)."""
    if value in (None, ""):
        return None, None
    try:
        return date.fromisoformat(str(value)), None
    except ValueError:
        return None, f"{field} must be a date (YYYY-MM-DD)"


def _clean_fields(body: dict, require_all: bool):
    """Validate vendor, start, end and notes. Returns (fields, error)."""
    fields = {}
    start, err = _parse_date(body.get("warranty_start"), "Start date")
    if err:
        return None, err
    end, err = _parse_date(body.get("warranty_end"), "End date")
    if err:
        return None, err
    if require_all or "warranty_start" in body:
        if not start:
            return None, "Start date is required"
        fields["warranty_start"] = start
    if require_all or "warranty_end" in body:
        if not end:
            return None, "End date is required"
        fields["warranty_end"] = end
    if "vendor" in body or require_all:
        vendor = (body.get("vendor") or "").strip()
        if len(vendor) > VENDOR_MAX:
            return None, f"Vendor is longer than {VENDOR_MAX} characters"
        fields["vendor"] = vendor or None
    if "notes" in body or require_all:
        fields["notes"] = (body.get("notes") or "").strip() or None
    return fields, None


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get("/warranty/")
def warranty_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Warranty tracking page."""
    today = local_today()
    warranties = (
        db.query(DeviceWarranty)
        .order_by(desc(DeviceWarranty.warranty_end), DeviceWarranty.id)
        .all()
    )
    items = _items_by_id(db, warranties)

    rows = []
    for w in warranties:
        badge, days_left = warranty_status(w, today)
        rows.append({"warranty": w, "item": items.get(w.item_id), "badge": badge, "days_left": days_left})

    return templates.TemplateResponse(request, "warranty.html", {
        "request": request,
        "user": user,
        "rows": rows,
        "expiring_count": sum(1 for r in rows if r["badge"] == "expiring"),
        "quarterly_forecast": _build_quarterly_forecast(warranties, today),
    })


# ---------------------------------------------------------------------------
# Warranty CRUD API
# ---------------------------------------------------------------------------

@router.post("/api/warranty")
async def create_warranty(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Create a warranty on one item."""
    body = await request.json()

    try:
        item_id = int(body.get("item_id"))
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Pick an item"})
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return JSONResponse(status_code=404, content={"error": "Item not found"})
    # A warranty is a delete blocker (ITEM_LINKS), so an item frozen by a
    # pending delete request must not gain one.
    if locked_ids(db, "items", [item.id]):
        return JSONResponse(status_code=409, content={"error": LOCK_MESSAGE})

    fields, err = _clean_fields(body, require_all=True)
    if err:
        return JSONResponse(status_code=400, content={"error": err})
    if fields["warranty_end"] < fields["warranty_start"]:
        return JSONResponse(status_code=400, content={"error": "End date is before the start date"})

    warranty = DeviceWarranty(item_id=item.id, **fields)
    db.add(warranty)
    db.commit()
    db.refresh(warranty)

    log_event(
        db, "warranty_created",
        request=request, user_id=user.id,
        target_table="device_warranties", target_id=warranty.id,
        action="create",
        new_values=model_to_dict(warranty),
        details=f"Warranty for item {item.id}, ends {warranty.warranty_end}",
    )

    return JSONResponse(content={"status": "created", "warranty_id": warranty.id})


@router.put("/api/warranty/{warranty_id}")
async def update_warranty(
    warranty_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Update vendor, dates or notes. The item does not change."""
    warranty = db.query(DeviceWarranty).filter(DeviceWarranty.id == warranty_id).first()
    if not warranty:
        return JSONResponse(status_code=404, content={"error": "Warranty not found"})

    body = await request.json()
    fields, err = _clean_fields(body, require_all=False)
    if err:
        return JSONResponse(status_code=400, content={"error": err})
    start = fields.get("warranty_start", warranty.warranty_start)
    end = fields.get("warranty_end", warranty.warranty_end)
    if start and end and end < start:
        return JSONResponse(status_code=400, content={"error": "End date is before the start date"})

    old_values = model_to_dict(warranty)
    for key, val in fields.items():
        setattr(warranty, key, val)
    db.commit()
    db.refresh(warranty)

    log_event(
        db, "warranty_updated",
        request=request, user_id=user.id,
        target_table="device_warranties", target_id=warranty.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(warranty),
    )

    return JSONResponse(content={"status": "updated"})


# ---------------------------------------------------------------------------
# Item picker and export: both must be before the /{warranty_id} routes
# ---------------------------------------------------------------------------

@router.get("/api/warranty/item-search")
def warranty_item_search(
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Add-warranty picker: items whose name or serial contains q."""
    q = (q or "").strip()
    if len(q) < 2:
        return JSONResponse(content={"results": []})
    # escape ilike wildcards, since scanned serials can contain % or _
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{esc}%"
    rows = (
        db.query(Item)
        .filter(or_(Item.item_name.ilike(like), Item.item_sn.ilike(like)))
        .order_by(Item.item_name, Item.id)
        .limit(20)
        .all()
    )
    return JSONResponse(content={"results": [
        {
            "id": r.id,
            "name": r.item_name or "(unnamed)",
            "serial": r.item_sn,
            "category": r.item_category,
        }
        for r in rows
    ]})


@router.get("/api/warranty/export")
def export_warranties(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export all warranty records to CSV or Excel."""
    today = local_today()
    warranties = (
        db.query(DeviceWarranty)
        .order_by(desc(DeviceWarranty.warranty_end), DeviceWarranty.id)
        .all()
    )
    items = _items_by_id(db, warranties)
    labels = {"expired": "Expired", "expiring": "Expiring Soon", "active": "Active"}

    rows = []
    for w in warranties:
        item = items.get(w.item_id)
        badge, days_left = warranty_status(w, today)
        rows.append({
            "Item": (item.item_name or "(unnamed)") if item else "",
            "Serial": (item.item_sn or "") if item else "",
            "Vendor": w.vendor or "",
            "Start": str(w.warranty_start) if w.warranty_start else "",
            "End": str(w.warranty_end) if w.warranty_end else "",
            "Status": labels[badge],
            "Days Left": days_left if days_left is not None else "",
            "Notes": w.notes or "",
        })

    timestamp = local_now().strftime("%Y%m%d_%H%M%S")
    if format == "csv":
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="warranties_{timestamp}.csv"'},
        )
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Warranties"
        if rows:
            headers = list(rows[0].keys())
            hfill = PatternFill(start_color="157ca4", end_color="157ca4", fill_type="solid")
            hfont = Font(bold=True, color="FFFFFF")
            for ci, h in enumerate(headers, 1):
                cell = ws.cell(row=1, column=ci, value=h)
                cell.fill = hfill
                cell.font = hfont
            for ri, rd in enumerate(rows, 2):
                for ci, h in enumerate(headers, 1):
                    ws.cell(row=ri, column=ci, value=rd[h])
            for col in ws.columns:
                ml = max((len(str(c.value or "")) for c in col), default=0)
                ws.column_dimensions[col[0].column_letter].width = min(ml + 2, 50)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="warranties_{timestamp}.xlsx"'},
        )


# ---------------------------------------------------------------------------
# Single warranty fetch (for edit modal) + Delete (warranty managers only)
# ---------------------------------------------------------------------------

@router.get("/api/warranty/{warranty_id}")
def get_warranty(
    warranty_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One warranty, with its item's name and serial, for the edit form."""
    warranty = db.query(DeviceWarranty).filter(DeviceWarranty.id == warranty_id).first()
    if not warranty:
        return JSONResponse(status_code=404, content={"error": "Warranty not found"})
    item = db.query(Item).filter(Item.id == warranty.item_id).first() if warranty.item_id else None

    return JSONResponse(content={
        "id": warranty.id,
        "item_id": warranty.item_id,
        "item_name": (item.item_name or "(unnamed)") if item else None,
        "item_serial": item.item_sn if item else None,
        "vendor": warranty.vendor,
        "warranty_start": warranty.warranty_start.isoformat() if warranty.warranty_start else None,
        "warranty_end": warranty.warranty_end.isoformat() if warranty.warranty_end else None,
        "notes": warranty.notes,
    })


@router.delete("/api/warranty/{warranty_id}")
def delete_warranty(
    warranty_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_warranty_manager),
):
    """Delete a warranty record (warranty admin or flagged users)."""
    warranty = db.query(DeviceWarranty).filter(DeviceWarranty.id == warranty_id).first()
    if not warranty:
        return JSONResponse(status_code=404, content={"error": "Warranty not found"})

    old_values = model_to_dict(warranty)
    db.delete(warranty)
    db.commit()

    log_event(
        db, "warranty_deleted",
        request=request, user_id=user.id,
        target_table="device_warranties", target_id=warranty_id,
        action="delete",
        old_values=old_values,
        details=f"Warranty#{warranty_id} deleted (item {old_values.get('item_id')})",
    )

    return JSONResponse(content={"status": "deleted"})
