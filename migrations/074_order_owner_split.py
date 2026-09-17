"""Migration 074: order owner split.

Creates oem_partners and adds owner and oem_partner_id to customer_orders per
docs/specs/order-owner-split-slice-1.md. Every existing order keeps the column
default, brand, so nothing is backfilled. A CHECK ties the two columns: a
partner is set exactly when the OEM owns the order.

Idempotent (IF NOT EXISTS, and the CHECK is dropped before it is added),
single transaction.

Run:
    docker compose exec -T app python migrations/074_order_owner_split.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

CHECK_NAME = "customer_orders_owner_partner_check"

STATEMENTS = [
    "CREATE TABLE IF NOT EXISTS oem_partners ("
    " id serial PRIMARY KEY,"
    " name varchar(128) NOT NULL UNIQUE,"
    " active boolean NOT NULL DEFAULT true,"
    " created_at timestamp DEFAULT now(),"
    " updated_at timestamp DEFAULT now()"
    ")",
    "ALTER TABLE customer_orders ADD COLUMN IF NOT EXISTS owner varchar(16)"
    " NOT NULL DEFAULT 'brand'",
    "ALTER TABLE customer_orders ADD COLUMN IF NOT EXISTS oem_partner_id integer"
    " REFERENCES oem_partners(id)",
    "ALTER TABLE customer_orders DROP CONSTRAINT IF EXISTS " + CHECK_NAME,
    "ALTER TABLE customer_orders ADD CONSTRAINT " + CHECK_NAME
    + " CHECK ((owner = 'oem') = (oem_partner_id IS NOT NULL))",
]


def main() -> None:
    with engine.begin() as conn:
        before = conn.execute(text("SELECT count(*) FROM customer_orders")).scalar()
        print(f"customer_orders rows before: {before}")
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
        after = conn.execute(text("SELECT count(*) FROM customer_orders")).scalar()
        print(f"customer_orders rows after: {after}")
        partners = conn.execute(text("SELECT count(*) FROM oem_partners")).scalar()
        print(f"oem_partners rows: {partners}")
        cols = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'customer_orders' "
            "AND column_name IN ('owner', 'oem_partner_id')"
        )).fetchall()
        col_names = sorted(c[0] for c in cols)
        print(f"owner columns present: {col_names}")
        cons = conn.execute(text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = CAST('public.customer_orders' AS regclass) "
            "AND conname = :name"
        ), {"name": CHECK_NAME}).fetchall()
        con_names = [c[0] for c in cons]
        print(f"owner partner check present: {con_names}")
        brand = conn.execute(text(
            "SELECT count(*) FILTER (WHERE owner = 'brand') FROM customer_orders"
        )).scalar()
        print(f"customer_orders rows owned by brand: {brand}")
        if col_names != ["oem_partner_id", "owner"]:
            raise SystemExit("ABORT: expected both owner columns present")
        if con_names != [CHECK_NAME]:
            raise SystemExit("ABORT: expected the owner partner CHECK present")
        if brand != after:
            raise SystemExit("ABORT: expected every customer_orders row owned by brand")
    print("OK: migration 074 complete")


if __name__ == "__main__":
    main()
