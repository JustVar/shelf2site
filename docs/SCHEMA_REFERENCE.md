> ⚠️ **Legacy NUC schema reference.** This document describes the schema of the
> `hardware_inventory` database on the legacy NUC (192.0.2.174), NOT the
> apphost `asset_tracker` database that powers the current application. Kept
> for historical reference and migration cross-checks. Do not edit the active
> app against this schema.

# Asset Tracker — Schema & Tech Stack Reference

**Generated:** 2026-03-24 | **Database:** `hardware_inventory` | **Schema:** `public`

---

## Tech Stack

| Layer | Component | Version |
|---|---|---|
| OS | Ubuntu LTS | 24.04.4 |
| Kernel | Linux | 6.8.0-106-generic |
| Runtime | Python | 3.12.3 |
| Database | PostgreSQL | 16.13 |
| Reverse Proxy | nginx | 1.24.0 |
| App Server | gunicorn | 25.1.0 |
| Framework | FastAPI | 0.135.2 |
| ASGI | Starlette | 0.52.1 |
| ORM | SQLAlchemy | 2.0.48 |
| Validation | Pydantic | 2.12.5 |
| Templates | Jinja2 | 3.1.6 |
| DB Driver | psycopg2-binary | 2.9.11 |
| HTTP Client | httpx | 0.28.1 |
| Encryption | cryptography | 46.0.5 |
| Image Processing | Pillow | 12.1.1 |
| Spreadsheets | openpyxl | 3.1.5 |
| OCR | pytesseract | 0.3.13 |
| Network Scan | python-nmap | 0.7.1 |
| SMTP | aiosmtplib | 5.1.0 |
| SSE | sse-starlette | 2.2.1 |

---

## Data Types Used

| PostgreSQL Type | Shorthand | Where Used |
|---|---|---|
| `integer` | int | Primary keys (auto-increment), foreign keys, counts, quantities |
| `character varying(N)` | varchar | Most string fields (N = 8 to 512) |
| `text` | text | Notes, descriptions, addresses, long-form content |
| `boolean` | bool | Flags (is_active, dismissed, permission toggles) |
| `timestamp without time zone` | timestamp | created_at, updated_at, last_seen, last_login |
| `timestamp with time zone` | timestamptz | error_log.created_at, delete_requests.requested_at, delete_requests.decided_at, item_schema.csv_import_map.imported_at |
| `date` | date | Purchase dates, warranty dates, shipping dates |
| `numeric` | numeric | Money fields (prices, costs, values) |
| `double precision` | float8 | Data completeness scores, geo coordinates |
| `jsonb` | jsonb | Structured data (audit diffs, SKU requirements, provisioning stages) |
| `bytea` | bytea | Fernet-encrypted credentials (username, password, notes) |

---

## Tables Overview (50 tables, 939 columns)

| # | Table | Category | Columns |
|---|---|---|---|
| 1 | access_control | Device | 26 |
| 2 | cameras | Device | 26 |
| 3 | computers | Device | 28 |
| 4 | edge_boxes | Device | 37 |
| 5 | mobile_devices | Device | 21 |
| 6 | monitors | Device | 22 |
| 7 | nas_devices | Device | 26 |
| 8 | network_equipment | Device | 22 |
| 9 | nucs | Device | 27 |
| 10 | office_equipment | Device | 22 |
| 11 | phones | Device | 19 |
| 12 | printers | Device | 20 |
| 13 | ups | Device | 23 |
| 14 | webcams | Device | 21 |
| 15 | cpus | Component | 19 |
| 16 | gpus | Component | 18 |
| 17 | hard_drives | Component | 26 |
| 18 | motherboards | Component | 18 |
| 19 | psus | Component | 20 |
| 20 | ram_modules | Component | 20 |
| 21 | pc_accessories | Component | 20 |
| 22 | pc_cooling | Component | 20 |
| 23 | nas_drives | Component | 23 |
| 24 | customer_orders | Fulfillment | 30 |
| 25 | deployment_records | Fulfillment | 14 |
| 26 | device_provisioning | Fulfillment | 23 |
| 27 | oem_purchase_orders | Fulfillment | 13 |
| 28 | receiving_events | Fulfillment | 11 |
| 29 | device_assignments | Lifecycle | 12 |
| 30 | device_components | Lifecycle | 9 |
| 31 | device_credentials | Lifecycle | 8 |
| 32 | device_dispositions | Lifecycle | 27 |
| 33 | device_warranties | Warranty | 29 |
| 34 | warranty_claims | Warranty | 15 |
| 35 | vendor_profiles | Vendor | 11 |
| 36 | vendor_trials | Vendor | 25 |
| 37 | users | System | 28 |
| 38 | teams | System | 17 |
| 39 | sites | System | 14 |
| 40 | audit_log | System | 11 |
| 41 | error_log | System | 11 |
| 42 | notifications | System | 8 |
| 43 | notification_subscriptions | System | 9 |
| 44 | edit_locks | System | 7 |
| 45 | part_numbers | Reference | 14 |
| 46 | pending_devices | Reference | 13 |
| 47 | oui_allowlist | Reference | 7 |
| 48 | intake_photos | Reference | 11 |
| 49 | intune_sync_log | Reference | 8 |
| 50 | user_tour_progress | Reference | 5 |

