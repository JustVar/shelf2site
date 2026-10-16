"""Build the database schema from the code.

app/models.py creates the tables. The SQL files in db/ add what the models
cannot express: the two enum types the models expect to exist already, a
view, CHECK constraints, partial unique indexes, three tables used only
through raw SQL, and reference rows. Every step is idempotent, so building
against a database that is already complete changes nothing.

The app builds on startup (app/main.py lifespan). Several gunicorn workers
start at once, so the build runs under a Postgres advisory lock: the first
worker builds, the rest wait and then find nothing left to do.
"""

from pathlib import Path

from sqlalchemy import text

from .database import Base, engine
from . import models  # noqa: F401  (registers every table on Base.metadata)

DB_DIR = Path(__file__).resolve().parent.parent / "db"
BEFORE = ["00_types.sql"]
AFTER = ["10_extras.sql", "20_reference.sql"]

# An arbitrary constant naming this lock; any other user of advisory locks
# in this database must pick a different number.
LOCK_KEY = 7302651

# Objects from db/10_extras.sql that a complete build must contain.
EXPECTED_RELATIONS = [
    "public.edit_locks",
    "public.error_log",
    "item_schema.csv_import_map",
    "item_schema.location_types",
    "item_schema.intake_photos",
    "item_schema.current_containment",
]
EXPECTED_INDEXES = ["checkouts_one_open_per_item", "uq_delete_requests_one_pending"]
EXPECTED_CHECKS = [
    "oem_status_check",
    "deployment_status_check",
    "customer_orders_owner_partner_check",
    "ck_delete_requests_target",
    "ck_delete_requests_status",
    "ck_delete_requests_reason",
]


def _run_sql_file(conn, name, log):
    # Through the driver cursor with no parameters, so the % in format()
    # calls inside the SQL is not read as a parameter marker.
    conn.connection.cursor().execute((DB_DIR / name).read_text(encoding="utf-8"))
    log("applied db/" + name)


def build_schema(log=lambda message: None):
    """Create everything the app needs. Safe to call on every startup."""
    with engine.connect() as lock_conn:
        lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            with engine.begin() as conn:
                for name in BEFORE:
                    _run_sql_file(conn, name, log)
            Base.metadata.create_all(bind=engine)
            log("created missing tables from app/models.py ("
                + str(len(Base.metadata.tables)) + " in the models)")
            with engine.begin() as conn:
                for name in AFTER:
                    _run_sql_file(conn, name, log)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock_conn.commit()


def missing_objects():
    """Names of expected relations, indexes and constraints that do not exist."""
    missing = []
    with engine.connect() as conn:
        for rel in EXPECTED_RELATIONS:
            if conn.execute(text("SELECT to_regclass(:r)"), {"r": rel}).scalar() is None:
                missing.append(rel)
        for idx in EXPECTED_INDEXES:
            if not conn.execute(text("SELECT 1 FROM pg_indexes WHERE indexname = :i"),
                                {"i": idx}).first():
                missing.append(idx)
        for chk in EXPECTED_CHECKS:
            if not conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = :c"),
                                {"c": chk}).first():
                missing.append(chk)
        for table in Base.metadata.sorted_tables:
            name = (table.schema or "public") + "." + table.name
            if conn.execute(text("SELECT to_regclass(:r)"), {"r": name}).scalar() is None:
                missing.append(name)
    return missing
