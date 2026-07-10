"""063: unify the two place vocabularies into public.sites (typed places).

Decision (2026-07-09): `sites` becomes the single place table. The item
`locations` vocabulary (item_schema.locations) folds in as site_type
'office' rows; existing sites keep their site_type. Coordinates move onto
the site record so a geocoded customer_site pins the units placed there.

Migration risk is deliberately on the SHALLOW fks: this repoints
item_schema.items.location_id and item_schema.part_numbers.location_id
(both nullable, no cascade) from item_schema.locations.id to sites.id. The
provisioning/deployment/assignment site_id fks are NOT touched.

De-dupe rules (per owner): item locations whose trimmed-lower nicknames are
exact duplicates merge to one office row (first wins); a nickname that
collides with an existing site name is suffixed " (2)", " (3)". Every
merge/rename and every old_location_id -> new_site_id pair is recorded in
place_migration_map for audit and rollback, with count assertions on both
sides. item_schema.locations is left intact (dead but preserved for
rollback); a later cleanup can drop it.

Idempotent: re-running is a no-op (guards on the geo columns, the mapping
rows, and the live fk target).

Run:
    docker compose exec app python migrations/063_unify_places_into_sites.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine


def _fk_target(conn, table, column):
    row = conn.execute(text("""
        SELECT confrelid::regclass::text
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.conrelid = CAST(:tbl AS regclass) AND c.contype = 'f' AND a.attname = :col
        LIMIT 1
    """), {"tbl": table, "col": column}).fetchone()
    return row[0] if row else None


def _fk_name(conn, table, column):
    row = conn.execute(text("""
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.conrelid = CAST(:tbl AS regclass) AND c.contype = 'f' AND a.attname = :col
        LIMIT 1
    """), {"tbl": table, "col": column}).fetchone()
    return row[0] if row else None


def run():
    with engine.begin() as conn:
        # 1. geo + geocode columns on sites (idempotent) ----------------------
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS geo_lat double precision"))
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS geo_lng double precision"))
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS show_on_map boolean NOT NULL DEFAULT false"))
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS geocoded_at timestamp"))
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS geocode_query text"))

        # 2. audit/rollback mapping table (idempotent) ------------------------
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS place_migration_map (
                old_location_id integer PRIMARY KEY,
                new_site_id integer NOT NULL,
                action varchar(16) NOT NULL,
                created_at timestamp NOT NULL DEFAULT now()
            )
        """))

        already = conn.execute(text("SELECT count(*) FROM place_migration_map")).scalar()
        loc_count = conn.execute(text("SELECT count(*) FROM item_schema.locations")).scalar()

        if already == 0 and loc_count > 0:
            existing_names = {
                r[0].strip().lower()
                for r in conn.execute(text("SELECT name FROM sites")).fetchall()
            }
            merged_by_key = {}  # normalized nickname -> new_site_id (exact-dup merge)
            for loc in conn.execute(text("""
                SELECT id, nickname, location_type, address_line_1, address_line_2,
                       city, state, zip, country, contact_name, contact_email,
                       contact_phone, customer, is_active, notes,
                       geo_lat, geo_lng, show_on_map
                FROM item_schema.locations ORDER BY id
            """)).fetchall():
                key = (loc.nickname or "").strip().lower()
                if key and key in merged_by_key:
                    conn.execute(text(
                        "INSERT INTO place_migration_map (old_location_id, new_site_id, action) "
                        "VALUES (:o, :n, 'merge')"),
                        {"o": loc.id, "n": merged_by_key[key]})
                    continue

                # name-collision suffixing against existing site names
                base = (loc.nickname or f"Location {loc.id}").strip()
                name = base
                n = 2
                while name.strip().lower() in existing_names:
                    name = f"{base} ({n})"
                    n += 1
                action = "rename" if name != base else "move"
                existing_names.add(name.strip().lower())

                addr = ", ".join(p for p in (loc.address_line_1, loc.address_line_2) if p) or None
                new_id = conn.execute(text("""
                    INSERT INTO sites (name, site_type, customer, address, city, state,
                        country, contact_name, contact_email, contact_phone, notes,
                        is_active, geo_lat, geo_lng, show_on_map)
                    VALUES (:name, 'office', :customer, :address, :city, :state,
                        :country, :cn, :ce, :cp, :notes, :active, :lat, :lng, :som)
                    RETURNING id
                """), {
                    "name": name, "customer": loc.customer, "address": addr,
                    "city": loc.city, "state": loc.state, "country": loc.country,
                    "cn": loc.contact_name, "ce": loc.contact_email, "cp": loc.contact_phone,
                    "notes": loc.notes, "active": loc.is_active if loc.is_active is not None else True,
                    "lat": loc.geo_lat, "lng": loc.geo_lng,
                    "som": bool(loc.show_on_map),
                }).scalar()
                merged_by_key[key] = new_id
                conn.execute(text(
                    "INSERT INTO place_migration_map (old_location_id, new_site_id, action) "
                    "VALUES (:o, :n, :a)"),
                    {"o": loc.id, "n": new_id, "a": action})

        # 3. repoint items.location_id + part_numbers.location_id -------------
        for tbl, schema in (("item_schema.items", "items"), ("item_schema.part_numbers", "part_numbers")):
            if _fk_target(conn, tbl, "location_id") == "item_schema.locations":
                items_before = conn.execute(text(
                    f"SELECT count(*) FROM {tbl} WHERE location_id IS NOT NULL")).scalar()
                # Drop the old fk BEFORE the update: the new values are site
                # ids that do not exist in item_schema.locations.
                old_fk = _fk_name(conn, tbl, "location_id")
                if old_fk:
                    conn.execute(text(f'ALTER TABLE {tbl} DROP CONSTRAINT "{old_fk}"'))
                conn.execute(text(
                    f"UPDATE {tbl} SET location_id = m.new_site_id "
                    f"FROM place_migration_map m WHERE {tbl}.location_id = m.old_location_id"))
                items_after = conn.execute(text(
                    f"SELECT count(*) FROM {tbl} WHERE location_id IS NOT NULL")).scalar()
                assert items_before == items_after, f"ABORT: {tbl} row count drift {items_before}->{items_after}"
                orphans = conn.execute(text(
                    f"SELECT count(*) FROM {tbl} t WHERE t.location_id IS NOT NULL "
                    f"AND NOT EXISTS (SELECT 1 FROM sites s WHERE s.id = t.location_id)")).scalar()
                assert orphans == 0, f"ABORT: {tbl} has {orphans} location_id values with no matching site"
                conn.execute(text(
                    f'ALTER TABLE {tbl} ADD CONSTRAINT {schema}_location_id_sites_fkey '
                    f"FOREIGN KEY (location_id) REFERENCES sites(id) ON DELETE SET NULL"))

        n_map = conn.execute(text("SELECT count(*) FROM place_migration_map")).scalar()
        print(f"063 done: sites gained geo columns; {n_map} location(s) folded in as office sites; "
              f"items + part_numbers location_id repointed to sites.id (item_schema.locations preserved)")


if __name__ == "__main__":
    print("Running migration 063: unify places into sites")
    run()
    print("Migration 063 complete.")
