"""SKU conversion utilities — old PVA SKUs to new 2026 EDGE SKUs.

Based on Old_to_New_SKU_Crosswalk_v3.xlsx (2026-02-18).

Usage:
    from app.sku_conversion import convert_legacy_sku, is_legacy_sku

    new_sku = convert_legacy_sku("PVA-25-30NR")  # Returns "EDGE25-56TB-NR"
    is_old = is_legacy_sku("PVA-50-60R6")  # Returns True
"""

# Old SKU → New SKU mapping (from crosswalk v3)
LEGACY_SKU_MAPPING = {
    # RAID6 (R6) variants
    "PVA-25-30R6": "PVA50-84TB-Z2",
    "PVA-25-60R6": "PVA50-84TB-Z2",
    "PVA-25-90R6": "PVA50-108TB-Z2",
    "PVA-50-30R6": "PVA50-84TB-Z2",
    "PVA-50-60R6": "PVA50-120TB-Z2",
    "PVA-50-90R6": "PVA100-180TB-Z2",
    "PVA-75-30R6": "PVA100-140TB-Z2",
    "PVA-75-60R6": "PVA100-180TB-Z2",
    "PVA-75-90R6": "PVA200-308TB-Z2",
    "PVA-100-30R6": "PVA100-140TB-Z2",
    "PVA-100-60R6": "PVA200-308TB-Z2",
    "PVA-100-90R6": "PVA200-396TB-Z2",
    "PVA-200-30R6": "PVA200-308TB-Z2",
    "PVA-200-60R6": "PVA300-476TB-Z2",
    "PVA-200-90R6": "PVA200-396TB-Z2",
    "PVA-300-30R6": "PVA300-476TB-Z2",
    "PVA-300-60R6": "PVA200-396TB-Z2",
    "PVA-300-90R6": "PVA300-612TB-Z2",

    # RAID5 (R5) variants — retired, mapped to Z2
    "PVA-25-30R5": "PVA50-84TB-Z2",
    "PVA-25-60R5": "PVA50-84TB-Z2",
    "PVA-25-90R5": "PVA50-108TB-Z2",
    "PVA-50-30R5": "PVA50-84TB-Z2",
    "PVA-50-60R5": "PVA50-120TB-Z2",
    "PVA-50-90R5": "PVA100-180TB-Z2",

    # No RAID (NR) variants
    "PVA-10-30NR": "EDGE10-28TB-NR",
    "PVA-10-60NR": "EDGE10-28TB-NR",
    "PVA-10-90NR": "EDGE10-36TB-NR",
    "PVA-25-30SFF": "EDGE25-56TB-NR",
    "PVA-25-30NR": "EDGE25-56TB-NR",
    "PVA-25-60NR": "EDGE25-72TB-NR",
    "PVA-25-90NR": "EDGE50-112TB-NR",
    "PVA-50-30NR": "EDGE50-112TB-NR",
    "PVA-50-60NR": "EDGE50-144TB-NR",
    "PVA-50-90NR": "EDGE100-216TB-NR",
    "PVA-75-30NR": "EDGE100-168TB-NR",
    "PVA-75-60NR": "EDGE100-216TB-NR",
    "PVA-75-90NR": "EDGE50-144TB-NR",
    "PVA-100-30NR": "EDGE100-168TB-NR",
    "PVA-100-60NR": "EDGE100-240TB-NR",
    "PVA-100-90NR": "EDGE100-216TB-NR",
    "PVA-200-30NR": "EDGE100-168TB-NR",
    "PVA-200-60NR": "EDGE100-240TB-NR",
    "PVA-200-90NR": "EDGE100-240TB-NR",
    "PVA-300-30NR": "EDGE100-168TB-NR",
    "PVA-300-60NR": "EDGE100-240TB-NR",
    "PVA-300-90NR": "EDGE100-216TB-NR",
}

