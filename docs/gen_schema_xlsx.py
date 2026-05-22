"""Legacy NUC schema generator.

SSHes to the legacy NUC (192.0.2.174) and dumps the hardware_inventory
schema to a local XLSX file. NOT the apphost asset_tracker schema — this
is the older on-NUC inventory database.

Usage:
    NUC_PGPASSWORD='...' python docs/gen_schema_xlsx.py

Security: previous versions of this script hardcoded the NUC
inventory_user password in plaintext. Assume the prior value is
COMPROMISED and rotate that password before running this again.
"""

import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import subprocess

# Get raw schema data from NUC
pgpw = os.environ.get("NUC_PGPASSWORD")
if not pgpw:
    raise SystemExit("NUC_PGPASSWORD env var not set. Refusing to run with a hardcoded fallback. See module docstring.")

result = subprocess.run(
    ['ssh', 'admin@192.0.2.174',
     f"PGPASSWORD={pgpw} psql -U inventory_user -h localhost -d hardware_inventory -t -A -F'|' -c "
     "\"SELECT table_name, column_name, data_type, character_maximum_length, is_nullable, column_default "
     "FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name, ordinal_position;\""],
    capture_output=True, text=True, timeout=30
)

rows = []
for line in result.stdout.strip().split('\n'):
    parts = line.strip().split('|')
    if len(parts) >= 6:
        rows.append(parts)

print(f"Fetched {len(rows)} columns from database")

# Style constants
HEADER_FILL = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
HEADER_FONT = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
CATEGORY_FILL = PatternFill(start_color='D6E4F0', end_color='D6E4F0', fill_type='solid')
DATA_FONT = Font(name='Calibri', size=10)
PK_FONT = Font(name='Calibri', size=10, bold=True)
THIN_BORDER = Border(
    left=Side(style='thin', color='B0B0B0'),
    right=Side(style='thin', color='B0B0B0'),
    top=Side(style='thin', color='B0B0B0'),
    bottom=Side(style='thin', color='B0B0B0')
)
ALT_FILL = PatternFill(start_color='F2F7FB', end_color='F2F7FB', fill_type='solid')
TABLE_SEP_FILL = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')

# Table categories
TABLE_CATEGORIES = {
    'access_control': 'Device Inventory', 'cameras': 'Device Inventory', 'computers': 'Device Inventory',
    'edge_boxes': 'Device Inventory', 'mobile_devices': 'Device Inventory', 'monitors': 'Device Inventory',
    'nas_devices': 'Device Inventory', 'network_equipment': 'Device Inventory', 'nucs': 'Device Inventory',
    'office_equipment': 'Device Inventory', 'phones': 'Device Inventory', 'printers': 'Device Inventory',
    'ups': 'Device Inventory', 'webcams': 'Device Inventory',
    'cpus': 'PC Components', 'gpus': 'PC Components', 'hard_drives': 'PC Components',
    'motherboards': 'PC Components', 'psus': 'PC Components', 'ram_modules': 'PC Components',
    'pc_accessories': 'PC Components', 'pc_cooling': 'PC Components', 'nas_drives': 'PC Components',
    'customer_orders': 'Fulfillment', 'deployment_records': 'Fulfillment',
    'device_provisioning': 'Fulfillment', 'oem_purchase_orders': 'Fulfillment',
    'receiving_events': 'Fulfillment',
    'device_assignments': 'Device Lifecycle', 'device_components': 'Device Lifecycle',
    'device_credentials': 'Device Lifecycle', 'device_dispositions': 'Device Lifecycle',
    'device_warranties': 'Warranty & Vendor', 'warranty_claims': 'Warranty & Vendor',
    'vendor_profiles': 'Warranty & Vendor', 'vendor_trials': 'Warranty & Vendor',
    'users': 'System', 'teams': 'System', 'sites': 'System', 'audit_log': 'System',
    'error_log': 'System', 'notifications': 'System', 'notification_subscriptions': 'System',
    'edit_locks': 'System',
    'part_numbers': 'Reference', 'pending_devices': 'Reference', 'oui_allowlist': 'Reference',
    'intake_photos': 'Reference', 'intune_sync_log': 'Reference', 'user_tour_progress': 'Reference',
}

