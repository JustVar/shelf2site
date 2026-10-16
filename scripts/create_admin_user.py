"""Create the first admin account on a new install.

The app has no sign-up page: every other account is created by an admin on
the Users page. The new admin must change the password on first sign-in.

    python -m scripts.create_admin_user USERNAME "Display Name"
    docker compose exec app python -m scripts.create_admin_user USERNAME "Display Name"

The password is asked for twice and must pass the password rules
(validate_password_strength in app/auth.py).
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import create_user, validate_password_strength  # noqa: E402
from app.database import SessionLocal, create_all_tables  # noqa: E402
from app.models import ADMIN_LEVEL_ROLES, User  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create the first admin account.")
    parser.add_argument("username")
    parser.add_argument("display_name", nargs="?", default=None)
    parser.add_argument("--role", default=ADMIN_LEVEL_ROLES[0], choices=list(ADMIN_LEVEL_ROLES))
    args = parser.parse_args(argv)

    create_all_tables()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == args.username).first():
            print(f"User '{args.username}' already exists; nothing changed.")
            return 1
        password = getpass.getpass(f"Password for {args.username}: ")
        problem = validate_password_strength(password, username=args.username)
        if problem:
            print("Password rejected: " + problem)
            return 1
        if getpass.getpass("Repeat the password: ") != password:
            print("The passwords do not match; nothing changed.")
            return 1
        user = create_user(db, args.username, args.display_name or args.username, password, args.role)
        print(f"Created '{user.username}' (role {user.role}). Sign in at /login.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
