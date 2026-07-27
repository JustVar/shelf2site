# Spreadsheet Import Improvements

## Overview

The enhanced import script (`import_spreadsheet_v2.py`) adds three major improvements over the original. (For category-specific imports, see also `import_all_categories.py`, `import_edge_boxes.py`, and `import_part_numbers.py` in `scripts/`.)

1. **Validation/Preview Mode** - See what would change without modifying the database
2. **Incremental Updates** - Update existing devices instead of requiring empty tables
3. **Better Error Handling** - Detailed per-row error tracking with line numbers

## Features

### 1. Validation/Preview Mode (--dry-run)

Preview what the import would do without making any database changes:

```bash
docker compose exec app python scripts/import_spreadsheet_v2.py --dry-run
# OR
docker compose exec app python scripts/import_spreadsheet_v2.py --validate
```

**Output Example:**
```
🔍 VALIDATION MODE (DRY RUN) - No database changes will be made
Processing 52 edge box rows...
Processing 48 camera rows...

edge_boxes:
  Added:     12
  Updated:   38
  Skipped:    2
  Errors:     0

cameras:
  Added:      5
  Updated:   43
  Skipped:    0
  Errors:     0

TOTAL:
  Added:            17
  Updated:          81
  Skipped:           2
  Credentials:      48
```

### 2. Incremental Updates

The new script automatically:
- **Updates** existing devices (matched by serial number)
- **Adds** new devices not yet in the database
- **Skips** rows with missing required fields

**Before (Original Script):**
- Only worked on empty tables
- Required manual database wipe to re-import
- No way to add new devices without full re-import

**After (New Script):**
- Works with existing data
- Updates changed fields on existing devices
- Adds only new devices

### 3. Detailed Error Handling

Every import operation is wrapped in try-catch with context:

```
cameras:
  Added:      5
  Updated:   40
  Skipped:    0
  Errors:     3 ⚠️
    Row 45 (CAM-12345): Invalid IP address format
    Row 67 (CAM-67890): Missing required field 'Model'
    Row 89 (N/A): Serial number cannot be empty
```

**Error Context Includes:**
- Row number in spreadsheet (for easy location)
- Serial number (if available)
- Specific error message
- Stack trace (in verbose mode)

### 4. Import Statistics

Detailed summary shows exactly what happened:

| Metric | Description |
|--------|-------------|
| **Added** | New devices inserted into database |
| **Updated** | Existing devices with modified data |
| **Skipped** | Rows with missing required fields (not errors) |
| **Errors** | Rows that failed with exceptions |
| **Credentials** | Encrypted credentials queued for insertion |

### 5. Automatic OUI Allowlist Management

**NEW:** The OUI allowlist now grows automatically instead of filtering devices:

**How it works:**
- **Network Scanner**: ALL discovered devices go to pending queue (no OUI filtering)
- **Device Approval**: When a device is approved from pending → OUI auto-added to allowlist
- **Spreadsheet Import**: When devices are imported → OUIs auto-added to allowlist
- **Result**: OUI allowlist becomes a growing catalog of known manufacturers

**Benefits:**
- No need to manually maintain OUI list
- Automatically learns from your inventory
- No devices blocked by missing OUI entries
- OUI list grows organically with your hardware

## Usage

### Standard Import (With Incremental Updates)

```bash
# Import with updates to existing devices
docker compose exec app python scripts/import_spreadsheet_v2.py

# The script will:
# - Update existing devices by serial number
# - Add new devices
# - Show summary of changes
# - Commit to database
```

### Validation Before Import

```bash
# Step 1: Preview changes
docker compose exec app python scripts/import_spreadsheet_v2.py --dry-run

# Review the output - check for errors

# Step 2: If everything looks good, run actual import
docker compose exec app python scripts/import_spreadsheet_v2.py
```

### Handling Errors

If you see errors in the output:

1. Note the row numbers reported
2. Open the Excel file
3. Go to the specific row (add 1 for header row)
4. Fix the data issue
5. Re-run import

**Common Issues:**
- Missing serial numbers
- Invalid date formats
- Malformed IP addresses
- Missing required fields for the device type

## Implementation Status

