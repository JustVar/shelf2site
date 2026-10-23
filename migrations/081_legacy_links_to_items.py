"""Migration 081: move every live legacy link onto items (legacy slice S2).

Data only. See docs/specs/retire-legacy-inventory.md sections 4 to 6a and
slice S2. Runs as ONE transaction. Without --apply it does all the work,
prints every count and rolls back (the dry run). With --apply it commits.

Rules, in order:
  snapshot  Classify every legacy link end (credentials, provisioning rows
            with no item_id, device_components parent and component). The
            fresh-run counts must match EXPECT_SNAPSHOT (taken after the R3
            deletes, 2026-09-28) or nothing is written.
  R2        Carry in CARRY_INS as new items. legacy_item_map records
            (legacy_table, legacy_id) -> item_id, rule 'R2'.
  R1        Any other legacy row a link needs resolves by serial:
            upper(trim()), ignoring NULL, empty and '-', exactly one item.
            Recorded in legacy_item_map, rule 'R1'.
  links     device_credentials, device_provisioning, device_warranties and
            device_assignments rows with item_id NULL get the resolved id.
  R4        device_components rows not yet done by migration 066 become
            'installed' events in item_schema.component_history, in the 066
            format and recorded in component_migration_map, so a re-run of
            either migration skips them. Components get status Installed.
            No row has removed_date set (READ 2026-09-28); one would abort.
  6a        RECATEGORISE: the confirmed item ids move to phone, printer,
            webcam and nas, each only from its expected current category.
  pending   pending_devices.suggested_category from suggested_table.

legacy_item_map has no foreign key to items, like csv_import_map, so it
never blocks an item delete. Re-runnable: a second --apply is a no-op.

Run:
    docker compose exec -T app python migrations/081_legacy_links_to_items.py
    docker compose exec -T app python migrations/081_legacy_links_to_items.py --apply
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

APPLY = "--apply" in sys.argv
PROVENANCE = "legacy slice S2, migration 081"

LEGACY_TABLES = [
    "edge_boxes", "gpus", "monitors", "computers", "phones", "mobile_devices",
    "cameras", "network_equipment", "access_control", "webcams", "printers",
    "office_equipment", "nas_devices", "nucs", "ups", "ram_modules", "cpus",
    "psus", "motherboards", "pc_cooling", "pc_accessories", "hard_drives",
]
SERIAL_COL = {"gpus": "gpu_serial"}

EXPECT_SNAPSHOT = {"one item": 62, "no item": 24, "no serial": 8}
EXPECT_ITEMS_BEFORE = 548

# R2 carry-ins (spec section 5, amended 2026-09-28: cameras 45 and 73 are
# already items 700 and 613, so they are not carried in).
CARRY_INS = (
    [("computers", i) for i in (28, 29)]
    + [("hard_drives", i) for i in range(7, 15)]
    + [("hard_drives", 19), ("edge_boxes", 41)]
    + [("nucs", i) for i in (12, 13, 14, 15)]
)

# Legacy status text -> item status (Jus, 2026-09-28). Hard drives inside
# a machine are set to Installed by R4, not here.
STATUS_MAP = {
    "in use": "Deployed",
    "customer lab": "Deployed",
    "brand inventory": "Unassigned",
    "in packaging": "Unassigned",
    "in device (dell machine)": "Unassigned",
}

# 6a, confirmed by Jus 2026-09-28: (item id, expected current category, new).
RECATEGORISE = (
    [(i, "office_equipment", "phone") for i in range(882, 889)]
    + [(i, "office_equipment", "printer") for i in (924, 925, 926)]
    + [(i, "pc_accessories", "webcam") for i in range(916, 924)]
    + [(929, "office_equipment", "webcam")]
    + [(i, "computer", "nas") for i in (773, 774, 775, 946)]
)

# Same vocabulary as app/containment.py UNIT_CATEGORIES after migration 080.
UNIT_CATEGORIES = {"edge_box", "cloud_box", "camera_c2c", "computer", "nas"}

# suggested_table -> item category (receiving's map plus legacy slice 6a).
SUGGESTED = {
    "edge_boxes": "edge_box", "gpus": "gpu", "monitors": "monitor",
    "computers": "computer", "nucs": "computer", "mobile_devices": "mobile_device",
    "phones": "phone", "cameras": "camera", "webcams": "webcam",
    "network_equipment": "network", "nas_devices": "nas",
    "access_control": "access_control", "office_equipment": "office_equipment",
    "printers": "printer", "ups": "ups", "ram_modules": "ram", "cpus": "cpu",
    "psus": "psu", "motherboards": "motherboard", "pc_cooling": "cpu_cooler",
    "pc_accessories": "pc_accessories", "hard_drives": "storage_drive",
}

MAP_DDL = """
CREATE TABLE IF NOT EXISTS public.legacy_item_map (
    legacy_table varchar(64) NOT NULL,
    legacy_id integer NOT NULL,
    item_id integer NOT NULL,
    rule varchar(8) NOT NULL,
    created_at timestamp DEFAULT now(),
    PRIMARY KEY (legacy_table, legacy_id)
)
"""


class Abort(Exception):
    pass


def q(conn, sql, **params):
    return conn.execute(text(sql), params)


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar()


def norm(s):
    if s is None:
        return None
    s = str(s).strip().upper()
    return None if s in ("", "-") else s


def legacy_serial(conn, table, lid):
    if table not in LEGACY_TABLES:
        raise Abort(f"unknown legacy table {table!r}")
    col = SERIAL_COL.get(table, "serial")
    row = q(conn, f"SELECT {col} FROM public.{table} WHERE id = :i", i=lid).first()
    if row is None:
        return False, None
    return True, norm(row[0])


def serial_match(conn, s):
    rows = q(conn, "SELECT id FROM item_schema.items WHERE upper(trim(item_sn)) = :s", s=s).fetchall()
    return [r[0] for r in rows]


def classify(conn, table, lid):
    exists, s = legacy_serial(conn, table, lid)
    if not exists:
        return "legacy row missing", None
    if s is None:
        return "no serial", None
    ids = serial_match(conn, s)
    if not ids:
        return "no item", None
    if len(ids) > 1:
        return "several items", None
    return "one item", ids[0]


def link_ends(conn):
    ends = []
    for r in q(conn, "SELECT id, parent_table, parent_id, component_table, component_id FROM device_components ORDER BY id"):
        ends.append(("dc_parent", r[0], r[1], r[2]))
        ends.append(("dc_component", r[0], r[3], r[4]))
    for r in q(conn, "SELECT id, device_table, device_id FROM device_credentials WHERE item_id IS NULL ORDER BY id"):
        ends.append(("credential", r[0], r[1], r[2]))
    for r in q(conn, "SELECT id, device_table, device_id FROM device_provisioning WHERE item_id IS NULL ORDER BY id"):
        ends.append(("provisioning", r[0], r[1], r[2]))
    for t in ("device_warranties", "device_assignments"):
        for r in q(conn, f"SELECT id, device_table, device_id FROM public.{t} WHERE item_id IS NULL ORDER BY id"):
            ends.append((t, r[0], r[1], r[2]))
    return ends


def mapped(conn, table, lid):
    return scalar(conn, "SELECT item_id FROM legacy_item_map WHERE legacy_table = :t AND legacy_id = :i", t=table, i=lid)


def resolve(conn, table, lid, record=True):
    hit = mapped(conn, table, lid)
    if hit:
        return hit
    result, item_id = classify(conn, table, lid)
    if result != "one item":
        return None
    if record:
        q(conn, "INSERT INTO legacy_item_map (legacy_table, legacy_id, item_id, rule) VALUES (:t, :i, :it, 'R1')",
          t=table, i=lid, it=item_id)
    return item_id


def site_id(conn, name):
    if not name or not str(name).strip():
        return None, None
    sid = scalar(conn, "SELECT id FROM sites WHERE is_active AND site_type <> 'customer_site' AND lower(name) = lower(:n)",
                 n=str(name).strip())
    return (sid, None) if sid else (None, str(name).strip())


def item_status(raw, default):
    if raw is None or not str(raw).strip():
        return default
    key = str(raw).strip().lower()
    if key not in STATUS_MAP:
        raise Abort(f"legacy status {raw!r} has no mapping")
    return STATUS_MAP[key]


def carry_in_fields(conn, table, lid):
    row = q(conn, f"SELECT * FROM public.{table} WHERE id = :i", i=lid).mappings().first()
    if row is None:
        raise Abort(f"carry-in {table}:{lid} does not exist")
    attrs = {"import_source": "legacy-item30", "legacy_table": table, "legacy_id": lid}
    f = {"item_mac_address_1": None, "item_storage_size_gb": None, "appliance_uuid": None,
         "brand_sku": None, "item_manufacturer": None, "item_model": None,
         "department_or_owner": None, "intended_purpose": None}
    if table == "computers":
        f.update(item_name=row["device_name"], item_manufacturer=row["device"],
                 item_model=row["model"], item_category="computer",
                 item_status="Deployed", department_or_owner=row["assigned_to"],
                 intended_purpose=row["purpose"])
    elif table == "hard_drives":
        gb = row["capacity_gb"] or (int(row["capacity_tb"] * 1000) if row["capacity_tb"] else None)
        f.update(item_name=" ".join(x for x in (row["manufacturer"], row["model"]) if x) or None,
                 item_manufacturer=row["manufacturer"], item_model=row["model"],
                 item_category="storage_drive", item_status=item_status(row["status"], None),
                 item_storage_size_gb=gb)
        for k in ("drive_type", "form_factor", "interface", "rpm"):
            if row[k]:
                attrs[k] = row[k]
        if gb:
            attrs["capacity_gb"] = gb
    elif table == "edge_boxes":
        sku = row["part_number"]
        if sku and not scalar(conn, "SELECT 1 FROM item_schema.part_numbers WHERE brand_sku = :s", s=sku):
            attrs["legacy_part_number"] = sku
            sku = None
        f.update(item_name=None, item_category="edge_box",
                 item_status=item_status(row["status"], None), brand_sku=sku,
                 appliance_uuid=row["uuid"], item_mac_address_1=row["mac_address"])
        for k in ("form_factor", "sku_version", "deployment_type", "partner", "customer"):
            if row[k]:
                attrs[k] = row[k]
    elif table == "nucs":
        f.update(item_name="NUC", item_category="computer",
                 item_status=item_status(row["status"], None),
                 item_mac_address_1=row["mac_address"], intended_purpose=row["purpose"])
        if row["deployment_type"]:
            attrs["deployment_type"] = row["deployment_type"]
    else:
        raise Abort(f"no carry-in mapping for {table}")
    if f["item_status"] is None:
        raise Abort(f"carry-in {table}:{lid} has no item status")
    loc_id, loc_text = site_id(conn, row.get("location"))
    notes = [f"migrated from legacy {table}:{lid} ({PROVENANCE})"]
    if loc_text:
        notes.append(f"legacy location: {loc_text}")
    if row.get("notes"):
        notes.append(str(row["notes"]))
    f.update(item_sn=row["serial"], location_id=loc_id, notes="; ".join(notes),
             attributes=json.dumps(attrs, sort_keys=True))
    return f


INSERT_ITEM = """
INSERT INTO item_schema.items
 (item_name, item_manufacturer, item_model, item_sn, item_category, item_status,
  location_id, department_or_owner, item_mac_address_1, item_storage_size_gb,
  appliance_uuid, brand_sku, intended_purpose, notes, attributes)