# Reverse mapping for lookup
NEW_TO_LEGACY_MAPPING = {}
for old_sku, new_sku in LEGACY_SKU_MAPPING.items():
    if new_sku not in NEW_TO_LEGACY_MAPPING:
        NEW_TO_LEGACY_MAPPING[new_sku] = []
    NEW_TO_LEGACY_MAPPING[new_sku].append(old_sku)


def is_legacy_sku(sku: str) -> bool:
    """Check if SKU follows legacy PVA-* format."""
    return sku.startswith("PVA-") if sku else False


def is_2026_sku(sku: str) -> bool:
    """Check if SKU follows 2026 EDGE* format."""
    return sku.startswith("EDGE") or sku.startswith("PVA") and "TB" in sku if sku else False


def convert_legacy_sku(legacy_sku: str) -> str:
    """Convert legacy PVA-* SKU to new 2026 EDGE* SKU.

    Args:
        legacy_sku: Old SKU format (e.g., "PVA-25-30NR")

    Returns:
        New SKU format (e.g., "EDGE25-56TB-NR"), or original if no mapping found
    """
    return LEGACY_SKU_MAPPING.get(legacy_sku, legacy_sku)


def get_legacy_skus_for_new(new_sku: str) -> list:
    """Get all legacy SKUs that map to a given new SKU.

    Args:
        new_sku: New SKU format (e.g., "EDGE25-56TB-NR")

    Returns:
        List of legacy SKUs that convert to this new SKU
    """
    return NEW_TO_LEGACY_MAPPING.get(new_sku, [])


def get_sku_version(sku: str) -> str:
    """Determine SKU version from SKU string.

    Args:
        sku: SKU string

    Returns:
        "legacy" or "2026"
    """
    if is_legacy_sku(sku):
        return "legacy"
    elif is_2026_sku(sku):
        return "2026"
    else:
        return "legacy"  # Default to legacy if unknown


def extract_sku_info(sku: str) -> dict:
    """Parse SKU and extract component information.

    Args:
        sku: SKU string (legacy or 2026 format)

    Returns:
        Dict with keys: channels, storage_tb, raid_type, version
    """
    info = {
        "channels": None,
        "storage_tb": None,
        "raid_type": None,
        "version": get_sku_version(sku),
        "chassis": None,
    }

    if is_legacy_sku(sku):
        # Parse PVA-{channels}-{retention}{RAID}
        parts = sku.split("-")
        if len(parts) >= 3:
            info["channels"] = parts[1]
            retention_raid = parts[2]
            if retention_raid.endswith("NR"):
                info["raid_type"] = "NR"
            elif retention_raid.endswith("R6"):
                info["raid_type"] = "R6"
            elif retention_raid.endswith("R5"):
                info["raid_type"] = "R5"

    elif is_2026_sku(sku):
        # Parse EDGE{channels}-{storage}TB-{RAID}
        if sku.startswith("EDGE"):
            # Extract channels (longest match first to avoid EDGE100 matching EDGE10)
            for ch in ["300", "200", "100", "50", "25", "10"]:
                if sku.startswith(f"EDGE{ch}"):
                    info["channels"] = ch
                    break

            # Extract storage TB
            if "TB" in sku:
                parts = sku.split("-")
                for part in parts:
                    if "TB" in part:
                        info["storage_tb"] = part.replace("TB", "")
                        break

            # Extract RAID type
            if sku.endswith("-NR"):
                info["raid_type"] = "NR"
            elif sku.endswith("-Z2"):
                info["raid_type"] = "Z2"

        # Determine chassis from channels and storage
        if info["channels"]:
            ch = int(info["channels"])
            if ch <= 10:
                info["chassis"] = "SFF" if "SFF" in sku else "1U"
            elif ch <= 25:
                info["chassis"] = "1U"
            elif ch <= 50:
                info["chassis"] = "1U" if info["storage_tb"] and int(info["storage_tb"]) < 100 else "2U"
            elif ch >= 100:
                info["chassis"] = "2U"

    return info
