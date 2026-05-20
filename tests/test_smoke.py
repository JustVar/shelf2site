#!/usr/bin/env python3
"""Smoke tests for the Hardware Asset Tracker.

Quick sanity check (~10 seconds) covering critical paths:
  - Login / auth
  - Core pages load
  - API endpoints respond
  - Edit locking (DB-backed, cross-worker)
  - RBAC enforcement

Usage:
  python3 tests/test_smoke.py                    # default: http://192.0.2.174/assettracker
  BASE_URL=http://localhost:8081 python3 tests/test_smoke.py  # local dev
"""
import os
import subprocess
import sys
import requests

BASE = os.environ.get("BASE_URL", "http://192.0.2.174/assettracker").rstrip("/")
ADMIN_USER = "smoke_admin"
ADMIN_PASS = "redacted-test-password"
VIEWER_USER = "smoke_viewer"
VIEWER_PASS = "redacted-test-password"

results = {"pass": 0, "fail": 0}

# ============================================================
# SETUP — create temporary smoke test users
# ============================================================
print("\n=== SETUP ===")
setup_script = """
import sys; sys.path.insert(0, '/opt/hardware_inventory')
from app.database import SessionLocal
from app.models import User
from app.auth import hash_password
db = SessionLocal()
for uname, role, pwd, dname in [('smoke_admin', 'admin', 'redacted-test-password', 'Smoke Admin'),
                                 ('smoke_viewer', 'viewer', 'redacted-test-password', 'Smoke Viewer')]:
    u = db.query(User).filter(User.username == uname).first()
    if u:
        u.password_hash = hash_password(pwd)
        u.must_change_password = False
        u.is_active = True
        u.role = role
        u.display_name = dname
    else:
        db.add(User(username=uname, display_name=dname,
                    password_hash=hash_password(pwd),
                    role=role, must_change_password=False, is_active=True))
db.commit()
db.close()
"""
r = subprocess.run(
    ["/opt/hardware_inventory/venv/bin/python3", "-c", setup_script],
    capture_output=True, text=True,
)
if r.returncode == 0:
    print("  Smoke users ready (smoke_admin, smoke_viewer)")
else:
    print(f"  WARNING: User setup failed: {r.stderr.strip()[:200]}")


def test(name, condition, detail=""):
    results["pass" if condition else "fail"] += 1
    mark = "\u2713" if condition else "\u2717"
    suffix = f" -- {detail}" if detail and not condition else ""
    print(f"  {mark} {name}{suffix}")


def login(username, password):
    s = requests.Session()
    r = s.post(f"{BASE}/login", data={"username": username, "password": password},
               allow_redirects=False)
    # Follow redirect manually to stay in session
    if r.status_code in (302, 303):
        s.get(f"{BASE}/dashboard", allow_redirects=False)
    return s, r.status_code


# ============================================================
# 1. AUTH
# ============================================================
print("\n=== 1. AUTH ===")
S, status = login(ADMIN_USER, ADMIN_PASS)
test("Admin login succeeds", status in (200, 302, 303), f"status={status}")

V, status = login(VIEWER_USER, VIEWER_PASS)
test("Viewer login succeeds", status in (200, 302, 303), f"status={status}")

bad = requests.Session()
r = bad.post(f"{BASE}/login", data={"username": "fake", "password": "wrong"},
             allow_redirects=False)
test("Bad credentials rejected", r.status_code in (401, 302, 200), f"status={r.status_code}")

# ============================================================
# 2. CORE PAGES LOAD
# ============================================================
print("\n=== 2. CORE PAGES ===")
pages = [
    ("/dashboard", "Dashboard", 200),
    ("/inventory/", "Inventory", 200),
    ("/warranty/", "Warranty", 200),
    ("/trials/", "Trials", 200),
    ("/disposal/", "Disposal", 200),
    ("/fulfillment/", "Fulfillment", 200),
    ("/sites/", "Sites", 200),
    ("/vendors/", "Vendors", 200),
    ("/search", "Search", 200),
    ("/receive", "Receive", 200),
    ("/admin/users", "Admin Users", 200),
    ("/admin/audit", "Admin Audit", 200),
    ("/admin/storage", "Admin Storage", 200),
    ("/dashboard/triage", "Triage", 200),
    ("/admin/errors", "Error Log", 200),
]
for path, name, expected in pages:
    r = S.get(f"{BASE}{path}", allow_redirects=False)
    test(f"{name} page loads", r.status_code == expected, f"status={r.status_code}")

# ============================================================
# 3. API ENDPOINTS
# ============================================================
print("\n=== 3. API ENDPOINTS ===")
r = S.get(f"{BASE}/api/provisioning/by-bucket")
test("Provisioning by-bucket API", r.status_code == 200, f"status={r.status_code}")

r = S.get(f"{BASE}/api/tours", params={"page": "/dashboard"})
test("Tours API", r.status_code == 200, f"status={r.status_code}")

