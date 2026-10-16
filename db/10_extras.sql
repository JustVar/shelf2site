-- Runs AFTER the tables are created from app/models.py.
-- Everything here is a database object the models cannot express. Each one
-- names the migration that created it on the original install, so the two
-- paths stay comparable. Every statement is safe to run again.

-- edit_locks (migration 043): app/locks.py reads and writes it with raw SQL;
-- it has no model.
CREATE TABLE IF NOT EXISTS public.edit_locks (
    resource_key   VARCHAR(128) PRIMARY KEY,
    user_id        INTEGER NOT NULL,
    username       VARCHAR(128) NOT NULL,
    display_name   VARCHAR(256) NOT NULL,
    level          VARCHAR(16) NOT NULL DEFAULT 'viewing',
    acquired_at    DOUBLE PRECISION NOT NULL,
    last_activity  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_edit_locks_user_id ON public.edit_locks (user_id);

-- error_log (migration 044): app/routes/error_routes.py uses raw SQL; no model.
CREATE TABLE IF NOT EXISTS public.error_log (
    id           SERIAL PRIMARY KEY,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT now(),
    source       VARCHAR(16) NOT NULL DEFAULT 'frontend',
    level        VARCHAR(16) NOT NULL DEFAULT 'error',
    message      TEXT NOT NULL,
    stack        TEXT,
    url          VARCHAR(512),
    user_id      INTEGER,
    username     VARCHAR(128),
    browser      VARCHAR(256),
    context      JSONB,
    fingerprint  VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS ix_error_log_fingerprint ON public.error_log (fingerprint);

-- csv_import_map (migration 067): import provenance, (source, csv_id) to the
-- item it created. A delete request clears the item link here
-- (app/delete_requests.py).
CREATE TABLE IF NOT EXISTS item_schema.csv_import_map (
    source      VARCHAR(128) NOT NULL,
    csv_id      INTEGER      NOT NULL,
    item_id     INTEGER,
    action      VARCHAR(64)  NOT NULL,
    imported_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (source, csv_id)
);

-- location_types: the validated list of place types (original db_init).
CREATE TABLE IF NOT EXISTS item_schema.location_types (
    id          SERIAL PRIMARY KEY,
    type_name   VARCHAR(100) UNIQUE NOT NULL,
    created_by  VARCHAR(100),
    created_at  DATE DEFAULT ((now() AT TIME ZONE 'America/Chicago'))::date
);

-- item_schema.intake_photos: delete-request preflight counts it
-- (app/delete_requests.py). Original db_init.
CREATE TABLE IF NOT EXISTS item_schema.intake_photos (
    id                  SERIAL PRIMARY KEY,
    item_id             INTEGER REFERENCES item_schema.items(id),
    receiving_event_id  INTEGER,
    filename            VARCHAR(255) NOT NULL,
    original_filename   VARCHAR(255),
    content_type        VARCHAR(100),
    file_size           INTEGER,
    caption             VARCHAR(255),
    uploaded_by         VARCHAR(100),
    created_at          DATE DEFAULT ((now() AT TIME ZONE 'America/Chicago'))::date
);
CREATE INDEX IF NOT EXISTS idx_intake_photos_item ON item_schema.intake_photos (item_id);

-- The containment read path (migration 065): the latest event per component,
-- present only while installed or moved. Same-day pairs tie-break on id.
CREATE OR REPLACE VIEW item_schema.current_containment AS
SELECT component_item_id, parent_item_id, slot_label, installed_date, event_id
FROM (
    SELECT DISTINCT ON (ch.item_id)
        ch.item_id      AS component_item_id,
        ch.parent_item_id,
        ch.slot_label,
        ch.action_date  AS installed_date,
        ch.action,
        ch.id           AS event_id
    FROM item_schema.component_history ch
    ORDER BY ch.item_id, ch.action_date DESC, ch.id DESC
) latest
WHERE latest.action IN ('installed', 'moved')
  AND latest.parent_item_id IS NOT NULL;

-- One open checkout per item (original db_init, checkouts C1).
CREATE UNIQUE INDEX IF NOT EXISTS checkouts_one_open_per_item
    ON item_schema.checkouts (item_id) WHERE checkin_date IS NULL;

-- One pending delete request per target (migration 078).
CREATE UNIQUE INDEX IF NOT EXISTS uq_delete_requests_one_pending
    ON public.delete_requests (target_table, target_id) WHERE status = 'pending';

-- CHECK constraints (migrations 022, 023, 074, 078).
DO $$
DECLARE
    checks text[][] := ARRAY[
        ['oem_purchase_orders', 'oem_status_check',
         'status IN (''ordered'', ''in_production'', ''acceptance'', ''receiving'', ''verified'', ''cancelled'')'],
        ['deployment_records', 'deployment_status_check',
         'status IN (''scheduled'', ''in_transit'', ''on_site'', ''installing'', ''complete'', ''cancelled'')'],
        ['customer_orders', 'customer_orders_owner_partner_check',
         '(owner = ''oem'') = (oem_partner_id IS NOT NULL)'],
        ['delete_requests', 'ck_delete_requests_target',
         'target_table IN (''items'', ''vendor_profiles'')'],
        ['delete_requests', 'ck_delete_requests_status',
         'status IN (''pending'', ''approved'', ''rejected'', ''withdrawn'')'],
        ['delete_requests', 'ck_delete_requests_reason',
         'length(trim(reason)) > 0']
    ];
    i int;
BEGIN
    FOR i IN 1 .. array_length(checks, 1) LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = checks[i][2]) THEN
            EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (%s)',
                           checks[i][1], checks[i][2], checks[i][3]);
        END IF;
    END LOOP;
END
$$;

-- Lookup indexes the original migrations added for the busiest reads.
CREATE INDEX IF NOT EXISTS idx_items_category    ON item_schema.items (item_category);
CREATE INDEX IF NOT EXISTS idx_items_status      ON item_schema.items (item_status);
CREATE INDEX IF NOT EXISTS idx_items_location    ON item_schema.items (location_id);
CREATE INDEX IF NOT EXISTS idx_items_item_sku ON item_schema.items (item_sku);
CREATE INDEX IF NOT EXISTS idx_items_vendor      ON item_schema.items (vendor_id);
CREATE INDEX IF NOT EXISTS idx_component_history_item   ON item_schema.component_history (item_id);
CREATE INDEX IF NOT EXISTS idx_component_history_parent ON item_schema.component_history (parent_item_id);
CREATE INDEX IF NOT EXISTS idx_checkouts_item ON item_schema.checkouts (item_id);
CREATE INDEX IF NOT EXISTS idx_customer_orders_status ON public.customer_orders (status);
CREATE INDEX IF NOT EXISTS ix_deployment_records_customer_order_id ON public.deployment_records (customer_order_id);
CREATE INDEX IF NOT EXISTS idx_provisioning_stage ON public.device_provisioning (current_stage) WHERE NOT is_complete;
CREATE INDEX IF NOT EXISTS ix_error_log_created_at ON public.error_log (created_at);
