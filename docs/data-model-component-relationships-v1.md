# Data Model Design: Component-to-Device Relationships

**the company — Hardware Asset Tracker**
Version 1.0 | Internal Reference

---

## 1. Purpose & Scope

This document defines the database design for tracking hardware components inside parent devices — specifically GPUs, storage drives, and RAM inside Edge Boxes and Desktop PCs. It covers the data model, migration approach, and implications for the dashboard and future integrations.

This design is intentionally scoped to what is needed now. Relationships for cameras, network equipment, and other categories are excluded from the initial implementation.

### 1.1 What This Solves

- Answer "which GPU is inside Edge Box EB-042?" without manual lookups
- Track component movement — a GPU pulled from one edge box and placed in another
- Flag edge boxes missing required components before deployment
- Support warranty tracking at the component level, not just the device level
- Enable fulfillment to verify component build specs before shipping

### 1.2 Out of Scope (This Version)

- Camera-to-edge-box relationships (planned, separate design pass)
- Network switch port mapping
- Component-level purchase orders (handled at device level for now)
- Intune sync for laptop components (laptops tracked as whole units only)

---

## 2. Current Data Model — Problems

Currently each device category (`edge_boxes`, `gpus`, `storage_drives`) lives in a flat table with no formal relationship between them.

| Problem | Current State | Impact |
|---|---|---|
| No parent-child link | GPUs table has no foreign key to edge_boxes | Cannot query "which box has this GPU" |
| No movement history | Status field only — no log of where a component was | Audit trail is lost when a component moves |
| No slot/position data | No way to record which PCIe slot a GPU occupies | Build verification is manual and error-prone |
| No build spec | Edge box has no defined required components | Cannot flag an incomplete build automatically |

---

## 3. Proposed Data Model

The solution uses two additions: a universal join table called `device_components` that links any component to any parent device, and an optional `edge_box_build_specs` table that defines what components a specific edge box model requires.

### 3.1 device_components — The Join Table

This is the core of the design. Instead of adding foreign keys to every component table (which would require modifying 16 existing tables), a single join table records all parent-child relationships.

| Column | Type | Required | Description |
|---|---|---|---|
| id | INTEGER PK | Yes | Auto-incrementing primary key |
| parent_table | VARCHAR(50) | Yes | Table name of the parent device e.g. `edge_boxes` |
| parent_id | INTEGER | Yes | ID of the parent device in its table |
| component_table | VARCHAR(50) | Yes | Table name of the component e.g. `gpus` |
| component_id | INTEGER | Yes | ID of the component in its table |
| slot_label | VARCHAR(50) | No | Physical slot or position e.g. `PCIe x16 Slot 1` |
| installed_date | DATE | No | Date component was installed into this parent |
| removed_date | DATE | No | Date component was removed — NULL if still installed |
| installed_by | VARCHAR(100) | No | Name or username of the person who made the change |
| notes | TEXT | No | Reason for install or removal, any relevant context |
| created_at | TIMESTAMP | Yes | Auto-set on record creation |

> **Note:** A component with `removed_date = NULL` is currently installed. A component with a `removed_date` value has been removed. This gives full movement history without a separate audit table.

#### Key Rules

- A component can only be installed in one parent at a time — enforced by checking that no active record (`removed_date IS NULL`) exists for the component before inserting a new one
- Removing a component sets `removed_date` on the existing record — it does NOT delete the record
- `parent_table` and `component_table` use the actual database table names for consistency with existing `TABLE_MODELS`

### 3.2 Valid Parent-Component Combinations (MVP Scope)

| Parent Device | parent_table | Allowed Components | component_table |
|---|---|---|---|
| Edge Box | edge_boxes | GPU | gpus |
| Edge Box | edge_boxes | Storage Drive | storage_drives |
| Edge Box | edge_boxes | RAM / Memory | ram_modules* |
| Desktop PC | computers | GPU | gpus |
| Desktop PC | computers | Storage Drive | storage_drives |
| Desktop PC | computers | RAM / Memory | ram_modules* |

> **Note:** RAM modules are not currently a tracked category in the database. A new `ram_modules` table will need to be created as part of this migration (Migration 025 or similar). If RAM tracking is not immediately needed, this row can be deferred.

