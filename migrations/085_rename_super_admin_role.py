"""Migration 085: rename the top role value justin_admin to super_admin.

The role was named after the one person who held it; the label shown in the
app was already "Super Admin". The code in the same commit only knows
super_admin, so on an existing database every user holding the old value
must be moved before the app restarts, or they lose their top tier.

This UPDATEs public.users.role and nothing else. Dry run by default: prints
the users that would change. --apply runs the UPDATE in one transaction and
checks no old value remains. A fresh install has no rows to change.

Run inside the app container:
    docker compose exec -T app python migrations/085_rename_super_admin_role.py
    docker compose exec -T app python migrations/085_rename_super_admin_role.py --apply
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

OLD, NEW = "justin_admin", "super_admin"


def main(apply: bool) -> None:
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, username FROM users WHERE role = :old ORDER BY id"), {"old": OLD}).all()
        for uid, username in rows:
            print("would change: user " + str(uid) + " (" + username + ")")
        if not rows:
            print("ALREADY APPLIED: no user holds role " + OLD)
            return
        if not apply:
            print("dry run: " + str(len(rows)) + " user(s); rerun with --apply")
            return
        changed = conn.execute(text(
            "UPDATE users SET role = :new WHERE role = :old"), {"new": NEW, "old": OLD}).rowcount
        left = conn.execute(text("SELECT count(*) FROM users WHERE role = :old"), {"old": OLD}).scalar()
        if changed != len(rows) or left:
            raise SystemExit("ABORT: changed " + str(changed) + " of " + str(len(rows))
                             + ", " + str(left) + " left; rolled back")
        print("changed " + str(changed) + " user(s) to " + NEW)


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
