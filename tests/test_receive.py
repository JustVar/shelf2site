"""Receive-path contract tests — the happy path plus the malformed inputs that
used to 500.

These write to the live database; each test removes the rows it creates.
"""

import pytest
from sqlalchemy import text as sqltext


@pytest.fixture
def cleanup_pending(db):
    """Remove any pending_devices row this module's scanner created."""
    yield
    db.execute(sqltext("DELETE FROM pending_devices WHERE scanner_id LIKE 'intake:contract-test%'"))
    db.commit()


def _pending_row(db, serial_hint):
    return db.execute(
        sqltext("""
            SELECT mac_address::text, manufacturer, status
            FROM pending_devices
            WHERE scanner_id LIKE 'intake:contract-test%' AND manufacturer = :m
            ORDER BY id DESC LIMIT 1
        """),
        {"m": serial_hint},
    ).fetchone()


def test_receive_happy_path_creates_a_pending_device(editor_client, db, cleanup_pending):
    r = editor_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-1",
        "manufacturer": "ContractTestCo",
        "mac_address": "AA:BB:CC:DD:EE:10",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_review"

    db.commit()  # see the app worker's committed row
    row = _pending_row(db, "ContractTestCo")
    assert row is not None, "no pending_devices row was created"
    assert row[2] == "pending"


def test_receive_normalizes_a_dash_separated_mac(editor_client, db, cleanup_pending):
    """AA-BB-... used to hit the macaddr column raw and raise InvalidTextRepresentation."""
    r = editor_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-2",
        "manufacturer": "ContractTestDash",
        "mac_address": "AA-BB-CC-DD-EE-11",
    })
    assert r.status_code == 200, r.text

    db.commit()
    row = _pending_row(db, "ContractTestDash")
    assert row is not None
    # pending_devices.mac_address is varchar, so the stored value keeps the
    # helper's canonical casing; the point is that the dashes became colons.
    assert row[0] == "AA:BB:CC:DD:EE:11", f"MAC stored un-normalized: {row[0]}"


def test_receive_rejects_an_invalid_mac_with_a_400(editor_client, cleanup_pending):
    r = editor_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-3",
        "mac_address": "AA:BB:CC:DD:GG",
    })
    assert r.status_code == 400
    assert "mac_address" in r.json().get("field_errors", {})


def test_receive_handles_a_null_mac_without_crashing(editor_client, db, cleanup_pending):
    """`body.get("mac", "").strip()` raised AttributeError on an explicit JSON null."""
    r = editor_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-4",
        "manufacturer": "ContractTestNull",
        "mac_address": None,
        "mac_address_1": None,
        "mac_address_2": None,
    })
    assert r.status_code == 200, r.text

    db.commit()
    row = _pending_row(db, "ContractTestNull")
    assert row is not None
    # pending_devices.mac_address is NOT NULL — the route falls back to a synthetic key
    assert row[0], "a null MAC must not produce a NULL mac_address insert"


def test_receive_handles_a_null_serial_without_crashing(editor_client):
    r = editor_client.post("/api/receive/device", json={"serial": None})
    assert r.status_code == 400
    assert "Serial" in r.json()["error"]


def test_receive_requires_editor_tier(viewer_client):
    r = viewer_client.post("/api/receive/device", json={"serial": "CONTRACT-TEST-5"})
    assert r.status_code == 403


# ── H1: unified, case-insensitive lookup (audit F1/F5/F11) ──────────────────

@pytest.fixture
def contract_item(db):
    """A throwaway item_schema.items row for lookup tests."""
    db.execute(sqltext("""
        INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status)
        VALUES ('Contract Test Item', 'CONTRACT-TEST-H1-ITEM', 'gpu', 'Unassigned')
    """))
    db.commit()
    yield "CONTRACT-TEST-H1-ITEM"
    db.execute(sqltext("DELETE FROM item_schema.items WHERE item_sn = 'CONTRACT-TEST-H1-ITEM'"))
    db.commit()


def test_scan_finds_serials_in_item_schema(editor_client, contract_item):
    """Audit F1: serials living only in item_schema used to scan as 'unknown',
    inviting double intake of the same physical unit."""
    r = editor_client.post("/api/receive/scan", json={"barcode": contract_item})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "already_exists", body
    assert body["table"] == "items"


def test_scan_matches_case_insensitively(editor_client, contract_item):
    """Audit F5: wedge scanners emit uppercase; stored serials are as-imported."""
    r = editor_client.post("/api/receive/scan", json={"barcode": contract_item.lower()})
    assert r.json()["status"] == "already_exists"


def test_check_duplicate_sees_item_schema(editor_client, contract_item):
    r = editor_client.get(f"/api/receive/check-duplicate?serial={contract_item.lower()}")
    body = r.json()
    assert body["exists"] is True
    assert body["table"] == "items"
