"""Order deletion is refused while any deployment record exists.

Ratified in docs/specs/fulfillment-vendor-direction.md. Without the guard,
customer_orders -> deployment_records is ON DELETE CASCADE and
deployment_records -> installation_certification cascades again, so one
unguarded order delete erased visits and their certifications with only a one
line audit row surviving. No route deletes a deployment record directly; the
order delete was the unguarded back door.

Fixture pattern per items 31 and 33: ORM/API creation, rollback guard,
commit-then-DELETE teardown, zero debris.
"""

import pytest
from sqlalchemy import text as sqltext


@pytest.fixture
def two_orders(admin_client, db):
    """Order A with one deployment record, order B with none."""
    db.rollback()
    ids = {}
    for key, name in (("a", "CONTRACT-TEST DelGuard A"), ("b", "CONTRACT-TEST DelGuard B")):
        r = admin_client.post("/api/orders/", json={
            "customer_name": name, "order_type": "pilot",
            "expected_return": "2026-10-01",
        })
        assert r.status_code == 200, r.text
        ids[key] = r.json()["id"]

    dep_id = db.execute(sqltext(
        "INSERT INTO deployment_records (customer_order_id, status) "
        "VALUES (:o, 'scheduled') RETURNING id"), {"o": ids["a"]}).scalar()
    db.commit()

    yield {"a": ids["a"], "b": ids["b"], "dep": dep_id}

    db.rollback()
    db.execute(sqltext("DELETE FROM deployment_records WHERE customer_order_id IN (:a, :b)"),
               {"a": ids["a"], "b": ids["b"]})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id IN (:a, :b)"),
               {"a": ids["a"], "b": ids["b"]})
    db.commit()


def _count(db, table, order_id):
    db.commit()
    col = "id" if table == "customer_orders" else "customer_order_id"
    return db.execute(sqltext(
        f"SELECT count(*) FROM {table} WHERE {col} = :o"), {"o": order_id}).scalar()


def test_delete_refused_while_deployment_records_exist(admin_client, db, two_orders):
    """Dies if the guard is removed: the CASCADE would return 200 and take the
    deployment record (and any certification on it) with the order."""
    r = admin_client.delete(f"/api/orders/{two_orders['a']}")
    assert r.status_code == 409, r.text
    assert "deployment record" in r.json()["error"]

    assert _count(db, "customer_orders", two_orders["a"]) == 1, "order must survive"
    assert _count(db, "deployment_records", two_orders["a"]) == 1, "visit must survive"


def test_delete_still_works_with_no_deployment_records(admin_client, db, two_orders):
    """The non-regression half: a bare order still deletes."""
    r = admin_client.delete(f"/api/orders/{two_orders['b']}")
    assert r.status_code == 200, r.text
    assert _count(db, "customer_orders", two_orders["b"]) == 0, "order must be gone"
