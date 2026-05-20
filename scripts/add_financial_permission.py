"""Add can_view_financial permission to users table.

This migration adds a boolean column to control access to financial/procurement data.
- Admins automatically get this permission (set to True)
- All other users default to False

Usage:
    python scripts/add_financial_permission.py
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Ensure repo root is on sys.path (for absolute imports)
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.database import engine


def add_financial_permission():
    """Add can_view_financial column to users table."""

    print("Adding can_view_financial permission to users table...")
    print("=" * 60)

    with engine.begin() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users'
            AND column_name = 'can_view_financial'
        """))

        if result.fetchone():
            print("✓ Column 'can_view_financial' already exists, skipping migration.")
            return

        # Add the column with default value False
        print("Adding column: can_view_financial (boolean, default=False)...")
        conn.execute(text("""
            ALTER TABLE users
            ADD COLUMN can_view_financial BOOLEAN NOT NULL DEFAULT FALSE
        """))

        print("✓ Column added successfully")

        # Set to True for all admin users
        print("\nGranting financial access to admin users...")
        result = conn.execute(text("""
            UPDATE users
            SET can_view_financial = TRUE
            WHERE role = 'admin'
        """))
        admin_count = result.rowcount
        print(f"✓ {admin_count} admin user(s) granted financial access")

        # Show summary
        result = conn.execute(text("""
            SELECT role, COUNT(*) as count
            FROM users
            GROUP BY role
        """))
        print("\nUser summary:")
        for row in result:
            print(f"  - {row.role}: {row.count} user(s)")

    print("\n" + "=" * 60)
    print("✅ Migration complete!")
    print("\nFinancial data access:")
    print("  - Admins: Automatically granted")
    print("  - Others: Use User Management page to grant access")


if __name__ == "__main__":
    add_financial_permission()