---

## Shared Fields (Device & Component Tables)

Most device and component tables inherit these common columns:

| Field | Type | Notes |
|---|---|---|
| `id` | int (PK) | Auto-increment via sequence |
| `created_at` | timestamp | Default: `now()` |
| `updated_at` | timestamp | Default: `now()` |
| `data_completeness` | float8 | 0.0 - 1.0 completeness score |
| `discovered_by` | varchar(64) | Scanner or manual entry source |
| `network_segment` | varchar(32) | LAN segment identifier |
| `last_seen` | timestamp | Last network discovery timestamp |
| `vendor` | varchar(128) | Procurement vendor |
| `purchase_date` | date | |
| `purchase_price` | numeric | |
| `purchase_order` | varchar(64) | PO number |
| `supplier_invoice` | varchar(128) | |
| `procurement_method` | varchar(32) | |

---

## Table Details

### 1. access_control

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(128) | YES | |
| model | varchar(128) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| device_name | varchar(128) | YES | |
| ip_address | varchar(45) | YES | |
| mac_address | varchar(64) | YES | |
| notes | text | YES | |
| deployment_type | varchar(32) | YES | 'internal' |
| + shared fields | | | |

### 2. cameras

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(128) | YES | |
| model | varchar(128) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| device_name | varchar(128) | YES | |
| ip_address | varchar(45) | YES | |
| mac_address | varchar(64) | YES | |
| notes | text | YES | |
| deployment_type | varchar(32) | YES | 'internal' |
| + shared fields | | | |

### 3. computers

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device | varchar(255) | YES | |
| device_name | varchar(128) | YES | |
| model | varchar(128) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| notes | text | YES | |
| intune_device_id | varchar(128) | YES | |
| intune_compliance | varchar(32) | YES | |
| os | varchar(64) | YES | |
| os_version | varchar(64) | YES | |
| primary_user_upn | varchar(255) | YES | |
| intune_last_checkin | timestamp | YES | |
| + shared fields | | | |

### 4. edge_boxes

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| org | varchar(255) | YES | |
| customer | varchar(255) | YES | |
| site_name | varchar(255) | YES | |
| serial | varchar(64) | YES | |
| status | varchar(64) | YES | |
| part_number | varchar(64) | YES | |
| warranty_id | varchar(64) | YES | |
| mac_address | varchar(64) | YES | |
| mac_address_2 | varchar(64) | YES | |
| uuid | varchar(128) | YES | |
| last_updated | timestamp | YES | |
| notes | text | YES | |
| pilot_type | varchar(32) | YES | |
| deployment_type | varchar(32) | YES | |
| geo_lat | float8 | YES | |
| geo_lng | float8 | YES | |
| show_on_map | bool | NO | true |
| sku_version | varchar(16) | YES | 'legacy' |
| location | varchar(100) | YES | |
| form_factor | varchar(20) | YES | |
| partner | varchar(100) | YES | |
| incomplete_reason | text | YES | |
| external_id | varchar(64) | YES | |
| + shared fields | | | |

