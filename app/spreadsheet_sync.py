"""Spreadsheet sync: compare uploaded Excel with database and generate diff.

Handles one-way sync from master spreadsheet → database.
Never writes back to the spreadsheet (read-only).
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from .models import TABLE_MODELS, TABLE_DISPLAY_NAMES

logger = logging.getLogger(__name__)


@dataclass
class DeviceChange:
    """Represents a change to be applied to a device."""
    table: str
    action: str  # "add" | "update" | "skip"
    serial: str
    row_data: dict[str, Any]
    existing_data: Optional[dict[str, Any]] = None
    changes: Optional[dict[str, tuple[Any, Any]]] = None  # field -> (old, new)


def parse_excel(file_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse Excel file and organize rows by table/category.

    Expected Excel structure:
    - Sheet name or "Category" column indicates which inventory table
    - Column headers map to model field names
    - Serial number column for matching (required)

    Returns:
        Dictionary mapping table name -> list of row data dicts
    """
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    tables_data = {}

    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]

        # Read header row
        headers = []
        for cell in sheet[1]:
            if cell.value:
                # Normalize header to lowercase with underscores
                header = str(cell.value).lower().strip().replace(" ", "_")
                headers.append(header)
            else:
                headers.append(None)

        if not headers:
            continue

        # Determine which table this sheet maps to
        table_name = _map_sheet_to_table(sheet_name)
        if not table_name:
            logger.warning(f"Sheet '{sheet_name}' doesn't map to any inventory table, skipping")
            continue

        # Read data rows
        rows = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            # Skip empty rows
            if not any(row):
                continue

            row_data = {}
            for i, value in enumerate(row):
                if i < len(headers) and headers[i]:
                    row_data[headers[i]] = value

            # Only include rows with a serial number
            if row_data.get("serial"):
                rows.append(row_data)

        if rows:
            tables_data[table_name] = rows
            logger.info(f"Parsed {len(rows)} rows from sheet '{sheet_name}' -> {table_name}")

    return tables_data


def _map_sheet_to_table(sheet_name: str) -> Optional[str]:
    """Map Excel sheet name to inventory table name.

    Args:
        sheet_name: Name of the Excel sheet

    Returns:
        Table name from TABLE_MODELS, or None if no match
    """
    # Direct matches
    sheet_lower = sheet_name.lower().strip()

    mapping = {
        "edge boxes": "edge_boxes",
        "edge box": "edge_boxes",
        "trade show": "trade_show_boxes",
        "trade show boxes": "trade_show_boxes",
        "gpus": "gpus",
        "gpu": "gpus",
        "graphics cards": "gpus",
        "part numbers": "part_numbers",
        "parts": "part_numbers",
        "monitors": "monitors",
        "monitor": "monitors",
        "computers": "computers",
        "computer": "computers",
        "laptops": "computers",
        "desktops": "computers",
        "phones": "phones",
        "phone": "phones",
        "mobile devices": "mobile_devices",
        "mobile": "mobile_devices",
        "tablets": "mobile_devices",
        "cameras": "cameras",
        "camera": "cameras",
        "network equipment": "network_equipment",
        "network": "network_equipment",
        "switches": "network_equipment",
        "routers": "network_equipment",
        "access control": "access_control",
        "door controllers": "access_control",
        "webcams": "webcams",
        "webcam": "webcams",
        "printers": "printers",
        "printer": "printers",
        "office equipment": "office_equipment",
        "office": "office_equipment",
        "nas": "nas_devices",
        "nas devices": "nas_devices",
        "storage": "nas_devices",
    }

    return mapping.get(sheet_lower)


