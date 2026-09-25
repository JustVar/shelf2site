"""Warranty & RMA tracking routes."""

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_admin, require_warranty_manager
from ..config import settings
from ..localtime import local_today, register
from ..database import get_db
from ..models import (
    DeviceWarranty, WarrantyClaim, User,
    TABLE_MODELS, TABLE_DISPLAY_NAMES,
    get_display_name, get_serial,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


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


def _resolve_device_label(db: Session, device_table: str, device_id: int) -> str:
    """Look up a device and return a human-readable label."""
    model = TABLE_MODELS.get(device_table)
    if not model:
        return f"{device_table}#{device_id}"
    device = db.query(model).filter(model.id == device_id).first()
    if not device:
        return f"{device_table}#{device_id}"
    display = TABLE_DISPLAY_NAMES.get(device_table, device_table)
    name = get_display_name(device)
    serial = get_serial(device)
    return f"{display}: {name} ({serial})"


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get("/warranty/")
def warranty_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Warranty & RMA management page."""
    today = local_today()
    threshold = today + timedelta(days=30)

    warranties = (
        db.query(DeviceWarranty)
        .order_by(desc(DeviceWarranty.warranty_end))
        .all()
    )

    # Enrich with device labels and status
    def _enrich(w):
        label = _resolve_device_label(db, w.device_table, w.device_id)
        days_left = (w.warranty_end - today).days if w.warranty_end else None
        if days_left is not None and days_left < 0:
            badge = "expired"
        elif days_left is not None and days_left <= 30:
            badge = "expiring"
        else:
            badge = "active"
        return {"warranty": w, "device_label": label, "days_left": days_left, "badge": badge}

    enriched = [_enrich(w) for w in warranties]

    # Split by scope
    external_warranties = [e for e in enriched if (e["warranty"].warranty_scope or "external") == "external"]
    internal_warranties = [e for e in enriched if e["warranty"].warranty_scope == "internal"]

    # Active claims
    active_claims = (
        db.query(WarrantyClaim)
        .filter(WarrantyClaim.claim_status.in_(["opened", "approved", "shipped"]))
        .order_by(desc(WarrantyClaim.claim_date))
        .all()
    )
    claims_enriched = []
    for c in active_claims:
        w = db.query(DeviceWarranty).filter(DeviceWarranty.id == c.warranty_id).first()
        device_label = _resolve_device_label(db, w.device_table, w.device_id) if w else "Unknown"
        claims_enriched.append({"claim": c, "device_label": device_label})

    expiring_count = sum(1 for e in external_warranties if e["badge"] == "expiring")
    internal_overdue = sum(
        1 for e in internal_warranties
        if e["warranty"].warranty_end and e["warranty"].warranty_end < today
    )

    # Quarterly expiration forecast (external only)
    external_only = [w for w in warranties if (w.warranty_scope or "external") == "external"]
    quarterly = _build_quarterly_forecast(external_only, today)

    return templates.TemplateResponse("warranty.html", {
        "request": request,
        "user": user,
        "warranties": enriched,
        "external_warranties": external_warranties,
        "internal_warranties": internal_warranties,
        "active_claims": claims_enriched,
        "expiring_count": expiring_count,
        "internal_overdue": internal_overdue,
        "quarterly_forecast": quarterly,
        "table_choices": TABLE_DISPLAY_NAMES,
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
    """Create a new warranty record."""
    body = await request.json()

    required = ["device_table", "device_id", "warranty_end", "vendor"]
    for field in required:
        if not body.get(field):
            return JSONResponse(status_code=400, content={"error": f"Missing required field: {field}"})

    # Validate device_table against known tables
    if body["device_table"] not in TABLE_MODELS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid device category: {body['device_table']}"},
        )

    scope = body.get("warranty_scope", "external")
    if scope not in ("external", "internal"):
        scope = "external"

    warranty = DeviceWarranty(
        device_table=body["device_table"],
        device_id=int(body["device_id"]),
        warranty_scope=scope,
        warranty_tier=body.get("warranty_tier"),
        vendor=body["vendor"],
        purchase_date=body.get("purchase_date") or None,
        warranty_start=body.get("warranty_start") or None,
        warranty_end=body["warranty_end"],
        warranty_type=body.get("warranty_type"),
        warranty_holder=body.get("warranty_holder") or "brand",
        registration_number=body.get("registration_number") or None,
        coverage_details=body.get("coverage_details"),
        auto_renew=body.get("auto_renew", False),
        renewal_cost=body.get("renewal_cost") or None,
        registration_status=body.get("registration_status") or None,
        loaner_from_team=body.get("loaner_from_team") or None,
        loaner_to_team=body.get("loaner_to_team") or None,
        loaner_contact=body.get("loaner_contact") or None,
        loaner_agreement=body.get("loaner_agreement") or None,
    )
    db.add(warranty)
    db.commit()
    db.refresh(warranty)

    log_event(
        db, "warranty_created",
        request=request, user_id=user.id,
        target_table="device_warranties", target_id=warranty.id,
        action="create",
        new_values=model_to_dict(warranty),
        details=f"Warranty for {body['device_table']}#{body['device_id']}, vendor={body['vendor']}",
    )

    return JSONResponse(content={"status": "created", "warranty_id": warranty.id})


@router.put("/api/warranty/{warranty_id}")
async def update_warranty(
    warranty_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Update a warranty record."""
    warranty = db.query(DeviceWarranty).filter(DeviceWarranty.id == warranty_id).first()
    if not warranty:
        return JSONResponse(status_code=404, content={"error": "Warranty not found"})

    body = await request.json()
    old_values = model_to_dict(warranty)

    updatable = [
        "warranty_scope", "warranty_tier", "vendor", "purchase_date", "warranty_start",
        "warranty_end", "warranty_type", "warranty_holder", "registration_number", "coverage_details",
        "auto_renew", "renewal_cost", "registration_status",
        "loaner_from_team", "loaner_to_team", "loaner_contact", "loaner_agreement",
    ]
    for field in updatable:
        if field in body:
            setattr(warranty, field, body[field] if body[field] != "" else None)

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
# Claims / RMA API
# ---------------------------------------------------------------------------

@router.post("/api/claim")
async def create_claim(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Open a new warranty claim / RMA."""
    body = await request.json()

    warranty_id = body.get("warranty_id")
    if not warranty_id:
        return JSONResponse(status_code=400, content={"error": "warranty_id is required"})

    warranty = db.query(DeviceWarranty).filter(DeviceWarranty.id == warranty_id).first()
    if not warranty:
        return JSONResponse(status_code=404, content={"error": "Warranty not found"})

    claim = WarrantyClaim(
        warranty_id=warranty_id,
        claim_number=body.get("claim_number") or None,
        claim_date=body.get("claim_date") or local_today().isoformat(),
        issue_description=body.get("issue_description"),
        claim_status=body.get("claim_status", "opened"),
        rma_number=body.get("rma_number") or None,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    log_event(
        db, "claim_created",
        request=request, user_id=user.id,
        target_table="warranty_claims", target_id=claim.id,
        action="create",
        details=f"RMA claim for warranty#{warranty_id}: {body.get('issue_description', '')[:100]}",
    )

    return JSONResponse(content={"status": "created", "claim_id": claim.id})


@router.put("/api/claim/{claim_id}")
async def update_claim(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Update an RMA claim status."""
    claim = db.query(WarrantyClaim).filter(WarrantyClaim.id == claim_id).first()
    if not claim:
        return JSONResponse(status_code=404, content={"error": "Claim not found"})

    body = await request.json()
    old_status = claim.claim_status

    updatable = [
        "claim_status", "rma_number", "tracking_number", "shipped_date",
        "expected_return", "received_date", "replacement_device_sn", "resolution_notes",
    ]
    for field in updatable:
        if field in body:
            setattr(claim, field, body[field] if body[field] != "" else None)

    db.commit()
    db.refresh(claim)

    log_event(
        db, "claim_updated",
        request=request, user_id=user.id,
        target_table="warranty_claims", target_id=claim.id,
        action="update",
        details=f"Claim#{claim_id} status: {old_status} -> {claim.claim_status}",
    )

    return JSONResponse(content={"status": "updated"})


# ---------------------------------------------------------------------------
# Export (CSV / Excel) — must be before /{warranty_id} routes
# ---------------------------------------------------------------------------

@router.get("/api/warranty/export")
def export_warranties(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export all warranty records to CSV or Excel."""
    today = local_today()
    warranties = db.query(DeviceWarranty).order_by(desc(DeviceWarranty.warranty_end)).all()

    rows = []
    for w in warranties:
        label = _resolve_device_label(db, w.device_table, w.device_id)
        days_left = (w.warranty_end - today).days if w.warranty_end else None
        if days_left is not None and days_left < 0:
            status = "Expired"
        elif days_left is not None and days_left <= 30:
            status = "Expiring Soon"
        else:
            status = "Active"
        rows.append({
            "Device": label,
            "Vendor": w.vendor or "",
            "Tier": w.warranty_tier or "",
            "Type": w.warranty_type or "",
            "Purchase Date": str(w.purchase_date) if w.purchase_date else "",
            "Start": str(w.warranty_start) if w.warranty_start else "",
            "End": str(w.warranty_end) if w.warranty_end else "",
            "Status": status,
            "Days Left": days_left if days_left is not None else "",
            "Registration #": w.registration_number or "",
            "Registration Status": w.registration_status or "",
            "Coverage": w.coverage_details or "",
            "Auto-Renew": "Yes" if w.auto_renew else "No",
            "Renewal Cost": str(w.renewal_cost) if w.renewal_cost else "",
        })

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
# Single warranty fetch (for edit modal) + Delete (admin only)
# ---------------------------------------------------------------------------

@router.get("/api/warranty/{warranty_id}")
def get_warranty(
    warranty_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single warranty record by ID."""
    warranty = db.query(DeviceWarranty).filter(DeviceWarranty.id == warranty_id).first()
    if not warranty:
        return JSONResponse(status_code=404, content={"error": "Warranty not found"})

    data = {}
    for key, val in warranty.__dict__.items():
        if key.startswith("_"):
            continue
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        data[key] = val
    return JSONResponse(content=data)


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
        details=f"Warranty#{warranty_id} deleted (vendor={old_values.get('vendor')})",
    )

    return JSONResponse(content={"status": "deleted"})