### 5. mobile_devices

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device | varchar(255) | YES | |
| model_name | varchar(128) | YES | |
| model_number | varchar(64) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| notes | text | YES | |
| + shared fields | | | |

### 6. monitors

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device | varchar(255) | YES | |
| model | varchar(128) | YES | |
| model_code | varchar(64) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| notes | text | YES | |
| + shared fields | | | |

### 7. nas_devices

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| model | varchar(128) | YES | |
| serial | varchar(64) | YES | |
| manufacturer | varchar(128) | YES | |
| mac_address_1 | varchar(64) | YES | |
| mac_address_2 | varchar(64) | YES | |
| bay_count | int | YES | |
| ram_gb | varchar(32) | YES | |
| firmware_version | varchar(64) | YES | |
| location | varchar(255) | YES | |
| status | varchar(64) | YES | |
| assigned_to | varchar(128) | YES | |
| ip_address | varchar(45) | YES | |
| receiving_event_id | int | YES | |
| notes | text | YES | |
| + shared fields | | | |

### 8. network_equipment

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device | varchar(255) | YES | |
| model_name | varchar(128) | YES | |
| model_number | varchar(64) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| notes | text | YES | |
| + shared fields | | | |

### 9. nucs

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| serial | varchar(64) | YES | |
| status | varchar(64) | YES | |
| location | varchar(100) | YES | |
| mac_address | varchar(64) | YES | |
| mac_address_2 | varchar(64) | YES | |
| uuid | varchar(128) | YES | |
| purpose | text | YES | |
| org | varchar(255) | YES | |
| notes | text | YES | |
| last_updated | timestamp | YES | |
| deployment_type | varchar(32) | YES | 'internal' |
| + shared fields | | | |

### 10. office_equipment

Same structure as network_equipment (device, model_name, model_number, serial, location, assigned_to, purpose, notes + shared).

### 11. phones

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device | varchar(255) | YES | |
| model | varchar(128) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| + shared fields | | | |

### 12. printers

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device | varchar(255) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| notes | text | YES | |
| + shared fields | | | |

### 13. ups

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(100) | YES | |
| model | varchar(100) | YES | |
| serial | varchar(64) | YES | |
| va_rating | varchar(32) | YES | |
| wattage | varchar(32) | YES | |
| location | varchar(100) | YES | |
| notes | text | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 14. webcams

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device | varchar(255) | YES | |
| model | varchar(128) | YES | |
| serial | varchar(64) | YES | |
| location | varchar(255) | YES | |
| assigned_to | varchar(128) | YES | |
| purpose | varchar(128) | YES | |
| notes | text | YES | |
| + shared fields | | | |

---

### 15. cpus

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(100) | YES | |
| model | varchar(100) | YES | |
| socket | varchar(32) | YES | |
| serial | varchar(64) | YES | |
| status | varchar(64) | YES | |
| location | varchar(100) | YES | |
| associated_device_serial | varchar(64) | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 16. gpus

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| gpu_serial | varchar(64) | YES | |
| model | varchar(128) | YES | |
| status | varchar(64) | YES | |
| associated_device_serial | varchar(64) | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 17. hard_drives

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(100) | YES | |
| model | varchar(100) | YES | |
| drive_type | varchar(32) | YES | |
| form_factor | varchar(32) | YES | |
| serial | varchar(64) | YES | |
| capacity_tb | float8 | YES | |
| capacity_gb | int | YES | |
| interface | varchar(32) | YES | |
| rpm | varchar(16) | YES | |
| status | varchar(64) | YES | |
| location | varchar(100) | YES | |
| associated_device_serial | varchar(64) | YES | |
| notes | text | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 18. motherboards

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(100) | YES | |
| model | varchar(100) | YES | |
| socket | varchar(32) | YES | |
| serial | varchar(64) | YES | |
| status | varchar(64) | YES | |
| associated_device_serial | varchar(64) | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 19. psus

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(100) | YES | |
| model | varchar(100) | YES | |
| serial | varchar(64) | YES | |
| wattage_rating | varchar(32) | YES | |
| efficiency | varchar(32) | YES | |
| status | varchar(64) | YES | |
| location | varchar(100) | YES | |
| associated_device_serial | varchar(64) | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 20. ram_modules

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(100) | YES | |
| model | varchar(100) | YES | |
| ram_type | varchar(32) | YES | |
| serial | varchar(64) | YES | |
| capacity_gb | int | YES | |
| speed_mhz | int | YES | |
| status | varchar(64) | YES | |
| location | varchar(100) | YES | |
| associated_device_serial | varchar(64) | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 21. pc_accessories

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(100) | YES | |
| model | varchar(100) | YES | |
| accessory_type | varchar(32) | YES | |
| serial | varchar(64) | YES | |
| status | varchar(64) | YES | |
| associated_device_serial | varchar(64) | YES | |
| location | varchar(100) | YES | |
| notes | text | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 22. pc_cooling

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| manufacturer | varchar(100) | YES | |
| model | varchar(100) | YES | |
| cooling_type | varchar(32) | YES | |
| serial | varchar(64) | YES | |
| speed_rpm | varchar(32) | YES | |
| status | varchar(64) | YES | |
| associated_device_serial | varchar(64) | YES | |
| location | varchar(100) | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 23. nas_drives

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| nas_device_id | int (FK) | NO | |
| bay_number | int | NO | |
| serial_number | varchar(128) | YES | |
| manufacturer | varchar(128) | YES | |
| model | varchar(128) | YES | |
| capacity_gb | int | YES | |
| drive_type | varchar(32) | YES | |
| interface | varchar(32) | YES | |
| drive_status | varchar(32) | YES | |
| install_date | date | YES | |
| removal_date | date | YES | |
| health_status | varchar(32) | YES | |
| smart_data | text | YES | |
| warranty_end | date | YES | |
| + shared fields | | | |

