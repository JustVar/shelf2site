#!/usr/bin/env python3
"""
Create internal Computer records for custom builds and link their components.

Usage:
    python scripts/link_custom_builds.py

Creates Computer records for 'LLM Machine' and 'Dell Machine' (if they don't
already exist), then creates device_components links for all components whose
associated_device_serial matches these names.

Safe to run multiple times — skips existing records and links.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import (
    Computer, DeviceComponent,
    GPU, HardDrive, RamModule, CPU, PSU, Motherboard, PCCooling, PCAccessory,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Computer records to create
# ---------------------------------------------------------------------------

CUSTOM_BUILDS = [
    {
        "device_name": "LLM Machine",
        "device": "Custom Build",
        "serial": "INTERNAL-LLM-01",
        "location": "Hardware Office",
        "purpose": "Internal AI/LLM Development Machine",
        "notes": "Custom built machine. Internal serial assigned. Components tracked via device_components.",
    },
    {
        "device_name": "Dell Machine",
        "device": "Dell",
        "serial": "INTERNAL-DELL-01",
        "location": "Hardware Office",
        "purpose": "Internal Testing Machine",
        "notes": "Dell machine. Internal serial assigned. Components tracked via device_components.",
    },
]

NAME_TO_SERIAL = {
    "LLM Machine": "INTERNAL-LLM-01",
    "Dell Machine": "INTERNAL-DELL-01",
}

COMPONENT_TABLES = [
    ("gpus",           GPU,         "gpu_serial"),
    ("hard_drives",    HardDrive,   "serial"),
    ("ram_modules",    RamModule,   "serial"),
    ("cpus",           CPU,         "serial"),
    ("psus",           PSU,         "serial"),
    ("motherboards",   Motherboard, "serial"),
    ("pc_cooling",     PCCooling,   "serial"),
    ("pc_accessories", PCAccessory, "serial"),
]


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    today = date.today()
    computers_created = 0
    computers_skipped = 0

    # --- Step 1: Create Computer records ---
    print("Step 1: Creating internal Computer records...")
    for build in CUSTOM_BUILDS:
        existing = session.query(Computer).filter(
            Computer.device_name == build["device_name"]
        ).first()
        if existing:
            print(f"  SKIP: '{build['device_name']}' already exists (id={existing.id})")
            computers_skipped += 1
            continue
        try:
            sp = session.begin_nested()
            obj = Computer(
                device_name=build["device_name"],
                device=build["device"],
                serial=build["serial"],
                location=build["location"],
                purpose=build["purpose"],
                notes=build["notes"],
                discovered_by="spreadsheet_import",
            )
            session.add(obj)
            sp.commit()
            print(f"  CREATED: '{build['device_name']}' (serial={build['serial']})")
            computers_created += 1
        except Exception as e:
            sp.rollback()
            print(f"  ERROR creating '{build['device_name']}': {e}")

    session.commit()

    # --- Step 2: Link components ---
    print("\nStep 2: Linking components to custom builds...")
    links_created = 0
    links_skipped = 0
    links_failed = 0
    link_details = {}

    for name, serial in NAME_TO_SERIAL.items():
        parent = session.query(Computer).filter(
            Computer.serial == serial
        ).first()
        if not parent:
            print(f"  ERROR: Computer with serial '{serial}' not found, skipping '{name}'")
            continue

        print(f"\n  Linking components for '{name}' (computer id={parent.id})...")

        for comp_table, Model, serial_attr in COMPONENT_TABLES:
            components = session.query(Model).filter(
                Model.associated_device_serial == name
            ).all()

            if not components:
                continue

            table_created = 0
            for comp in components:
                # Check if link already exists
                existing_link = session.query(DeviceComponent).filter(
                    DeviceComponent.component_table == comp_table,
                    DeviceComponent.component_id == comp.id,
                    DeviceComponent.removed_date == None,
                ).first()
                if existing_link:
                    links_skipped += 1
                    continue

                try:
                    sp = session.begin_nested()
                    link = DeviceComponent(
                        parent_table="computers",
                        parent_id=parent.id,
                        component_table=comp_table,
                        component_id=comp.id,
                        installed_date=today,
                        installed_by="spreadsheet_import",
                        notes="Linked via custom build reconciliation",
                    )
                    session.add(link)
                    sp.commit()
                    links_created += 1
                    table_created += 1
                except Exception as e:
                    sp.rollback()
                    links_failed += 1
                    print(f"    ERROR linking {comp_table} id={comp.id}: {e}")

            if table_created:
                print(f"    {comp_table}: {table_created} linked")
                link_details[f"{name}/{comp_table}"] = table_created

    session.commit()
    session.close()

    # --- Report ---
    print("\n" + "=" * 55)
    print("CUSTOM BUILD RECONCILIATION COMPLETE")
    print("=" * 55)
    print(f"  Computers created:    {computers_created}")
    print(f"  Computers skipped:    {computers_skipped}")
    print(f"  Component links:      {links_created} created, "
          f"{links_skipped} already existed, {links_failed} failed")
    if link_details:
        print("\n  Links by table:")
        for key, count in link_details.items():
            print(f"    {key:<35s} {count:>3}")
    print("=" * 55)
