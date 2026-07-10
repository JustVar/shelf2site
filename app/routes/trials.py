"""Vendor Trial (Try & Buy) tracking routes."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_admin, require_trials_manager
from ..config import settings
from ..database import get_db
from ..models import (
    VendorTrial, User,
    TABLE_MODELS, TABLE_DISPLAY_NAMES,
    get_display_name, get_serial,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


def _resolve_device_label(db: Session, device_table: str, device_id: int) -> str:
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

@router.get("/trials/")
def trials_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Try & Buy management page."""
    today = date.today()

    trials = (
        db.query(VendorTrial)
        .order_by(desc(VendorTrial.return_deadline))
        .all()
    )

    enriched = []
    for t in trials:
        label = _resolve_device_label(db, t.device_table, t.device_id)
        days_left = (t.return_deadline - today).days if t.return_deadline else None

        # Auto-compute display status
        if t.trial_status == "active" and days_left is not None and days_left < 0:
            badge = "overdue"
        elif t.trial_status == "active" and days_left is not None and days_left <= 7:
            badge = "expiring"
        elif t.trial_status == "approved_purchase":
            badge = "purchased"
        elif t.trial_status == "returned":
            badge = "returned"
        else:
            badge = t.trial_status or "active"

        enriched.append({"trial": t, "device_label": label, "days_left": days_left, "badge": badge})

    overdue_count = sum(1 for e in enriched if e["badge"] == "overdue")
    expiring_count = sum(1 for e in enriched if e["badge"] == "expiring")

    return templates.TemplateResponse("trials.html", {
        "request": request,
        "user": user,
        "trials": enriched,
        "overdue_count": overdue_count,
        "expiring_count": expiring_count,
        "table_choices": TABLE_DISPLAY_NAMES,
    })


# ---------------------------------------------------------------------------
# Trial CRUD API
# ---------------------------------------------------------------------------

