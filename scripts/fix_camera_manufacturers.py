#!/usr/bin/env python3
"""
Fill in missing camera manufacturers based on model prefix matching.

Flags unrecognized models for manual review instead of guessing.

Usage:
    python scripts/fix_camera_manufacturers.py [--dry-run]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Prefix → manufacturer mapping
# Order matters — more specific prefixes first
# ---------------------------------------------------------------------------

PREFIX_MAP = [
    # Avigilon
    ("ANV-",        "Avigilon"),
    ("9C-H4A-",     "Avigilon"),
    ("320S-H4A-",   "Avigilon"),

    # Hanwha
    ("QND-",        "Hanwha"),
    ("QNV-",        "Hanwha"),
    ("XND-",        "Hanwha"),
    ("XNF-",        "Hanwha"),
    ("XNO-",        "Hanwha"),
    ("XNP-",        "Hanwha"),
    ("XNV-",        "Hanwha"),
    ("PNM-",        "Hanwha"),
    ("CD52-",       "Hanwha"),
    ("WBS",         "Hanwha"),
    ("WDA",         "Hanwha"),

    # i-PRO
    ("WV-",         "i-PRO"),

    # AXIS
    ("P3",          "AXIS"),

    # Uniview
    ("IPC",         "Uniview"),

    # VCA / Company-branded VCA
    ("IPAi",        "VCA"),
    ("IPAI",        "VCA"),
    ("IPB",         "VCA"),
    ("IPFE",        "VCA"),
    ("BC-5M-",      "the company (VCA)"),
    ("BC-5V-",      "the company (VCA)"),
    ("DC-5F-",      "the company (VCA)"),
    ("DC-5V-",      "the company (VCA)"),
    ("FC-",         "the company (VCA)"),
    ("MS-",         "the company (VCA)"),
]

# Models that cannot be auto-mapped — flag for manual review
MANUAL_REVIEW = {
    "DOME-B",
    "1.0MP-HD-DOME-DN",
}


def match_manufacturer(model: str) -> str | None:
    """Return matched manufacturer or None if unrecognized."""
    if not model or model.strip().lower() == "none":
        return None
    model = model.strip()
    if model in MANUAL_REVIEW:
        return None
    for prefix, manufacturer in PREFIX_MAP:
        if model.upper().startswith(prefix.upper()):
            return manufacturer
    return None


def main(dry_run: bool = False):
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    rows = session.execute(
        text("SELECT id, model, manufacturer FROM cameras ORDER BY model")
    ).fetchall()

    updated = []
    skipped_no_model = []
    skipped_has_manufacturer = []
    flagged_manual = []
    unrecognized = []

    for row in rows:
        model = row.model
        current_manufacturer = row.manufacturer

        # Skip if manufacturer already set
        if current_manufacturer:
            skipped_has_manufacturer.append((row.id, model, current_manufacturer))
            continue

        # Skip if no model
        if not model or str(model).strip().lower() == "none":
            skipped_no_model.append(row.id)
            continue

        # Flag known manual review models
        if str(model).strip() in MANUAL_REVIEW:
            flagged_manual.append((row.id, model))
            continue

        matched = match_manufacturer(model)

        if matched:
            updated.append((row.id, model, matched))
            if not dry_run:
                session.execute(
                    text("UPDATE cameras SET manufacturer = :m WHERE id = :id"),
                    {"m": matched, "id": row.id}
                )
        else:
            unrecognized.append((row.id, model))

    if not dry_run:
        session.commit()

    session.close()

    # ---------------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"CAMERA MANUFACTURER FIX {'(DRY RUN)' if dry_run else ''}")
    print("=" * 60)

    print(f"\n✅ {'Would update' if dry_run else 'Updated'}: {len(updated)}")
    for id_, model, manufacturer in updated:
        print(f"   id={id_:<4} {model:<35} → {manufacturer}")

    print(f"\n⏭  Already had manufacturer: {len(skipped_has_manufacturer)}")
    for id_, model, manufacturer in skipped_has_manufacturer:
        print(f"   id={id_:<4} {model:<35}   {manufacturer}")

    print(f"\n⚠️  Flagged for manual review: {len(flagged_manual)}")
    for id_, model in flagged_manual:
        print(f"   id={id_:<4} {model}")

    print(f"\n❓ Unrecognized model — manual review needed: {len(unrecognized)}")
    for id_, model in unrecognized:
        print(f"   id={id_:<4} {model}")

    print(f"\n⬜ No model — cannot map: {len(skipped_no_model)}")
    print(f"   {len(skipped_no_model)} records with no model value")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Fill missing camera manufacturers from model prefix matching."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to the database"
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
