"""Bulk operations — multi-select device batch actions."""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy.orm import Session

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor, require_sites_manager, User
from ..config import settings
from ..localtime import local_today
from ..database import get_db
from ..models import (
    TABLE_MODELS, TABLE_DISPLAY_NAMES,
    DeviceAssignment, Site,
    get_display_name, get_serial, get_status, get_mac,
    compute_completeness,
)

router = APIRouter()
BP = settings.ROOT_PATH.rstrip("/")


def _validate_device_list(body: dict, db: Session):
    """Validate and resolve a list of {table_name, device_id} pairs.

    Returns (devices_list, error_response) where error_response is None on success.
    """
    items = body.get("devices", [])
    if not items:
        return None, JSONResponse(
            status_code=400,
            content={"error": "No devices selected"},
        )

    if len(items) > 500:
        return None, JSONResponse(
            status_code=400,
            content={"error": "Maximum 500 devices per bulk operation"},
        )

    resolved = []
    for item in items:
        table_name = item.get("table_name", "")
        device_id = item.get("device_id")
        model = TABLE_MODELS.get(table_name)
        if not model or device_id is None:
            continue
        device = db.query(model).filter(model.id == int(device_id)).first()
        if device:
            resolved.append({
                "table_name": table_name,
                "device_id": device.id,
                "device": device,
                "model": model,
            })

    if not resolved:
        return None, JSONResponse(
            status_code=400,
            content={"error": "No valid devices found in selection"},
        )

    return resolved, None


@router.post("/api/bulk/status")
async def bulk_status_change(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Bulk update status for multiple devices. Requires editor role."""
    body = await request.json()
    new_status = (body.get("status") or "").strip()

    if not new_status:
        return JSONResponse(status_code=400, content={"error": "Status is required"})

    devices, error = _validate_device_list(body, db)
    if error:
        return error

    updated = 0
    skipped = 0
    for item in devices:
        device = item["device"]
        if not hasattr(device, "status"):
            skipped += 1
            continue

        old_status = device.status
        device.status = new_status
        device.data_completeness = compute_completeness(device)
        db.commit()

        log_event(
            db, "bulk_status_change",
            request=request, user_id=user.id,
            target_table=item["table_name"],
            target_id=item["device_id"],
            action="update",
            old_values={"status": old_status},
            new_values={"status": new_status},
            details=f"Bulk status change: {old_status} -> {new_status}",
        )
        updated += 1

    return JSONResponse(content={
        "status": "success",
        "updated": updated,
        "skipped": skipped,
        "message": f"Updated {updated} device(s) to status '{new_status}'",
    })


@router.post("/api/bulk/assign")
async def bulk_assign_to_site(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_sites_manager),
):
    """Bulk assign multiple devices to a site. Requires sites manager."""
    body = await request.json()
    site_id = body.get("site_id")
    ownership = body.get("ownership", "owned")

    if not site_id:
        return JSONResponse(status_code=400, content={"error": "Site ID is required"})

    site = db.query(Site).filter(Site.id == int(site_id)).first()
    if not site:
        return JSONResponse(status_code=404, content={"error": "Site not found"})

    if ownership not in DeviceAssignment.OWNERSHIP_TYPES:
        return JSONResponse(status_code=400, content={"error": f"Invalid ownership type: {ownership}"})

    devices, error = _validate_device_list(body, db)
    if error:
        return error

    assigned = 0
    skipped = 0
    for item in devices:
        # Check if already assigned to this site
        existing = (
            db.query(DeviceAssignment)
            .filter(
                DeviceAssignment.device_table == item["table_name"],
                DeviceAssignment.device_id == item["device_id"],
                DeviceAssignment.is_active.is_(True),
            )
            .first()
        )
        if existing:
            if existing.site_id == int(site_id):
                skipped += 1
                continue
            # Return from current site first
            existing.is_active = False
            existing.returned_date = local_today()
            db.commit()

        assignment = DeviceAssignment(
            device_table=item["table_name"],
            device_id=item["device_id"],
            site_id=int(site_id),
            ownership=ownership,
            assigned_date=local_today(),
            assigned_by=user.id,
            notes=f"Bulk assignment to {site.name}",
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        device_label = get_display_name(item["device"])
        log_event(
            db, "bulk_assign_to_site",
            request=request, user_id=user.id,
            target_table="device_assignments",
            target_id=assignment.id,
            action="create",
            new_values=model_to_dict(assignment),
            details=f"Bulk: {device_label} assigned to {site.name} ({DeviceAssignment.OWNERSHIP_TYPES[ownership]})",
        )
        assigned += 1

    return JSONResponse(content={
        "status": "success",
        "assigned": assigned,
        "skipped": skipped,
        "message": f"Assigned {assigned} device(s) to '{site.name}'",
    })


@router.post("/api/bulk/export")
async def bulk_export_selected(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export selected devices to CSV or XLSX. All authenticated users."""
    body = await request.json()
    export_format = body.get("format", "xlsx")

    devices, error = _validate_device_list(body, db)
    if error:
        return error

    rows = []
    for item in devices:
        device = item["device"]
        rows.append({
            "Category": TABLE_DISPLAY_NAMES.get(item["table_name"], item["table_name"]),
            "Name/Device": get_display_name(device),
            "Serial": get_serial(device),
            "Status": get_status(device),
            "MAC Address": get_mac(device),
            "Location": getattr(device, "location", "") or "",
            "Vendor": getattr(device, "vendor", "") or "",
            "Notes": getattr(device, "notes", "") or "",
            "Completeness %": int(device.data_completeness or 0),
        })

    if not rows:
        return JSONResponse(status_code=400, content={"error": "No exportable data"})

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if export_format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="bulk_export_{timestamp}.csv"'},
        )

    # Default: XLSX
    wb = Workbook()
    ws = wb.active
    ws.title = "Selected Devices"
    headers = list(rows[0].keys())
    header_fill = PatternFill(start_color="157ca4", end_color="157ca4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
    for row_idx, row_data in enumerate(rows, 2):
        for col_idx, header in enumerate(headers, 1):
            ws.cell(row=row_idx, column=col_idx, value=row_data[header])
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if cell.value and len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="bulk_export_{timestamp}.xlsx"'},
    )