@router.post("/api/trial")
async def create_trial(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Create a new vendor trial."""
    body = await request.json()

    required = ["device_table", "device_id", "vendor", "received_date", "return_deadline"]
    for field in required:
        if not body.get(field):
            return JSONResponse(status_code=400, content={"error": f"Missing required field: {field}"})

    # Validate device_table against known tables
    if body["device_table"] not in TABLE_MODELS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid device category: {body['device_table']}"},
        )

    trial = VendorTrial(
        device_table=body["device_table"],
        device_id=int(body["device_id"]),
        vendor=body["vendor"],
        trial_type=body.get("trial_type", "evaluation"),
        received_date=body["received_date"],
        return_deadline=body["return_deadline"],
        decision_deadline=body.get("decision_deadline") or None,
        trial_status="active",
        decision="pending",
        evaluation_notes=body.get("evaluation_notes") or None,
        test_results=body.get("test_results") or None,
        pros=body.get("pros") or None,
        cons=body.get("cons") or None,
    )
    db.add(trial)
    db.commit()
    db.refresh(trial)

    log_event(
        db, "trial_created",
        request=request, user_id=user.id,
        target_table="vendor_trials", target_id=trial.id,
        action="create",
        new_values=model_to_dict(trial),
        details=f"Trial from {body['vendor']} for {body['device_table']}#{body['device_id']}",
    )

    return JSONResponse(content={"status": "created", "trial_id": trial.id})


@router.put("/api/trial/{trial_id}/decision")
async def record_decision(
    trial_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Record a purchase or decline decision."""
    trial = db.query(VendorTrial).filter(VendorTrial.id == trial_id).first()
    if not trial:
        return JSONResponse(status_code=404, content={"error": "Trial not found"})

    body = await request.json()
    old_values = model_to_dict(trial)

    decision = body.get("decision")  # approved | declined
    if decision not in ("approved", "declined"):
        return JSONResponse(status_code=400, content={"error": "decision must be 'approved' or 'declined'"})

    trial.decision = decision
    trial.decision_date = body.get("decision_date") or date.today().isoformat()
    trial.decision_notes = body.get("decision_notes")

    # Update evaluation fields if provided
    for eval_field in ("evaluation_notes", "test_results", "pros", "cons"):
        if eval_field in body:
            setattr(trial, eval_field, body[eval_field] if body[eval_field] != "" else None)

    if decision == "approved":
        trial.trial_status = "approved_purchase"
        trial.purchase_order = body.get("purchase_order")
        trial.purchase_price = body.get("purchase_price") or None
    else:
        trial.trial_status = "returned"

    db.commit()
    db.refresh(trial)

    log_event(
        db, "trial_decision",
        request=request, user_id=user.id,
        target_table="vendor_trials", target_id=trial.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(trial),
        details=f"Trial#{trial_id} decision: {decision}",
    )

    return JSONResponse(content={"status": "updated", "decision": decision})


@router.put("/api/trial/{trial_id}/return")
async def record_return(
    trial_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Record that a trial device was returned."""
    trial = db.query(VendorTrial).filter(VendorTrial.id == trial_id).first()
    if not trial:
        return JSONResponse(status_code=404, content={"error": "Trial not found"})

    body = await request.json()
    old_values = model_to_dict(trial)

    trial.trial_status = "returned"
    trial.returned_date = body.get("returned_date") or date.today().isoformat()
    trial.return_tracking = body.get("return_tracking")

    db.commit()
    db.refresh(trial)

    log_event(
        db, "trial_returned",
        request=request, user_id=user.id,
        target_table="vendor_trials", target_id=trial.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(trial),
        details=f"Trial#{trial_id} returned",
    )

    return JSONResponse(content={"status": "returned"})


# ---------------------------------------------------------------------------
# Export (CSV / Excel) — must be before /{trial_id} routes
# ---------------------------------------------------------------------------

@router.get("/api/trial/export")
def export_trials(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export all trial records to CSV or Excel."""
    today = date.today()
    trials = db.query(VendorTrial).order_by(desc(VendorTrial.return_deadline)).all()

    rows = []
    for t in trials:
        label = _resolve_device_label(db, t.device_table, t.device_id)
        days_left = (t.return_deadline - today).days if t.return_deadline else None
        rows.append({
            "Device": label,
            "Vendor": t.vendor or "",
            "Trial Type": t.trial_type or "",
            "Received": str(t.received_date) if t.received_date else "",
            "Return Deadline": str(t.return_deadline) if t.return_deadline else "",
            "Days Left": days_left if days_left is not None else "",
            "Status": t.trial_status or "",
            "Decision": t.decision or "",
            "Decision Date": str(t.decision_date) if t.decision_date else "",
            "Purchase Order": t.purchase_order or "",
            "Purchase Price": str(t.purchase_price) if t.purchase_price else "",
            "Pros": t.pros or "",
            "Cons": t.cons or "",
            "Test Results": t.test_results or "",
            "Evaluation Notes": t.evaluation_notes or "",
            "Returned Date": str(t.returned_date) if t.returned_date else "",
            "Return Tracking": t.return_tracking or "",
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
            headers={"Content-Disposition": f'attachment; filename="trials_{timestamp}.csv"'},
        )
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Vendor Trials"
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
            headers={"Content-Disposition": f'attachment; filename="trials_{timestamp}.xlsx"'},
        )


# ---------------------------------------------------------------------------
# Single trial fetch (for edit modal) + Edit + Delete (admin only)
# ---------------------------------------------------------------------------

@router.get("/api/trial/{trial_id}")
def get_trial(
    trial_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single trial record by ID."""
    trial = db.query(VendorTrial).filter(VendorTrial.id == trial_id).first()
    if not trial:
        return JSONResponse(status_code=404, content={"error": "Trial not found"})

    data = {}
    for key, val in trial.__dict__.items():
        if key.startswith("_"):
            continue
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        elif isinstance(val, Decimal):
            val = float(val)
        data[key] = val
    return JSONResponse(content=data)


@router.put("/api/trial/{trial_id}")
async def update_trial(
    trial_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Update a trial record (evaluation notes, dates, etc.)."""
    trial = db.query(VendorTrial).filter(VendorTrial.id == trial_id).first()
    if not trial:
        return JSONResponse(status_code=404, content={"error": "Trial not found"})

    body = await request.json()
    old_values = model_to_dict(trial)

    updatable = [
        "vendor", "trial_type", "received_date", "return_deadline",
        "decision_deadline", "evaluation_notes", "test_results", "pros", "cons",
    ]
    for field in updatable:
        if field in body:
            setattr(trial, field, body[field] if body[field] != "" else None)

    db.commit()
    db.refresh(trial)

    log_event(
        db, "trial_updated",
        request=request, user_id=user.id,
        target_table="vendor_trials", target_id=trial.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(trial),
    )

    return JSONResponse(content={"status": "updated"})


@router.delete("/api/trial/{trial_id}")
def delete_trial(
    trial_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_trials_manager),
):
    """Delete a trial record (trials admin or flagged users)."""
    trial = db.query(VendorTrial).filter(VendorTrial.id == trial_id).first()
    if not trial:
        return JSONResponse(status_code=404, content={"error": "Trial not found"})

    old_values = model_to_dict(trial)
    db.delete(trial)
    db.commit()

    log_event(
        db, "trial_deleted",
        request=request, user_id=user.id,
        target_table="vendor_trials", target_id=trial_id,
        action="delete",
        old_values=old_values,
        details=f"Trial#{trial_id} deleted (vendor={old_values.get('vendor')})",
    )

    return JSONResponse(content={"status": "deleted"})
