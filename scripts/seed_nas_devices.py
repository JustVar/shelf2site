"""Seed the 4 QNAP TS-264 NAS devices received 02/10/2026."""

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.database import SessionLocal, create_all_tables
from app.models import NASDevice, compute_completeness

QNAP_TS264_UNITS = [
    {"serial": "Q854310683Q",  "status": "Received"},
    {"serial": "Q7FQM099133", "status": "Received"},
    {"serial": "Q78VS100482", "status": "Received"},
    {"serial": "Q78ZC106416", "status": "Received"},
]

COMMON = {
    "manufacturer": "QNAP",
    "model": "TS-264-8G-US",
    "bay_count": 2,
    "ram_gb": "8",
    "discovered_by": "manual",
}


def main():
    create_all_tables()
    db = SessionLocal()
    added = 0
    try:
        for unit in QNAP_TS264_UNITS:
            existing = db.query(NASDevice).filter(
                NASDevice.serial == unit["serial"]
            ).first()
            if existing:
                print(f"  [SKIP] {unit['serial']} already exists")
                continue
            device = NASDevice(**COMMON, **unit)
            device.data_completeness = compute_completeness(device)
            db.add(device)
            added += 1
            print(f"  [ADD]  {unit['serial']} — QNAP TS-264-8G-US")
        db.commit()
        print(f"\nDone. {added} of {len(QNAP_TS264_UNITS)} devices seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
