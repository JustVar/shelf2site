"""Seed the OUI allowlist with known company device manufacturers.

Pre-populated from the spreadsheet data (camera MACs, Yealink phones, etc.)
and well-known enterprise OUI prefixes.

Run once during setup:
    python -m scripts.seed_oui_allowlist
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import SessionLocal, create_all_tables  # noqa: E402
from app.models import OUIAllowlist  # noqa: E402


# Known company device OUIs (from spreadsheet MAC analysis + manufacturer lookups)
SEED_DATA = [
    # Cameras - Hanwha Techwin / Samsung Techwin
    ("E4:30:22", "Hanwha Techwin", "cameras"),
    ("F0:B2:B9", "Hanwha Techwin", "cameras"),
    ("00:09:18", "Samsung Techwin", "cameras"),
    ("00:16:6C", "Samsung Techwin", "cameras"),
    ("9C:57:AD", "Hanwha Techwin", "cameras"),
    # Cameras - Axis Communications
    ("B8:A4:4F", "Axis Communications", "cameras"),
    ("00:40:8C", "Axis Communications", "cameras"),
    ("AC:CC:8E", "Axis Communications", "cameras"),
    # Cameras - Avigilon
    ("00:18:85", "Avigilon", "cameras"),
    # Access Control - Avigilon (Alta)
    ("70:B3:D5", "Avigilon (Alta)", "access_control"),
    # Phones - Yealink
    ("80:5E:C0", "Yealink", "phones"),
    ("00:15:65", "Yealink", "phones"),
    ("24:21:24", "Yealink", "phones"),
    # Network Equipment - Cisco
    ("00:1A:A1", "Cisco Systems", "network_equipment"),
    ("00:17:94", "Cisco-Linksys", "network_equipment"),
    # Network Equipment - Ubiquiti
    ("FC:EC:DA", "Ubiquiti", "network_equipment"),
    ("24:5A:4C", "Ubiquiti", "network_equipment"),
    ("78:8A:20", "Ubiquiti", "network_equipment"),
    # Printers - HP
    ("3C:D9:2B", "HP Inc.", "printers"),
    ("A0:D3:C1", "HP Inc.", "printers"),
    # Edge Boxes / NUCs - Intel
    ("B4:96:91", "Intel Corporate", "edge_boxes"),
    ("A4:BB:6D", "Intel Corporate", "edge_boxes"),
    ("48:21:0B", "Intel Corporate", "edge_boxes"),
]


def main():
    print("=== Company Hardware Inventory - OUI Allowlist Seed ===")
    print()

    create_all_tables()
    db = SessionLocal()

    try:
        added = 0
        skipped = 0

        for oui_prefix, manufacturer, maps_to_table in SEED_DATA:
            oui_upper = oui_prefix.upper()
            existing = db.query(OUIAllowlist).filter(
                OUIAllowlist.oui_prefix == oui_upper
            ).first()

            if existing:
                print(f"  [SKIP] {oui_upper} ({manufacturer}) - already exists")
                skipped += 1
                continue

            entry = OUIAllowlist(
                oui_prefix=oui_upper,
                manufacturer=manufacturer,
                maps_to_table=maps_to_table,
                is_active=True,
            )
            db.add(entry)
            print(f"  [ADD]  {oui_upper} -> {manufacturer} -> {maps_to_table}")
            added += 1

        db.commit()
        print()
        print(f"Done. Added {added}, skipped {skipped} (already existed).")
        print(f"Total OUI entries: {db.query(OUIAllowlist).count()}")
        print()
        print("You can manage the allowlist at /admin/oui in the dashboard.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
