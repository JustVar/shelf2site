"""Contract tests for the triage gap engine in app/routes/triage.py.

Owner spec: docs/specs/triage-single-role.md. The engine functions are
called in process with the shared `db` session; HTTP is used only where a
route owns the state (containment install). The engine is looked up through
the module (`triage.X`) at call time, so a fail proof can swap a function in.

Covers the missing-value rule, SQL and Python agreement for every required
field, the installed-component location exemption, both data checks (place
mismatch, containment divergence) and the badge count, including the
decommissioned exclusion.

Rows are prefixed CONTRACT-TEST-TRG (serials, SKU) or contract-test-trg
(names) and removed by their fixtures. Leftovers from a crashed run are
purged by prefix before the module starts.
"""

import itertools

import pytest
from sqlalchemy import text as sqltext

from app.models import Item, ItemPartNumber, Site, VendorProfile
from app.routes import triage

FIELDS = Item.REQUIRED_FIELDS_HARDWARE
SN_PREFIX = "CONTRACT-TEST-TRG"
NAME_PREFIX = "contract-test-trg"
_serials = itertools.count(1)


def _purge(db):
    """Remove every row this module could have left behind, by prefix."""
    db.rollback()
    ids = [r[0] for r in db.execute(sqltext(
        "SELECT id FROM item_schema.items WHERE item_sn LIKE :p"), {"p": SN_PREFIX + "%"})]
    _delete_items(db, ids)
    db.execute(sqltext("DELETE FROM item_schema.part_numbers WHERE item_sku LIKE :p"),
               {"p": SN_PREFIX + "%"})
    db.execute(sqltext("DELETE FROM sites WHERE name LIKE :p"), {"p": NAME_PREFIX + "%"})
    db.execute(sqltext("DELETE FROM vendor_profiles WHERE name LIKE :p"), {"p": NAME_PREFIX + "%"})
    db.commit()


def _delete_items(db, ids):
    if not ids:
        return
    db.execute(sqltext(
        "DELETE FROM item_schema.component_history "
        "WHERE item_id = ANY(:i) OR parent_item_id = ANY(:i)"), {"i": ids})
    db.execute(sqltext(
        "DELETE FROM audit_log WHERE target_table = 'items' AND target_id = ANY(:i)"), {"i": ids})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = ANY(:i)"), {"i": ids})
    db.commit()


@pytest.fixture(scope="module")
def ref(db):
    """A customer site, a warehouse site, a vendor and a SKU, made through the
    ORM so Python-side defaults (VendorProfile.is_oem) apply."""
    _purge(db)
    customer = Site(name=NAME_PREFIX + " customer site", site_type="customer_site")
    warehouse = Site(name=NAME_PREFIX + " warehouse", site_type="warehouse")
    vendor = VendorProfile(name=NAME_PREFIX + " vendor")
    sku = ItemPartNumber(item_sku=SN_PREFIX + "-SKU", item_category="gpu")
    db.add_all([customer, warehouse, vendor, sku])
    db.commit()
    refs = {"customer": customer.id, "warehouse": warehouse.id,
            "vendor": vendor.id, "sku": sku.item_sku}
    yield refs
    _purge(db)


@pytest.fixture
def make_item(db, ref):
    """Factory for a complete item: all 11 hardware fields filled. Keyword
    overrides replace a field, including with None."""
    created = []

    def make(**overrides):
        values = {
            "item_name": NAME_PREFIX + " item",
            "item_manufacturer": NAME_PREFIX + " maker",
            "item_model": NAME_PREFIX + " model",
            "item_sn": "%s-%d" % (SN_PREFIX, next(_serials)),
            "item_category": "gpu",
            "item_status": "Unassigned",
            "location_id": ref["warehouse"],
            "department_or_owner": NAME_PREFIX + " dept",
            "item_sku": ref["sku"],
            "item_pn": SN_PREFIX + "-PN",
            "vendor_id": ref["vendor"],
        }
        values.update(overrides)
        item = Item(**values)
        db.add(item)
        db.commit()
        created.append(item.id)
        return item

    yield make
    db.rollback()
    _delete_items(db, created)


def _matches_gap_filter(db, item_id, fields):
    """True if the SQL gap filter selects this item."""
    db.commit()
    return db.query(Item.id).filter(Item.id == item_id).filter(triage._gap_filter(fields)).first() is not None


def _install(client, db, component_id, parent_id):
    r = client.post("/api/containment/install", json={
        "component_item_id": component_id, "parent_item_id": parent_id,
    })
    assert r.status_code == 200, r.text
    db.commit()  # end the session's transaction so it sees the route's commit


