"""Migration 077: drop contract_value and hardware_cost from customer_orders.

Board item 40 slice B; spec at docs/specs/receipts-permission-and-financial-drop.md.
The two NUMERIC(12,2) columns added by migration 020 are dropped. The live
table carried 0 non-null values in either column when the spec was written;
this migration re-reads that and aborts before the first statement if any
row holds a value, so no data can be lost silently.

Idempotent: a column already absent is reported and skipped. Single
transaction. Row count asserted unchanged.

Run:
    docker compose exec -T app python migrations/077_drop_order_money_columns.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

TABLE = "customer_orders"
COLUMNS = ["contract_value", "hardware_cost"]


def has_column(conn, column):
    return conn.execute(text(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
    ), {"t": TABLE, "c": column}).scalar() == 1


def total(conn):
    return conn.execute(text("SELECT count(*) FROM " + TABLE)).scalar()


def nonnull(conn, column):
    return conn.execute(text("SELECT count(" + column + ") FROM " + TABLE)).scalar()


def main() -> None:
    with engine.begin() as conn:
        rows_before = total(conn)
        print("rows before: " + str(rows_before))
        present = [c for c in COLUMNS if has_column(conn, c)]
        absent = [c for c in COLUMNS if c not in present]
        for c in absent:
            print("already absent: " + c)
        for c in present:
            n = nonnull(conn, c)
            print("non-null " + c + ": " + str(n))
            if n:
                raise SystemExit("ABORT: " + c + " holds " + str(n) + " value(s); nothing dropped")

        for c in present:
            conn.execute(text("ALTER TABLE " + TABLE + " DROP COLUMN IF EXISTS " + c))
            print("dropped " + TABLE + "." + c)

        for c in COLUMNS:
            if has_column(conn, c):
                raise SystemExit("ABORT: " + c + " still present after drop")
        rows_after = total(conn)
        print("rows after: " + str(rows_after))
        if rows_after != rows_before:
            raise SystemExit("ABORT: row count moved")
        cols = conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ), {"t": TABLE}).scalar()
        print("columns on " + TABLE + " now: " + str(cols))
    print("OK: migration 077 complete")


if __name__ == "__main__":
    main()
