"""Unified device lifecycle view — aggregates all lifecycle data for a single device."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from ..auth import get_current_user, User
from ..config import settings
from ..database import get_db
from ..models import (
    TABLE_MODELS, TABLE_DISPLAY_NAMES, get_display_name,
    DeviceWarranty, WarrantyClaim, VendorTrial, DeviceDisposition,
    DeviceAssignment, DeviceProvisioning, Site,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


@router.get("/api/device/{table_name}/{device_id}/lifecycle")
def device_lifecycle(
    table_name: str,
    device_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return all lifecycle records for a single device."""
    model = TABLE_MODELS.get(table_name)
    if not model:
        return JSONResponse(status_code=400, content={"error": "Invalid table"})

    device = db.query(model).filter(model.id == device_id).first()
    if not device:
        return JSONResponse(status_code=404, content={"error": "Device not found"})

    result = {
        "device_name": get_display_name(device),
        "table_name": table_name,
        "display_table": TABLE_DISPLAY_NAMES.get(table_name, table_name),
    }

    # Provisioning records
    prov_records = (
        db.query(DeviceProvisioning)
        .filter(
            DeviceProvisioning.device_table == table_name,
            DeviceProvisioning.device_id == device_id,
        )
        .order_by(DeviceProvisioning.created_at.desc())
        .all()
    )
    result["provisioning"] = [
        {
            "id": p.id,
            "current_stage": p.current_stage,
            "stages": p.stages,
            "is_complete": p.is_complete,
            "priority": p.priority,
            "due_date": p.due_date.isoformat() if p.due_date else None,
            "start_date": p.start_date.isoformat() if p.start_date else None,
            "completed_at": p.completed_at.strftime("%Y-%m-%d") if p.completed_at else None,
            "created_at": p.created_at.strftime("%Y-%m-%d") if p.created_at else None,
            "deployment_bucket": p.deployment_bucket,
            "location_note": p.location_note,
            "zendesk_ticket_id": p.zendesk_ticket_id,
            "validation_result": p.validation_result,
            "site_name": p.site.name if p.site else None,
            "assignee_name": p.assignee.display_name if p.assignee else None,
        }
        for p in prov_records
    ]

    # Warranties
    warranties = (
        db.query(DeviceWarranty)
        .filter(
            DeviceWarranty.device_table == table_name,
            DeviceWarranty.device_id == device_id,
        )
        .all()
    )
    result["warranties"] = [
        {
            "id": w.id,
            "vendor": w.vendor,
            "warranty_tier": w.warranty_tier,
            "warranty_type": w.warranty_type,
            "warranty_start": w.warranty_start.isoformat() if w.warranty_start else None,
            "warranty_end": w.warranty_end.isoformat() if w.warranty_end else None,
            "registration_status": w.registration_status,
            "auto_renew": w.auto_renew,
            "claims": [
                {
                    "id": c.id,
                    "claim_number": c.claim_number,
                    "claim_status": c.claim_status,
                    "claim_date": c.claim_date.isoformat() if c.claim_date else None,
                    "rma_number": c.rma_number,
                    "resolution_notes": c.resolution_notes,
                }
                for c in w.claims
            ],
        }
        for w in warranties
    ]

    # Trials
    trials = (
        db.query(VendorTrial)
        .filter(
            VendorTrial.device_table == table_name,
            VendorTrial.device_id == device_id,
        )
        .all()
    )
    result["trials"] = [
        {
            "id": t.id,
            "vendor": t.vendor,
            "trial_type": t.trial_type,
            "trial_status": t.trial_status,
            "decision": t.decision,
            "received_date": t.received_date.isoformat() if t.received_date else None,
            "return_deadline": t.return_deadline.isoformat() if t.return_deadline else None,
            "decision_date": t.decision_date.isoformat() if t.decision_date else None,
        }
        for t in trials
    ]

    # Assignments (current + history)
    assignments = (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.device_table == table_name,
            DeviceAssignment.device_id == device_id,
        )
        .order_by(DeviceAssignment.assigned_date.desc())
        .all()
    )
    result["assignments"] = [
        {
            "id": a.id,
            "site_name": a.site.name if a.site else "Unknown",
            "ownership": a.ownership,
            "assigned_date": a.assigned_date.isoformat() if a.assigned_date else None,
            "expected_return": a.expected_return.isoformat() if a.expected_return else None,
            "returned_date": a.returned_date.isoformat() if a.returned_date else None,
            "is_active": a.is_active,
            "notes": a.notes,
        }
        for a in assignments
    ]

    # Dispositions
    dispositions = (
        db.query(DeviceDisposition)
        .filter(
            DeviceDisposition.device_table == table_name,
            DeviceDisposition.device_id == device_id,
        )
        .all()
    )
    result["dispositions"] = [
        {
            "id": d.id,
            "disposition_type": d.disposition_type,
            "disposition_date": d.disposition_date.isoformat() if d.disposition_date else None,
            "reason": d.reason,
            "sanitization_method": d.sanitization_method,
            "certificate_number": d.certificate_number,
            "transferred_to": d.transferred_to,
        }
        for d in dispositions
    ]

    return JSONResponse(content=result)


@router.get("/device/{table_name}/{device_id}/lifecycle")
def device_lifecycle_page(
    table_name: str,
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Render the device lifecycle HTML partial (for HTMX loading in modals)."""
    model = TABLE_MODELS.get(table_name)
    if not model:
        return HTMLResponse("<p>Invalid device table.</p>", status_code=400)

    device = db.query(model).filter(model.id == device_id).first()
    if not device:
        return HTMLResponse("<p>Device not found.</p>", status_code=404)

    # Gather all lifecycle data
    prov_records = (
        db.query(DeviceProvisioning)
        .filter(DeviceProvisioning.device_table == table_name, DeviceProvisioning.device_id == device_id)
        .order_by(DeviceProvisioning.created_at.desc())
        .all()
    )
    warranties = (
        db.query(DeviceWarranty)
        .filter(DeviceWarranty.device_table == table_name, DeviceWarranty.device_id == device_id)
        .all()
    )
    trials = (
        db.query(VendorTrial)
        .filter(VendorTrial.device_table == table_name, VendorTrial.device_id == device_id)
        .all()
    )
    assignments = (
        db.query(DeviceAssignment)
        .filter(DeviceAssignment.device_table == table_name, DeviceAssignment.device_id == device_id)
        .order_by(DeviceAssignment.assigned_date.desc())
        .all()
    )
    dispositions = (
        db.query(DeviceDisposition)
        .filter(DeviceDisposition.device_table == table_name, DeviceDisposition.device_id == device_id)
        .all()
    )

    return templates.TemplateResponse("partials/lifecycle_panel.html", {
        "request": request,
        "user": user,
        "device": device,
        "device_name": get_display_name(device),
        "table_name": table_name,
        "display_table": TABLE_DISPLAY_NAMES.get(table_name, table_name),
        "provisioning": prov_records,
        "warranties": warranties,
        "trials": trials,
        "assignments": assignments,
        "dispositions": dispositions,
    })
