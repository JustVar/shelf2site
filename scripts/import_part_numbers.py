#!/usr/bin/env python3
"""
Import/update Part Numbers from the master Excel spreadsheet.

Usage:
    python scripts/import_part_numbers.py <path_to_xlsx>

UPSERT behavior — never deletes existing records:
  - If part_number exists → update vendor, form_factor, service_type, last_updated
  - If part_number does not exist → insert new record
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import PartNumber

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


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


def cell_val(row, header):
    """Safely get cell value, return None if missing or empty."""
    val = row.get(header)
    if val is None:
        return None
    s = str(val).strip()
    return None if s in ('', 'None', 'FALSE', 'True') else s


if __name__ == '__main__':
    import openpyxl

    if len(sys.argv) < 2:
        print("Usage: python scripts/import_part_numbers.py <path_to_xlsx>")
        sys.exit(1)

    xlsx_path = sys.argv[1]
    print(f"Loading workbook: {xlsx_path}")
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)

    if 'Part Numbers' not in wb.sheetnames:
        print("ERROR: 'Part Numbers' sheet not found in workbook")
        sys.exit(1)

    ws = wb['Part Numbers']
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        print("ERROR: Sheet is empty")
        sys.exit(1)

    headers = [str(h).strip() if h else '' for h in rows[0]]
    data_rows = [dict(zip(headers, row)) for row in rows[1:]]

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    inserted, updated, skipped, failed = 0, 0, 0, []

    for i, row in enumerate(data_rows, 2):
        pn = cell_val(row, 'Part Number')
        if not pn:
            skipped += 1
            continue

        try:
            sp = session.begin_nested()
            existing = session.query(PartNumber).filter(
                PartNumber.part_number == pn
            ).first()

            if existing:
                existing.vendor = cell_val(row, 'Vendor') or existing.vendor
                existing.form_factor = cell_val(row, 'Form Factor') or existing.form_factor
                existing.service_type = cell_val(row, 'Service Type') or existing.service_type
                existing.last_updated = parse_date(row.get('Last Updated')) or existing.last_updated
                sp.commit()
                updated += 1
            else:
                obj = PartNumber(
                    part_number=pn,
                    vendor=cell_val(row, 'Vendor'),
                    form_factor=cell_val(row, 'Form Factor'),
                    service_type=cell_val(row, 'Service Type'),
                    last_updated=parse_date(row.get('Last Updated')),
                    discovered_by='spreadsheet_import',
                )
                session.add(obj)
                sp.commit()
                inserted += 1
        except Exception as e:
            sp.rollback()
            failed.append((i, pn, str(e)))

    session.commit()
    session.close()
    wb.close()

    print("\n" + "=" * 50)
    print("PART NUMBERS IMPORT COMPLETE")
    print("=" * 50)
    print(f"  Total rows in sheet:  {len(data_rows)}")
    print(f"  Inserted (new):       {inserted}")
    print(f"  Updated (existing):   {updated}")
    print(f"  Skipped (empty PN):   {skipped}")
    print(f"  Failed:               {len(failed)}")
    if failed:
        print("\n  FAILURES:")
        for row_num, pn, err in failed:
            print(f"    Row {row_num} ({pn}): {err}")
    print("=" * 50)
