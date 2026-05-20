#!/usr/bin/env python3
"""
Import all inventory categories from the master Excel spreadsheet.

Usage:
    python scripts/import_all_categories.py <path_to_xlsx>

WARNING: This script DELETES ALL existing rows in each target table
         before importing. IDs are reset to start from 1.
         Edge boxes are NOT wiped — variant sheets dedup by serial.
"""

import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import (
    GPU, Camera, Monitor, Computer, Phone, MobileDevice, Webcam,
    Printer, OfficeEquipment, NetworkEquipment, AccessControl,
    NUC, UPS, RamModule, CPU, PSU, Motherboard, PCCooling,
    PCAccessory, HardDrive, DeviceComponent, EdgeBox,
    compute_completeness,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def parse_date(value):
    """Parse date from various formats, return datetime or None."""
    if not value or str(value).strip() in ('', 'None'):
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def parse_float(value):
    """Extract numeric float from string like '12 TB', '2 TB'."""
    if not value or str(value).strip() in ('', 'None'):
        return None
    match = re.search(r'[\d.]+', str(value))
    return float(match.group()) if match else None


def parse_int(value):
    """Extract integer from string like '16GB', '3200MHz'."""
    if not value or str(value).strip() in ('', 'None'):
        return None
    match = re.search(r'\d+', str(value))
    return int(match.group()) if match else None


def cell_val(row, header):
    """Safely get cell value, return None if missing or empty."""
    val = row.get(header)
    if val is None:
        return None
    s = str(val).strip()
    return None if s in ('', 'None', 'FALSE', 'True') else s


def bool_val(row, header):
    """Get boolean cell value."""
    val = row.get(header)
    if val is None:
        return False
    return str(val).strip().upper() == 'TRUE'


def wipe_table(session, tablename, id_seq):
    """Wipe table and reset ID sequence."""
    session.execute(text(f"DELETE FROM {tablename}"))
    session.execute(text(f"SELECT setval('{id_seq}', 1, false)"))
    session.commit()
    print(f"  Wiped {tablename}, ID sequence reset.")


def read_sheet(wb, sheet_name):
    """Read sheet into list of dicts keyed by header row."""
    if sheet_name not in wb.sheetnames:
        print(f"  WARNING: Sheet '{sheet_name}' not found, skipping.")
        return []
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h else '' for h in rows[0]]
    result = []
    for row in rows[1:]:
        result.append(dict(zip(headers, row)))
    return result


# ---------------------------------------------------------------------------
# Import functions — one per sheet/model
# ---------------------------------------------------------------------------