---

### 24. customer_orders

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| order_number | varchar(32) | NO | |
| salesforce_order_id | varchar(64) | YES | |
| salesforce_opp_id | varchar(64) | YES | |
| customer_name | varchar(256) | NO | |
| customer_account | varchar(256) | YES | |
| sales_engineer | varchar(128) | YES | |
| sales_engineer_id | int | YES | |
| deployment_type | varchar(32) | YES | 'direct' |
| integrator_name | varchar(256) | YES | |
| distributor_name | varchar(256) | YES | |
| due_date | date | YES | |
| status | varchar(32) | YES | 'new' |
| sku_requirements | jsonb | YES | '[]' |
| pre_site_survey | text | YES | |
| post_install_notes | text | YES | |
| notes | text | YES | |
| created_by | int | YES | |
| is_sensitive | bool | NO | false |
| contract_value | numeric | YES | |
| hardware_cost | numeric | YES | |
| shipped_date | date | YES | |
| delivered_date | date | YES | |
| carrier | varchar(64) | YES | |
| tracking_number | varchar(128) | YES | |
| shipping_address | text | YES | |
| ship_method | varchar(32) | YES | |
| recipient_name | varchar(256) | YES | |
| created_at | timestamp | YES | now() |
| updated_at | timestamp | YES | now() |

### 25. deployment_records

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| customer_order_id | int (FK) | NO | |
| site_id | int (FK) | YES | |
| address | text | YES | |
| status | varchar(32) | NO | 'scheduled' |
| scheduled_date | date | YES | |
| installed_date | date | YES | |
| se_assigned_id | int | YES | |
| integrator_name | varchar(256) | YES | |
| integrator_contact | varchar(256) | YES | |
| notes | text | YES | |
| created_at | timestamp | NO | now() |
| updated_at | timestamp | NO | now() |
| created_by | int | YES | |

### 26. device_provisioning

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device_table | varchar(64) | NO | |
| device_id | int | NO | |
| site_id | int | YES | |
| current_stage | varchar(32) | NO | |
| stages | jsonb | NO | |
| assigned_to | int | YES | |
| notes | text | YES | |
| priority | varchar(16) | YES | |
| is_complete | bool | YES | |
| completed_at | timestamp | YES | |
| due_date | date | YES | |
| start_date | date | YES | |
| location_note | text | YES | |
| deployment_bucket | varchar(32) | YES | |
| zendesk_ticket_id | int | YES | |
| validation_report_path | varchar(512) | YES | |
| validation_result | varchar(16) | YES | |
| validation_date | timestamp | YES | |
| customer_order_id | int | YES | |
| created_at | timestamp | YES | now() |
| updated_at | timestamp | YES | now() |
| created_by | int | YES | |