### 3.3 edge_box_build_specs — Optional Build Requirements

This table defines what components a given edge box model should have. It enables automatic flagging of incomplete builds before shipping.

| Column | Type | Required | Description |
|---|---|---|---|
| id | INTEGER PK | Yes | Auto-incrementing primary key |
| model_name | VARCHAR(100) | Yes | Edge box model identifier e.g. `EDGE-8` |
| component_table | VARCHAR(50) | Yes | Which component category is required |
| quantity_required | INTEGER | Yes | How many of this component the model needs |
| component_subtype | VARCHAR(100) | No | Optional: specific model or spec required e.g. `A-1000` |
| notes | TEXT | No | Any clarification on the requirement |

> **Note:** This table is optional for MVP. It becomes useful once you have consistent edge box models and want to automate pre-ship build verification in the Fulfillment pipeline.

---

## 4. Edge Box Classification: Lab vs Customer-Deployed

Based on the current approach, an edge box is considered customer-facing if it is assigned to a site. There is no separate field needed — `site_id` being populated (or NULL) is the distinguishing factor.

| Classification | site_id Value | Meaning |
|---|---|---|
| Lab / Internal | NULL | Not assigned to any customer site — in lab, staging, or storage |
| Customer-Deployed | Populated | Assigned to a customer site — considered production |

### Dashboard Metric Implications

- **Edge Boxes Deployed** = `COUNT of edge_boxes WHERE site_id IS NOT NULL`
- **Edge Boxes in Lab** = `COUNT of edge_boxes WHERE site_id IS NULL AND status != 'retired'`
- These two metrics replace "Assigned to Sites %" on the dashboard — they are specific to Edge Boxes, not all 265 devices

> **Note:** Do not use the status field alone to classify lab vs deployed — a box with status `brand lab` that also has a `site_id` is an edge case that would be misclassified. Site assignment is the authoritative signal.

---

## 5. Migration Plan

Following the existing numbered migration pattern used throughout the app.

| Migration | File | What It Does |
|---|---|---|
| 024 | 024_device_components.py | CREATE TABLE device_components with all columns and indexes |
| 025 | 025_ram_modules.py | CREATE TABLE ram_modules (defer if RAM tracking not immediate) |
| 026 | 026_build_specs.py | CREATE TABLE edge_box_build_specs (defer until model specs defined) |

### 5.1 Migration 024 — device_components Table

```sql
CREATE TABLE IF NOT EXISTS device_components (
    id               SERIAL PRIMARY KEY,
    parent_table     VARCHAR(50)  NOT NULL,
    parent_id        INTEGER      NOT NULL,
    component_table  VARCHAR(50)  NOT NULL,
    component_id     INTEGER      NOT NULL,
    slot_label       VARCHAR(50),
    installed_date   DATE,
    removed_date     DATE,
    installed_by     VARCHAR(100),
    notes            TEXT,
    created_at       TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_active_component
        UNIQUE (component_table, component_id, removed_date)
);

CREATE INDEX IF NOT EXISTS idx_dc_parent
    ON device_components (parent_table, parent_id);

CREATE INDEX IF NOT EXISTS idx_dc_component
    ON device_components (component_table, component_id);
```

> **Note:** The UNIQUE constraint on `(component_table, component_id, removed_date)` prevents a component from being actively installed in two parents simultaneously. NULL `removed_date` means currently installed.

---

## 6. SQLAlchemy Model (app/models.py)

Add this class to `models.py` alongside the existing device models:

```python
class DeviceComponent(Base):
    __tablename__ = 'device_components'

    id              = Column(Integer, primary_key=True)
    parent_table    = Column(String(50), nullable=False)
    parent_id       = Column(Integer, nullable=False)
    component_table = Column(String(50), nullable=False)
    component_id    = Column(Integer, nullable=False)
    slot_label      = Column(String(50))
    installed_date  = Column(Date)
    removed_date    = Column(Date)
    installed_by    = Column(String(100))
    notes           = Column(Text)
    created_at      = Column(DateTime, default=datetime.utcnow)

    @property
    def is_active(self):
        return self.removed_date is None
```

---

## 7. Common Query Patterns

