# Photo Storage Cleanup Plan

## Current Status (Feb 2026)

**Storage:** 870GB available on `/data` HDD
**Growth Rate:** ~50MB/day estimated (10 photos @ 5MB each)
**Longevity:** 47+ years at current rate
**Policy:** Indefinite storage (no automatic cleanup)

**Decision:** Monitor storage via admin dashboard, implement cleanup when retention policy is defined.

---

## Future Cleanup Options

### Option 1: Age-Based Deletion
**Description:** Automatically delete photos older than a specified age.

**Implementation:**
- Configurable retention period (e.g., 90 days, 1 year, 2 years)
- Scheduled cleanup job (daily cron)
- Exceptions for flagged photos (RMA, warranty cases)

**Pros:**
- Simple to implement and understand
- Predictable storage usage
- Automatic maintenance

**Cons:**
- May delete useful reference photos
- No context awareness

**SQL Query:**
```sql
DELETE FROM intake_photos
WHERE created_at < NOW() - INTERVAL '90 days'
AND device_table IS NULL  -- Not linked to a device
```

---

### Option 2: Event-Based Deletion
**Description:** Delete photos when the associated device is added to inventory or dismissed.

**Implementation:**
- Trigger on device approval/dismissal
- Optional grace period (e.g., keep for 30 days after approval)
- Keep photos for devices in Review Queue indefinitely

**Pros:**
- Context-aware
- Photos available during review process
- Cleans up automatically as workflow completes

**Cons:**
- Photos deleted even if potentially useful later
- Requires careful trigger implementation

**Workflow:**
1. Photo uploaded during receiving
2. Device reviewed and approved → added to inventory
3. After 30 days, photo auto-deleted
4. Exception: If device linked to RMA/warranty, keep photo

---

### Option 3: Manual Cleanup UI
**Description:** Admin interface to browse, filter, and selectively delete photos.

**Features:**
- Grid view of all photos with thumbnails
- Filter by: age, size, linked device, event
- Bulk select and delete
- Preview before deletion
- Confirmation dialog

**Pros:**
- Complete control
- Can review before deleting
- Selective retention

**Cons:**
- Manual effort required
- Risk of forgetting to clean up

---

### Option 4: Compressed Archives
**Description:** Move old photos to compressed ZIP files for long-term storage.

**Implementation:**
- Monthly job: find photos older than 6 months
- Compress by month (e.g., `photos_2025_06.zip`)
- Store archives in `/data/asset-tracker/archives/`
- Database flag: `archived=true, archive_file='2025_06.zip'`
- Extract on demand when photo is viewed

**Pros:**
- Preserves all photos
- Reduces disk usage (50-70% compression)
- Can still access if needed

**Cons:**
- More complex to implement
- Slower access to archived photos
- Requires extraction logic

**Storage Savings:**
- 10GB of JPEGs → ~3-5GB compressed
- Effective 2-3x capacity increase

---

### Option 5: Selective Retention
**Description:** Keep photos only for specific use cases.

**Retention Rules:**
- **Keep indefinitely:**
  - Devices with active RMA cases
  - Devices with warranty issues
  - Devices flagged for reference
  - Edge boxes and high-value equipment

- **Delete after 90 days:**
  - Dismissed/rejected devices
  - Duplicate photos
  - Photos not linked to any device

- **Delete after 1 year:**
  - Routine intake photos
  - Photos of decommissioned devices

**Implementation:**
- Device model includes `photo_retention_policy` field
- Cleanup job respects retention policy per device type
- Admin can flag specific photos as "keep forever"

**Pros:**
- Balances storage and utility
- Keeps important photos
- Reduces manual review

**Cons:**
- Complex rule engine
- Requires policy decisions per device type

---

## Recommended Approach (When Needed)

**Phase 1: Monitoring (Current)**
- Storage monitor dashboard ✅
- Alert at 50% disk usage
- Manual review quarterly

**Phase 2: Simple Cleanup (Implement at 50% usage)**
- Age-based deletion: 1 year retention for unlinked photos
- Keep photos linked to devices indefinitely
- Manual cleanup UI for selective deletion

**Phase 3: Advanced (Implement at 70% usage)**
- Compressed archives for photos older than 6 months
- Selective retention by device type
- Automated cleanup with exceptions

---

## Implementation Checklist (Future)

### Phase 1: Monitoring ✅
- [x] Storage dashboard
- [x] Disk usage stats
- [x] Growth rate calculation
- [x] Time-until-full estimate

### Phase 2: Basic Cleanup
- [ ] Age-based deletion config (`.env` setting)
- [ ] Scheduled cleanup job (daily cron)
- [ ] Cleanup dry-run mode (preview before delete)
- [ ] Audit logging for deletions
- [ ] Manual cleanup UI (browse and delete)

### Phase 3: Advanced
- [ ] Compression and archiving
- [ ] Selective retention rules
- [ ] Photo flagging system (keep forever)
- [ ] Device-type retention policies
- [ ] Extract-on-demand for archived photos

---

## Notes

- Current storage is more than adequate (47+ years at current rate)
- Implement cleanup only when:
  - Disk usage exceeds 50% (430GB used)
  - Compliance requires photo deletion
  - Performance degradation observed
- Always include audit logging for any deletions
- Provide dry-run/preview mode before actual deletion
- Consider backup before implementing automated cleanup

---

**Last Updated:** February 12, 2026
**Status:** Monitoring phase, no cleanup needed