def compare_with_database(
    tables_data: dict[str, list[dict[str, Any]]],
    db: Session,
) -> list[DeviceChange]:
    """Compare spreadsheet data with database and generate list of changes.

    Args:
        tables_data: Parsed spreadsheet data organized by table
        db: Database session

    Returns:
        List of DeviceChange objects representing adds/updates/skips
    """
    changes = []

    for table_name, rows in tables_data.items():
        model_class = TABLE_MODELS.get(table_name)
        if not model_class:
            logger.warning(f"Unknown table '{table_name}', skipping")
            continue

        for row_data in rows:
            serial = row_data.get("serial", "").strip()
            if not serial:
                continue

            # Check if device exists in database
            existing = (
                db.query(model_class)
                .filter(model_class.serial == serial)
                .first()
            )

            if not existing:
                # New device to add
                changes.append(DeviceChange(
                    table=table_name,
                    action="add",
                    serial=serial,
                    row_data=row_data,
                ))
            else:
                # Check if any fields changed
                existing_dict = _model_to_dict(existing)
                field_changes = {}

                for field, new_value in row_data.items():
                    if not hasattr(model_class, field):
                        continue

                    old_value = existing_dict.get(field)

                    # Normalize for comparison
                    old_norm = _normalize_value(old_value)
                    new_norm = _normalize_value(new_value)

                    if old_norm != new_norm:
                        field_changes[field] = (old_value, new_value)

                if field_changes:
                    # Device has updates
                    changes.append(DeviceChange(
                        table=table_name,
                        action="update",
                        serial=serial,
                        row_data=row_data,
                        existing_data=existing_dict,
                        changes=field_changes,
                    ))
                else:
                    # No changes, skip
                    changes.append(DeviceChange(
                        table=table_name,
                        action="skip",
                        serial=serial,
                        row_data=row_data,
                        existing_data=existing_dict,
                    ))

    return changes


def _model_to_dict(instance) -> dict[str, Any]:
    """Convert SQLAlchemy model instance to dict."""
    result = {}
    for column in instance.__table__.columns:
        result[column.name] = getattr(instance, column.name)
    return result


def _normalize_value(value: Any) -> Any:
    """Normalize value for comparison (strip whitespace, handle None/empty)."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value.strip()
    return value


def apply_changes(
    changes: list[DeviceChange],
    db: Session,
    user_id: int,
) -> dict[str, int]:
    """Apply approved changes to the database.

    Args:
        changes: List of DeviceChange objects to apply
        db: Database session
        user_id: ID of user applying changes (for audit log)

    Returns:
        Stats dict with counts: added, updated, skipped
    """
    from .audit import log_event
    from .models import compute_completeness

    stats = {"added": 0, "updated": 0, "skipped": 0}

    for change in changes:
        model_class = TABLE_MODELS[change.table]

        if change.action == "add":
            # Create new device
            kwargs = {}
            for field, value in change.row_data.items():
                if hasattr(model_class, field):
                    kwargs[field] = value

            # Set discovered_by to indicate spreadsheet import
            kwargs["discovered_by"] = "spreadsheet_sync"

            device = model_class(**kwargs)
            device.data_completeness = compute_completeness(device)
            db.add(device)
            stats["added"] += 1

            log_event(
                db, "device_added",
                user_id=user_id,
                target_table=change.table,
                action="create",
                new_values=kwargs,
                details=f"Spreadsheet sync: added {change.serial}",
            )

        elif change.action == "update":
            # Update existing device
            existing = (
                db.query(model_class)
                .filter(model_class.serial == change.serial)
                .first()
            )
            if not existing:
                continue

            old_values = _model_to_dict(existing)

            for field, new_value in change.row_data.items():
                if hasattr(model_class, field):
                    setattr(existing, field, new_value)

            existing.data_completeness = compute_completeness(existing)
            stats["updated"] += 1

            log_event(
                db, "device_updated",
                user_id=user_id,
                target_table=change.table,
                target_id=existing.id,
                action="update",
                old_values=old_values,
                new_values=change.row_data,
                details=f"Spreadsheet sync: updated {change.serial}",
            )

        else:  # skip
            stats["skipped"] += 1

    db.commit()
    return stats
