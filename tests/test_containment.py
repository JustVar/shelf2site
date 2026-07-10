"""Containment invariant contract tests (Option A slice).

Each guard is exercised positive AND negative. Test rows use
CONTRACT-TEST-CTM serials and are removed by the fixture.
"""

import pytest
from sqlalchemy import text as sqltext


@pytest.fixture
def ctm(db):
    """Two units (edge_box, computer) + two components (gpu, storage_drive)."""
    specs = {
        "unit1": ("CTM Edge Unit", "CONTRACT-TEST-CTM-U1", "edge_box"),
        "unit2": ("CTM Computer", "CONTRACT-TEST-CTM-U2", "computer"),
        "comp1": ("CTM GPU", "CONTRACT-TEST-CTM-C1", "gpu"),
        "comp2": ("CTM Drive", "CONTRACT-TEST-CTM-C2", "storage_drive"),
    }
    ids = {}
    for key, (name, sn, cat) in specs.items():
        ids[key] = db.execute(sqltext(
            "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
            "VALUES (:n, :s, :c, 'Unassigned') RETURNING id"),
            {"n": name, "s": sn, "c": cat}).scalar()
    db.commit()
    yield ids
    all_ids = list(ids.values())
    db.execute(sqltext(
        "DELETE FROM item_schema.component_history "
        "WHERE item_id = ANY(:i) OR parent_item_id = ANY(:i)"), {"i": all_ids})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = ANY(:i)"), {"i": all_ids})
    db.commit()


def _view_row(db, component_id):
    db.commit()
    return db.execute(sqltext(
        "SELECT parent_item_id, slot_label FROM item_schema.current_containment "
        "WHERE component_item_id = :i"), {"i": component_id}).fetchone()


def _status(db, item_id):
    db.commit()
    return db.execute(sqltext(
        "SELECT item_status FROM item_schema.items WHERE id = :i"), {"i": item_id}).scalar()


# ── install ──────────────────────────────────────────────────────────────────

def test_install_happy_path(editor_client, db, ctm):
    r = editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
        "slot_label": "PCIe 1",
    })
    assert r.status_code == 200, r.text
    row = _view_row(db, ctm["comp1"])
    assert row is not None and row[0] == ctm["unit1"] and row[1] == "PCIe 1"
    assert _status(db, ctm["comp1"]) == "Installed"


def test_install_rejects_non_unit_parent(editor_client, ctm):
    r = editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["comp2"],
    })
    assert r.status_code == 400
    assert "not a parent-eligible unit" in r.json()["error"]


def test_install_rejects_unit_as_component(editor_client, ctm):
    """Units can never be components — this is also the no-cycles guard."""
    r = editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["unit2"], "parent_item_id": ctm["unit1"],
    })
    assert r.status_code == 400
    assert "units cannot be installed" in r.json()["error"]


def test_install_rejects_self(editor_client, ctm):
    r = editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["unit1"], "parent_item_id": ctm["unit1"],
    })
    assert r.status_code == 400


def test_install_rejects_already_installed(editor_client, ctm):
    first = editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    assert first.status_code == 200
    second = editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit2"],
    })
    assert second.status_code == 409
    assert "already installed" in second.json()["error"]


def test_install_rejects_checked_out_component(editor_client, db, ctm):
    db.execute(sqltext(
        "UPDATE item_schema.items SET item_status = 'Checked Out' WHERE id = :i"),
        {"i": ctm["comp2"]})
    db.commit()
    r = editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp2"], "parent_item_id": ctm["unit1"],
    })
    assert r.status_code == 409
    assert "checked out" in r.json()["error"]


def test_install_missing_items_404(editor_client, ctm):
    r = editor_client.post("/api/containment/install", json={
        "component_item_id": 99999999, "parent_item_id": ctm["unit1"],
    })
    assert r.status_code == 404


# ── uninstall ────────────────────────────────────────────────────────────────

def test_uninstall_happy_path_defaults_unassigned(editor_client, db, ctm):
    editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    r = editor_client.post("/api/containment/uninstall", json={
        "component_item_id": ctm["comp1"],
    })
    assert r.status_code == 200, r.text
    assert r.json()["status_after"] == "Unassigned"
    assert _view_row(db, ctm["comp1"]) is None
    assert _status(db, ctm["comp1"]) == "Unassigned"


