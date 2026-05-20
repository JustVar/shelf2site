"""OUI (Organizationally Unique Identifier) lookup for MAC addresses.

Resolves the first 3 octets of a MAC address to a manufacturer name
using the local IEEE OUI database (no network calls).
"""

import logging

logger = logging.getLogger(__name__)

_lookup = None


def _get_lookup():
    """Lazy-load the MAC vendor lookup database."""
    global _lookup
    if _lookup is None:
        try:
            from mac_vendor_lookup import MacLookup
            _lookup = MacLookup()
            _lookup.update_vendors()  # Download/update on first use
            logger.info("MAC vendor database loaded")
        except ImportError:
            logger.error(
                "mac-vendor-lookup not installed. "
                "Install with: pip install mac-vendor-lookup"
            )
        except Exception as e:
            logger.warning(f"Failed to load vendor database: {e}")
    return _lookup


def lookup_manufacturer(mac: str) -> str | None:
    """Look up the manufacturer for a MAC address.

    Args:
        mac: MAC address in any common format (aa:bb:cc:dd:ee:ff, AA-BB-CC-DD-EE-FF, etc.)

    Returns:
        Manufacturer name or None if not found.
    """
    lookup = _get_lookup()
    if lookup is None:
        return None

    try:
        return lookup.lookup(mac)
    except Exception:
        return None


# Well-known OUI prefixes for auto-classification
# Maps manufacturer to inventory table name
MANUFACTURER_TABLE_MAP = {
    "Hanwha": "cameras",
    "Hanwha Techwin": "cameras",
    "Samsung Techwin": "cameras",
    "Axis Communications": "cameras",
    "i-PRO": "cameras",
    "Panasonic i-PRO": "cameras",
    "Avigilon": "cameras",
    "Vivotek": "cameras",
    "Hikvision": "cameras",
    "Dahua": "cameras",
    "Yealink": "phones",
    "HP": "printers",
    "Hewlett Packard": "printers",
    "Brother": "printers",
    "Cisco": "network_equipment",
    "Ubiquiti": "network_equipment",
    "Netgear": "network_equipment",
    "TP-Link": "network_equipment",
}


def classify_by_manufacturer(manufacturer: str | None) -> str | None:
    """Suggest an inventory table based on manufacturer name.

    Returns:
        Table name string or None if no match.
    """
    if not manufacturer:
        return None
    for key, table in MANUFACTURER_TABLE_MAP.items():
        if key.lower() in manufacturer.lower():
            return table
    return None
