"""Fill an empty database with a made-up but realistic demo data set.

Every company, person, site, address and serial number here is invented.
The data goes in through the app's own HTTP routes (in-process, through
FastAPI's TestClient), so it passes the same validation, guards and audit
trail as a person using the app. Dates are relative to the day it runs, so
due dates, warranties and loans always look current.

Run against an EMPTY database (it refuses if any inventory item exists):
    python -m scripts.seed_demo
    docker compose exec app python -m scripts.seed_demo

Then sign in as  demo / harbor-lantern-quilt-42  (super admin). Other demo
users share the password orbit-cactus-meadow-4417 and must change it on
first sign-in.
"""

import io
import random
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.auth import hash_password, validate_password_strength  # noqa: E402
from app.database import SessionLocal, create_all_tables, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

DEMO_USER = "demo"
DEMO_PASSWORD = "harbor-lantern-quilt-42"
TEAM_PASSWORD = "orbit-cactus-meadow-4417"
TODAY = date.today()
rng = random.Random(20260929)


def d(days):
    """ISO date `days` from today (negative for the past)."""
    return (TODAY + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

class Seeder:
    def __init__(self, client):
        self.c = client
        self.counts = {}

    def _check(self, r, expect, what):
        if r.status_code not in expect:
            raise SystemExit(f"seed failed at {what}: HTTP {r.status_code} {r.text[:400]}")
        return r

    def post(self, path, what=None, expect=(200,), **kw):
        return self._check(self.c.post(path, **kw), expect, what or path)

    def put(self, path, what=None, expect=(200,), **kw):
        return self._check(self.c.put(path, **kw), expect, what or path)

    def get(self, path, what=None, expect=(200,), **kw):
        return self._check(self.c.get(path, **kw), expect, what or path)

    def bump(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n


def pdf_bytes(title, lines):
    """A one-page PDF with a title and some lines, for receipts and reports."""
    import pymupdf as fitz  # already an app dependency
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((56, 80), title, fontsize=18)
    y = 120
    for line in lines:
        page.insert_text((56, y), line, fontsize=11)
        y += 18
    page.insert_text((56, 740), "Demo document. All names and figures are fictional.", fontsize=8)
    out = doc.tobytes()
    doc.close()
    return out


def label_png(text_lines, color=(32, 96, 160)):
    """A shipping-label style PNG, for unit photos."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (900, 600), (238, 232, 220))
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 60, 840, 540], fill=(255, 255, 255), outline=color, width=8)
    draw.rectangle([60, 60, 840, 140], fill=color)
    y = 170
    for i, line in enumerate(text_lines):
        draw.text((100, y), line, fill=(20, 20, 20) if i else (255, 255, 255))
        y += 60
    for x in range(100, 800, 14):  # a fake barcode
        draw.rectangle([x, 440, x + rng.choice((3, 5, 7)), 510], fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def mac():
    return "02:" + ":".join(f"{rng.randrange(256):02X}" for _ in range(5))


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

DEPARTMENTS = {
    "Hardware": ["can_access_receiving", "can_manage_provisioning", "can_view_provisioning",
                 "can_access_map", "can_view_receipts", "can_manage_warranty"],
    "QA": ["can_view_provisioning", "can_manage_provisioning", "can_access_receiving"],
    "Field Engineering": ["can_view_provisioning", "can_access_map", "can_manage_sites"],
    "Sales": ["can_view_provisioning", "can_access_map"],
    "Operations": ["can_view_receipts", "can_manage_warranty", "can_view_provisioning",
                   "can_access_map", "can_view_audit_log"],
}

USERS = [  # username, display name, role, department
    ("maya.patel", "Maya Patel", "admin", "Operations"),
    ("diego.ramirez", "Diego Ramirez", "editor", "Hardware"),
    ("sam.okafor", "Sam Okafor", "editor", "QA"),
    ("jordan.lee", "Jordan Lee", "editor", "Field Engineering"),
    ("riley.brooks", "Riley Brooks", "viewer", "Sales"),
    ("priya.shah", "Priya Shah", "procurement_admin", "Operations"),
    ("lobby.display", "Lobby Map Display", "map_kiosk", None),
]

VENDORS = [  # name, display, categories, is_oem
    ("northstar-it", "Northstar IT Supply", "Laptops, Monitors, Peripherals", False),
    ("granite-compute", "Granite Compute Partners", "Edge servers, GPUs, Memory", True),
    ("bluewire-networks", "Bluewire Networks", "Switches, Access points", False),
    ("keystone-storage", "Keystone Storage", "Hard drives, NAS", False),
    ("lumen-optics", "Lumen Optics", "Cameras", True),
    ("summit-power", "Summit Power Co", "UPS, Power", False),
    ("corner-office", "Corner Office Supply", "Printers, Phones, Webcams", False),
]

OEM_PARTNERS = ["Ridgeline Systems Integration", "Copperleaf Manufacturing"]

EXTRA_SKUS = [  # sku, description, category
    ("C2C-GEN1-4MP", "Cloud camera, 4MP fixed dome", "camera_c2c"),
    ("C2C-GEN1-8MP", "Cloud camera, 8MP bullet", "camera_c2c"),
    ("CLOUDBOX-1U", "Cloud gateway, 1U rackmount", "cloud_box"),
    ("IT-LAPTOP-14", "Staff laptop, 14 inch", "computer"),
    ("IT-WORKSTATION", "Build lab workstation", "computer"),
    ("IT-MON-27", "Monitor, 27 inch", "monitor"),
    ("NET-SW-24P", "PoE switch, 24 port", "network"),
    ("PWR-UPS-1500", "UPS, 1500VA", "ups"),
    ("GPU-RTX-A2000", "GPU, RTX A2000 12GB", "gpu"),
    ("RAM-32G-DDR5", "Memory, 32GB DDR5", "ram"),
    ("CPU-I7-13700", "CPU, Core i7-13700", "cpu"),
    ("IT-PHONE-STD", "Staff phone", "phone"),
    ("IT-PRINTER-MFP", "Multifunction printer", "printer"),
    ("IT-WEBCAM-HD", "Webcam, 1080p", "webcam"),
    ("NAS-8BAY", "NAS, 8 bay", "nas"),
]

INTERNAL_SITES = [  # name, type, city, state
    ("HQ Office", "office", "Dallas", "TX"),
    ("Build Lab", "internal_lab", "Dallas", "TX"),
    ("North Warehouse", "warehouse", "Carrollton", "TX"),
]

CUSTOMERS = {  # customer: [(site name, city, state, lat, lng)]
    "Harbor Point Logistics": [("Harbor Point - Houston DC", "Houston", "TX", 29.7499, -95.3584),
                               ("Harbor Point - Fort Worth Yard", "Fort Worth", "TX", 32.7767, -97.3308)],
    "Red River Medical Group": [("Red River - Dallas Clinic", "Dallas", "TX", 32.8121, -96.8395),
                                ("Red River - Plano Clinic", "Plano", "TX", 33.0198, -96.6989)],
    "Lakeside Retail Co": [("Lakeside Retail - San Antonio", "San Antonio", "TX", 29.4241, -98.4936)],
    "Cedar Valley Schools": [("Cedar Valley - Austin Campus", "Austin", "TX", 30.2849, -97.7341)],
    "Summit Ridge Apartments": [("Summit Ridge - Denver", "Denver", "CO", 39.7392, -104.9903)],
    "Bluebonnet Transit": [("Bluebonnet Transit - El Paso Depot", "El Paso", "TX", 31.7619, -106.4850)],
    "Mesa Verde Foods": [("Mesa Verde - Phoenix Plant", "Phoenix", "AZ", 33.4484, -112.0740)],
    "Prairie Wind Energy": [("Prairie Wind - Amarillo Field Office", "Amarillo", "TX", 35.2220, -101.8313)],
    "Riverbend Credit Union": [("Riverbend - Tulsa Branch", "Tulsa", "OK", 36.1540, -95.9928)],
    "Oakmont Hotels": [("Oakmont Hotel - Santa Fe", "Santa Fe", "NM", 35.6870, -105.9378)],
    "Northgate Stadium": [("Northgate Stadium - Lubbock", "Lubbock", "TX", 33.5779, -101.8552)],
    "Gulf Coast Marina": [("Gulf Coast Marina - Corpus Christi", "Corpus Christi", "TX", 27.8006, -97.3964)],
}


def make_demo_user():
    problem = validate_password_strength(DEMO_PASSWORD)
    if problem:
        raise SystemExit("demo password rejected by the password rules: " + problem)
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == DEMO_USER).first() is None:
            db.add(User(username=DEMO_USER, display_name="Avery Demo", role="super_admin",
                        password_hash=hash_password(DEMO_PASSWORD), is_active=True,
                        must_change_password=False, slack_auto_match=False))
            db.commit()
    finally:
        db.close()


def refuse_if_not_empty():
    create_all_tables()  # a brand-new database has no tables to count yet
    with engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM item_schema.items")).scalar()
    if n and "--force" not in sys.argv:
        raise SystemExit(f"refusing to seed: the database already holds {n} inventory items. "
                         "Seed an empty database (or pass --force on a throwaway one).")


# ---------------------------------------------------------------------------
# The seed
# ---------------------------------------------------------------------------

def seed(s: Seeder):
    ids = {"dept": {}, "user": {}, "vendor": {}, "site": {}, "partner": {}}

    # People -----------------------------------------------------------------
    for name, perms in DEPARTMENTS.items():
        r = s.post("/admin/departments/add", json={"name": name, "description": name + " team"})
        did = r.json()["department_id"]
        ids["dept"][name] = did
        s.post(f"/api/admin/departments/{did}/permissions", json={p: "grant" for p in perms})
        s.bump("departments")
    for username, display, role, dept in USERS:
        r = s.post("/admin/users/add", data={"username": username, "display_name": display,
                                             "password": TEAM_PASSWORD, "role": role})
        uid = r.json()["id"]
        ids["user"][username] = uid
        if dept:
            s.post(f"/api/admin/users/{uid}/department", json={"department_id": ids["dept"][dept]})
        s.bump("users")

    # Vendors, OEM partners, part numbers -------------------------------------
    for name, display, cats, is_oem in VENDORS:
        r = s.post("/api/vendors/", json={"name": name, "display_name": display,
                                          "categories_supplied": cats, "is_oem": is_oem,
                                          "contact_email": "orders@" + name + ".example"})
        ids["vendor"][name] = r.json()["vendor_id"]
        s.bump("vendors")
    for name in OEM_PARTNERS:
        ids["partner"][name] = s.post("/api/oem-partners/", json={"name": name}).json()["id"]
    for sku, desc, cat in EXTRA_SKUS:
        s.post("/admin/part-numbers/add", data={"item_sku": sku, "sku_description": desc,
                                               "item_category": cat})
        s.bump("part numbers")

    # Sites -------------------------------------------------------------------
    for name, kind, city, state in INTERNAL_SITES:
        r = s.post("/api/sites", json={"name": name, "site_type": kind, "city": city, "state": state,
                                       "country": "USA", "address": "100 Example Way"})
        ids["site"][name] = r.json()["site_id"]
        s.bump("sites")
    coords = {}
    for customer, sites in CUSTOMERS.items():
        for name, city, state, lat, lng in sites:
            r = s.post("/api/sites", json={
                "name": name, "site_type": "customer_site", "customer": customer, "city": city,
                "state": state, "country": "USA", "address": f"{rng.randrange(100, 9900)} Commerce Pkwy",
                "contact_name": "Site Manager", "contact_email": "facilities@example.com"})
            ids["site"][name] = r.json()["site_id"]
            coords[name] = (lat, lng)
            s.bump("sites")

    hq, lab, wh = ids["site"]["HQ Office"], ids["site"]["Build Lab"], ids["site"]["North Warehouse"]
    V = ids["vendor"]

    # Inventory -----------------------------------------------------------------
    def intake(fields, receipt=None):
        form = {k: ("" if v is None else str(v)) for k, v in fields.items()}
        files = None
        if receipt:
            form["record_type"] = receipt["type"]
            form["purchase_order"] = receipt["po"]
            files = {"receipt_file": (receipt["po"] + ".pdf",
                                      pdf_bytes(receipt["type"].title() + " " + receipt["po"], receipt["lines"]),
                                      "application/pdf")}
        s.post("/intake", what="intake " + form.get("item_sn", ""), expect=(303,), data=form, files=files)
        r = s.get("/api/receive/check-duplicate", params={"serial": form["item_sn"]})
        s.bump("items")
        return r.json()["device_id"]

    items = {}

    def batch(key, n, base, receipt_po=None):
        """Create n items from a base field dict; serial and name get a suffix."""
        out = []
        for i in range(1, n + 1):
            f = dict(base)
            f["item_sn"] = f"{base['item_sn']}-{i:04d}"
            f["item_name"] = f"{base['item_name']} {i:02d}"
            f["item_pn"] = f"{base['item_pn']}-{i:04d}"
            receipt = None
            if receipt_po and i == 1:  # one invoice covers the batch
                receipt = {"type": "invoice", "po": receipt_po,
                           "lines": [f"{n} x {base['item_model']}", f"Vendor: {base['item_manufacturer']}",
                                     f"PO {receipt_po}", f"Date {base.get('date_purchased')}"]}
            if "mac" in base:
                f.pop("mac")
                f["item_mac_address_1"] = mac()
            out.append(intake(f, receipt))
        items[key] = out
        return out

    edge_common = {"item_manufacturer": "Granite Compute", "item_category": "edge_box",
                   "department_or_owner": "Hardware", "vendor_id": V["granite-compute"], "mac": True}
    for key, sku, model, n, status, place, days_ago in [
        ("edge25", "EDGE25-NR", "GX-25 Edge Server", 6, "Ready to Deploy", wh, 70),
        ("edge50", "EDGE50-NR", "GX-50 Edge Server", 8, "Pending", lab, 40),
        ("edge100", "EDGE100-Z2", "GX-100 Edge Server", 6, "Pending", lab, 30),
        ("edge200", "EDGE200-Z2", "GX-200 Edge Server", 3, "Ready to Deploy", wh, 90),
    ]:
        base = dict(edge_common, item_name=model, item_model=model, item_sku=sku, item_status=status,
                    location_id=place, item_sn="EBX-" + sku.split("-")[0], item_pn="PN-" + sku,
                    date_purchased=d(-days_ago), item_storage_size_gb=24000 if "Z2" in sku else 8000)
        ids_out = batch(key, n, base, receipt_po=f"GCP-{2400 + n * 7}")
        # every edge box gets a device UUID so provisioning can pass registration
        for iid in ids_out:
            items.setdefault("uuid", {})[iid] = str(uuid.UUID(int=rng.getrandbits(128)))

    cam_common = {"item_manufacturer": "Lumen Optics", "item_category": "camera_c2c",
                  "department_or_owner": "Hardware", "vendor_id": V["lumen-optics"],
                  "location_id": wh, "item_status": "Ready to Deploy", "mac": True}
    batch("cam4", 24, dict(cam_common, item_name="Dome Camera 4MP", item_model="LD-4 Dome", item_sku="C2C-GEN1-4MP",
                           item_sn="C2C4", item_pn="PN-C2C4", date_purchased=d(-55)), receipt_po="LO-7781")
    batch("cam8", 14, dict(cam_common, item_name="Bullet Camera 8MP", item_model="LB-8 Bullet", item_sku="C2C-GEN1-8MP",
                           item_sn="C2C8", item_pn="PN-C2C8", date_purchased=d(-55)), receipt_po="LO-7782")
    batch("cloudbox", 3, {"item_name": "Cloud Gateway", "item_manufacturer": "Granite Compute", "item_model": "CG-1U",
                          "item_category": "cloud_box", "item_status": "Ready to Deploy", "location_id": wh,
                          "department_or_owner": "Hardware", "vendor_id": V["granite-compute"],
                          "item_sku": "CLOUDBOX-1U", "item_sn": "CBX", "item_pn": "PN-CBX",
                          "date_purchased": d(-120), "mac": True})

    def it(key, name, maker, model, cat, sku, sn, owner, vendor, status, place, n, bought, po=None, extra=None):
        base = {"item_name": name, "item_manufacturer": maker, "item_model": model, "item_category": cat,
                "item_sku": sku, "item_sn": sn, "item_pn": "PN-" + sn, "department_or_owner": owner,
                "vendor_id": V[vendor], "item_status": status, "location_id": place, "date_purchased": d(-bought)}
        base.update(extra or {})
        return batch(key, n, base, receipt_po=po)

    it("laptop", "Staff Laptop", "Dell", "Latitude 7450", "computer", "IT-LAPTOP-14", "LT", "Operations",
       "northstar-it", "Deployed", hq, 10, 200, po="NS-55120", extra={"mac": True})
    it("workstation", "Build Workstation", "Granite Compute", "GW-9", "computer", "IT-WORKSTATION", "WS", "Hardware",
       "granite-compute", "Deployed", lab, 2, 300)
    it("monitor", "Monitor 27in", "Dell", "P2725H", "monitor", "IT-MON-27", "MN", "Operations",
       "northstar-it", "Deployed", hq, 8, 200, po="NS-55121")
    it("switch", "PoE Switch", "Bluewire", "BW-24P", "network", "NET-SW-24P", "SW", "Hardware",
       "bluewire-networks", "Deployed", lab, 3, 400, po="BW-1180", extra={"mac": True})
    it("ups", "UPS 1500VA", "Summit Power", "SP-1500", "ups", "PWR-UPS-1500", "UPS", "Hardware",
       "summit-power", "Deployed", lab, 2, 500)
    it("gpu", "GPU RTX A2000", "PNY", "RTX A2000 12GB", "gpu", "GPU-RTX-A2000", "GPU", "Hardware",
       "granite-compute", "Unassigned", lab, 6, 60, po="GCP-2290")
    it("ram", "Memory 32GB", "Kingston", "KF556C40-32", "ram", "RAM-32G-DDR5", "RAM", "Hardware",
       "granite-compute", "Unassigned", lab, 6, 60)
    it("hdd", "Hard Drive 12TB", "Seagate", "Exos X18", "storage_drive", "STOR-HDD-12TB", "HDD", "Hardware",
       "keystone-storage", "Unassigned", lab, 8, 75, po="KS-4410", extra={"item_storage_size_gb": 12000})
    it("cpu", "CPU i7-13700", "Intel", "Core i7-13700", "cpu", "CPU-I7-13700", "CPU", "Hardware",
       "granite-compute", "Unassigned", lab, 2, 60)
    it("phone", "Desk Phone", "Polycom", "VVX 450", "phone", "IT-PHONE-STD", "PH", "Operations",
       "corner-office", "Deployed", hq, 4, 400)
    it("printer", "Office Printer", "Brother", "MFC-L8900", "printer", "IT-PRINTER-MFP", "PR", "Operations",
       "corner-office", "Deployed", hq, 1, 600)
    it("webcam", "Webcam 1080p", "Logitech", "C920", "webcam", "IT-WEBCAM-HD", "WC", "Operations",
       "corner-office", "Unassigned", hq, 5, 150)
    it("nas", "Lab NAS", "Synology", "DS1823xs+", "nas", "NAS-8BAY", "NAS", "Hardware",
       "keystone-storage", "Deployed", lab, 1, 365, extra={"mac": True})

    # Set the edge box UUIDs (POST /items/{id} replaces the whole record, so
    # send every field back with the UUID added).
    db = SessionLocal()
    try:
        from app.models import Item
        for iid, dev_uuid in items["uuid"].items():
            row = db.get(Item, iid)
            form = {c: getattr(row, c) for c in (
                "item_name", "item_manufacturer", "item_model", "item_sn", "item_category", "item_status",
                "location_id", "department_or_owner", "item_mac_address_1", "item_mac_address_2",
                "item_storage_size_gb", "item_sku", "item_pn", "item_associated_pn",
                "vendor_id", "item_vendor", "date_purchased", "intended_purpose", "dispatched_date",
                "tracking_number", "notes")}
            form["platform_uuid"] = dev_uuid
            s.post(f"/items/{iid}", what="set uuid", expect=(303,),
                   data={k: ("" if v is None else str(v)) for k, v in form.items()})
    finally:
        db.close()

    # Triage on purpose: a few items with gaps a person would need to fill.
    gaps = [
        {"item_name": "Loaner Laptop", "item_manufacturer": "Lenovo", "item_model": "ThinkPad T14",
         "item_category": "computer", "item_sn": "LT-LOANER-01", "item_status": "Unassigned",
         "location_id": hq, "department_or_owner": "Operations", "vendor_id": V["northstar-it"],
         "item_sku": "IT-LAPTOP-14"},                       # no part number
        {"item_name": "Spare Switch", "item_manufacturer": "Bluewire", "item_model": "BW-8P",
         "item_category": "network", "item_sn": "SW-SPARE-01", "item_status": "Unassigned",
         "department_or_owner": "Hardware", "item_sku": "NET-SW-24P", "item_pn": "PN-SW-SPARE-01"},  # no place or vendor
        {"item_name": "Monitor (unlabeled)", "item_manufacturer": "Dell", "item_category": "monitor",
         "item_sn": "MN-UNLABELED-01", "item_status": "Pending", "location_id": wh,
         "vendor_id": V["northstar-it"]},                      # several fields missing
        {"item_name": "Conference Room Webcam", "item_manufacturer": "Logitech", "item_model": "Rally",
         "item_category": "webcam", "item_sn": "WC-CONF-01", "item_status": "Deployed", "location_id": hq,
         "vendor_id": V["corner-office"], "item_sku": "IT-WEBCAM-HD", "item_pn": "PN-WC-CONF-01"},  # no owner
    ]
    for f in gaps:
        intake(f)
    s.bump("items left with triage gaps", len(gaps))
    clean_spare = intake({"item_name": "Duplicate Monitor Entry", "item_manufacturer": "Dell",
                          "item_model": "P2725H", "item_category": "monitor", "item_sn": "MN-DUP-0001",
                          "item_status": "Unassigned", "location_id": hq, "department_or_owner": "Operations",
                          "vendor_id": V["northstar-it"], "item_sku": "IT-MON-27", "item_pn": "PN-MN-DUP"})

    # Containment: components installed in build lab units ----------------------
    builds = items["edge100"][:3] + items["workstation"][:1]
    parts = list(zip(items["gpu"], items["ram"], items["hdd"][::2], items["hdd"][1::2]))
    for unit, (gpu, ram, hdd1, hdd2) in zip(builds, parts):
        for comp, slot in ((gpu, "PCIe 1"), (ram, "DIMM A1"), (hdd1, "Bay 1"), (hdd2, "Bay 2")):
            s.post("/api/containment/install", json={"component_item_id": comp, "parent_item_id": unit,
                                                     "slot_label": slot})
            s.bump("components installed")

    # Custody, warranties, maintenance, decommissions ------------------------------
    for iid, uname in zip(items["laptop"][:4], ["diego.ramirez", "sam.okafor", "jordan.lee", "riley.brooks"]):
        s.post("/checkout", expect=(303,), data={"item_id": str(iid),
                                                 "checked_out_to_user_id": str(ids["user"][uname]),
                                                 "notes": "Assigned laptop"})
        s.bump("checkouts")
    s.post("/checkout", expect=(303,), data={"item_id": str(items["webcam"][0]),
                                             "checked_out_to_name": "Visiting auditor",
                                             "notes": "Return by Friday"})
    s.bump("checkouts")

    for iid, start, end, who in [
        (items["laptop"][0], -400, 330, "Dell ProSupport"), (items["laptop"][1], -400, 330, "Dell ProSupport"),
        (items["switch"][0], -700, 20, "Bluewire Care"), (items["ups"][0], -900, -10, "Summit Power"),
        (items["nas"][0], -365, 1460, "Synology Extended"), (items["edge200"][0], -90, 1005, "Granite 3-year"),
        (items["edge200"][1], -90, 1005, "Granite 3-year"), (items["printer"][0], -600, 12, "Corner Office"),
    ]:
        s.post("/api/warranty", json={"item_id": iid, "warranty_start": d(start), "warranty_end": d(end),
                                      "vendor": who, "notes": "Demo warranty"})
        s.bump("warranties")

    for iid, kind, desc, ago in [
        (items["ups"][0], "inspection", "Battery self-test passed, runtime 14 minutes at current load", 30),
        (items["ups"][1], "part_replacement", "Replaced battery pack after failed self-test", 75),
        (items["workstation"][0], "cleaning", "Dust cleaning and fan inspection", 45),
        (items["switch"][0], "firmware_update", "Updated firmware to 4.2.7", 20),
        (items["nas"][0], "repair", "Replaced failed drive in bay 3, array rebuilt", 12),
        (items["edge100"][0], "calibration", "Fan curve tuned for the build lab rack", 5),
    ]:
        s.post(f"/items/{iid}/maintenance", expect=(303,),
               data={"entry_type": kind, "description": desc, "maintenance_date": d(-ago),
                     "performed_by": rng.choice(["Diego Ramirez", "Sam Okafor"])})
        s.bump("maintenance entries")

    for iid, reason in [(items["laptop"][9], "Cracked display hinge, past economical repair"),
                        (items["monitor"][7], "Dead backlight")]:
        s.post(f"/items/{iid}/decommission", data={"reason": reason, "decommission_date": d(-8)})
        s.bump("decommissioned")

    # Orders: one board, two tracks (docs/specs/one-board-two-tracks.md) ------------
    def order(customer, otype, **kw):
        body = {"customer_name": customer, "order_type": otype,
                "deployment_type": kw.pop("deployment_type", "direct")}
        body.update(kw)
        r = s.post("/api/orders/", what="order " + customer, json=body)
        s.bump("orders")
        return r.json()["id"]

    def reqs(oid, lines):
        s.put(f"/api/orders/{oid}", json={"sku_requirements": [
            {"model": m, "qty": q, "source": src} for m, q, src in lines]})

    def advance(oid, *steps):
        for to in steps:
            s.post(f"/api/orders/{oid}/advance", what=f"advance {oid} to {to}", json={"to": to})
            s.bump("order moves")

    def assign(oid, item_ids):
        s.post(f"/api/orders/{oid}/assign-items", json={"item_ids": item_ids})
        s.bump("units assigned", len(item_ids))

    def acquire(order_id, cam_ids, site=None, cert=False):
        out = []
        for cid in cam_ids:
            body = {"device_id": cid, "customer_order_id": order_id, "notes": "Allocated from stock"}
            if site:
                body["site_id"] = ids["site"][site]
            pid = s.post("/fulfillment/c2c/acquire", what="acquire camera", json=body).json()["id"]
            if cert:
                s.post(f"/fulfillment/c2c/{pid}/certify", json={
                    "checklist": {"powered_on": True, "firmware_verified": True,
                                  "qr_site_connected": True, "registered": True},
                    "firmware_evidence": {"version": "2.4.1", "license": "PRO-25", "plugins": ["LPR", "PeopleCount"]},
                    "notes": "Bench verified"})
                s.bump("camera certifications")
            out.append(pid)
            s.bump("cameras allocated")
        return out

    def units_of(order_id):
        panel = s.get(f"/api/fulfillment/panel/{order_id}").json()
        return [dv["prov_id"] for dv in panel.get("devices", [])]

    def place(order_id, site):
        for pid in units_of(order_id):
            s.put(f"/api/provisioning/{pid}", json={"site_id": ids["site"][site]})

    def document(oid, name, kind, title, lines, note=""):
        s.post(f"/api/orders/{oid}/documents", what="document " + name,
               files={"file": (name, pdf_bytes(title, lines), "application/pdf")},
               data={"kind": kind, "note": note})
        s.bump("vendor documents")

    def visit(oid, site, when, integrator, status=None, certify=None):
        dep = s.post("/fulfillment/deployments", json={
            "customer_order_id": oid, "site_id": ids["site"][site], "scheduled_date": d(when),
            "se_assigned_id": se, "integrator_name": integrator}).json()["id"]
        s.post(f"/fulfillment/deployments/{dep}/units", json={"provisioning_ids": units_of(oid)})
        if status:
            s.post(f"/fulfillment/deployments/{dep}/status", json={"status": status})
        if certify:
            report = pdf_bytes("Post-install report: " + site, certify["lines"])
            s.post(f"/fulfillment/deployments/{dep}/install/certify",
                   files={"file": (certify["file"], report, "application/pdf")},
                   data={"installer_name": certify["by"], "installer_company": integrator,
                         "completion_date": d(certify["on"]), "notes": "Verified with the customer"})
        s.bump("site visits")
        return dep

    P = ids["partner"]
    se = ids["user"]["jordan.lee"]
    e25, e200, cboxes = list(items["edge25"]), list(items["edge200"]), list(items["cloudbox"])
    cams4, cams8 = list(items["cam4"]), list(items["cam8"])

    # Vendor track: sales built, certified and shipped by a vendor partner.
    o_harbor = order("Harbor Point Logistics", "sale", po_number="HPL-PO-88412", due_date=d(21),
                     owner="oem", oem_partner_id=P["Ridgeline Systems Integration"],
                     sales_engineer="Jordan Lee", sales_engineer_id=se,
                     notes="Two distribution centers, phased rollout")
    reqs(o_harbor, [("EDGE100-Z2", 2, "oem"), ("C2C-GEN1-8MP", 6, "oem")])
    advance(o_harbor, "building")
    s.post(f"/api/orders/{o_harbor}/oem-pos", json={
        "vendor_name": "Ridgeline Systems Integration", "po_number": "RSI-PO-3301", "sku": "EDGE100-Z2",
        "qty_ordered": 2, "order_date": d(-12), "expected_delivery": d(9), "status": "in_production"})
    s.bump("purchase orders")

    o_redriver = order("Red River Medical Group", "sale", po_number="RRMG-2026-114", due_date=d(28),
                       owner="oem", oem_partner_id=P["Copperleaf Manufacturing"], is_sensitive=True,
                       sales_engineer="Jordan Lee", sales_engineer_id=se,
                       deployment_type="via_integrator", integrator_name="North Texas Integrators")
    reqs(o_redriver, [("EDGE50-NR", 3, "oem"), ("C2C-GEN1-4MP", 8, "oem")])

    o_lakeside = order("Lakeside Retail Co", "sale", po_number="LRC-7731", due_date=d(-3),
                       owner="oem", oem_partner_id=P["Ridgeline Systems Integration"],
                       sales_engineer="Jordan Lee", sales_engineer_id=se,
                       notes="Vendor waiting on a GPU allocation")
    reqs(o_lakeside, [("EDGE25-NR", 2, "oem"), ("C2C-GEN1-4MP", 4, "oem")])
    advance(o_lakeside, "building")
    document(o_lakeside, "lakeside-build-plan.pdf", "other", "Build plan: Lakeside Retail Co",
             ["2 x EDGE25-NR, 4 x C2C-GEN1-4MP", "GPU allocation pending at the vendor",
              "Revised ship date to follow"])

    o_cedar = order("Cedar Valley Schools", "sale", po_number="CVS-PO-2026-09", due_date=d(-12),
                    owner="oem", oem_partner_id=P["Copperleaf Manufacturing"],
                    sales_engineer="Jordan Lee", sales_engineer_id=se)
    reqs(o_cedar, [("EDGE25-NR", 2, "oem"), ("C2C-GEN1-8MP", 4, "stock")])
    s.post(f"/api/orders/{o_cedar}/oem-pos", json={
        "vendor_name": "Copperleaf Manufacturing", "po_number": "CLM-PO-1150", "sku": "EDGE25-NR",
        "qty_ordered": 2, "qty_received": 2, "order_date": d(-40), "expected_delivery": d(-20),
        "status": "verified"})
    s.bump("purchase orders")
    advance(o_cedar, "building")
    document(o_cedar, "copperleaf-certificate-CVS.pdf", "certification", "Certificate of conformance",
             ["Customer order CVS-PO-2026-09", "2 x EDGE25-NR burn-in 48h: pass",
              "SMART and memory tests: pass", "Signed: Copperleaf QA"], note="Vendor build certificate")
    document(o_cedar, "copperleaf-validation-CVS.pdf", "validation", "Software validation report",
             ["Platform image 7.3.2", "Camera onboarding: 4 of 4", "Retention policy verified"])
    # The vendor shipped into our stock first, so the units are in inventory.
    assign(o_cedar, [e25.pop(0), e25.pop(0)])
    acquire(o_cedar, [cams8.pop() for _ in range(4)], cert=True)
    advance(o_cedar, "shipped")
    s.post(f"/fulfillment/{o_cedar}/ship", json={
        "ship_method": "carrier", "carrier": "UPS", "tracking_number": "DEMO-TRK-44090",
        "shipped_date": d(-16), "delivered_date": d(-13), "recipient_name": "District IT"})
    place(o_cedar, "Cedar Valley - Austin Campus")
    visit(o_cedar, "Cedar Valley - Austin Campus", -12, "Hill Country Integrators", status="installing",
          certify={"file": "cedar-valley-post-install.pdf", "by": "Alex Moreno", "on": -10,
                   "lines": ["Site: Austin Campus", "2 edge servers racked and powered",
                             "4 cameras online and recording", "Customer walkthrough completed"]})
    advance(o_cedar, "installed")

    o_gulf = order("Gulf Coast Marina", "sale", po_number="GCM-1042", due_date=d(8),
                   owner="oem", oem_partner_id=P["Ridgeline Systems Integration"])
    reqs(o_gulf, [("EDGE200-Z2", 1, "oem"), ("C2C-GEN1-8MP", 6, "stock")])
    s.post(f"/api/orders/{o_gulf}/oem-pos", json={
        "vendor_name": "Ridgeline Systems Integration", "po_number": "RSI-PO-3288", "sku": "EDGE200-Z2",
        "qty_ordered": 1, "qty_received": 1, "order_date": d(-30), "expected_delivery": d(-6),
        "status": "receiving"})
    s.bump("purchase orders")
    advance(o_gulf, "building")
    assign(o_gulf, [e200.pop(0)])
    acquire(o_gulf, [cams8.pop() for _ in range(6)])
    advance(o_gulf, "shipped")   # shipped, but the vendor certificate has not arrived
    s.post(f"/fulfillment/{o_gulf}/ship", json={
        "ship_method": "carrier", "carrier": "FedEx Freight", "tracking_number": "DEMO-TRK-45112",
        "recipient_name": "Harbor Master", "shipping_address": "Gulf Coast Marina, Corpus Christi TX"})
    place(o_gulf, "Gulf Coast Marina - Corpus Christi")

    o_inhouse = order("Bluebonnet Transit", "sale", po_number="BBT-5520", due_date=d(14),
                      sales_engineer="Jordan Lee", sales_engineer_id=se,
                      notes="Small rush order built in our lab")
    reqs(o_inhouse, [("CLOUDBOX-1U", 1, "stock")])
    assign(o_inhouse, [cboxes.pop(0)])
    advance(o_inhouse, "building")

    o_phase2 = order("Harbor Point Logistics", "sale", po_number="HPL-PO-88990", due_date=d(45),
                     owner="oem", oem_partner_id=P["Copperleaf Manufacturing"],
                     notes="Second phase, quoted by the vendor")
    reqs(o_phase2, [("EDGE100-Z2", 4, "oem")])
    s.post(f"/api/orders/{o_phase2}/oem-pos", json={
        "vendor_name": "Copperleaf Manufacturing", "po_number": "CLM-PO-1207", "sku": "EDGE100-Z2",
        "qty_ordered": 4, "order_date": d(-2), "expected_delivery": d(30), "status": "ordered"})
    s.bump("purchase orders")

    # Pilots and demos: lent from our stock and collected again.
    o_summit = order("Summit Ridge Apartments", "pilot", expected_return=d(5), due_date=d(-25),
                     notes="30 day pilot, decision meeting scheduled")
    reqs(o_summit, [("EDGE25-NR", 1, "stock"), ("C2C-GEN1-4MP", 3, "stock")])
    assign(o_summit, [e25.pop(0)])
    acquire(o_summit, [cams4.pop() for _ in range(3)], cert=True)
    advance(o_summit, "shipped", "at_site")
    s.post(f"/fulfillment/{o_summit}/ship", json={
        "ship_method": "carrier", "carrier": "FedEx", "tracking_number": "DEMO-TRK-45870",
        "shipped_date": d(-27), "delivered_date": d(-25), "recipient_name": "Property Manager",
        "shipping_address": "Summit Ridge Apartments, Denver CO"})
    place(o_summit, "Summit Ridge - Denver")
    visit(o_summit, "Summit Ridge - Denver", -24, "Front Range AV", status="complete")

    o_prairie = order("Prairie Wind Energy", "try_and_buy", expected_return=d(-6), due_date=d(-50))
    reqs(o_prairie, [("C2C-GEN1-8MP", 2, "stock")])
    acquire(o_prairie, [cams8.pop() for _ in range(2)])
    advance(o_prairie, "shipped", "at_site")
    s.post(f"/fulfillment/{o_prairie}/ship", json={
        "ship_method": "carrier", "carrier": "UPS", "tracking_number": "DEMO-TRK-43315",
        "shipped_date": d(-52), "delivered_date": d(-49), "recipient_name": "Field Office Lead"})
    place(o_prairie, "Prairie Wind - Amarillo Field Office")

    o_mesa = order("Mesa Verde Foods", "demo", expected_return=d(40), due_date=d(2))
    reqs(o_mesa, [("C2C-GEN1-4MP", 2, "stock")])
    acquire(o_mesa, [cams4.pop() for _ in range(2)])
    advance(o_mesa, "shipped")
    s.post(f"/fulfillment/{o_mesa}/ship", json={"ship_method": "carrier", "carrier": "UPS", "tracking_number": "DEMO-TRK-46220",
                                                "recipient_name": "Plant Security"})

    o_riverbend = order("Riverbend Credit Union", "pilot", expected_return=d(25), due_date=d(4))
    reqs(o_riverbend, [("EDGE25-NR", 1, "stock"), ("C2C-GEN1-4MP", 2, "stock")])
    assign(o_riverbend, [e25.pop(0)])
    acquire(o_riverbend, [cams4.pop() for _ in range(2)])

    o_oakmont = order("Oakmont Hotels", "demo", expected_return=d(-10), due_date=d(-40))
    reqs(o_oakmont, [("C2C-GEN1-4MP", 2, "stock")])
    acquire(o_oakmont, [cams4.pop() for _ in range(2)])
    advance(o_oakmont, "shipped", "at_site", "returned")
    s.post(f"/fulfillment/{o_oakmont}/ship", json={
        "ship_method": "transferred", "shipped_date": d(-42), "delivered_date": d(-41),
        "recipient_name": "Hotel IT"})

    o_northgate = order("Northgate Stadium", "pilot", expected_return=d(60), due_date=d(9),
                        notes="Waiting on the venue's network survey")
    reqs(o_northgate, [("EDGE200-Z2", 1, "stock"), ("C2C-GEN1-8MP", 4, "stock")])

    o_cancel = order("Pinewood Storage", "pilot", expected_return=d(30))
    s.post(f"/api/orders/{o_cancel}/cancel", json={"reason": "Customer postponed the project to next year"})

    # Map coordinates: one call per customer site that now holds a unit ------------
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT DISTINCT ON (s.id) s.name, i.id FROM item_schema.items i JOIN sites s ON s.id = i.location_id "
            "WHERE s.site_type = 'customer_site' AND i.item_category IN ('edge_box','cloud_box','camera_c2c') "
            "ORDER BY s.id, i.id")).all()
    finally:
        db.close()
    for site_name, item_id in rows:
        lat, lng = coords[site_name]
        s.post("/map/set-location", json={"kind": "item", "id": item_id, "lat": lat, "lng": lng})
        s.bump("sites mapped")

    # Receiving: an OEM shipment arriving against its PO, plus a review queue ----
    ev = s.post("/api/receive/events", json={"vendor": "Granite Compute Partners", "purchase_order": "GCP-PO-3302",
                                             "tracking_number": "DEMO-TRK-77801",
                                             "notes": "Pallet 1 of 2"}).json()["event_id"]
    for i in range(1, 7):
        s.post("/api/receive/device", json={
            "serial": f"HDD-RCV-{i:04d}", "target_table": "hard_drives", "part_number": "STOR-HDD-12TB",
            "manufacturer": "Seagate", "model": "Exos X18", "status": "in storage",
            "location_id": ids["site"]["North Warehouse"], "direct_to_inventory": True,
            "receiving_event_id": ev, "capacity_gb": "12000"})
        s.bump("items received against the PO")
    s.post("/api/photos", files={"file": ("pallet-label.png", label_png(
        ["INBOUND SHIPMENT", "Granite Compute Partners", "PO GCP-PO-3302", "Pallet 1 of 2"]), "image/png")},
        data={"direction": "inbound", "caption": "Pallet label on arrival", "receiving_event_id": str(ev),
              "serials": "HDD-RCV-0001, HDD-RCV-0002"})
    s.bump("photos")

    ev2 = s.post("/api/receive/events", json={"vendor": "Bluewire Networks", "purchase_order": "BW-1192",
                                              "expected_quantity": 4}).json()["event_id"]
    pending = []
    for i, (target, maker, model) in enumerate([
            ("network_equipment", "Bluewire", "BW-AP7"), ("network_equipment", "Bluewire", "BW-AP7"),
            ("network_equipment", "Bluewire", "BW-24P"), ("network_equipment", "Bluewire", "BW-24P")], start=1):
        r = s.post("/api/receive/device", json={"serial": f"BW-RCV-{i:04d}", "target_table": target,
                                                "manufacturer": maker, "model": model, "mac_address": mac(),
                                                "direct_to_inventory": False, "receiving_event_id": ev2})
        pending.append(r.json()["pending_id"])
    s.post(f"/api/pending/{pending[0]}/approve", json={"item_category": "network"})
    s.post(f"/api/pending/{pending[1]}/dismiss", json={"reason": "Wrong model shipped, returning to vendor"})
    s.bump("devices left in the review queue", 2)

    s.post("/api/photos", files={"file": ("outbound-crate.png", label_png(
        ["OUTBOUND", "Gulf Coast Marina", "Order GCM-1042", "1 edge server, 6 cameras"], (40, 120, 70)),
        "image/png")}, data={"direction": "outbound", "caption": "Crate sealed for shipping",
                             "customer_order_id": str(o_gulf), "tag_order_units": "true"})
    s.bump("photos")

    # A delete request from an editor, waiting for an admin -----------------------
    editor = TestClient(app, base_url="http://testserver", follow_redirects=False)
    editor.post("/login", data={"username": "diego.ramirez", "password": TEAM_PASSWORD})
    r = editor.post("/api/delete-requests", json={"target_table": "items", "target_id": clean_spare,
                                                  "reason": "Entered twice; the real monitor is MN-0003"})
    if r.status_code != 200:
        raise SystemExit("seed failed at delete request: " + r.text[:300])
    s.bump("delete requests")


def main():
    refuse_if_not_empty()
    with TestClient(app, base_url="http://testserver", follow_redirects=False) as client:
        make_demo_user()
        r = client.post("/login", data={"username": DEMO_USER, "password": DEMO_PASSWORD},
                        follow_redirects=False)
        if r.status_code != 302:
            raise SystemExit("could not sign in as the demo user: HTTP " + str(r.status_code))
        s = Seeder(client)
        seed(s)
    width = max(len(k) for k in s.counts)
    print("Demo data created:")
    for key, n in s.counts.items():
        print(f"  {key:<{width}}  {n}")
    print(f"\nSign in as {DEMO_USER} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
