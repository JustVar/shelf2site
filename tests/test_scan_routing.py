"""Contract tests for the §4 decode routing table (POST /api/receive/scan).

One parametrized case per routing rule, plus the documented tie-breaks
(12-hex MAC-vs-serial, Q-prefix alnum-only) and GS1-128 unwrapping.
Seeded rows are CONTRACT-TEST-prefixed and removed by the fixture.
"""

import pytest
from sqlalchemy import text as sqltext

from app.scan_routing import classify, preprocess


@pytest.fixture(scope="module")
def routing_rows(db):
    """Seed one findable row per lookup surface the table routes to."""
    ids = {}
    ids["item"] = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status, "
        "item_mac_address_1, platform_uuid, item_pn, tracking_number) VALUES "
        "('CONTRACT-TEST Route Box', 'CONTRACT-TEST-RT-1', 'edge_box', 'Unassigned', "
        "'AA:BB:CC:11:22:33', 'DEADBEEF-1111-2222-3333-444455556666', "
        "'PVA-25-30NR-099999', '1Z999AA10123456784') RETURNING id")).scalar()
    ids["hexserial"] = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) VALUES "
        "('CONTRACT-TEST Hex Serial', 'AABBCCDDEEF1', 'gpu', 'Unassigned') RETURNING id")).scalar()
    ids["order"] = db.execute(sqltext(
        "INSERT INTO customer_orders (order_number, customer_name, order_type, status, is_sensitive, tracking_number) "
        "VALUES ('AT-999901', 'CONTRACT-TEST Route Corp', 'pilot', 'new', false, '9400111899560001234567') "
        "RETURNING id")).scalar()
    ids["oui"] = db.execute(sqltext(
        "INSERT INTO oui_allowlist (oui_prefix, manufacturer, is_active) "
        "VALUES ('FE:ED:99', 'CONTRACT-TEST OUI Co', true) "
        "ON CONFLICT (oui_prefix) DO NOTHING RETURNING id")).scalar()
    db.commit()
    yield ids
    db.rollback()
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = ANY(:i)"),
               {"i": [ids["item"], ids["hexserial"]]})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :i"), {"i": ids["order"]})
    if ids["oui"]:
        db.execute(sqltext("DELETE FROM oui_allowlist WHERE id = :i"), {"i": ids["oui"]})
    db.commit()


def _scan(client, barcode):
    r = client.post("/api/receive/scan", json={"barcode": barcode})
    assert r.status_code == 200, r.text
    return r.json()


# ── pure classification (no DB) — the 12 rules + tie-breaks ─────────────────

@pytest.mark.parametrize("value,expected", [
    ("AA:BB:CC:DD:EE:FF", "mac"),                       # 1 colon
    ("aa-bb-cc-dd-ee-ff", "mac"),                       # 1 dash
    ("AABB.CCDD.EEFF", "mac"),                          # 1 dotted quad-pairs
    ("DEADBEEF-1111-2222-3333-444455556666", "uuid"),   # 2
    ("1Z999AA10123456784", "tracking"),                 # 3 UPS
    ("00123456789012345678", "tracking"),               # 4 SSCC
    ("9400111899560001234567", "tracking"),             # 4 USPS 22-digit
    ("AT-9009", "order_number"),                        # 5
    ("SO-9009", "order_number"),                        # 5 current prefix
    ("PVA-25-30NR-099999", "unit_pn"),                  # 6
    ("edge100nr-000003", "unit_pn"),                    # 6 lowercase PN
    ("PVA-100-30NR", "sku"),                            # 7
    ("EDGE25-56TB-NR", "sku"),                          # 7
    ("PVA50-84TB-Z2", "sku"),                           # 7
    ("E2C-25-2TB", "sku"),                              # 7
    ("AABBCCDDEEF1", "hex12"),                          # 8 (has hex letters)
    ("123456789012", "ambiguous_digits"),               # 8-vs-11 tie-break: pure digits are NOT hex12
    ("USCFS0226099", "uscf_serial"),                    # 9
    ("Q1234567890", "qnap_candidate"),                  # 10
    ("QHTTP://EVIL", "serial"),                         # 10 tie-break: non-alnum never QNAP
    ("123456789012345", "ambiguous_digits"),            # 11 (15 digits)
    ("4006381333931", "ambiguous_digits"),              # 11 EAN-13 (bench: product code)
    ("SN-2026-XYZ", "serial"),                          # 12
    ("AB", "unclassified"),                             # too short
])
def test_classification_rules(value, expected):
    assert classify(value) == expected


def test_gs1_unwrapping():
    value, gs1 = preprocess("]C1010123456789012821CONTRACT-RT-SER1")
    assert gs1["gtin"] == "01234567890128"
    assert gs1["serial"] == "CONTRACT-RT-SER1"
    assert value == "CONTRACT-RT-SER1"
    value2, gs12 = preprocess("(01)01234567890128(21)SER99")
    assert gs12["serial"] == "SER99" and value2 == "SER99"
    value3, gs13 = preprocess("]C100123456789012345678")
    assert gs13["sscc"] == "123456789012345678"
    assert value3 == "00123456789012345678"
    assert classify(value3) == "tracking"


# ── endpoint round trips per class ───────────────────────────────────────────