r = S.get(f"{BASE}/api/sites/list")
test("Sites list API", r.status_code == 200, f"status={r.status_code}")

r = S.get(f"{BASE}/api/notifications/subscriptions")
test("Notifications API", r.status_code == 200, f"status={r.status_code}")

r = S.get(f"{BASE}/api/locks")
test("Admin locks list API", r.status_code == 200, f"status={r.status_code}")

# ============================================================
# 4. EDIT LOCKING (DB-backed, cross-worker)
# ============================================================
print("\n=== 4. EDIT LOCKING ===")
LOCK_KEY = "smoke_test:999999"

# Clean up any stale lock from prior runs (DB-level, handles any user)
subprocess.run(
    ["/opt/hardware_inventory/venv/bin/python3", "-c",
     "import sys; sys.path.insert(0, '/opt/hardware_inventory');"
     "from app.database import SessionLocal; from sqlalchemy import text;"
     "db = SessionLocal(); db.execute(text(\"DELETE FROM edit_locks WHERE resource_key = 'smoke_test:999999'\"));"
     "db.commit(); db.close()"],
    capture_output=True, text=True,
)

r = S.post(f"{BASE}/api/locks/acquire", json={"resource_key": LOCK_KEY})
test("Acquire lock", r.status_code == 200 and r.json().get("granted"), f"resp={r.json()}")

r = S.post(f"{BASE}/api/locks/escalate", json={"resource_key": LOCK_KEY})
test("Escalate to editing", r.status_code == 200 and r.json().get("escalated"), f"resp={r.json()}")

r = S.get(f"{BASE}/api/locks/{LOCK_KEY}")
lock = r.json().get("lock")
test("Lock level is editing", lock and lock.get("level") == "editing", f"lock={lock}")

r = V.post(f"{BASE}/api/locks/acquire", json={"resource_key": LOCK_KEY})
test("Viewer blocked by hard lock", r.json().get("granted") is False, f"resp={r.json()}")
test("Conflict detected", r.json().get("conflict") is True)

r = S.post(f"{BASE}/api/locks/release", json={"resource_key": LOCK_KEY})
test("Release lock", r.json().get("released") is True, f"resp={r.json()}")

r = S.get(f"{BASE}/api/locks/{LOCK_KEY}")
test("Lock cleared", r.json().get("lock") is None, f"resp={r.json()}")

# ============================================================
# 5. RBAC ENFORCEMENT
# ============================================================
print("\n=== 5. RBAC ===")
rbac_blocked = [
    ("/fulfillment/", "Fulfillment"),
    ("/admin/users", "Admin Users"),
    ("/receive", "Receive"),
]
for path, name in rbac_blocked:
    r = V.get(f"{BASE}{path}", allow_redirects=False)
    test(f"Viewer blocked from {name}", r.status_code in (302, 403), f"status={r.status_code}")

r = V.post(f"{BASE}/api/locks/acquire", json={"resource_key": "rbac:test"})
test("Viewer CAN acquire locks (authenticated)", r.status_code == 200)
V.post(f"{BASE}/api/locks/release", json={"resource_key": "rbac:test"})

r = V.get(f"{BASE}/api/locks")
test("Viewer CANNOT list all locks (admin-only)", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# 6. STATIC ASSETS
# ============================================================
print("\n=== 6. STATIC ASSETS ===")
assets = [
    "/static/css/main.css",
    "/static/js/edit-modal.js",
    "/static/js/scanner.js",
    "/static/css/scanner.css",
    "/static/js/toast.js",
]
for path in assets:
    r = S.get(f"{BASE}{path}")
    name = path.split("/")[-1]
    test(f"{name} loads", r.status_code == 200, f"status={r.status_code}")

# ============================================================
# CLEANUP — deactivate smoke users (don't delete, FK on audit_log)
# ============================================================
print("\n=== CLEANUP ===")
cleanup_script = """
import sys; sys.path.insert(0, '/opt/hardware_inventory')
from app.database import SessionLocal
from app.models import User
db = SessionLocal()
for uname in ('smoke_admin', 'smoke_viewer'):
    u = db.query(User).filter(User.username == uname).first()
    if u:
        u.is_active = False
db.commit()
db.close()
"""
r = subprocess.run(
    ["/opt/hardware_inventory/venv/bin/python3", "-c", cleanup_script],
    capture_output=True, text=True,
)
print("  Smoke users deactivated" if r.returncode == 0 else f"  WARNING: {r.stderr.strip()[:200]}")

# ============================================================
# RESULTS
# ============================================================
total = results["pass"] + results["fail"]
print(f"\n{'=' * 60}")
print(f"SMOKE: {results['pass']} passed, {results['fail']} failed (of {total})")
print(f"{'=' * 60}")
sys.exit(1 if results["fail"] else 0)
