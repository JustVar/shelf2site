"""Discovery pipeline: processes scan results and adds to pending queue.

Used by the local scanner (NUC 1) in its async background loop.
Remote scanners (NUC 2+) POST to the /api/discover endpoint instead.

ALL discovered devices go to the pending queue for review.
OUI allowlist is auto-populated when devices are approved.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _get_oui_prefix(mac: str) -> str:
    """Extract the first 3 octets (OUI) from a MAC address."""
    clean = mac.replace("-", ":").upper()
    parts = clean.split(":")
    if len(parts) >= 3:
        return ":".join(parts[:3])
    return clean[:8]


def process_discoveries(
    session: Session,
    devices: list,
    scanner_id: str,
    network_segment: str,
):
    """Process a batch of discovered devices (no OUI filtering).

    For each device:
    1. If already in inventory -> update last_seen
    2. If new -> insert into pending_devices for review
    3. OUI allowlist is auto-populated when devices are approved
    """
    from app.models import (
        TABLE_MODELS, OUIAllowlist, PendingDevice, AuditLog,
    )
    from .oui_lookup import lookup_manufacturer

    now = datetime.utcnow()
    updated_count = 0
    pending_count = 0
    ignored_count = 0  # Keep for backwards compatibility with logs

    # Optional: Load OUI allowlist for suggested table mapping
    active_ouis = (
        session.query(OUIAllowlist)
        .filter(OUIAllowlist.is_active.is_(True))
        .all()
    )
    oui_map = {entry.oui_prefix.upper(): entry for entry in active_ouis}

    for device in devices:
        mac = device.mac.strip().lower()

        # Enrich with OUI lookup if manufacturer not already set
        if not device.manufacturer:
            device.manufacturer = lookup_manufacturer(mac)

        # Check if MAC already exists in any inventory table
        found_in_inventory = False
        for table_name, model in TABLE_MODELS.items():
            if not hasattr(model, "mac_address"):
                continue

            existing = (
                session.query(model)
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
            session.query(PendingDevice)
            .filter(PendingDevice.mac_address.ilike(mac))
            .first()
        )
        if already_pending:
            if already_pending.status == "pending":
                already_pending.last_seen = now
                already_pending.ip_address = device.ip
            continue

        # Get suggested table from OUI allowlist (if available) or default to network_equipment
        oui = _get_oui_prefix(mac)
        allowlist_entry = oui_map.get(oui.upper())
        suggested_table = allowlist_entry.maps_to_table if allowlist_entry else "network_equipment"
        manufacturer_hint = allowlist_entry.manufacturer if allowlist_entry else None

        # New device -> pending queue (ALL devices, not just allowlisted)
        pending = PendingDevice(
            mac_address=mac,
            ip_address=device.ip,
            hostname=device.hostname,
            manufacturer=device.manufacturer or manufacturer_hint or "Unknown",
            suggested_table=suggested_table,
            scanner_id=scanner_id,
            network_segment=network_segment,
            first_seen=now,
            last_seen=now,
            status="pending",
        )
        session.add(pending)
        pending_count += 1

    session.commit()

    # Audit log entry
    audit = AuditLog(
        timestamp=now,
        event_type="scan_completed",
        target_table="pending_devices",
        action="create",
        details=(
            f"Local scanner {scanner_id}: "
            f"{len(devices)} scanned, {updated_count} updated, "
            f"{pending_count} new pending, {ignored_count} ignored"
        ),
        new_values={
            "scanned": len(devices),
            "updated": updated_count,
            "new_pending": pending_count,
            "ignored": ignored_count,
        },
    )
    session.add(audit)
    session.commit()

    logger.info(
        f"Discovery batch from {scanner_id}: "
        f"{len(devices)} scanned, {updated_count} updated, "
        f"{pending_count} new pending, {ignored_count} ignored"
    )

    # Publish SSE event if new pending devices
    if pending_count > 0:
        try:
            from app.routes.sse import publish_event
            publish_event("device_pending", {"count": pending_count})
        except Exception:
            pass

    return updated_count, pending_count, ignored_count


def mark_offline_devices(session: Session, timeout_hours: int = 24):
    """Mark scanner-discovered devices as offline if not seen within timeout."""
    from app.models import TABLE_MODELS

    cutoff = datetime.utcnow() - timedelta(hours=timeout_hours)

    for table_name, model in TABLE_MODELS.items():
        if not hasattr(model, "last_seen") or not hasattr(model, "status"):
            continue

        stale = (
            session.query(model)
            .filter(
                model.last_seen.isnot(None),
                model.last_seen < cutoff,
                model.status != "Offline",
                model.status != "Decommissioned",
                model.discovered_by.like("scanner:%"),
            )
            .all()
        )
        for device in stale:
            device.status = "Offline"
            logger.info(
                f"Marked {table_name} id={device.id} as Offline "
                f"(last seen: {device.last_seen})"
            )

    session.commit()


async def run_local_scanner_loop():
    """Async background loop for the local scanner on NUC 1.

    Scans configured subnets on a fixed interval and processes results
    through the OUI allowlist filter.
    """
    from app.config import settings
    from app.database import SessionLocal
    from .network_scanner import scan_subnets

    interval = settings.SCAN_INTERVAL_SECONDS
    scanner_id = settings.SCANNER_ID
    subnets = settings.SCAN_SUBNETS

    logger.info(
        f"Local scanner starting: subnets={subnets}, interval={interval}s, "
        f"id={scanner_id}"
    )

    while True:
        try:
            devices = await asyncio.to_thread(scan_subnets, subnets)

            if devices:
                session = SessionLocal()
                try:
                    process_discoveries(session, devices, scanner_id, "lab")
                    mark_offline_devices(session)
                finally:
                    session.close()

        except asyncio.CancelledError:
            logger.info("Local scanner loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Scanner loop error: {e}")

        await asyncio.sleep(interval)
