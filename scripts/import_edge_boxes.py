#!/usr/bin/env python3
"""
Import edge boxes from a CSV spreadsheet export.

Usage:
    python scripts/import_edge_boxes.py <path_to_csv>

WARNING: This script DELETES ALL existing edge_boxes rows before importing.
         IDs are reset to start from 1.
"""

import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import EdgeBox, compute_completeness

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: python scripts/import_edge_boxes.py <path_to_csv>")
    sys.exit(1)

csv_path = sys.argv[1]
if not os.path.isfile(csv_path):
    print(f"ERROR: File not found: {csv_path}")
    sys.exit(1)

# --- Column mapping: spreadsheet header → model field ---
COLUMN_MAP = {
    "Device Serial*": "serial",
    "Device Status*": "status",
    "Location*": "location",
    "Part Number*": "part_number",
    "MAC Address 1*": "mac_address",
    "Partner": "partner",
    "Customer": "customer",
    "Site Name": "site_name",
    "Type": "form_factor",
    "Warranty ID": "warranty_id",
    "UUID": "uuid",
    "Notes": "notes",
    "Purpose": "deployment_type",
    "Last Updated": "last_updated",
}

# --- Deployment type normalization ---
DEPLOYMENT_MAP = {
    "Customer": "customer",
    "Pilot": "pilot",
    "Demo": "demo",
    "Trade Show": "trade_show",
    "QA Environment": "internal",
    "QA Stage": "internal",
    "Testing": "internal",
    "Testing (Emulators)": "internal",
    "Emulator 1": "internal",
    "Emulator 2": "internal",
    "Emulator 3": "internal",
    "Monitoring": "internal",
    "Wireguard VPN": "internal",
    "Zoom Room Host": "internal",
    "Tigua Mirror": "internal",
    "RAID Testing": "internal",
    "": "internal",
}

# --- Status remapping ---
STATUS_REMAP = {
    "In Packaging": "Stock",
    "Out Of Box": "Stock",
}


def parse_date(value):
    """Try common date formats, return datetime or None."""
    if not value or not value.strip():
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def determine_sku(part_number, serial):
    """Determine SKU version from part number or serial prefix."""
    pn = (part_number or "").upper()
    sn = (serial or "").upper()
    if pn.startswith("EDGE") or sn.startswith("USCF"):
        return "2026"
    return "legacy"


# --- Main ---
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

print(f"Reading CSV: {csv_path}")

skipped = []
imported = 0
failed = []
total_rows = 0

with open(csv_path, encoding="latin-1") as f:
    reader = csv.DictReader(f)

    # Wipe existing data
    print("Deleting all existing edge_boxes rows...")
    session.execute(text("DELETE FROM edge_boxes"))
    session.execute(text("SELECT setval('edge_boxes_id_seq', 1, false)"))
    session.commit()
    print("  Wiped. ID sequence reset to 1.")

    for row_num, row in enumerate(reader, start=2):  # row 2 = first data row
        total_rows += 1

        serial_val = (row.get("Device Serial*") or "").strip()
        mac_val = (row.get("MAC Address 1*") or "").strip()

        form_factor_val = (row.get('Type') or '').strip()
        if form_factor_val.upper() == 'NUC':
            skipped.append((row_num, serial_val,
                f"form_factor=NUC — import via NUCs sheet instead"))
            continue

        try:
            sp = session.begin_nested()  # savepoint per row

            # Map spreadsheet columns to model fields
            fields = {}
            for csv_col, model_field in COLUMN_MAP.items():
                val = (row.get(csv_col) or "").strip()
                if val:
                    fields[model_field] = val
                else:
                    fields[model_field] = None

            # Normalize deployment_type
            purpose_raw = (row.get("Purpose") or "").strip()
            fields["deployment_type"] = DEPLOYMENT_MAP.get(purpose_raw, "internal")

            # Remap status
            raw_status = fields.get("status") or ""
            fields["status"] = STATUS_REMAP.get(raw_status, raw_status)

            # Parse last_updated as date
            fields["last_updated"] = parse_date(row.get("Last Updated") or "")

            # Determine SKU version
            fields["sku_version"] = determine_sku(fields.get("part_number"), fields.get("serial"))

            # Set import source
            fields["discovered_by"] = "spreadsheet_import"

            box = EdgeBox(**fields)
            session.add(box)
            session.flush()
            box.data_completeness = compute_completeness(box) / 100.0
            sp.commit()
            imported += 1

        except Exception as e:
            sp.rollback()  # only rolls back this one row
            # Retry with MAC cleared if it was a duplicate MAC violation
            if "UniqueViolation" in type(e).__name__ or "unique constraint" in str(e).lower():
                try:
                    sp2 = session.begin_nested()
                    fields["mac_address"] = None
                    fields["incomplete_reason"] = (
                        "MAC address removed during import — duplicate of another device "
                        "in the spreadsheet. Verify and update the correct MAC address."
                    )
                    box = EdgeBox(**fields)
                    session.add(box)
                    session.flush()
                    box.data_completeness = compute_completeness(box) / 100.0
                    sp2.commit()
                    imported += 1
                    print(f"    Row {row_num} (serial={serial_val}): retried without MAC — imported")
                    continue
                except Exception as e2:
                    sp2.rollback()
                    e = e2  # fall through to failed
            failed.append((row_num, serial_val, str(e)))

    session.commit()

session.close()

# --- Report ---
print("\n" + "=" * 50)
print("IMPORT COMPLETE")
print("=" * 50)
print(f"  Total CSV rows:    {total_rows}")
print(f"  Imported:          {imported}")
print(f"  Skipped:           {len(skipped)}")
print(f"  Failed:            {len(failed)}")

if skipped:
    print(f"\n  Skipped rows:")
    for row_num, serial, reason in skipped:
        print(f"    Row {row_num} (serial={serial}): {reason}")

if failed:
    print(f"\n  Failed rows:")
    for row_num, serial_val, err in failed:
        print(f"    Row {row_num} (serial={serial_val}): {err}")