### 27. oem_purchase_orders

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| customer_order_id | int (FK) | YES | |
| vendor_name | varchar(128) | NO | |
| po_number | varchar(64) | YES | |
| sku | varchar(128) | NO | |
| qty_ordered | int | NO | 1 |
| qty_received | int | NO | 0 |
| order_date | date | YES | |
| expected_delivery | date | YES | |
| received_date | date | YES | |
| status | varchar(32) | YES | 'ordered' |
| notes | text | YES | |
| created_at | timestamp | YES | now() |

### 28. receiving_events

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| received_date | timestamp | YES | now() |
| vendor | varchar(255) | YES | |
| purchase_order | varchar(64) | YES | |
| expected_quantity | int | YES | |
| received_quantity | int | YES | |
| status | varchar(32) | YES | |
| notes | text | YES | |
| created_by | int | YES | |
| created_at | timestamp | YES | now() |
| updated_at | timestamp | YES | now() |

---

### 29. device_assignments

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device_table | varchar(64) | NO | |
| device_id | int | NO | |
| site_id | int | NO | |
| ownership | varchar(32) | NO | |
| assigned_date | date | YES | Central date (migration 079) |
| expected_return | date | YES | |
| returned_date | date | YES | |
| assigned_by | int | YES | |
| notes | text | YES | |
| is_active | bool | YES | |
| created_at | timestamp | YES | now() |
| updated_at | timestamp | YES | now() |

### 30. device_components

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| parent_table | varchar(50) | NO | |
| parent_id | int | NO | |
| component_table | varchar(50) | NO | |
| component_id | int | NO | |
| slot_label | varchar(50) | YES | |
| installed_date | date | YES | |
| removed_date | date | YES | |
| installed_by | varchar(100) | YES | |
| notes | text | YES | |
| created_at | timestamp | YES | |

### 31. device_credentials

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device_table | varchar(64) | NO | |
| device_id | int | NO | |
| credential_type | varchar(32) | NO | |
| username | **bytea** | YES | Fernet encrypted |
| password | **bytea** | YES | Fernet encrypted |
| notes | **bytea** | YES | Fernet encrypted |
| created_at | timestamp | YES | now() |
| updated_at | timestamp | YES | now() |

### 32. device_dispositions

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device_table | varchar(64) | NO | |
| device_id | int | NO | |
| disposition_type | varchar(32) | YES | |
| disposition_date | date | NO | |
| reason | text | YES | |
| sanitization_method | varchar(64) | YES | |
| sanitization_date | date | YES | |
| sanitization_verified_by | varchar(128) | YES | |
| certificate_number | varchar(128) | YES | |
| certificate_file_path | varchar(512) | YES | |
| transferred_to | varchar(128) | YES | |
| transfer_method | varchar(64) | YES | |
| transfer_value | numeric | YES | |
| transfer_notes | text | YES | |
| + shared fields | | | |

---

### 33. device_warranties

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device_table | varchar(64) | NO | |
| device_id | int | NO | |
| warranty_tier | varchar(32) | YES | |
| vendor | varchar(128) | YES | |
| purchase_date | date | YES | |
| warranty_start | date | YES | |
| warranty_end | date | YES | |
| warranty_type | varchar(64) | YES | |
| registration_number | varchar(128) | YES | |
| coverage_details | text | YES | |
| auto_renew | bool | YES | |
| renewal_cost | numeric | YES | |
| registration_status | varchar(32) | YES | |
| warranty_scope | varchar(16) | NO | 'external' |
| warranty_holder | varchar(32) | YES | 'in_house' |
| loaner_from_team | varchar(128) | YES | |
| loaner_to_team | varchar(128) | YES | |
| loaner_contact | varchar(128) | YES | |
| loaner_agreement | varchar(128) | YES | |
| + shared fields (minus vendor, purchase_date) | | | |

