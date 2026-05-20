"""OUI utility functions for automatic OUI allowlist management."""

import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_oui_prefix(mac: str) -> str:
    """Extract the first 3 octets (OUI) from a MAC address.

    Args:
        mac: MAC address in any format (AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, etc.)

    Returns:
        OUI prefix in format "AA:BB:CC"
    """
    if not mac:
        return ""

    clean = mac.replace("-", ":").upper()
    parts = clean.split(":")
    if len(parts) >= 3:
        return ":".join(parts[:3])

    # Fallback for malformed MAC
    clean_no_sep = mac.replace(":", "").replace("-", "").upper()
    if len(clean_no_sep) >= 6:
        return f"{clean_no_sep[:2]}:{clean_no_sep[2:4]}:{clean_no_sep[4:6]}"

    return ""


def auto_add_oui(
    db: Session,
    mac_address: str,
    manufacturer: str | None = None,
    table_name: str | None = None,
) -> bool:
    """Automatically add OUI to allowlist if not present.

    Args:
        db: Database session
        mac_address: Device MAC address
        manufacturer: Optional manufacturer name (will be looked up if not provided)
        table_name: Optional table name for categorization (e.g., "cameras", "phones")

    Returns:
        True if OUI was added, False if already exists or invalid MAC
    """
    from app.models import OUIAllowlist
    from scanner.oui_lookup import lookup_manufacturer

    if not mac_address:
        return False

    oui = get_oui_prefix(mac_address)
    if not oui:
        logger.warning(f"Could not extract OUI from MAC: {mac_address}")
        return False

    # Check if OUI already exists
    existing = db.query(OUIAllowlist).filter(
        OUIAllowlist.oui_prefix == oui
    ).first()

    if existing:
        return False

    # Lookup manufacturer if not provided
    if not manufacturer:
        manufacturer = lookup_manufacturer(mac_address)
        if not manufacturer:
            manufacturer = "Unknown Manufacturer"

    # Determine table mapping from device type
    maps_to_table = table_name or "network_equipment"

    # Add new OUI entry
    new_oui = OUIAllowlist(
        oui_prefix=oui,
        manufacturer=manufacturer,
        maps_to_table=maps_to_table,
        is_active=True,
    )
    db.add(new_oui)

    try:
        db.commit()
        logger.info(f"Auto-added OUI: {oui} -> {manufacturer} ({maps_to_table})")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to auto-add OUI {oui}: {e}")
        return False


def auto_add_oui_batch(
    db: Session,
    mac_addresses: list[str],
    manufacturer: str | None = None,
    table_name: str | None = None,
) -> int:
    """Add multiple OUIs in batch (more efficient for imports).

    Args:
        db: Database session
        mac_addresses: List of MAC addresses to process
        manufacturer: Optional manufacturer name for all MACs
        table_name: Optional table name for categorization

    Returns:
        Count of OUIs added
    """
    added_count = 0
    ouis_seen = set()

    for mac in mac_addresses:
        if not mac:
            continue

        oui = get_oui_prefix(mac)
        if not oui or oui in ouis_seen:
            continue

        ouis_seen.add(oui)
        if auto_add_oui(db, mac, manufacturer, table_name):
            added_count += 1

    return added_count
