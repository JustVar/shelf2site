"""062: create map_visibility — server-side map curation flags.

The deployment map redesign lets editors hide customers, sites, or single
units from the map (and from every metric derived from it). Customer and
site identities are free-text strings across the schema, so curation rows
key on the normalized string; units key on 'item:{id}' / 'edge_box:{id}'
because item_schema items carry no per-unit map flag column (the legacy
edge_boxes.show_on_map boolean is still honored in addition).

A row's presence means HIDDEN; unhide deletes the row. Absence = visible.

Idempotent: CREATE TABLE / CREATE INDEX use IF NOT EXISTS throughout.

Run:
    docker compose exec app python migrations/062_create_map_visibility.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS map_visibility (
        id serial PRIMARY KEY,
        level varchar(16) NOT NULL,
        key varchar(512) NOT NULL,
        label varchar(512),
        hidden_by varchar(128),
        created_at timestamp NOT NULL DEFAULT now(),
        CONSTRAINT uq_map_visibility_level_key UNIQUE (level, key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_map_visibility_level ON map_visibility (level)",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("062 done: map_visibility table created (presence of a row = hidden)")


if __name__ == "__main__":
    print("Running migration 062: create map_visibility")
    run()
    print("Migration 062 complete.")
