"""Contract tests for the three derived audit page filters (b59f8b4).

b59f8b4 replaced a hardcoded 13-option event type list with a distinct query,
restricted the user dropdown to actors who appear in the log, and computed the
total separately from the 500 row cap. Nothing tested any of it, so a plausible
cleanup (simplify back to a static list, just query all users, drop the extra
count) could revert each one and the suite would stay green.

Each test is written to FAIL against the pre-b59f8b4 behaviour:

  1. seeds an event type invented inside the test, which no static list can
     contain by construction
  2. asserts a non-actor is ABSENT from the roster, which "query every user"
     cannot satisfy
  3. asserts a filtered total and the absence of the old unconditional
     "most recent 500" notice

Seeds are contract-test prefixed and deleted in teardown. Assertions compare
against what the test seeded, never absolute counts: the live log grows with
every login (the suite shares the live database, see CLAUDE.md).
"""

import secrets

import pytest
from sqlalchemy import text as sqltext

from app.models import User


@pytest.fixture
def audit_seed(db):
    """A unique event type (fits varchar(32)) seeded as rows with no user_id,
    plus two throwaway users: one actor with a log row, one non-actor."""
    ev = "contract-test-ev-" + secrets.token_hex(4)          # 25 chars
    tag = secrets.token_hex(4)
    actor_name = f"Contract audit actor {tag}"
    ghost_name = f"Contract audit ghost {tag}"

    # ORM constructor, not raw SQL: users has NOT NULL columns whose defaults
    # live on the model (slack_auto_match and the permission enums), so a raw
    # INSERT violates them. Same reason the conftest users fixture uses it.
    db.rollback()
    actor = User(username=f"contract-test-aud-actor-{tag}", display_name=actor_name,
                 role="viewer", password_hash="x", is_active=True,
                 must_change_password=False)
    ghost = User(username=f"contract-test-aud-ghost-{tag}", display_name=ghost_name,
                 role="viewer", password_hash="x", is_active=True,
                 must_change_password=False)
    db.add_all([actor, ghost])
    db.commit()
    actor_id, ghost_id = actor.id, ghost.id

    for _ in range(3):
        db.execute(sqltext(
            "INSERT INTO audit_log (event_type, user_id, details) "
            "VALUES (:e, NULL, 'contract-test seed')"), {"e": ev})
    db.execute(sqltext(
        "INSERT INTO audit_log (event_type, user_id, details) "
        "VALUES (:e, :a, 'contract-test seed, actor row')"), {"e": ev, "a": actor_id})
    db.commit()

    yield {"event_type": ev, "actor_id": actor_id, "actor_name": actor_name,
           "ghost_id": ghost_id, "ghost_name": ghost_name}

    db.execute(sqltext("DELETE FROM audit_log WHERE event_type = :e"), {"e": ev})
    db.execute(sqltext("DELETE FROM users WHERE id IN (:a, :g)"),
               {"a": actor_id, "g": ghost_id})
    db.commit()


def test_event_types_are_derived_from_the_log(admin_client, audit_seed):
    """Fails pre-b59f8b4: a type invented inside this test cannot appear in a
    hardcoded option list. Guards the distinct query at admin.py:42-53."""
    r = admin_client.get("/admin/audit")
    assert r.status_code == 200, r.text
    assert f'value="{audit_seed["event_type"]}"' in r.text, (
        "the invented event type must appear as a dropdown option")


def test_user_roster_is_actors_only(admin_client, audit_seed):
    """Both directions, because 'query every user' passes the first alone.
    Guards the actor_ids restriction at admin.py:35-37."""
    r = admin_client.get("/admin/audit")
    assert r.status_code == 200, r.text
    assert audit_seed["actor_name"] in r.text, "an actor with a log row must be offered"
    assert audit_seed["ghost_name"] not in r.text, (
        "a user with no log rows must NOT appear anywhere on the page")


def test_total_is_real_and_notice_is_conditional(admin_client, audit_seed):
    """Filter on the invented type so the expected total is exactly what was
    seeded, immune to live log growth. Guards total_entries at admin.py:22 and
    the conditional notice in the template.

    Pre-b59f8b4 the notice read 'Showing most recent 500 entries.'
    unconditionally, at any actual count."""
    r = admin_client.get(f"/admin/audit?event_type={audit_seed['event_type']}")
    assert r.status_code == 200, r.text
    assert "Showing 4 entries" in r.text, "the filtered total must be the seeded count"
    assert "Showing most recent 500" not in r.text, (
        "the truncation notice must be absent below the cap")
