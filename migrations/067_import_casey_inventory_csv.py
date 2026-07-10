"""Import Casey's inventory CSV (544 rows, exported 2026-07-10) into
item_schema.items.

Source of truth: Casey_Postgresdb_data-1783692249371.csv — an export of the
same items-schema lineage, so columns map 1:1 with three exceptions:
  * cog (money string)      -> attributes['cog_usd'] (items has no cog column)
  * brand_sku             -> column ONLY when the exact value exists in
                               item_schema.part_numbers (FK); otherwise the raw
                               value is preserved in attributes['import_brand_sku']
                               and reported with a near-miss suggestion. The
                               tool never guesses catalog identity.
  * id / location_id / vendor_id -> never imported (foreign id space).

Merge rule (locked 2026-07-10): match by serial, case-insensitive, trimmed.
On match LIVE WINS — app-managed fields (item_status, location_id; containment
and custody are derived from status) are never written. CSV fills only fields
that are empty on the live row. Both-sides-non-empty-and-different is REPORTED,
never applied.

Serial-less rows (blank / whitespace / literal '0' / literal 'NULL') import
as-is with item_sn NULL — the missing-fields triage surfaces them. In-CSV
duplicate serials: first occurrence in file order wins; the rest are skipped
and listed for manual resolution.

RE-RUNNABLE BY DESIGN: item_schema.csv_import_map records (source, csv_id) ->
action + item id. Rows already in the map are skipped, so re-running after
apply is a no-op. Serial-less rows rely on the map alone (they can never
re-match by serial). Provenance also rides on each created/updated row in
attributes: import_source + import_csv_id.

DRY-RUN IS THE DEFAULT and writes nothing (not even the map table). Apply is
one transaction: any assertion failure rolls everything back.

Run (CSV staged untracked under migrations/data/ — 'data/' is gitignored;
dumps of customer data never enter the repo):
    docker compose exec -T app python migrations/067_import_casey_inventory_csv.py \
        --csv migrations/data/Casey_Postgresdb_data-1783692249371.csv [--apply]
"""
import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.validation import normalize_mac  # noqa: E402

SOURCE = "casey-csv-1783692249371"

MAP_TABLE = """
CREATE TABLE IF NOT EXISTS item_schema.csv_import_map (
    source      varchar(128) NOT NULL,
    csv_id      integer      NOT NULL,
    item_id     integer,
    action      varchar(64)  NOT NULL,
    imported_at timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (source, csv_id)
)
"""

# CSV fields that map straight onto items columns (same names, same meaning).
DIRECT_TEXT = [
    "item_name", "item_manufacturer", "item_model",
    "department_or_owner", "appliance_uuid", "brand_pn",
    "item_associated_brand_pn", "intended_purpose", "notes",
    "tracking_number",
]
DATE_FIELDS = ["date_purchased", "dispatched_date", "created_at", "last_updated"]

# Never written on a matched live row (live wins; containment/custody are
# derived from item_status so protecting status protects them too).
APP_MANAGED = {"item_status", "location_id"}

JUNK = {"", "0", "NULL"}


def clean(v):
    """Placeholder junk ('0', blank, whitespace-only, literal NULL) -> None."""
    if v is None:
        return None
    v = v.strip()
    return None if v in JUNK else v


def money(v):
    v = clean(v)
    if v is None:
        return None
    stripped = v.replace("$", "").replace(",", "")
    return float(stripped)  # ValueError on garbage = loud failure, wanted


def iso_date(v):
    v = clean(v)
    return date.fromisoformat(v) if v else None


def load_csv(path):
    # StringIO, NOT splitlines(): quoted fields spanning lines must keep their
    # embedded newlines (splitlines() fuses them — csv ids 214/215 notes).
    text_body = Path(path).read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text_body)))
    assert rows, "CSV parsed to zero rows"
    return rows


def norm_serial(v):
    v = clean(v)
    return v.lower() if v else None


