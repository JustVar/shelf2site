"""Discovery endpoint — receives scan results from local and remote scanners.

ALL discovered devices go to the pending queue for review.
OUI allowlist is used for suggested table mapping only, not filtering.
OUI entries are auto-added when devices are approved.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import OUIAllowlist, PendingDevice, TABLE_MODELS

router = APIRouter()
logger = logging.getLogger(__name__)


class DiscoveredDevice(BaseModel):
    mac: str
    ip: str
    hostname: Optional[str] = None
    manufacturer: Optional[str] = None
    os_hint: Optional[str] = None


class DiscoveryPayload(BaseModel):
    scanner_id: str
    subnet: str
    devices: list[DiscoveredDevice]


def _verify_api_key(x_scanner_key: str = Header(...)):
    """Validate the scanner API key from the request header."""
    if x_scanner_key != settings.SCANNER_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid scanner API key",
        )
    return x_scanner_key


def _get_oui_prefix(mac: str) -> str:
    """Extract the first 3 octets (OUI) from a MAC address."""
    clean = mac.replace("-", ":").upper()
    parts = clean.split(":")
    if len(parts) >= 3:
        return ":".join(parts[:3])
    return clean[:8]


@router.post("/discover")
def receive_discoveries(
    payload: DiscoveryPayload,
    db: Session = Depends(get_db),
    _key: str = Depends(_verify_api_key),
):
    """Receive device discoveries from a scanner (local or remote).

    All discovered devices go to pending queue:
    1. If MAC already in inventory -> update last_seen
    2. If MAC already in pending -> update last_seen
    3. If new -> insert into pending_devices for review
    4. OUI allowlist used for suggested table mapping only
    """
    now = datetime.utcnow()
    updated_count = 0
    pending_count = 0
    ignored_count = 0  # Kept for response backwards compatibility

    # Determine network segment
    segment_map = {"lab-nuc": "lab", "office-nuc": "office"}
    network_segment = segment_map.get(payload.scanner_id, payload.scanner_id)

    # Load OUI allowlist for suggested table mapping (not filtering)
    active_ouis = (
        db.query(OUIAllowlist)
        .filter(OUIAllowlist.is_active.is_(True))
        .all()
    )
    oui_map = {entry.oui_prefix.upper(): entry for entry in active_ouis}

    for device in payload.devices:
        mac = device.mac.strip().lower()

        # Check if MAC already exists in any inventory table
        found_in_inventory = False
        for table_name, model in TABLE_MODELS.items():
            if not hasattr(model, "mac_address"):
                continue
            existing = (
                db.query(model)
                .filter(model.mac_address.ilike(mac))
                .first()
            )
            if existing:
                existing.last_seen = now
                if hasattr(existing, "ip_address"):
                    existing.ip_address = device.ip
                if hasattr(existing, "network_segment"):
                    existing.network_segment = network_segment
                updated_count += 1
                found_in_inventory = True
                break

        if found_in_inventory:
            continue

        # Check if already in pending (any status)
        already_pending = (
            db.query(PendingDevice)
            .filter(PendingDevice.mac_address.ilike(mac))
            .first()
        )
        if already_pending:
            if already_pending.status == "pending":
                already_pending.last_seen = now
                already_pending.ip_address = device.ip
            continue

        # Get suggested table from OUI allowlist if available
        oui = _get_oui_prefix(mac)
        allowlist_entry = oui_map.get(oui.upper())
        suggested_table = allowlist_entry.maps_to_table if allowlist_entry else "network_equipment"
        manufacturer_hint = allowlist_entry.manufacturer if allowlist_entry else None

        # New device -> pending queue (ALL devices, no OUI filtering)
        pending = PendingDevice(
            mac_address=mac,
            ip_address=device.ip,
            hostname=device.hostname,
            manufacturer=device.manufacturer or manufacturer_hint or "Unknown",
            suggested_table=suggested_table,
            scanner_id=payload.scanner_id,
            network_segment=network_segment,
            first_seen=now,
            last_seen=now,
            status="pending",
        )
        db.add(pending)
        pending_count += 1

    db.commit()

    # Log scan completion
    logger.info(
        "Scanner %s completed on %s: %d scanned, %d updated, %d new pending",
        payload.scanner_id,
        payload.subnet,
        len(payload.devices),
        updated_count,
        pending_count,
    )

    # Publish SSE event if new pending devices
    if pending_count > 0:
        try:
            from .sse import publish_event
            publish_event("device_pending", {"count": pending_count})
        except Exception:
            pass

    return {
        "status": "ok",
        "scanner_id": payload.scanner_id,
        "received": len(payload.devices),
        "updated": updated_count,
        "new_pending": pending_count,
        "ignored": ignored_count,
    }
