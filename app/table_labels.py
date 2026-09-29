"""Display labels for the retired legacy table names (item 30 S5).

The 22 per-category public tables are gone, but their names live on as a
vocabulary in two places: audit history (audit_log.target_table keeps the
string it was written with) and the OUI reference, whose maps_to_table
column records a device-type hint by the old table name. This dict labels
both. It is a vocabulary only; nothing here reads a table.
"""

LEGACY_TABLE_LABELS = {
    "edge_boxes": "Edge Boxes",
    "gpus": "GPUs",
    "monitors": "Monitors",
    "computers": "Computers",
    "phones": "Phones",
    "mobile_devices": "Mobile Devices",
    "cameras": "Cameras",
    "network_equipment": "Network Equipment",
    "access_control": "Access Control",
    "webcams": "Webcams",
    "printers": "Printers",
    "office_equipment": "Office Equipment",
    "nas_devices": "NAS Devices",
    "nucs": "NUCs",
    "ups": "UPS",
    "ram_modules": "RAM Modules",
    "cpus": "CPUs",
    "psus": "PSUs",
    "motherboards": "Motherboards",
    "pc_cooling": "PC Cooling",
    "pc_accessories": "PC Accessories",
    "hard_drives": "Hard Drives",
}
