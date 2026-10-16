"""Migration 087: create public.order_documents (docs/specs/one-board-two-tracks.md).

Files attached to a customer order, mostly the vendor's certification and
validation documents. The table is defined by OrderDocument in app/models.py;
a fresh install creates it from the model, so this is for existing databases.

Dry run by default: says whether the table would be created. --apply creates
it and its index in one transaction. Rerunning after apply prints ALREADY
APPLIED.

Run inside the app container:
    docker compose exec -T app python migrations/087_order_documents.py
    docker compose exec -T app python migrations/087_order_documents.py --apply
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine
from app.models import OrderDocument

TABLE = "public.order_documents"


def main(apply: bool) -> None:
    with engine.begin() as conn:
        if conn.execute(text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is not None:
            print("ALREADY APPLIED: " + TABLE + " exists")
            return
        if not apply:
            print("dry run: would create " + TABLE + "; rerun with --apply")
            return
        OrderDocument.__table__.create(conn)
        if conn.execute(text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is None:
            raise SystemExit("ABORT: " + TABLE + " was not created; rolled back")
        print("created " + TABLE)


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