def import_gpus(session, wb):
    print("\nProcessing sheet: GPUs...")
    wipe_table(session, 'gpus', 'gpus_id_seq')
    rows = read_sheet(wb, 'GPUs')
    imported, failed = 0, []
    gpu_map = {}
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            model_val = cell_val(row, 'Model Name') or cell_val(row, 'GPU Model*')
            obj = GPU(
                gpu_serial=cell_val(row, 'GPU Serial*'),
                model=model_val,
                status=cell_val(row, 'GPU Status*'),
                associated_device_serial=cell_val(row, 'Associated Device Serial'),
                last_updated=parse_date(row.get('Last Updated')),
                vendor=cell_val(row, 'Manufacturer*'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            session.refresh(obj)
            gpu_map[obj.gpu_serial] = obj.id
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  GPUs: {imported} imported, {len(failed)} failed")
    return imported, failed, gpu_map


def import_cameras(session, wb):
    print("\nProcessing sheet: Cameras...")
    wipe_table(session, 'cameras', 'cameras_id_seq')
    rows = read_sheet(wb, 'Cameras')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = Camera(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                serial=cell_val(row, 'Serial Number*'),
                location=cell_val(row, 'Location*'),
                purpose=cell_val(row, 'Purpose'),
                device_name=cell_val(row, 'Device Name'),
                ip_address=cell_val(row, 'IP Address'),
                mac_address=cell_val(row, 'MAC Address*'),
                notes=cell_val(row, 'Notes'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Cameras: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_hard_drives(session, wb):
    print("\nProcessing sheet: Storage Drives...")
    wipe_table(session, 'hard_drives', 'hard_drives_id_seq')
    rows = read_sheet(wb, 'Storage Drives')
    imported, failed = 0, []
    hd_map = {}
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            cap_str = cell_val(row, 'Capacity*')
            cap_tb = parse_float(cap_str) if cap_str and 'TB' in str(cap_str).upper() else None
            cap_gb = parse_int(cap_str) if cap_str and 'GB' in str(cap_str).upper() else None
            mac = cell_val(row, 'MAC Address')
            speed = cell_val(row, 'Speed')
            notes_parts = []
            if mac:
                notes_parts.append(f"MAC: {mac}")
            if speed:
                notes_parts.append(f"Speed: {speed}")
            obj = HardDrive(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                drive_type=cell_val(row, 'Type*'),
                serial=cell_val(row, 'Serial*'),
                capacity_tb=cap_tb,
                capacity_gb=cap_gb,
                status=cell_val(row, 'Status*'),
                location=cell_val(row, 'Location*'),
                associated_device_serial=cell_val(row, 'Associated Device Serial'),
                last_updated=parse_date(row.get('Last Updated')),
                notes=', '.join(notes_parts) if notes_parts else None,
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            session.refresh(obj)
            if obj.serial:
                hd_map[obj.serial] = obj.id
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Hard Drives: {imported} imported, {len(failed)} failed")
    return imported, failed, hd_map


def import_ram(session, wb):
    print("\nProcessing sheet: RAM...")
    wipe_table(session, 'ram_modules', 'ram_modules_id_seq')
    rows = read_sheet(wb, 'RAM')
    imported, failed = 0, []
    ram_map = {}
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = RamModule(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model'),
                ram_type=cell_val(row, 'Type*'),
                serial=cell_val(row, 'Serial*'),
                capacity_gb=parse_int(row.get('Capacity*')),
                speed_mhz=parse_int(row.get('Speed')),
                status=cell_val(row, 'Status*'),
                location=cell_val(row, 'Location*'),
                associated_device_serial=cell_val(row, 'Associated Device Serial'),
                last_updated=parse_date(row.get('Last Updated')),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            session.refresh(obj)
            if obj.serial:
                ram_map[obj.serial] = obj.id
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  RAM: {imported} imported, {len(failed)} failed")
    return imported, failed, ram_map


def import_motherboards(session, wb):
    print("\nProcessing sheet: Motherboards...")
    wipe_table(session, 'motherboards', 'motherboards_id_seq')
    rows = read_sheet(wb, 'Motherboards')
    imported, failed = 0, []
    mb_map = {}
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = Motherboard(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                socket=cell_val(row, 'Socket*'),
                serial=cell_val(row, 'Serial*'),
                status=cell_val(row, 'Status*'),
                associated_device_serial=cell_val(row, 'Associated Device Serial'),
                last_updated=parse_date(row.get('Last Updated')),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            session.refresh(obj)
            if obj.serial:
                mb_map[obj.serial] = obj.id
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Motherboards: {imported} imported, {len(failed)} failed")
    return imported, failed, mb_map


def import_cpus(session, wb):
    print("\nProcessing sheet: CPUs...")
    wipe_table(session, 'cpus', 'cpus_id_seq')
    rows = read_sheet(wb, 'CPUs')
    imported, failed = 0, []
    cpu_map = {}
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = CPU(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                socket=cell_val(row, 'Socket*'),
                serial=cell_val(row, 'Serial*'),
                status=cell_val(row, 'Status*'),
                location=cell_val(row, 'Location*'),
                associated_device_serial=cell_val(row, 'Associated Device Serial'),
                last_updated=parse_date(row.get('Last Updated')),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            session.refresh(obj)
            if obj.serial:
                cpu_map[obj.serial] = obj.id
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  CPUs: {imported} imported, {len(failed)} failed")
    return imported, failed, cpu_map


def import_psus(session, wb):
    print("\nProcessing sheet: PSUs...")
    wipe_table(session, 'psus', 'psus_id_seq')
    rows = read_sheet(wb, 'PSUs')
    imported, failed = 0, []
    psu_map = {}
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = PSU(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                serial=cell_val(row, 'Serial*'),
                wattage_rating=cell_val(row, 'Wattage Rating*'),
                efficiency=cell_val(row, 'Energy Effiency'),
                status=cell_val(row, 'Status*'),
                location=cell_val(row, 'Location*'),
                associated_device_serial=cell_val(row, 'Associated Device Serial'),
                last_updated=parse_date(row.get('Last Updated')),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            session.refresh(obj)
            if obj.serial:
                psu_map[obj.serial] = obj.id
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  PSUs: {imported} imported, {len(failed)} failed")
    return imported, failed, psu_map


def import_ups(session, wb):
    print("\nProcessing sheet: UPS...")
    wipe_table(session, 'ups', 'ups_id_seq')
    rows = read_sheet(wb, 'UPS')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = UPS(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                serial=cell_val(row, 'Serial*'),
                va_rating=cell_val(row, 'VA Rating*'),
                wattage=cell_val(row, 'Wattage Rating*'),
                location=cell_val(row, 'Location*'),
                notes=cell_val(row, 'Notes'),
                last_updated=parse_date(row.get('Last Updated')),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  UPS: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_pc_cooling(session, wb):
    print("\nProcessing sheet: PC Cooling...")
    wipe_table(session, 'pc_cooling', 'pc_cooling_id_seq')
    rows = read_sheet(wb, 'PC Cooling')
    imported, failed = 0, []
    cool_map = {}
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = PCCooling(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                cooling_type=cell_val(row, 'Type*'),
                serial=cell_val(row, 'Serial*'),
                speed_rpm=cell_val(row, 'Speed'),
                status=cell_val(row, 'Status*'),
                associated_device_serial=cell_val(row, 'Associated Device Serial'),
                location=cell_val(row, 'Location*'),
                last_updated=parse_date(row.get('Last Updated')),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            session.refresh(obj)
            if obj.serial:
                cool_map[obj.serial] = obj.id
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  PC Cooling: {imported} imported, {len(failed)} failed")
    return imported, failed, cool_map


def import_pc_accessories(session, wb):
    print("\nProcessing sheet: PC Accessories...")
    wipe_table(session, 'pc_accessories', 'pc_accessories_id_seq')
    rows = read_sheet(wb, 'PC Accessories')
    imported, failed = 0, []
    acc_map = {}
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = PCAccessory(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                accessory_type=cell_val(row, 'Type*'),
                serial=cell_val(row, 'Serial*'),
                status=cell_val(row, 'Status*'),
                associated_device_serial=cell_val(row, 'Associated Device Serial'),
                location=cell_val(row, 'Location*'),
                notes=cell_val(row, 'Notes'),
                last_updated=parse_date(row.get('Last Updated')),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            session.refresh(obj)
            if obj.serial:
                acc_map[obj.serial] = obj.id
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  PC Accessories: {imported} imported, {len(failed)} failed")
    return imported, failed, acc_map


def import_monitors(session, wb):
    print("\nProcessing sheet: Monitors...")
    wipe_table(session, 'monitors', 'monitors_id_seq')
    rows = read_sheet(wb, 'Monitors')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = Monitor(
                device=cell_val(row, 'Device*'),
                model=cell_val(row, 'Model'),
                model_code=cell_val(row, 'Model Code'),
                serial=cell_val(row, 'Serial Number*'),
                location=cell_val(row, 'Location*'),
                assigned_to=cell_val(row, 'Assigned To*'),
                purpose=cell_val(row, 'Purpose*'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Monitors: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_computers(session, wb):
    """Import Computers sheet, then enrich with All Computers
    (Intune data) by matching on serial number."""
    print("\nProcessing sheet: Computers...")
    wipe_table(session, 'computers', 'computers_id_seq')
    rows = read_sheet(wb, 'Computers')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = Computer(
                device=cell_val(row, 'Device'),
                device_name=cell_val(row, 'Device Name*'),
                model=cell_val(row, 'Model'),
                serial=cell_val(row, 'Serial Number*'),
                location=cell_val(row, 'Location'),
                assigned_to=cell_val(row, 'Assigned To*'),
                purpose=cell_val(row, 'Purpose*'),
                notes=cell_val(row, 'Notes'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Computers: {imported} imported, {len(failed)} failed")

    # Enrich with Intune data from All Computers sheet
    print("  Enriching with Intune data from 'All Computers' sheet...")
    intune_rows = read_sheet(wb, 'All Computers')
    enriched, intune_new, intune_failed = 0, 0, []
    for i, row in enumerate(intune_rows, 2):
        try:
            serial = cell_val(row, 'Serial number')
            device_name = cell_val(row, 'Device name')
            if not serial and not device_name:
                continue
            # Try to match existing computer by serial
            existing = None
            if serial:
                existing = session.query(Computer).filter(
                    Computer.serial.ilike(serial)
                ).first()
            if existing:
                # Enrich existing record with Intune data
                sp = session.begin_nested()
                try:
                    existing.intune_device_id = cell_val(row, 'Device ID')
                    existing.intune_compliance = cell_val(row, 'Compliance')
                    existing.os = cell_val(row, 'OS')
                    existing.os_version = cell_val(row, 'OS version')
                    existing.primary_user_upn = cell_val(row, 'Primary user UPN')
                    existing.intune_last_checkin = parse_date(
                        row.get('Last check-in'))
                    if not existing.device_name and device_name:
                        existing.device_name = device_name
                    existing.data_completeness = compute_completeness(existing) / 100.0
                    sp.commit()
                    enriched += 1
                except Exception as e:
                    sp.rollback()
                    intune_failed.append((i, str(e)))
            else:
                # No match — create new Computer record from Intune data
                sp = session.begin_nested()
                try:
                    obj = Computer(
                        device_name=device_name,
                        serial=serial,
                        intune_device_id=cell_val(row, 'Device ID'),
                        intune_compliance=cell_val(row, 'Compliance'),
                        os=cell_val(row, 'OS'),
                        os_version=cell_val(row, 'OS version'),
                        primary_user_upn=cell_val(row, 'Primary user UPN'),
                        intune_last_checkin=parse_date(
                            row.get('Last check-in')),
                        discovered_by='intune_import',
                    )
                    session.add(obj)
                    session.flush()
                    obj.data_completeness = compute_completeness(obj) / 100.0
                    sp.commit()
                    intune_new += 1
                except Exception as e:
                    sp.rollback()
                    intune_failed.append((i, str(e)))
        except Exception as e:
            intune_failed.append((i, str(e)))
    print(f"  Intune enrichment: {enriched} matched, "
          f"{intune_new} new from Intune, {len(intune_failed)} failed")
    return imported, failed


def import_phones(session, wb):
    print("\nProcessing sheet: Phones...")
    wipe_table(session, 'phones', 'phones_id_seq')
    rows = read_sheet(wb, 'Phones')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = Phone(
                device=cell_val(row, 'Device*'),
                model=cell_val(row, 'Model*'),
                serial=cell_val(row, 'Serial Number*'),
                location=cell_val(row, 'Location*'),
                assigned_to=cell_val(row, 'Assigned To'),
                purpose=cell_val(row, 'Purpose'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Phones: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_mobile_devices(session, wb):
    print("\nProcessing sheet: Mobile Testing...")
    wipe_table(session, 'mobile_devices', 'mobile_devices_id_seq')
    rows = read_sheet(wb, 'Mobile Testing')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = MobileDevice(
                device=cell_val(row, 'Device*'),
                model_name=cell_val(row, 'Model Name*'),
                model_number=cell_val(row, 'Model Number'),
                serial=cell_val(row, 'Serial Number*'),
                location=cell_val(row, 'Location*'),
                assigned_to=cell_val(row, 'Assigned To'),
                purpose=cell_val(row, 'Purpose'),
                notes=cell_val(row, 'Notes'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Mobile Devices: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_network_equipment(session, wb):
    print("\nProcessing sheet: Network Equipment...")
    wipe_table(session, 'network_equipment', 'network_equipment_id_seq')
    rows = read_sheet(wb, 'Network Equipment')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            mac = cell_val(row, 'MAC Address')
            notes = cell_val(row, 'Notes')
            notes_parts = []
            if mac:
                notes_parts.append(f"MAC: {mac}")
            if notes:
                notes_parts.append(notes)
            obj = NetworkEquipment(
                vendor=cell_val(row, 'Manufacturer*'),
                device=cell_val(row, 'Device*'),
                model_name=cell_val(row, 'Model'),
                serial=cell_val(row, 'Serial Number'),
                location=cell_val(row, 'Location*'),
                assigned_to=cell_val(row, 'Assigned To'),
                purpose=cell_val(row, 'Purpose'),
                notes=', '.join(notes_parts) if notes_parts else None,
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Network Equipment: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_access_control(session, wb):
    print("\nProcessing sheet: Access Control...")
    wipe_table(session, 'access_control', 'access_control_id_seq')
    rows = read_sheet(wb, 'Access Control')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = AccessControl(
                manufacturer=cell_val(row, 'Manufacturer*'),
                model=cell_val(row, 'Model*'),
                serial=cell_val(row, 'Serial Number*'),
                location=cell_val(row, 'Location*'),
                assigned_to=cell_val(row, 'Assigned To'),
                purpose=cell_val(row, 'Purpose'),
                ip_address=cell_val(row, 'IP Address')
                    if 'IP Address' in row else None,
                mac_address=cell_val(row, 'MAC Address*')
                    if 'MAC Address*' in row else None,
                notes=cell_val(row, 'Notes'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Access Control: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_webcams(session, wb):
    print("\nProcessing sheet: Webcams...")
    wipe_table(session, 'webcams', 'webcams_id_seq')
    rows = read_sheet(wb, 'Webcams')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = Webcam(
                device=cell_val(row, 'Device*'),
                model=cell_val(row, 'Model*'),
                serial=cell_val(row, 'Serial Number'),
                location=cell_val(row, 'Location*'),
                assigned_to=cell_val(row, 'Assigned To*'),
                notes=cell_val(row, 'Notes'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Webcams: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_printers(session, wb):
    print("\nProcessing sheet: Printers...")
    wipe_table(session, 'printers', 'printers_id_seq')
    rows = read_sheet(wb, 'Printers')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = Printer(
                device=cell_val(row, 'Device*'),
                serial=cell_val(row, 'Serial Number*'),
                location=cell_val(row, 'Location*'),
                assigned_to=cell_val(row, 'Assigned To'),
                purpose=cell_val(row, 'Purpose'),
                notes=cell_val(row, 'Notes'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Printers: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_office_equipment(session, wb):
    print("\nProcessing sheet: Office Equipment...")
    wipe_table(session, 'office_equipment', 'office_equipment_id_seq')
    rows = read_sheet(wb, 'Office Equipment')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = OfficeEquipment(
                device=cell_val(row, 'Device'),
                model_name=cell_val(row, 'Model Name'),
                model_number=cell_val(row, 'Model Number'),
                serial=cell_val(row, 'Serial Number'),
                location=cell_val(row, 'Location'),
                assigned_to=cell_val(row, 'Assigned To'),
                purpose=cell_val(row, 'Purpose'),
                notes=cell_val(row, 'Notes'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  Office Equipment: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_nucs(session, wb):
    print("\nProcessing sheet: NUCs...")
    wipe_table(session, 'nucs', 'nucs_id_seq')
    rows = read_sheet(wb, 'NUCs')
    imported, failed = 0, []
    for i, row in enumerate(rows, 2):
        try:
            sp = session.begin_nested()
            obj = NUC(
                org=cell_val(row, 'Associated Org'),
                purpose=cell_val(row, 'Purpose'),
                serial=cell_val(row, 'Device Serial*'),
                status=cell_val(row, 'Device Status*'),
                location=cell_val(row, 'Location*'),
                mac_address=cell_val(row, 'MAC Address 1'),
                uuid=cell_val(row, 'UUID'),
                last_updated=parse_date(row.get('Last Updated')),
                notes=cell_val(row, 'Notes'),
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, str(e)))
    print(f"  NUCs: {imported} imported, {len(failed)} failed")
    return imported, failed


def import_edge_boxes_dedup(session, wb, sheet_name):
    """Import edge box variant sheets — skip rows where serial
    already exists in edge_boxes."""
    print(f"\nProcessing sheet: {sheet_name} (dedup by serial)...")
    rows = read_sheet(wb, sheet_name)
    imported, skipped, failed = 0, 0, []
    for i, row in enumerate(rows, 2):
        serial = cell_val(row, 'Device Serial*')
        if not serial:
            skipped += 1
            continue
        existing = session.query(EdgeBox).filter(
            EdgeBox.serial == serial
        ).first()
        if existing:
            skipped += 1
            continue
        try:
            sp = session.begin_nested()
            obj = EdgeBox(
                serial=serial,
                status=cell_val(row, 'Device Status') or
                       cell_val(row, 'Device Status*'),
                part_number=cell_val(row, 'Part Number') or
                            cell_val(row, 'Part Number*'),
                mac_address=cell_val(row, 'MAC Address 1'),
                uuid=cell_val(row, 'UUID') or cell_val(row, 'UUID*'),
                warranty_id=cell_val(row, 'Warranty ID'),
                last_updated=parse_date(row.get('Last Updated')),
                customer=cell_val(row, 'Customer') or
                         cell_val(row, 'Customer*') or
                         cell_val(row, 'Partner/Customer*'),
                partner=cell_val(row, 'Partner') or
                        cell_val(row, 'Partner*'),
                site_name=cell_val(row, 'Site Name'),
                deployment_type=cell_val(row, 'Pilot Type*') or
                    'customer',
                discovered_by='spreadsheet_import',
            )
            session.add(obj)
            session.flush()
            obj.data_completeness = compute_completeness(obj) / 100.0
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, serial, str(e)))
    print(f"  {sheet_name}: {imported} new, {skipped} skipped "
          f"(duplicates/no serial), {len(failed)} failed")
    return imported, failed


# ---------------------------------------------------------------------------
# Component linking
# ---------------------------------------------------------------------------

def link_components(session):
    """Create device_components records for all components
    with associated_device_serial set."""
    print("\nLinking components to parent devices...")

    from datetime import date
    today = date.today()
    links_created = 0
    links_skipped = 0

    component_configs = [
        ('gpus',           GPU,         'gpu_serial'),
        ('hard_drives',    HardDrive,   'serial'),
        ('ram_modules',    RamModule,   'serial'),
        ('cpus',           CPU,         'serial'),
        ('psus',           PSU,         'serial'),
        ('motherboards',   Motherboard, 'serial'),
        ('pc_cooling',     PCCooling,   'serial'),
        ('pc_accessories', PCAccessory, 'serial'),
    ]

    for comp_table, Model, serial_attr in component_configs:
        components = session.query(Model).filter(
            Model.associated_device_serial != None,
            Model.associated_device_serial != ''
        ).all()

        for comp in components:
            parent_serial = comp.associated_device_serial.strip()

            # Check if link already exists
            existing_link = session.query(DeviceComponent).filter(
                DeviceComponent.component_table == comp_table,
                DeviceComponent.component_id == comp.id,
                DeviceComponent.removed_date == None,
            ).first()
            if existing_link:
                links_skipped += 1
                continue

            # Try EdgeBox first, then NUC
            parent = session.query(EdgeBox).filter(
                EdgeBox.serial.ilike(parent_serial)
            ).first()
            parent_table = 'edge_boxes'

            if not parent:
                parent = session.query(NUC).filter(
                    NUC.serial.ilike(parent_serial)
                ).first()
                parent_table = 'nucs'

            if not parent:
                print(f"  WARNING: No parent found for "
                      f"{comp_table} serial={getattr(comp, serial_attr)} "
                      f"associated_device_serial={parent_serial}")
                continue

            try:
                sp = session.begin_nested()
                link = DeviceComponent(
                    parent_table=parent_table,
                    parent_id=parent.id,
                    component_table=comp_table,
                    component_id=comp.id,
                    installed_date=today,
                    installed_by='spreadsheet_import',
                    notes='Linked during initial spreadsheet import',
                )
                session.add(link)
                sp.commit()
                links_created += 1
            except Exception as e:
                sp.rollback()
                print(f"  ERROR linking {comp_table} id={comp.id}: {e}")

    session.commit()
    print(f"  Component links: {links_created} created, "
          f"{links_skipped} already existed")
    return links_created


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    import openpyxl

    parser = argparse.ArgumentParser(
        description='Import inventory categories from master Excel spreadsheet.'
    )
    parser.add_argument('xlsx', help='Path to the .xlsx workbook')
    parser.add_argument(
        '--sheet',
        metavar='SHEET',
        help=(
            'Import a single sheet only. Valid values: '
            'gpus, cameras, hard_drives, ram, motherboards, cpus, psus, ups, '
            'pc_cooling, pc_accessories, monitors, computers, phones, '
            'mobile_devices, network_equipment, access_control, webcams, '
            'printers, office_equipment, nucs, '
            'edge_boxes_customer, edge_boxes_pilots'
        )
    )
    args = parser.parse_args()

    print(f"Loading workbook: {args.xlsx}")
    wb = openpyxl.load_workbook(args.xlsx, data_only=True)

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Map sheet keys to import functions
    SHEET_MAP = {
        'gpus':               lambda: import_gpus(session, wb),
        'cameras':            lambda: import_cameras(session, wb),
        'hard_drives':        lambda: import_hard_drives(session, wb),
        'ram':                lambda: import_ram(session, wb),
        'motherboards':       lambda: import_motherboards(session, wb),
        'cpus':               lambda: import_cpus(session, wb),
        'psus':               lambda: import_psus(session, wb),
        'ups':                lambda: import_ups(session, wb),
        'pc_cooling':         lambda: import_pc_cooling(session, wb),
        'pc_accessories':     lambda: import_pc_accessories(session, wb),
        'monitors':           lambda: import_monitors(session, wb),
        'computers':          lambda: import_computers(session, wb),
        'phones':             lambda: import_phones(session, wb),
        'mobile_devices':     lambda: import_mobile_devices(session, wb),
        'network_equipment':  lambda: import_network_equipment(session, wb),
        'access_control':     lambda: import_access_control(session, wb),
        'webcams':            lambda: import_webcams(session, wb),
        'printers':           lambda: import_printers(session, wb),
        'office_equipment':   lambda: import_office_equipment(session, wb),
        'nucs':               lambda: import_nucs(session, wb),
        'edge_boxes_customer': lambda: import_edge_boxes_dedup(session, wb, 'Customer Edge Boxes'),
        'edge_boxes_pilots':   lambda: import_edge_boxes_dedup(session, wb, 'Pilots'),
    }

    results = {}

    if args.sheet:
        # Single sheet mode
        key = args.sheet.lower().strip()
        if key not in SHEET_MAP:
            print(f"ERROR: Unknown sheet '{key}'")
            print(f"Valid values: {', '.join(SHEET_MAP.keys())}")
            session.close()
            wb.close()
            sys.exit(1)
        print(f"\nSingle-sheet mode: importing '{key}' only")
        result = SHEET_MAP[key]()
        if isinstance(result, tuple):
            results[key] = result
        # Run component linking pass after single-sheet import
        links = link_components(session)
    else:
        # Full import mode — all sheets in order
        for key, fn in SHEET_MAP.items():
            if key.startswith('edge_boxes'):
                fn()
            else:
                results[key] = fn()
        links = link_components(session)

    session.close()
    wb.close()

    # Final report
    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    for category, result in results.items():
        if isinstance(result, tuple):
            imported = result[0]
            failed = result[1]
            print(f"  {category:<20} {imported:>4} imported  "
                  f"{len(failed):>3} failed")
    print(f"  {'component_links':<20} {links:>4} created")
    print("=" * 60)