wb = openpyxl.Workbook()


def apply_header(ws, headers, row=1):
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center')
        cell.border = THIN_BORDER


# ── Sheet 1: Tech Stack ──
ws1 = wb.active
ws1.title = 'Tech Stack'
ws1.sheet_properties.tabColor = '1F4E79'

tech_stack = [
    ('OS', 'Ubuntu LTS', '24.04.4'),
    ('Kernel', 'Linux', '6.8.0-106-generic'),
    ('Runtime', 'Python', '3.12.3'),
    ('Database', 'PostgreSQL', '16.13'),
    ('Reverse Proxy', 'nginx', '1.24.0'),
    ('App Server', 'gunicorn', '25.1.0'),
    ('Framework', 'FastAPI', '0.135.2'),
    ('ASGI', 'Starlette', '0.52.1'),
    ('ORM', 'SQLAlchemy', '2.0.48'),
    ('Validation', 'Pydantic', '2.12.5'),
    ('Templates', 'Jinja2', '3.1.6'),
    ('DB Driver', 'psycopg2-binary', '2.9.11'),
    ('HTTP Client', 'httpx', '0.28.1'),
    ('Encryption', 'cryptography', '46.0.5'),
    ('Image Processing', 'Pillow', '12.1.1'),
    ('Spreadsheets', 'openpyxl', '3.1.5'),
    ('OCR', 'pytesseract', '0.3.13'),
    ('Network Scan', 'python-nmap', '0.7.1'),
    ('SMTP', 'aiosmtplib', '5.1.0'),
    ('SSE', 'sse-starlette', '2.2.1'),
]

apply_header(ws1, ['Layer', 'Component', 'Version'])
for i, (layer, comp, ver) in enumerate(tech_stack, 2):
    for c, val in enumerate([layer, comp, ver], 1):
        cell = ws1.cell(row=i, column=c, value=val)
        cell.font = DATA_FONT
        cell.border = THIN_BORDER
        if i % 2 == 0:
            cell.fill = ALT_FILL

ws1.column_dimensions['A'].width = 18
ws1.column_dimensions['B'].width = 22
ws1.column_dimensions['C'].width = 22


# ── Sheet 2: Tables Summary ──
ws2 = wb.create_sheet('Tables Summary')
ws2.sheet_properties.tabColor = '2E75B6'

table_col_counts = {}
for r in rows:
    t = r[0].strip()
    table_col_counts[t] = table_col_counts.get(t, 0) + 1

apply_header(ws2, ['#', 'Table Name', 'Category', 'Columns'])
sorted_tables = sorted(table_col_counts.keys())
for i, tname in enumerate(sorted_tables, 1):
    r = i + 1
    cat = TABLE_CATEGORIES.get(tname, 'Other')
    for c, val in enumerate([i, tname, cat, table_col_counts[tname]], 1):
        cell = ws2.cell(row=r, column=c, value=val)
        cell.font = DATA_FONT
        cell.border = THIN_BORDER
        if r % 2 == 0:
            cell.fill = ALT_FILL

ws2.column_dimensions['A'].width = 6
ws2.column_dimensions['B'].width = 32
ws2.column_dimensions['C'].width = 20
ws2.column_dimensions['D'].width = 10
ws2.auto_filter.ref = f'A1:D{len(sorted_tables)+1}'


# ── Sheet 3: Full Schema ──
ws3 = wb.create_sheet('Full Schema')
ws3.sheet_properties.tabColor = '548235'

apply_header(ws3, ['Table', 'Category', 'Field', 'Data Type', 'Max Length', 'Nullable', 'Default'])

