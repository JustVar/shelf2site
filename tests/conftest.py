"""Shared fixtures for the contract tests.

The tests drive the running app over HTTP at 127.0.0.1:8081 and read its
database directly (there is no separate test cluster). Every fixture that
writes cleans up after itself and prefixes its rows with `contract-test`, so
anything left behind by a crashed run is obvious and safe to delete.

Run them inside the app container:

    docker compose exec -T app python -m pytest tests/ -q
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
    """A logged-in client. Yielded (not `with`-wrapped) by the fixtures below:
    issuing the login request already opens the client, and httpx refuses to
    re-enter an opened instance."""
    c = httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=False)
    if username is not None:
        r = c.post("/login", data={"username": username, "password": TEST_PASSWORD})
        assert r.status_code == 302, f"login as {username} failed: HTTP {r.status_code}"
    return c


@pytest.fixture(scope="session")
def anon():
    c = httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=False)
    yield c
    c.close()


def _client_fixture(role_key):
    def fixture(users):
        c = _client(TEST_USERS[role_key])
        yield c
        c.close()
    return pytest.fixture(scope="session")(fixture)


admin_client = _client_fixture("admin")
editor_client = _client_fixture("editor")
viewer_client = _client_fixture("viewer")
kiosk_client = _client_fixture("kiosk")


@pytest.fixture
def fresh_viewer_client(users):
    """A viewer session of its own, for a test that could end the session.

    viewer_client is shared by the whole run; a test that logs it out by
    mistake would fail every later viewer test with a misleading error.
    """
    c = _client(TEST_USERS["viewer"])
    yield c
    c.close()