### 34. warranty_claims

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| warranty_id | int (FK) | YES | |
| claim_number | varchar(128) | YES | |
| claim_date | date | NO | |
| issue_description | text | YES | |
| claim_status | varchar(32) | YES | |
| rma_number | varchar(128) | YES | |
| tracking_number | varchar(128) | YES | |
| shipped_date | date | YES | |
| expected_return | date | YES | |
| received_date | date | YES | |
| replacement_device_sn | varchar(128) | YES | |
| resolution_notes | text | YES | |
| created_at | timestamp | YES | now() |
| updated_at | timestamp | YES | now() |

### 35. vendor_profiles

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| name | varchar(128) | NO | |
| display_name | varchar(128) | YES | |
| contact_name | varchar(128) | YES | |
| contact_email | varchar(256) | YES | |
| contact_phone | varchar(64) | YES | |
| website | varchar(512) | YES | |
| is_oem | bool | NO | false |
| categories_supplied | text | YES | |
| notes | text | YES | |
| created_at | timestamp | NO | now() |
| updated_at | timestamp | NO | now() |

### 36. vendor_trials

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| device_table | varchar(64) | NO | |
| device_id | int | NO | |
| vendor | varchar(128) | NO | |
| trial_type | varchar(64) | YES | |
| received_date | date | NO | |
| return_deadline | date | NO | |
| decision_deadline | date | YES | |
| trial_status | varchar(32) | YES | |
| decision | varchar(32) | YES | |
| decision_date | date | YES | |
| decision_notes | text | YES | |
| purchase_order | varchar(128) | YES | |
| purchase_price | numeric | YES | |
| return_tracking | varchar(128) | YES | |
| returned_date | date | YES | |
| evaluation_notes | text | YES | |
| test_results | text | YES | |
| pros | text | YES | |
| cons | text | YES | |
| + shared fields (partial) | | | |

---

### 37. users

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| username | varchar(64) | NO | |
| display_name | varchar(128) | NO | |
| password_hash | varchar(256) | NO | |
| role | varchar(32) | NO | |
| is_active | bool | YES | |
| created_at | timestamp | YES | now() |
| last_login | timestamp | YES | |
| email | varchar(256) | YES | |
| slack_user_id | varchar(64) | YES | |
| slack_auto_match | bool | NO | true |
| must_change_password | bool | NO | true |
| password_changed_at | timestamp | YES | |
| team_id | int (FK) | YES | |
| last_seen_at | timestamp | YES | |
| view_sensitive_customers | bool | YES | |
| can_view_receipts | user_permission_state | NO | inherit |
| can_manage_warranty | bool | YES | |
| can_manage_trials | bool | YES | |
| can_manage_procurement | bool | YES | |
| can_manage_sites | bool | YES | |
| can_manage_users | bool | YES | |
| can_manage_system | bool | YES | |
| can_view_audit_log | bool | YES | |
| can_access_receiving | bool | YES | |
| can_access_map | bool | YES | |
| can_access_disposal | bool | YES | |
| can_access_credentials | bool | YES | |
| can_manage_provisioning | bool | YES | |
| can_view_provisioning | bool | YES | |

### 38. teams

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| name | varchar(64) | NO | |
| description | text | YES | |
| created_at | timestamp | YES | now() |
| can_view_receipts | department_permission_state | NO | block |
| can_manage_warranty | bool | NO | |
| can_manage_trials | bool | NO | |
| can_manage_procurement | bool | NO | |
| can_manage_sites | bool | NO | |
| can_manage_users | bool | NO | |
| can_manage_system | bool | NO | |
| can_view_audit_log | bool | NO | |
| can_access_receiving | bool | NO | |
| can_access_map | bool | NO | |
| can_access_disposal | bool | NO | |
| can_access_credentials | bool | NO | |
| can_manage_provisioning | bool | NO | |
| can_view_provisioning | bool | NO | |

### 39. sites

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| name | varchar(255) | NO | |
| site_type | varchar(32) | NO | |
| customer | varchar(255) | YES | |
| address | text | YES | |
| city | varchar(128) | YES | |
| state | varchar(64) | YES | |
| country | varchar(64) | YES | |
| contact_name | varchar(128) | YES | |
| contact_email | varchar(255) | YES | |
| contact_phone | varchar(64) | YES | |
| notes | text | YES | |
| is_active | bool | YES | |
| created_at | timestamp | YES | now() |
| updated_at | timestamp | YES | now() |