def test_mac_hit_and_miss(editor_client, routing_rows):
    hit = _scan(editor_client, "aa:bb:cc:11:22:33")
    assert hit["status"] == "already_exists" and hit["matched_on"] == "mac"
    assert hit["table"] == "items" and hit["device_id"] == routing_rows["item"]
    miss = _scan(editor_client, "AA:BB:CC:99:99:99")
    assert miss["status"] == "unknown" and miss["class"] == "mac"
    assert "MAC" in miss["guidance"] and miss["prefill"]["mac_address"] == "AA:BB:CC:99:99:99"


def test_uuid_hit_and_miss(editor_client, routing_rows):
    hit = _scan(editor_client, "deadbeef-1111-2222-3333-444455556666")
    assert hit["status"] == "already_exists" and hit["matched_on"] == "uuid"
    miss = _scan(editor_client, "00000000-0000-4000-8000-000000000000")
    assert miss["status"] == "unknown" and "serial instead" in miss["guidance"]


def test_tracking_hit_and_miss(editor_client, routing_rows):
    hit = _scan(editor_client, "1Z999AA10123456784")
    assert hit["status"] == "already_exists" and hit["matched_on"] == "tracking"
    order_hit = _scan(editor_client, "9400111899560001234567")
    assert order_hit["table"] == "customer_orders"
    assert order_hit["order_number"] == "AT-999901"
    miss = _scan(editor_client, "1Z999AA10199999999")
    assert miss["status"] == "unknown" and "receiving event" in miss["guidance"]


def test_order_number_hit_and_miss(editor_client, routing_rows):
    hit = _scan(editor_client, "at-999901")
    assert hit["status"] == "already_exists" and hit["table"] == "customer_orders"
    assert hit["customer_name"] == "CONTRACT-TEST Route Corp"
    miss = _scan(editor_client, "AT-424242")
    assert miss["status"] == "unknown" and miss["guidance"] == "Order not found."


def test_unit_pn_hit_and_miss(editor_client, routing_rows):
    hit = _scan(editor_client, "pva-25-30nr-099999")
    assert hit["status"] == "already_exists" and hit["matched_on"] == "unit_pn"
    miss = _scan(editor_client, "PVA-25-30NR-088888")
    assert miss["status"] == "unknown" and miss["prefill"]["item_pn"] == "PVA-25-30NR-088888"


def test_sku_is_recognized_not_a_unit(editor_client, routing_rows):
    got = _scan(editor_client, "pva-100-30nr")   # real catalog SKU
    assert got["status"] == "recognized" and got["class"] == "sku"
    assert "not a unit serial" in got["guidance"]
    assert got["prefill"]["item_sku"] == "PVA-100-30NR"
    miss = _scan(editor_client, "PVA-77-77ZZ")
    assert miss["status"] == "unknown" and "not in the catalog" in miss["guidance"]


def test_hex12_tiebreak_serial_then_mac_then_oui(editor_client, routing_rows):
    serial_hit = _scan(editor_client, "aabbccddeef1")
    assert serial_hit["status"] == "already_exists" and serial_hit["matched_on"] == "serial"
    mac_hit = _scan(editor_client, "AABBCC112233")
    assert mac_hit["status"] == "already_exists" and mac_hit["matched_on"] == "mac"
    oui_hint = _scan(editor_client, "FEED99ABCDEF")
    assert oui_hint["status"] == "unknown" and "CONTRACT-TEST OUI Co" in oui_hint["guidance"]
    assert oui_hint["prefill"]["mac_address"] == "FE:ED:99:AB:CD:EF"
    plain = _scan(editor_client, "ABCDEF123456")
    assert plain["status"] == "unknown" and "MAC" in plain["guidance"]


def test_uscf_prefills_2026_edge_box(editor_client, routing_rows):
    got = _scan(editor_client, "USCFS0226ZZZ")
    assert got["status"] == "recognized"
    assert got["prefill"]["target_table"] == "edge_boxes"
    assert "2026 edge box" in got["guidance"]


def test_qnap_requires_confirm_and_kills_url_false_positive(editor_client):
    got = _scan(editor_client, "Q1234567890")
    assert got["status"] == "recognized" and got["class"] == "qnap_candidate"
    assert "confirm" in got["guidance"].lower()
    assert got["prefill"]["target_table"] == "nas_devices"
    url = _scan(editor_client, "QHTTP://EVIL.EXAMPLE/A")
    assert url["class"] == "serial" and url["status"] == "unknown"


def test_ambiguous_digits_guidance(editor_client):
    got = _scan(editor_client, "4006381333931")
    assert got["status"] == "unknown" and got["class"] == "ambiguous_digits"
    assert "product or shipping code" in got["guidance"]


def test_gs1_wrapped_serial_finds_the_item(editor_client, routing_rows):
    got = _scan(editor_client, "]C10101234567890128" + "21CONTRACT-TEST-RT-1")
    assert got["status"] == "already_exists", got
    assert got["device_id"] == routing_rows["item"]
    assert got["gs1"]["serial"] == "CONTRACT-TEST-RT-1"


def test_plain_serial_still_works(editor_client, routing_rows):
    got = _scan(editor_client, "contract-test-rt-1")
    assert got["status"] == "already_exists" and got["table"] == "items"
    miss = _scan(editor_client, "CONTRACT-TEST-NOPE-1")
    assert miss["status"] == "unknown" and "manually" in miss["guidance"]
