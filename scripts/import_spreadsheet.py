"""Import hardware inventory data from the Excel spreadsheet into PostgreSQL.

Reads: data/Inventory_Tracker_Export.xlsx
Creates: 14 inventory tables + encrypted credentials vault entries

Usage:
    python scripts/import_spreadsheet.py
"""

import re
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
from sqlalchemy import inspect

# Ensure repo root is on sys.path (for absolute imports)
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.config import settings
from app.credentials import encrypt
from app.database import SessionLocal, create_all_tables
from app.models import (
    AccessControl, Camera, Computer, DeviceCredential, EdgeBox, GPU,
    MobileDevice, Monitor, NetworkEquipment, OfficeEquipment, PartNumber,
    Phone, Printer, TradeShowBox, Webcam, compute_completeness,
)


def _read_sheet(wb, sheet_name: str) -> list[dict]:
    """Read a worksheet into a list of dicts keyed by header names."""
    if sheet_name not in wb.sheetnames:
        print(f"  [SKIP] Sheet '{sheet_name}' not found")
        return []
    ws = wb[sheet_name]
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        if all(v is None for v in row):
            continue
        rows.append(dict(zip(headers, row)))
    return rows


def _to_str(val) -> str | None:
    """Convert a cell value to a trimmed string or None."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _to_datetime(val) -> datetime | None:
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
    """Extract username and PIN from printer notes like 'Username: admin, PIN: 75114838'."""
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


# ---------------------------------------------------------------------------
# Sheet importers
# ---------------------------------------------------------------------------

def import_edge_boxes(wb, session) -> int:
    """Import Edge Boxes + Customer Edge Boxes + Pilots into one table."""
    count = 0
    seen_macs = set()

    # Sheet 1: All Edge Boxes
    for row in _read_sheet(wb, "All Edge Boxes"):
        mac = _to_str(row.get("MAC Address 1"))
        if mac and mac in seen_macs:
            continue
        if mac:
            seen_macs.add(mac)

        # Determine deployment type from status
        status_val = _to_str(row.get("Device Status"))
        deployment_type = "internal"
        if status_val:
            sl = status_val.lower()
            if "demo" in sl:
                deployment_type = "demo"
            elif "customer" in sl:
                deployment_type = "customer"
            elif "production" in sl:
                deployment_type = "customer"

        # Determine from column D (unlabeled in spreadsheet, used as sub-type)
        col_d = _to_str(row.get(None))
        if col_d and "pilot" in col_d.lower():
            deployment_type = "pilot"
        elif col_d and "demo" in col_d.lower():
            deployment_type = "demo"
        elif col_d and "testing" in col_d.lower():
            deployment_type = "internal"

        obj = EdgeBox(
            org=_to_str(row.get("Associated Org")),
            customer=_to_str(row.get("Customer")),
            site_name=_to_str(row.get("Site Name")),
            serial=_to_str(row.get("Device Serial")),
            status=status_val,
            part_number=_to_str(row.get("Part Number")),
            warranty_id=_to_str(row.get("Warranty ID")),
            mac_address=mac,
            uuid=_to_str(row.get("UUID")),
            last_updated=_to_datetime(row.get("Last Updated")),
            notes=_to_str(row.get("Notes")),
            deployment_type=deployment_type,
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1

    # Sheet 2: Customer Edge Boxes (merge into edge_boxes, skip duplicates by MAC)
    for row in _read_sheet(wb, "Customer Edge Boxes"):
        mac = _to_str(row.get("MAC Address 1"))
        if mac and mac in seen_macs:
            continue
        if mac:
            seen_macs.add(mac)
        obj = EdgeBox(
            org=_to_str(row.get("Partner")),
            customer=_to_str(row.get("Customer")),
            site_name=_to_str(row.get("Site Name")),
            serial=_to_str(row.get("Device Serial")),
            status=_to_str(row.get("Device Status")),
            part_number=_to_str(row.get("Part Number")),
            warranty_id=_to_str(row.get("Warranty ID")),
            mac_address=mac,
            uuid=_to_str(row.get("UUID")),
            last_updated=_to_datetime(row.get("Last Updated")),
            deployment_type="customer",
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1

    # Sheet 3: Pilots (merge into edge_boxes, skip duplicates by MAC/UUID)
    seen_uuids = {obj.uuid for obj in session.new if isinstance(obj, EdgeBox) and obj.uuid}
    for row in _read_sheet(wb, "Pilots"):
        mac = _to_str(row.get("MAC Address 1"))
        uuid_val = _to_str(row.get("UUID"))
        if mac and mac in seen_macs:
            continue
        if uuid_val and uuid_val in seen_uuids:
            continue
        if mac:
            seen_macs.add(mac)
        if uuid_val:
            seen_uuids.add(uuid_val)
        obj = EdgeBox(
            org=_to_str(row.get("Associated Org")),
            serial=_to_str(row.get("Device Serial")),
            status=_to_str(row.get("Device Status")),
            part_number=_to_str(row.get("Part Number")),
            warranty_id=_to_str(row.get("Warranty ID")),
            mac_address=mac,
            uuid=uuid_val,
            last_updated=_to_datetime(row.get("Last Updated")),
            notes=_to_str(row.get("Notes")),
            pilot_type=_to_str(row.get("Pilot Type")),
            deployment_type="pilot",
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1

    return count


def import_trade_show_boxes(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Trade Show Boxes"):
        if not _to_str(row.get("Device Serial")) and not _to_str(row.get("Associated Org")):
            continue
        obj = TradeShowBox(
            org=_to_str(row.get("Associated Org")),
            serial=_to_str(row.get("Device Serial")),
            status=_to_str(row.get("Device Status")),
            part_number=_to_str(row.get("Part Number")),
            external_id=_to_str(row.get("External ID")),
            mac_address=_to_str(row.get("MAC Address 1")),
            location=_to_str(row.get("Location")),
            last_updated=_to_datetime(row.get("Last Updated")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def import_gpus(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "GPUs"):
        if not _to_str(row.get("GPU Serial")):
            continue
        obj = GPU(
            gpu_serial=_to_str(row.get("GPU Serial")),
            model=_to_str(row.get("GPU Model")),
            status=_to_str(row.get("GPU Status")),
            associated_device_serial=_to_str(row.get("Associated Device Serial")),
            last_updated=_to_datetime(row.get("Last Updated")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def import_part_numbers(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Part Numbers"):
        if not _to_str(row.get("Part Number")):
            continue
        obj = PartNumber(
            part_number=_to_str(row.get("Part Number")),
            vendor=_to_str(row.get("Vendor")),
            form_factor=_to_str(row.get("Form Factor")),
            service_type=_to_str(row.get("Service Type")),
            last_updated=_to_datetime(row.get("Last Updated")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def import_monitors(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Monitors"):
        obj = Monitor(
            device=_to_str(row.get("Device")),
            model=_to_str(row.get("Model")),
            model_code=_to_str(row.get("Model Code")),
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            notes=_to_str(row.get("Notes")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def import_computers(wb, session) -> int:
    """Import Computers sheet and merge Intune data from All Computers sheet."""
    count = 0
    serial_to_obj: dict[str, Computer] = {}

    # Primary: Computers sheet
    for row in _read_sheet(wb, "Computers"):
        serial = _to_str(row.get("Serial Number"))
        obj = Computer(
            device=_to_str(row.get("Device")),
            device_name=_to_str(row.get("Device Name")),
            model=_to_str(row.get("Model")),
            serial=serial,
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            notes=_to_str(row.get("Notes")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        if serial:
            serial_to_obj[serial] = obj
        count += 1

    # Merge: All Computers (Intune export) — enrich existing records
    for row in _read_sheet(wb, "All Computers"):
        serial = _to_str(row.get("Serial number"))
        if serial and serial in serial_to_obj:
            obj = serial_to_obj[serial]
            obj.intune_device_id = _to_str(row.get("Device ID"))
            obj.intune_compliance = _to_str(row.get("Compliance"))
            obj.os = _to_str(row.get("OS"))
            obj.os_version = _to_str(row.get("OS version"))
            obj.primary_user_upn = _to_str(row.get("Primary user UPN"))
            obj.intune_last_checkin = _to_datetime(row.get("Last check-in"))
            if not obj.device_name:
                obj.device_name = _to_str(row.get("Device name"))
        elif serial:
            # Intune-only device not in Computers sheet
            obj = Computer(
                device_name=_to_str(row.get("Device name")),
                serial=serial,
                intune_device_id=_to_str(row.get("Device ID")),
                intune_compliance=_to_str(row.get("Compliance")),
                os=_to_str(row.get("OS")),
                os_version=_to_str(row.get("OS version")),
                primary_user_upn=_to_str(row.get("Primary user UPN")),
                intune_last_checkin=_to_datetime(row.get("Last check-in")),
                discovered_by="intune_import",
            )
            obj.data_completeness = compute_completeness(obj)
            session.add(obj)
            serial_to_obj[serial] = obj
            count += 1

    return count


def import_phones(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Phones"):
        obj = Phone(
            device=_to_str(row.get("Device")),
            model=_to_str(row.get("Model")),
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def import_mobile_devices(wb, session, credentials_queue: list) -> int:
    """Import mobile devices. Extracts PINs into credentials_queue."""
    count = 0
    for row in _read_sheet(wb, "Mobile Testing"):
        notes = _to_str(row.get("Notes"))
        pin = _extract_pin(notes)
        clean_notes = _strip_pin_from_notes(notes)

        obj = MobileDevice(
            device=_to_str(row.get("Device")),
            model_name=_to_str(row.get("Model Name")),
            model_number=_to_str(row.get("Model Number")),
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            notes=clean_notes,
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)

        if pin:
            credentials_queue.append({
                "table": "mobile_devices",
                "obj": obj,
                "type": "pin",
                "username": None,
                "password": pin,
                "notes": f"Device PIN for {_to_str(row.get('Device'))}",
            })

        count += 1
    return count


def import_cameras(wb, session, credentials_queue: list) -> int:
    """Import cameras. Extracts login credentials into credentials_queue."""
    count = 0
    current_manufacturer = None

    for row in _read_sheet(wb, "Cameras"):
        # Manufacturer is only set on the first row of each group
        mfr = _to_str(row.get("Manufacturer"))
        if mfr:
            current_manufacturer = mfr

        # Skip empty rows
        model = _to_str(row.get("Model"))
        device_name = _to_str(row.get("Device Name"))
        if not model and not device_name:
            continue

        username = _to_str(row.get("User"))
        password = _to_str(row.get("Password"))

        obj = Camera(
            manufacturer=current_manufacturer,
            model=model,
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            device_name=device_name,
            ip_address=_to_str(row.get("IP Address")),
            mac_address=_to_str(row.get("MAC Address")),
            notes=_to_str(row.get("Notes")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)

        if username or password:
            credentials_queue.append({
                "table": "cameras",
                "obj": obj,
                "type": "login",
                "username": username,
                "password": password,
                "notes": f"Camera login for {device_name or model}",
            })

        count += 1
    return count


def import_network_equipment(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Network Equipment"):
        obj = NetworkEquipment(
            device=_to_str(row.get("Device")),
            model_name=_to_str(row.get("Model Name")),
            model_number=_to_str(row.get("Model Number")),
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            notes=_to_str(row.get("Notes")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def import_access_control(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Access Control"):
        obj = AccessControl(
            manufacturer=_to_str(row.get("Manufacturer")),
            model=_to_str(row.get("Model")),
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            device_name=_to_str(row.get("Device Name")),
            ip_address=_to_str(row.get("IP Address")),
            mac_address=_to_str(row.get("MAC Address")),
            notes=_to_str(row.get("Notes")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def import_webcams(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Webcams"):
        obj = Webcam(
            device=_to_str(row.get("Device")),
            model=_to_str(row.get("Model")),
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            notes=_to_str(row.get("Notes")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def import_printers(wb, session, credentials_queue: list) -> int:
    """Import printers. Extracts admin credentials into credentials_queue."""
    count = 0
    for row in _read_sheet(wb, "Printers"):
        notes = _to_str(row.get("Notes"))
        username, pin = _extract_printer_creds(notes)
        clean_notes = _strip_creds_from_notes(notes)

        obj = Printer(
            device=_to_str(row.get("Device")),
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            notes=clean_notes,
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)

        if username or pin:
            credentials_queue.append({
                "table": "printers",
                "obj": obj,
                "type": "login" if username else "pin",
                "username": username,
                "password": pin,
                "notes": f"Printer admin for {_to_str(row.get('Device'))}",
            })

        count += 1
    return count


def import_office_equipment(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Office Equipment"):
        obj = OfficeEquipment(
            device=_to_str(row.get("Device")),
            model_name=_to_str(row.get("Model Name")),
            model_number=_to_str(row.get("Model Number")),
            serial=_to_str(row.get("Serial Number")),
            location=_to_str(row.get("Location")),
            assigned_to=_to_str(row.get("Assigned To")),
            purpose=_to_str(row.get("Purpose")),
            notes=_to_str(row.get("Notes")),
            discovered_by="manual",
        )
        obj.data_completeness = compute_completeness(obj)
        session.add(obj)
        count += 1
    return count


def flush_credentials(session, credentials_queue: list) -> int:
    """Encrypt and insert all queued credentials after device IDs are assigned."""
    count = 0
    for entry in credentials_queue:
        obj = entry["obj"]
        # After session.flush(), obj.id is populated
        cred = DeviceCredential(
            device_table=entry["table"],
            device_id=obj.id,
            credential_type=entry["type"],
            username=encrypt(entry["username"]),
            password=encrypt(entry["password"]),
            notes=encrypt(entry["notes"]),
        )
        session.add(cred)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    spreadsheet_path = Path(settings.SPREADSHEET_PATH)
    if not spreadsheet_path.exists():
        print(f"ERROR: Spreadsheet not found at {spreadsheet_path}")
        sys.exit(1)

    print(f"Loading spreadsheet: {spreadsheet_path}")
    wb = openpyxl.load_workbook(str(spreadsheet_path), data_only=True)
    print(f"Sheets found: {wb.sheetnames}")

    print("\nCreating database tables...")
    create_all_tables()

    session = SessionLocal()
    credentials_queue: list[dict] = []

    try:
        # Check if data already exists
        existing = session.query(EdgeBox).count()
        if existing > 0:
            print(f"\nWARNING: Database already has {existing} edge boxes.")
            print("This script is idempotent only on empty tables.")
            print("To re-import, drop and recreate tables first.")
            response = input("Continue anyway? (y/N): ").strip().lower()
            if response != "y":
                print("Aborted.")
                return

        print("\n--- Importing inventory data ---")

        results = {}
        results["edge_boxes"] = import_edge_boxes(wb, session)
        results["trade_show_boxes"] = import_trade_show_boxes(wb, session)
        results["gpus"] = import_gpus(wb, session)
        results["part_numbers"] = import_part_numbers(wb, session)
        results["monitors"] = import_monitors(wb, session)
        results["computers"] = import_computers(wb, session)
        results["phones"] = import_phones(wb, session)
        results["mobile_devices"] = import_mobile_devices(wb, session, credentials_queue)
        results["cameras"] = import_cameras(wb, session, credentials_queue)
        results["network_equipment"] = import_network_equipment(wb, session)
        results["access_control"] = import_access_control(wb, session)
        results["webcams"] = import_webcams(wb, session)
        results["printers"] = import_printers(wb, session, credentials_queue)
        results["office_equipment"] = import_office_equipment(wb, session)

        # Flush to get device IDs assigned before inserting credentials
        print("\nFlushing inventory records...")
        session.flush()

        # Encrypt and insert credentials
        print("Encrypting and inserting credentials...")
        cred_count = flush_credentials(session, credentials_queue)

        # Commit everything
        session.commit()

        # Print summary
        print("\n" + "=" * 60)
        print("IMPORT COMPLETE")
        print("=" * 60)
        total = 0
        for table, count in results.items():
            print(f"  {table:.<30} {count:>4} rows")
            total += count
        print(f"  {'':.<30} {'':->4}")
        print(f"  {'TOTAL INVENTORY':.<30} {total:>4} rows")
        print(f"  {'credentials (encrypted)':.<30} {cred_count:>4} entries")
        print("=" * 60)

    except Exception as e:
        session.rollback()
        print(f"\nERROR: Import failed: {e}")
        raise
    finally:
        session.close()
        wb.close()


if __name__ == "__main__":
    main()