VALUES
 (:item_name, :item_manufacturer, :item_model, :item_sn, CAST(:item_category AS public.item_categories),
  CAST(:item_status AS public.item_statuses), :location_id, :department_or_owner,
  CAST(:item_mac_address_1 AS macaddr), :item_storage_size_gb, :appliance_uuid, :brand_sku,
  :intended_purpose, :notes, CAST(:attributes AS jsonb))
RETURNING id
"""


def counts(conn):
    c = {}
    c["items"] = scalar(conn, "SELECT count(*) FROM item_schema.items")
    c["history"] = scalar(conn, "SELECT count(*) FROM item_schema.component_history")
    c["contained"] = scalar(conn, "SELECT count(*) FROM item_schema.current_containment")
    c["dc_map"] = scalar(conn, "SELECT count(*) FROM component_migration_map")
    c["dc_rows"] = scalar(conn, "SELECT count(*) FROM device_components")
    c["nas_drives"] = scalar(conn, "SELECT count(*) FROM nas_drives")
    c["legacy_map"] = scalar(conn, "SELECT count(*) FROM legacy_item_map")
    c["legacy_map_r2"] = scalar(conn, "SELECT count(*) FROM legacy_item_map WHERE rule = 'R2'")
    for t in ("device_credentials", "device_provisioning", "device_warranties", "device_assignments"):
        c[t + "_null"] = scalar(conn, f"SELECT count(*) FROM public.{t} WHERE item_id IS NULL")
    c["pending_null"] = scalar(conn, "SELECT count(*) FROM pending_devices WHERE suggested_category IS NULL AND suggested_table IS NOT NULL")
    c["removed_dates"] = scalar(conn, "SELECT count(*) FROM device_components WHERE removed_date IS NOT NULL")
    c["installed_not_status"] = scalar(conn,
        "SELECT count(*) FROM item_schema.current_containment cc JOIN item_schema.items i ON i.id = cc.component_item_id "
        "WHERE i.item_status IS DISTINCT FROM 'Installed'")
    return c


def by_category(conn):
    rows = q(conn, "SELECT coalesce(item_category::text, '(none)'), count(*) FROM item_schema.items GROUP BY 1 ORDER BY 1")
    return {r[0]: r[1] for r in rows}


def run(conn):
    q(conn, MAP_DDL)
    before = counts(conn)
    cat_before = by_category(conn)
    print("== counts before:", json.dumps(before, sort_keys=True))
    if before["removed_dates"]:
        raise Abort("a device_components row has removed_date set; R4 would need uninstall events")
    if before["nas_drives"]:
        raise Abort("nas_drives has rows; R6 is not implemented")

    fresh = before["legacy_map_r2"] == 0
    if not fresh and before["legacy_map_r2"] != len(CARRY_INS):
        raise Abort(f"partial carry-in state: {before['legacy_map_r2']} of {len(CARRY_INS)} R2 rows")

    # snapshot
    ends = link_ends(conn)
    snap = {}
    for src, sid, t, lid in ends:
        result, _ = classify(conn, t, lid)
        snap[result] = snap.get(result, 0) + 1
    print("== snapshot of open link ends:", json.dumps(snap, sort_keys=True))
    if fresh:
        if snap != EXPECT_SNAPSHOT:
            raise Abort(f"snapshot {snap} differs from expected {EXPECT_SNAPSHOT}")
        if before["items"] != EXPECT_ITEMS_BEFORE:
            raise Abort(f"items {before['items']} differs from expected {EXPECT_ITEMS_BEFORE}")

    # R2
    made = 0
    for t, lid in CARRY_INS:
        if mapped(conn, t, lid):
            continue
        f = carry_in_fields(conn, t, lid)
        if f["item_sn"] and serial_match(conn, norm(f["item_sn"])):
            raise Abort(f"carry-in {t}:{lid} serial already on an item")
        if f["item_mac_address_1"] and scalar(conn,
                "SELECT count(*) FROM item_schema.items WHERE item_mac_address_1 = CAST(:m AS macaddr) "
                "OR item_mac_address_2 = CAST(:m AS macaddr)", m=f["item_mac_address_1"]):
            raise Abort(f"carry-in {t}:{lid} MAC already on an item")
        new_id = scalar(conn, INSERT_ITEM, **f)
        q(conn, "INSERT INTO legacy_item_map (legacy_table, legacy_id, item_id, rule) VALUES (:t, :i, :it, 'R2')",
          t=t, i=lid, it=new_id)
        print(f"R2 {t}:{lid} -> item {new_id} ({f['item_category']}, {f['item_status']}, location {f['location_id']})")
        made += 1

    # links
    relinked = {}
    for t in ("device_credentials", "device_provisioning", "device_warranties", "device_assignments"):
        rows = q(conn, f"SELECT id, device_table, device_id FROM public.{t} WHERE item_id IS NULL ORDER BY id").fetchall()
        for rid, dt, did in rows:
            item_id = resolve(conn, dt, did)
            if not item_id:
                raise Abort(f"{t} {rid} ({dt}:{did}) does not resolve to an item")
            q(conn, f"UPDATE public.{t} SET item_id = :it WHERE id = :i AND item_id IS NULL", it=item_id, i=rid)
        relinked[t] = len(rows)
    print("== links re-pointed:", json.dumps(relinked, sort_keys=True))

    # R4
    events = 0
    rows = q(conn,
        "SELECT id, parent_table, parent_id, component_table, component_id, slot_label, installed_date, "
        "removed_date, installed_by, notes, created_at FROM device_components ORDER BY id").fetchall()
    seen = set()
    for (dc_id, pt, pid, ct, cid, slot, inst, removed, by, dnotes, created) in rows:
        if scalar(conn, "SELECT 1 FROM component_migration_map WHERE old_dc_id = :i", i=dc_id):
            continue
        if scalar(conn, "SELECT 1 FROM item_schema.component_history WHERE notes LIKE :p LIMIT 1",
                  p=f"[backfill:device_components:{dc_id}]%"):
            raise Abort(f"dc#{dc_id} has an event but no map row")
        parent = resolve(conn, pt, pid)
        comp = resolve(conn, ct, cid)
        if not parent or not comp:
            raise Abort(f"dc#{dc_id} does not resolve: parent {pt}:{pid} -> {parent}, component {ct}:{cid} -> {comp}")
        pcat = scalar(conn, "SELECT item_category::text FROM item_schema.items WHERE id = :i", i=parent)
        ccat = scalar(conn, "SELECT item_category::text FROM item_schema.items WHERE id = :i", i=comp)
        if pcat not in UNIT_CATEGORIES:
            raise Abort(f"dc#{dc_id} parent item {parent} is {pcat}, not a unit")
        if ccat in UNIT_CATEGORIES:
            raise Abort(f"dc#{dc_id} component item {comp} is a unit ({ccat})")
        if comp in seen or scalar(conn, "SELECT 1 FROM item_schema.current_containment WHERE component_item_id = :i", i=comp):
            raise Abort(f"dc#{dc_id} component item {comp} is already contained")
        seen.add(comp)
        provenance = (
            f"[backfill:device_components:{dc_id}] {pt}#{pid} -> {ct}#{cid}; installed_date is the "
            f"2026-03-05 import-run date, not the physical install date; {PROVENANCE}"
            + (f"; orig: {dnotes}" if dnotes else "")
        )
        action_date = inst or (created.date() if created else None)
        ev = scalar(conn,
            "INSERT INTO item_schema.component_history (item_id, parent_item_id, action, slot_label, action_date, performed_by, notes) "
            "VALUES (:c, :p, 'installed', :s, COALESCE(:d, CURRENT_DATE), :b, :n) RETURNING id",
            c=comp, p=parent, s=slot, d=action_date, b=by or "backfill", n=provenance)
        q(conn, "UPDATE item_schema.items SET item_status = 'Installed' WHERE id = :i", i=comp)
        q(conn, "INSERT INTO component_migration_map (old_dc_id, installed_event_id, uninstalled_event_id) VALUES (:o, :e, NULL)",
          o=dc_id, e=ev)
        events += 1
    print(f"== R4 installed events: {events}")

    # 6a
    moved = 0
    for iid, old, new in RECATEGORISE:
        cur = scalar(conn, "SELECT item_category::text FROM item_schema.items WHERE id = :i", i=iid)
        if cur == new:
            continue
        if cur != old:
            raise Abort(f"item {iid} is {cur}, expected {old} before moving to {new}")
        q(conn, "UPDATE item_schema.items SET item_category = CAST(:n AS public.item_categories) WHERE id = :i AND item_category::text = :o",
          n=new, i=iid, o=old)
        moved += 1
    print(f"== 6a recategorised: {moved}")

    # pending
    pend = 0
    for pid, st in q(conn, "SELECT id, suggested_table FROM pending_devices WHERE suggested_category IS NULL AND suggested_table IS NOT NULL").fetchall():
        if st not in SUGGESTED:
            raise Abort(f"pending {pid} suggested_table {st!r} has no category")
        q(conn, "UPDATE pending_devices SET suggested_category = CAST(:c AS public.item_categories) WHERE id = :i",
          c=SUGGESTED[st], i=pid)
        pend += 1
    print(f"== pending suggested_category set: {pend}")

    after = counts(conn)
    cat_after = by_category(conn)
    print("== counts after:", json.dumps(after, sort_keys=True))
    changed = {k: (cat_before.get(k, 0), cat_after.get(k, 0)) for k in sorted(set(cat_before) | set(cat_after))
               if cat_before.get(k, 0) != cat_after.get(k, 0)}
    print("== categories changed (before, after):", json.dumps(changed, sort_keys=True))

    if after["items"] != before["items"] + made:
        raise Abort("items count off")
    if fresh and made != len(CARRY_INS):
        raise Abort(f"made {made} carry-ins, expected {len(CARRY_INS)}")
    for t in ("device_credentials", "device_provisioning", "device_warranties", "device_assignments"):
        if after[t + "_null"]:
            raise Abort(f"{t} still has rows without item_id")
    if after["dc_map"] != after["dc_rows"]:
        raise Abort(f"component_migration_map {after['dc_map']} != device_components {after['dc_rows']}")
    if after["history"] != before["history"] + events or after["contained"] != before["contained"] + events:
        raise Abort("containment counts off")
    if after["installed_not_status"]:
        raise Abort("a contained component is not Installed")
    if after["pending_null"]:
        raise Abort("a pending row has no suggested_category")
    for iid, old, new in RECATEGORISE:
        if scalar(conn, "SELECT item_category::text FROM item_schema.items WHERE id = :i", i=iid) != new:
            raise Abort(f"item {iid} not in {new}")
    left = [(src, sid) for src, sid, t, lid in link_ends(conn) if not src.startswith("dc_")]
    if left:
        raise Abort(f"open link ends remain: {left[:5]}")
    return made + events + moved + pend + sum(relinked.values())


def main() -> None:
    conn = engine.connect()
    trans = conn.begin()
    try:
        work = run(conn)
    except Abort as e:
        trans.rollback()
        print(f"ABORT: {e}. Rolled back, nothing written.")
        sys.exit(1)
    except Exception:
        trans.rollback()
        print("ABORT: unexpected error. Rolled back, nothing written.")
        raise
    if work == 0:
        trans.rollback()
        print("ALREADY APPLIED. No-op.")
    elif APPLY:
        trans.commit()
        print(f"OK: migration 081 applied, {work} changes committed")
    else:
        trans.rollback()
        print(f"DRY RUN: {work} changes computed and rolled back. Re-run with --apply to commit.")
    conn.close()


if __name__ == "__main__":
    main()
