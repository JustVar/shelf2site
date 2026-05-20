"""045 — Create receipts table.

Stores purchase receipts and sale/disposal records linked to any device.
"""

from sqlalchemy import text


def upgrade(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS receipts (
                id                SERIAL PRIMARY KEY,
                device_table      VARCHAR(50)     NOT NULL,
                device_id         INTEGER         NOT NULL,
                record_type       VARCHAR(20)     NOT NULL,
                amount            NUMERIC(10,2)   NOT NULL,
                transaction_date  DATE            NOT NULL,
                file_path         VARCHAR(500),
                original_filename VARCHAR(255),
                notes             TEXT,
                created_by        VARCHAR(100)    NOT NULL,
                created_at        TIMESTAMP       DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_receipts_device
                ON receipts (device_table, device_id);
        """))


def downgrade(engine):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS receipts;"))
