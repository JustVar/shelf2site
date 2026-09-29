"""Pending device review queue: approve or dismiss discovered devices."""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError

from ..audit import log_event, model_to_dict
from ..auth import get_current_user, require_editor
from ..database import get_db
from ..models import PendingDevice, ReceivedDevice, User, item_categories_enum, user_can_approve_category
from .intake import create_item
from .receiving import TARGET_TABLE_TO_CATEGORY

router = APIRouter()

_CATEGORIES = frozenset(item_categories_enum.enums)


def _pending_category(pending: PendingDevice, body: dict) -> str:
    """The item category for a pending device, from an override or the suggestion."""
    override = str(body.get("item_category") or "").strip()
    if override in _CATEGORIES:
        return override
    legacy = str(body.get("target_table") or "").strip()
    if legacy in TARGET_TABLE_TO_CATEGORY:
        return TARGET_TABLE_TO_CATEGORY[legacy]
    if pending.suggested_category and str(pending.suggested_category) in _CATEGORIES:
        return str(pending.suggested_category)
    return "network"


@router.post("/pending/{device_id}/approve")
async def approve_device(
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Approve a pending device: create it as an item in item_schema.items.

    Item 30 S3 (docs/specs/retire-legacy-inventory.md): approval no longer
    writes a legacy public.* row; the item is built by the shared create_item
    path. Item 30 S4: the review queue sends item_category. A legacy
    target_table is still accepted and mapped through TARGET_TABLE_TO_CATEGORY.
    """
    pending = db.query(PendingDevice).filter(PendingDevice.id == device_id).first()
    if not pending:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    if pending.status != "pending":
        return JSONResponse(status_code=400, content={"error": f"Already {pending.status}"})

    # Category: a JSON override (item_category, or a legacy target_table),
    # else what intake suggested, else network.
    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
    item_category = _pending_category(pending, body)

    # RBAC: edge boxes need sites admin, everything else editor
    if not user_can_approve_category(user, item_category):
        return JSONResponse(
            status_code=403,
            content={"error": f"You do not have permission to approve {item_category.replace('_', ' ')} devices. Sites Manager access required."},
        )

    # the intake-<serial> placeholder is a NOT NULL hack, not a real MAC
    mac = pending.mac_address
    if not mac or mac.startswith("intake-"):
        mac = None

    manufacturer = (pending.manufacturer or "").strip()
    model = (pending.model or "").strip()
    notes = [pending.notes] if pending.notes else []
    notes.append(f"Approved from the review queue (pending #{pending.id}, {pending.scanner_id or 'unknown source'})")
    if pending.ip_address:
        notes.append(f"IP at discovery: {pending.ip_address}")
    attributes = {"approved_from_pending": pending.id}
    if pending.network_segment:
        attributes["network_segment"] = pending.network_segment

    fields = {
        "item_name": pending.hostname or f"{manufacturer} {model}".strip() or pending.serial or "Auto-discovered",
        "item_manufacturer": manufacturer,
        "item_model": model,
        "item_sn": pending.serial,
        "item_category": item_category,
        "item_status": "Unassigned",
        "item_mac_address_1": mac,
        "notes": "\n".join(notes),
    }
    created_by = user.display_name or user.username
    try:
        try:
            item = create_item(db, fields=fields, created_by=created_by, attributes=attributes)
        except ValueError:
            # A MAC that does not normalise stays in notes, not the column.
            fields["item_mac_address_1"] = None
            fields["notes"] += f"\nMAC at discovery: {mac}"
            item = create_item(db, fields=fields, created_by=created_by, attributes=attributes)

        # The receiving event's unit link (H16) gains the new item.
        rd = db.query(ReceivedDevice).filter(ReceivedDevice.pending_device_id == pending.id).first()
        if rd and rd.item_id is None:
            rd.item_id = item.id

        # Auto-add OUI to allowlist if not present. The intake-<serial>
        # placeholder is a NOT NULL hack, not a MAC — feeding it to the OUI
        # lookup raised InvalidMacError and 500'd the approval of every
        # scan-intake pending row (pre-existing, surfaced by the H15 tests).
        if mac:
            from app.oui_utils import auto_add_oui
            # the OUI allowlist still keys on scan-intake table names
            oui_table = next((t for t, c in TARGET_TABLE_TO_CATEGORY.items() if c == item_category), None)
            auto_add_oui(db, mac_address=mac, manufacturer=pending.manufacturer, table_name=oui_table)

        # Update pending record
        pending.status = "approved"
        pending.reviewed_by = user.id
        pending.reviewed_at = datetime.utcnow()

        # H15 (supersedes the H3 approve-time count): receiving counts at SUBMIT
        # time — the unit physically arrived when it was scanned, not when a
        # reviewer clicked approve. Incrementing here again would double-count.

        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=409, content={
            "error": "Database rejected this device: a uniqueness constraint matched "
                     "an existing item (duplicate serial or MAC).",
        })
    db.refresh(item)

    log_event(
        db, "device_approved",
        request=request,
        user_id=user.id,
        target_table="items",
        target_id=item.id,
        action="approve",
        new_values=model_to_dict(item),
        details=f"Approved pending device {pending.serial or pending.mac_address} -> item {item.id} ({item_category})",
    )

    from ..sidebar_cache import invalidate_category_stats, invalidate_triage_cache
    invalidate_category_stats()
    invalidate_triage_cache()

    return JSONResponse(content={
        "status": "approved",
        "target_table": "items",
        "item_category": item_category,
        "device_id": item.id,
    })


@router.post("/pending/{device_id}/dismiss")
async def dismiss_device(
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Dismiss a pending device (ignore it, never prompt again for this MAC)."""
    pending = db.query(PendingDevice).filter(PendingDevice.id == device_id).first()
    if not pending:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    if pending.status != "pending":
        return JSONResponse(status_code=400, content={"error": f"Already {pending.status}"})

    # RBAC: same category gate as approve
    item_category = _pending_category(pending, {})
    if not user_can_approve_category(user, item_category):
        return JSONResponse(
            status_code=403,
            content={"error": f"You do not have permission to dismiss {item_category.replace('_', ' ')} devices. Sites Manager access required."},
        )

    form = await request.form() if request.headers.get("content-type", "").startswith("application/x-www-form") else None
    reason = ""
    if form:
        reason = form.get("reason", "")
    else:
        # Also accept JSON body
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            body = await request.json()
            reason = body.get("reason", "")

    pending.status = "dismissed"
    pending.reviewed_by = user.id
    pending.reviewed_at = datetime.utcnow()
    pending.dismiss_reason = reason

    # H15/H17: the count was taken at submit time; a dismissed record was a
    # scan mistake, not a received unit — give EVERYTHING back: the event
    # count, the event's SKU line, the OEM PO line (with its status), and
    # the received_devices link itself.
    if pending.receiving_event_id:
        from app.models import ReceivedDevice, ReceivingEvent
        from app.po_matching import match_oem_lines, norm_sku
        event = db.query(ReceivingEvent).filter(
            ReceivingEvent.id == pending.receiving_event_id
        ).first()
        if event and (event.received_quantity or 0) > 0:
            event.received_quantity -= 1
            rd = db.query(ReceivedDevice).filter(
                ReceivedDevice.pending_device_id == pending.id
            ).first()
            if rd:
                if rd.line_id:
                    for line in event.lines:
                        if line.id == rd.line_id and (line.qty_received or 0) > 0:
                            line.qty_received -= 1
                if rd.sku:
                    for row in match_oem_lines(db, event.purchase_order):
                        if norm_sku(row.sku) == norm_sku(rd.sku) and (row.qty_received or 0) > 0:
                            row.qty_received -= 1
                            if row.status == "verified" and row.qty_received < (row.qty_ordered or 0):
                                row.status = "receiving"
                            break
                db.delete(rd)
            if event.status == "complete":
                # the auto-complete this unit contributed to no longer stands
                lines = event.lines or []
                if lines:
                    if not all((l.qty_received or 0) >= (l.qty_expected or 0) for l in lines):
                        event.status = "open"
                elif event.expected_quantity and event.received_quantity < event.expected_quantity:
                    event.status = "open"

    db.commit()

    log_event(
        db, "device_dismissed",
        request=request,
        user_id=user.id,
        target_table="pending_devices",
        target_id=device_id,
        action="dismiss",
        details=f"Dismissed {pending.mac_address}: {reason or 'no reason given'}",
    )

    return JSONResponse(content={"status": "dismissed"})