r = 2
prev_table = ''
for row_data in rows:
    table = row_data[0].strip()
    field = row_data[1].strip()
    dtype = row_data[2].strip()
    maxlen = row_data[3].strip() if row_data[3].strip() else ''
    nullable = row_data[4].strip()
    default = row_data[5].strip() if len(row_data) > 5 else ''
    cat = TABLE_CATEGORIES.get(table, 'Other')

    # Friendly type names
    if dtype == 'character varying' and maxlen:
        friendly_type = f'varchar({maxlen})'
    elif dtype == 'timestamp without time zone':
        friendly_type = 'timestamp'
    elif dtype == 'timestamp with time zone':
        friendly_type = 'timestamptz'
    elif dtype == 'double precision':
        friendly_type = 'float8'
    else:
        friendly_type = dtype

    is_pk = (field == 'id' and 'nextval' in default)
    is_new_table = (table != prev_table and prev_table != '')

    vals = [table, cat, field, friendly_type, maxlen, nullable, default]
    for c, val in enumerate(vals, 1):
        cell = ws3.cell(row=r, column=c, value=val)
        cell.border = THIN_BORDER
        cell.font = PK_FONT if is_pk else DATA_FONT
        if is_new_table:
            cell.fill = TABLE_SEP_FILL
        elif r % 2 == 0:
            cell.fill = ALT_FILL

    prev_table = table
    r += 1

ws3.column_dimensions['A'].width = 28
ws3.column_dimensions['B'].width = 18
ws3.column_dimensions['C'].width = 28
ws3.column_dimensions['D'].width = 16
ws3.column_dimensions['E'].width = 12
ws3.column_dimensions['F'].width = 10
ws3.column_dimensions['G'].width = 44
ws3.auto_filter.ref = f'A1:G{r-1}'
ws3.freeze_panes = 'A2'


# ── Sheet 4: Data Types ──
ws4 = wb.create_sheet('Data Types')
ws4.sheet_properties.tabColor = 'BF8F00'

type_data = [
    ('integer', 'int', 'Primary keys (auto-increment), foreign keys, counts, quantities'),
    ('character varying(N)', 'varchar', 'Most string fields (N = 8 to 512)'),
    ('text', 'text', 'Notes, descriptions, addresses, long-form content'),
    ('boolean', 'bool', 'Flags (is_active, dismissed, permission toggles)'),
    ('timestamp without time zone', 'timestamp', 'created_at, updated_at, last_seen, last_login'),
    ('timestamp with time zone', 'timestamptz', 'error_log.created_at (only instance)'),
    ('date', 'date', 'Purchase dates, warranty dates, shipping dates'),
    ('numeric', 'numeric', 'Money fields (prices, costs, values)'),
    ('double precision', 'float8', 'Data completeness scores, geo coordinates'),
    ('jsonb', 'jsonb', 'Structured data (audit diffs, SKU requirements, provisioning stages)'),
    ('bytea', 'bytea', 'Fernet-encrypted credentials (username, password, notes)'),
]

apply_header(ws4, ['PostgreSQL Type', 'Shorthand', 'Usage'])
for i, (pgtype, short, usage) in enumerate(type_data, 2):
    for c, val in enumerate([pgtype, short, usage], 1):
        cell = ws4.cell(row=i, column=c, value=val)
        cell.font = DATA_FONT
        cell.border = THIN_BORDER
        if i % 2 == 0:
            cell.fill = ALT_FILL

ws4.column_dimensions['A'].width = 32
ws4.column_dimensions['B'].width = 14
ws4.column_dimensions['C'].width = 65


# Save
path = r'C:\Users\you\Company\asset-tracker\asset-tracker\docs\Asset_Tracker_Schema_Reference.xlsx'
wb.save(path)
print(f'Saved: {path}')
print(f'Sheets: Tech Stack, Tables Summary ({len(sorted_tables)} tables), Full Schema ({len(rows)} columns), Data Types')
