-- =============================================================================
-- Asset Tracker Schema v2
-- the company — Hardware Asset Tracker
-- Generated: 2026-03-30
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS item_schema;

-- =============================================================================
-- ENUMS
-- =============================================================================

CREATE TYPE item_categories AS ENUM (
    'access_control',
    'camera',
    'computer',
    'cpu',
    'motherboard',
    'gpu',
    'ram',
    'storage_drive',
    'psu',
    'cpu_cooler',
    'case_fan',
    'pci',
    'product_cabling',
    'consumables',
    'edge_box',
    'ups',
    'mobile_device',
    'monitor',
    'network',
    'office_equipment',
    'pc_accessories',
    'camera_c2c',
    'cloud_box'
);

CREATE TYPE item_statuses AS ENUM (
    'Deployed',
    'Ready to Deploy',
    'Pending',
    'Un-deployable',
    'Decommissioned',
    'Unassigned'
);

-- =============================================================================
-- REFERENCE / VALIDATION TABLES
-- =============================================================================

-- location_types: validated list of location types
-- Prevents free-text drift (e.g. 15 versions of 'Hardware')
-- Add new types here via UI (admin only) rather than migration
CREATE TABLE IF NOT EXISTS item_schema.location_types (
    id          SERIAL PRIMARY KEY,
    type_name   VARCHAR(100) UNIQUE NOT NULL,  -- e.g. Internal, Customer, Pilot, R&D, Storage
    created_by  VARCHAR(100),
    created_at  DATE DEFAULT CURRENT_DATE
);

-- Seed data for location_types
INSERT INTO item_schema.location_types (type_name, created_by) VALUES
    ('Internal',  'system'),
    ('Customer',  'system'),
    ('Pilot',     'system'),
    ('R&D',       'system'),
    ('Storage',   'system')
ON CONFLICT (type_name) DO NOTHING;

-- =============================================================================
-- LOCATIONS (replaces and consolidates the sites table)
-- Covers internal office, customer sites, pilot sites, R&D, storage
-- =============================================================================

CREATE TABLE IF NOT EXISTS item_schema.locations (
    id               SERIAL PRIMARY KEY,
    nickname         VARCHAR(255) NOT NULL,                          -- Required display name
    location_type    VARCHAR(100) REFERENCES item_schema.location_types(type_name),
    address_line_1   VARCHAR(255),
    address_line_2   VARCHAR(255),
    city             VARCHAR(100),
    state            VARCHAR(100),
    zip              VARCHAR(20),
    country          VARCHAR(100) DEFAULT 'United States',
    is_international BOOLEAN      DEFAULT FALSE,                     -- Drives US vs foreign address UI
    geo_lat          DOUBLE PRECISION,                               -- Latitude for map plotting
    geo_lng          DOUBLE PRECISION,                               -- Longitude for map plotting
    show_on_map      BOOLEAN      DEFAULT FALSE,
    contact_name     VARCHAR(255),
    contact_email    VARCHAR(255),
    contact_phone    VARCHAR(50),
    customer         VARCHAR(255),                                   -- Populated for customer/pilot sites
    is_active        BOOLEAN      DEFAULT TRUE,
    notes            TEXT,
    created_at       DATE         DEFAULT CURRENT_DATE,
    last_updated     DATE         DEFAULT CURRENT_DATE
);

-- =============================================================================
-- PART NUMBERS
-- SKU = product family (e.g. EDGE10-NR)
-- PN  = unique unit    (e.g. EDGE10-NR-000001)
-- Casey owns the PN scheme and assignment
-- =============================================================================

CREATE TABLE IF NOT EXISTS item_schema.part_numbers (
    id              SERIAL PRIMARY KEY,
    brand_sku     VARCHAR(512) UNIQUE NOT NULL,   -- Product family identifier
    sku_description TEXT,
    item_category   item_categories,
    is_legacy       BOOLEAN DEFAULT FALSE,           -- Legacy SKUs predating the PN scheme
    is_customer_pn  BOOLEAN DEFAULT FALSE,           -- Customer-facing PN
    location_id     INTEGER REFERENCES item_schema.locations(id),
    created_by      VARCHAR(100),
    created_at      DATE    DEFAULT CURRENT_DATE,
    notes           TEXT
);

-- =============================================================================
-- ITEMS (core inventory table)
-- Replaces all 17 device inventory tables and 7 PC component tables
-- =============================================================================

