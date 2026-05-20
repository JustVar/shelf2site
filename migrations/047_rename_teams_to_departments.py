"""Migration: Rename `teams` table to `departments` and `users.team_id` to `department_id`.

The `teams` concept is being renamed to `departments` for clarity (it always was
"who owns this asset / which org-unit do you belong to", not a team in the chat
sense). Pure rename — no schema or permission changes.

Changes:
- `teams` -> `departments` (table). PG auto-renames pkey + unique-name index. The implicit SERIAL sequence is NOT auto-renamed by ALTER TABLE; we explicitly rename it via ALTER SEQUENCE.
- `users.team_id` -> `users.department_id` (column).
- FK constraint `users_team_id_fkey` -> `users_department_id_fkey` (cosmetic).
- User-named index `idx_users_team_id` -> `idx_users_department_id` (must be explicit;
  not auto-renamed because it's user-named).

Idempotent — wrapped in a single transaction.

Run instructions:
    docker compose exec app python migrations/047_rename_teams_to_departments.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.begin() as conn:
        # 1. Table rename — also auto-renames teams_pkey, teams_name_key, teams_id_seq.
        conn.execute(text("ALTER TABLE teams RENAME TO departments"))
        print("  ✓ teams -> departments (and pkey / name_key / id_seq auto-renamed)")

        # 2. Column rename on users.
        conn.execute(text("ALTER TABLE users RENAME COLUMN team_id TO department_id"))
        print("  ✓ users.team_id -> users.department_id")

        # 3. FK constraint name (cosmetic — Postgres keeps the constraint working
        #    under the old name, but matching the new column reduces confusion).
        conn.execute(text(
            "ALTER TABLE users RENAME CONSTRAINT users_team_id_fkey "
            "TO users_department_id_fkey"
        ))
        print("  ✓ FK constraint renamed: users_team_id_fkey -> users_department_id_fkey")

        # 4. User-named index does NOT auto-rename — has to be explicit.
        conn.execute(text(
            "ALTER INDEX idx_users_team_id RENAME TO idx_users_department_id"
        ))
        print("  ✓ Index renamed: idx_users_team_id -> idx_users_department_id")

        # 5. The implicit SERIAL sequence (teams_id_seq) is NOT auto-renamed by
        #    ALTER TABLE — has to be explicit. Cosmetic only; nextval() works
        #    either way because the column default holds the sequence OID.
        conn.execute(text("ALTER SEQUENCE teams_id_seq RENAME TO departments_id_seq"))
        print("  ✓ Sequence renamed: teams_id_seq -> departments_id_seq")


if __name__ == "__main__":
    print("Running migration 047: Rename teams -> departments...")
    run()
    print("Migration 047 complete.")
