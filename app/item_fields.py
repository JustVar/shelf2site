"""Per-category attribute definitions for the unified item detail page.

Common fields (name, manufacturer, model, serial, status, location,
department, MAC addresses, SKU/PN, dates, notes) live as top-level
columns on item_schema.items and are rendered by the shared skeleton.

This module defines only the CATEGORY-SPECIFIC fields, stored in the
items.attributes JSONB column. Each entry is (json_key, label).

IMPORTANT: dict keys MUST match the item_schema.item_categories ENUM
values exactly (e.g. 'storage_drive', not 'hard_drive'). All 27 enum
values are present below; categories with no extra fields map to [].

Excluded by design:
- Scanner-era fields (ip_address, network_segment, last_seen) — scanner removed.
- Component-install fields (installed-in, slot, installed date) — come from
  item_schema.component_history, not attributes.
- Warranty — comes from device_warranties, handled separately.
"""

_DEPLOYMENT = [
    ("form_factor", "Form Factor"),
    ("deployment_type", "Deployment"),
    ("sku_version", "SKU Version"),
    ("system_uuid", "System UUID"),
    ("customer", "Customer"),
    ("partner", "Partner"),
    ("service_type", "Service Type"),
]

# key == item_schema.item_categories ENUM value -> [(attr_json_key, label), ...]
CATEGORY_ATTRIBUTES = {
    # --- network / surveillance devices ---
    "access_control": [("deployment_type", "Deployment")],
    "camera": [("deployment_type", "Deployment")],
    "camera_c2c": [("deployment_type", "Deployment")],
    "network": [],

    # --- computers / managed endpoints ---
    "computer": [
        ("operating_system", "Operating System"),
        ("os_version", "OS Version"),
        ("device_type", "Device Type"),
        ("primary_user_upn", "Primary User UPN"),
        ("intune_device_id", "Intune Device ID"),
        ("intune_compliance", "Intune Compliance"),
        ("last_check_in", "Last Check-in"),
    ],

    # --- PC components ---
    "cpu": [("socket", "Socket")],
    "motherboard": [("socket", "Socket")],
    "gpu": [],
    "storage_drive": [
        ("drive_type", "Drive Type"),
        ("form_factor", "Form Factor"),
        ("capacity_gb", "Capacity (GB)"),
        ("interface", "Interface"),
        ("rpm", "RPM"),
    ],
    "ram": [
        ("ram_type", "RAM Type"),
        ("capacity_gb", "Capacity (GB)"),
        ("ram_speed_mhz", "Speed (MHz)"),
    ],
    "psu": [
        ("wattage_rating", "Wattage Rating"),
        ("efficiency", "Efficiency"),
    ],
    "cpu_cooler": [
        ("cooling_type", "Cooling Type"),
        ("fan_speed_rpm", "Fan Speed (RPM)"),
    ],
    "case_fan": [
        ("fan_speed_rpm", "Fan Speed (RPM)"),
    ],
    "pc_accessories": [("accessory_type", "Accessory Type")],
    "pci": [],
    "product_cabling": [],
    "consumables": [],

    # --- deployment-rich devices ---
    "edge_box": list(_DEPLOYMENT),
    "cloud_box": list(_DEPLOYMENT),

    # --- power / field devices ---
    "ups": [
        ("va_rating", "VA Rating"),
        ("wattage", "Wattage"),
    ],
    "mobile_device": [],
    "monitor": [],
    "office_equipment": [],

    # --- added by item 30 (migration 080) ---
    "phone": [],
    "webcam": [],
    "printer": [],
    "nas": [],
}


def attributes_for(category):
    """Return the (key, label) list for a category, or [] if unknown/None.

    `category` may be a string or the SQLAlchemy enum value; coerced to str.
    """
    if category is None:
        return []
    return CATEGORY_ATTRIBUTES.get(str(category), [])
