"""046 — Create maintenance_log table.

Tracks inspections, repairs, and component install/uninstall/move events
linked to any device, with optional FK to device_components.
"""

from sqlalchemy import text


def upgrade(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS maintenance_log (
                id                SERIAL PRIMARY KEY,
                device_table      VARCHAR(50)     NOT NULL,
                device_id         INTEGER         NOT NULL,
                entry_type        VARCHAR(50)     NOT NULL,
                description       TEXT            NOT NULL,
                performed_by      VARCHAR(100)    NOT NULL,
                maintenance_date  DATE            NOT NULL DEFAULT CURRENT_DATE,
                component_id      INTEGER,
                created_by        VARCHAR(100)    NOT NULL,
                created_at        TIMESTAMP       DEFAULT NOW(),
                CONSTRAINT fk_maintenance_component
                    FOREIGN KEY (component_id)
                    REFERENCES device_components (id)
                    ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_maintenance_device
                ON maintenance_log (device_table, device_id);

            CREATE INDEX IF NOT EXISTS idx_maintenance_component
                ON maintenance_log (component_id);
        """))


def downgrade(engine):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS maintenance_log;"))
