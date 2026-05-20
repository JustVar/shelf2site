"""Data validation utilities for hardware asset tracker."""

import re
from typing import Any


def validate_mac_address(mac: str) -> tuple[bool, str | None]:
    """
    Validate MAC address format.

    Accepts formats:
    - AA:BB:CC:DD:EE:FF
    - AA-BB-CC-DD-EE-FF
    - AABBCCDDEEFF

    Returns:
        (is_valid, normalized_mac_or_error)
    """
    if not mac:
        return True, None  # Empty is allowed

    mac = mac.strip().upper()

    # Remove common separators
    clean_mac = mac.replace(":", "").replace("-", "").replace(".", "")

    # Check if it's exactly 12 hex characters
    if len(clean_mac) != 12:
        return False, f"MAC address must be 12 hex characters (got {len(clean_mac)})"

    if not re.match(r'^[0-9A-F]{12}$', clean_mac):
        return False, "MAC address must contain only hexadecimal characters (0-9, A-F)"

    # Normalize to colon-separated format
    normalized = ":".join([clean_mac[i:i+2] for i in range(0, 12, 2)])
    return True, normalized


def validate_serial_number(serial: str, required: bool = True) -> tuple[bool, str | None]:
    """
    Validate serial number.

    Returns:
        (is_valid, error_message)
    """
    if not serial or not serial.strip():
        if required:
            return False, "Serial number is required"
        return True, None

    serial = serial.strip()

    # Basic validation: non-empty, reasonable length, no special characters
    if len(serial) < 3:
        return False, "Serial number too short (minimum 3 characters)"

    if len(serial) > 100:
        return False, "Serial number too long (maximum 100 characters)"

    return True, None


def validate_ip_address(ip: str) -> tuple[bool, str | None]:
    """
    Validate IPv4 address format.

    Returns:
        (is_valid, error_message)
    """
    if not ip:
        return True, None  # Empty is allowed

    ip = ip.strip()

    # Basic IPv4 regex
    pattern = r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$'
    match = re.match(pattern, ip)

    if not match:
        return False, "Invalid IP address format (expected: xxx.xxx.xxx.xxx)"

    # Check each octet is 0-255
    for octet in match.groups():
        if int(octet) > 255:
            return False, f"IP address octet {octet} out of range (0-255)"

    return True, None


def validate_required_fields(data: dict[str, Any], required_fields: list[str]) -> dict[str, str]:
    """
    Validate that required fields are present and non-empty.

    Returns:
        Dictionary mapping field_name -> error_message for any validation failures
    """
    errors = {}

    for field in required_fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors[field] = f"{field.replace('_', ' ').title()} is required"

    return errors


def get_category_required_fields(table_name: str) -> list[str]:
    """
    Get list of required fields for a given device category.

    Returns:
        List of field names that are required for this category
    """
    # Common required fields for all categories
    common_required = ["serial"]

    # Category-specific required fields
    category_requirements = {
        "nas_devices": ["serial", "manufacturer", "model", "bay_count"],
        "cameras": ["serial", "manufacturer", "model"],
        "gpus": ["serial", "manufacturer", "model"],
        "computers": ["serial", "manufacturer"],
        "network_equipment": ["serial", "manufacturer", "device"],
        "monitors": ["serial", "manufacturer", "model"],
        "printers": ["serial", "manufacturer", "model"],
        "mobile_devices": ["serial", "manufacturer", "device"],
        "storage_drives": ["serial", "manufacturer"],
    }

    return category_requirements.get(table_name, common_required)