def test_uninstall_accepts_explicit_status(editor_client, db, ctm):
    editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    r = editor_client.post("/api/containment/uninstall", json={
        "component_item_id": ctm["comp1"], "status_after": "Ready to Deploy",
    })
    assert r.status_code == 200
    assert _status(db, ctm["comp1"]) == "Ready to Deploy"


def test_uninstall_rejects_not_installed(editor_client, ctm):
    r = editor_client.post("/api/containment/uninstall", json={
        "component_item_id": ctm["comp1"],
    })
    assert r.status_code == 409
    assert "not installed" in r.json()["error"]


def test_uninstall_rejects_managed_status_after(editor_client, ctm):
    editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    r = editor_client.post("/api/containment/uninstall", json={
        "component_item_id": ctm["comp1"], "status_after": "Installed",
    })
    assert r.status_code == 400


# ── move ─────────────────────────────────────────────────────────────────────

def test_move_happy_path_single_event(editor_client, db, ctm):
    editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    r = editor_client.post("/api/containment/move", json={
        "component_item_id": ctm["comp1"], "new_parent_item_id": ctm["unit2"],
        "slot_label": "bay 2",
    })
    assert r.status_code == 200, r.text
    row = _view_row(db, ctm["comp1"])
    assert row is not None and row[0] == ctm["unit2"] and row[1] == "bay 2"
    assert _status(db, ctm["comp1"]) == "Installed"
    events = db.execute(sqltext(
        "SELECT action, parent_item_id FROM item_schema.component_history "
        "WHERE item_id = :i ORDER BY id"), {"i": ctm["comp1"]}).fetchall()
    assert [e[0] for e in events] == ["installed", "moved"]
    assert events[0][1] == ctm["unit1"] and events[1][1] == ctm["unit2"]


def test_move_rejects_same_parent(editor_client, ctm):
    editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    r = editor_client.post("/api/containment/move", json={
        "component_item_id": ctm["comp1"], "new_parent_item_id": ctm["unit1"],
    })
    assert r.status_code == 400


def test_move_rejects_not_installed(editor_client, ctm):
    r = editor_client.post("/api/containment/move", json={
        "component_item_id": ctm["comp1"], "new_parent_item_id": ctm["unit1"],
    })
    assert r.status_code == 409


# ── candidates + auth ────────────────────────────────────────────────────────

def test_candidates_units_and_components(editor_client, ctm):
    r = editor_client.get("/api/containment/candidates?mode=units&q=CONTRACT-TEST-CTM")
    ids = [x["id"] for x in r.json()["results"]]
    assert ctm["unit1"] in ids and ctm["unit2"] in ids
    assert ctm["comp1"] not in ids

    editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    r = editor_client.get("/api/containment/candidates?mode=components&q=CONTRACT-TEST-CTM")
    ids = [x["id"] for x in r.json()["results"]]
    assert ctm["comp2"] in ids, "standalone component missing from picker"
    assert ctm["comp1"] not in ids, "installed component must not be offered"
    assert ctm["unit1"] not in ids, "units must not be offered as components"


def test_containment_requires_editor(viewer_client, ctm):
    r = viewer_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    assert r.status_code == 403


# ── Installed items are edit-protected ───────────────────────────────────────

def test_item_detail_save_cannot_dislodge_installed(editor_client, db, ctm):
    """A form save on an Installed item must not change its managed status
    or its (frozen) stored location."""
    editor_client.post("/api/containment/install", json={
        "component_item_id": ctm["comp1"], "parent_item_id": ctm["unit1"],
    })
    r = editor_client.post(f"/items/{ctm['comp1']}", data={
        "item_name": "CTM GPU renamed",
        "item_sn": "CONTRACT-TEST-CTM-C1",
        "item_category": "gpu",
        "item_status": "Deployed",       # attempt to dislodge
        "location_id": "",
    })
    assert r.status_code in (200, 303), r.text
    assert _status(db, ctm["comp1"]) == "Installed"
    name = db.execute(sqltext(
        "SELECT item_name FROM item_schema.items WHERE id = :i"),
        {"i": ctm["comp1"]}).scalar()
    assert name == "CTM GPU renamed", "non-managed fields must still save"
