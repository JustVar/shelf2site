"""Disposal & End-of-Life tracking routes."""

import csv
import io
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_admin, require_disposal_access
from ..config import settings
from ..database import get_db
from ..models import (
    DeviceDisposition, User,
    TABLE_MODELS, TABLE_DISPLAY_NAMES,
    get_display_name, get_serial,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

CERTIFICATE_DIR = Path("/data/certificates")


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

@router.get("/disposal/")
def disposal_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_disposal_access),
):
    """Disposal & EOL tracking page."""
    dispositions = (
        db.query(DeviceDisposition)
        .order_by(desc(DeviceDisposition.disposition_date))
        .all()
    )

    enriched = []
    for d in dispositions:
        label = _resolve_device_label(db, d.device_table, d.device_id)
        needs_sanitization = d.sanitization_date is None
        enriched.append({
            "disposition": d,
            "device_label": label,
            "needs_sanitization": needs_sanitization,
        })

    pending_sanitization = sum(1 for e in enriched if e["needs_sanitization"])

    return templates.TemplateResponse("disposal.html", {
        "request": request,
        "user": user,
        "dispositions": enriched,
        "pending_sanitization": pending_sanitization,
        "table_choices": TABLE_DISPLAY_NAMES,
    })


# ---------------------------------------------------------------------------
# Disposition CRUD API
# ---------------------------------------------------------------------------

