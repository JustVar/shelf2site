"""Vendor/model defaults for auto-fill during intake scanning."""

VENDOR_MODEL_DEFAULTS = {
    "QNAP TS-264": {
        "manufacturer": "QNAP",
        "model": "TS-264",
        "bay_count": 2,
        "ram_gb": "8",
        "target_table": "nas_devices",
    },
    "QNAP TS-464": {
        "manufacturer": "QNAP",
        "model": "TS-464",
        "bay_count": 4,
        "ram_gb": "8",
        "target_table": "nas_devices",
    },
}


def lookup_by_serial_prefix(serial: str) -> dict | None:
    """Try to identify device type from serial number prefix patterns."""
    serial_upper = serial.upper().strip()
    # QNAP serials: Q + alphanumeric (e.g., Q854310683Q, Q7FQM099133)
    if serial_upper.startswith("Q") and len(serial_upper) >= 10:
        return {
            "manufacturer": "QNAP",
            "target_table": "nas_devices",
        }
    return None


def lookup_by_model(model: str) -> dict | None:
    """Get defaults for a known model string."""
    return VENDOR_MODEL_DEFAULTS.get(model)