### 7.1 Get All Active Components in an Edge Box

```python
components = db.query(DeviceComponent).filter(
    DeviceComponent.parent_table == 'edge_boxes',
    DeviceComponent.parent_id   == edge_box_id,
    DeviceComponent.removed_date == None
).all()
```

### 7.2 Find Which Edge Box a GPU is Currently In

```python
gpu_location = db.query(DeviceComponent).filter(
    DeviceComponent.component_table == 'gpus',
    DeviceComponent.component_id   == gpu_id,
    DeviceComponent.removed_date   == None
).first()

# gpu_location.parent_table == 'edge_boxes'
# gpu_location.parent_id    == the edge box's ID
```

### 7.3 Move a Component — Remove from Old, Install in New

```python
from datetime import date

# Step 1: Close the existing active record
existing = db.query(DeviceComponent).filter(
    DeviceComponent.component_table == 'gpus',
    DeviceComponent.component_id   == gpu_id,
    DeviceComponent.removed_date   == None
).first()
if existing:
    existing.removed_date  = date.today()
    existing.installed_by  = current_user

# Step 2: Create new active record for the new parent
new_link = DeviceComponent(
    parent_table    = 'edge_boxes',
    parent_id       = new_edge_box_id,
    component_table = 'gpus',
    component_id    = gpu_id,
    installed_date  = date.today(),
    installed_by    = current_user,
)
db.add(new_link)
db.commit()
```

---

## 8. Dashboard Metrics — Revised

| Metric | How It's Computed | Category Scope | Replaces |
|---|---|---|---|
| Total Devices | COUNT(*) across all 16 tables | All | Total Devices |
| Active / Online | COUNT WHERE status IN ('production', 'deployed') | All | Active / Online |
| Incomplete Records | Devices missing any REQUIRED_FIELDS value | All | Incomplete Data |
| Edge Boxes Deployed | COUNT edge_boxes WHERE site_id IS NOT NULL | Edge Boxes only | Assigned to Sites % |
| Edge Boxes in Lab | COUNT edge_boxes WHERE site_id IS NULL AND status != 'retired' | Edge Boxes only | NEW |
| In Fulfillment | COUNT active fulfillment orders | Orders | Tracked Value |

> **Note:** "Needs Attention" (currently 0) should be deferred until alert rules are defined. Showing 0 with no context is not useful. Consider replacing it with "Unlocated Devices" — devices with no room, rack, or parent device assignment.

---

## 9. UI Changes Needed

### 9.1 Edge Box Detail Page

- Add a "Components" section showing installed GPU, storage, and RAM with slot labels
- Add Install / Remove buttons that write to `device_components`
- Show component history — all past components with install/remove dates

### 9.2 GPU / Storage / RAM Detail Pages

- Add a "Current Location" field showing which Edge Box or Desktop PC this is installed in
- If uninstalled, show "Available — not currently installed in any device"
- Show installation history

### 9.3 Asset Triage

- Add a check: Edge Boxes with no GPU installed flagged as incomplete build
- Requires `edge_box_build_specs` table — defer until Migration 026 is run

### 9.4 Dashboard

- Replace "Assigned to Sites %" with "Edge Boxes Deployed" and "Edge Boxes in Lab" count cards
- Replace "Needs Attention: 0" with "Unlocated Devices" or defer until alert rules exist

---

## 10. Implementation Order

1. **Write and run Migration 024** (`device_components` table)
   - Follow existing migration pattern in `migrations/` directory
   - Push to both remotes and pull on the server before running

2. **Add `DeviceComponent` model to `app/models.py`**
   - Include `is_active` property
   - Verify `Base.metadata.create_all()` does not conflict with migration

3. **Add components section to Edge Box detail/edit page**
   - Read-only list first — show what is currently installed
   - Add install/remove actions in a second pass

4. **Update dashboard metrics**
   - Replace "Assigned to Sites %" with deployed/lab split
   - Update banner and triage counts

5. **Decide on RAM tracking and run Migration 025 if needed**
   - If RAM is not tracked now, skip and revisit when needed

---

> This document should be updated as implementation progresses. Version 2.0 will cover camera-to-edge-box relationships and Salesforce/Zendesk integration data contracts.
