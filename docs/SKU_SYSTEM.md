# SKU System — Legacy to 2026 Migration

**Date**: 2026-02-18
**Context**: Hardware Asset Tracker edge box inventory management

---

## Overview

Edge box SKUs evolved from legacy PVA-* format to new 2026 EDGE* format. The asset tracker supports both via the **SKU version tracking system** (Migration 007).

---

## SKU Formats

### Legacy Format (Pre-2026)
**Pattern**: `PVA-{channels}-{retention}{RAID}`

**Components**:
- **Prefix**: PVA (Processing + Video Analytics)
- **Channels**: 10, 25, 50, 75, 100, 200, 300
- **Retention**: 30, 60, 90 (days)
- **RAID**: R5 (RAID5, retired), R6 (RAID6), NR (No RAID), SFF (Small Form Factor NR)

**Examples**:
- `PVA-25-30NR` → 25 channels, 30-day retention, no RAID
- `PVA-100-60R6` → 100 channels, 60-day retention, RAID6
- `PVA-50-90R5` → 50 channels, 90-day retention, RAID5 (retired)

### 2026 Format
**Pattern**: `EDGE{channels}-{storage}TB-{RAID}`

**Components**:
- **Prefix**: EDGE (Edge computing platform)
- **Channels**: 10, 25, 50, 100, 200, 300 (no 75-channel tier)
- **Storage**: Total usable TB (28, 36, 56, 72, 84, 108, 112, 120, 140, 144, etc.)
- **RAID**: NR (No RAID), Z2 (ZFS RAID-Z2, RAID6-class)

**Examples**:
- `EDGE25-56TB-NR` → 25 channels, 56TB usable, no RAID
- `EDGE100-140TB-Z2` → 100 channels, 140TB usable, ZFS RAID-Z2
- `EDGE50-144TB-NR` → 50 channels, 144TB usable, no RAID

### Modular Format (Future/Optional)
**Processing SKU**: `EDGE{channels}-{RAID}` (e.g., EDGE25-NR, EDGE100-Z2)
**Storage SKU**: `STOR-HDD-{size}TB` or `STOR-PACK-{size}TB`

---

## Key Changes in 2026 SKUs

| Aspect | Legacy | 2026 |
|---|---|---|
| Prefix | PVA | EDGE |
| Storage encoding | Retention days (30/60/90) | Total usable TB |
| Channel tiers | 10/25/50/75/100/200/300 | 10/25/50/100/200/300 (no 75) |
| RAID options | R5/R6/NR/SFF | NR/Z2 (R5 retired) |
| Form factors | Implicit (SFF suffix) | Explicit chassis (1U/2U in BOM) |

---

## Conversion Mapping

### Common Conversions

| Legacy SKU | New SKU | Notes |
|---|---|---|
| PVA-25-30NR | EDGE25-56TB-NR | Standard 25-channel, 1U |
| PVA-25-30SFF | EDGE25-56TB-NR | SFF variant retired |
| PVA-50-60NR | EDGE50-144TB-NR | Standard 50-channel, 2U |
| PVA-100-30NR | EDGE100-168TB-NR | Standard 100-channel, 2U |
| PVA-25-30R6 | PVA50-84TB-Z2 | Compute tier upsized 25→50 |
| PVA-50-90R5 | PVA100-180TB-Z2 | RAID5 retired → Z2, compute upsized |

**Full mapping**: See `app/sku_conversion.py` (46 mappings)

### Conversion Rules

1. **RAID5 → RAID-Z2**: All R5 SKUs map to Z2 equivalents
2. **Compute tier upsizing**: Many old SKUs map to higher channel counts (e.g., 25→50, 100→200)
3. **75-channel retirement**: No EDGE75-* tier; maps to EDGE50-* or EDGE100-*
4. **Multi-unit splits**: High-capacity old SKUs sometimes map to multiple new units (e.g., PVA-300-60NR → 3× EDGE100-NR)
5. **SFF consolidation**: PVA-25-30SFF maps to standard EDGE25-56TB-NR (SFF no longer separate SKU)

---

## Database Implementation

### Migration 007
```sql
ALTER TABLE edge_boxes
ADD COLUMN sku_version VARCHAR(16) DEFAULT 'legacy';

UPDATE edge_boxes
SET sku_version = CASE
    WHEN part_number LIKE 'PVA-%' THEN 'legacy'
    WHEN part_number LIKE 'EDGE%' THEN '2026'
    ELSE 'legacy'
END;

CREATE INDEX idx_edge_boxes_sku_version ON edge_boxes(sku_version);
```

### Model Field
```python
class EdgeBox(InventoryMixin, Base):
    ...
    part_number = Column(String(64), nullable=True)
    sku_version = Column(String(16), default="legacy", nullable=False)
    ...
```

---

## UI Differentiation

### SKU Version Badges

**Legacy SKU** (gray gradient):
```html
<span class="badge-sku-legacy">LEGACY</span>
```

