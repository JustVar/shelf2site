"""Migration 084: drop public.intake_photos (board item N23).

The receive photo routes (POST /api/receive/photo and its serve route) had no
caller once label OCR moved to the unit photos upload (migration 069), and
they are removed in the same commit as this migration. This drops the table
they wrote. The photo files on disk under PHOTO_UPLOAD_DIR are not touched.

Not to be confused with item_schema.intake_photos, which stays.

Dry run by default: prints the row count and changes nothing. --apply drops
the table in one transaction. Rerunning after apply prints ALREADY APPLIED.
A fresh install never has the table (app/models.py no longer maps it).

Run inside the app container:
    docker compose exec -T app python migrations/084_drop_intake_photos.py
    docker compose exec -T app python migrations/084_drop_intake_photos.py --apply
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

TABLE = "public.intake_photos"


def main(apply: bool) -> None:
    with engine.begin() as conn:
        if conn.execute(text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is None:
            print("ALREADY APPLIED: " + TABLE + " does not exist")
            return
        rows = conn.execute(text("SELECT count(*) FROM " + TABLE)).scalar()
        print(TABLE + " rows: " + str(rows))
        if not apply:
            print("dry run: nothing changed; rerun with --apply to drop " + TABLE)
            return
        conn.execute(text("DROP TABLE " + TABLE))
        if conn.execute(text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is not None:
            raise SystemExit("ABORT: " + TABLE + " still exists; rolled back")
        print("dropped " + TABLE)


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
