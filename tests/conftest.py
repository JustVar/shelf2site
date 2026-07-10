"""Shared fixtures for the contract tests.

These run INSIDE the app container against the live `asset_tracker` database
(there is no separate test cluster). Every fixture that writes cleans up after
itself and prefixes its rows with `contract-test` so anything left behind by a
crashed run is obvious and safe to delete.

Run them with:

    ssh admin@192.0.2.10 "cd /opt/asset_tracker && docker compose exec -T app python -m pytest tests/ -q"
"""

import secrets

import httpx
import pytest
from sqlalchemy import text as sqltext

from app.auth import hash_password
from app.database import SessionLocal
from app.models import User

BASE_URL = "http://127.0.0.1:8081"

# A password that clears every rule: >= PASSWORD_MIN_LENGTH, <= 72 bytes, not
# in the breach blocklist. Regenerated per run so it is never a real secret.
TEST_PASSWORD = "contract-test-" + secrets.token_urlsafe(12)

TEST_USERS = {
    "admin": "contract-test-admin",
    "editor": "contract-test-editor",
    "viewer": "contract-test-viewer",
    "kiosk": "contract-test-kiosk",
}
_ROLES = {"admin": "admin", "editor": "editor", "viewer": "viewer", "kiosk": "map_kiosk"}


@pytest.fixture(scope="session")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="session")
def users(db):
    """Create the four throwaway accounts; remove them (and their audit rows) after."""
    created = {}
    for key, username in TEST_USERS.items():
        u = db.query(User).filter(User.username == username).first()
        if u is None:
            u = User(username=username, display_name=f"Contract test {key}", role=_ROLES[key],
                     password_hash=hash_password(TEST_PASSWORD), is_active=True,
                     must_change_password=False)
            db.add(u)
        else:
            u.password_hash = hash_password(TEST_PASSWORD)
            u.role = _ROLES[key]
            u.is_active = True
            u.must_change_password = False
        db.commit()
        db.refresh(u)
        created[key] = u.id

    yield created

    for uid in created.values():
        # login writes audit rows; clear them so the user row can be removed
        db.execute(sqltext("DELETE FROM audit_log WHERE user_id = :i"), {"i": uid})
        db.execute(sqltext("DELETE FROM error_log WHERE user_id = :i"), {"i": uid})
        db.execute(sqltext("DELETE FROM users WHERE id = :i"), {"i": uid})
    db.commit()


def _client(username):
    c = httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=False)
    if username is not None:
        r = c.post("/login", data={"username": username, "password": TEST_PASSWORD})
        assert r.status_code == 302, f"login as {username} failed: HTTP {r.status_code}"
    return c


@pytest.fixture(scope="session")
def anon():
    with httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=False) as c:
        yield c


@pytest.fixture(scope="session")
def admin_client(users):
    with _client(TEST_USERS["admin"]) as c:
        yield c


@pytest.fixture(scope="session")
def editor_client(users):
    with _client(TEST_USERS["editor"]) as c:
        yield c


@pytest.fixture(scope="session")
def viewer_client(users):
    with _client(TEST_USERS["viewer"]) as c:
        yield c


@pytest.fixture(scope="session")
def kiosk_client(users):
    with _client(TEST_USERS["kiosk"]) as c:
        yield c