@router.post("/api/disposition")
async def create_disposition(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Create a new disposition record."""
    body = await request.json()

    required = ["device_table", "device_id", "disposition_type", "disposition_date"]
    for field in required:
        if not body.get(field):
            return JSONResponse(status_code=400, content={"error": f"Missing required field: {field}"})

    # Validate device_table against known tables
    if body["device_table"] not in TABLE_MODELS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid device category: {body['device_table']}"},
        )

    # Prevent duplicate dispositions for the same device
    existing = (
        db.query(DeviceDisposition)
        .filter(
            DeviceDisposition.device_table == body["device_table"],
            DeviceDisposition.device_id == int(body["device_id"]),
        )
        .first()
    )
    if existing:
        label = _resolve_device_label(db, body["device_table"], int(body["device_id"]))
        return JSONResponse(
            status_code=409,
            content={"error": f"A disposition already exists for {label} (ID #{existing.id}). Delete the existing record first."},
        )

    disposition = DeviceDisposition(
        device_table=body["device_table"],
        device_id=int(body["device_id"]),
        disposition_type=body["disposition_type"],
        disposition_date=body["disposition_date"],
        reason=body.get("reason"),
        sanitization_method=body.get("sanitization_method") or None,
        sanitization_date=body.get("sanitization_date") or None,
        sanitization_verified_by=body.get("sanitization_verified_by") or None,
        certificate_number=body.get("certificate_number") or None,
        transferred_to=body.get("transferred_to") or None,
        transfer_method=body.get("transfer_method") or None,
        transfer_value=body.get("transfer_value") or None,
        transfer_notes=body.get("transfer_notes") or None,
    )
    db.add(disposition)
    db.commit()
    db.refresh(disposition)

    # Auto-set source device status to "Decommissioned"
    model = TABLE_MODELS.get(body["device_table"])
    if model and hasattr(model, "status"):
        device = db.query(model).filter(model.id == int(body["device_id"])).first()
        if device and device.status != "Decommissioned":
            device.status = "Decommissioned"
            db.commit()

    log_event(
        db, "disposition_created",
        request=request, user_id=user.id,
        target_table="device_dispositions", target_id=disposition.id,
        action="create",
        new_values=model_to_dict(disposition),
        details=f"Disposition: {body['disposition_type']} for {body['device_table']}#{body['device_id']} (status → Decommissioned)",
    )

    return JSONResponse(content={"status": "created", "disposition_id": disposition.id})


@router.put("/api/disposition/{disposition_id}")
async def update_disposition(
    disposition_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Update a disposition record."""
    disposition = db.query(DeviceDisposition).filter(DeviceDisposition.id == disposition_id).first()
    if not disposition:
        return JSONResponse(status_code=404, content={"error": "Disposition not found"})

    body = await request.json()
    old_values = model_to_dict(disposition)

    updatable = [
        "disposition_type", "disposition_date", "reason",
        "sanitization_method", "sanitization_date", "sanitization_verified_by",
        "certificate_number", "transferred_to", "transfer_method",
        "transfer_value", "transfer_notes",
    ]
    for field in updatable:
        if field in body:
            setattr(disposition, field, body[field] if body[field] != "" else None)

    db.commit()
    db.refresh(disposition)

    log_event(
        db, "disposition_updated",
        request=request, user_id=user.id,
        target_table="device_dispositions", target_id=disposition.id,
        action="update",
        old_values=old_values, new_values=model_to_dict(disposition),
    )

    return JSONResponse(content={"status": "updated"})


# ---------------------------------------------------------------------------
# Certificate upload / download
# ---------------------------------------------------------------------------

@router.post("/api/disposition/{disposition_id}/certificate")
async def upload_certificate(
    disposition_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Upload a sanitization certificate PDF."""
    disposition = db.query(DeviceDisposition).filter(DeviceDisposition.id == disposition_id).first()
    if not disposition:
        return JSONResponse(status_code=404, content={"error": "Disposition not found"})

    if file.content_type not in ("application/pdf", "image/jpeg", "image/png"):
        return JSONResponse(status_code=400, content={"error": "Only PDF, JPEG, or PNG files allowed"})

    CERTIFICATE_DIR.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix if file.filename else ".pdf"
    stored_name = f"cert_{disposition_id}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = CERTIFICATE_DIR / stored_name

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    disposition.certificate_file_path = str(file_path)
    db.commit()

    log_event(
        db, "certificate_uploaded",
        request=request, user_id=user.id,
        target_table="device_dispositions", target_id=disposition.id,
        action="update",
        details=f"Certificate uploaded: {file.filename} ({len(content)} bytes)",
    )

    return JSONResponse(content={"status": "uploaded", "file_path": str(file_path)})


@router.get("/api/disposition/{disposition_id}/certificate")
def download_certificate(
    disposition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download a sanitization certificate."""
    disposition = db.query(DeviceDisposition).filter(DeviceDisposition.id == disposition_id).first()
    if not disposition or not disposition.certificate_file_path:
        return JSONResponse(status_code=404, content={"error": "Certificate not found"})

    file_path = Path(disposition.certificate_file_path)
    if not file_path.exists():
        return JSONResponse(status_code=404, content={"error": "Certificate file missing"})

    return FileResponse(path=str(file_path), filename=file_path.name)


# ---------------------------------------------------------------------------
# Export (CSV / Excel) — must be before /{disposition_id} routes
# ---------------------------------------------------------------------------

@router.get("/api/disposition/export")
def export_dispositions(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export all disposition records to CSV or Excel."""
    dispositions = db.query(DeviceDisposition).order_by(desc(DeviceDisposition.disposition_date)).all()

    rows = []
    for d in dispositions:
        label = _resolve_device_label(db, d.device_table, d.device_id)
        rows.append({
            "Device": label,
            "Disposition Type": d.disposition_type or "",
            "Date": str(d.disposition_date) if d.disposition_date else "",
            "Reason": d.reason or "",
            "Sanitization Method": d.sanitization_method or "",
            "Sanitization Date": str(d.sanitization_date) if d.sanitization_date else "",
            "Verified By": d.sanitization_verified_by or "",
            "Certificate #": d.certificate_number or "",
            "Has Certificate File": "Yes" if d.certificate_file_path else "No",
            "Transferred To": d.transferred_to or "",
            "Transfer Method": d.transfer_method or "",
            "Transfer Value": str(d.transfer_value) if d.transfer_value else "",
            "Transfer Notes": d.transfer_notes or "",
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
            headers={"Content-Disposition": f'attachment; filename="dispositions_{timestamp}.csv"'},
        )
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Dispositions"
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
            headers={"Content-Disposition": f'attachment; filename="dispositions_{timestamp}.xlsx"'},
        )


# ---------------------------------------------------------------------------
# Single disposition fetch (for edit modal) + Delete (admin only)
# ---------------------------------------------------------------------------

@router.get("/api/disposition/{disposition_id}/data")
def get_disposition(
    disposition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single disposition record by ID."""
    disposition = db.query(DeviceDisposition).filter(DeviceDisposition.id == disposition_id).first()
    if not disposition:
        return JSONResponse(status_code=404, content={"error": "Disposition not found"})

    data = {}
    for key, val in disposition.__dict__.items():
        if key.startswith("_"):
            continue
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        data[key] = val
    return JSONResponse(content=data)


@router.delete("/api/disposition/{disposition_id}")
def delete_disposition(
    disposition_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Delete a disposition record (admin only)."""
    disposition = db.query(DeviceDisposition).filter(DeviceDisposition.id == disposition_id).first()
    if not disposition:
        return JSONResponse(status_code=404, content={"error": "Disposition not found"})

    old_values = model_to_dict(disposition)
    db.delete(disposition)
    db.commit()

    log_event(
        db, "disposition_deleted",
        request=request, user_id=user.id,
        target_table="device_dispositions", target_id=disposition_id,
        action="delete",
        old_values=old_values,
        details=f"Disposition#{disposition_id} deleted ({old_values.get('disposition_type')})",
    )

    return JSONResponse(content={"status": "deleted"})
