"""054 - Retire legacy install_certification table (orphan from 050).

Drops install_certification, created by 050 but never wired to any route,
template, or registry. It encoded an earlier in-app-checklist design that was
superseded by the ratified PDF-as-certificate model in installation_certification
(053). Had 0 rows and 0 consumers at retirement. Idempotent.

Run:
    docker compose exec app python migrations/054_drop_install_certification.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    "DROP TABLE IF EXISTS install_certification CASCADE",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("054 done: install_certification dropped (was 0 rows, 0 consumers)")


if __name__ == "__main__":
    run()