CREATE TABLE IF NOT EXISTS item_schema.items (
    id                          SERIAL PRIMARY KEY,
    item_name                   TEXT,
    item_manufacturer           VARCHAR(1024),
    item_model                  VARCHAR(1024),
    item_sn                     VARCHAR(512),
    item_category               item_categories,
    item_status                 item_statuses,
    location_id                 INTEGER          REFERENCES item_schema.locations(id),
    department_or_owner         VARCHAR(1024),
    item_mac_address_1          MACADDR,
    item_mac_address_2          MACADDR,
    item_storage_size_gb        REAL,                                -- GB as base unit
    appliance_uuid                 VARCHAR(512),
    brand_sku                 VARCHAR(512)     REFERENCES item_schema.part_numbers(brand_sku),
    brand_pn                  VARCHAR(512),                        -- Unit-level PN (e.g. PVA-25-30SFF-000001)
    item_associated_brand_pn  VARCHAR(512),                        -- Parent device/component PN
    vendor_id                   INTEGER,                             -- FK to vendor_profiles (future)
    item_vendor                 VARCHAR(1024),
    date_purchased              DATE,
    intended_purpose            VARCHAR(1024),
    dispatched_date             DATE,
    tracking_number             VARCHAR(512),
    notes                       TEXT,
    created_at                  DATE             DEFAULT CURRENT_DATE,
    last_updated                DATE             DEFAULT CURRENT_DATE,
    attributes                  JSONB
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_items_category    ON item_schema.items (item_category);
CREATE INDEX IF NOT EXISTS idx_items_status      ON item_schema.items (item_status);
CREATE INDEX IF NOT EXISTS idx_items_location    ON item_schema.items (location_id);
CREATE INDEX IF NOT EXISTS idx_items_brand_sku ON item_schema.items (brand_sku);
CREATE INDEX IF NOT EXISTS idx_items_brand_pn  ON item_schema.items (brand_pn);
CREATE INDEX IF NOT EXISTS idx_items_vendor      ON item_schema.items (vendor_id);

-- =============================================================================
-- COMPONENT HISTORY (replaces device_components)
-- Tracks install / uninstall / move events for components
-- =============================================================================

CREATE TYPE component_actions AS ENUM (
    'installed',
    'uninstalled',
    'moved'
);

CREATE TABLE IF NOT EXISTS item_schema.component_history (
    id              SERIAL PRIMARY KEY,
    item_id         INTEGER           NOT NULL REFERENCES item_schema.items(id),  -- The component
    parent_item_id  INTEGER                    REFERENCES item_schema.items(id),  -- The device it went into
    action          component_actions NOT NULL,
    slot_label      VARCHAR(100),              -- e.g. PCIe x16 Slot 1
    action_date     DATE              DEFAULT CURRENT_DATE,
    performed_by    VARCHAR(100),
    notes           TEXT,
    created_at      DATE              DEFAULT CURRENT_DATE
);

CREATE INDEX IF NOT EXISTS idx_component_history_item   ON item_schema.component_history (item_id);
CREATE INDEX IF NOT EXISTS idx_component_history_parent ON item_schema.component_history (parent_item_id);

-- =============================================================================
-- RECEIPTS (revised — per transaction, not per item)
-- One receipt covers one purchase transaction which may include multiple items
-- Tax tracked separately from COG per Morgan's requirement
--
-- FUTURE: Add tax_rates lookup table keyed by state to auto-fill tax_rate
--         and remove manual entry error risk as transaction volume grows
-- =============================================================================

CREATE TABLE IF NOT EXISTS item_schema.receipts (
    id                SERIAL PRIMARY KEY,
    vendor_id         INTEGER,                             -- FK to vendor_profiles (future)
    purchase_order    VARCHAR(100),                -- PO number if applicable
    record_type       VARCHAR(20)      NOT NULL,   -- purchase / sale_disposal
    transaction_date  DATE             NOT NULL,
    subtotal          NUMERIC(10,2)    NOT NULL,   -- Pre-tax total
    tax_rate          NUMERIC(5,4),               -- e.g. 0.0825 for 8.25% — manual entry
    tax_amount        NUMERIC(10,2),              -- Entered manually or derived
    total             NUMERIC(10,2)    NOT NULL,   -- subtotal + tax
    tax_exempt        BOOLEAN          DEFAULT FALSE,  -- For resale or exempt purchases
    file_path         VARCHAR(500),               -- Optional — stored at /data/asset-tracker/receipts/
    original_filename VARCHAR(255),               -- Flagged as missing for audit if null
    notes             TEXT,
    created_by        VARCHAR(100)     NOT NULL,
    created_at        DATE             DEFAULT CURRENT_DATE
);

CREATE INDEX IF NOT EXISTS idx_receipts_vendor ON item_schema.receipts (vendor_id);
CREATE INDEX IF NOT EXISTS idx_receipts_date   ON item_schema.receipts (transaction_date);

-- =============================================================================
-- RECEIPT ITEMS (join table — one receipt → many items)
-- Each unit in inventory is its own item record (Option A)
-- quantity field reflects how many units share the same unit_cog on this receipt
-- but each unit still has its own row in items with its own serial and location
-- =============================================================================

CREATE TABLE IF NOT EXISTS item_schema.receipt_items (
    id          SERIAL PRIMARY KEY,
    receipt_id  INTEGER  NOT NULL REFERENCES item_schema.receipts(id),
    item_id     INTEGER  NOT NULL REFERENCES item_schema.items(id),
    unit_cog    MONEY    NOT NULL,   -- Pre-tax cost for this specific item
    quantity    INTEGER  DEFAULT 1,  -- Units on this receipt line sharing the same COG
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt ON item_schema.receipt_items (receipt_id);
CREATE INDEX IF NOT EXISTS idx_receipt_items_item    ON item_schema.receipt_items (item_id);

-- =============================================================================
-- MAINTENANCE LOG (updated from migration 046)
-- Now uses item_id FK — replaces device_table + device_id polymorphic pattern
-- Any user can create entries
-- =============================================================================

CREATE TABLE IF NOT EXISTS item_schema.maintenance_log (
    id               SERIAL PRIMARY KEY,
    item_id          INTEGER      NOT NULL REFERENCES item_schema.items(id),
    entry_type       VARCHAR(50)  NOT NULL,   -- Inspection / Repair / Component Installed / Component Uninstalled / Component Moved
    description      TEXT         NOT NULL,
    performed_by     VARCHAR(100),
    maintenance_date DATE         DEFAULT CURRENT_DATE,
    component_id     INTEGER      REFERENCES item_schema.component_history(id),  -- Optional link to component event
    created_by       VARCHAR(100) NOT NULL,
    created_at       DATE         DEFAULT CURRENT_DATE
);

CREATE INDEX IF NOT EXISTS idx_maintenance_item      ON item_schema.maintenance_log (item_id);
CREATE INDEX IF NOT EXISTS idx_maintenance_component ON item_schema.maintenance_log (component_id);

-- =============================================================================
-- INTAKE PHOTOS (updated)
-- Now uses item_id FK — replaces device_table + device_id polymorphic pattern
-- =============================================================================

CREATE TABLE IF NOT EXISTS item_schema.intake_photos (
    id                  SERIAL PRIMARY KEY,
    item_id             INTEGER      REFERENCES item_schema.items(id),
    receiving_event_id  INTEGER,                                     -- FK to receiving_events (future)
    filename            VARCHAR(255) NOT NULL,
    original_filename   VARCHAR(255),
    content_type        VARCHAR(100),
    file_size           INTEGER,               -- bytes
    caption             VARCHAR(255),
    uploaded_by         VARCHAR(100),
    created_at          DATE         DEFAULT CURRENT_DATE
);

CREATE INDEX IF NOT EXISTS idx_intake_photos_item ON item_schema.intake_photos (item_id);

-- =============================================================================
-- END OF SCHEMA
-- =============================================================================
-- Tables NOT included here (unchanged, remain in public schema):
--   users, teams, vendor_profiles, audit_log, error_log
--   customer_orders, deployment_records, receiving_events
--   device_credentials, device_warranties, warranty_claims
--   notifications, notification_subscriptions, edit_locks
--   pending_devices, oui_allowlist, intune_sync_log
-- =============================================================================


-- =============================================================================
-- SEED DATA
-- =============================================================================

-- Location types (already seeded via INSERT in schema, included here for reference)

-- Locations
INSERT INTO item_schema.locations (nickname, location_type, address_line_1, address_line_2, city, state, zip)
VALUES
    ('QA Office',       'Internal', '100 Example Way', 'Suite 700', 'Dallas', 'TX', '75226'),
    ('Hardware Office', 'Internal', '100 Example Way', 'Suite 700', 'Dallas', 'TX', '75226'),
    ('Lab Office','Internal', '100 Example Way', 'Suite 700', 'Dallas', 'TX', '75226')
ON CONFLICT DO NOTHING;

-- Part Numbers (Legacy SKUs is_legacy=true, Current SKUs is_legacy=false)
INSERT INTO item_schema.part_numbers (brand_sku, sku_description, item_category, is_legacy)
VALUES
    ('PVA-25-30R5',  '25 Channel, 30xdays of storage, Raid5',  'edge_box', true),
    ('PVA-25-60R5',  '25 Channel, 60xdays of storage, Raid5',  'edge_box', true),
    ('PVA-25-90R5',  '25 Channel, 90xdays of storage, Raid5',  'edge_box', true),
    ('PVA-50-30R5',  '50 Channel, 30xdays of storage, Raid5',  'edge_box', true),
    ('PVA-50-60R5',  '50 Channel, 60xdays of storage, Raid5',  'edge_box', true),
    ('PVA-50-90R5',  '50 Channel, 90xdays of storage, Raid5',  'edge_box', true),
    ('PVA-75-30R5',  '75 Channel, 30xdays of storage, Raid5',  'edge_box', true),
    ('PVA-75-60R5',  '75 Channel, 60xdays of storage, Raid5',  'edge_box', true),
    ('PVA-75-90R5',  '75 Channel, 90xdays of storage, Raid5',  'edge_box', true),
    ('PVA-100-30R5', '100 Channel, 30xdays of storage, Raid5', 'edge_box', true),
    ('PVA-100-60R5', '100 Channel, 60xdays of storage, Raid5', 'edge_box', true),
    ('PVA-100-90R5', '100 Channel, 90xdays of storage, Raid5', 'edge_box', true),
    ('PVA-25-30R6',  '25 Channel, 30xdays of storage, Raid6',  'edge_box', true),
    ('PVA-25-60R6',  '25 Channel, 60xdays of storage, Raid6',  'edge_box', true),
    ('PVA-25-90R6',  '25 Channel, 90xdays of storage, Raid6',  'edge_box', true),
    ('PVA-50-30R6',  '50 Channel, 30xdays of storage, Raid6',  'edge_box', true),
    ('PVA-50-60R6',  '50 Channel, 60xdays of storage, Raid6',  'edge_box', true),
    ('PVA-50-90R6',  '50 Channel, 90xdays of storage, Raid6',  'edge_box', true),
    ('PVA-75-30R6',  '75 Channel, 30xdays of storage, Raid6',  'edge_box', true),
    ('PVA-75-60R6',  '75 Channel, 60xdays of storage, Raid6',  'edge_box', true),
    ('PVA-75-90R6',  '75 Channel, 90xdays of storage, Raid6',  'edge_box', true),
    ('PVA-100-30R6', '100 Channel, 30xdays of storage, Raid6', 'edge_box', true),
    ('PVA-100-60R6', '100 Channel, 60xdays of storage, Raid6', 'edge_box', true),
    ('PVA-100-90R6', '100 Channel, 90xdays of storage, Raid6', 'edge_box', true),
    ('PVA-200-30R6', '200 Channel, 30xdays of storage, Raid6', 'edge_box', true),
    ('PVA-200-60R6', '200 Channel, 60xdays of storage, Raid6', 'edge_box', true),
    ('PVA-200-90R6', '200 Channel, 90xdays of storage, Raid6', 'edge_box', true),
    ('PVA-300-30R6', '300 Channel, 30xdays of storage, Raid6', 'edge_box', true),
    ('PVA-300-60R6', '300 Channel, 60xdays of storage, Raid6', 'edge_box', true),
    ('PVA-300-90R6', '300 Channel, 90xdays of storage, Raid6', 'edge_box', true),
    ('PVA-50-30R10',  '50 Channel, 30xdays of storage, Raid10',  'edge_box', true),
    ('PVA-50-60R10',  '50 Channel, 60xdays of storage, Raid10',  'edge_box', true),
    ('PVA-50-90R10',  '50 Channel, 90xdays of storage, Raid10',  'edge_box', true),
    ('PVA-75-30R10',  '75 Channel, 30xdays of storage, Raid10',  'edge_box', true),
    ('PVA-75-60R10',  '75 Channel, 60xdays of storage, Raid10',  'edge_box', true),
    ('PVA-75-90R10',  '75 Channel, 90xdays of storage, Raid10',  'edge_box', true),
    ('PVA-100-30R10', '100 Channel, 30xdays of storage, Raid10', 'edge_box', true),
    ('PVA-100-60R10', '100 Channel, 60xdays of storage, Raid10', 'edge_box', true),
    ('PVA-100-90R10', '100 Channel, 90xdays of storage, Raid10', 'edge_box', true),
    ('PVA-25-30SFF',  '25 Channel, 30xdays of storage, Non-Raid', 'edge_box', true),
    ('E2C-25-2TB',    '25 Channel, 2TB of storage, SimplyNUC',    'edge_box', true),
    ('PVA-8-30NR',    '8 Channel, 30xdays of storage, Non-Raid',  'edge_box', true),
    ('PVA-16-30NR',   '16 Channel, 30xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-10-30NR',   '10 Channel, 30xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-10-60NR',   '10 Channel, 60xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-10-90NR',   '10 Channel, 90xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-25-30NR',   '25 Channel, 30xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-25-60NR',   '25 Channel, 60xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-25-90NR',   '25 Channel, 90xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-50-30NR',   '50 Channel, 30xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-50-60NR',   '50 Channel, 60xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-50-90NR',   '50 Channel, 90xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-75-30NR',   '75 Channel, 30xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-75-60NR',   '75 Channel, 60xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-75-90NR',   '75 Channel, 90xdays of storage, Non-Raid', 'edge_box', true),
    ('PVA-100-30NR',  '100 Channel, 30xdays of storage, Non-Raid','edge_box', true),
    ('PVA-100-60NR',  '100 Channel, 60xdays of storage, Non-Raid','edge_box', true),
    ('PVA-100-90NR',  '100 Channel, 90xdays of storage, Non-Raid','edge_box', true),
    ('PVA-200-30NR',  '200 Channel, 30xdays of storage, Non-Raid','edge_box', true),
    ('PVA-200-60NR',  '200 Channel, 60xdays of storage, Non-Raid','edge_box', true),
    ('PVA-200-90NR',  '200 Channel, 90xdays of storage, Non-Raid','edge_box', true),
    ('PVA-300-30NR',  '300 Channel, 30xdays of storage, Non-Raid','edge_box', true),
    ('PVA-300-60NR',  '300 Channel, 60xdays of storage, Non-Raid','edge_box', true),
    ('PVA-300-90NR',  '300 Channel, 90xdays of storage, Non-Raid','edge_box', true),
    ('EDGE10-NR',     '10 Channel, Non-Raid',                     'edge_box', false),
    ('EDGE25SFF-NR',  '25 Channel, Small Form Factor, Non-Raid',  'edge_box', false),
    ('EDGE25-NR',     '25 Channel, Non-Raid',                     'edge_box', false),
    ('EDGE50-NR',     '50 Channel, Non-Raid',                     'edge_box', false),
    ('EDGE100-NR',    '100 Channel, Non-Raid',                    'edge_box', false),
    ('EDGE50-Z2',     '50 Channel, ZFS Z2 Raid',                  'edge_box', false),
    ('EDGE100-Z2',    '100 Channel, ZFS Z2 Raid',                 'edge_box', false),
    ('EDGE200-Z2',    '200 Channel, ZFS Z2 Raid',                 'edge_box', false),
    ('EDGE300-Z2',    '300 Channel, ZFS Z2 Raid',                 'edge_box', false),
    ('STOR-HDD-12TB', 'Single HDD. Can be used in SFF as well.',  'storage_drive', false),
    ('STOR-HDD-16TB', 'Single HDD. Can be used in SFF as well.',  'storage_drive', false),
    ('STOR-HDD-20TB', 'Single HDD. Can be used in SFF as well.',  'storage_drive', false),
    ('STOR-PACK-96TB',  'Group of drives totaling 96TB',          'storage_drive', false),
    ('STOR-PACK-128TB', 'Group of drives totaling 128TB',         'storage_drive', false),
    ('STOR-PACK-160TB', 'Group of drives totaling 160TB',         'storage_drive', false)
ON CONFLICT (brand_sku) DO NOTHING;
