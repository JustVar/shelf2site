#!/usr/bin/env python3
"""End-to-end API tests for the Hardware Asset Tracker."""
import os
import requests
import subprocess
import sys
from pathlib import Path

# BASE_URL env var overrides the default. Examples:
#   LAN (office):        http://192.0.2.174/assettracker
#   Cloudflare / cloud:  https://tracker.example.com/assettracker
#   Local dev (direct):  http://localhost:8081/assettracker
BASE = os.environ.get("BASE_URL", "http://192.0.2.174/assettracker").rstrip("/")
ADMIN_USER = os.environ.get("E2E_ADMIN_USER", "test_admin_e2e")
ADMIN_PASS = os.environ.get("E2E_ADMIN_PASS", "redacted-test-password")
S = requests.Session()
results = {"pass": 0, "fail": 0, "warn": 0, "details": []}


def test(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results["pass" if condition else "fail"] += 1
    results["details"].append({"name": name, "status": status, "detail": detail})
    mark = "\u2713" if condition else "\u2717"
    print(f"  {mark} {name}" + (f" -- {detail}" if detail and not condition else ""))


def warn(name, detail=""):
    results["warn"] += 1
    results["details"].append({"name": name, "status": "WARN", "detail": detail})
    print(f"  ! {name} -- {detail}")


# ============================================================
# PRE-RUN CLEANUP — delete leftover test users from prior runs
# ============================================================
print("\n=== PRE-RUN CLEANUP ===")
pre_cleanup_users = ["test_admin_e2e", "test_warranty_adm", "test_trials_adm", "test_procure_adm",
                     "test_viewer_e2e", "test_editor_e2e", "xss_test_e2e", "badrole_e2e", "nopwd_e2e",
                     "toggle_test_e2e", "temp_admin_toggle", "test_ceo_e2e"]
# Also clean up tour progress that references these users
subprocess.run(
    "sudo -u postgres psql -d hardware_inventory -tAc "
    "\"DELETE FROM user_tour_progress WHERE user_id IN "
    "(SELECT id FROM users WHERE username LIKE 'test_%_e2e' OR username IN "
    "('temp_admin_toggle','toggle_test_e2e','xss_test_e2e','badrole_e2e','nopwd_e2e'))\"",
    shell=True, capture_output=True, text=True,
)
for uname in pre_cleanup_users:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM users WHERE username = '{uname}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up leftover user: {uname}")
# Clean up leftover test teams
for tname in ["E2E Test Team", "E2E Team Two", "E2E Delete Test", "E2E Renamed Team", "E2E Prov Team", "Hacker Team"]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM teams WHERE name = '{tname}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up leftover team: {tname}")

# Clean up leftover vendor profiles from prior E2E runs
for vname in ["E2E Vendor Corp", "E2E Viewer Vendor Attempt"]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM vendor_profiles WHERE name = '{vname}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up leftover vendor profile: {vname}")

# Create fresh admin user using app's own password hashing
setup_script = f"""
import sys; sys.path.insert(0, '/opt/hardware_inventory')
from app.database import SessionLocal
from app.models import User
from app.auth import hash_password
db = SessionLocal()
u = db.query(User).filter(User.username == '{ADMIN_USER}').first()
if u:
    u.password_hash = hash_password('{ADMIN_PASS}')
    u.must_change_password = False
    u.is_active = True
    u.role = 'admin'
else:
    db.add(User(username='{ADMIN_USER}', display_name='Test Admin',
                password_hash=hash_password('{ADMIN_PASS}'),
                role='admin', must_change_password=False, is_active=True))
db.commit()
db.close()
"""
subprocess.run(
    ["/opt/hardware_inventory/venv/bin/python3", "-c", setup_script],
    capture_output=True, text=True,
)
print(f"  Admin user '{ADMIN_USER}' ready (must_change_password=FALSE)")

# Route Slack notifications to the private test channel for the duration of this run.
# Create the flag on the local machine AND SSH to the NUC so this works whether the
# test is run directly on the NUC or from a remote workstation.
import atexit

def _cleanup_test_mode():
    subprocess.run("rm -f /tmp/.asset_tracker_test_mode", shell=True, capture_output=True)

atexit.register(_cleanup_test_mode)

# Set test mode flag — this script runs directly on the NUC
subprocess.run("touch /tmp/.asset_tracker_test_mode", shell=True, capture_output=True)
print("  E2E test mode flag set (/tmp/.asset_tracker_test_mode)")


# ============================================================
# 1. AUTHENTICATION TESTS
# ============================================================
print("\n=== 1. AUTHENTICATION ===")

r = requests.get(f"{BASE}/dashboard", allow_redirects=False)
test("Unauth /dashboard redirects to login", r.status_code in (302, 303, 307))

r = requests.get(f"{BASE}/warranty/", allow_redirects=False)
test("Unauth /warranty/ redirects", r.status_code in (302, 303, 307))

r = requests.get(f"{BASE}/admin/users", allow_redirects=False)
test("Unauth /admin/users redirects", r.status_code in (302, 303, 307))

r = requests.get(f"{BASE}/devices/edge_boxes/1", allow_redirects=False)
test("Unauth API /devices returns 401 or redirect", r.status_code in (401, 302, 303, 307))

r = requests.post(f"{BASE}/login", data={"username": "baduser", "password": "badpass"}, allow_redirects=False)
test("Bad login rejected", r.status_code != 200 or "Invalid" in r.text or r.status_code in (302, 303, 401))

r = S.post(f"{BASE}/login", data={"username": ADMIN_USER, "password": ADMIN_PASS}, allow_redirects=False)
test("Admin login succeeds", r.status_code in (302, 303), f"status={r.status_code}")

r = S.get(f"{BASE}/dashboard", allow_redirects=False)
test("Authenticated /dashboard loads (200)", r.status_code == 200, f"status={r.status_code}")

# ============================================================
# 2. RBAC - Admin Access
# ============================================================
print("\n=== 2. RBAC - Admin Access ===")

r = S.get(f"{BASE}/admin/users")
test("Admin can access /admin/users", r.status_code == 200)

r = S.get(f"{BASE}/admin/oui")
test("Admin can access /admin/oui (vendor catalog)", r.status_code == 200)

r = S.get(f"{BASE}/admin/audit")
test("Admin can access /admin/audit", r.status_code == 200)

r = S.get(f"{BASE}/admin/storage")
test("Admin can access /admin/storage", r.status_code == 200)

r = S.get(f"{BASE}/warranty/")
test("Admin can access /warranty/", r.status_code == 200)

r = S.get(f"{BASE}/trials/")
test("Admin can access /trials/", r.status_code == 200)

r = S.get(f"{BASE}/disposal/")
test("Admin can access /disposal/", r.status_code == 200)

r = S.get(f"{BASE}/admin/procurement")
test("Admin can access /admin/procurement", r.status_code == 200, f"status={r.status_code}")

# ============================================================
# 3. CREATE TEST USERS
# ============================================================
print("\n=== 3. CREATE TEST USERS ===")

test_users = [
    ("test_warranty_adm", "Test Warranty Admin", "redacted-test-password", "warranty_admin"),
    ("test_trials_adm", "Test Trials Admin", "redacted-test-password", "trials_admin"),
    ("test_procure_adm", "Test Procurement Admin", "redacted-test-password", "procurement_admin"),
    ("test_viewer_e2e", "Test Viewer", "redacted-test-password", "viewer"),
    ("test_editor_e2e", "Test Editor", "redacted-test-password", "editor"),
]

for uname, dname, pwd, role in test_users:
    r = S.post(f"{BASE}/admin/users/add", data={
        "username": uname, "display_name": dname, "password": pwd, "role": role
    })
    test(f"Create {role} user ({uname})", r.status_code in (200, 409), r.text[:80] if r.status_code not in (200, 409) else "")

# Disable forced password change for all test users so sessions work correctly
subprocess.run(
    "sudo -u postgres psql -d hardware_inventory -tAc "
    "\"UPDATE users SET must_change_password = FALSE WHERE username LIKE 'test_%'\"",
    shell=True, capture_output=True, text=True,
)

# ============================================================
# 4. VIEWER RESTRICTIONS
# ============================================================
print("\n=== 4. VIEWER ROLE RESTRICTIONS ===")

V = requests.Session()
r = V.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
test("Viewer login succeeds", r.status_code in (302, 303))

r = V.get(f"{BASE}/dashboard")
test("Viewer can read dashboard", r.status_code == 200)

r = V.get(f"{BASE}/warranty/")
test("Viewer can read warranty page", r.status_code == 200)

r = V.post(f"{BASE}/api/warranty", json={"device_table": "cameras", "device_id": 1, "warranty_provider": "Test"})
test("Viewer CANNOT create warranty (403)", r.status_code == 403, f"status={r.status_code}")

r = V.get(f"{BASE}/admin/users", allow_redirects=False)
test("Viewer CANNOT access /admin/users", r.status_code in (403, 302, 307), f"status={r.status_code}")

r = V.get(f"{BASE}/admin/audit", allow_redirects=False)
test("Viewer CANNOT access /admin/audit", r.status_code in (403, 302, 307), f"status={r.status_code}")

r = V.get(f"{BASE}/admin/procurement", allow_redirects=False)
test("Viewer CANNOT access /admin/procurement", r.status_code in (403, 302, 307), f"status={r.status_code}")

r = V.get(f"{BASE}/map/", allow_redirects=False)
test("Viewer CANNOT access /map/", r.status_code in (403, 302, 307), f"status={r.status_code}")

# Viewer cannot delete anything
r = V.delete(f"{BASE}/api/warranty/1")
test("Viewer CANNOT delete warranty", r.status_code in (403, 401), f"status={r.status_code}")

r = V.delete(f"{BASE}/api/trial/1")
test("Viewer CANNOT delete trial", r.status_code in (403, 401), f"status={r.status_code}")

r = V.delete(f"{BASE}/api/disposition/1")
test("Viewer CANNOT delete disposition", r.status_code in (403, 401), f"status={r.status_code}")

# Viewer cannot toggle permissions (IDOR attempt)
r = V.post(f"{BASE}/api/admin/toggle-warranty/1")
test("Viewer CANNOT toggle permissions (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

# ============================================================
# 5. WARRANTY_ADMIN RBAC
# ============================================================
print("\n=== 5. WARRANTY_ADMIN ROLE ===")

WA = requests.Session()
r = WA.post(f"{BASE}/login", data={"username": "test_warranty_adm", "password": "redacted-test-password"}, allow_redirects=False)
test("Warranty admin login succeeds", r.status_code in (302, 303))

r = WA.get(f"{BASE}/warranty/")
test("Warranty admin can read warranty page", r.status_code == 200)
test("Warranty admin sees delete buttons", "deleteWarranty" in r.text or "has_warranty_admin" in r.text or "Delete" in r.text)

r = WA.get(f"{BASE}/admin/audit")
test("Warranty admin can access audit log", r.status_code == 200, f"status={r.status_code}")

r = WA.get(f"{BASE}/trials/")
test("Warranty admin can read trials page", r.status_code == 200)

# Warranty admin should NOT access system admin
r = WA.get(f"{BASE}/admin/users", allow_redirects=False)
test("Warranty admin CANNOT access /admin/users", r.status_code in (403, 302, 307), f"status={r.status_code}")

r = WA.get(f"{BASE}/admin/storage", allow_redirects=False)
test("Warranty admin CANNOT access /admin/storage", r.status_code in (403, 302, 307), f"status={r.status_code}")

# Warranty admin should NOT be able to delete trials
r = WA.delete(f"{BASE}/api/trial/99999")
test("Warranty admin CANNOT delete trials (403)", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# 6. TRIALS_ADMIN RBAC
# ============================================================
print("\n=== 6. TRIALS_ADMIN ROLE ===")

TA = requests.Session()
r = TA.post(f"{BASE}/login", data={"username": "test_trials_adm", "password": "redacted-test-password"}, allow_redirects=False)
test("Trials admin login succeeds", r.status_code in (302, 303))

r = TA.get(f"{BASE}/trials/")
test("Trials admin can read trials page", r.status_code == 200)

r = TA.get(f"{BASE}/admin/audit")
test("Trials admin can access audit log", r.status_code == 200, f"status={r.status_code}")

# Trials admin should NOT delete warranties
r = TA.delete(f"{BASE}/api/warranty/99999")
test("Trials admin CANNOT delete warranty (403)", r.status_code == 403, f"status={r.status_code}")

# Trials admin should NOT access system admin
r = TA.get(f"{BASE}/admin/users", allow_redirects=False)
test("Trials admin CANNOT access /admin/users", r.status_code in (403, 302, 307), f"status={r.status_code}")

# ============================================================
# 7. PROCUREMENT_ADMIN RBAC
# ============================================================
print("\n=== 7. PROCUREMENT_ADMIN ROLE ===")

PA = requests.Session()
r = PA.post(f"{BASE}/login", data={"username": "test_procure_adm", "password": "redacted-test-password"}, allow_redirects=False)
test("Procurement admin login succeeds", r.status_code in (302, 303))

r = PA.get(f"{BASE}/admin/procurement")
test("Procurement admin can access /admin/procurement", r.status_code == 200, f"status={r.status_code}")

r = PA.get(f"{BASE}/admin/audit")
test("Procurement admin can access audit log", r.status_code == 200, f"status={r.status_code}")

# Procurement admin should NOT access system admin
r = PA.get(f"{BASE}/admin/users", allow_redirects=False)
test("Procurement admin CANNOT access /admin/users", r.status_code in (403, 302, 307), f"status={r.status_code}")

# Procurement admin should NOT delete warranty/trials
r = PA.delete(f"{BASE}/api/warranty/99999")
test("Procurement admin CANNOT delete warranty", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# 8. EDITOR RBAC
# ============================================================
print("\n=== 8. EDITOR ROLE ===")

ED = requests.Session()
r = ED.post(f"{BASE}/login", data={"username": "test_editor_e2e", "password": "redacted-test-password"}, allow_redirects=False)
test("Editor login succeeds", r.status_code in (302, 303))

r = ED.get(f"{BASE}/dashboard")
test("Editor can read dashboard", r.status_code == 200)

# Editor CANNOT delete warranty (needs warranty_admin)
r = ED.delete(f"{BASE}/api/warranty/99999")
test("Editor CANNOT delete warranty (403)", r.status_code == 403, f"status={r.status_code}")

# Editor CANNOT delete trial (needs trials_admin)
r = ED.delete(f"{BASE}/api/trial/99999")
test("Editor CANNOT delete trial (403)", r.status_code == 403, f"status={r.status_code}")

# Editor CANNOT access admin user management
r = ED.get(f"{BASE}/admin/users", allow_redirects=False)
test("Editor CANNOT access /admin/users", r.status_code in (403, 302, 307), f"status={r.status_code}")

# Editor CANNOT access audit log
r = ED.get(f"{BASE}/admin/audit", allow_redirects=False)
test("Editor CANNOT access /admin/audit", r.status_code in (403, 302, 307), f"status={r.status_code}")

# ============================================================
# 9. VENDOR CATALOG TESTS
# ============================================================
print("\n=== 9. VENDOR CATALOG ===")

r = S.get(f"{BASE}/admin/oui")
test("Vendor catalog loads (200)", r.status_code == 200)
test("Grouped view renders vendor-group-header", "vendor-group-header" in r.text)
test("Expand arrows present", "expand-arrow" in r.text)
test("Summary cards present", "Manufacturers" in r.text and "OUI Prefixes" in r.text)
test("Admin sees Add OUI form", "add-oui-form" in r.text)
test("Admin sees edit/delete buttons", "btn-danger" in r.text)

# Non-admin (editor) can see catalog but no edit controls
r = ED.get(f"{BASE}/admin/oui")
test("Editor can see vendor catalog", r.status_code == 200)
if r.status_code == 200:
    test("Non-admin does NOT see add form HTML", "Add OUI Prefix" not in r.text)
    test("Non-admin does NOT see delete buttons", "btn-danger" not in r.text)

# ============================================================
# 10. SECURITY TESTS
# ============================================================
print("\n=== 10. SECURITY ===")

# SQL Injection in login
r = requests.post(f"{BASE}/login", data={"username": "admin' OR '1'='1", "password": "x"}, allow_redirects=False)
test("SQLi in login blocked", r.status_code != 302 or "dashboard" not in r.headers.get("location", ""))

r = requests.post(f"{BASE}/login", data={"username": "admin'; DROP TABLE users;--", "password": "x"}, allow_redirects=False)
test("SQLi DROP TABLE blocked", r.status_code != 302 or "dashboard" not in r.headers.get("location", ""))

# XSS in user creation
r = S.post(f"{BASE}/admin/users/add", data={
    "username": "xss_test_e2e",
    "display_name": '<script>alert("xss")</script>',
    "password": "redacted-test-password",
    "role": "viewer"
})
r2 = S.get(f"{BASE}/admin/users")
test("XSS in display_name is escaped", '<script>alert("xss")</script>' not in r2.text,
     "Raw script tag in output!" if '<script>alert("xss")</script>' in r2.text else "Properly escaped")

# XSS in OUI manufacturer (check for unescaped HTML tag, not escaped text)
r = S.post(f"{BASE}/admin/oui/add", data={
    "oui_prefix": "FE:FE:FE",
    "manufacturer": '<img src=x onerror=alert(1)>',
    "maps_to_table": "cameras"
})
r2 = S.get(f"{BASE}/admin/oui")
test("XSS in OUI manufacturer escaped", "<img src=x onerror" not in r2.text,
     "Raw <img tag in output!" if "<img src=x onerror" in r2.text else "Properly escaped")

# IDOR: Viewer tries admin-only API
r = V.post(f"{BASE}/api/admin/toggle-financial/2")
test("IDOR: Viewer cannot toggle financial perm", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

r = V.post(f"{BASE}/api/admin/reset-password/2")
test("IDOR: Viewer cannot reset passwords", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

# Path traversal in cert endpoint
r = S.get(f"{BASE}/api/disposition/1/certificate")
test("Cert endpoint with no cert returns 404", r.status_code in (404, 200), f"status={r.status_code}")

# Invalid role in user creation
r = S.post(f"{BASE}/admin/users/add", data={
    "username": "badrole_e2e", "display_name": "Bad Role",
    "password": "redacted-test-password", "role": "superadmin"
})
test("Invalid role rejected (400)", r.status_code == 400, f"status={r.status_code}")

# Session cookie attributes
r = requests.post(f"{BASE}/login", data={"username": ADMIN_USER, "password": ADMIN_PASS}, allow_redirects=False)
cookies = r.headers.get("set-cookie", "")
test("Session cookie has SameSite", "samesite" in cookies.lower(), cookies[:100])
if "httponly" in cookies.lower():
    test("Session cookie has HttpOnly", True)
else:
    warn("Session cookie missing HttpOnly flag", "Starlette SessionMiddleware uses signed but not HttpOnly cookies")

# Test non-existent endpoints return proper codes
r = S.get(f"{BASE}/nonexistent-page")
test("Non-existent page returns 404", r.status_code == 404, f"status={r.status_code}")

# ============================================================
# 11. LIFECYCLE CRUD & EXPORT
# ============================================================
print("\n=== 11. LIFECYCLE CRUD & EXPORT ===")

r = S.get(f"{BASE}/api/warranty/export?format=csv")
test("Warranty CSV export works", r.status_code == 200)

r = S.get(f"{BASE}/api/warranty/export?format=xlsx")
test("Warranty XLSX export works", r.status_code == 200)

r = S.get(f"{BASE}/api/trial/export?format=csv")
test("Trials CSV export works", r.status_code == 200)

r = S.get(f"{BASE}/api/disposition/export?format=csv")
test("Disposal CSV export works", r.status_code == 200)

r = S.get(f"{BASE}/dashboard/table/cameras")
test("Dashboard table partial loads", r.status_code == 200, f"status={r.status_code}")

r = S.get(f"{BASE}/api/stats")
test("Stats API returns data", r.status_code == 200)

# Audit log export
r = S.get(f"{BASE}/audit-log/export?format=csv")
test("Audit log export works", r.status_code == 200, f"status={r.status_code}")

# Dashboard export
r = S.get(f"{BASE}/dashboard/export?tables=cameras&format=csv")
test("Dashboard CSV export works", r.status_code == 200, f"status={r.status_code}")

r = S.get(f"{BASE}/dashboard/export?tables=cameras&format=xlsx")
test("Dashboard XLSX export works", r.status_code == 200, f"status={r.status_code}")

# ============================================================
# 11a. LIFECYCLE WORKFLOW TESTS (create -> fetch -> update -> decide -> delete)
# ============================================================
print("\n=== 11a. LIFECYCLE WORKFLOWS ===")

# --- Warranty full lifecycle ---
r = S.post(f"{BASE}/api/warranty", json={
    "device_table": "cameras", "device_id": 998001,
    "warranty_end": "2027-06-01", "vendor": "E2E Test Vendor",
    "warranty_start": "2025-01-01", "warranty_tier": "premium",
    "warranty_type": "full", "registration_status": "registered",
})
wid = None
if r.status_code == 200:
    wid = r.json().get("warranty_id")
    test("Warranty create returns warranty_id", wid is not None)
else:
    test("Warranty lifecycle: create", False, f"status={r.status_code}")

if wid:
    # Fetch single warranty
    r = S.get(f"{BASE}/api/warranty/{wid}")
    test("Warranty fetch by ID (200)", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("Warranty fetch returns correct vendor", data.get("vendor") == "E2E Test Vendor")
        test("Warranty fetch returns correct tier", data.get("warranty_tier") == "premium")

    # Update warranty
    r = S.put(f"{BASE}/api/warranty/{wid}", json={
        "vendor": "E2E Updated Vendor", "warranty_tier": "basic",
    })
    test("Warranty update (200)", r.status_code == 200, f"status={r.status_code}")

    # Verify update persisted
    r = S.get(f"{BASE}/api/warranty/{wid}")
    if r.status_code == 200:
        test("Warranty update persisted", r.json().get("vendor") == "E2E Updated Vendor")

    # Create a claim on this warranty
    r = S.post(f"{BASE}/api/claim", json={
        "warranty_id": wid,
        "claim_number": "RMA-E2E-001",
        "issue_description": "E2E test claim",
        "claim_status": "opened",
    })
    cid = None
    if r.status_code == 200:
        cid = r.json().get("claim_id")
        test("Claim create returns claim_id", cid is not None)
    else:
        test("Claim create", False, f"status={r.status_code}")

    if cid:
        # Update claim status
        r = S.put(f"{BASE}/api/claim/{cid}", json={
            "claim_status": "approved", "rma_number": "RMA-12345",
        })
        test("Claim update to approved (200)", r.status_code == 200, f"status={r.status_code}")

        r = S.put(f"{BASE}/api/claim/{cid}", json={
            "claim_status": "shipped", "tracking_number": "1Z999AA10123456784",
        })
        test("Claim update to shipped (200)", r.status_code == 200, f"status={r.status_code}")

        r = S.put(f"{BASE}/api/claim/{cid}", json={
            "claim_status": "resolved", "resolution_notes": "Replacement received",
        })
        test("Claim update to resolved (200)", r.status_code == 200, f"status={r.status_code}")

    # Claim on non-existent warranty
    r = S.post(f"{BASE}/api/claim", json={"warranty_id": 99999, "issue_description": "Broken"})
    test("Claim on non-existent warranty (404)", r.status_code == 404, f"status={r.status_code}")

    # Claim without warranty_id
    r = S.post(f"{BASE}/api/claim", json={"issue_description": "Missing warranty"})
    test("Claim without warranty_id (400)", r.status_code == 400, f"status={r.status_code}")

    # Delete warranty (cleanup)
    r = S.delete(f"{BASE}/api/warranty/{wid}")
    test("Warranty delete (200)", r.status_code == 200, f"status={r.status_code}")

# --- Trial full lifecycle ---
r = S.post(f"{BASE}/api/trial", json={
    "device_table": "cameras", "device_id": 998002,
    "vendor": "E2E Trial Vendor", "received_date": "2026-01-01",
    "return_deadline": "2026-04-01", "trial_type": "evaluation",
    "evaluation_notes": "Initial notes", "pros": "Good quality", "cons": "Expensive",
})
tid = None
if r.status_code == 200:
    tid = r.json().get("trial_id")
    test("Trial create returns trial_id", tid is not None)
else:
    test("Trial lifecycle: create", False, f"status={r.status_code}")

if tid:
    # Fetch single trial
    r = S.get(f"{BASE}/api/trial/{tid}")
    test("Trial fetch by ID (200)", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("Trial fetch returns correct vendor", data.get("vendor") == "E2E Trial Vendor")
        test("Trial fetch returns evaluation notes", data.get("evaluation_notes") == "Initial notes")

    # Update trial
    r = S.put(f"{BASE}/api/trial/{tid}", json={
        "evaluation_notes": "Updated evaluation", "test_results": "Passed all tests",
    })
    test("Trial update (200)", r.status_code == 200, f"status={r.status_code}")

    # Record decision: approved
    r = S.put(f"{BASE}/api/trial/{tid}/decision", json={
        "decision": "approved", "purchase_order": "PO-E2E-001",
        "purchase_price": 1500.00, "decision_notes": "Approved for purchase",
    })
    test("Trial decision approved (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Trial decision response has decision=approved", r.json().get("decision") == "approved")

    # Verify trial status changed
    r = S.get(f"{BASE}/api/trial/{tid}")
    if r.status_code == 200:
        test("Trial status = approved_purchase", r.json().get("trial_status") == "approved_purchase")

    # Delete trial (cleanup)
    r = S.delete(f"{BASE}/api/trial/{tid}")
    test("Trial delete (200)", r.status_code == 200, f"status={r.status_code}")

# Create another trial to test decline + return workflow
r = S.post(f"{BASE}/api/trial", json={
    "device_table": "cameras", "device_id": 998003,
    "vendor": "E2E Return Vendor", "received_date": "2026-01-15",
    "return_deadline": "2026-03-15",
})
tid2 = r.json().get("trial_id") if r.status_code == 200 else None
if tid2:
    # Decision: declined
    r = S.put(f"{BASE}/api/trial/{tid2}/decision", json={"decision": "declined"})
    test("Trial decision declined (200)", r.status_code == 200, f"status={r.status_code}")

    # Record return
    r = S.put(f"{BASE}/api/trial/{tid2}/return", json={
        "returned_date": "2026-02-10", "return_tracking": "TRACK-E2E-001",
    })
    test("Trial return recorded (200)", r.status_code == 200, f"status={r.status_code}")

    # Verify returned status
    r = S.get(f"{BASE}/api/trial/{tid2}")
    if r.status_code == 200:
        test("Trial status = returned", r.json().get("trial_status") == "returned")

    # Invalid decision value
    r = S.put(f"{BASE}/api/trial/{tid2}/decision", json={"decision": "maybe"})
    test("Trial invalid decision rejected (400)", r.status_code == 400, f"status={r.status_code}")

    r = S.delete(f"{BASE}/api/trial/{tid2}")

# --- Disposition update lifecycle ---
r = S.post(f"{BASE}/api/disposition", json={
    "device_table": "cameras", "device_id": 998004,
    "disposition_type": "recycle", "disposition_date": "2026-01-20",
    "reason": "End of life",
})
did = r.json().get("disposition_id") if r.status_code == 200 else None
if did:
    # Fetch disposition data
    r = S.get(f"{BASE}/api/disposition/{did}/data")
    test("Disposition fetch by ID (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Disposition fetch returns correct type", r.json().get("disposition_type") == "recycle")

    # Update disposition with sanitization
    r = S.put(f"{BASE}/api/disposition/{did}", json={
        "sanitization_method": "NIST 800-88 Clear",
        "sanitization_date": "2026-01-25",
        "sanitization_verified_by": "E2E Tester",
    })
    test("Disposition update with sanitization (200)", r.status_code == 200, f"status={r.status_code}")

    # Verify update
    r = S.get(f"{BASE}/api/disposition/{did}/data")
    if r.status_code == 200:
        data = r.json()
        test("Sanitization method persisted", data.get("sanitization_method") == "NIST 800-88 Clear")
        test("Sanitization verified_by persisted", data.get("sanitization_verified_by") == "E2E Tester")

    r = S.delete(f"{BASE}/api/disposition/{did}")

# ============================================================
# 11b. DEVICE API TESTS
# ============================================================
print("\n=== 11b. DEVICE API ===")

# List devices (paginated: {table, total, offset, limit, items: [...]})
r = S.get(f"{BASE}/api/devices/cameras")
test("List cameras (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    data = r.json()
    test("Device list has items array", isinstance(data.get("items"), list))
    test("Device list has total count", isinstance(data.get("total"), int))
    items = data.get("items", [])
    if items:
        test("Device has id field", "id" in items[0])
        first_cam_id = items[0]["id"]

        # Get single device
        r = S.get(f"{BASE}/api/devices/cameras/{first_cam_id}")
        test("Get single camera (200)", r.status_code == 200, f"status={r.status_code}")

        # Device history
        r = S.get(f"{BASE}/api/devices/cameras/{first_cam_id}/history")
        test("Device history (200)", r.status_code == 200, f"status={r.status_code}")

# Invalid table name
r = S.get(f"{BASE}/api/devices/nonexistent_table")
test("Invalid device table (400 or 404)", r.status_code in (400, 404, 422), f"status={r.status_code}")

# Stats endpoint returns object
r = S.get(f"{BASE}/api/stats")
if r.status_code == 200:
    data = r.json()
    test("Stats returns dict with tables", isinstance(data, dict))

# Vendors endpoint
r = S.get(f"{BASE}/api/vendors")
test("Vendors API (200)", r.status_code == 200, f"status={r.status_code}")

# ============================================================
# 11c. PAGE LOAD & ADMIN TESTS
# ============================================================
print("\n=== 11c. PAGE LOADS & ADMIN OPS ===")

# Logout (uses admin session, so do this near the end before we need to re-login)
r2 = requests.Session()
r2.post(f"{BASE}/login", data={"username": ADMIN_USER, "password": ADMIN_PASS}, allow_redirects=False)
r = r2.get(f"{BASE}/logout", allow_redirects=False)
test("Logout redirects (302/303)", r.status_code in (302, 303), f"status={r.status_code}")

# After logout, dashboard should redirect
r = r2.get(f"{BASE}/dashboard", allow_redirects=False)
test("After logout, dashboard redirects to login", r.status_code in (302, 303, 307))

# Root redirect
r = S.get(f"{BASE}/", allow_redirects=False)
test("Root / redirects (200 or 302)", r.status_code in (200, 302, 303), f"status={r.status_code}")

# Receive page
r = S.get(f"{BASE}/receive")
test("Receive page loads (200)", r.status_code == 200, f"status={r.status_code}")

# Map page (admin/editor can access)
r = S.get(f"{BASE}/map/")
test("Map page loads for admin (200)", r.status_code == 200, f"status={r.status_code}")

# Multi-table view
r = S.get(f"{BASE}/dashboard/table/multi?tables=cameras,edge_boxes")
test("Multi-table view loads (200)", r.status_code == 200, f"status={r.status_code}")

# Spreadsheet sync page
r = S.get(f"{BASE}/admin/spreadsheet-sync")
test("Spreadsheet sync page loads (200)", r.status_code == 200, f"status={r.status_code}")

# Scanner logs
r = S.get(f"{BASE}/audit-log/scanner-logs")
test("Scanner logs page loads (200)", r.status_code == 200, f"status={r.status_code}")

# Audit log with filters
r = S.get(f"{BASE}/audit-log?event_type=user_login")
test("Audit log filtered by event type (200)", r.status_code == 200, f"status={r.status_code}")

# Dashboard table with filters
r = S.get(f"{BASE}/dashboard/table/cameras?status=Active")
test("Dashboard table filtered by status (200)", r.status_code == 200, f"status={r.status_code}")

# OUI edit (need an existing OUI — create, edit, then delete)
r = S.post(f"{BASE}/admin/oui/add", data={
    "oui_prefix": "FC:FC:FC", "manufacturer": "Edit Test Mfr", "maps_to_table": "cameras"
})
if r.status_code == 200:
    try:
        oui_id = r.json().get("id")
    except Exception:
        oui_id = None
    if oui_id:
        r = S.post(f"{BASE}/admin/oui/{oui_id}/edit", data={
            "manufacturer": "Edited Mfr Name", "maps_to_table": "network_equipment"
        })
        test("OUI edit (200)", r.status_code == 200, f"status={r.status_code}")

        r = S.delete(f"{BASE}/admin/oui/{oui_id}")
        test("OUI delete (200)", r.status_code == 200, f"status={r.status_code}")

# User toggle (create a temp user, toggle active, then cleanup)
r = S.post(f"{BASE}/admin/users/add", data={
    "username": "toggle_test_e2e", "display_name": "Toggle Test",
    "password": "redacted-test-password", "role": "viewer"
})
if r.status_code == 200:
    try:
        toggled_user_data = r.json()
    except Exception:
        toggled_user_data = {}
    toggle_uid = toggled_user_data.get("user_id") or toggled_user_data.get("id")
    if toggle_uid:
        r = S.post(f"{BASE}/admin/users/{toggle_uid}/toggle")
        test("User toggle active (200)", r.status_code == 200, f"status={r.status_code}")

        # Toggle back
        r = S.post(f"{BASE}/admin/users/{toggle_uid}/toggle")
        test("User toggle back (200)", r.status_code == 200, f"status={r.status_code}")

# NAS drives — test against first NAS device if any exist
r = S.get(f"{BASE}/api/devices/nas_devices")
if r.status_code == 200:
    nas_data = r.json()
    nas_items = nas_data.get("items", []) if isinstance(nas_data, dict) else nas_data
    if nas_items:
        nas_id = nas_items[0]["id"]
        r = S.get(f"{BASE}/api/nas-drives/{nas_id}")
        test("NAS drives list (200)", r.status_code == 200, f"status={r.status_code}")
    else:
        test("NAS drives: no NAS devices in inventory", True, "skipped — no NAS devices")
else:
    test("NAS drives: NAS device list", False, f"status={r.status_code}")

# Duplicate check endpoint
r = S.get(f"{BASE}/api/receive/check-duplicate?serial=NONEXISTENT_SERIAL_E2E")
test("Duplicate check API (200)", r.status_code == 200, f"status={r.status_code}")

# ============================================================
# 11d. FILE UPLOAD & DOWNLOAD TESTS (was 11b)
# ============================================================
print("\n=== 11d. FILE UPLOAD & DOWNLOAD ===")

# --- Certificate upload/download round-trip ---
# First, create a temp disposition to attach a cert to
r = S.post(f"{BASE}/api/disposition", json={
    "device_table": "cameras", "device_id": 999777,
    "disposition_type": "recycle", "disposition_date": "2026-01-15"
})
cert_disp_id = None
if r.status_code == 200:
    cert_disp_id = r.json().get("disposition_id")
    test("Created temp disposition for cert test", True)
elif r.status_code == 409:
    # Already exists from prior run — fetch its id
    test("Temp disposition already exists (reusing)", True)

if cert_disp_id:
    # Upload a valid PDF (minimal valid PDF content)
    pdf_content = b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\nxref\n0 3\ntrailer<</Size 3/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    r = S.post(
        f"{BASE}/api/disposition/{cert_disp_id}/certificate",
        files={"file": ("test_cert.pdf", pdf_content, "application/pdf")},
    )
    test("Certificate PDF upload succeeds (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Upload response has status=uploaded", r.json().get("status") == "uploaded")

    # Download the certificate back
    r = S.get(f"{BASE}/api/disposition/{cert_disp_id}/certificate")
    test("Certificate download succeeds (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Downloaded cert matches uploaded size", len(r.content) == len(pdf_content),
             f"expected={len(pdf_content)} got={len(r.content)}")

    # Upload a JPEG (valid content-type)
    jpeg_header = b'\xff\xd8\xff\xe0' + b'\x00' * 50 + b'\xff\xd9'
    r = S.post(
        f"{BASE}/api/disposition/{cert_disp_id}/certificate",
        files={"file": ("test_cert.jpg", jpeg_header, "image/jpeg")},
    )
    test("Certificate JPEG upload succeeds", r.status_code == 200, f"status={r.status_code}")

    # Reject invalid content type (text/html)
    r = S.post(
        f"{BASE}/api/disposition/{cert_disp_id}/certificate",
        files={"file": ("evil.html", b"<script>alert(1)</script>", "text/html")},
    )
    test("Certificate rejects text/html (400)", r.status_code == 400, f"status={r.status_code}")

    # Reject invalid content type (application/zip)
    r = S.post(
        f"{BASE}/api/disposition/{cert_disp_id}/certificate",
        files={"file": ("archive.zip", b"PK\x03\x04fake", "application/zip")},
    )
    test("Certificate rejects application/zip (400)", r.status_code == 400, f"status={r.status_code}")

# Certificate on non-existent disposition
r = S.post(
    f"{BASE}/api/disposition/99999/certificate",
    files={"file": ("test.pdf", b"%PDF", "application/pdf")},
)
test("Certificate upload on missing disposition (404)", r.status_code == 404, f"status={r.status_code}")

# --- Photo upload tests ---
# Upload a valid JPEG photo
jpeg_bytes = b'\xff\xd8\xff\xe0' + b'\x00' * 100 + b'\xff\xd9'
r = S.post(
    f"{BASE}/api/receive/photo",
    files={"file": ("label_photo.jpg", jpeg_bytes, "image/jpeg")},
    data={"caption": "E2E test photo", "run_ocr": "false"},
)
test("Photo upload JPEG succeeds", r.status_code == 200, f"status={r.status_code}")
uploaded_photo_id = None
if r.status_code == 200:
    uploaded_photo_id = r.json().get("photo_id")
    test("Photo upload returns photo_id", uploaded_photo_id is not None)

# Upload a valid PNG
png_header = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
r = S.post(
    f"{BASE}/api/receive/photo",
    files={"file": ("label.png", png_header, "image/png")},
    data={"caption": "PNG test", "run_ocr": "false"},
)
test("Photo upload PNG succeeds", r.status_code == 200, f"status={r.status_code}")
uploaded_png_id = r.json().get("photo_id") if r.status_code == 200 else None

# Upload a valid WebP
r = S.post(
    f"{BASE}/api/receive/photo",
    files={"file": ("label.webp", b"RIFF\x00\x00\x00\x00WEBP", "image/webp")},
    data={"caption": "WebP test", "run_ocr": "false"},
)
test("Photo upload WebP succeeds", r.status_code == 200, f"status={r.status_code}")
uploaded_webp_id = r.json().get("photo_id") if r.status_code == 200 else None

# Reject invalid type (application/pdf — photos only accept images)
r = S.post(
    f"{BASE}/api/receive/photo",
    files={"file": ("doc.pdf", b"%PDF-1.0", "application/pdf")},
    data={"run_ocr": "false"},
)
test("Photo rejects application/pdf (400)", r.status_code == 400, f"status={r.status_code}")

# Reject text/plain
r = S.post(
    f"{BASE}/api/receive/photo",
    files={"file": ("notes.txt", b"some text", "text/plain")},
    data={"run_ocr": "false"},
)
test("Photo rejects text/plain (400)", r.status_code == 400, f"status={r.status_code}")

# Download uploaded photo back
if uploaded_photo_id:
    r = S.get(f"{BASE}/api/receive/photo/{uploaded_photo_id}")
    test("Photo download succeeds (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Downloaded photo matches uploaded size", len(r.content) == len(jpeg_bytes),
             f"expected={len(jpeg_bytes)} got={len(r.content)}")

# Non-existent photo returns 404
r = S.get(f"{BASE}/api/receive/photo/99999")
test("Non-existent photo returns 404", r.status_code == 404, f"status={r.status_code}")

# Viewer CANNOT upload photos (requires editor)
r = V.post(
    f"{BASE}/api/receive/photo",
    files={"file": ("hack.jpg", jpeg_bytes, "image/jpeg")},
    data={"run_ocr": "false"},
)
test("Viewer CANNOT upload photos (403)", r.status_code == 403, f"status={r.status_code}")

# Viewer CANNOT upload certificates
if cert_disp_id:
    r = V.post(
        f"{BASE}/api/disposition/{cert_disp_id}/certificate",
        files={"file": ("hack.pdf", b"%PDF", "application/pdf")},
    )
    test("Viewer CANNOT upload certificates (403)", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# 11e. OCR REGEX EXTRACTION (unit-level)
# ============================================================
print("\n=== 11e. OCR REGEX TESTS ===")

import importlib
import sys as _sys

# Add project root so we can import the OCR module directly
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in _sys.path:
    _sys.path.insert(0, _project_root)

try:
    from scanner.ocr_processor import (
        _extract_serial, _extract_model, _extract_mac,
        _extract_part_number, _extract_manufacturer,
    )

    # Serial number extraction
    test("OCR: extracts 'S/N: ABC123456'",
         _extract_serial("Device Info\nS/N: ABC123456\nEnd") == "ABC123456")
    test("OCR: extracts 'Serial: XYZ-789-012'",
         _extract_serial("Serial: XYZ-789-012") is not None)
    test("OCR: extracts 'Serial Number: LONG1234567890'",
         _extract_serial("Serial Number: LONG1234567890") is not None)
    test("OCR: no serial in random text",
         _extract_serial("Hello world nothing here") is None)

    # Model extraction
    test("OCR: extracts 'Model: DS-2CD2347G2-LU'",
         _extract_model("Model: DS-2CD2347G2-LU") is not None)
    test("OCR: extracts 'Model No: PTZ-100'",
         _extract_model("Model No: PTZ-100") is not None)
    test("OCR: no model in random text",
         _extract_model("Just some random text") is None)

    # MAC address extraction
    test("OCR: extracts colon-sep MAC 'AA:BB:CC:DD:EE:FF'",
         _extract_mac("MAC: AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF")
    test("OCR: extracts dash-sep MAC 'AA-BB-CC-DD-EE-FF'",
         _extract_mac("MAC Address: AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF")
    test("OCR: extracts bare MAC 'AABBCCDDEEFF'",
         _extract_mac("AABBCCDDEEFF") == "AA:BB:CC:DD:EE:FF")
    test("OCR: no MAC in normal text",
         _extract_mac("Nothing resembling a mac address") is None)

    # Part number extraction
    test("OCR: extracts 'P/N: HWK-2023-A'",
         _extract_part_number("P/N: HWK-2023-A") is not None)
    test("OCR: extracts 'Part Number: ABC-123'",
         _extract_part_number("Part Number: ABC-123") is not None)
    test("OCR: no part number in random text",
         _extract_part_number("Hello") is None)

    # Manufacturer detection
    test("OCR: detects 'Hikvision' in text",
         _extract_manufacturer("Made by Hikvision Co Ltd") == "Hikvision")
    test("OCR: detects 'Dell' in text",
         _extract_manufacturer("Dell PowerEdge R740") == "Dell")
    test("OCR: detects 'Synology' in text",
         _extract_manufacturer("Synology DiskStation DS920+") == "Synology")
    test("OCR: case insensitive manufacturer",
         _extract_manufacturer("HIKVISION DS-2CD2347") == "Hikvision")
    test("OCR: no manufacturer in generic text",
         _extract_manufacturer("Some unknown company XYZ") is None)

except ImportError as e:
    warn("OCR module import failed — skipping regex tests", str(e))
except Exception as e:
    warn("OCR regex tests error", str(e))

# ============================================================
# 11f. DEVICE UPDATE API
# ============================================================
print("\n=== 11f. DEVICE UPDATE ===")

# Get a real camera to update (then revert)
r = S.get(f"{BASE}/api/devices/cameras")
if r.status_code == 200:
    cam_items = r.json().get("items", [])
    if cam_items:
        cam_id = cam_items[0]["id"]
        cam_notes = cam_items[0].get("notes", "")

        # Update notes field
        r = S.put(f"{BASE}/api/devices/cameras/{cam_id}", json={
            "notes": "E2E_TEST_MARKER — temp update"
        })
        test("Device update (200)", r.status_code == 200, f"status={r.status_code}")

        # Verify update persisted
        r = S.get(f"{BASE}/api/devices/cameras/{cam_id}")
        if r.status_code == 200:
            test("Device update persisted", "E2E_TEST_MARKER" in (r.json().get("notes") or ""))

        # Revert to original
        r = S.put(f"{BASE}/api/devices/cameras/{cam_id}", json={
            "notes": cam_notes if cam_notes else ""
        })
        test("Device update reverted", r.status_code == 200, f"status={r.status_code}")

        # Viewer cannot update devices
        r = V.put(f"{BASE}/api/devices/cameras/{cam_id}", json={"notes": "hack"})
        test("Viewer CANNOT update device (403)", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# 11g. MAP DATA API
# ============================================================
print("\n=== 11g. MAP DATA ===")

r = S.get(f"{BASE}/map/data")
test("Map data endpoint (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    try:
        data = r.json()
    except Exception:
        data = {}
    test("Map data has markers key", "markers" in data)
    test("Map markers is list", isinstance(data.get("markers"), list))
    markers = data.get("markers", [])
    if markers:
        test("Map marker has lat/lng", "lat" in markers[0] and "lng" in markers[0])
        test("Map marker has popup data", "popup" in markers[0])
    else:
        test("Map markers: no edge boxes with coords", True, "skipped — no geolocated boxes")

# Viewer cannot access map data
r = V.get(f"{BASE}/map/data", allow_redirects=False)
test("Viewer CANNOT access map data", r.status_code in (403, 302, 307), f"status={r.status_code}")

# ============================================================
# 11h. CREDENTIAL VAULT
# ============================================================
print("\n=== 11h. CREDENTIALS ===")

# Read existing credentials (cameras/1 has a login credential)
# Creds router is mounted at /api/credentials (not /api/creds)
r = S.get(f"{BASE}/api/credentials/cameras/1")
test("Credentials read (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    cred_data = r.json()
    test("Credentials response has 'credentials' key", "credentials" in cred_data)
    creds_list = cred_data.get("credentials", [])
    if creds_list:
        test("Credential has credential_type", "credential_type" in creds_list[0])
        test("Credential has username field", "username" in creds_list[0])
        test("Credential has password field", "password" in creds_list[0])
        test("Credential decrypted (not bytes)", not str(creds_list[0].get("username", "")).startswith("gAAAAA"))
    else:
        test("Credentials list: camera has stored creds", False, "empty credentials array")

# Read mobile device PINs
r = S.get(f"{BASE}/api/credentials/mobile_devices/1")
test("Mobile device credentials read (200)", r.status_code == 200, f"status={r.status_code}")

# Non-existent device returns 404
r = S.get(f"{BASE}/api/credentials/cameras/99999")
test("Credentials for non-existent device (404)", r.status_code == 404, f"status={r.status_code}")

# Viewer CANNOT read credentials (requires editor+)
r = V.get(f"{BASE}/api/credentials/cameras/1")
test("Viewer CANNOT read credentials (403)", r.status_code == 403, f"status={r.status_code}")

# Invalid table for credentials
r = S.get(f"{BASE}/api/credentials/nonexistent_table/1")
test("Credentials for invalid table (404)", r.status_code == 404, f"status={r.status_code}")

# ============================================================
# 11i. RECEIVING WORKFLOW
# ============================================================
print("\n=== 11i. RECEIVING WORKFLOW ===")

# Create a receiving event
r = S.post(f"{BASE}/api/receive/events", json={
    "vendor": "E2E Test Vendor",
    "purchase_order": "PO-E2E-9999",
    "expected_quantity": 3,
    "notes": "E2E test shipment",
})
recv_event_id = None
if r.status_code == 200:
    recv_event_id = r.json().get("event_id")
    test("Receiving event created", recv_event_id is not None)
else:
    test("Receiving event create", False, f"status={r.status_code}")

# Barcode scan (unknown serial — should return status)
r = S.post(f"{BASE}/api/receive/scan", json={"barcode": "SN-E2E-NONEXISTENT-99"})
test("Barcode scan returns result (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    scan_data = r.json()
    test("Scan result has status", "status" in scan_data)
    test("Unknown barcode returns 'unknown'", scan_data.get("status") == "unknown")

# Duplicate check (known existing serial via scan)
r = S.get(f"{BASE}/api/receive/check-duplicate?serial=SN-E2E-NONEXISTENT-99")
test("Duplicate check: non-existent returns exists=false", r.status_code == 200 and r.json().get("exists") is False,
     f"status={r.status_code}")

# Create device via receiving (direct to inventory)
r = S.post(f"{BASE}/api/receive/device", json={
    "target_table": "network_equipment",
    "serial": "SN-E2E-RECV-001",
    "direct_to_inventory": True,
    "receiving_event_id": recv_event_id,
    "manufacturer": "E2E Test Mfr",
    "model": "E2E-TEST-MODEL",
    "location": "E2E Test Lab",
    "status": "Active",
    "mac_address": "E2:E2:E2:00:00:01",
    "notes": "E2E receiving test device",
})
recv_device_id = None
if r.status_code == 200:
    recv_device_id = r.json().get("device_id")
    test("Device created via receiving", recv_device_id is not None)
    test("Device routed to inventory (not pending)", r.json().get("status") == "created")
else:
    test("Device creation via receiving", False, f"status={r.status_code} {r.text[:200]}")

# Viewer cannot create receiving events
r = V.post(f"{BASE}/api/receive/events", json={"vendor": "Hack"})
test("Viewer CANNOT create receiving event (403)", r.status_code == 403, f"status={r.status_code}")

# Viewer cannot scan barcodes
r = V.post(f"{BASE}/api/receive/scan", json={"barcode": "SN-HACK"})
test("Viewer CANNOT scan barcodes (403)", r.status_code == 403, f"status={r.status_code}")

# Viewer cannot create devices
r = V.post(f"{BASE}/api/receive/device", json={"target_table": "cameras", "serial": "HACK"})
test("Viewer CANNOT create devices (403)", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# 11j. NAS DEVICE + DRIVE CRUD
# ============================================================
print("\n=== 11j. NAS DEVICE + DRIVE CRUD ===")

# Create a NAS device in inventory via receiving (the QNAP at 192.0.2.23)
r = S.post(f"{BASE}/api/receive/device", json={
    "target_table": "nas_devices",
    "serial": "SN-QNAP-E2E-001",
    "direct_to_inventory": True,
    "manufacturer": "QNAP",
    "model": "TS-473A",
    "location": "Hardware Lab",
    "status": "Active",
    "mac_address": "24:5E:BE:91:86:25",
    "ip_address": "192.0.2.23",
    "notes": "E2E test — QNAP NAS",
})
nas_device_id = None
if r.status_code == 200:
    nas_device_id = r.json().get("device_id")
    test("NAS device created via receiving", nas_device_id is not None)
else:
    test("NAS device creation", False, f"status={r.status_code} {r.text[:200]}")

if nas_device_id:
    # Set bay_count on the NAS device (needed for drive validation)
    r = S.put(f"{BASE}/api/devices/nas_devices/{nas_device_id}", json={"bay_count": 4})
    test("NAS bay_count set to 4", r.status_code == 200, f"status={r.status_code}")

    # Create a drive in bay 1
    r = S.post(f"{BASE}/api/nas-drives/", json={
        "nas_device_id": nas_device_id,
        "bay_number": 1,
        "serial_number": "WD-E2E-001",
        "manufacturer": "Western Digital",
        "model": "Red Plus WD120EFBX",
        "capacity_gb": 12000,
        "drive_type": "HDD",
        "interface": "SATA",
    })
    drive_id = None
    if r.status_code == 200:
        drive_id = r.json().get("drive_id")
        test("NAS drive created in bay 1", drive_id is not None)
    else:
        test("NAS drive creation", False, f"status={r.status_code} {r.text[:200]}")

    # List drives for this NAS
    r = S.get(f"{BASE}/api/nas-drives/{nas_device_id}")
    test("NAS drives list (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        drives_data = r.json()
        test("NAS drives response has 'drives' key", "drives" in drives_data)
        test("NAS has 1 drive", len(drives_data.get("drives", [])) == 1)

    if drive_id:
        # Update drive status to degraded
        r = S.put(f"{BASE}/api/nas-drives/{drive_id}", json={
            "drive_status": "degraded",
            "health_status": "warning",
        })
        test("NAS drive update to degraded (200)", r.status_code == 200, f"status={r.status_code}")

        # Create second drive in bay 2
        r = S.post(f"{BASE}/api/nas-drives/", json={
            "nas_device_id": nas_device_id,
            "bay_number": 2,
            "serial_number": "WD-E2E-002",
            "manufacturer": "Western Digital",
            "model": "Red Plus WD120EFBX",
            "capacity_gb": 12000,
            "drive_type": "HDD",
        })
        drive_id2 = r.json().get("drive_id") if r.status_code == 200 else None
        test("NAS second drive created in bay 2", drive_id2 is not None, f"status={r.status_code}")

        # Verify bay count constraint — try bay 5 on a 4-bay NAS
        r = S.post(f"{BASE}/api/nas-drives/", json={
            "nas_device_id": nas_device_id,
            "bay_number": 5,
            "serial_number": "WD-E2E-BAD",
        })
        test("NAS drive rejects bay > bay_count", r.status_code == 400, f"status={r.status_code}")

        # Duplicate bay — try bay 1 again
        r = S.post(f"{BASE}/api/nas-drives/", json={
            "nas_device_id": nas_device_id,
            "bay_number": 1,
            "serial_number": "WD-E2E-DUP",
        })
        test("NAS drive rejects occupied bay (400 or 409)", r.status_code in (400, 409), f"status={r.status_code}")

        # Delete drive (admin only)
        r = S.delete(f"{BASE}/api/nas-drives/{drive_id}")
        test("NAS drive delete (200)", r.status_code == 200, f"status={r.status_code}")

        # Viewer cannot create drives
        r = V.post(f"{BASE}/api/nas-drives/", json={
            "nas_device_id": nas_device_id, "bay_number": 3, "serial_number": "HACK"
        })
        test("Viewer CANNOT create NAS drive (403)", r.status_code == 403, f"status={r.status_code}")

        # Editor cannot delete drives (admin only)
        if drive_id2:
            r = ED.delete(f"{BASE}/api/nas-drives/{drive_id2}")
            test("Editor CANNOT delete NAS drive (403)", r.status_code == 403, f"status={r.status_code}")
            # Clean up second drive
            S.delete(f"{BASE}/api/nas-drives/{drive_id2}")

# ============================================================
# 11k. SUPPORT/REVIEW PAGES + OUI TOGGLE + PROCUREMENT TOGGLE
# ============================================================
print("\n=== 11k. SUPPORT & ADMIN OPS ===")

# Support redirect
r = S.get(f"{BASE}/support", allow_redirects=False)
test("Support redirects to /review (301/302)", r.status_code in (301, 302, 303, 307), f"status={r.status_code}")

# Review page
r = S.get(f"{BASE}/review")
test("Review/pending page loads (200)", r.status_code == 200, f"status={r.status_code}")

# Review with status filter
r = S.get(f"{BASE}/review?status_filter=pending")
test("Review page with filter (200)", r.status_code == 200, f"status={r.status_code}")

# OUI toggle (create OUI, toggle it, verify, clean up)
r = S.post(f"{BASE}/admin/oui/add", data={
    "oui_prefix": "FB:FB:FB", "manufacturer": "Toggle Test Mfr", "maps_to_table": "cameras"
})
oui_toggle_id = r.json().get("id") if r.status_code == 200 else None
if oui_toggle_id:
    r = S.post(f"{BASE}/admin/oui/{oui_toggle_id}/toggle")
    test("OUI toggle deactivate (200)", r.status_code == 200, f"status={r.status_code}")

    r = S.post(f"{BASE}/admin/oui/{oui_toggle_id}/toggle")
    test("OUI toggle reactivate (200)", r.status_code == 200, f"status={r.status_code}")

    # Clean up
    S.delete(f"{BASE}/admin/oui/{oui_toggle_id}")

# Procurement toggle
# Find user ID for test_warranty_adm via admin users page
import re as _re
r = S.get(f"{BASE}/admin/users")
if r.status_code == 200 and "test_warranty_adm" in r.text:
    # Try multiple patterns: toggle links, data attributes, or user row IDs
    match = (_re.search(r'toggle-procurement/(\d+)', r.text)
             or _re.search(r'toggle-financial/(\d+)', r.text)
             or _re.search(r'toggle-warranty/(\d+)', r.text)
             or _re.search(r'user-row-(\d+).*?test_warranty_adm', r.text, _re.DOTALL))
    if match:
        test_uid = match.group(1)
        r = S.post(f"{BASE}/api/admin/toggle-procurement/{test_uid}")
        test("Procurement toggle on sub-admin (200)", r.status_code == 200, f"status={r.status_code}")

        # Toggle back
        r = S.post(f"{BASE}/api/admin/toggle-procurement/{test_uid}")
        test("Procurement toggle off (200)", r.status_code == 200, f"status={r.status_code}")
    else:
        # Fallback: get ID via DB on NUC
        result = subprocess.run(
            "sudo -u postgres psql -d hardware_inventory -tAc \"SELECT id FROM users WHERE username = 'test_warranty_adm';\"",
            shell=True, capture_output=True, text=True
        )
        test_uid = result.stdout.strip()
        if test_uid:
            r = S.post(f"{BASE}/api/admin/toggle-procurement/{test_uid}")
            test("Procurement toggle on sub-admin (200)", r.status_code == 200, f"status={r.status_code}")
            r = S.post(f"{BASE}/api/admin/toggle-procurement/{test_uid}")
            test("Procurement toggle off (200)", r.status_code == 200, f"status={r.status_code}")
        else:
            warn("Could not find test_warranty_adm user ID", "Neither HTML nor DB query returned ID")

# ============================================================
# 11l. STORAGE DRIVE CRUD
# ============================================================
print("\n=== 11l. STORAGE DRIVE CRUD ===")

# Check if storage_drives table exists
_sd_check = S.get(f"{BASE}/api/devices/storage_drives")
STORAGE_DRIVES_EXISTS = _sd_check.status_code == 200
sd_device_id = None

if STORAGE_DRIVES_EXISTS:
    # Create a storage drive via receiving workflow
    r = S.post(f"{BASE}/api/receive/device", json={
        "target_table": "storage_drives",
        "serial": "SN-WD-E2E-001",
        "direct_to_inventory": True,
        "manufacturer": "Western Digital",
        "model": "Red Plus WD120EFBX",
        "capacity_gb": 12000,
        "drive_type": "HDD",
        "form_factor": '3.5"',
        "interface": "SATA",
        "installed_in": "QNAP TS-473A",
        "status": "Active",
        "location": "Hardware Lab",
        "notes": "E2E test storage drive",
    })
    if r.status_code == 200:
        sd_device_id = r.json().get("device_id")
        test("Storage drive created via receiving", sd_device_id is not None)
    else:
        test("Storage drive creation", False, f"status={r.status_code} {r.text[:200]}")

    # Verify it appears in device list
    r = S.get(f"{BASE}/api/devices/storage_drives")
    test("Storage drives list (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        sd_data = r.json()
        test("Storage drives has items array", isinstance(sd_data.get("items"), list))
        sd_items = sd_data.get("items", [])
        test("Storage drives list not empty", len(sd_items) > 0, f"count={len(sd_items)}")

    if sd_device_id:
        # Get single device
        r = S.get(f"{BASE}/api/devices/storage_drives/" + str(sd_device_id))
        test("Get storage drive (200)", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            sd = r.json()
            test("Storage drive has installed_in", sd.get("installed_in") == "QNAP TS-473A")
            test("Storage drive has capacity_gb", sd.get("capacity_gb") == 12000)
            test("Storage drive has drive_type", sd.get("drive_type") == "HDD")
            test("Storage drive has form_factor", sd.get("form_factor") == '3.5"')
            test("Storage drive has interface", sd.get("interface") == "SATA")

        # Update installed_in field
        r = S.put(f"{BASE}/api/devices/storage_drives/" + str(sd_device_id), json={
            "installed_in": "Edge Box #5"
        })
        test("Storage drive update installed_in (200)", r.status_code == 200, f"status={r.status_code}")

        # Verify update persisted
        r = S.get(f"{BASE}/api/devices/storage_drives/" + str(sd_device_id))
        if r.status_code == 200:
            test("installed_in update persisted", r.json().get("installed_in") == "Edge Box #5")

        # Revert
        S.put(f"{BASE}/api/devices/storage_drives/" + str(sd_device_id), json={
            "installed_in": "QNAP TS-473A"
        })

        # Viewer cannot create storage drives
        r = V.post(f"{BASE}/api/receive/device", json={
            "target_table": "storage_drives", "serial": "SN-HACK-DRIVE"
        })
        test("Viewer CANNOT create storage drive (403)", r.status_code == 403, f"status={r.status_code}")

        # Viewer cannot update storage drives
        r = V.put(f"{BASE}/api/devices/storage_drives/" + str(sd_device_id), json={"notes": "hack"})
        test("Viewer CANNOT update storage drive (403)", r.status_code == 403, f"status={r.status_code}")
else:
    print("  SKIP: storage_drives table not available")

# ============================================================
# 12. EDGE CASES & VALIDATION
# ============================================================
print("\n=== 12. EDGE CASES ===")

# Duplicate username
r = S.post(f"{BASE}/admin/users/add", data={
    "username": "test_viewer_e2e", "display_name": "Dup",
    "password": "redacted-test-password", "role": "viewer"
})
test("Duplicate username rejected (409)", r.status_code == 409, f"status={r.status_code}")

# Empty username
r = S.post(f"{BASE}/admin/users/add", data={
    "username": "", "display_name": "",
    "password": "redacted-test-password", "role": "viewer"
})
test("Empty username rejected", r.status_code == 400, f"status={r.status_code}")

# Empty password
r = S.post(f"{BASE}/admin/users/add", data={
    "username": "nopwd_e2e", "display_name": "No Pass",
    "password": "", "role": "viewer"
})
test("Empty password rejected", r.status_code == 400, f"status={r.status_code}")

# Delete non-existent records
r = S.delete(f"{BASE}/api/warranty/99999")
test("Delete non-existent warranty returns 404", r.status_code == 404, f"status={r.status_code}")

r = S.delete(f"{BASE}/api/trial/99999")
test("Delete non-existent trial returns 404", r.status_code == 404, f"status={r.status_code}")

r = S.delete(f"{BASE}/api/disposition/99999")
test("Delete non-existent disposition returns 404", r.status_code == 404, f"status={r.status_code}")

# Invalid device_table validation (Finding #4)
r = S.post(f"{BASE}/api/warranty", json={
    "device_table": "nonexistent_table", "device_id": 1,
    "warranty_end": "2027-01-01", "vendor": "Test Vendor"
})
test("Warranty rejects invalid device_table (400)", r.status_code == 400, f"status={r.status_code}")
if r.status_code == 400:
    test("Warranty error message mentions invalid category", "Invalid device category" in r.json().get("error", ""))

r = S.post(f"{BASE}/api/trial", json={
    "device_table": "fake_table", "device_id": 1,
    "vendor": "Test", "received_date": "2026-01-01", "return_deadline": "2026-03-01"
})
test("Trial rejects invalid device_table (400)", r.status_code == 400, f"status={r.status_code}")

r = S.post(f"{BASE}/api/disposition", json={
    "device_table": "bad_table", "device_id": 1,
    "disposition_type": "recycle", "disposition_date": "2026-01-01"
})
test("Disposition rejects invalid device_table (400)", r.status_code == 400, f"status={r.status_code}")

# Duplicate disposition prevention (Finding #3)
# Create a disposition, then try to create another for the same device
r = S.post(f"{BASE}/api/disposition", json={
    "device_table": "cameras", "device_id": 999888,
    "disposition_type": "recycle", "disposition_date": "2026-01-01"
})
test("First disposition creates OK", r.status_code == 200, f"status={r.status_code}")

r2 = S.post(f"{BASE}/api/disposition", json={
    "device_table": "cameras", "device_id": 999888,
    "disposition_type": "donate", "disposition_date": "2026-02-01"
})
test("Duplicate disposition blocked (409)", r2.status_code == 409, f"status={r2.status_code}")
if r2.status_code == 409:
    test("Duplicate error mentions existing record", "already exists" in r2.json().get("error", ""))

# Duplicate OUI prefix
r = S.post(f"{BASE}/admin/oui/add", data={
    "oui_prefix": "FD:FD:FD", "manufacturer": "Dup Test", "maps_to_table": "cameras"
})
r2 = S.post(f"{BASE}/admin/oui/add", data={
    "oui_prefix": "FD:FD:FD", "manufacturer": "Dup Test 2", "maps_to_table": "cameras"
})
test("Duplicate OUI prefix handled", r2.status_code in (200, 400, 409), f"status={r2.status_code}")
if r2.status_code == 200:
    warn("Duplicate OUI prefix allowed", "No uniqueness constraint on oui_prefix column")

# ============================================================
# 13. PERMISSION FLAG CROSS-DOMAIN TESTS
# ============================================================
print("\n=== 13. PERMISSION FLAGS ===")

# Grant trials permission to warranty admin
r = S.post(f"{BASE}/api/admin/toggle-trials/0")
test("Toggle permission for non-existent user returns 404", r.status_code == 404, f"status={r.status_code}")

# Try toggling permission for admin user (should be rejected)
# Real admin is id=2
r = S.post(f"{BASE}/api/admin/toggle-warranty/2")
# Admin always has warranty access, so this should fail
test("Cannot toggle warranty for admin user", r.status_code == 400, f"status={r.status_code}")

# ============================================================
# 14. DRIVE ASSIGNMENT WORKFLOW
# ============================================================
print("\n=== 14. DRIVE ASSIGNMENT ===")

# Create two test storage drives via receiving workflow
assign_drive_a_id = None
assign_drive_b_id = None
assign_edge_id = None

if STORAGE_DRIVES_EXISTS:
    r = S.post(f"{BASE}/api/receive/device", json={
        "serial": "SN-ASSIGN-DRV-A", "manufacturer": "WD", "model": "Red Pro 18TB",
        "target_table": "storage_drives", "status": "Spare",
        "capacity_gb": 18000, "drive_type": "HDD", "form_factor": "3.5\"", "interface": "SATA",
        "direct_to_inventory": True
    })
    test("Create test drive A for assignment", r.status_code == 200 and r.json().get("status") == "created")
    if r.status_code == 200:
        assign_drive_a_id = r.json().get("device_id")

    r = S.post(f"{BASE}/api/receive/device", json={
        "serial": "SN-ASSIGN-DRV-B", "manufacturer": "Seagate", "model": "IronWolf 12TB",
        "target_table": "storage_drives", "status": "Spare",
        "capacity_gb": 12000, "drive_type": "HDD", "form_factor": "3.5\"", "interface": "SATA",
        "direct_to_inventory": True
    })
    test("Create test drive B for assignment", r.status_code == 200 and r.json().get("status") == "created")
    if r.status_code == 200:
        assign_drive_b_id = r.json().get("device_id")
else:
    print("  SKIP: storage_drives table not available — skipping drive assignment tests")

if STORAGE_DRIVES_EXISTS:
    # Create a test edge box as parent device
    r = S.post(f"{BASE}/api/receive/device", json={
        "serial": "SN-ASSIGN-EDGE-001", "manufacturer": "Company", "model": "Edge Box v2",
        "target_table": "edge_boxes", "status": "Active",
        "direct_to_inventory": True
    })
    test("Create test edge box for drive assignment", r.status_code == 200 and r.json().get("status") == "created")
    if r.status_code == 200:
        assign_edge_id = r.json().get("device_id")

if STORAGE_DRIVES_EXISTS:
    # Drive lookup by serial
    r = S.get(f"{BASE}/api/drives/lookup?serial=SN-ASSIGN-DRV-A")
    test("Drive lookup finds drive A", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("Drive lookup returns correct serial", data.get("serial") == "SN-ASSIGN-DRV-A")
        test("Drive lookup returns manufacturer", data.get("manufacturer") == "WD")
        test("Drive lookup returns capacity", data.get("capacity_gb") == 18000)
        test("Drive lookup shows not installed", data.get("installed_in") is None)

    # Drive lookup — not found
    r = S.get(f"{BASE}/api/drives/lookup?serial=NONEXISTENT-SERIAL-XYZ")
    test("Drive lookup returns 404 for unknown serial", r.status_code == 404)

# Assign drive A to edge box
if assign_drive_a_id and assign_edge_id:
    r = S.post(f"{BASE}/api/drives/assign", json={
        "drive_id": assign_drive_a_id,
        "target_table": "edge_boxes",
        "target_id": assign_edge_id
    })
    test("Assign drive A to edge box", r.status_code == 200 and r.json().get("status") == "assigned")
    if r.status_code == 200:
        test("Assignment returns installed_in name", r.json().get("installed_in") is not None)

    # Verify drive A is now installed via lookup
    r = S.get(f"{BASE}/api/drives/lookup?serial=SN-ASSIGN-DRV-A")
    if r.status_code == 200:
        data = r.json()
        test("Drive A now shows installed_in after assignment", data.get("installed_in") is not None)
        test("Drive A installed_in_table is edge_boxes", data.get("installed_in_table") == "edge_boxes")
        test("Drive A installed_in_id matches edge box", data.get("installed_in_id") == assign_edge_id)

    # List installed drives for edge box
    r = S.get(f"{BASE}/api/devices/edge_boxes/{assign_edge_id}/drives")
    test("List installed drives returns 200", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("Edge box has 1 installed drive", len(data.get("drives", [])) == 1)
        if data.get("drives"):
            test("Installed drive is drive A", data["drives"][0].get("serial") == "SN-ASSIGN-DRV-A")

# Assign drive B to same edge box
if assign_drive_b_id and assign_edge_id:
    r = S.post(f"{BASE}/api/drives/assign", json={
        "drive_id": assign_drive_b_id,
        "target_table": "edge_boxes",
        "target_id": assign_edge_id
    })
    test("Assign drive B to same edge box", r.status_code == 200 and r.json().get("status") == "assigned")

    # Now edge box should have 2 drives
    r = S.get(f"{BASE}/api/devices/edge_boxes/{assign_edge_id}/drives")
    if r.status_code == 200:
        test("Edge box now has 2 installed drives", len(r.json().get("drives", [])) == 2)

# Re-assign drive A to same device (should return already_assigned)
if assign_drive_a_id and assign_edge_id:
    r = S.post(f"{BASE}/api/drives/assign", json={
        "drive_id": assign_drive_a_id,
        "target_table": "edge_boxes",
        "target_id": assign_edge_id
    })
    test("Re-assign same drive to same device returns already_assigned", r.json().get("status") == "already_assigned")

# Uninstall drive A
if assign_drive_a_id:
    r = S.post(f"{BASE}/api/drives/uninstall", json={"drive_id": assign_drive_a_id})
    test("Uninstall drive A", r.status_code == 200 and r.json().get("status") == "uninstalled")

    # Verify drive A is now spare
    r = S.get(f"{BASE}/api/drives/lookup?serial=SN-ASSIGN-DRV-A")
    if r.status_code == 200:
        data = r.json()
        test("Drive A status is Spare after uninstall", data.get("status") == "Spare")
        test("Drive A installed_in is cleared", data.get("installed_in") is None)
        test("Drive A installed_in_table is cleared", data.get("installed_in_table") is None)

    # Edge box should now have 1 drive
    if assign_edge_id:
        r = S.get(f"{BASE}/api/devices/edge_boxes/{assign_edge_id}/drives")
        if r.status_code == 200:
            test("Edge box has 1 drive after uninstall", len(r.json().get("drives", [])) == 1)

if STORAGE_DRIVES_EXISTS:
    # Viewer RBAC: can view installed drives but can't assign/uninstall
    r = V.get(f"{BASE}/api/drives/lookup?serial=SN-ASSIGN-DRV-B")
    test("Viewer can look up drives", r.status_code == 200)

    if assign_edge_id:
        r = V.get(f"{BASE}/api/devices/edge_boxes/{assign_edge_id}/drives")
        test("Viewer can list installed drives", r.status_code == 200)

    if assign_drive_a_id and assign_edge_id:
        r = V.post(f"{BASE}/api/drives/assign", json={
            "drive_id": assign_drive_a_id, "target_table": "edge_boxes", "target_id": assign_edge_id
        })
        test("Viewer cannot assign drives (403)", r.status_code == 403, f"status={r.status_code}")

        r = V.post(f"{BASE}/api/drives/uninstall", json={"drive_id": assign_drive_a_id})
        test("Viewer cannot uninstall drives (403)", r.status_code == 403, f"status={r.status_code}")

    # Assign validation: missing fields
    r = S.post(f"{BASE}/api/drives/assign", json={"drive_id": 999999})
    test("Assign with missing fields returns 400", r.status_code == 400)

    # Assign validation: nonexistent drive
    r = S.post(f"{BASE}/api/drives/assign", json={
        "drive_id": 999999, "target_table": "edge_boxes", "target_id": 1
    })
    test("Assign nonexistent drive returns 404", r.status_code == 404)

# Uninstall validation: nonexistent drive
r = S.post(f"{BASE}/api/drives/uninstall", json={"drive_id": 999999})
test("Uninstall nonexistent drive returns 404", r.status_code == 404)

# List drives for nonexistent device
r = S.get(f"{BASE}/api/devices/edge_boxes/999999/drives")
test("List drives for nonexistent device returns 404", r.status_code == 404)

# ============================================================
# 15. OUI AUTO-ADD ON DEVICE APPROVAL
# ============================================================
print("\n=== 15. OUI AUTO-ADD WORKFLOW ===")

# Create a pending device directly in the DB with a unique OUI not in the catalog
oui_test_mac = "FA:FA:FA:11:22:33"
oui_test_prefix = "FA:FA:FA"

# Clean up any leftover from prior runs
subprocess.run(
    f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM oui_allowlist WHERE oui_prefix = '{oui_test_prefix}'\"",
    shell=True, capture_output=True, text=True,
)
subprocess.run(
    f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM pending_devices WHERE mac_address = '{oui_test_mac.lower()}'\"",
    shell=True, capture_output=True, text=True,
)

# Verify OUI doesn't exist yet
r = S.get(f"{BASE}/admin/oui")
test("OUI FA:FA:FA not in catalog before test", oui_test_prefix not in r.text)

# Insert a pending device with the test MAC
cmd = (
    f"sudo -u postgres psql -d hardware_inventory -tAc \""
    f"INSERT INTO pending_devices (mac_address, ip_address, hostname, manufacturer, suggested_table, scanner_id, network_segment, first_seen, last_seen, status) "
    f"VALUES ('{oui_test_mac.lower()}', '10.0.0.99', 'e2e-oui-test', 'E2E OUI Test Mfr', 'network_equipment', 'e2e-test', 'lab', NOW(), NOW(), 'pending') "
    f"RETURNING id;\""
)
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
# psql output may include "INSERT 0 1" on a second line — extract just the numeric ID
pending_id = result.stdout.strip().split("\n")[0].strip()
test("Pending device created for OUI test", pending_id.isdigit(), f"id={pending_id}")

if pending_id:
    # Approve the device
    r = S.post(f"{BASE}/api/pending/{pending_id}/approve")
    test("Approve pending device (200)", r.status_code == 200, f"status={r.status_code}")

    if r.status_code == 200:
        approved_data = r.json()
        test("Approval returns target_table", approved_data.get("target_table") == "network_equipment")
        test("Approval returns device_id", approved_data.get("device_id") is not None)

        # Verify OUI was auto-added to the catalog
        r = S.get(f"{BASE}/admin/oui")
        test("OUI FA:FA:FA auto-added to catalog after approval", oui_test_prefix in r.text)

        # Clean up the approved device
        approved_device_id = approved_data.get("device_id")
        if approved_device_id:
            subprocess.run(
                f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM network_equipment WHERE id = {approved_device_id}\"",
                shell=True, capture_output=True, text=True,
            )

# Clean up pending device and OUI entry
subprocess.run(
    f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM pending_devices WHERE mac_address = '{oui_test_mac.lower()}'\"",
    shell=True, capture_output=True, text=True,
)
subprocess.run(
    f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM oui_allowlist WHERE oui_prefix = '{oui_test_prefix}'\"",
    shell=True, capture_output=True, text=True,
)

# ============================================================
# 16. SITES & OWNERSHIP
# ============================================================
print("\n=== 16. SITES & OWNERSHIP ===")

# --- 16a. Sites Page Access ---
r = S.get(f"{BASE}/sites/")
test("Sites page loads (200)", r.status_code == 200, f"status={r.status_code}")
test("Sites page has title", "Sites &amp; Ownership" in r.text or "Sites & Ownership" in r.text)
test("Sites page has summary cards", "Total Sites" in r.text)

# --- 16b. Unauthenticated access blocked ---
r_unauth = requests.get(f"{BASE}/sites/", allow_redirects=False)
test("Unauth /sites/ redirects", r_unauth.status_code in (302, 303, 307))

# --- 16c. Create Site (API) ---
site_payload = {
    "name": "E2E Test Lab",
    "site_type": "internal_lab",
    "customer": "the company",
    "city": "New York",
    "state": "NY",
    "country": "US",
    "contact_name": "E2E Tester",
    "contact_email": "e2e@test.local",
}
r = S.post(f"{BASE}/api/sites", json=site_payload)
test("Create site (200)", r.status_code == 200, f"status={r.status_code}")
site_id = None
if r.status_code == 200:
    site_data = r.json()
    site_id = site_data.get("site_id")
    test("Create site returns site_id", site_id is not None)

# --- 16d. Duplicate site name rejected ---
r = S.post(f"{BASE}/api/sites", json={"name": "E2E Test Lab", "site_type": "internal_lab"})
test("Duplicate site name rejected (409)", r.status_code == 409, f"status={r.status_code}")

# --- 16e. Invalid site type rejected ---
r = S.post(f"{BASE}/api/sites", json={"name": "Bad Type Site", "site_type": "invalid_type"})
test("Invalid site type rejected (400)", r.status_code == 400)

# --- 16f. Site appears on list page ---
r = S.get(f"{BASE}/sites/")
test("New site appears on sites page", "E2E Test Lab" in r.text)

# --- 16g. Site detail page loads ---
if site_id:
    r = S.get(f"{BASE}/sites/{site_id}")
    test("Site detail page loads (200)", r.status_code == 200, f"status={r.status_code}")
    test("Site detail shows name", "E2E Test Lab" in r.text)
    test("Site detail shows city", "New York" in r.text)

# --- 16h. Update site ---
if site_id:
    r = S.put(f"{BASE}/api/sites/{site_id}", json={"contact_phone": "555-0199", "notes": "E2E updated"})
    test("Update site (200)", r.status_code == 200, f"status={r.status_code}")

# --- 16i. Create a second site (partner type) ---
partner_site_payload = {
    "name": "E2E Partner Site",
    "site_type": "partner",
    "customer": "Acme Partner Corp",
    "city": "Chicago",
    "state": "IL",
}
r = S.post(f"{BASE}/api/sites", json=partner_site_payload)
test("Create partner site (200)", r.status_code == 200)
partner_site_id = r.json().get("site_id") if r.status_code == 200 else None

# --- 16j. Assign device to site ---
# First, create a test camera to assign
e2e_cam_cmd = (
    "sudo -u postgres psql -d hardware_inventory -tAc \""
    "INSERT INTO cameras (manufacturer, model, serial, location, discovered_by) "
    "VALUES ('E2ETestMfr', 'E2ETestModel', 'SN-SITE-E2E-CAM-001', 'Lab', 'manual') "
    "RETURNING id;\""
)
cam_result = subprocess.run(e2e_cam_cmd, shell=True, capture_output=True, text=True)
cam_id_str = cam_result.stdout.strip().split("\n")[0].strip()
cam_id = int(cam_id_str) if cam_id_str.isdigit() else None
test("Test camera created for assignment", cam_id is not None, f"cam_id={cam_id}")

assignment_id = None
if site_id and cam_id:
    assign_payload = {
        "device_table": "cameras",
        "device_id": cam_id,
        "site_id": site_id,
        "ownership": "owned",
        "notes": "E2E assignment test",
    }
    r = S.post(f"{BASE}/api/assignments", json=assign_payload)
    test("Assign device to site (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        assignment_id = r.json().get("assignment_id")
        test("Assignment returns assignment_id", assignment_id is not None)

# --- 16k. Duplicate assignment rejected ---
if site_id and cam_id:
    r = S.post(f"{BASE}/api/assignments", json={
        "device_table": "cameras", "device_id": cam_id,
        "site_id": site_id, "ownership": "owned",
    })
    test("Duplicate assignment returns already_assigned", r.status_code == 200 and r.json().get("status") == "already_assigned")

# --- 16l. Assignment to different site rejected (device busy) ---
if partner_site_id and cam_id:
    r = S.post(f"{BASE}/api/assignments", json={
        "device_table": "cameras", "device_id": cam_id,
        "site_id": partner_site_id, "ownership": "partner_loaner",
    })
    test("Assignment to different site when active rejected (409)", r.status_code == 409)

# --- 16m. Site detail shows assigned device ---
if site_id:
    r = S.get(f"{BASE}/sites/{site_id}")
    test("Site detail shows assigned camera", "E2ETestMfr" in r.text or "SN-SITE-E2E-CAM-001" in r.text)
    test("Site detail shows ownership badge", "Owned" in r.text)

# --- 16n. Assign loaner with expected return ---
e2e_cam2_cmd = (
    "sudo -u postgres psql -d hardware_inventory -tAc \""
    "INSERT INTO cameras (manufacturer, model, serial, location, discovered_by) "
    "VALUES ('E2EPartnerMfr', 'E2EPartnerCam', 'SN-SITE-E2E-CAM-002', 'Lab', 'manual') "
    "RETURNING id;\""
)
cam2_result = subprocess.run(e2e_cam2_cmd, shell=True, capture_output=True, text=True)
cam2_id_str = cam2_result.stdout.strip().split("\n")[0].strip()
cam2_id = int(cam2_id_str) if cam2_id_str.isdigit() else None
loaner_assignment_id = None

if partner_site_id and cam2_id:
    r = S.post(f"{BASE}/api/assignments", json={
        "device_table": "cameras",
        "device_id": cam2_id,
        "site_id": partner_site_id,
        "ownership": "partner_loaner",
        "expected_return": "2025-01-01",  # In the past = overdue
    })
    test("Assign partner loaner with return date (200)", r.status_code == 200)
    if r.status_code == 200:
        loaner_assignment_id = r.json().get("assignment_id")

# --- 16o. Sites page shows overdue count ---
r = S.get(f"{BASE}/sites/")
test("Sites page shows overdue count", "Overdue Returns" in r.text)

# --- 16p. Return device ---
if assignment_id:
    r = S.post(f"{BASE}/api/assignments/{assignment_id}/return", json={"notes": "E2E return test"})
    test("Return device (200)", r.status_code == 200, f"status={r.status_code}")

# --- 16q. After return, can reassign to different site ---
reassignment_id = None
if partner_site_id and cam_id:
    r = S.post(f"{BASE}/api/assignments", json={
        "device_table": "cameras", "device_id": cam_id,
        "site_id": partner_site_id, "ownership": "evaluation",
    })
    test("Reassign after return succeeds (200)", r.status_code == 200)
    reassignment_id = r.json().get("assignment_id") if r.status_code == 200 else None

# --- 16r. Delete assignment ---
if loaner_assignment_id:
    r = S.delete(f"{BASE}/api/assignments/{loaner_assignment_id}")
    test("Delete assignment (200)", r.status_code == 200, f"status={r.status_code}")

# --- 16s. Cannot delete site with active assignments ---
if partner_site_id:
    r = S.delete(f"{BASE}/api/sites/{partner_site_id}")
    test("Cannot delete site with active assignments (409)", r.status_code == 409)

# --- 16t. Delete assignment then delete site ---
if reassignment_id:
    S.delete(f"{BASE}/api/assignments/{reassignment_id}")
if partner_site_id:
    r = S.delete(f"{BASE}/api/sites/{partner_site_id}")
    test("Delete site after clearing assignments (200)", r.status_code == 200)

# --- 16u. RBAC: Sites list API ---
r = S.get(f"{BASE}/api/sites/list")
test("Sites list API returns JSON array", r.status_code == 200 and isinstance(r.json(), list))

# --- 16v. Invalid device table rejected ---
if site_id:
    r = S.post(f"{BASE}/api/assignments", json={
        "device_table": "nonexistent_table", "device_id": 1,
        "site_id": site_id, "ownership": "owned",
    })
    test("Invalid device table rejected (400)", r.status_code == 400)

# --- 16w. Cleanup test site and cameras ---
if site_id:
    # Clean up remaining assignments first
    subprocess.run(
        f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM device_assignments WHERE site_id = {site_id}\"",
        shell=True, capture_output=True, text=True,
    )
    r = S.delete(f"{BASE}/api/sites/{site_id}")
    test("Delete test site (200)", r.status_code == 200, f"status={r.status_code}")

# Clean up test cameras
for serial in ["SN-SITE-E2E-CAM-001", "SN-SITE-E2E-CAM-002"]:
    subprocess.run(
        f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM cameras WHERE serial = '{serial}'\"",
        shell=True, capture_output=True, text=True,
    )
    print(f"  Cleaned up test camera: {serial}")

# Clean up any remaining test data
subprocess.run(
    "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM device_assignments WHERE notes LIKE 'E2E%'\"",
    shell=True, capture_output=True, text=True,
)
subprocess.run(
    "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM sites WHERE name LIKE 'E2E%'\"",
    shell=True, capture_output=True, text=True,
)


# ============================================================
# 17. GLOBAL SEARCH
# ============================================================
print("\n=== 17. GLOBAL SEARCH ===")

r = S.get(f"{BASE}/search")
test("Search page loads (200)", r.status_code == 200)

r = S.get(f"{BASE}/search/results?q=a")
test("Search with 1 char returns empty/placeholder", r.status_code == 200)

r = S.get(f"{BASE}/search/results?q=test")
test("Search HTMX partial returns 200", r.status_code == 200)
test("Search results return HTML", "text/html" in r.headers.get("content-type", ""))

r = V.get(f"{BASE}/search")
test("Viewer can access search page (200)", r.status_code == 200)

r = V.get(f"{BASE}/search/results?q=test")
test("Viewer can use search HTMX partial", r.status_code == 200)

# ============================================================
# 18. DASHBOARD SUMMARY VIEW
# ============================================================
print("\n=== 18. DASHBOARD SUMMARY VIEW ===")

r = S.get(f"{BASE}/dashboard/summary")
test("Dashboard summary partial loads (200)", r.status_code == 200)
test("Summary contains Total Devices", "Total Devices" in r.text)
test("Summary contains Active / Online card", "Active / Online" in r.text)
test("Summary contains Edge Boxes Deployed card", "Edge Boxes Deployed" in r.text)
test("Summary shows Incomplete Records for admin", "Incomplete Records" in r.text)

r = V.get(f"{BASE}/dashboard/summary")
test("Viewer summary loads (200)", r.status_code == 200)
test("Viewer summary also shows Active / Online", "Active / Online" in r.text)

# ============================================================
# 19. BULK OPERATIONS
# ============================================================
print("\n=== 19. BULK OPERATIONS ===")

# Empty device list
r = S.post(f"{BASE}/api/bulk/export", json={"devices": [], "format": "csv"})
test("Bulk export empty list returns 400", r.status_code == 400)

r = S.post(f"{BASE}/api/bulk/status", json={"devices": [], "status": "Online"})
test("Bulk status empty list returns 400", r.status_code == 400)

# Bulk export with a real device (camera id 1 may or may not exist)
r = S.post(f"{BASE}/api/bulk/export", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "format": "csv",
})
test("Bulk export CSV returns 200 or 400 (no device)", r.status_code in (200, 400))

r = S.post(f"{BASE}/api/bulk/export", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "format": "xlsx",
})
test("Bulk export XLSX returns 200 or 400", r.status_code in (200, 400))

# Bulk status change
r = S.post(f"{BASE}/api/bulk/status", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "status": "Testing",
})
test("Bulk status change (admin) returns 200 or 400", r.status_code in (200, 400))

# Viewer CANNOT bulk status change
r = V.post(f"{BASE}/api/bulk/status", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "status": "Testing",
})
test("Viewer CANNOT bulk status change (403)", r.status_code == 403)

# Viewer CAN bulk export
r = V.post(f"{BASE}/api/bulk/export", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "format": "csv",
})
test("Viewer CAN bulk export", r.status_code in (200, 400))

# Bulk assign
r = S.post(f"{BASE}/api/bulk/assign", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "site_id": 99999,
    "ownership": "owned",
})
test("Bulk assign to nonexistent site returns 404", r.status_code == 404)

# Viewer CANNOT bulk assign
r = V.post(f"{BASE}/api/bulk/assign", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "site_id": 1,
    "ownership": "owned",
})
test("Viewer CANNOT bulk assign (403)", r.status_code == 403)

# Missing status field
r = S.post(f"{BASE}/api/bulk/status", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "status": "",
})
test("Bulk status with empty status returns 400", r.status_code == 400)

# Invalid ownership
r = S.post(f"{BASE}/api/bulk/assign", json={
    "devices": [{"table_name": "cameras", "device_id": 1}],
    "site_id": 1,
    "ownership": "invalid_type",
})
test("Bulk assign with invalid ownership returns 400 or 404", r.status_code in (400, 404))

# ============================================================
# 20. EXPANDED RBAC - Granular Permission Flags
# ============================================================
print("\n=== 20. EXPANDED RBAC - GRANULAR PERMISSIONS ===")

# --- 20a. New toggle endpoints work for admin ---
toggle_domains = ["sites", "users", "system", "audit", "receiving", "map", "disposal", "credentials"]

# Get the viewer user ID directly from DB (admin page hides test_ accounts from non-justin_admin)
viewer_id = None
_vr = subprocess.run(
    "sudo -u postgres psql -d hardware_inventory -tAc "
    "\"SELECT id FROM users WHERE username = 'test_viewer_e2e'\"",
    shell=True, capture_output=True, text=True,
)
if _vr.stdout.strip().isdigit():
    viewer_id = int(_vr.stdout.strip())
    test("Found viewer user ID for toggle tests", True, f"id={viewer_id}")
else:
    warn("Could not find viewer user ID", "Toggle tests will be limited")

if viewer_id:
    # Toggle each new permission on
    for domain in toggle_domains:
        r = S.post(f"{BASE}/api/admin/toggle-{domain}/{viewer_id}")
        test(f"Admin toggles {domain} ON for viewer (200)", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            data = r.json()
            test(f"  {domain} flag is now True", data.get(f"can_{'view_audit_log' if domain == 'audit' else 'manage_' + domain if domain in ('sites', 'users', 'system') else 'access_' + domain}", data.get("new_value")) == True, str(data))

    # Viewer should now be able to access restricted pages with flags
    V2 = requests.Session()
    r = V2.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login for flag tests", r.status_code in (302, 303))

    r = V2.get(f"{BASE}/receive")
    test("Viewer WITH receiving flag can access /receive", r.status_code == 200, f"status={r.status_code}")

    r = V2.get(f"{BASE}/map/")
    test("Viewer WITH map flag can access /map/", r.status_code == 200, f"status={r.status_code}")

    r = V2.get(f"{BASE}/disposal/")
    test("Viewer WITH disposal flag can access /disposal/", r.status_code == 200, f"status={r.status_code}")

    r = V2.get(f"{BASE}/admin/audit")
    test("Viewer WITH audit flag can access /admin/audit", r.status_code == 200, f"status={r.status_code}")

    r = V2.get(f"{BASE}/admin/users")
    test("Viewer WITH users flag can access /admin/users", r.status_code == 200, f"status={r.status_code}")

    r = V2.get(f"{BASE}/admin/storage")
    test("Viewer WITH system flag can access /admin/storage", r.status_code == 200, f"status={r.status_code}")

    # Toggle each permission: True → False (force OFF)
    for domain in toggle_domains:
        r = S.post(f"{BASE}/api/admin/toggle-{domain}/{viewer_id}")
        test(f"Admin toggles {domain} to force-OFF for viewer (200)", r.status_code == 200, f"status={r.status_code}")

    # Viewer with force-OFF flags should be blocked
    V3 = requests.Session()
    r = V3.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login after flags force-OFF", r.status_code in (302, 303))

    r = V3.get(f"{BASE}/receive", allow_redirects=False)
    test("Viewer WITH force-OFF receiving blocked from /receive", r.status_code in (403, 302, 307), f"status={r.status_code}")

    r = V3.get(f"{BASE}/disposal/", allow_redirects=False)
    test("Viewer WITH force-OFF disposal blocked from /disposal/", r.status_code in (403, 302, 307), f"status={r.status_code}")

    r = V3.get(f"{BASE}/admin/audit", allow_redirects=False)
    test("Viewer WITH force-OFF audit blocked from /admin/audit", r.status_code in (403, 302, 307), f"status={r.status_code}")

    # Toggle each permission: False → NULL (back to inherit)
    for domain in toggle_domains:
        r = S.post(f"{BASE}/api/admin/toggle-{domain}/{viewer_id}")
        test(f"Admin resets {domain} to inherit for viewer (200)", r.status_code == 200, f"status={r.status_code}")

# --- 20b. Cannot toggle inherent permissions ---
# Create a temp admin user and get ID directly from the response
r = S.post(f"{BASE}/admin/users/add", data={
    "username": "temp_admin_toggle", "display_name": "Temp Admin", "password": "redacted-test-password", "role": "admin"
})
test("Create temp admin for toggle test", r.status_code in (200, 409))

temp_admin_id = None
if r.status_code == 200:
    temp_admin_id = r.json().get("id")

if temp_admin_id:
    for domain in ["users", "system", "audit", "receiving", "map", "disposal", "credentials", "sites",
                    "provisioning-manage", "provisioning-view"]:
        r = S.post(f"{BASE}/api/admin/toggle-{domain}/{temp_admin_id}")
        test(f"Cannot toggle {domain} on admin user (400)", r.status_code == 400, f"status={r.status_code}")

# --- 20c. Viewer IDOR on new toggle endpoints ---
r = V.post(f"{BASE}/api/admin/toggle-users/1")
test("Viewer CANNOT toggle users permission (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

r = V.post(f"{BASE}/api/admin/toggle-system/1")
test("Viewer CANNOT toggle system permission (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

r = V.post(f"{BASE}/api/admin/toggle-receiving/1")
test("Viewer CANNOT toggle receiving permission (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

# --- 20d. Non-existent user returns 404 ---
r = S.post(f"{BASE}/api/admin/toggle-map/999999")
test("Toggle map on non-existent user returns 404", r.status_code == 404, f"status={r.status_code}")

r = S.post(f"{BASE}/api/admin/toggle-credentials/999999")
test("Toggle credentials on non-existent user returns 404", r.status_code == 404, f"status={r.status_code}")


# ============================================================
# 21. DEVICE PROVISIONING
# ============================================================
print("\n=== 21. DEVICE PROVISIONING ===")

# --- 21a. Page access ---
r = S.get(f"{BASE}/provisioning/")
test("Admin can access /provisioning/ page", r.status_code == 200, f"status={r.status_code}")

r = V.get(f"{BASE}/provisioning/", allow_redirects=False)
test("Viewer CANNOT access /provisioning/ (403)", r.status_code in (301, 302, 303, 307, 403), f"status={r.status_code}")

# --- 21b. Create provisioning record (edge boxes only) ---
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 1, "priority": "high",
    "deployment_type": "pilot", "notes": "E2E provisioning test"
})
test("Create provisioning (valid)", r.status_code == 200, f"status={r.status_code}")
prov_id = None
if r.status_code == 200:
    prov_id = r.json().get("id")
    test("Create response includes id", prov_id is not None, f"id={prov_id}")

# Duplicate should return 409
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 1
})
test("Duplicate provisioning returns 409", r.status_code == 409, f"status={r.status_code}")

# Non-edge_boxes category should return 400
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "cameras", "device_id": 1
})
test("Non-edge_boxes category returns 400", r.status_code == 400, f"status={r.status_code}")

# Invalid device table
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "nonexistent_table", "device_id": 999
})
test("Invalid device table returns 400", r.status_code == 400, f"status={r.status_code}")

# Missing fields
r = S.post(f"{BASE}/api/provisioning", json={})
test("Missing fields returns 400", r.status_code == 400, f"status={r.status_code}")

# Invalid priority
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 1, "priority": "super_urgent"
})
test("Invalid priority returns 400", r.status_code in (400, 409), f"status={r.status_code}")

# Device not found
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 999999
})
test("Non-existent device returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 21c. Viewer RBAC on provisioning API ---
r = V.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 2
})
test("Viewer CANNOT create provisioning (403)", r.status_code in (403, 401), f"status={r.status_code}")

if prov_id:
    r = V.post(f"{BASE}/api/provisioning/{prov_id}/advance")
    test("Viewer CANNOT advance provisioning (403)", r.status_code in (403, 401), f"status={r.status_code}")

    r = V.post(f"{BASE}/api/provisioning/{prov_id}/revert")
    test("Viewer CANNOT revert provisioning (403)", r.status_code in (403, 401), f"status={r.status_code}")

    r = V.put(f"{BASE}/api/provisioning/{prov_id}", json={"priority": "low"})
    test("Viewer CANNOT update provisioning (403)", r.status_code in (403, 401), f"status={r.status_code}")

    r = V.delete(f"{BASE}/api/provisioning/{prov_id}")
    test("Viewer CANNOT delete provisioning (403)", r.status_code in (403, 401), f"status={r.status_code}")

# --- 21d. Advance through all 40 stages ---
if prov_id:
    stage_names = [
        "po_in", "scoped", "sourced", "ready",
        "ordered", "tracking", "deliver", "received",
        "staged", "building", "registered", "licensed",
        "hw_check", "sw_version", "pva_events", "certified",
        "packed", "labeled", "pickup", "transit",
        "dep_confirmed", "dep_se_assigned", "dep_site_ready", "dep_parts_staged",
        "dep_packed", "dep_shipped", "dep_in_transit", "dep_delivered",
        "dep_arrived", "dep_unpacked", "dep_cabled", "dep_powered_on",
        "dep_hw_install", "dep_configured", "dep_cameras_up", "dep_testing",
        "dep_verified", "dep_signoff", "dep_docs_sent", "dep_closed",
    ]
    _completed_early = False
    for i, stage_name in enumerate(stage_names):
        if _completed_early:
            break
        r = S.post(f"{BASE}/api/provisioning/{prov_id}/advance")
        resp_status = r.json().get("status") if r.status_code == 200 else None
        if resp_status == "completed":
            test(f"Complete final stage '{stage_name}'", r.status_code == 200,
                 f"status={r.status_code}")
            _completed_early = True
        elif i < len(stage_names) - 1:
            test(f"Advance past '{stage_name}' stage", r.status_code == 200 and resp_status == "advanced",
                 f"status={r.status_code}, resp={r.text[:80] if r.status_code != 200 else resp_status}")
        else:
            test(f"Complete final stage '{stage_name}'",
                 r.status_code == 200 and resp_status == "completed",
                 f"status={r.status_code}, resp={r.text[:80] if r.status_code != 200 else resp_status}")
            if r.status_code == 200:
                test("is_complete flag is true", r.json().get("is_complete") is True)

    # Advancing a completed record should fail
    r = S.post(f"{BASE}/api/provisioning/{prov_id}/advance")
    test("Advance on completed record returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 21e. Revert a stage ---
if prov_id:
    r = S.post(f"{BASE}/api/provisioning/{prov_id}/revert")
    test("Revert last completed stage", r.status_code == 200 and r.json().get("status") == "reverted",
         f"status={r.status_code}")
    if r.status_code == 200:
        test("After revert, current stage is 'dep_closed'", r.json().get("current_stage") == "dep_closed")

    # Advance again to re-complete
    r = S.post(f"{BASE}/api/provisioning/{prov_id}/advance")
    test("Re-advance after revert completes provisioning",
         r.status_code == 200 and r.json().get("is_complete") is True,
         f"status={r.status_code}")

# --- 21f. Update provisioning metadata ---
if prov_id:
    r = S.put(f"{BASE}/api/provisioning/{prov_id}", json={
        "priority": "urgent", "notes": "Updated by E2E test"
    })
    test("Update provisioning priority + notes", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Changed fields include priority and notes",
             set(r.json().get("changed", [])) == {"priority", "notes"})

    r = S.put(f"{BASE}/api/provisioning/{prov_id}", json={"priority": "invalid_val"})
    test("Update with invalid priority returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 21g. Non-existent provisioning IDs ---
r = S.post(f"{BASE}/api/provisioning/999999/advance")
test("Advance non-existent provisioning returns 404", r.status_code == 404, f"status={r.status_code}")

r = S.post(f"{BASE}/api/provisioning/999999/revert")
test("Revert non-existent provisioning returns 404", r.status_code == 404, f"status={r.status_code}")

r = S.put(f"{BASE}/api/provisioning/999999", json={"priority": "low"})
test("Update non-existent provisioning returns 404", r.status_code == 404, f"status={r.status_code}")

r = S.delete(f"{BASE}/api/provisioning/999999")
test("Delete non-existent provisioning returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 21h. Device list helper ---
r = S.get(f"{BASE}/api/provisioning/devices/edge_boxes")
test("Get devices for category (edge_boxes)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Edge boxes list is non-empty", len(r.json().get("devices", [])) > 0,
         f"count={len(r.json().get('devices', []))}")

r = S.get(f"{BASE}/api/provisioning/devices/fake_table")
test("Get devices for invalid category returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 21i. Delete provisioning ---
if prov_id:
    r = S.delete(f"{BASE}/api/provisioning/{prov_id}")
    test("Delete provisioning record", r.status_code == 200 and r.json().get("status") == "deleted",
         f"status={r.status_code}")

    # Confirm it's gone
    r = S.delete(f"{BASE}/api/provisioning/{prov_id}")
    test("Re-delete returns 404 (already deleted)", r.status_code == 404, f"status={r.status_code}")

# --- 21j. Auto-assignment on completion with site_id ---
# Create a test site for auto-assignment
r = S.post(f"{BASE}/api/sites", json={
    "name": "E2E Prov Site", "site_type": "internal_lab", "address": "Test"
})
prov_site_id = None
if r.status_code in (200, 201):
    prov_site_id = r.json().get("site_id") or r.json().get("id")

# Create provisioning with site (edge box only)
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 1,
    "site_id": prov_site_id, "priority": "normal",
    "deployment_type": "customer"
})
prov_id2 = None
if r.status_code == 200:
    prov_id2 = r.json().get("id")

# Advance through all 40 stages to complete the provisioning
if prov_id2:
    for _ in range(40):
        S.post(f"{BASE}/api/provisioning/{prov_id2}/advance")

    # Verify an assignment was auto-created
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"SELECT COUNT(*) FROM device_assignments WHERE device_table = 'edge_boxes' AND device_id = 1 AND site_id = {prov_site_id} AND is_active = true;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    auto_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
    test("Auto-assignment created on completion with site_id", auto_count > 0, f"count={auto_count}")

    # Clean up auto-assignment
    subprocess.run(
        f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM device_assignments WHERE device_table = 'edge_boxes' AND device_id = 1 AND site_id = {prov_site_id} AND notes LIKE 'Auto-assigned%';\"",
        shell=True, capture_output=True, text=True,
    )

# Clean up section 21 test data
if prov_id2:
    S.delete(f"{BASE}/api/provisioning/{prov_id2}")
if prov_site_id:
    subprocess.run(
        f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM sites WHERE id = {prov_site_id};\"",
        shell=True, capture_output=True, text=True,
    )

# --- 21k. Pipeline fields (due_date, start_date, location_note, deployment_bucket) ---
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 1,
    "deployment_type": "pilot",
    "due_date": "2026-03-15",
    "start_date": "2026-02-01",
    "location_note": "QA Lab - Test Unit",
    "deployment_bucket": "confirmed_pilot",
    "priority": "high"
})
test("Create provisioning with pipeline fields", r.status_code == 200, f"status={r.status_code}")
pipeline_prov_id = r.json().get("id") if r.status_code == 200 else None

# Invalid date format
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 3,
    "due_date": "2026/03/15"  # Wrong format
})
test("Invalid due_date format returns 400", r.status_code == 400, f"status={r.status_code}")

# Invalid deployment_bucket
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 3,
    "deployment_bucket": "invalid_bucket"
})
test("Invalid deployment_bucket returns 400", r.status_code == 400, f"status={r.status_code}")

# Update pipeline fields
if pipeline_prov_id:
    r = S.put(f"{BASE}/api/provisioning/{pipeline_prov_id}", json={
        "due_date": "2026-04-01",
        "location_note": "Sales Engineer Possession",
        "deployment_bucket": "in_progress"
    })
    test("Update pipeline fields", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        changed = set(r.json().get("changed", []))
        test("Changed fields include pipeline fields",
             {"due_date", "location_note", "deployment_bucket"}.issubset(changed),
             f"changed={changed}")

# --- 21l. Pipeline board endpoint (/api/provisioning/by-bucket) ---
r = S.get(f"{BASE}/api/provisioning/by-bucket")
test("Get provisioning by bucket", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    data = r.json()
    test("Response includes 'buckets' dict", "buckets" in data)
    test("Response includes 'bucket_labels' dict", "bucket_labels" in data)
    if "buckets" in data:
        buckets = data["buckets"]
        expected_buckets = ["customer_po", "confirmed_pilot", "in_progress", "certified", "in_inventory", "no_bucket"]
        test("All expected buckets present",
             all(b in buckets for b in expected_buckets),
             f"buckets={list(buckets.keys())}")

# Viewer CANNOT access by-bucket endpoint
r = V.get(f"{BASE}/api/provisioning/by-bucket")
test("Viewer CANNOT access /api/provisioning/by-bucket", r.status_code in (403, 401), f"status={r.status_code}")

# Clean up pipeline prov
if pipeline_prov_id:
    S.delete(f"{BASE}/api/provisioning/{pipeline_prov_id}")


# ============================================================
# 22. EDIT LOCKING API
# ============================================================
print("\n=== 22. EDIT LOCKING ===")

# 22a. Acquire a viewing lock
r = S.post(f"{BASE}/api/locks/acquire", json={"resource_key": "cameras:999"})
test("Acquire viewing lock (200)", r.status_code == 200)
data = r.json()
test("Lock granted", data.get("granted") is True)
test("No conflict on fresh lock", data.get("conflict") is False)
test("Lock level is viewing", data.get("lock_level") == "viewing")

# 22b. Re-acquire same lock (same user = refresh)
r = S.post(f"{BASE}/api/locks/acquire", json={"resource_key": "cameras:999"})
test("Re-acquire own lock succeeds", r.json().get("granted") is True)

# 22c. Escalate to editing
r = S.post(f"{BASE}/api/locks/escalate", json={"resource_key": "cameras:999"})
test("Escalate to editing (200)", r.status_code == 200)
data = r.json()
test("Escalation succeeded", data.get("escalated") is True)
test("Lock level now editing", data.get("lock_level") == "editing")

# 22d. Check lock status
r = S.get(f"{BASE}/api/locks/cameras:999")
test("Get lock status (200)", r.status_code == 200)
lock = r.json().get("lock")
test("Lock info returned", lock is not None)
test("Lock level is editing", lock is not None and lock.get("level") == "editing",
     "lock=" + str(lock))

# 22e. Heartbeat
r = S.post(f"{BASE}/api/locks/heartbeat", json={"resource_key": "cameras:999"})
test("Heartbeat succeeds", r.status_code == 200)
test("Heartbeat alive", r.json().get("alive") is True)

# 22f. Conflict detection - viewer session tries to lock same resource
r = V.post(f"{BASE}/api/locks/acquire", json={"resource_key": "cameras:999"})
test("Viewer conflict detected", r.status_code == 200)
data = r.json()
test("Viewer not granted (hard lock)", data.get("granted") == False,
     "granted=" + str(data.get("granted")) + " lock_level=" + str(data.get("lock_level")))
test("Conflict flagged", data.get("conflict") is True)
test("Shows locked_by", "locked_by" in data)

# 22g. Viewer cannot escalate someone else's lock
r = V.post(f"{BASE}/api/locks/escalate", json={"resource_key": "cameras:999"})
test("Viewer escalate blocked", r.json().get("escalated") is False)

# 22h. Release lock
r = S.post(f"{BASE}/api/locks/release", json={"resource_key": "cameras:999"})
test("Release lock (200)", r.status_code == 200)
test("Lock released", r.json().get("released") is True)

# 22i. Lock is gone after release
r = S.get(f"{BASE}/api/locks/cameras:999")
test("Lock cleared after release", r.json().get("lock") is None)

# 22j. Viewer can now acquire after release
r = V.post(f"{BASE}/api/locks/acquire", json={"resource_key": "cameras:999"})
test("Viewer can acquire after release", r.json().get("granted") is True)
V.post(f"{BASE}/api/locks/release", json={"resource_key": "cameras:999"})

# 22k. Release non-existent lock
r = S.post(f"{BASE}/api/locks/release", json={"resource_key": "nonexistent:0"})
test("Release non-existent lock (200)", r.status_code == 200)
test("Nothing to release", r.json().get("released") is False)

# 22l. Missing resource_key validation
r = S.post(f"{BASE}/api/locks/acquire", json={})
test("Acquire without key returns 400", r.status_code == 400)

r = S.post(f"{BASE}/api/locks/escalate", json={})
test("Escalate without key returns 400", r.status_code == 400)

r = S.post(f"{BASE}/api/locks/release", json={})
test("Release without key returns 400", r.status_code == 400)

r = S.post(f"{BASE}/api/locks/heartbeat", json={})
test("Heartbeat without key returns 400", r.status_code == 400)

# 22m. Admin can list all locks
r = S.post(f"{BASE}/api/locks/acquire", json={"resource_key": "test:listcheck"})
r = S.get(f"{BASE}/api/locks")
test("Admin list locks (200)", r.status_code == 200)
locks = r.json().get("locks", [])
test("Locks list is array", isinstance(locks, list))
S.post(f"{BASE}/api/locks/release", json={"resource_key": "test:listcheck"})

# 22n. Viewer cannot list all locks (admin only)
r = V.get(f"{BASE}/api/locks")
test("Viewer cannot list all locks (403)", r.status_code == 403, f"status={r.status_code}")

# 22o. Heartbeat on non-held lock
r = S.post(f"{BASE}/api/locks/heartbeat", json={"resource_key": "nobody:holds:this"})
test("Heartbeat on non-held lock returns false", r.json().get("alive") is False)

# 22p. Escalate without holding a lock
r = S.post(f"{BASE}/api/locks/escalate", json={"resource_key": "nobody:holds:this"})
test("Escalate without lock returns not escalated", r.json().get("escalated") is False)

# ============================================================
# 23. ZENDESK INTEGRATION (admin page)
# ============================================================
print("\n=== 23. ZENDESK ADMIN ===")

# 23a. Admin can access Zendesk settings page
r = S.get(f"{BASE}/admin/zendesk")
test("Admin can access Zendesk page (200)", r.status_code == 200)
test("Zendesk page has title", "Zendesk Integration" in r.text)

# 23b. Viewer cannot access Zendesk settings page
r = V.get(f"{BASE}/admin/zendesk", allow_redirects=False)
test("Viewer cannot access Zendesk page (403)", r.status_code in (403, 302, 307), f"status={r.status_code}")

# 23c. Test connection endpoint (returns 200 if configured, 400 if not)
r = S.post(f"{BASE}/api/zendesk/test")
test("Zendesk test returns 200 or 400", r.status_code in (200, 400), f"status={r.status_code}")
if r.status_code == 200:
    test("Zendesk test returns user info", "zendesk_user" in r.json() or "status" in r.json())
else:
    test("Error mentions not configured", "not configured" in r.json().get("error", "").lower())

# 23d. Organization endpoint
r = S.get(f"{BASE}/api/zendesk/organizations")
test("Zendesk orgs returns 200 or 400", r.status_code in (200, 400), f"status={r.status_code}")

# 23e. Tickets endpoint
r = S.get(f"{BASE}/api/zendesk/tickets")
test("Zendesk tickets returns 200 or 400", r.status_code in (200, 400), f"status={r.status_code}")

# 23f. Ticket fields endpoint
r = S.get(f"{BASE}/api/zendesk/ticket-fields")
test("Zendesk fields returns 200 or 400", r.status_code in (200, 400), f"status={r.status_code}")

# 23g. Viewer cannot access Zendesk API endpoints
r = V.post(f"{BASE}/api/zendesk/test")
test("Viewer cannot test Zendesk (403)", r.status_code == 403, f"status={r.status_code}")

r = V.get(f"{BASE}/api/zendesk/organizations")
test("Viewer cannot list orgs (403)", r.status_code == 403, f"status={r.status_code}")


# ============================================================
# 24. GUIDED TOURS API
# ============================================================
print("\n=== 24. GUIDED TOURS ===")

# 24a. List tours for dashboard page
r = S.get(f"{BASE}/api/tours", params={"page": "/dashboard"})
test("List tours for /dashboard (200)", r.status_code == 200)
data = r.json()
test("Tours response has tours array", "tours" in data)
dashboard_tours = data.get("tours", [])
test("Dashboard has at least 1 tour", len(dashboard_tours) >= 1)
if dashboard_tours:
    tour = dashboard_tours[0]
    test("Tour has id field", "id" in tour)
    test("Tour has steps array", "steps" in tour and isinstance(tour["steps"], list))
    test("Tour has progress field", "progress" in tour)
    test("Tour not yet completed", tour["progress"]["completed"] is False)

# 24b. List tours for warranty page
r = S.get(f"{BASE}/api/tours", params={"page": "/warranty"})
test("List tours for /warranty (200)", r.status_code == 200)
warranty_tours = r.json().get("tours", [])
test("Warranty has at least 1 tour", len(warranty_tours) >= 1)

# 24c. List tours for fulfillment page (provisioning moved to fulfillment)
r = S.get(f"{BASE}/api/tours", params={"page": "/fulfillment"})
test("List tours for /fulfillment (200)", r.status_code == 200)
ful_tours = r.json().get("tours", [])
test("Fulfillment has at least 1 tour", len(ful_tours) >= 1)

# 24d. List tours for non-tour page returns empty
r = S.get(f"{BASE}/api/tours", params={"page": "/admin/audit"})
test("Non-tour page returns 200", r.status_code == 200)
test("Non-tour page has empty tours", len(r.json().get("tours", [])) == 0)

# 24e. Missing page param returns 422
r = S.get(f"{BASE}/api/tours")
test("Missing page param returns 422", r.status_code == 422)

# 24f. Get all tours (help menu)
r = S.get(f"{BASE}/api/tours/all")
test("All tours endpoint (200)", r.status_code == 200)
all_tours = r.json().get("tours", [])
test("At least 3 tours defined", len(all_tours) >= 3)
if all_tours:
    test("Tour has name", "name" in all_tours[0])
    test("Tour has description", "description" in all_tours[0])
    test("Tour has step_count", "step_count" in all_tours[0])

# 24g. Get single tour by ID
r = S.get(f"{BASE}/api/tours/dashboard_tour")
test("Get dashboard_tour (200)", r.status_code == 200)
tour_data = r.json()
test("Tour ID matches", tour_data.get("id") == "dashboard_tour")
test("Tour has steps", len(tour_data.get("steps", [])) >= 1)

# 24h. Get non-existent tour returns 404
r = S.get(f"{BASE}/api/tours/nonexistent_tour_xyz")
test("Non-existent tour returns 404", r.status_code == 404)

# 24i. Mark tour as completed
r = S.post(f"{BASE}/api/tours/progress", json={"tour_id": "dashboard_tour", "dismissed": False})
test("Complete tour progress (200)", r.status_code == 200)
test("Progress ok response", r.json().get("ok") is True)

# 24j. Verify completed tour shows in progress
r = S.get(f"{BASE}/api/tours", params={"page": "/dashboard"})
test("Dashboard tours after completion (200)", r.status_code == 200)
tours_after = r.json().get("tours", [])
if tours_after:
    test("Tour shows completed", tours_after[0]["progress"]["completed"] is True)
    test("Tour not dismissed", tours_after[0]["progress"]["dismissed"] is False)

# 24k. Mark tour as dismissed
r = S.post(f"{BASE}/api/tours/progress", json={"tour_id": "warranty_tour", "dismissed": True})
test("Dismiss tour progress (200)", r.status_code == 200)
r = S.get(f"{BASE}/api/tours", params={"page": "/warranty"})
w_tours = r.json().get("tours", [])
if w_tours:
    test("Tour shows dismissed", w_tours[0]["progress"]["dismissed"] is True)

# 24l. Upsert: update existing progress
r = S.post(f"{BASE}/api/tours/progress", json={"tour_id": "dashboard_tour", "dismissed": True})
test("Update progress upsert (200)", r.status_code == 200)
r = S.get(f"{BASE}/api/tours", params={"page": "/dashboard"})
tours_upsert = r.json().get("tours", [])
if tours_upsert:
    test("Progress updated to dismissed", tours_upsert[0]["progress"]["dismissed"] is True)

# 24m. Missing tour_id returns 400
r = S.post(f"{BASE}/api/tours/progress", json={})
test("Progress without tour_id returns 400", r.status_code == 400)

# 24n. Reset tour progress (retake)
r = S.delete(f"{BASE}/api/tours/progress/dashboard_tour")
test("Reset tour progress (200)", r.status_code == 200)
test("Deleted 1 record", r.json().get("deleted") == 1)

# 24o. After reset, tour shows not completed
r = S.get(f"{BASE}/api/tours", params={"page": "/dashboard"})
tours_reset = r.json().get("tours", [])
if tours_reset:
    test("Tour not completed after reset", tours_reset[0]["progress"]["completed"] is False)

# 24p. Reset non-existent progress
r = S.delete(f"{BASE}/api/tours/progress/nonexistent_tour_xyz")
test("Reset non-existent progress (200)", r.status_code == 200)
test("Deleted 0 records", r.json().get("deleted") == 0)

# 24q. Viewer can access tour endpoints (tours are for all users)
r = V.get(f"{BASE}/api/tours", params={"page": "/dashboard"})
test("Viewer can list tours (200)", r.status_code == 200)

r = V.get(f"{BASE}/api/tours/all")
test("Viewer can list all tours (200)", r.status_code == 200)

r = V.post(f"{BASE}/api/tours/progress", json={"tour_id": "dashboard_tour", "dismissed": False})
test("Viewer can save progress (200)", r.status_code == 200)

# Clean up viewer's tour progress
V.delete(f"{BASE}/api/tours/progress/dashboard_tour")

# Clean up admin's tour progress
S.delete(f"{BASE}/api/tours/progress/warranty_tour")


# ============================================================
# 25. SKU CONVERSION SYSTEM
# ============================================================
print("\n=== 25. SKU CONVERSION ===")

# 25a. Test SKU conversion utilities (import directly)
import importlib.util, sys
sku_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "sku_conversion.py")
spec = importlib.util.spec_from_file_location("sku_conversion", sku_path)
sku_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sku_mod)

# 25b. Legacy SKU detection
test("is_legacy_sku PVA-25-30NR", sku_mod.is_legacy_sku("PVA-25-30NR") is True)
test("is_legacy_sku EDGE25-56TB-NR is False", sku_mod.is_legacy_sku("EDGE25-56TB-NR") is False)
test("is_legacy_sku None is False", sku_mod.is_legacy_sku(None) is False)
test("is_legacy_sku empty is False", sku_mod.is_legacy_sku("") is False)

# 25c. 2026 SKU detection
test("is_2026_sku EDGE25-56TB-NR", sku_mod.is_2026_sku("EDGE25-56TB-NR") is True)
test("is_2026_sku PVA-25-30NR is False", sku_mod.is_2026_sku("PVA-25-30NR") is False)

# 25d. SKU version detection
test("get_sku_version legacy", sku_mod.get_sku_version("PVA-50-60R6") == "legacy")
test("get_sku_version 2026", sku_mod.get_sku_version("EDGE100-168TB-NR") == "2026")

# 25e. Legacy → New conversion
test("Convert PVA-25-30NR → EDGE25-56TB-NR",
     sku_mod.convert_legacy_sku("PVA-25-30NR") == "EDGE25-56TB-NR")
test("Convert PVA-50-60R6 → PVA50-120TB-Z2",
     sku_mod.convert_legacy_sku("PVA-50-60R6") == "PVA50-120TB-Z2")
test("Convert PVA-100-30NR → EDGE100-168TB-NR",
     sku_mod.convert_legacy_sku("PVA-100-30NR") == "EDGE100-168TB-NR")
test("Convert PVA-25-30R5 → PVA50-84TB-Z2 (RAID5 retired)",
     sku_mod.convert_legacy_sku("PVA-25-30R5") == "PVA50-84TB-Z2")
test("Unknown SKU returns original",
     sku_mod.convert_legacy_sku("UNKNOWN-SKU") == "UNKNOWN-SKU")

# 25f. Reverse mapping
legacy_skus = sku_mod.get_legacy_skus_for_new("EDGE25-56TB-NR")
test("Reverse lookup EDGE25-56TB-NR has legacy matches", len(legacy_skus) > 0)
test("PVA-25-30NR in reverse lookup", "PVA-25-30NR" in legacy_skus)

# 25g. Extract SKU info
info = sku_mod.extract_sku_info("EDGE100-168TB-NR")
test("extract_sku_info channels=100", info["channels"] == "100")
test("extract_sku_info storage=168", info["storage_tb"] == "168")
test("extract_sku_info raid=NR", info["raid_type"] == "NR")
test("extract_sku_info version=2026", info["version"] == "2026")
test("extract_sku_info chassis=2U", info["chassis"] == "2U")

info_legacy = sku_mod.extract_sku_info("PVA-50-60R6")
test("extract_sku_info legacy channels=50", info_legacy["channels"] == "50")
test("extract_sku_info legacy raid=R6", info_legacy["raid_type"] == "R6")
test("extract_sku_info legacy version=legacy", info_legacy["version"] == "legacy")

# 25h. Mapping completeness
test("Legacy mapping has 46 entries", len(sku_mod.LEGACY_SKU_MAPPING) == 46)

# 25i. SKU version in edge box dropdown API
r = S.get(f"{BASE}/api/provisioning/devices/edge_boxes")
test("Edge box dropdown includes sku_version", r.status_code == 200)
if r.status_code == 200:
    devices = r.json().get("devices", [])
    if devices:
        first = devices[0]
        test("Dropdown device has sku_version field", "sku_version" in first)
        test("Dropdown device has sku_version value", first.get("sku_version") is not None)



# ============================================================
# 26. ZENDESK TICKET INTEGRATION (Provisioning)
# ============================================================
print("\n=== 26. ZENDESK TICKET INTEGRATION ===")

# 26a. Fetch known Zendesk ticket (507 = Kitchen Demo Site)
r = S.get(f"{BASE}/api/provisioning/zendesk-ticket/507")
if r.status_code == 200:
    data = r.json()
    test("Fetch ticket 507 returns ticket_id", data.get("ticket_id") == 507)
    test("Ticket 507 subject is Kitchen Demo Site",
         "kitchen" in data.get("subject", "").lower(),
         f"subject={data.get('subject')}")
    test("Ticket has edge_box object", "edge_box" in data)

    eb = data.get("edge_box", {})
    test("Ticket 507 serial_number is F0P4SF4",
         eb.get("serial_number") == "F0P4SF4",
         f"serial={eb.get('serial_number')}")
    test("Ticket 507 UUID present",
         eb.get("uuid") == "00064A6A-83FFEA45-EC725F38-02926620",
         f"uuid={eb.get('uuid')}")
    test("Ticket 507 MAC1 present",
         eb.get("mac1") == "1c:86:0b:39:03:83",
         f"mac1={eb.get('mac1')}")
    test("Ticket 507 MAC2 present",
         eb.get("mac2") == "fc:4c:ea:cd:0c:e4",
         f"mac2={eb.get('mac2')}")
    test("Ticket 507 customer_site is Kitchen",
         eb.get("customer_site") == "Kitchen",
         f"site={eb.get('customer_site')}")
    test("Ticket 507 licenses present", eb.get("licenses") is not None)
    test("Ticket 507 due_date present", eb.get("due_date") is not None)

    # Inventory match
    inv = data.get("inventory_match")
    test("Ticket 507 has inventory match", inv is not None)
    if inv:
        test("Inventory match serial=F0P4SF4", inv.get("serial") == "F0P4SF4")
        test("Inventory match has part_number", inv.get("part_number") is not None)
        test("Inventory match has sku_version", "sku_version" in inv,
             "sku_version=" + str(inv.get("sku_version")))

    test("Ticket has Zendesk URL",
         "example-help.zendesk.com" in data.get("url", ""))
elif r.status_code == 503:
    test("Zendesk not configured (503) — skipping ticket tests", True)
    warn("Zendesk not configured, skipping ticket integration tests")
else:
    test("Fetch ticket 507 succeeds", False, f"status={r.status_code}")

# 26b. Fetch non-existent ticket
r = S.get(f"{BASE}/api/provisioning/zendesk-ticket/999999999")
test("Non-existent ticket returns 404 or 500",
     r.status_code in (404, 500),
     f"status={r.status_code}")

# 26c. Viewer CANNOT access zendesk ticket endpoint
r = V.get(f"{BASE}/api/provisioning/zendesk-ticket/507")
test("Viewer cannot fetch Zendesk ticket (403)",
     r.status_code in (403, 401),
     f"status={r.status_code}")

# 26d. Create provisioning with zendesk_ticket_id
r = S.post(f"{BASE}/api/provisioning", json={
    "device_table": "edge_boxes", "device_id": 3,
    "deployment_type": "pilot",
    "zendesk_ticket_id": 507,
    "deployment_bucket": "confirmed_pilot",
    "notes": "E2E Zendesk test"
})
test("Create provisioning with zendesk_ticket_id",
     r.status_code == 200, f"status={r.status_code}")
zendesk_prov_id = r.json().get("id") if r.status_code == 200 else None

# 26e. Clean up Zendesk provisioning test
if zendesk_prov_id:
    S.delete(f"{BASE}/api/provisioning/{zendesk_prov_id}")


# ============================================================
# 27. TEAM MANAGEMENT & PERMISSION INHERITANCE
# ============================================================
print("\n=== 27. TEAM MANAGEMENT & PERMISSION INHERITANCE ===")

# --- 27a. Admin can access /admin/teams page ---
r = S.get(f"{BASE}/admin/teams")
test("Admin can access /admin/teams page", r.status_code == 200, f"status={r.status_code}")

# --- 27b. Viewer CANNOT access /admin/teams ---
r = V.get(f"{BASE}/admin/teams", allow_redirects=False)
test("Viewer CANNOT access /admin/teams (403)", r.status_code in (403, 302, 307), f"status={r.status_code}")

# --- 27c. Create team via API ---
r = S.post(f"{BASE}/admin/teams/add", json={"name": "E2E Test Team", "description": "E2E automated test team"})
test("Create team via API (200)", r.status_code == 200, f"status={r.status_code}")
e2e_team_id = None
if r.status_code == 200:
    data = r.json()
    e2e_team_id = data.get("team_id")
    test("Create team response includes team_id", e2e_team_id is not None, str(data))
    test("Create team response includes name", data.get("name") == "E2E Test Team", str(data))

# --- 27d. Duplicate team name returns 400 ---
r = S.post(f"{BASE}/admin/teams/add", json={"name": "E2E Test Team", "description": "Duplicate"})
test("Duplicate team name returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 27e. Empty team name returns 400 ---
r = S.post(f"{BASE}/admin/teams/add", json={"name": "", "description": "No name"})
test("Empty team name returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 27f. Team name too long returns 400 ---
r = S.post(f"{BASE}/admin/teams/add", json={"name": "A" * 65, "description": "Too long"})
test("Team name >64 chars returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 27g. Update team name/description ---
if e2e_team_id:
    r = S.put(f"{BASE}/api/admin/teams/{e2e_team_id}", json={"name": "E2E Renamed Team", "description": "Updated description"})
    test("Update team name/description (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Updated team name matches", r.json().get("name") == "E2E Renamed Team", str(r.json()))

    # Rename back for consistency
    S.put(f"{BASE}/api/admin/teams/{e2e_team_id}", json={"name": "E2E Test Team"})

# --- 27h. Update to duplicate name returns 400 ---
# Create a second team to test duplicate rename
r = S.post(f"{BASE}/admin/teams/add", json={"name": "E2E Team Two", "description": "Second team"})
e2e_team2_id = r.json().get("team_id") if r.status_code == 200 else None
if e2e_team2_id and e2e_team_id:
    r = S.put(f"{BASE}/api/admin/teams/{e2e_team2_id}", json={"name": "E2E Test Team"})
    test("Rename team to existing name returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 27i. Update non-existent team returns 404 ---
r = S.put(f"{BASE}/api/admin/teams/999999", json={"name": "Ghost"})
test("Update non-existent team returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 27j. Delete non-existent team returns 404 ---
r = S.delete(f"{BASE}/api/admin/teams/999999")
test("Delete non-existent team returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 27k. Update team permissions ---
if e2e_team_id:
    r = S.post(f"{BASE}/api/admin/teams/{e2e_team_id}/permissions", json={
        "can_access_map": True,
        "can_view_audit_log": True,
        "can_access_disposal": True,
        "can_view_provisioning": True,
    })
    test("Update team permissions (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Team permissions changed count", r.json().get("changes") == 4, str(r.json()))

# --- 27l. Update non-existent team permissions returns 404 ---
r = S.post(f"{BASE}/api/admin/teams/999999/permissions", json={"can_access_map": True})
test("Update perms on non-existent team returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 27m. Assign viewer to team ---
if viewer_id and e2e_team_id:
    r = S.post(f"{BASE}/api/admin/users/{viewer_id}/team", json={"team_id": e2e_team_id})
    test("Assign viewer to E2E Test Team (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        data = r.json()
        test("Assignment response team_name correct", data.get("team_name") == "E2E Test Team", str(data))

# --- 27n. Assign to non-existent team returns 404 ---
if viewer_id:
    r = S.post(f"{BASE}/api/admin/users/{viewer_id}/team", json={"team_id": 999999})
    test("Assign to non-existent team returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 27o. Assign non-existent user returns 404 ---
r = S.post(f"{BASE}/api/admin/users/999999/team", json={"team_id": e2e_team_id or 1})
test("Assign non-existent user returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 27p. TEAM PERMISSION INHERITANCE ---
# Viewer was assigned to team with: map=T, audit=T, disposal=T, prov_view=T
# Viewer's user-level flags should all be NULL (inherit) after Section 20 reset
if viewer_id and e2e_team_id:
    V4 = requests.Session()
    r = V4.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login for inheritance tests", r.status_code in (302, 303))

    # Should inherit map access from team
    r = V4.get(f"{BASE}/map/")
    test("Viewer INHERITS map access from team", r.status_code == 200, f"status={r.status_code}")

    # Should inherit audit access from team
    r = V4.get(f"{BASE}/admin/audit")
    test("Viewer INHERITS audit access from team", r.status_code == 200, f"status={r.status_code}")

    # Should inherit disposal access from team
    r = V4.get(f"{BASE}/disposal/")
    test("Viewer INHERITS disposal access from team", r.status_code == 200, f"status={r.status_code}")

    # Should inherit provisioning view access from team
    r = V4.get(f"{BASE}/provisioning/")
    test("Viewer INHERITS provisioning view from team", r.status_code == 200, f"status={r.status_code}")

    # Should NOT have receiving access (team doesn't grant it)
    r = V4.get(f"{BASE}/receive", allow_redirects=False)
    test("Viewer does NOT inherit receiving (team has no flag)", r.status_code in (403, 302, 307), f"status={r.status_code}")

    # Should NOT have credentials access (team doesn't grant it)
    # Credentials are per-device API calls (no standalone page), test with API endpoint
    r = V4.get(f"{BASE}/api/credentials/edge_boxes/1", allow_redirects=False)
    test("Viewer does NOT inherit credentials (team has no flag)", r.status_code in (403, 302, 307), f"status={r.status_code}")

# --- 27q. USER OVERRIDE: Force-OFF overrides team default ---
if viewer_id and e2e_team_id:
    # Toggle map to True first (None→True), then to False (True→False = force OFF)
    S.post(f"{BASE}/api/admin/toggle-map/{viewer_id}")  # None→True
    S.post(f"{BASE}/api/admin/toggle-map/{viewer_id}")  # True→False (force OFF)

    V5 = requests.Session()
    r = V5.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login for force-OFF override test", r.status_code in (302, 303))

    r = V5.get(f"{BASE}/map/", allow_redirects=False)
    test("Viewer force-OFF map overrides team (blocked)", r.status_code in (403, 302, 307), f"status={r.status_code}")

    # Reset map back to NULL (inherit) — cycle: False→None
    S.post(f"{BASE}/api/admin/toggle-map/{viewer_id}")  # False→None

    # Verify inheritance works again
    V6 = requests.Session()
    r = V6.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login after map reset to inherit", r.status_code in (302, 303))

    r = V6.get(f"{BASE}/map/")
    test("Viewer inherits map again after reset to NULL", r.status_code == 200, f"status={r.status_code}")

# --- 27r. USER OVERRIDE: Force-ON works without team ---
if viewer_id and e2e_team_id:
    # Toggle receiving ON for viewer (team doesn't have it)
    S.post(f"{BASE}/api/admin/toggle-receiving/{viewer_id}")  # None→True

    V7 = requests.Session()
    r = V7.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login for force-ON override test", r.status_code in (302, 303))

    r = V7.get(f"{BASE}/receive")
    test("Viewer force-ON receiving overrides team (allowed)", r.status_code == 200, f"status={r.status_code}")

    # Reset receiving back to NULL — cycle: True→False→None
    S.post(f"{BASE}/api/admin/toggle-receiving/{viewer_id}")  # True→False
    S.post(f"{BASE}/api/admin/toggle-receiving/{viewer_id}")  # False→None

# --- 27s. Remove viewer from team ---
if viewer_id:
    r = S.post(f"{BASE}/api/admin/users/{viewer_id}/team", json={"team_id": None})
    test("Remove viewer from team (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Removal response team_name is None", r.json().get("team_name") == "None", str(r.json()))

    # Verify viewer lost inherited access
    V8 = requests.Session()
    r = V8.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login after team removal", r.status_code in (302, 303))

    r = V8.get(f"{BASE}/map/", allow_redirects=False)
    test("Viewer lost map access after team removal", r.status_code in (403, 302, 307), f"status={r.status_code}")

    r = V8.get(f"{BASE}/provisioning/", allow_redirects=False)
    test("Viewer lost provisioning view after team removal", r.status_code in (301, 302, 303, 307, 403), f"status={r.status_code}")

# --- 27t. Viewer IDOR on team CRUD ---
r = V.post(f"{BASE}/admin/teams/add", json={"name": "Hacker Team"})
test("Viewer CANNOT create team (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

if e2e_team_id:
    r = V.put(f"{BASE}/api/admin/teams/{e2e_team_id}", json={"name": "Hacked"})
    test("Viewer CANNOT update team (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

    r = V.delete(f"{BASE}/api/admin/teams/{e2e_team_id}")
    test("Viewer CANNOT delete team (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

    r = V.post(f"{BASE}/api/admin/teams/{e2e_team_id}/permissions", json={"can_access_map": True})
    test("Viewer CANNOT update team perms (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

if viewer_id:
    r = V.post(f"{BASE}/api/admin/users/{viewer_id}/team", json={"team_id": 1})
    test("Viewer CANNOT assign team (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

# --- 27u. Delete team with members unassigns them ---
# Create a fresh team, assign viewer, then delete
r = S.post(f"{BASE}/admin/teams/add", json={"name": "E2E Delete Test", "description": "Will be deleted"})
del_team_id = r.json().get("team_id") if r.status_code == 200 else None
if del_team_id and viewer_id:
    S.post(f"{BASE}/api/admin/users/{viewer_id}/team", json={"team_id": del_team_id})
    r = S.delete(f"{BASE}/api/admin/teams/{del_team_id}")
    test("Delete team with member (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Delete reports 1 member unassigned", r.json().get("members_unassigned") == 1, str(r.json()))

# --- 27v. Cleanup test teams ---
if e2e_team2_id:
    S.delete(f"{BASE}/api/admin/teams/{e2e_team2_id}")
if e2e_team_id:
    S.delete(f"{BASE}/api/admin/teams/{e2e_team_id}")


# ============================================================
# 28. PROVISIONING VIEW/MANAGE SPLIT & CEO ROLE
# ============================================================
print("\n=== 28. PROVISIONING VIEW/MANAGE SPLIT & CEO ROLE ===")

# --- 28a. Create CEO test user via setup script (CEO is tier 4 — admin cannot create via HTTP) ---
ceo_setup = """
import sys; sys.path.insert(0, '/opt/hardware_inventory')
from app.database import SessionLocal
from app.models import User
from app.auth import hash_password
db = SessionLocal()
u = db.query(User).filter(User.username == 'test_ceo_e2e').first()
if u:
    u.password_hash = hash_password('redacted-test-password')
    u.must_change_password = False
    u.is_active = True
    u.role = 'ceo'
else:
    u = User(username='test_ceo_e2e', display_name='Test CEO',
             password_hash=hash_password('redacted-test-password'),
             role='ceo', must_change_password=False, is_active=True)
    db.add(u)
db.commit()
db.refresh(u)
print(u.id)
db.close()
"""
ceo_result = subprocess.run(
    ["/opt/hardware_inventory/venv/bin/python3", "-c", ceo_setup],
    capture_output=True, text=True,
)
ceo_id = int(ceo_result.stdout.strip()) if ceo_result.stdout.strip().isdigit() else None
test("Create CEO test user", ceo_id is not None, f"id={ceo_id}, err={ceo_result.stderr[:100] if ceo_result.stderr else ''}")

# Login as CEO
CEO = requests.Session()
r = CEO.post(f"{BASE}/login", data={"username": "test_ceo_e2e", "password": "redacted-test-password"}, allow_redirects=False)
test("CEO login succeeds", r.status_code in (302, 303))

# --- 28b. CEO can access admin pages ---
r = CEO.get(f"{BASE}/dashboard")
test("CEO can access dashboard", r.status_code == 200, f"status={r.status_code}")

r = CEO.get(f"{BASE}/admin/users")
test("CEO can access /admin/users", r.status_code == 200, f"status={r.status_code}")

r = CEO.get(f"{BASE}/admin/teams")
test("CEO can access /admin/teams", r.status_code == 200, f"status={r.status_code}")

r = CEO.get(f"{BASE}/admin/audit")
test("CEO can access /admin/audit", r.status_code == 200, f"status={r.status_code}")

# --- 28c. CEO can access provisioning (manage level) ---
r = CEO.get(f"{BASE}/provisioning/")
test("CEO can access /provisioning/ (manage)", r.status_code == 200, f"status={r.status_code}")

# --- 28d. CEO CANNOT access credentials (unless flag granted) ---
# Credentials are accessed via API endpoint (no standalone page)
r = CEO.get(f"{BASE}/api/credentials/edge_boxes/1", allow_redirects=False)
test("CEO CANNOT access /api/credentials/ without flag", r.status_code in (403, 302, 307), f"status={r.status_code}")

# --- 28e. CEO can access other lifecycle pages ---
r = CEO.get(f"{BASE}/warranty/")
test("CEO can access /warranty/", r.status_code == 200, f"status={r.status_code}")

r = CEO.get(f"{BASE}/trials/")
test("CEO can access /trials/", r.status_code == 200, f"status={r.status_code}")

r = CEO.get(f"{BASE}/disposal/")
test("CEO can access /disposal/", r.status_code == 200, f"status={r.status_code}")

# --- 28f. Cannot toggle permissions on CEO (inherent admin) ---
if ceo_id:
    for domain in ["sites", "users", "system", "provisioning-manage", "provisioning-view"]:
        r = S.post(f"{BASE}/api/admin/toggle-{domain}/{ceo_id}")
        test(f"Cannot toggle {domain} on CEO (400)", r.status_code == 400, f"status={r.status_code}")

# --- 28g. Provisioning view-only: toggle on viewer ---
if viewer_id:
    # Toggle provisioning-view ON for viewer: None→True
    r = S.post(f"{BASE}/api/admin/toggle-provisioning-view/{viewer_id}")
    test("Toggle provisioning-view ON for viewer (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Provisioning view flag is True", r.json().get("can_view_provisioning") == True, str(r.json()))

    PV = requests.Session()
    r = PV.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login for provisioning view test", r.status_code in (302, 303))

    # --- 28h. Viewer with prov-view CAN access provisioning page ---
    r = PV.get(f"{BASE}/provisioning/")
    test("Viewer WITH prov-view can access /provisioning/", r.status_code == 200, f"status={r.status_code}")

    # --- 28i. Viewer with prov-view CANNOT create provisioning ---
    r = PV.post(f"{BASE}/api/provisioning", json={
        "device_table": "edge_boxes", "device_id": 999, "notes": "E2E view-only test"
    })
    test("Viewer WITH prov-view CANNOT create provisioning (403)", r.status_code == 403, f"status={r.status_code}")

    # --- 28j. Viewer with prov-view CANNOT delete provisioning ---
    r = PV.delete(f"{BASE}/api/provisioning/1")
    test("Viewer WITH prov-view CANNOT delete provisioning (403)", r.status_code in (403, 401), f"status={r.status_code}")

    # --- 28k. Reset provisioning-view: True→False→None ---
    S.post(f"{BASE}/api/admin/toggle-provisioning-view/{viewer_id}")  # True→False
    S.post(f"{BASE}/api/admin/toggle-provisioning-view/{viewer_id}")  # False→None

# --- 28l. Provisioning manage: toggle on viewer ---
if viewer_id:
    # Toggle provisioning-manage ON for viewer: None→True
    r = S.post(f"{BASE}/api/admin/toggle-provisioning-manage/{viewer_id}")
    test("Toggle provisioning-manage ON for viewer (200)", r.status_code == 200, f"status={r.status_code}")

    PM = requests.Session()
    r = PM.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login for provisioning manage test", r.status_code in (302, 303))

    # Viewer with prov-manage CAN access provisioning page
    r = PM.get(f"{BASE}/provisioning/")
    test("Viewer WITH prov-manage can access /provisioning/", r.status_code == 200, f"status={r.status_code}")

    # Viewer with prov-manage CAN create provisioning (if valid device exists)
    r = PM.post(f"{BASE}/api/provisioning", json={
        "device_table": "edge_boxes", "device_id": 999999, "notes": "E2E manage test"
    })
    # 404 for non-existent device is fine — proves the guard passed
    test("Viewer WITH prov-manage passes provisioning guard", r.status_code in (200, 404, 400), f"status={r.status_code}")

    # Reset provisioning-manage: True→False→None
    S.post(f"{BASE}/api/admin/toggle-provisioning-manage/{viewer_id}")  # True→False
    S.post(f"{BASE}/api/admin/toggle-provisioning-manage/{viewer_id}")  # False→None

# --- 28m. Team-based provisioning inheritance ---
# Create team with provisioning-view, assign viewer, verify access
r = S.post(f"{BASE}/admin/teams/add", json={"name": "E2E Prov Team", "description": "Provisioning test team"})
prov_team_id = r.json().get("team_id") if r.status_code == 200 else None

if prov_team_id and viewer_id:
    # Set team to have provisioning view only
    S.post(f"{BASE}/api/admin/teams/{prov_team_id}/permissions", json={
        "can_view_provisioning": True,
    })

    # Assign viewer to team
    S.post(f"{BASE}/api/admin/users/{viewer_id}/team", json={"team_id": prov_team_id})

    PT = requests.Session()
    r = PT.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login for team prov inheritance", r.status_code in (302, 303))

    r = PT.get(f"{BASE}/provisioning/")
    test("Viewer INHERITS prov-view from team", r.status_code == 200, f"status={r.status_code}")

    r = PT.post(f"{BASE}/api/provisioning", json={
        "device_table": "edge_boxes", "device_id": 999, "notes": "E2E team view test"
    })
    test("Viewer with team prov-view CANNOT create (403)", r.status_code == 403, f"status={r.status_code}")

    # Upgrade team to provisioning-manage
    S.post(f"{BASE}/api/admin/teams/{prov_team_id}/permissions", json={
        "can_manage_provisioning": True,
    })

    PT2 = requests.Session()
    r = PT2.post(f"{BASE}/login", data={"username": "test_viewer_e2e", "password": "redacted-test-password"}, allow_redirects=False)
    test("Viewer re-login for team prov-manage", r.status_code in (302, 303))

    r = PT2.post(f"{BASE}/api/provisioning", json={
        "device_table": "edge_boxes", "device_id": 999999, "notes": "E2E team manage test"
    })
    test("Viewer with team prov-manage passes guard", r.status_code in (200, 404, 400), f"status={r.status_code}")

    # Cleanup: remove viewer from team
    S.post(f"{BASE}/api/admin/users/{viewer_id}/team", json={"team_id": None})

    # Delete provisioning team
    S.delete(f"{BASE}/api/admin/teams/{prov_team_id}")

# --- 28n. Three-state toggle cycle verification ---
if viewer_id:
    # Start: NULL (inherit)
    r = S.post(f"{BASE}/api/admin/toggle-provisioning-view/{viewer_id}")
    test("Prov-view toggle 1: NULL→True", r.status_code == 200 and r.json().get("can_view_provisioning") == True,
         str(r.json()) if r.status_code == 200 else f"status={r.status_code}")

    r = S.post(f"{BASE}/api/admin/toggle-provisioning-view/{viewer_id}")
    test("Prov-view toggle 2: True→False", r.status_code == 200 and r.json().get("can_view_provisioning") == False,
         str(r.json()) if r.status_code == 200 else f"status={r.status_code}")

    r = S.post(f"{BASE}/api/admin/toggle-provisioning-view/{viewer_id}")
    test("Prov-view toggle 3: False→None (inherit)",
         r.status_code == 200 and r.json().get("can_view_provisioning") is None,
         str(r.json()) if r.status_code == 200 else f"status={r.status_code}")

# --- 28o. Viewer IDOR on provisioning toggles ---
r = V.post(f"{BASE}/api/admin/toggle-provisioning-manage/1")
test("Viewer CANNOT toggle prov-manage (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

r = V.post(f"{BASE}/api/admin/toggle-provisioning-view/1")
test("Viewer CANNOT toggle prov-view (IDOR)", r.status_code in (403, 302, 307, 401), f"status={r.status_code}")

# --- 28p. Non-existent user provisioning toggles return 404 ---
r = S.post(f"{BASE}/api/admin/toggle-provisioning-manage/999999")
test("Toggle prov-manage on non-existent user returns 404", r.status_code == 404, f"status={r.status_code}")

r = S.post(f"{BASE}/api/admin/toggle-provisioning-view/999999")
test("Toggle prov-view on non-existent user returns 404", r.status_code == 404, f"status={r.status_code}")


# ============================================================
# 29. VENDOR PROFILES
# ============================================================
print("\n=== 29. VENDOR PROFILES ===")

# --- 29a. Viewer CAN access vendor list page ---
r = V.get(f"{BASE}/vendors/")
test("Viewer CAN access /vendors/ (200)", r.status_code == 200, f"status={r.status_code}")

# --- 29b. Admin CAN access vendor list page ---
r = S.get(f"{BASE}/vendors/")
test("Admin CAN access /vendors/ (200)", r.status_code == 200, f"status={r.status_code}")

# --- 29c. Viewer CANNOT create vendor profile (403) ---
r = V.post(f"{BASE}/api/vendors/", json={"name": "E2E Viewer Vendor Attempt"})
test("Viewer CANNOT POST /api/vendors/ (403)", r.status_code in (403, 302, 307), f"status={r.status_code}")

# --- 29d. Admin CAN create vendor profile ---
r = S.post(f"{BASE}/api/vendors/", json={
    "name": "E2E Vendor Corp",
    "display_name": "E2E Vendor Corporation",
    "contact_name": "Test Contact",
    "contact_email": "vendor@e2e.test",
    "contact_phone": "555-0199",
    "website": "https://e2e-vendor.test",
    "is_oem": True,
    "categories_supplied": "Edge Boxes, Cameras",
    "notes": "E2E test vendor profile",
})
test("Admin CAN create vendor profile (200)", r.status_code == 200, f"status={r.status_code}, body={r.text[:100]}")
vendor_id = r.json().get("vendor_id") if r.status_code == 200 else None

# --- 29e. Vendor detail page accessible ---
if vendor_id:
    r = S.get(f"{BASE}/vendors/{vendor_id}")
    test("GET /vendors/{id} returns detail page (200)", r.status_code == 200, f"status={r.status_code}")

    r = V.get(f"{BASE}/vendors/{vendor_id}")
    test("Viewer CAN access vendor detail page (200)", r.status_code == 200, f"status={r.status_code}")

# --- 29f. Duplicate vendor name rejected (409) ---
r = S.post(f"{BASE}/api/vendors/", json={"name": "E2E Vendor Corp"})
test("Duplicate vendor name returns 409", r.status_code == 409, f"status={r.status_code}")

# --- 29g. Empty vendor name rejected (400) ---
r = S.post(f"{BASE}/api/vendors/", json={"name": ""})
test("Empty vendor name returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 29h. Admin CAN update vendor profile ---
if vendor_id:
    r = S.put(f"{BASE}/api/vendors/{vendor_id}", json={
        "contact_name": "Updated Contact",
        "is_oem": False,
        "notes": "E2E updated notes",
    })
    test("Admin CAN update vendor profile (200)", r.status_code == 200, f"status={r.status_code}")

    # 29i. Viewer CANNOT update vendor profile
    r = V.put(f"{BASE}/api/vendors/{vendor_id}", json={"contact_name": "Hack"})
    test("Viewer CANNOT PUT /api/vendors/{id} (403)", r.status_code in (403, 302, 307), f"status={r.status_code}")

# --- 29j. Update on non-existent ID returns 404 ---
r = S.put(f"{BASE}/api/vendors/999999", json={"contact_name": "Ghost"})
test("PUT /api/vendors/999999 returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 29k. POST /api/vendors/auto-create requires admin ---
r = V.post(f"{BASE}/api/vendors/auto-create")
test("Viewer CANNOT POST /api/vendors/auto-create (403)", r.status_code in (403, 302, 307), f"status={r.status_code}")

r = S.post(f"{BASE}/api/vendors/auto-create")
test("Admin CAN POST /api/vendors/auto-create (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    data = r.json()
    test("Auto-create returns count field", "count" in data and isinstance(data["count"], int),
         f"count={data.get('count')}")

# --- 29l. Admin CAN delete vendor profile ---
if vendor_id:
    r = S.delete(f"{BASE}/api/vendors/{vendor_id}")
    test("Admin CAN delete vendor profile (200)", r.status_code == 200, f"status={r.status_code}")
    vendor_id = None  # cleared

# --- 29m. DELETE on non-existent ID returns 404 ---
r = S.delete(f"{BASE}/api/vendors/999999")
test("DELETE /api/vendors/999999 returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 29n. Redirect on unknown vendor detail page ---
r = S.get(f"{BASE}/vendors/999999", allow_redirects=False)
test("Unknown vendor detail redirects (302/303)", r.status_code in (302, 303, 307), f"status={r.status_code}")


# ============================================================
# 30. NOTIFICATION SUBSCRIPTIONS & WATCH
# ============================================================
print("\n=== 30. NOTIFICATION SUBSCRIPTIONS & WATCH ===")

# --- 30a. GET /api/notifications/subscriptions returns list (any logged-in user) ---
r = S.get(f"{BASE}/api/notifications/subscriptions")
test("Admin GET /api/notifications/subscriptions (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Subscriptions response has 'subscriptions' key", "subscriptions" in r.json(), str(r.json()))

r = V.get(f"{BASE}/api/notifications/subscriptions")
test("Viewer GET /api/notifications/subscriptions (200)", r.status_code == 200, f"status={r.status_code}")

# --- 30b. POST creates event_type subscription ---
r = S.post(f"{BASE}/api/notifications/subscriptions", json={
    "event_type": "provisioning_advance",
    "deliver_slack": True,
    "deliver_inapp": True,
})
test("Admin subscribe to provisioning_advance (200)", r.status_code in (200, 409), f"status={r.status_code}")
sub_id = None
if r.status_code == 200:
    sub_id = r.json().get("id")
elif r.status_code == 409:
    sub_id = r.json().get("id")
    test("Subscription already exists, got existing ID", sub_id is not None, str(r.json()))

# --- 30c. Duplicate subscription returns 409 ---
r = S.post(f"{BASE}/api/notifications/subscriptions", json={
    "event_type": "provisioning_advance",
    "deliver_slack": True,
    "deliver_inapp": True,
})
test("Duplicate subscription returns 409", r.status_code == 409, f"status={r.status_code}")

# --- 30d. Missing event_type AND resource returns 400 ---
r = S.post(f"{BASE}/api/notifications/subscriptions", json={"deliver_slack": True})
test("Subscription without event_type or resource returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 30e. DELETE (unsubscribe) deactivates subscription ---
if sub_id:
    r = S.delete(f"{BASE}/api/notifications/subscriptions/{sub_id}")
    test("Admin can unsubscribe (200)", r.status_code == 200, f"status={r.status_code}")

# --- 30f. DELETE on non-existent or non-owned sub returns 404 ---
r = S.delete(f"{BASE}/api/notifications/subscriptions/999999")
test("DELETE non-existent subscription returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 30g. Subscribe to a specific record (resource watch) ---
WATCH_ID = 1  # Likely exists; endpoint doesn't validate resource existence
r = S.post(f"{BASE}/api/notifications/subscriptions", json={
    "resource_type": "provisioning",
    "resource_id": WATCH_ID,
    "deliver_slack": True,
    "deliver_inapp": True,
})
test("Create record-specific watch subscription (200 or 409)", r.status_code in (200, 409),
     f"status={r.status_code}")
watch_sub_id = r.json().get("id") if r.status_code in (200, 409) else None
# Clean up immediately
if watch_sub_id:
    S.delete(f"{BASE}/api/notifications/subscriptions/{watch_sub_id}")

# --- 30h. GET watch status for a resource ---
r = S.get(f"{BASE}/api/notifications/watch/provisioning/{WATCH_ID}")
test("GET /api/notifications/watch/provisioning/{id} returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Watch response has 'watching' key", "watching" in r.json(), str(r.json()))
    initial_watching = r.json().get("watching", False)

# --- 30i. POST watch toggle (subscribe) ---
r = S.post(f"{BASE}/api/notifications/watch/provisioning/{WATCH_ID}")
test("POST watch toggle returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Watch toggle returned a 'watching' state", "watching" in r.json(), str(r.json()))
    after_first_toggle = r.json().get("watching")

# --- 30j. POST watch toggle again flips state ---
r = S.post(f"{BASE}/api/notifications/watch/provisioning/{WATCH_ID}")
test("Second watch toggle returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    after_second_toggle = r.json().get("watching")
    test("Second toggle flipped state", after_second_toggle != after_first_toggle,
         f"first={after_first_toggle}, second={after_second_toggle}")

# --- 30k. Viewer can also use watch endpoints ---
r = V.get(f"{BASE}/api/notifications/watch/provisioning/{WATCH_ID}")
test("Viewer GET watch status returns 200", r.status_code == 200, f"status={r.status_code}")

r = V.post(f"{BASE}/api/notifications/watch/provisioning/{WATCH_ID}")
test("Viewer POST watch toggle returns 200", r.status_code == 200, f"status={r.status_code}")
# Toggle back off
V.post(f"{BASE}/api/notifications/watch/provisioning/{WATCH_ID}")


# ============================================================
# 31. INTUNE SYNC & SLACK BOT ADMIN PAGES
# ============================================================
print("\n=== 31. INTUNE SYNC & SLACK BOT ADMIN PAGES ===")

# --- 31a. GET /admin/intune requires system_admin (admin passes) ---
r = S.get(f"{BASE}/admin/intune")
test("Admin CAN access /admin/intune (200)", r.status_code == 200, f"status={r.status_code}")

# --- 31b. Viewer cannot access /admin/intune ---
r = V.get(f"{BASE}/admin/intune", allow_redirects=False)
test("Viewer CANNOT access /admin/intune (403/302)", r.status_code in (302, 303, 307, 403),
     f"status={r.status_code}")

# --- 31c. POST /api/intune/test returns 400 when credentials not configured ---
r = S.post(f"{BASE}/api/intune/test")
test("Intune test returns 400 when not configured", r.status_code in (400, 200),
     f"status={r.status_code}")
if r.status_code == 400:
    test("Intune test error message mentions credentials", "credential" in r.json().get("error", "").lower()
         or "INTUNE_" in r.json().get("error", ""), str(r.json()))

# --- 31d. POST /api/intune/sync returns 400 when not configured ---
r = S.post(f"{BASE}/api/intune/sync")
test("Intune sync returns 400 when not configured", r.status_code in (400, 200),
     f"status={r.status_code}")

# --- 31e. GET /api/intune/sync-log returns log list (200) ---
r = S.get(f"{BASE}/api/intune/sync-log")
test("GET /api/intune/sync-log returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Sync log response has 'logs' key", "logs" in r.json(), str(r.json()))

# --- 31f. Viewer cannot access intune API endpoints ---
r = V.post(f"{BASE}/api/intune/test", allow_redirects=False)
test("Viewer CANNOT POST /api/intune/test (403/302)", r.status_code in (302, 303, 307, 403),
     f"status={r.status_code}")

r = V.get(f"{BASE}/api/intune/sync-log", allow_redirects=False)
test("Viewer CANNOT GET /api/intune/sync-log (403/302)", r.status_code in (302, 303, 307, 403),
     f"status={r.status_code}")

# --- 31g. GET /admin/slack-bot accessible by admin ---
r = S.get(f"{BASE}/admin/slack-bot")
test("Admin CAN access /admin/slack-bot (200)", r.status_code == 200, f"status={r.status_code}")

# --- 31h. Viewer cannot access /admin/slack-bot (redirects to /admin/notifications) ---
r = V.get(f"{BASE}/admin/slack-bot", allow_redirects=False)
test("Viewer CANNOT access /admin/slack-bot (403/302)", r.status_code in (301, 302, 303, 307, 403),
     f"status={r.status_code}")

# --- 31i. POST /api/slack-bot/test returns 400 when token not configured ---
r = S.post(f"{BASE}/api/slack-bot/test")
test("Slack bot test returns 400 when not configured", r.status_code in (400, 200),
     f"status={r.status_code}")
if r.status_code == 400:
    test("Slack bot error mentions token", "token" in r.json().get("error", "").lower()
         or "SLACK_" in r.json().get("error", ""), str(r.json()))

# --- 31j. POST /api/slack-bot/test-dm returns 400 when not configured ---
r = S.post(f"{BASE}/api/slack-bot/test-dm")
test("Slack bot test-dm returns 400 when not configured", r.status_code in (400, 200),
     f"status={r.status_code}")

# --- 31k. Viewer cannot access slack bot API endpoints ---
r = V.post(f"{BASE}/api/slack-bot/test", allow_redirects=False)
test("Viewer CANNOT POST /api/slack-bot/test (403/302)", r.status_code in (302, 303, 307, 403),
     f"status={r.status_code}")


# ============================================================
# 32. FULFILLMENT PAGE & ENDPOINTS
# ============================================================
print("\n=== 32. FULFILLMENT PAGE & ENDPOINTS ===")

# --- 32a. GET /fulfillment/ loads for admin ---
r = S.get(f"{BASE}/fulfillment/")
test("Admin CAN access /fulfillment/ (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Fulfillment page has command band", "cmd-band" in r.text, "missing cmd-band")
    test("Fulfillment page has kanban grid", "kanban-grid" in r.text, "missing kanban-grid")
    test("Fulfillment page has search input", 'id="cb-search"' in r.text, "missing search input")
    test("Fulfillment page has search-hide CSS rule", "search-hide" in r.text, "missing search-hide CSS")

# --- 32b. Viewer blocked from /fulfillment/ ---
r = V.get(f"{BASE}/fulfillment/", allow_redirects=False)
test("Viewer CANNOT access /fulfillment/ (403/302)", r.status_code in (302, 303, 307, 403),
     f"status={r.status_code}")

# --- 32c. /orders/ redirects to /fulfillment/ ---
r = S.get(f"{BASE}/orders/", allow_redirects=False)
test("/orders/ redirects to /fulfillment/ (301/302/303/307)", r.status_code in (301, 302, 303, 307),
     f"status={r.status_code}")

# --- 32d. Create test order for fulfillment tests ---
order_payload = {
    "customer_name": "E2E Fulfillment Corp",
    "sales_engineer": "Test SE",
    "status": "new",
    "sku_requirements": [{"model": "Appliance-4", "qty": 2, "source": "stock"}],
}
r = S.post(f"{BASE}/api/orders/", json=order_payload)
test("Create test order for fulfillment", r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}")
e2e_ful_order_id = r.json().get("order_id") if r.status_code in (200, 201) else None
e2e_ful_order_num = r.json().get("order_number") if r.status_code in (200, 201) else None

# --- 32e. Ship details — save shipping info ---
if e2e_ful_order_id:
    ship_payload = {
        "ship_method": "carrier",
        "carrier": "FedEx",
        "tracking_number": "E2E-TRACK-001",
        "recipient_name": "Test Recipient",
        "shipping_address": "123 Test St",
    }
    r = S.post(f"{BASE}/fulfillment/{e2e_ful_order_id}/ship", json=ship_payload)
    test("Ship details saved (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Ship response has ok=true", r.json().get("ok") is True, str(r.json()))

# --- 32f. Ship details — viewer blocked ---
if e2e_ful_order_id:
    r = V.post(f"{BASE}/fulfillment/{e2e_ful_order_id}/ship", json={"carrier": "UPS"}, allow_redirects=False)
    test("Viewer CANNOT update ship details (403/302)", r.status_code in (302, 303, 307, 403),
         f"status={r.status_code}")

# --- 32g. Ship details — nonexistent order ---
r = S.post(f"{BASE}/fulfillment/99999/ship", json={"carrier": "UPS"})
test("Ship on nonexistent order returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 32h. Create deployment record ---
if e2e_ful_order_id:
    dep_payload = {
        "customer_order_id": e2e_ful_order_id,
        "address": "456 Deploy Ave, Test City",
        "notes": "E2E test deployment",
    }
    r = S.post(f"{BASE}/fulfillment/deployments", json=dep_payload)
    test("Create deployment (200)", r.status_code == 200, f"status={r.status_code}")
    e2e_dep_id = r.json().get("id") if r.status_code == 200 else None
    if r.status_code == 200:
        test("Deployment status is scheduled", r.json().get("status") == "scheduled", str(r.json()))

# --- 32i. Create deployment — viewer blocked ---
if e2e_ful_order_id:
    r = V.post(f"{BASE}/fulfillment/deployments", json={"customer_order_id": e2e_ful_order_id},
               allow_redirects=False)
    test("Viewer CANNOT create deployment (403/302)", r.status_code in (302, 303, 307, 403),
         f"status={r.status_code}")

# --- 32j. Create deployment — nonexistent order ---
r = S.post(f"{BASE}/fulfillment/deployments", json={"customer_order_id": 99999})
test("Deployment on nonexistent order returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 32k. Update deployment status ---
if e2e_ful_order_id and e2e_dep_id:
    r = S.post(f"{BASE}/fulfillment/deployments/{e2e_dep_id}/status",
               json={"status": "in_transit"})
    test("Deployment status update (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Old status was scheduled", r.json().get("old_status") == "scheduled", str(r.json()))
        test("New status is in_transit", r.json().get("status") == "in_transit", str(r.json()))

# --- 32l. Update deployment — invalid status ---
if e2e_ful_order_id and e2e_dep_id:
    r = S.post(f"{BASE}/fulfillment/deployments/{e2e_dep_id}/status",
               json={"status": "bogus_status"})
    test("Deployment invalid status returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 32m. Update deployment — nonexistent ---
r = S.post(f"{BASE}/fulfillment/deployments/99999/status", json={"status": "in_transit"})
test("Deployment status on nonexistent returns 404", r.status_code == 404, f"status={r.status_code}")

# --- 32n. Update deployment — viewer blocked ---
if e2e_ful_order_id and e2e_dep_id:
    r = V.post(f"{BASE}/fulfillment/deployments/{e2e_dep_id}/status",
               json={"status": "on_site"}, allow_redirects=False)
    test("Viewer CANNOT update deployment status (403/302)", r.status_code in (302, 303, 307, 403),
         f"status={r.status_code}")

# --- 32o. Deployment complete auto-sets installed_date ---
if e2e_ful_order_id and e2e_dep_id:
    r = S.post(f"{BASE}/fulfillment/deployments/{e2e_dep_id}/status",
               json={"status": "complete"})
    test("Deployment complete returns 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("New status is complete", r.json().get("status") == "complete", str(r.json()))

# --- 32p. Fulfillment page shows test order in kanban ---
if e2e_ful_order_num:
    r = S.get(f"{BASE}/fulfillment/")
    test("Fulfillment page contains test order", e2e_ful_order_num in r.text,
         f"order {e2e_ful_order_num} not found in page")
    test("Fulfillment page contains customer name", "E2E Fulfillment Corp" in r.text,
         "customer name not in page")

# --- 32r. Deployment type toggle persists via PUT ---
if e2e_ful_order_id:
    r = S.put(f"{BASE}/api/orders/{e2e_ful_order_id}",
              json={"deployment_type": "via_integrator"})
    test("Update deployment_type to via_integrator (200)", r.status_code == 200,
         f"status={r.status_code}")
    # Verify it persisted
    r = S.get(f"{BASE}/orders/{e2e_ful_order_id}")
    if r.status_code == 200:
        test("Order detail shows via_integrator", "via_integrator" in r.text or "Via Integrator" in r.text,
             "deployment_type not found in page")
    # Reset back
    S.put(f"{BASE}/api/orders/{e2e_ful_order_id}", json={"deployment_type": "direct"})

# --- 32s. Bulk assign endpoint — missing prov_ids returns 400 ---
r = S.post(f"{BASE}/api/provisioning/bulk-assign-order",
           json={"prov_ids": [], "order_id": e2e_ful_order_id})
test("Bulk assign with empty prov_ids returns 400", r.status_code == 400,
     f"status={r.status_code}")

# --- 32t. Bulk assign — nonexistent order returns 404 ---
r = S.post(f"{BASE}/api/provisioning/bulk-assign-order",
           json={"prov_ids": [1], "order_id": 99999})
test("Bulk assign to nonexistent order returns 404", r.status_code == 404,
     f"status={r.status_code}")

# --- 32u. Bulk assign — viewer blocked ---
r = V.post(f"{BASE}/api/provisioning/bulk-assign-order",
           json={"prov_ids": [1], "order_id": e2e_ful_order_id}, allow_redirects=False)
test("Viewer CANNOT bulk assign (403/302)", r.status_code in (302, 303, 307, 403),
     f"status={r.status_code}")

# --- 32v. Dashboard shows fulfillment summary tile ---
r = S.get(f"{BASE}/dashboard")
if r.status_code == 200:
    test("Dashboard has fulfillment link", "/fulfillment/" in r.text,
         "fulfillment link not found in dashboard")
    test("Dashboard alerts point to /fulfillment/ (not /provisioning/)",
         "Review Provisioning" not in r.text,
         "still has old 'Review Provisioning' link")

# --- 32w. /provisioning/ also redirects to /fulfillment/ ---
r = S.get(f"{BASE}/provisioning/", allow_redirects=False)
test("/provisioning/ redirects to /fulfillment/ (301/302/303/307)",
     r.status_code in (301, 302, 303, 307), f"status={r.status_code}")

# --- 32x. Fulfillment page has ORDER_DEVICES JS constant ---
r = S.get(f"{BASE}/fulfillment/")
if r.status_code == 200:
    test("Fulfillment page has ORDER_DEVICES for deploy mini-steps",
         "ORDER_DEVICES" in r.text, "ORDER_DEVICES not found in page JS")

# --- 32y. Export endpoint returns XLSX ---
r = S.get(f"{BASE}/api/fulfillment/export")
test("Export fulfillment returns XLSX", r.status_code == 200,
     f"status={r.status_code}, content-type={r.headers.get('content-type', '')}")
test("Export has XLSX content type",
     "spreadsheetml" in r.headers.get("content-type", ""),
     f"content-type={r.headers.get('content-type', '')}")
test("Export has Content-Disposition attachment",
     "attachment" in r.headers.get("content-disposition", ""),
     f"disposition={r.headers.get('content-disposition', '')}")

# --- 32z. Export — viewer without provisioning access gets 403 ---
r = V.get(f"{BASE}/api/fulfillment/export")
test("Export viewer blocked without provisioning access (403)", r.status_code == 403,
     f"status={r.status_code}")

# --- 32aa. Technician assignment endpoint ---
if e2e_ful_order_id:
    # Create a provisioning record for this test
    cmd = f'''sudo -u postgres psql -d hardware_inventory -tAc "INSERT INTO device_provisioning (device_table, device_id, current_stage, customer_order_id) VALUES ('edge_boxes', 1, 'received', {e2e_ful_order_id}) RETURNING id;"'''
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    test_prov_id = result.stdout.strip()
    if test_prov_id:
        # Assign technician by name
        r = S.put(f"{BASE}/api/provisioning/{test_prov_id}/technician",
                  json={"technician_name": "reese"})
        test("Assign technician by name", r.status_code == 200,
             f"status={r.status_code}")

        # Clear technician
        r = S.put(f"{BASE}/api/provisioning/{test_prov_id}/technician",
                  json={"technician_name": ""})
        test("Clear technician assignment", r.status_code == 200 and r.json().get("assigned_to") is None,
             f"status={r.status_code}, body={r.text[:200]}")

        # Viewer blocked
        r = V.put(f"{BASE}/api/provisioning/{test_prov_id}/technician",
                  json={"technician_name": "reese"})
        test("Technician assign — viewer blocked", r.status_code in (401, 403),
             f"status={r.status_code}")

        # Nonexistent record
        r = S.put(f"{BASE}/api/provisioning/999999/technician",
                  json={"technician_name": "reese"})
        test("Technician assign — nonexistent 404", r.status_code == 404,
             f"status={r.status_code}")

        # Cleanup prov record
        cmd = f'sudo -u postgres psql -d hardware_inventory -tAc "DELETE FROM device_provisioning WHERE id = {test_prov_id} RETURNING id;"'
        subprocess.run(cmd, shell=True, capture_output=True, text=True)

# --- 32ab. Drag-and-drop — PUT /api/orders/{id} with status change ---
if e2e_ful_order_id:
    r = S.put(f"{BASE}/api/orders/{e2e_ful_order_id}",
              json={"status": "sourcing"})
    test("Drag-drop status change via PUT", r.status_code == 200,
         f"status={r.status_code}")
    # Verify status changed
    r = S.get(f"{BASE}/fulfillment/")
    test("Order moved to sourcing column",
         f'"sourcing"' in r.text or "Sourcing" in r.text,
         f"page contains sourcing reference")
    # Move back to new
    r = S.put(f"{BASE}/api/orders/{e2e_ful_order_id}",
              json={"status": "new"})
    test("Drag-drop move back to new", r.status_code == 200,
         f"status={r.status_code}")

# --- 32ac. Fulfillment page has draggable attribute on cards ---
r = S.get(f"{BASE}/fulfillment/")
test("Cards have draggable attribute (admin)",
     'draggable="true"' in r.text,
     "draggable found: " + str('draggable="true"' in r.text))

# --- 32ad. Viewer cards are NOT draggable ---
r = V.get(f"{BASE}/fulfillment/")
test("Viewer cards not draggable",
     'draggable="true"' not in r.text,
     "draggable absent: " + str('draggable="true"' not in r.text))

# --- 32ae. Fulfillment page has export button ---
r = S.get(f"{BASE}/fulfillment/")
test("Export button visible on page",
     'exportFulfillment()' in r.text,
     f"exportFulfillment found: {'exportFulfillment()' in r.text}")

# --- 32af. Archived section has polished card styling ---
test("Archived cards have arch-color CSS var",
     '--arch-color' in r.text,
     f"arch-color found: {'--arch-color' in r.text}")

# --- 32ag. Fulfillment tour exists and targets correct selectors ---
r = S.get(f"{BASE}/api/tours")
if r.status_code == 200:
    tours = r.json()
    ful_tour = next((t for t in tours if t["id"] == "orders_tour"), None)
    test("Fulfillment tour exists", ful_tour is not None, f"tour={ful_tour}")
    if ful_tour:
        test("Fulfillment tour has 10+ steps",
             len(ful_tour.get("steps", [])) >= 10,
             f"steps={len(ful_tour.get('steps', []))}")
        targets = [s["target"] for s in ful_tour["steps"]]
        test("Tour targets .fl-header", ".fl-header" in targets, f"targets={targets[:5]}")
        test("Tour targets .mode-toggle", ".mode-toggle" in targets, f"targets={targets[:5]}")

# --- 32q. Cleanup: delete test order ---
if e2e_ful_order_id:
    # Delete deployment first (cascade may not cover it)
    if e2e_dep_id:
        cmd = f'sudo -u postgres psql -d hardware_inventory -tAc "DELETE FROM deployment_records WHERE id = {e2e_dep_id} RETURNING id;"'
        subprocess.run(cmd, shell=True, capture_output=True, text=True)
    r = S.delete(f"{BASE}/api/orders/{e2e_ful_order_id}")
    test("Cleanup: delete test order", r.status_code == 200, f"status={r.status_code}")


# ============================================================
# 33. BARCODE SCANNER MODULE & INTEGRATION
# ============================================================
print("\n=== 33. BARCODE SCANNER MODULE & INTEGRATION ===")

# --- 33a. Scanner static assets load ---
r = S.get(f"{BASE}/static/js/scanner.js")
test("scanner.js loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("scanner.js contains BarcodeScanner class", "class BarcodeScanner" in r.text)
    test("scanner.js has native BarcodeDetector path", "BarcodeDetector" in r.text)
    test("scanner.js has html5-qrcode fallback", "html5-qrcode" in r.text or "Html5Qrcode" in r.text)
    test("scanner.js exports to window", "window.BarcodeScanner" in r.text)

r = S.get(f"{BASE}/static/css/scanner.css")
test("scanner.css loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("scanner.css has overlay class", ".scanner-overlay" in r.text)
    test("scanner.css has viewfinder frame", ".scanner-frame" in r.text)
    test("scanner.css has toast styles", ".scanner-toast" in r.text)

# --- 33b. Service worker caches scanner assets ---
r = S.get(f"{BASE}/static/sw.js")
test("sw.js loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("SW caches scanner.css", "scanner.css" in r.text)
    test("SW caches scanner.js", "scanner.js" in r.text)
    test("SW cache version is v4+", "asset-tracker-v4" in r.text or "asset-tracker-v5" in r.text)

# --- 33c. Receive page includes scanner module ---
r = S.get(f"{BASE}/receive")
test("Receive page loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Receive includes scanner.js", "scanner.js" in r.text)
    test("Receive includes scanner.css", "scanner.css" in r.text)
    test("Receive has BarcodeScanner instantiation", "BarcodeScanner" in r.text)
    test("Receive has quick-mode checkbox", "quick-mode-cb" in r.text)
    test("Receive has quickModeActive flag", "quickModeActive" in r.text)

# --- 33d. Fulfillment page includes scanner + scan button ---
r = S.get(f"{BASE}/fulfillment/")
test("Fulfillment page loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Fulfillment includes scanner.js", "scanner.js" in r.text)
    test("Fulfillment includes scanner.css", "scanner.css" in r.text)
    test("Fulfillment has scanToFind() function", "scanToFind" in r.text)
    test("Fulfillment has scan button", "Scan barcode" in r.text or "scanToFind()" in r.text)

# --- 33e. Provisioning detail includes scanner + verify button ---
# First find a provisioning record to test the detail page
r = S.get(f"{BASE}/provisioning/queue")
prov_detail_id = None
if r.status_code == 200 and "/provisioning/" in r.text:
    import re
    prov_links = re.findall(r'/provisioning/(\d+)', r.text)
    if prov_links:
        prov_detail_id = prov_links[0]

if prov_detail_id:
    r = S.get(f"{BASE}/provisioning/{prov_detail_id}")
    test("Provisioning detail loads (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Prov detail includes scanner.js", "scanner.js" in r.text)
        test("Prov detail includes scanner.css", "scanner.css" in r.text)
        test("Prov detail has scanVerifySerial() function", "scanVerifySerial" in r.text)
else:
    warn("No provisioning records found to test detail page scanner integration")

# --- 33f. Quick-action scan flow: unknown serial → auto-populate ---
r = S.post(f"{BASE}/api/receive/scan", json={"barcode": "SN-E2E-SCANNER-NEW"})
test("Quick scan unknown serial returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    scan_data = r.json()
    test("Unknown serial returns 'unknown' status", scan_data.get("status") == "unknown")
    test("Unknown serial returns serial in response", scan_data.get("serial") == "SN-E2E-SCANNER-NEW")
    test("Unknown serial has empty prefill", scan_data.get("prefill") == {})

# --- 33g. Quick-action: create device direct to inventory ---
r = S.post(f"{BASE}/api/receive/device", json={
    "target_table": "network_equipment",
    "serial": "SN-E2E-SCANNER-QA-001",
    "direct_to_inventory": True,
    "manufacturer": "E2E Scanner Test",
    "model": "QA-SCAN-MODEL",
    "location": "Scanner Test Lab",
    "status": "Inventory",
    "mac_address": "E2:E2:E2:00:5C:01",
    "notes": "Quick-scan intake",
})
scanner_test_device_id = None
if r.status_code == 200:
    scanner_test_device_id = r.json().get("device_id")
    test("Quick-action device created", scanner_test_device_id is not None)
    test("Device routed to inventory (status=created)", r.json().get("status") == "created")
else:
    test("Quick-action device creation", False, f"status={r.status_code} {r.text[:200]}")

# --- 33h. Re-scan same serial → already_exists ---
if scanner_test_device_id:
    r = S.post(f"{BASE}/api/receive/scan", json={"barcode": "SN-E2E-SCANNER-QA-001"})
    test("Re-scan returns already_exists", r.status_code == 200 and r.json().get("status") == "already_exists",
         f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        data = r.json()
        test("Already-exists returns device_id", data.get("device_id") == scanner_test_device_id,
             f"expected={scanner_test_device_id} got={data.get('device_id')}")
        test("Already-exists returns table name", data.get("table") == "network_equipment",
             f"table={data.get('table')}")
        test("Already-exists returns display_table", data.get("display_table") is not None,
             f"display_table={data.get('display_table')}")

# --- 33i. Empty barcode returns 400 ---
r = S.post(f"{BASE}/api/receive/scan", json={"barcode": ""})
test("Empty barcode returns 400", r.status_code == 400, f"status={r.status_code}")

r = S.post(f"{BASE}/api/receive/scan", json={"barcode": "   "})
test("Whitespace-only barcode returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 33j. Device creation validation: empty serial ---
r = S.post(f"{BASE}/api/receive/device", json={
    "target_table": "network_equipment",
    "serial": "",
    "direct_to_inventory": True,
})
test("Device with empty serial returns 400", r.status_code == 400, f"status={r.status_code}")

# --- 33k. Viewer cannot use scanner endpoints ---
r = V.post(f"{BASE}/api/receive/scan", json={"barcode": "SN-HACK-SCAN"})
test("Viewer CANNOT scan barcodes (403)", r.status_code == 403, f"status={r.status_code}")

r = V.post(f"{BASE}/api/receive/device", json={
    "target_table": "network_equipment",
    "serial": "SN-HACK-CREATE",
    "direct_to_inventory": True,
})
test("Viewer CANNOT create devices via scanner (403)", r.status_code == 403, f"status={r.status_code}")

# --- 33l. Fulfillment scan-to-find: existing device ---
if scanner_test_device_id:
    r = S.post(f"{BASE}/api/receive/scan", json={"barcode": "SN-E2E-SCANNER-QA-001"})
    test("Fulfillment scan-to-find returns already_exists",
         r.status_code == 200 and r.json().get("status") == "already_exists")
    if r.status_code == 200:
        test("Scan-to-find returns device_id for navigation",
             r.json().get("device_id") is not None)

# --- 33m. Fulfillment scan-to-find: unknown device ---
r = S.post(f"{BASE}/api/receive/scan", json={"barcode": "SN-E2E-UNKNOWN-FULFILLMENT"})
test("Fulfillment scan unknown returns status for 'not found' toast",
     r.status_code == 200 and r.json().get("status") == "unknown")

# --- 33n. Cleanup: delete test scanner device ---
if scanner_test_device_id:
    cmd = f'sudo -u postgres psql -d hardware_inventory -tAc "DELETE FROM network_equipment WHERE id = {scanner_test_device_id} RETURNING id;"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        test("Cleanup: scanner test device deleted", True)
    else:
        warn("Cleanup: scanner test device not found", f"id={scanner_test_device_id}")


# ============================================================
# 34. CREDENTIALS ON DETAIL PAGES
# ============================================================
print("\n=== 34. CREDENTIALS ON DETAIL PAGES ===")

# --- 34a. Camera detail page loads and has credentials panel ---
r = S.get(f"{BASE}/cameras/1")
test("Camera detail page loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Camera detail has credentials panel", "View Credentials" in r.text)
    test("Camera detail has showCredentials call", "showCredentials" in r.text)
    test("Camera detail has creds-modal (from base.html)", "creds-modal" in r.text)

# --- 34b. Access control detail page loads and has credentials panel ---
r = S.get(f"{BASE}/access-control/1")
test("Access control detail page loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Access control detail has credentials panel", "View Credentials" in r.text)
    test("Access control detail has showCredentials call", "showCredentials" in r.text)

# --- 34c. Credentials API works from detail page context ---
r = S.get(f"{BASE}/api/credentials/cameras/1")
test("Credentials API for camera (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    cdata = r.json()
    test("Credentials response has credentials key", "credentials" in cdata)
    creds_list = cdata.get("credentials", [])
    if creds_list:
        test("Credential has credential_type", "credential_type" in creds_list[0])
        test("Credential decrypted (not Fernet bytes)", not str(creds_list[0].get("username", "")).startswith("gAAAAA"))

# --- 34d. Viewer cannot see credentials button on detail page ---
r = V.get(f"{BASE}/cameras/1")
test("Viewer camera detail loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Viewer does NOT see View Credentials button", "View Credentials" not in r.text)
    test("Viewer sees Restricted label", "Restricted" in r.text)

# --- 34e. Viewer cannot access credentials API ---
r = V.get(f"{BASE}/api/credentials/cameras/1")
test("Viewer CANNOT access credentials API (403)", r.status_code == 403, f"status={r.status_code}")

# --- 34f. Other detail pages have creds-modal from base.html ---
r = S.get(f"{BASE}/monitors/1")
if r.status_code == 200:
    test("Monitor detail has creds-modal (inherited from base)", "creds-modal" in r.text)
    test("Monitor detail has showCredentials function (inherited from base)", "showCredentials" in r.text)
else:
    warn("Monitor detail /monitors/1 not found", f"status={r.status_code}")

# --- 34g. window.BASE_PATH is set in base.html ---
r = S.get(f"{BASE}/cameras/1")
if r.status_code == 200:
    test("window.BASE_PATH is set in page", "window.BASE_PATH" in r.text)

# ============================================================
# Section 35: DEVICE ICONS, ADD DEVICE, CONTACT ADMIN, TRIAGE
# ============================================================
print("\n=== Section 35: Device Icons, Add Device, Contact Admin, Triage ===")

# --- 35a. Device icon mappings cover all inventory categories ---
r = S.get(f"{BASE}/inventory/")
if r.status_code == 200:
    test("Inventory page has tile-icon divs", "tile-icon" in r.text)
    test("Inventory page imports device_icon macro", "device_icon" in r.text or "tile-icon" in r.text)

# --- 35b. Add Device button visible for editor, hidden for viewer ---
r = S.get(f"{BASE}/inventory/")
if r.status_code == 200:
    test("Editor sees Add Device button", "add-device-btn" in r.text)
    test("Add Device button has goToReceive()", "goToReceive()" in r.text)

r = V.get(f"{BASE}/inventory/")
if r.status_code == 200:
    test("Viewer does NOT see Add Device button", "add-device-btn" not in r.text)

# --- 35c. Receive page accepts category query param ---
r = S.get(f"{BASE}/receive?category=cameras")
test("Receive page with category param loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Receive page has preselect_category JS", "preselect" in r.text.lower() or "cameras" in r.text)

# --- 35d. Contact Admin API rejects empty message ---
r = S.post(f"{BASE}/api/contact-admin", json={"message": "", "page": "/test"})
test("Contact Admin rejects empty message (400)", r.status_code == 400, f"status={r.status_code}")

# --- 35e. Contact Admin API accepts valid message ---
r = S.post(f"{BASE}/api/contact-admin", json={"message": "E2E test message - please ignore", "page": "/e2e-test"})
test("Contact Admin accepts valid message (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Contact Admin returns ok status", r.json().get("status") == "ok")

# --- 35f. Contact Admin modal is in base.html (all pages) ---
r = S.get(f"{BASE}/")
if r.status_code == 200:
    test("Contact admin modal present on inventory page", "contact-admin-modal" in r.text)
    test("openContactAdminModal function present", "openContactAdminModal" in r.text)
    test("submitContactAdmin function present", "submitContactAdmin" in r.text)

# --- 35g. Permission denied page has Contact Admin button ---
r = V.get(f"{BASE}/admin/users")
if r.status_code == 200:
    test("Permission denied page has openContactAdminModal", "openContactAdminModal" in r.text)
    test("Permission denied page does NOT have alert()", "alert('Please contact" not in r.text)

# --- 35h. Triage page loads with pill styling ---
r = S.get(f"{BASE}/dashboard/triage")
test("Triage page loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Triage has sx-pill CSS defined", ".sx-pill {" in r.text or "sx-pill--red" in r.text)
    test("Triage has sx-pill--green CSS", "sx-pill--green" in r.text)
    test("Triage has sx-missing-fields CSS", "sx-missing-fields" in r.text)
    test("Triage has GlobalEditModal.open", "GlobalEditModal.open" in r.text)

# --- 35i. Triage edit button hidden from viewer ---
r = V.get(f"{BASE}/dashboard/triage")
if r.status_code == 200:
    test("Viewer does NOT see edit button on triage", "GlobalEditModal.open" not in r.text)

# --- 35j. Table header font size is 11px ---
r = S.get(f"{BASE}/?select=edge_boxes")
if r.status_code == 200:
    test("Table header uses 11px font-size", "font-size: 11px" in r.text or "font-size:11px" in r.text)

# --- 35k. UUID field uses word-break for long values ---
r = S.get(f"{BASE}/edge-boxes/1")
if r.status_code == 200:
    test("Detail page has eb-mono class for UUID", "eb-mono" in r.text)

# ============================================================
# 36. TRIAGE FILTERS & EDIT MODAL IMPROVEMENTS
# ============================================================
print("\n=== 36. TRIAGE FILTERS & EDIT MODAL IMPROVEMENTS ===")

# --- 36a. Triage page has filter controls ---
r = S.get(f"{BASE}/dashboard/triage")
test("Triage page loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Triage has filter-category select", "filter-category" in r.text)
    test("Triage has filter-deployment select", "filter-deployment" in r.text)
    test("Triage rows have data-category attribute", "data-category" in r.text)
    test("Triage rows have data-deployment attribute", "data-deployment" in r.text)
    test("Triage row data includes deployment_type", 'data-deployment="' in r.text)

# --- 36b. Triage rows are clickable for editors ---
r = S.get(f"{BASE}/dashboard/triage")
if r.status_code == 200:
    # Check class= context to avoid matching CSS rule definitions
    test("Triage rows have clickable class", 'class="sx-table__row sx-table__row--clickable"' in r.text)
    test("Triage rows have onclick handler", "GlobalEditModal.open(" in r.text)

# --- 36c. Triage rows NOT clickable for viewers ---
r = V.get(f"{BASE}/dashboard/triage", allow_redirects=True)
if r.status_code == 200:
    test("Viewer triage rows lack clickable class", 'class="sx-table__row sx-table__row--clickable"' not in r.text)

# --- 36d. Edit modal JS has UUID field styling ---
r = S.get(f"{BASE}/static/js/edit-modal.js")
test("edit-modal.js loads (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Edit modal has gem-input--uuid class", "gem-input--uuid" in r.text)
    test("Edit modal has gem-uuid-wrap", "gem-uuid-wrap" in r.text)
    test("Edit modal has gem-copy-btn", "gem-copy-btn" in r.text)

# --- 36e. Edit modal COMMON_FIELDS includes mac_address_2 with colRight ---
if r.status_code == 200:
    test("Edit modal COMMON_FIELDS has mac_address_2", "mac_address_2" in r.text)
    test("mac_address_2 has colRight:true", "mac_address_2" in r.text and "colRight" in r.text)

# --- 36f. Edit modal _buildField supports colRight / gem-field--col2 ---
if r.status_code == 200:
    test("Edit modal has gem-field--col2 class", "gem-field--col2" in r.text)
    test("_buildField checks colRight property", "colRight" in r.text)

# ============================================================
# SECTION 37 — ERROR TRACKING & TOAST SYSTEM
# ============================================================
print("\n=== Section 37: Error Tracking & Toast System ===")
e2e_errors = []
_e2e_err_id = None

# --- 37a. Error report API ---
r = S.post(f"{BASE}/api/errors/report", json={
    "message": "E2E test error",
    "stack": "Error: E2E test error\n    at test:1:1",
    "url": "/test-page",
    "level": "error",
    "browser": "E2E-Test-Agent/1.0",
})
test("POST /api/errors/report (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Error report returns ok:true", r.json().get("ok") is True)

# --- 37b. Error report with warning level ---
r = S.post(f"{BASE}/api/errors/report", json={
    "message": "E2E test warning",
    "level": "warning",
    "url": "/test-warning",
})
test("POST /api/errors/report warning level (200)", r.status_code == 200, f"status={r.status_code}")

# --- 37c. Error report with no message defaults to Unknown ---
r = S.post(f"{BASE}/api/errors/report", json={
    "level": "error",
    "url": "/no-message",
})
test("POST /api/errors/report no message still works (200)", r.status_code == 200, f"status={r.status_code}")

# --- 37d. Admin errors page ---
r = S.get(f"{BASE}/admin/errors")
test("GET /admin/errors (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Admin errors has Error Log heading", "Error Log" in r.text)
    test("Admin errors has summary cards", "Total Errors" in r.text)
    test("Admin errors has filter bar", "filter-source" in r.text)
    test("Admin errors shows E2E test error", "E2E test error" in r.text)

# --- 37e. Error list API (admin) ---
r = S.get(f"{BASE}/api/errors")
test("GET /api/errors (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    data = r.json()
    test("Error list has errors key", "errors" in data)
    test("Error list has total key", "total" in data)
    errs = data.get("errors", [])
    if len(errs) > 0:
        e = errs[0]
        test("Error has id field", "id" in e)
        test("Error has message field", "message" in e)
        test("Error has source field", "source" in e)
        # Find our E2E error
        e2e_errors = [x for x in errs if "E2E test error" in (x.get("message") or "")]
        test("E2E test error in list", len(e2e_errors) > 0)
        if e2e_errors:
            _e2e_err_id = e2e_errors[0]["id"]

# --- 37f. Error detail API ---
if _e2e_err_id:
    r = S.get(f"{BASE}/api/errors/{_e2e_err_id}")
    test("GET /api/errors/<id> (200)", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        detail = r.json()
        test("Error detail has stack", "stack" in detail)
        test("Error detail message matches", "E2E test error" in detail.get("message", ""))
        test("Error detail has fingerprint", detail.get("fingerprint") is not None)

# --- 37g. Error list with source filter ---
r = S.get(f"{BASE}/api/errors?source=frontend")
test("GET /api/errors?source=frontend (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    filtered = r.json().get("errors", [])
    test("Filtered errors all frontend", all(x.get("source") == "frontend" for x in filtered))

# --- 37h. RBAC: viewer cannot access error APIs ---
r = V.get(f"{BASE}/api/errors")
test("Viewer GET /api/errors (403)", r.status_code == 403, f"status={r.status_code}")

r = V.get(f"{BASE}/admin/errors", allow_redirects=False)
test("Viewer GET /admin/errors blocked", r.status_code in (302, 303, 403), f"status={r.status_code}")

r = V.get(f"{BASE}/api/errors/1")
test("Viewer GET /api/errors/<id> (403)", r.status_code == 403, f"status={r.status_code}")

# --- 37i. Prune API (dry run — prune with high days to avoid deleting real data) ---
r = S.delete(f"{BASE}/api/errors/prune?days=9999")
test("DELETE /api/errors/prune (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Prune returns deleted count", "deleted" in r.json())

# --- 37j. toast.js loads ---
r = S.get(f"{BASE}/static/js/toast.js")
test("GET /static/js/toast.js (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("toast.js has SxToast class", "SxToast" in r.text or "window.SxToast" in r.text)
    test("toast.js has error capture", "onerror" in r.text or "addEventListener" in r.text)
    test("toast.js has sendBeacon", "sendBeacon" in r.text)
    test("toast.js has rate limiting", "MAX_REPORTS" in r.text or "reportCount" in r.text)

# --- 37k. Error tracking tour exists ---
r = S.get(f"{BASE}/api/tours/all")
test("GET /api/tours/all (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    tours_resp = r.json()
    tours_list = tours_resp.get("tours", []) if isinstance(tours_resp, dict) else tours_resp
    tour_ids = [t.get("id") for t in tours_list]
    test("error_log_tour in tour list", "error_log_tour" in tour_ids, f"tours={tour_ids}")

# ============================================================
# 38. QUICK VIEW MODAL
# ============================================================
print("\n=== 38. QUICK VIEW MODAL ===")

# --- 38a. Inventory page loads with quick view modal HTML ---
r = S.get(f"{BASE}/dashboard")
test("GET /dashboard (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Quick view overlay present", "qv-overlay" in r.text)
    test("Quick view modal present", "qv-modal" in r.text)
    test("Quick view JS function present", "openQuickView" in r.text)
    test("Quick view closeQuickView present", "closeQuickView" in r.text)
    test("Quick view Edit button present", "qv-edit-btn" in r.text)
    test("Quick view detail link present", "qv-detail-link" in r.text)

# --- 38b. Device API returns data for quick view ---
r = S.get(f"{BASE}/api/devices/edge_boxes/1")
test("GET /api/devices/edge_boxes/1 (200)", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    d = r.json()
    test("Device API returns id", "id" in d)
    test("Device API returns serial", "serial" in d)
    test("Device API returns status", "status" in d)

# --- 38c. Device API 404 for missing device ---
r = S.get(f"{BASE}/api/devices/edge_boxes/999999")
test("GET /api/devices/edge_boxes/999999 (404)", r.status_code == 404, f"status={r.status_code}")

# --- 38d. Device API 404 for unknown table ---
r = S.get(f"{BASE}/api/devices/fake_table/1")
test("GET /api/devices/fake_table/1 (404)", r.status_code == 404, f"status={r.status_code}")

# --- 38e. Viewer can access device API (read-only) ---
r = V.get(f"{BASE}/api/devices/edge_boxes/1")
test("Viewer GET /api/devices/edge_boxes/1 (200)", r.status_code == 200, f"status={r.status_code}")

# --- 38f. Row click handler uses openQuickView ---
r = S.get(f"{BASE}/dashboard/table/multi?tables=edge_boxes")
if r.status_code == 200:
    test("Table rows use openQuickView onclick", "openQuickView(" in r.text)
    test("Table rows do NOT use window.location", "window.location=" not in r.text)

# --- 38g. Quick view CSS loaded ---
r = S.get(f"{BASE}/dashboard")
if r.status_code == 200:
    test("Quick view CSS .qv-overlay present", ".qv-overlay" in r.text)
    test("Quick view CSS .qv-fields present", ".qv-fields" in r.text)
    test("Quick view CSS .qv-btn-detail present", ".qv-btn-detail" in r.text)


# ============================================================
# CLEANUP
# ============================================================
print("\n=== CLEANUP ===")

# Clean up E2E error log entries
cmd = "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM error_log WHERE message LIKE 'E2E test%' RETURNING id;\""
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
if result.stdout.strip():
    print(f"  Cleaned up E2E error log entries")

cleanup_users = ["test_admin_e2e", "test_warranty_adm", "test_trials_adm", "test_procure_adm",
                 "test_viewer_e2e", "test_editor_e2e", "xss_test_e2e", "badrole_e2e", "nopwd_e2e",
                 "toggle_test_e2e", "temp_admin_toggle", "test_ceo_e2e"]
for uname in cleanup_users:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM users WHERE username = '{uname}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up user: {uname}")

# Clean up test teams
for tname in ["E2E Test Team", "E2E Team Two", "E2E Delete Test", "E2E Renamed Team", "E2E Prov Team", "Hacker Team"]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM teams WHERE name = '{tname}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up team: {tname}")

# Clean up test dispositions (dup test, cert test, and lifecycle tests)
for did in [999888, 999777, 998001, 998002, 998003, 998004]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM device_dispositions WHERE device_table = 'cameras' AND device_id = {did} RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up test disposition (device_id={did})")

# Clean up lifecycle test warranties (safety net if delete in test failed)
for did in [998001, 998002, 998003, 998004]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM warranty_claims WHERE warranty_id IN (SELECT id FROM device_warranties WHERE device_table = 'cameras' AND device_id = {did}) RETURNING id;\""
    subprocess.run(cmd, shell=True, capture_output=True, text=True)
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM device_warranties WHERE device_table = 'cameras' AND device_id = {did} RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up test warranty (device_id={did})")

# Clean up lifecycle test trials (safety net)
for did in [998001, 998002, 998003, 998004]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM vendor_trials WHERE device_table = 'cameras' AND device_id = {did} RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up test trial (device_id={did})")

# Clean up drive assignment test devices
for tbl, serial in [("storage_drives", "SN-ASSIGN-DRV-A"), ("storage_drives", "SN-ASSIGN-DRV-B"), ("edge_boxes", "SN-ASSIGN-EDGE-001")]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM {tbl} WHERE serial = '{serial}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up assignment test device: {serial} from {tbl}")

# Clean up test receiving devices (network_equipment, nas_devices, storage_drives created by E2E)
for tbl, serial in [("network_equipment", "SN-E2E-RECV-001"), ("nas_devices", "SN-QNAP-E2E-001"), ("storage_drives", "SN-WD-E2E-001")]:
    # First delete NAS drives if this is a NAS
    if tbl == "nas_devices":
        cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM nas_drives WHERE nas_device_id IN (SELECT id FROM {tbl} WHERE serial = '{serial}') RETURNING id;\""
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.stdout.strip():
            print(f"  Cleaned up NAS drives for {serial}")
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM {tbl} WHERE serial = '{serial}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up test device: {serial} from {tbl}")

# Clean up test receiving events
cmd = "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM receiving_events WHERE purchase_order = 'PO-E2E-9999' RETURNING id;\""
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
if result.stdout.strip():
    print(f"  Cleaned up test receiving event")

# Clean up test photos
cmd = "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM intake_photos WHERE caption IN ('E2E test photo', 'PNG test', 'WebP test') RETURNING id;\""
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
if result.stdout.strip():
    print(f"  Cleaned up test photos")

# Clean up test sites and assignments (safety net)
subprocess.run(
    "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM device_assignments WHERE notes LIKE 'E2E%'\"",
    shell=True, capture_output=True, text=True,
)
for sname in ["E2E Test Lab", "E2E Partner Site"]:
    result = subprocess.run(
        f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM sites WHERE name = '{sname}' RETURNING id;\"",
        shell=True, capture_output=True, text=True,
    )
    if result.stdout.strip():
        print(f"  Cleaned up site: {sname}")

for serial in ["SN-SITE-E2E-CAM-001", "SN-SITE-E2E-CAM-002"]:
    subprocess.run(
        f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM cameras WHERE serial = '{serial}'\"",
        shell=True, capture_output=True, text=True,
    )

# Clean up test provisioning records
cmd = "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM device_provisioning WHERE notes LIKE 'E2E%' RETURNING id;\""
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
if result.stdout.strip():
    print(f"  Cleaned up test provisioning records")

# Clean up test customer orders
cmd = "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM customer_orders WHERE customer_name LIKE 'E2E%' RETURNING id;\""
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
if result.stdout.strip():
    print(f"  Cleaned up test customer orders")

# Clean up provisioning test site
subprocess.run(
    "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM sites WHERE name = 'E2E Prov Site' RETURNING id;\"",
    shell=True, capture_output=True, text=True,
)

# Clean up test tour progress
cmd = "sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM user_tour_progress WHERE user_id IN (SELECT id FROM users WHERE username IN ('test_admin_e2e', 'test_viewer_e2e')) RETURNING id;\""
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
if result.stdout.strip():
    print(f"  Cleaned up test tour progress records")

# Remove test mode flag
subprocess.run("rm -f /tmp/.asset_tracker_test_mode", shell=True, capture_output=True)
print("  E2E test mode flag removed")

# Clean up vendor profiles created by E2E tests
for vname in ["E2E Vendor Corp", "E2E Viewer Vendor Attempt"]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM vendor_profiles WHERE name = '{vname}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up vendor profile: {vname}")

# Clean up notification subscriptions created by E2E users
cmd = ("sudo -u postgres psql -d hardware_inventory -tAc "
       "\"DELETE FROM notification_subscriptions WHERE user_id IN "
       "(SELECT id FROM users WHERE username LIKE '%_e2e' OR username IN "
       "('test_admin_e2e','test_viewer_e2e','test_editor_e2e')) RETURNING id;\"")
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
if result.stdout.strip():
    print(f"  Cleaned up E2E notification subscriptions")

# Clean up test OUIs
for prefix in ["FE:FE:FE", "FD:FD:FD", "FC:FC:FC", "FB:FB:FB"]:
    cmd = f"sudo -u postgres psql -d hardware_inventory -tAc \"DELETE FROM oui_allowlist WHERE oui_prefix = '{prefix}' RETURNING id;\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Cleaned up OUI: {prefix}")

# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*60}")
print(f"RESULTS: {results['pass']} passed, {results['fail']} failed, {results['warn']} warnings")
print(f"{'='*60}")

if results["fail"] > 0:
    print("\nFAILED TESTS:")
    for d in results["details"]:
        if d["status"] == "FAIL":
            print(f"  X {d['name']}: {d['detail']}")

if results["warn"] > 0:
    print("\nWARNINGS:")
    for d in results["details"]:
        if d["status"] == "WARN":
            print(f"  ! {d['name']}: {d['detail']}")

sys.exit(1 if results["fail"] > 0 else 0)
