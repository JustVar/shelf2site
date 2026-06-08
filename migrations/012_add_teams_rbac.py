"""Migration: Add team-based RBAC system.

Creates:
- teams table with 14 permission flag columns
- team_id FK on users
- 2 new provisioning permission columns on users
- Converts existing 13 user permission columns from NOT NULL to nullable (three-state)
- Seeds 5 default teams: Product Management, Support, QA, Hardware, Sales Engineering

Three-state permissions:
- NULL = inherit from team (default after migration)
- True = force ON (user override)
- False = force OFF (user override)

Run on the server:
    cd /opt/asset_tracker
    source venv/bin/activate
    python migrations/012_add_teams_rbac.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


# Existing permission columns that need to become nullable
EXISTING_PERM_COLUMNS = [
    "can_view_financial",
    "can_manage_warranty",
    "can_manage_trials",
    "can_manage_procurement",
    "can_manage_sites",
    "can_manage_users",
    "can_manage_system",
    "can_view_audit_log",
    "can_access_receiving",
    "can_access_map",
    "can_access_disposal",
    "can_access_credentials",
]

# New columns to add to users table
NEW_USER_COLUMNS = [
    ("team_id", "INTEGER REFERENCES teams(id) ON DELETE SET NULL"),
    ("can_manage_provisioning", "BOOLEAN DEFAULT NULL"),
    ("can_view_provisioning", "BOOLEAN DEFAULT NULL"),
]

# Team seed data: (name, description, {permission_flags})
TEAM_SEEDS = [
    (
        "Product Management",
        "Product managers — financial, warranty, trials, procurement, sites, user management, audit, map, disposal, provisioning",
        {
            "can_view_financial": True,
            "can_manage_warranty": True,
            "can_manage_trials": True,
            "can_manage_procurement": True,
            "can_manage_sites": True,
            "can_manage_users": True,
            "can_view_audit_log": True,
            "can_access_map": True,
            "can_access_disposal": True,
            "can_manage_provisioning": True,
        },
    ),
    (
        "Support",
        "Support team — warranty, sites, audit, map, disposal, provisioning",
        {
            "can_manage_warranty": True,
            "can_manage_sites": True,
            "can_view_audit_log": True,
            "can_access_map": True,
            "can_access_disposal": True,
            "can_manage_provisioning": True,
        },
    ),
    (
        "QA",
        "QA team — audit, receiving, map, disposal, provisioning",
        {
            "can_view_audit_log": True,
            "can_access_receiving": True,
            "can_access_map": True,
            "can_access_disposal": True,
            "can_manage_provisioning": True,
        },
    ),
    (
        "Hardware",
        "Hardware team — warranty, trials, procurement, sites, audit, receiving, map, disposal, provisioning",
        {
            "can_manage_warranty": True,
            "can_manage_trials": True,
            "can_manage_procurement": True,
            "can_manage_sites": True,
            "can_view_audit_log": True,
            "can_access_receiving": True,
            "can_access_map": True,
            "can_access_disposal": True,
            "can_manage_provisioning": True,
        },
    ),
    (
        "Sales Engineering",
        "Sales engineers — audit, map, provisioning (view-only)",
        {
            "can_view_audit_log": True,
            "can_access_map": True,
            "can_view_provisioning": True,
        },
    ),
]


def run_migration():
    """Add teams table, team_id to users, three-state permissions, seed teams."""

    with engine.begin() as conn:
        # ---------------------------------------------------------------
        # 1. Create teams table
        # ---------------------------------------------------------------
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS teams (
                id SERIAL PRIMARY KEY,
                name VARCHAR(64) UNIQUE NOT NULL,
                description TEXT,
                can_view_financial BOOLEAN NOT NULL DEFAULT FALSE,
                can_manage_warranty BOOLEAN NOT NULL DEFAULT FALSE,
                can_manage_trials BOOLEAN NOT NULL DEFAULT FALSE,
                can_manage_procurement BOOLEAN NOT NULL DEFAULT FALSE,
                can_manage_sites BOOLEAN NOT NULL DEFAULT FALSE,
                can_manage_users BOOLEAN NOT NULL DEFAULT FALSE,
                can_manage_system BOOLEAN NOT NULL DEFAULT FALSE,
                can_view_audit_log BOOLEAN NOT NULL DEFAULT FALSE,
                can_access_receiving BOOLEAN NOT NULL DEFAULT FALSE,
                can_access_map BOOLEAN NOT NULL DEFAULT FALSE,
                can_access_disposal BOOLEAN NOT NULL DEFAULT FALSE,
                can_access_credentials BOOLEAN NOT NULL DEFAULT FALSE,
                can_manage_provisioning BOOLEAN NOT NULL DEFAULT FALSE,
                can_view_provisioning BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        print("  Created table: teams")

        # ---------------------------------------------------------------
        # 2. Add new columns to users table
        # ---------------------------------------------------------------
        for col_name, col_def in NEW_USER_COLUMNS:
            try:
                conn.execute(text(
                    f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"
                ))
                print(f"  Added column: users.{col_name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                    print(f"  Column users.{col_name} already exists, skipping")
                else:
                    raise

        # ---------------------------------------------------------------
        # 3. Convert existing boolean columns to nullable (three-state)
        #    First drop NOT NULL, then set FALSE → NULL (inherit from team)
        # ---------------------------------------------------------------
        for col in EXISTING_PERM_COLUMNS:
            # Drop NOT NULL constraint and change default to NULL FIRST
            conn.execute(text(
                f"ALTER TABLE users ALTER COLUMN {col} DROP NOT NULL"
            ))
            conn.execute(text(
                f"ALTER TABLE users ALTER COLUMN {col} SET DEFAULT NULL"
            ))
            print(f"  Made nullable: users.{col}")

            # Now set FALSE values to NULL (will inherit from team)
            result = conn.execute(text(
                f"UPDATE users SET {col} = NULL WHERE {col} = FALSE"
            ))
            print(f"  Converted {result.rowcount} FALSE→NULL for users.{col}")

        # ---------------------------------------------------------------
        # 4. Seed default teams
        # ---------------------------------------------------------------
        all_perm_cols = EXISTING_PERM_COLUMNS + ["can_manage_provisioning", "can_view_provisioning"]

        for team_name, team_desc, perms in TEAM_SEEDS:
            # Check if already exists
            exists = conn.execute(
                text("SELECT id FROM teams WHERE name = :name"),
                {"name": team_name},
            ).fetchone()
            if exists:
                print(f"  Team '{team_name}' already exists, skipping")
                continue

            col_names = ["name", "description"] + all_perm_cols
            col_vals = [team_name, team_desc] + [perms.get(c, False) for c in all_perm_cols]
            placeholders = ", ".join([f":v{i}" for i in range(len(col_vals))])
            col_list = ", ".join(col_names)
            params = {f"v{i}": v for i, v in enumerate(col_vals)}

            conn.execute(text(f"INSERT INTO teams ({col_list}) VALUES ({placeholders})"), params)
            print(f"  Seeded team: {team_name}")

        # ---------------------------------------------------------------
        # 5. Index for team lookups
        # ---------------------------------------------------------------
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_users_team_id ON users (team_id)
        """))
        print("  Created index: idx_users_team_id")

    print("\nMigration 012 complete: teams RBAC system added.")


if __name__ == "__main__":
    print("Running migration 012: Add teams RBAC...")
    run_migration()