def normalize_row(raw, enum_categories, enum_statuses, valid_skus):
    """Return (fields-dict ready for items, extras-dict, problems-list)."""
    problems = []
    f = {}
    f["item_sn"] = clean(raw["item_sn"])
    for col in DIRECT_TEXT:
        f[col] = clean(raw[col])
    for col in DATE_FIELDS:
        f[col] = iso_date(raw[col])

    cat = clean(raw["item_category"])
    if cat not in enum_categories:
        problems.append(f"category '{cat}' not in live enum")
        cat = None
    f["item_category"] = cat

    status = clean(raw["item_status"])
    if status is not None and status not in enum_statuses:
        problems.append(f"status '{status}' not in live enum")
        status = None
    f["item_status"] = status

    for col in ("item_mac_address_1", "item_mac_address_2"):
        v = clean(raw[col])
        try:
            f[col] = normalize_mac(v) if v else None
        except ValueError as e:
            problems.append(str(e))
            f[col] = None

    v = clean(raw["item_storage_size_gb"])
    f["item_storage_size_gb"] = float(v) if v else None

    extras = {}
    cog = money(raw["cog"])
    if cog:  # "$0.00" is placeholder junk in spirit — store real costs only
        extras["cog_usd"] = cog

    sku = clean(raw["brand_sku"])
    f["brand_sku"] = None
    if sku is not None:
        if sku in valid_skus:
            f["brand_sku"] = sku
        else:
            extras["import_brand_sku"] = sku

    # foreign id space — the export has these all-NULL; refuse surprises
    for col in ("location_id", "vendor_id"):
        if clean(raw[col]) is not None:
            problems.append(f"{col}={raw[col]!r} — foreign FK space, refusing to map")
    return f, extras, problems


def sku_suggestion(sku, valid_skus):
    flat = lambda s: "".join(ch for ch in s.upper() if ch.isalnum())
    hits = [v for v in valid_skus if flat(v) == flat(sku)]
    return hits[0] if hits else None


INSERT_COLS = [
    "item_name", "item_manufacturer", "item_model", "item_sn",
    "item_category", "item_status", "department_or_owner",
    "item_mac_address_1", "item_mac_address_2", "item_storage_size_gb",
    "appliance_uuid", "brand_sku", "brand_pn", "item_associated_brand_pn",
    "date_purchased", "intended_purpose", "notes", "dispatched_date",
    "tracking_number", "created_at", "last_updated",
]
# Fill-blank candidates on a matched live row = everything importable that is
# not app-managed and not the match key. Timestamps are excluded too: they are
# row metadata, not mergeable data, and last_updated in a SET list would
# collide with the hardcoded last_updated = CURRENT_DATE in the UPDATE.
FILL_COLS = [c for c in INSERT_COLS
             if c not in APP_MANAGED and c not in ("item_sn", "created_at", "last_updated")]

