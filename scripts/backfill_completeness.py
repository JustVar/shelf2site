#!/usr/bin/env python3
"""
Backfill data_completeness for all inventory records.

Usage:
    python scripts/backfill_completeness.py

One-time script. Calculates completeness from REQUIRED_FIELDS
and saves to data_completeness (0.0–1.0 scale) for every record.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    EdgeBox, NUC, GPU, Camera, Monitor, Computer, Phone,
    MobileDevice, Webcam, Printer, OfficeEquipment,
    NetworkEquipment, AccessControl, HardDrive, RamModule,
    CPU, PSU, Motherboard, PCCooling, PCAccessory, UPS,
    PartNumber, compute_completeness,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

MODELS_TO_BACKFILL = [
    EdgeBox, NUC, GPU, Camera, Monitor, Computer, Phone,
    MobileDevice, Webcam, Printer, OfficeEquipment,
    NetworkEquipment, AccessControl, HardDrive, RamModule,
    CPU, PSU, Motherboard, PCCooling, PCAccessory, UPS,
    PartNumber,
]

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

print("Backfilling data_completeness...\n")

total_updated = 0
for Model in MODELS_TO_BACKFILL:
    name = Model.__name__
    records = session.query(Model).all()
    count = len(records)
    if count == 0:
        print(f"  {name}: 0 records, skipped")
        continue

    total_score = 0.0
    for i, record in enumerate(records):
        score = compute_completeness(record)
        record.data_completeness = score / 100.0
        total_score += score
        if (i + 1) % 100 == 0:
            session.commit()

    session.commit()
    avg = total_score / count
    total_updated += count
    print(f"  {name}: {count} records, avg completeness: {avg:.1f}%")

session.close()

print(f"\nDone. {total_updated} records updated.")