### ✅ Completed Features
- Import framework with validation and incremental updates
- Error tracking and reporting
- Dry-run/preview mode
- Import statistics

### ✅ Implemented Tables (2/15)
- Edge Boxes
- Cameras

### 🔜 Remaining Tables (13)
The following tables need to be migrated to the new import pattern:
- Trade Show Boxes
- GPUs
- Part Numbers
- Monitors
- Computers (with Intune merge)
- Phones
- Mobile Devices
- Network Equipment
- Access Control
- Webcams
- Printers
- Office Equipment
- NAS Devices (if applicable)

**Migration Pattern:** Each table needs an `import_{table}_incremental()` function that:
1. Queries for existing device by serial number
2. Updates existing device OR creates new one
3. Tracks stats (added/updated/skipped/errors)
4. Handles credentials queue if needed
5. Wraps each row in try-except for error capture

## Example: Migrating a Table

Here's how to migrate `import_trade_show_boxes()` to the new pattern:

**Original (import_spreadsheet.py):**
```python
def import_trade_show_boxes(wb, session) -> int:
    count = 0
    for row in _read_sheet(wb, "Trade Show Boxes"):
        obj = TradeShowBox(serial=_to_str(row.get("Device Serial")), ...)
        session.add(obj)
        count += 1
    return count
```

**New Pattern (import_spreadsheet_v2.py):**
```python
def import_trade_show_boxes_incremental(wb, session, ctx: ImportContext) -> ImportStats:
    stats = ctx.get_stats("trade_show_boxes")
    rows = _read_sheet(wb, "Trade Show Boxes")

    for row in rows:
        row_num = row.get("__row_num__", "?")
        try:
            serial = _to_str(row.get("Device Serial"))
            if not serial:
                stats.skipped += 1
                continue

            # Check if exists
            existing = session.query(TradeShowBox).filter(TradeShowBox.serial == serial).first()

            device_data = {
                "serial": serial,
                "part_number": _to_str(row.get("Part Number")),
                # ... all other fields
                "last_updated": datetime.utcnow(),
            }

            if existing:
                # Update
                for key, value in device_data.items():
                    setattr(existing, key, value)
                existing.data_completeness = compute_completeness(existing)
                stats.updated += 1
                if ctx.dry_run:
                    session.expunge(existing)
            else:
                # Insert
                device = TradeShowBox(**device_data)
                device.data_completeness = compute_completeness(device)
                if not ctx.dry_run:
                    session.add(device)
                stats.added += 1

        except Exception as e:
            stats.add_error(row_num, serial, str(e))
            continue

    return stats
```

## Testing

### Test on Development

```bash
# 1. Backup database first
pg_dump asset_tracker > backup_$(date +%Y%m%d).sql

# 2. Test dry-run mode
docker compose exec app python scripts/import_spreadsheet_v2.py --dry-run

# 3. If validation passes, run actual import
docker compose exec app python scripts/import_spreadsheet_v2.py

# 4. Verify changes in dashboard
open https://localhost:8443/assettracker/
```

## Roadmap

### Phase 1: Core Framework ✅
- Validation/preview mode
- Incremental update logic
- Error handling and reporting
- Import statistics

### Phase 2: Table Migration (In Progress)
- [x] Edge Boxes
- [x] Cameras
- [ ] All remaining 13 tables

### Phase 3: Advanced Features (Future)
- Conflict resolution (manual edits vs spreadsheet data)
- Timestamp-based smart updates (only update if spreadsheet is newer)
- Rollback functionality (undo last import)
- Import history tracking
- Web UI for import (upload + preview + import)
- Scheduled imports (cron job for automatic updates)

## Benefits

**For Regular Updates:**
- No need to wipe database
- Preserves manual edits
- See changes before applying
- Clear audit trail

**For Data Quality:**
- Catch errors before they reach database
- Fix source data issues early
- Detailed error reporting
- Row-level traceability

**For Confidence:**
- Preview mode eliminates risk
- Rollback capability (future)
- Detailed logs of what changed
- Statistics for reporting

---

**Next Steps:**
1. Complete remaining 13 table migrations
2. Test with full spreadsheet on dev environment
3. Deploy to apphost for production use
4. Consider automated scheduled imports
