"""Shipment photos schema (unit_photos + unit_photo_items) + adoption of the
legacy intake_photos debt (audit F13: photos permanently orphaned from
devices — the linking endpoint never existed).

Adoption policy, per photo, reported line by line:
  * file exists on disk           -> ADOPTED as an inbound unit photo
    pointing at the SAME file (no moves); a thumbnail is generated; the
    event linkage carries over. The legacy row is kept (the old GET route
    still serves it) but is superseded.
  * file missing on disk          -> SKIPPED (reported; row kept as record).
Idempotent: a legacy photo is adopted at most once (matched on file_path).

Run:
    docker compose exec app python migrations/069_unit_photos.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402

DDL = [
    """
    CREATE TABLE IF NOT EXISTS unit_photos (
        id SERIAL PRIMARY KEY,
        file_path VARCHAR(255) NOT NULL,
        thumb_path VARCHAR(255) NOT NULL,
        direction VARCHAR(16) NOT NULL,
        caption VARCHAR(255),
        taken_at TIMESTAMP,
        original_filename VARCHAR(255),
        file_size INTEGER,
        uploaded_by INTEGER REFERENCES users(id),
        receiving_event_id INTEGER REFERENCES receiving_events(id) ON DELETE SET NULL,
        customer_order_id INTEGER REFERENCES customer_orders(id) ON DELETE SET NULL,
        deployment_record_id INTEGER REFERENCES deployment_records(id) ON DELETE SET NULL,
        is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
        hidden_by INTEGER REFERENCES users(id),
        hidden_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_up_event ON unit_photos(receiving_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_up_order ON unit_photos(customer_order_id)",
    """
    CREATE TABLE IF NOT EXISTS unit_photo_items (
        photo_id INTEGER NOT NULL REFERENCES unit_photos(id) ON DELETE CASCADE,
        item_id INTEGER NOT NULL REFERENCES item_schema.items(id) ON DELETE CASCADE,
        PRIMARY KEY (photo_id, item_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_upi_item ON unit_photo_items(item_id)",
]


def main():
    from PIL import Image  # in-container dependency, same as the app

    root = Path(settings.PHOTO_UPLOAD_DIR)
    (root / "unit" / "thumbs").mkdir(parents=True, exist_ok=True)

    with engine.begin() as conn:
        for ddl in DDL:
            conn.execute(text(ddl))

        legacy = conn.execute(text(
            "SELECT id, receiving_event_id, filename, original_filename, "
            "file_size, caption, uploaded_by, created_at FROM intake_photos "
            "ORDER BY id")).fetchall()

        adopted = skipped_missing = already = 0
        for row in legacy:
            pid, event_id, rel, orig, size, caption, by, created = row
            if conn.execute(text(
                    "SELECT 1 FROM unit_photos WHERE file_path = :p"),
                    {"p": rel}).fetchone():
                already += 1
                print(f"  intake#{pid}: already adopted")
                continue
            fpath = root / rel
            if not fpath.exists():
                skipped_missing += 1
                print(f"  intake#{pid}: SKIPPED — file missing on disk ({rel})")
                continue
            thumb_rel = f"unit/thumbs/legacy_{pid}.jpg"
            try:
                img = Image.open(fpath)
                img.load()
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.thumbnail((480, 480))
                img.save(root / thumb_rel, "JPEG", quality=80)
            except Exception as e:
                skipped_missing += 1
                print(f"  intake#{pid}: SKIPPED — unreadable image ({e})")
                continue
            conn.execute(text(
                "INSERT INTO unit_photos (file_path, thumb_path, direction, caption, "
                "original_filename, file_size, uploaded_by, receiving_event_id, "
                "taken_at, created_at) VALUES (:f, :t, 'inbound', :c, :o, :s, :u, :e, "
                ":ts, :ts)"),
                {"f": rel, "t": thumb_rel, "c": caption, "o": orig, "s": size,
                 "u": by, "e": event_id, "ts": created})
            adopted += 1
            print(f"  intake#{pid}: ADOPTED (event={event_id or '—'})")

        total = len(legacy)
        assert adopted + skipped_missing + already == total, "adoption accounting broken"
        print(f"069 applied. Legacy intake photos: total={total} adopted={adopted} "
              f"already-adopted={already} skipped-missing={skipped_missing}")


if __name__ == "__main__":
    main()
