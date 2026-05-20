"""CLI script to create initial admin user accounts.

Run once during setup:
    python -m scripts.create_admin_user

Or from the hardware_inventory directory:
    python scripts/create_admin_user.py
"""

import sys
from pathlib import Path

# Add parent to path so we can import the app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import SessionLocal, create_all_tables  # noqa: E402
from app.auth import create_user, hash_password  # noqa: E402
from app.models import User  # noqa: E402


def main():
    print("=== Company Hardware Inventory - User Setup ===")
    print()

    create_all_tables()
    db = SessionLocal()

    try:
        # Initial accounts per plan
        initial_users = [
            ("justin", "Justin Varughese", "admin"),
            ("nico", "Nico", "editor"),
            ("chris", "Chris", "editor"),
        ]

        for username, display_name, role in initial_users:
            existing = db.query(User).filter(User.username == username).first()
            if existing:
                print(f"  [SKIP] User '{username}' already exists (role={existing.role})")
                continue

            # Prompt for password
            import getpass
            password = getpass.getpass(f"  Password for {username} ({role}): ")
            if not password:
                print(f"  [SKIP] No password entered for '{username}'")
                continue

            user = create_user(db, username, display_name, password, role)
            print(f"  [OK] Created user '{username}' (role={role}, id={user.id})")

        print()
        print("Done. Users can now log in at /login")

    finally:
        db.close()


if __name__ == "__main__":
    main()