INSERT_SQL = text(
    "INSERT INTO item_schema.items ("
    + ", ".join(INSERT_COLS)
    + ", attributes) VALUES ("
    + ", ".join(f":{c}" for c in INSERT_COLS)
    + ", CAST(:attributes AS jsonb)) RETURNING id"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write changes; default is a read-only dry run")
    args = ap.parse_args()

    rows = load_csv(args.csv)
    total = len(rows)
    print(f"MODE: {'APPLY' if args.apply else 'DRY-RUN (no writes)'}   csv rows: {total}")

    with engine.connect() as conn:
        enum_categories = {r[0] for r in conn.execute(
            text("SELECT unnest(enum_range(NULL::public.item_categories))"))}
        enum_statuses = {r[0] for r in conn.execute(
            text("SELECT unnest(enum_range(NULL::public.item_statuses))"))}
        valid_skus = {r[0] for r in conn.execute(
            text("SELECT brand_sku FROM item_schema.part_numbers"))}
        live = conn.execute(text(
            "SELECT id, item_sn, item_status::text AS item_status, location_id, "
            "item_name, item_manufacturer, item_model, item_category::text AS item_category, "
            "department_or_owner, item_mac_address_1::text AS item_mac_address_1, "
            "item_mac_address_2::text AS item_mac_address_2, item_storage_size_gb, "
            "appliance_uuid, brand_sku, brand_pn, item_associated_brand_pn, "
            "date_purchased, intended_purpose, notes, dispatched_date, "
            "tracking_number, created_at, last_updated "
            "FROM item_schema.items")).mappings().all()
        already = {}
        if conn.execute(text(
                "SELECT to_regclass('item_schema.csv_import_map')")).scalar():
            already = {r[0]: r[1] for r in conn.execute(text(
                "SELECT csv_id, action FROM item_schema.csv_import_map WHERE source = :s"),
                {"s": SOURCE})}

    live_by_serial = {}
    for r in live:
        key = norm_serial(r["item_sn"])
        if key:
            if key in live_by_serial:
                print(f"WARNING: live serial duplicated in items: '{key}' "
                      f"(ids {live_by_serial[key]['id']}, {r['id']}) — matching lowest id")
                continue
            live_by_serial[key] = r
    live_macs = {}
    for r in live:
        for col in ("item_mac_address_1", "item_mac_address_2"):
            if r[col]:
                live_macs.setdefault(r[col].lower(), r["id"])

    # ── classify every CSV row into exactly one bucket ──────────────────────
    creates, updates, identical, conflicts_only = [], [], [], []
    dup_skips, imported_skips, problem_rows = [], [], []
    seen_serials = {}
    mac_notes = []

    for raw in rows:
        csv_id = int(raw["id"])
        fields, extras, problems = normalize_row(
            raw, enum_categories, enum_statuses, valid_skus)
        if problems:
            problem_rows.append((csv_id, problems))

        if csv_id in already:
            imported_skips.append((csv_id, already[csv_id]))
            continue

        key = norm_serial(raw["item_sn"])
        if key:
            if key in seen_serials:
                dup_skips.append((csv_id, raw["item_sn"].strip(),
                                  seen_serials[key], fields["item_name"]))
                continue
            seen_serials[key] = csv_id

        for col in ("item_mac_address_1", "item_mac_address_2"):
            mac = fields[col]
            if mac and mac.lower() in live_macs:
                owner = live_macs[mac.lower()]
                match = live_by_serial.get(key)
                if not match or match["id"] != owner:
                    mac_notes.append(
                        f"csv {csv_id} ({raw['item_sn'].strip() or 'no serial'}) "
                        f"carries MAC {mac} already on live item {owner}")

        match = live_by_serial.get(key) if key else None
        if match is None:
            creates.append((csv_id, fields, extras))
            continue

        fills, confs, infos = [], [], []
        for col in FILL_COLS:
            csv_v, live_v = fields[col], match[col]
            live_empty = live_v is None or (isinstance(live_v, str) and not live_v.strip())
            if csv_v is None:
                continue
            if live_empty:
                fills.append((col, csv_v))
            elif str(live_v).strip().lower() != str(csv_v).strip().lower():
                confs.append((col, live_v, csv_v))
        for col in sorted(APP_MANAGED):
            csv_v, live_v = fields.get(col), match[col]
            if csv_v is not None and str(csv_v) != str(live_v):
                infos.append((col, live_v, csv_v))
        entry = (csv_id, match["id"], raw["item_sn"].strip(), fills, confs, infos, extras)
        if fills:
            updates.append(entry)
        elif confs:
            conflicts_only.append(entry)
        else:
            identical.append(entry)

    buckets = (len(creates) + len(updates) + len(identical) + len(conflicts_only)
               + len(dup_skips) + len(imported_skips))
    assert buckets == total, f"accounting broken: {buckets} != {total}"

    # ── report ──────────────────────────────────────────────────────────────
    serial_less = [c for c, f, e in creates if f["item_sn"] is None]
    print(f"\nSUMMARY  create={len(creates)} (serial-less {len(serial_less)})  "
          f"fill-blanks-update={len(updates)}  skip-identical={len(identical)}  "
          f"conflict-only-match={len(conflicts_only)}  dup-in-csv={len(dup_skips)}  "
          f"already-imported={len(imported_skips)}")

    if problem_rows:
        print(f"\nROWS WITH NORMALIZATION PROBLEMS ({len(problem_rows)}):")
        for csv_id, probs in problem_rows:
            print(f"  csv {csv_id}: {'; '.join(probs)}")

    for entry in updates + conflicts_only + identical:
        csv_id, item_id, sn, fills, confs, infos, _ = entry
        print(f"\nMATCH csv {csv_id} -> live item {item_id} (serial {sn})")
        for col, v in fills:
            print(f"  FILL      {col}: {v!r} (live empty)")
        for col, lv, cv in confs:
            print(f"  CONFLICT  {col}: live={lv!r} csv={cv!r} — reported, NOT applied")
        for col, lv, cv in infos:
            print(f"  INFO      {col}: live={lv!r} csv={cv!r} — app-managed, live wins")

    if dup_skips:
        print(f"\nDUPLICATE SERIALS IN CSV ({len(dup_skips)} rows skipped, first wins):")
        for csv_id, sn, winner, name in dup_skips:
            print(f"  csv {csv_id} '{sn}' ({name}) — first occurrence csv {winner} wins")

    sku_rows = [(c, e["import_brand_sku"]) for c, f, e in creates
                if "import_brand_sku" in e]
    if sku_rows:
        by_sku = {}
        for c, s in sku_rows:
            by_sku.setdefault(s, []).append(c)
        print(f"\nSKUs NOT IN part_numbers ({len(sku_rows)} rows — column left NULL, "
              f"raw value kept in attributes.import_brand_sku):")
        for s, ids in sorted(by_sku.items()):
            sug = sku_suggestion(s, valid_skus)
            hint = f"  (near-miss of catalog '{sug}'?)" if sug else ""
            print(f"  '{s}' x{len(ids)} rows{hint}")

    if mac_notes:
        print(f"\nMAC COLLISIONS WITH LIVE ROWS ({len(mac_notes)} — report only):")
        for n in mac_notes:
            print(f"  {n}")

    by_cat = {}
    for _, f, _ in creates:
        by_cat[f["item_category"]] = by_cat.get(f["item_category"], 0) + 1
    print("\nCREATES BY CATEGORY: "
          + "  ".join(f"{k}={v}" for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])))
    by_status = {}
    for _, f, _ in creates:
        by_status[f["item_status"]] = by_status.get(f["item_status"], 0) + 1
    print("CREATES BY STATUS: "
          + "  ".join(f"{k}={v}" for k, v in sorted(by_status.items(), key=lambda kv: str(kv[0]))))

    print(f"\nSERIAL-LESS CREATES ({len(serial_less)}): csv ids "
          + ", ".join(str(c) for c in serial_less))

    if not args.apply:
        print("\nDRY-RUN complete — nothing written. Re-run with --apply after review.")
        return

    # ── apply: one transaction, all-or-nothing ──────────────────────────────
    with engine.begin() as conn:
        conn.execute(text(MAP_TABLE))
        before = conn.execute(text("SELECT count(*) FROM item_schema.items")).scalar()

        for csv_id, fields, extras in creates:
            attrs = dict(extras)
            attrs["import_source"] = SOURCE
            attrs["import_csv_id"] = csv_id
            params = {c: fields[c] for c in INSERT_COLS}
            params["attributes"] = json.dumps(attrs)
            item_id = conn.execute(INSERT_SQL, params).scalar()
            conn.execute(text(
                "INSERT INTO item_schema.csv_import_map (source, csv_id, item_id, action) "
                "VALUES (:s, :c, :i, 'created')"),
                {"s": SOURCE, "c": csv_id, "i": item_id})

        for entry in updates:
            csv_id, item_id, _, fills, _, _, extras = entry
            sets = ", ".join(f"{col} = :{col}" for col, _ in fills)
            params = {col: v for col, v in fills}
            params["i"] = item_id
            conn.execute(text(
                f"UPDATE item_schema.items SET {sets}, last_updated = CURRENT_DATE "
                f"WHERE id = :i"), params)
            attrs = dict(extras)
            attrs["import_source"] = SOURCE
            attrs["import_csv_id"] = csv_id
            conn.execute(text(
                "UPDATE item_schema.items SET attributes = "
                "COALESCE(attributes, '{}'::jsonb) || CAST(:a AS jsonb) WHERE id = :i"),
                {"a": json.dumps(attrs), "i": item_id})
            conn.execute(text(
                "INSERT INTO item_schema.csv_import_map (source, csv_id, item_id, action) "
                "VALUES (:s, :c, :i, 'filled-blanks')"),
                {"s": SOURCE, "c": csv_id, "i": item_id})

        for entry, action in [(e, "matched-identical") for e in identical] + \
                             [(e, "matched-conflicts-reported") for e in conflicts_only]:
            csv_id, item_id = entry[0], entry[1]
            conn.execute(text(
                "INSERT INTO item_schema.csv_import_map (source, csv_id, item_id, action) "
                "VALUES (:s, :c, :i, :a)"),
                {"s": SOURCE, "c": csv_id, "i": item_id, "a": action})

        for csv_id, sn, winner, _ in dup_skips:
            conn.execute(text(
                "INSERT INTO item_schema.csv_import_map (source, csv_id, item_id, action) "
                "VALUES (:s, :c, NULL, :a)"),
                {"s": SOURCE, "c": csv_id, "a": f"dup-in-csv-of-{winner}"})

        after = conn.execute(text("SELECT count(*) FROM item_schema.items")).scalar()
        assert after - before == len(creates), \
            f"row-count delta {after - before} != creates {len(creates)}"
        mapped = conn.execute(text(
            "SELECT count(*) FROM item_schema.csv_import_map WHERE source = :s"),
            {"s": SOURCE}).scalar()
        assert mapped == total, f"map rows {mapped} != {total}"

    print(f"\nAPPLIED: items {before} -> {after} (+{after - before}); "
          f"map rows for source = {total}. Re-running is now a no-op.")


if __name__ == "__main__":
    main()