**2026 SKU** (blue gradient):
```html
<span class="badge-sku-2026">2026</span>
```

### Where Badges Appear
- **Provisioning dropdown**: Edge box selection shows SKU badge next to serial/part number
- **Provisioning detail**: SKU version displayed in device info card
- **Inventory tables**: Part number column includes SKU badge
- **Device edit forms**: SKU version shown as read-only field

---

## API Integration

### Device Dropdown Endpoint
`GET /api/provisioning/devices/edge_boxes`

**Response**:
```json
{
  "devices": [
    {
      "id": 123,
      "name": "867TY24 (PVA-25-30NR) <span class=\"badge-sku-legacy\">LEGACY</span>",
      "sku_version": "legacy"
    },
    {
      "id": 456,
      "name": "9X2P45 (EDGE50-112TB-NR) <span class=\"badge-sku-2026\">2026</span>",
      "sku_version": "2026"
    }
  ]
}
```

---

## Utilities

### SKU Conversion Functions

**File**: `app/sku_conversion.py`

```python
from app.sku_conversion import (
    convert_legacy_sku,
    is_legacy_sku,
    is_2026_sku,
    get_sku_version,
    extract_sku_info,
)

# Convert old to new
new_sku = convert_legacy_sku("PVA-25-30NR")  # Returns "EDGE25-56TB-NR"

# Check SKU format
is_old = is_legacy_sku("PVA-50-60R6")  # Returns True
is_new = is_2026_sku("EDGE100-168TB-NR")  # Returns True

# Get version string
version = get_sku_version("EDGE25-56TB-NR")  # Returns "2026"

# Parse SKU components
info = extract_sku_info("EDGE100-168TB-NR")
# Returns: {
#   "channels": "100",
#   "storage_tb": "168",
#   "raid_type": "NR",
#   "version": "2026",
#   "chassis": "2U"
# }
```

---

## Zendesk Integration

### Ticket Field Mapping

**Zendesk Custom Field**: "Service Type - VMS+AI" (ID: 26350801370900)

**Values** (legacy PVA SKUs):
- PVA-8-30NR, PVA-8-60NR, PVA-8-90NR
- PVA-16-30NR, PVA-16-60NR, PVA-16-90NR

**Auto-conversion workflow**:
1. User creates edge box provisioning and links Zendesk ticket
2. Fetch ticket via API: `GET /api/v2/tickets/{ticket_id}`
3. Extract "Service Type - VMS+AI" custom field value
4. Convert using `convert_legacy_sku()` → new SKU
5. Display both in provisioning record:
   - **Ticket SKU** (legacy): PVA-25-30NR `[LEGACY]`
   - **Inventory SKU** (new): EDGE25-56TB-NR `[2026]`

---

## BOM Reference

**File**: `SKU_BOM_Matrix_EDGE_Jan_2026.xlsx`

**Key fields**:
- UpTo_Ch (channels)
- Chassis (1U/2U)
- Bays/Pop (drive bays and populated drives)
- RAID (NR/Z2)
- Drive_Size_TB (14/18/20)
- Usable_Storage_TB (net capacity)
- CPU (Core i7-14700 / Xeon 4510Y)
- RAM (64GB / 128GB / 256GB ECC)
- GPU (RTX A1000 / RTX 2000 Ada)

---

## Best Practices

1. **New deployments**: Use 2026 EDGE* SKUs for all new edge boxes
2. **Legacy units**: Keep original PVA-* SKU in `part_number`, mark `sku_version='legacy'`
3. **Zendesk imports**: Auto-convert old SKUs when importing from tickets, display both
4. **Filtering**: Use `sku_version` field to filter legacy vs 2026 inventory
5. **Reporting**: Group by SKU version for migration tracking (% legacy vs % 2026)
6. **Documentation**: Link to this doc when explaining SKU badges to users

---

## Migration Progress Tracking

**Query to check SKU version distribution**:
```sql
SELECT
    sku_version,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
FROM edge_boxes
GROUP BY sku_version
ORDER BY sku_version;
```

**Example output**:
| sku_version | count | percentage |
|---|---|---|
| legacy | 45 | 78.9% |
| 2026 | 12 | 21.1% |

---

## Related Files

- **Migration**: `migrations/007_add_sku_version.py`
- **Model**: `app/models.py` (EdgeBox.sku_version)
- **Conversion**: `app/sku_conversion.py`
- **API**: `app/routes/provisioning.py` (device dropdown)
- **CSS**: `static/css/main.css` (.badge-sku-legacy, .badge-sku-2026)
- **Reference docs**:
  - `Downloads/Old_to_New_SKU_Crosswalk_v3.xlsx`
  - `Downloads/2026_SKUs_and_StoragePacks.xlsx`
  - `Downloads/SKU_BOM_Matrix_EDGE_Jan_2026.xlsx`

---

**Last updated**: 2026-02-18
**Next review**: When modular SKU system (EDGE*-NR + STOR-*) goes live
