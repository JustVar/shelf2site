"""Migration: Add forced password change fields to users table.

Adds:
- must_change_password: Boolean, default TRUE (forces password change on first login)
- password_changed_at: DateTime, nullable (tracks last password change)

All existing users except justin_admin get must_change_password=TRUE so they
are prompted to set their own password on next login.

Run this migration on the NUC with:
    cd /opt/hardware_inventory
    source venv/bin/activate
    python migrations/009_add_must_change_password.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run_migration():
    """Add must_change_password and password_changed_at columns."""

    with engine.begin() as conn:
        # Add must_change_password (default TRUE so existing users get prompted)
        try:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT TRUE"
            ))
            print("  Added column: users.must_change_password (default TRUE)")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("  Column users.must_change_password already exists, skipping")
            else:
                raise

        # Add password_changed_at
        try:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP NULL"
            ))
            print("  Added column: users.password_changed_at")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("  Column users.password_changed_at already exists, skipping")
            else:
                raise

        # Exempt justin_admin accounts from forced change
        result = conn.execute(text(
            "UPDATE users SET must_change_password = FALSE WHERE role = 'justin_admin'"
        ))
        print(f"  Exempted {result.rowcount} justin_admin account(s) from forced password change")

    print("\nMigration 009 complete: forced password change fields added.")


if __name__ == "__main__":
    print("Running migration 009: Add must_change_password fields...")
    run_migration()
