"""Migration: Convert user + department permission columns from BOOLEAN to ENUM.

The tri-state semantics that were encoded as nullable booleans (NULL=inherit,
TRUE=grant, FALSE=block on users; TRUE=grant, FALSE=block on departments) are
moved to explicit ENUM types so the schema documents the state space directly
and the drawer UI in U2d can present the three states without a sentinel
nullable boolean.

Changes:
- New types:
    user_permission_state       ENUM ('inherit', 'grant', 'block')
    department_permission_state ENUM ('grant', 'block')
- users: 14 inherited can_* columns swap BOOLEAN NULL → user_permission_state
    NOT NULL DEFAULT 'inherit'.  Backfill: NULL→inherit, TRUE→grant, FALSE→block.
- users: view_sensitive_customers (no department fallback) → user_permission_state
    NOT NULL DEFAULT 'block'.  Backfill: NULL→block, TRUE→grant, FALSE→block.
- departments: 14 can_* columns BOOLEAN NOT NULL → department_permission_state
    NOT NULL DEFAULT 'block'.  Backfill: TRUE→grant, FALSE→block.

Single transaction.  All-or-nothing.

Run instructions:
    docker compose exec app python migrations/048_permission_columns_to_enum.py

Single transaction, all-or-nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


# 14 user permissions that fall back to the department default when 'inherit'.
USER_INHERITED_PERMS = [
    "can_view_financial", "can_manage_warranty", "can_manage_trials",
    "can_manage_procurement", "can_manage_sites", "can_manage_users",
    "can_manage_system", "can_view_audit_log", "can_access_receiving",
    "can_access_map", "can_access_disposal", "can_access_credentials",
    "can_manage_provisioning", "can_view_provisioning",
]
# User-only permission (no department equivalent — no inheritance fallback).
USER_NON_INHERITED_PERMS = ["view_sensitive_customers"]
# Department permissions — same 14 as USER_INHERITED_PERMS, by definition.
DEPT_PERMS = USER_INHERITED_PERMS


def run():
    with engine.begin() as conn:
        # ── Step 1: Create ENUM types ─────────────────────────────────
        conn.execute(text("CREATE TYPE user_permission_state AS ENUM ('inherit', 'grant', 'block')"))
        print("  ✓ created type user_permission_state ('inherit', 'grant', 'block')")
        conn.execute(text("CREATE TYPE department_permission_state AS ENUM ('grant', 'block')"))
        print("  ✓ created type department_permission_state ('grant', 'block')")

        # ── Step 2: 14 inherited user columns ────────────────────────
        for col in USER_INHERITED_PERMS:
            conn.execute(text(
                f"ALTER TABLE users ADD COLUMN {col}_v2 user_permission_state NOT NULL DEFAULT 'inherit'"
            ))
            conn.execute(text(f"""
                UPDATE users SET {col}_v2 = (CASE
                    WHEN {col} IS NULL THEN 'inherit'
                    WHEN {col} = TRUE THEN 'grant'
                    ELSE 'block'
                END)::user_permission_state
            """))
            conn.execute(text(f"ALTER TABLE users DROP COLUMN {col}"))
            conn.execute(text(f"ALTER TABLE users RENAME COLUMN {col}_v2 TO {col}"))
            print(f"  ✓ users.{col}: BOOLEAN NULL → user_permission_state")

        # ── Step 3: view_sensitive_customers (no inheritance fallback) ─
        for col in USER_NON_INHERITED_PERMS:
            conn.execute(text(
                f"ALTER TABLE users ADD COLUMN {col}_v2 user_permission_state NOT NULL DEFAULT 'block'"
            ))
            # NULL maps to 'block' here (not 'inherit') because there is no
            # department-side column to fall back to.
            conn.execute(text(f"""
                UPDATE users SET {col}_v2 = (CASE
                    WHEN {col} IS NULL THEN 'block'
                    WHEN {col} = TRUE THEN 'grant'
                    ELSE 'block'
                END)::user_permission_state
            """))
            conn.execute(text(f"ALTER TABLE users DROP COLUMN {col}"))
            conn.execute(text(f"ALTER TABLE users RENAME COLUMN {col}_v2 TO {col}"))
            print(f"  ✓ users.{col}: BOOLEAN NULL → user_permission_state (no inherit fallback)")

        # ── Step 4: 14 department columns ────────────────────────────
        for col in DEPT_PERMS:
            conn.execute(text(
                f"ALTER TABLE departments ADD COLUMN {col}_v2 department_permission_state NOT NULL DEFAULT 'block'"
            ))
            conn.execute(text(f"""
                UPDATE departments SET {col}_v2 = (CASE
                    WHEN {col} = TRUE THEN 'grant'
                    ELSE 'block'
                END)::department_permission_state
            """))
            conn.execute(text(f"ALTER TABLE departments DROP COLUMN {col}"))
            conn.execute(text(f"ALTER TABLE departments RENAME COLUMN {col}_v2 TO {col}"))
            print(f"  ✓ departments.{col}: BOOLEAN NOT NULL → department_permission_state")


if __name__ == "__main__":
    print("Running migration 048: Permission columns to ENUM...")
    run()
    print("Migration 048 complete.")