### 40. audit_log

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| timestamp | timestamp | YES | now() |
| user_id | int | YES | |
| event_type | varchar(32) | NO | |
| target_table | varchar(64) | YES | |
| target_id | int | YES | |
| action | varchar(16) | YES | |
| old_values | jsonb | YES | |
| new_values | jsonb | YES | |
| ip_address | varchar(45) | YES | |
| details | text | YES | |

### 41. error_log

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| created_at | **timestamptz** | YES | now() |
| source | varchar(16) | NO | 'frontend' |
| level | varchar(16) | NO | 'error' |
| message | text | NO | |
| stack | text | YES | |
| url | varchar(512) | YES | |
| user_id | int | YES | |
| username | varchar(128) | YES | |
| browser | varchar(256) | YES | |
| context | jsonb | YES | |
| fingerprint | varchar(64) | YES | |

### 42. notifications

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| notification_type | varchar(64) | NO | |
| title | varchar(256) | NO | |
| message | text | NO | |
| link | varchar(512) | YES | |
| actor_id | int | YES | |
| is_read | bool | NO | false |
| dismissed | bool | NO | false |
| created_at | timestamp | YES | now() |

### 43. notification_subscriptions

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| user_id | int | NO | |
| event_type | varchar(64) | YES | |
| resource_type | varchar(64) | YES | |
| resource_id | int | YES | |
| deliver_slack | bool | NO | true |
| deliver_inapp | bool | NO | true |
| deliver_email | bool | NO | false |
| is_active | bool | NO | true |
| created_at | timestamp | NO | now() |

### 44. edit_locks

| Field | Type | Nullable | Default |
|---|---|---|---|
| resource_key | varchar(128) | NO | |
| user_id | int | NO | |
| username | varchar(128) | NO | |
| display_name | varchar(256) | NO | |
| level | varchar(16) | NO | 'viewing' |
| acquired_at | float8 | NO | |
| last_activity | float8 | NO | |

### 45. part_numbers

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| part_number | varchar(64) | YES | |
| vendor | varchar(255) | YES | |
| form_factor | varchar(64) | YES | |
| service_type | varchar(128) | YES | |
| last_updated | timestamp | YES | |
| + shared fields | | | |

### 46. pending_devices

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| mac_address | varchar(64) | NO | |
| ip_address | varchar(45) | YES | |
| hostname | varchar(128) | YES | |
| manufacturer | varchar(128) | YES | |
| suggested_table | varchar(64) | YES | |
| scanner_id | varchar(64) | YES | |
| network_segment | varchar(32) | YES | |
| first_seen | timestamp | YES | now() |
| last_seen | timestamp | YES | now() |
| status | varchar(16) | YES | |
| reviewed_by | int | YES | |
| reviewed_at | timestamp | YES | |
| dismiss_reason | text | YES | |

### 47. oui_allowlist

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| oui_prefix | varchar(8) | NO | |
| manufacturer | varchar(128) | YES | |
| maps_to_table | varchar(64) | YES | |
| is_active | bool | YES | |
| added_by | int | YES | |
| created_at | timestamp | YES | now() |

### 48. intake_photos

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| receiving_event_id | int (FK) | YES | |
| device_table | varchar(64) | YES | |
| device_id | int | YES | |
| filename | varchar(255) | NO | |
| original_filename | varchar(255) | YES | |
| content_type | varchar(64) | YES | |
| file_size | int | YES | |
| caption | varchar(255) | YES | |
| uploaded_by | int | YES | |
| created_at | timestamp | YES | now() |

### 49. intune_sync_log

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| synced_at | timestamp | NO | now() |
| synced_by | int | YES | |
| devices_found | int | NO | 0 |
| devices_added | int | NO | 0 |
| devices_updated | int | NO | 0 |
| devices_skipped | int | NO | 0 |
| status | varchar(32) | NO | 'pending' |
| error_message | text | YES | |

### 50. user_tour_progress

| Field | Type | Nullable | Default |
|---|---|---|---|
| id | int | NO | auto |
| user_id | int | NO | |
| tour_id | varchar(64) | NO | |
| completed_at | timestamp | YES | now() |
| dismissed | bool | YES | |
