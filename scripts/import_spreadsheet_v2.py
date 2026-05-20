"""Enhanced hardware inventory import with validation, incremental updates, and error handling.

Features:
- Validation/preview mode (--dry-run): Shows what would be imported without committing
- Incremental updates: Updates existing devices by serial number instead of requiring empty tables
- Detailed error reporting: Per-row error tracking with line numbers and device info
- Import summary: Shows adds, updates, skips, and errors

Usage:
    python scripts/import_spreadsheet_v2.py                # Full import with incremental updates
    python scripts/import_spreadsheet_v2.py --dry-run      # Preview mode (no database changes)
    python scripts/import_spreadsheet_v2.py --validate     # Alias for --dry-run
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

# Ensure repo root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.config import settings
from app.credentials import encrypt
from app.database import SessionLocal, create_all_tables
from app.models import (
    AccessControl, Camera, Computer, DeviceCredential, EdgeBox, GPU,
    MobileDevice, Monitor, NetworkEquipment, NASDevice, OfficeEquipment,
    PartNumber, Phone, Printer, TradeShowBox, Webcam, compute_completeness,
)


@dataclass
class ImportStats:
    """Track import statistics per table."""
    table_name: str
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return self.added + self.updated + self.skipped

    def add_error(self, row_num: int, serial: str | None, error: str):
        """Add an error with context."""
        self.errors.append({
            "row": row_num,
            "serial": serial or "N/A",
            "error": error,
        })

    def print_summary(self):
        """Print formatted summary for this table."""
        print(f"\n{self.table_name}:")
        print(f"  Added:   {self.added:>4}")
        print(f"  Updated: {self.updated:>4}")
        print(f"  Skipped: {self.skipped:>4}")
        if self.errors:
            print(f"  Errors:  {len(self.errors):>4} ⚠️")
            for err in self.errors[:5]:  # Show first 5 errors
                print(f"    Row {err['row']} ({err['serial']}): {err['error']}")
            if len(self.errors) > 5:
                print(f"    ... and {len(self.errors) - 5} more errors")


class ImportContext:
    """Shared import context for validation and dry-run mode."""
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.stats: dict[str, ImportStats] = {}
        self.credentials_queue: list[dict] = []

    def get_stats(self, table_name: str) -> ImportStats:
        """Get or create stats for a table."""
        if table_name not in self.stats:
            self.stats[table_name] = ImportStats(table_name)
        return self.stats[table_name]

    def print_summary(self):
        """Print overall import summary."""
        print("\n" + "=" * 70)
        if self.dry_run:
            print("VALIDATION SUMMARY (DRY RUN - NO CHANGES MADE)")
        else:
            print("IMPORT SUMMARY")
        print("=" * 70)

        total_added = sum(s.added for s in self.stats.values())
        total_updated = sum(s.updated for s in self.stats.values())
        total_skipped = sum(s.skipped for s in self.stats.values())
        total_errors = sum(len(s.errors) for s in self.stats.values())

        for stats in self.stats.values():
            stats.print_summary()

        print("\n" + "-" * 70)
        print(f"TOTAL:")
        print(f"  Added:           {total_added:>4}")
        print(f"  Updated:         {total_updated:>4}")
        print(f"  Skipped:         {total_skipped:>4}")
        print(f"  Errors:          {total_errors:>4}")
        print(f"  Credentials:     {len(self.credentials_queue):>4}")
        print("=" * 70)

        if total_errors > 0:
            print(f"\n⚠️  {total_errors} error(s) occurred during import")
            if not self.dry_run:
                print("   Review errors above and fix source data if needed")


# ============================================================================
# Helper functions (same as original but with error handling)
# ============================================================================

def _read_sheet(wb, sheet_name: str) -> list[dict]:
    """Read a worksheet into a list of dicts keyed by header names."""
    if sheet_name not in wb.sheetnames:
        print(f"  [SKIP] Sheet '{sheet_name}' not found")
        return []
    ws = wb[sheet_name]
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True), start=2):
        if all(v is None for v in row):
            continue
        row_data = dict(zip(headers, row))
        row_data["__row_num__"] = row_idx  # Track source row number for error reporting
        rows.append(row_data)
    return rows


def _to_str(val) -> str | None:
    """Convert a cell value to a trimmed string or None."""
    if val is None:
        return None
    try:
        s = str(val).strip()
        return s if s else None
    except Exception:
        return None


def _to_datetime(val) -> datetime | None:
    """Convert value to datetime if possible."""
    if isinstance(val, datetime):
        return val
    return None


def _extract_pin(notes: str | None) -> str | None:
    """Extract a PIN from a notes field like 'PIN: 121234'."""
    if not notes:
        return None
    match = re.search(r"PIN:\s*(\S+)", notes, re.IGNORECASE)
    return match.group(1) if match else None


def _strip_pin_from_notes(notes: str | None) -> str | None:
    """Remove PIN references from notes text."""
    if not notes:
        return None
    cleaned = re.sub(r"PIN:\s*\S+", "", notes, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else None


def _extract_printer_creds(notes: str | None) -> tuple[str | None, str | None]:
    """Extract username and PIN from printer notes."""
    if not notes:
        return None, None
    username = None
    pin = None
    u_match = re.search(r"Username:\s*(\S+)", notes, re.IGNORECASE)
    if u_match:
        username = u_match.group(1).rstrip(",")
    p_match = re.search(r"PIN:\s*(\S+)", notes, re.IGNORECASE)
    if p_match:
        pin = p_match.group(1)
    return username, pin


def _strip_creds_from_notes(notes: str | None) -> str | None:
    """Remove credential references from notes text."""
    if not notes:
        return None
    cleaned = re.sub(r"Username:\s*\S+,?\s*", "", notes, flags=re.IGNORECASE)
    cleaned = re.sub(r"PIN:\s*\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    return cleaned if cleaned else None


# ============================================================================
# Incremental import functions (update existing or insert new)
# ============================================================================

def import_edge_boxes_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import edge boxes with incremental update support."""
    stats = ctx.get_stats("edge_boxes")
    sheets_to_merge = ["Edge Boxes"]  # Can add more sheets if needed

    all_rows = []
    for sheet_name in sheets_to_merge:
        rows = _read_sheet(wb, sheet_name)
        all_rows.extend(rows)

    print(f"Processing {len(all_rows)} edge box rows...")

    for row in all_rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            if not serial:
                stats.skipped += 1
                continue

            # Check if device exists
            existing = session.query(EdgeBox).filter(EdgeBox.serial == serial).first()

            # Build device data
            device_data = {
                "serial": serial,
                "part_number": _to_str(row.get("Part Number")),
                "model": _to_str(row.get("Model")),
                "mac_address": _to_str(row.get("MAC Address")),
                "organization": _to_str(row.get("Organization")),
                "customer_name": _to_str(row.get("Customer")),
                "site_name": _to_str(row.get("Site")),
                "status": _to_str(row.get("Status")),
                "deployment_type": _to_str(row.get("Deployment")),
                "location": _to_str(row.get("Location")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
                "last_updated": datetime.utcnow(),
            }

            if existing:
                # Update existing device
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)  # Don't persist in dry-run
            else:
                # Create new device
                device = EdgeBox(**device_data)
                device.data_completeness = compute_completeness(device)
                if not ctx.dry_run:
                    session.add(device)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_cameras_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import cameras with incremental update support."""
    stats = ctx.get_stats("cameras")
    rows = _read_sheet(wb, "Cameras")

    print(f"Processing {len(rows)} camera rows...")

    current_manufacturer = None

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            # Manufacturer is only set on the first row of each group
            mfr = _to_str(row.get("Manufacturer"))
            if mfr:
                current_manufacturer = mfr

            # Skip empty rows
            model = _to_str(row.get("Model"))
            device_name = _to_str(row.get("Device Name"))
            if not model and not device_name:
                stats.skipped += 1
                continue

            serial = _to_str(row.get("Serial Number"))
            # For cameras, use combination of model + device_name if no serial
            identifier = serial or f"{model}_{device_name}"
            if not identifier:
                stats.skipped += 1
                continue

            # Check if device exists by serial or by model+device_name
            if serial:
                existing = session.query(Camera).filter(Camera.serial == serial).first()
            else:
                existing = session.query(Camera).filter(
                    Camera.model == model,
                    Camera.device_name == device_name
                ).first()

            # Extract credentials
            username = _to_str(row.get("User"))
            password = _to_str(row.get("Password"))

            device_data = {
                "manufacturer": current_manufacturer,
                "model": model,
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "device_name": device_name,
                "ip_address": _to_str(row.get("IP Address")),
                "mac_address": _to_str(row.get("MAC Address")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
                "last_updated": datetime.utcnow(),
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                camera_id = existing.id
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                camera = Camera(**device_data)
                camera.data_completeness = compute_completeness(camera)
                if not ctx.dry_run:
                    session.add(camera)
                    session.flush()  # Get ID
                    camera_id = camera.id
                else:
                    camera_id = None
                stats.added += 1

            # Queue credentials
            if (username or password) and camera_id and not ctx.dry_run:
                ctx.credentials_queue.append({
                    "device_table": "cameras",
                    "device_id": camera_id,
                    "credential_type": "login",
                    "username": username,
                    "password": password,
                    "notes": f"Camera login for {device_name or model}",
                })

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_trade_show_boxes_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import trade show boxes with incremental update support."""
    stats = ctx.get_stats("trade_show_boxes")
    rows = _read_sheet(wb, "Trade Show Boxes")

    print(f"Processing {len(rows)} trade show box rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Device Serial"))
            org = _to_str(row.get("Associated Org"))
            if not serial and not org:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(TradeShowBox).filter(TradeShowBox.serial == serial).first()
            else:
                existing = None

            device_data = {
                "org": org,
                "serial": serial,
                "status": _to_str(row.get("Device Status")),
                "part_number": _to_str(row.get("Part Number")),
                "external_id": _to_str(row.get("External ID")),
                "mac_address": _to_str(row.get("MAC Address 1")),
                "location": _to_str(row.get("Location")),
                "last_updated": _to_datetime(row.get("Last Updated")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                device = TradeShowBox(**device_data)
                device.data_completeness = compute_completeness(device)
                if not ctx.dry_run:
                    session.add(device)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Device Serial")), str(e))
            continue

    return stats


def import_gpus_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import GPUs with incremental update support."""
    stats = ctx.get_stats("gpus")
    rows = _read_sheet(wb, "GPUs")

    print(f"Processing {len(rows)} GPU rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            gpu_serial = _to_str(row.get("GPU Serial"))
            if not gpu_serial:
                stats.skipped += 1
                continue

            existing = session.query(GPU).filter(GPU.gpu_serial == gpu_serial).first()

            device_data = {
                "gpu_serial": gpu_serial,
                "model": _to_str(row.get("GPU Model")),
                "status": _to_str(row.get("GPU Status")),
                "associated_device_serial": _to_str(row.get("Associated Device Serial")),
                "last_updated": _to_datetime(row.get("Last Updated")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                device = GPU(**device_data)
                device.data_completeness = compute_completeness(device)
                if not ctx.dry_run:
                    session.add(device)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("GPU Serial")), str(e))
            continue

    return stats


def import_part_numbers_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import part numbers with incremental update support."""
    stats = ctx.get_stats("part_numbers")
    rows = _read_sheet(wb, "Part Numbers")

    print(f"Processing {len(rows)} part number rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            part_number = _to_str(row.get("Part Number"))
            if not part_number:
                stats.skipped += 1
                continue

            existing = session.query(PartNumber).filter(PartNumber.part_number == part_number).first()

            device_data = {
                "part_number": part_number,
                "vendor": _to_str(row.get("Vendor")),
                "form_factor": _to_str(row.get("Form Factor")),
                "service_type": _to_str(row.get("Service Type")),
                "last_updated": _to_datetime(row.get("Last Updated")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                device = PartNumber(**device_data)
                device.data_completeness = compute_completeness(device)
                if not ctx.dry_run:
                    session.add(device)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Part Number")), str(e))
            continue

    return stats


def import_monitors_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import monitors with incremental update support."""
    stats = ctx.get_stats("monitors")
    rows = _read_sheet(wb, "Monitors")

    print(f"Processing {len(rows)} monitor rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            # Monitors might not always have serial numbers, use device name as fallback
            device = _to_str(row.get("Device"))
            if not serial and not device:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(Monitor).filter(Monitor.serial == serial).first()
            else:
                existing = None

            device_data = {
                "device": device,
                "model": _to_str(row.get("Model")),
                "model_code": _to_str(row.get("Model Code")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                monitor = Monitor(**device_data)
                monitor.data_completeness = compute_completeness(monitor)
                if not ctx.dry_run:
                    session.add(monitor)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_computers_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import computers with Intune merge and incremental update support."""
    stats = ctx.get_stats("computers")
    serial_to_obj: dict[str, Computer] = {}

    # Primary: Computers sheet
    rows = _read_sheet(wb, "Computers")
    print(f"Processing {len(rows)} computer rows from Computers sheet...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            if not serial:
                stats.skipped += 1
                continue

            existing = session.query(Computer).filter(Computer.serial == serial).first()

            device_data = {
                "device": _to_str(row.get("Device")),
                "device_name": _to_str(row.get("Device Name")),
                "model": _to_str(row.get("Model")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                serial_to_obj[serial] = existing
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                computer = Computer(**device_data)
                computer.data_completeness = compute_completeness(computer)
                if not ctx.dry_run:
                    session.add(computer)
                serial_to_obj[serial] = computer
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    # Merge: All Computers (Intune export)
    intune_rows = _read_sheet(wb, "All Computers")
    print(f"Merging {len(intune_rows)} Intune computer rows...")

    for row in intune_rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial number"))
            if not serial:
                stats.skipped += 1
                continue

            if serial in serial_to_obj:
                # Enrich existing record with Intune data
                obj = serial_to_obj[serial]
                obj.intune_device_id = _to_str(row.get("Device ID"))
                obj.intune_compliance = _to_str(row.get("Compliance"))
                obj.os = _to_str(row.get("OS"))
                obj.os_version = _to_str(row.get("OS version"))
                obj.primary_user_upn = _to_str(row.get("Primary user UPN"))
                obj.intune_last_checkin = _to_datetime(row.get("Last check-in"))
                if not obj.device_name:
                    obj.device_name = _to_str(row.get("Device name"))
                obj.data_completeness = compute_completeness(obj)
            else:
                # Intune-only device not in Computers sheet
                existing = session.query(Computer).filter(Computer.serial == serial).first()

                device_data = {
                    "device_name": _to_str(row.get("Device name")),
                    "serial": serial,
                    "intune_device_id": _to_str(row.get("Device ID")),
                    "intune_compliance": _to_str(row.get("Compliance")),
                    "os": _to_str(row.get("OS")),
                    "os_version": _to_str(row.get("OS version")),
                    "primary_user_upn": _to_str(row.get("Primary user UPN")),
                    "intune_last_checkin": _to_datetime(row.get("Last check-in")),
                    "discovered_by": "intune_import",
                }

                if existing:
                    for key, value in device_data.items():
                        setattr(existing, key, value)
                    existing.data_completeness = compute_completeness(existing)
                    serial_to_obj[serial] = existing
                    stats.updated += 1
                    if ctx.dry_run:
                        session.expunge(existing)
                else:
                    computer = Computer(**device_data)
                    computer.data_completeness = compute_completeness(computer)
                    if not ctx.dry_run:
                        session.add(computer)
                    serial_to_obj[serial] = computer
                    stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial number")), str(e))
            continue

    return stats


def import_phones_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import phones with incremental update support."""
    stats = ctx.get_stats("phones")
    rows = _read_sheet(wb, "Phones")

    print(f"Processing {len(rows)} phone rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            device = _to_str(row.get("Device"))
            if not serial and not device:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(Phone).filter(Phone.serial == serial).first()
            else:
                existing = None

            device_data = {
                "device": device,
                "model": _to_str(row.get("Model")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                phone = Phone(**device_data)
                phone.data_completeness = compute_completeness(phone)
                if not ctx.dry_run:
                    session.add(phone)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_mobile_devices_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import mobile devices with credential extraction and incremental update support."""
    stats = ctx.get_stats("mobile_devices")
    rows = _read_sheet(wb, "Mobile Testing")

    print(f"Processing {len(rows)} mobile device rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            device = _to_str(row.get("Device"))
            if not serial and not device:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(MobileDevice).filter(MobileDevice.serial == serial).first()
            else:
                existing = None

            # Extract credentials
            notes = _to_str(row.get("Notes"))
            pin = _extract_pin(notes)
            clean_notes = _strip_pin_from_notes(notes)

            device_data = {
                "device": device,
                "model_name": _to_str(row.get("Model Name")),
                "model_number": _to_str(row.get("Model Number")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "notes": clean_notes,
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                device_id = existing.id
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                mobile = MobileDevice(**device_data)
                mobile.data_completeness = compute_completeness(mobile)
                if not ctx.dry_run:
                    session.add(mobile)
                    session.flush()  # Get ID
                    device_id = mobile.id
                else:
                    device_id = None
                stats.added += 1

            # Queue credentials
            if pin and device_id and not ctx.dry_run:
                ctx.credentials_queue.append({
                    "device_table": "mobile_devices",
                    "device_id": device_id,
                    "credential_type": "pin",
                    "username": None,
                    "password": pin,
                    "notes": f"Device PIN for {device}",
                })

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_network_equipment_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import network equipment with incremental update support."""
    stats = ctx.get_stats("network_equipment")
    rows = _read_sheet(wb, "Network Equipment")

    print(f"Processing {len(rows)} network equipment rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            device = _to_str(row.get("Device"))
            if not serial and not device:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(NetworkEquipment).filter(NetworkEquipment.serial == serial).first()
            else:
                existing = None

            device_data = {
                "device": device,
                "model_name": _to_str(row.get("Model Name")),
                "model_number": _to_str(row.get("Model Number")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                equipment = NetworkEquipment(**device_data)
                equipment.data_completeness = compute_completeness(equipment)
                if not ctx.dry_run:
                    session.add(equipment)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_access_control_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import access control devices with incremental update support."""
    stats = ctx.get_stats("access_control")
    rows = _read_sheet(wb, "Access Control")

    print(f"Processing {len(rows)} access control rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            device_name = _to_str(row.get("Device Name"))
            if not serial and not device_name:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(AccessControl).filter(AccessControl.serial == serial).first()
            else:
                existing = None

            device_data = {
                "manufacturer": _to_str(row.get("Manufacturer")),
                "model": _to_str(row.get("Model")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "device_name": device_name,
                "ip_address": _to_str(row.get("IP Address")),
                "mac_address": _to_str(row.get("MAC Address")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                access_ctrl = AccessControl(**device_data)
                access_ctrl.data_completeness = compute_completeness(access_ctrl)
                if not ctx.dry_run:
                    session.add(access_ctrl)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_webcams_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import webcams with incremental update support."""
    stats = ctx.get_stats("webcams")
    rows = _read_sheet(wb, "Webcams")

    print(f"Processing {len(rows)} webcam rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            device = _to_str(row.get("Device"))
            if not serial and not device:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(Webcam).filter(Webcam.serial == serial).first()
            else:
                existing = None

            device_data = {
                "device": device,
                "model": _to_str(row.get("Model")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                webcam = Webcam(**device_data)
                webcam.data_completeness = compute_completeness(webcam)
                if not ctx.dry_run:
                    session.add(webcam)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_printers_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import printers with credential extraction and incremental update support."""
    stats = ctx.get_stats("printers")
    rows = _read_sheet(wb, "Printers")

    print(f"Processing {len(rows)} printer rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            device = _to_str(row.get("Device"))
            if not serial and not device:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(Printer).filter(Printer.serial == serial).first()
            else:
                existing = None

            # Extract credentials
            notes = _to_str(row.get("Notes"))
            username, pin = _extract_printer_creds(notes)
            clean_notes = _strip_creds_from_notes(notes)

            device_data = {
                "device": device,
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "notes": clean_notes,
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                device_id = existing.id
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                printer = Printer(**device_data)
                printer.data_completeness = compute_completeness(printer)
                if not ctx.dry_run:
                    session.add(printer)
                    session.flush()  # Get ID
                    device_id = printer.id
                else:
                    device_id = None
                stats.added += 1

            # Queue credentials
            if (username or pin) and device_id and not ctx.dry_run:
                ctx.credentials_queue.append({
                    "device_table": "printers",
                    "device_id": device_id,
                    "credential_type": "login" if username else "pin",
                    "username": username,
                    "password": pin,
                    "notes": f"Printer admin for {device}",
                })

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_office_equipment_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import office equipment with incremental update support."""
    stats = ctx.get_stats("office_equipment")
    rows = _read_sheet(wb, "Office Equipment")

    print(f"Processing {len(rows)} office equipment rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            device = _to_str(row.get("Device"))
            if not serial and not device:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(OfficeEquipment).filter(OfficeEquipment.serial == serial).first()
            else:
                existing = None

            device_data = {
                "device": device,
                "model_name": _to_str(row.get("Model Name")),
                "model_number": _to_str(row.get("Model Number")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                equipment = OfficeEquipment(**device_data)
                equipment.data_completeness = compute_completeness(equipment)
                if not ctx.dry_run:
                    session.add(equipment)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


def import_nas_devices_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    """Import NAS devices with incremental update support."""
    stats = ctx.get_stats("nas_devices")
    rows = _read_sheet(wb, "NAS Devices")

    print(f"Processing {len(rows)} NAS device rows...")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Serial Number"))
            device = _to_str(row.get("Device"))
            if not serial and not device:
                stats.skipped += 1
                continue

            # Check if device exists
            if serial:
                existing = session.query(NASDevice).filter(NASDevice.serial == serial).first()
            else:
                existing = None

            device_data = {
                "device": device,
                "model": _to_str(row.get("Model")),
                "serial": serial,
                "location": _to_str(row.get("Location")),
                "assigned_to": _to_str(row.get("Assigned To")),
                "purpose": _to_str(row.get("Purpose")),
                "ip_address": _to_str(row.get("IP Address")),
                "notes": _to_str(row.get("Notes")),
                "discovered_by": "manual",
            }

            if existing:
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                nas = NASDevice(**device_data)
                nas.data_completeness = compute_completeness(nas)
                if not ctx.dry_run:
                    session.add(nas)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, _to_str(row.get("Serial Number")), str(e))
            continue

    return stats


# ============================================================================
# OUI Auto-add Helper
# ============================================================================

def _auto_add_ouis_from_import(session) -> int:
    """Scan all inventory tables for MAC addresses and auto-add OUIs to allowlist.

    Returns:
        Number of new OUIs added
    """
    from app.oui_utils import auto_add_oui

    mac_to_table = {}

    # Collect MAC addresses from all tables
    tables_with_macs = {
        "edge_boxes": EdgeBox,
        "cameras": Camera,
        "trade_show_boxes": TradeShowBox,
        "access_control": AccessControl,
        "phones": Phone,
        "mobile_devices": MobileDevice,
        "network_equipment": NetworkEquipment,
    }

    for table_name, model in tables_with_macs.items():
        devices = session.query(model).filter(model.mac_address.isnot(None)).all()
        for device in devices:
            if device.mac_address:
                mac_to_table[device.mac_address] = table_name

    # Auto-add OUIs
    added_count = 0
    for mac, table_name in mac_to_table.items():
        if auto_add_oui(session, mac_address=mac, table_name=table_name):
            added_count += 1

    return added_count


# ============================================================================
# Main import orchestration
# ============================================================================

def run_import(dry_run: bool = False):
    """Run the import with optional dry-run/validation mode."""
    spreadsheet_path = Path(settings.SPREADSHEET_PATH)
    if not spreadsheet_path.exists():
        print(f"ERROR: Spreadsheet not found at {spreadsheet_path}")
        sys.exit(1)

    print(f"Loading spreadsheet: {spreadsheet_path}")
    wb = openpyxl.load_workbook(str(spreadsheet_path), data_only=True)
    print(f"Sheets found: {wb.sheetnames}")

    if dry_run:
        print("\n🔍 VALIDATION MODE (DRY RUN) - No database changes will be made")
    else:
        print("\nCreating database tables...")
        create_all_tables()

    session = SessionLocal()
    ctx = ImportContext(dry_run=dry_run)

    try:
        if not dry_run:
            existing_count = session.query(EdgeBox).count()
            if existing_count > 0:
                print(f"\nℹ️  Database has {existing_count} existing edge boxes")
                print("   Import will update existing devices and add new ones")

        print("\n" + "=" * 70)
        print("IMPORTING INVENTORY DATA")
        print("=" * 70)

        # Import all 15 tables
        import_edge_boxes_incremental(wb, session, ctx)
        import_trade_show_boxes_incremental(wb, session, ctx)
        import_gpus_incremental(wb, session, ctx)
        import_part_numbers_incremental(wb, session, ctx)
        import_monitors_incremental(wb, session, ctx)
        import_computers_incremental(wb, session, ctx)
        import_phones_incremental(wb, session, ctx)
        import_mobile_devices_incremental(wb, session, ctx)
        import_cameras_incremental(wb, session, ctx)
        import_network_equipment_incremental(wb, session, ctx)
        import_access_control_incremental(wb, session, ctx)
        import_webcams_incremental(wb, session, ctx)
        import_printers_incremental(wb, session, ctx)
        import_office_equipment_incremental(wb, session, ctx)
        import_nas_devices_incremental(wb, session, ctx)

        if not dry_run:
            # Flush to get device IDs
            print("\nFlushing inventory records...")
            session.flush()

            # Encrypt and insert credentials
            if ctx.credentials_queue:
                print(f"Encrypting and inserting {len(ctx.credentials_queue)} credentials...")
                for cred_data in ctx.credentials_queue:
                    # Handle both formats: new format with username/password or old format with value
                    if "value" in cred_data:
                        # Old format (simple PIN)
                        encrypted_value = encrypt(cred_data["value"])
                        credential = DeviceCredential(
                            device_table=cred_data["device_table"],
                            device_id=cred_data["device_id"],
                            credential_type=cred_data["credential_type"],
                            encrypted_value=encrypted_value,
                        )
                    else:
                        # New format (username/password)
                        credential = DeviceCredential(
                            device_table=cred_data["device_table"],
                            device_id=cred_data["device_id"],
                            credential_type=cred_data["credential_type"],
                            username=encrypt(cred_data.get("username")),
                            password=encrypt(cred_data.get("password")),
                            notes=encrypt(cred_data.get("notes")),
                        )
                    session.add(credential)

            # Auto-add OUIs from imported devices with MAC addresses
            print("\nAuto-adding OUIs from imported devices...")
            oui_count = _auto_add_ouis_from_import(session)
            if oui_count > 0:
                print(f"✅ Added {oui_count} new OUI(s) to allowlist")
            else:
                print("   All OUIs already in allowlist")

            # Commit everything
            print("\nCommitting changes...")
            session.commit()
            print("✅ Commit successful")

        # Print summary
        ctx.print_summary()

    except SQLAlchemyError as e:
        if not dry_run:
            session.rollback()
        print(f"\n❌ DATABASE ERROR: {e}")
        raise
    except Exception as e:
        if not dry_run:
            session.rollback()
        print(f"\n❌ IMPORT ERROR: {e}")
        raise
    finally:
        session.close()
        wb.close()


def main():
    parser = argparse.ArgumentParser(
        description="Import hardware inventory from Excel with validation and incremental updates"
    )
    parser.add_argument(
        "--dry-run",
        "--validate",
        action="store_true",
        help="Validation mode: preview changes without modifying database",
    )
    args = parser.parse_args()

    run_import(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