def _set_location(db, item_id, location_id):
    db.execute(sqltext("UPDATE item_schema.items SET location_id = :l WHERE id = :i"),
               {"l": location_id, "i": item_id})
    db.commit()


# -- A. The missing-value rule ----------------------------------------------------

@pytest.mark.parametrize("value, field, missing", [
    (None, "item_name", True),
    ("", "item_name", True),
    (0, "item_storage_size_gb", True),
    (0, "location_id", False),
], ids=["none", "empty-string", "zero-storage", "zero-fk"])
def test_is_missing(value, field, missing):
    assert triage._is_missing(value, field) is missing


# -- B. SQL and Python agree, one required field at a time ------------------------

@pytest.mark.parametrize("field", FIELDS)
def test_one_null_field_is_the_only_gap_in_both_paths(db, make_item, field):
    item = make_item(**{field: None})
    assert triage._compute_gaps(item, FIELDS, set()) == [field]
    assert _matches_gap_filter(db, item.id, FIELDS)


# -- C. Extra parity -------------------------------------------------------------

def test_complete_item_has_no_gap_in_either_path(db, make_item):
    item = make_item()
    assert triage._compute_gaps(item, FIELDS, set()) == []
    assert not _matches_gap_filter(db, item.id, FIELDS)


def test_empty_string_name_is_a_gap_in_both_paths(db, make_item):
    item = make_item(item_name="")
    assert triage._compute_gaps(item, FIELDS, set()) == ["item_name"]
    assert _matches_gap_filter(db, item.id, FIELDS)


# -- D. Installed components and location ----------------------------------------

def test_installed_component_without_location_is_not_a_location_gap(db, make_item, editor_client):
    unit = make_item(item_category="edge_box")
    gpu = make_item(location_id=None)
    _install(editor_client, db, gpu.id, unit.id)
    installed = triage._installed_ids(db)
    assert gpu.id in installed
    item = db.get(Item, gpu.id)
    assert "location_id" not in triage._compute_gaps(item, FIELDS, installed)
    assert not _matches_gap_filter(db, gpu.id, ["location_id"])


def test_standalone_item_without_location_is_a_location_gap(db, make_item):
    item = make_item(location_id=None)
    assert triage._compute_gaps(item, FIELDS, triage._installed_ids(db)) == ["location_id"]
    assert _matches_gap_filter(db, item.id, FIELDS)


# -- E. Place and status mismatch -------------------------------------------------

@pytest.mark.parametrize("category, status, place, flagged", [
    ("edge_box", "Deployed", "warehouse", True),
    ("edge_box", "Deployed", None, True),
    ("edge_box", "Unassigned", "customer", True),
    ("edge_box", "Deployed", "customer", False),
    ("gpu", "Deployed", "warehouse", False),
], ids=["deployed-at-warehouse", "deployed-nowhere", "unassigned-at-customer",
        "deployed-at-customer", "gpu-not-deployable"])
def test_place_mismatch(db, ref, make_item, category, status, place, flagged):
    item = make_item(item_category=category, item_status=status,
                     location_id=ref[place] if place else None)
    assert (item.id in triage._place_mismatch_ids(db)) is flagged


# -- F. Installed place divergence ------------------------------------------------

@pytest.mark.parametrize("stored, flagged", [
    ("customer", True),
    ("warehouse", False),
    (None, False),
], ids=["differs-from-parent", "same-as-parent", "no-stored-place"])
def test_containment_divergence(db, ref, make_item, editor_client, stored, flagged):
    unit = make_item(item_category="edge_box", location_id=ref["warehouse"])
    gpu = make_item()
    _install(editor_client, db, gpu.id, unit.id)
    _set_location(db, gpu.id, ref[stored] if stored else None)
    assert (gpu.id in triage._containment_divergence_ids(db)) is flagged


# -- G. The sidenav badge count, as deltas around one baseline --------------------

def test_badge_counts_an_item_with_a_gap(db, make_item):
    baseline = triage.get_triage_total_count(db)
    make_item(item_pn=None)
    assert triage.get_triage_total_count(db) == baseline + 1


def test_badge_ignores_a_complete_item(db, make_item):
    baseline = triage.get_triage_total_count(db)
    make_item()
    assert triage.get_triage_total_count(db) == baseline


def test_badge_excludes_a_decommissioned_item(db, make_item):
    baseline = triage.get_triage_total_count(db)
    item = make_item(item_pn=None)
    assert triage.get_triage_total_count(db) == baseline + 1
    db.execute(sqltext("UPDATE item_schema.items SET item_status = 'Decommissioned' WHERE id = :i"),
               {"i": item.id})
    db.commit()
    assert triage.get_triage_total_count(db) == baseline
