"""SQLAlchemy ORM models for the hardware inventory system.

Inventory lives in item_schema.items (Item). Item 30 retired the 22 legacy
per-category public tables and their models (docs/specs/retire-legacy-inventory.md).
"""


from sqlalchemy import (
    Enum as SAEnum,
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, LargeBinary,
    MetaData, String, Table, Text, UniqueConstraint, func, literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.orm import relationship

from .database import Base

# Today's date in Central, computed by the database. docs/specs/local-time.md slice C.
LOCAL_TODAY_SQL = "(now() AT TIME ZONE 'America/Chicago')::date"


# Admin-level roles (CEO included, has all admin access except credentials).
# Single home for this tuple; auth, api and admin import it from here.
ADMIN_LEVEL_ROLES = ("super_admin", "system_admin", "admin", "ceo")


# item_categories ENUM (public schema). Defined here, ahead of the models,
# because PendingDevice (suggested_category, migration 080) uses it as well
# as Item and ItemPartNumber. DDL is owned by the migrations; 080 added the
# last four values (board item 30). The app category lists are hand-kept:
# see CLAUDE.md, "The item category vocabulary is hand-maintained".
item_categories_enum = SAEnum(
    'access_control', 'camera', 'computer', 'cpu', 'motherboard',
    'gpu', 'ram', 'storage_drive', 'psu', 'cpu_cooler', 'case_fan',
    'pci', 'product_cabling', 'consumables', 'edge_box', 'ups',
    'mobile_device', 'monitor', 'network', 'office_equipment', 'pc_accessories',
    'camera_c2c', 'cloud_box',
    'phone', 'webcam', 'printer', 'nas',
    name='item_categories',
    schema='public'
)


# ---------------------------------------------------------------------------
# Receiving Events (shipment intake tracking)
# ---------------------------------------------------------------------------
class ReceivingEvent(Base):
    __tablename__ = "receiving_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    received_date = Column(DateTime, server_default=func.now())
    vendor = Column(String(255), nullable=True)
    purchase_order = Column(String(64), nullable=True)
    tracking_number = Column(String(128), nullable=True)  # inbound shipment (H17, migration 068)
    expected_quantity = Column(Integer, nullable=True)
    received_quantity = Column(Integer, default=0)
    status = Column(String(32), default="open")  # open | complete | partial
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    lines = relationship("ReceivingEventLine", back_populates="event",
                         cascade="all, delete-orphan", order_by="ReceivingEventLine.id")


class ReceivingEventLine(Base):
    """Per-SKU expectation for ONE shipment (H17, migration 068) — snapshotted
    from the matched OEM PO's outstanding lines at event-create time."""
    __tablename__ = "receiving_event_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receiving_event_id = Column(Integer, ForeignKey("receiving_events.id", ondelete="CASCADE"), nullable=False)
    sku = Column(String(128), nullable=False)
    qty_expected = Column(Integer, nullable=False, default=0)
    qty_received = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    event = relationship("ReceivingEvent", back_populates="lines")


class ReceivedDevice(Base):
    """Polymorphic unit↔event link (H17, migration 068): one row per intaken
    unit — item_id for direct intakes, pending_device_id for the review
    queue. Replaces sprinkling receiving_event_id over 15+ legacy tables."""
    __tablename__ = "received_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receiving_event_id = Column(Integer, ForeignKey("receiving_events.id", ondelete="CASCADE"), nullable=False)
    line_id = Column(Integer, ForeignKey("receiving_event_lines.id", ondelete="SET NULL"), nullable=True)
    item_id = Column(Integer, ForeignKey("item_schema.items.id", ondelete="SET NULL"), nullable=True)
    pending_device_id = Column(Integer, ForeignKey("pending_devices.id", ondelete="SET NULL"), nullable=True)
    serial = Column(String(512), nullable=True)
    sku = Column(String(128), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class UnitPhoto(Base):
    """Shipment/unit photos (migration 069) — superseded the retired
    intake_photos table and its dead device linkage. One photo, nullable context FKs; serial tying is N:M via
    unit_photo_items (one arrival photo can show three boxes' labels).
    Deletion is soft (is_hidden + audit); hard delete is admin-only."""
    __tablename__ = "unit_photos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_path = Column(String(255), nullable=False)   # relative to PHOTO_UPLOAD_DIR
    thumb_path = Column(String(255), nullable=False)
    direction = Column(String(16), nullable=False)    # inbound | outbound
    caption = Column(String(255), nullable=True)
    taken_at = Column(DateTime, nullable=True)        # EXIF DateTimeOriginal, else upload time
    original_filename = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    receiving_event_id = Column(Integer, ForeignKey("receiving_events.id", ondelete="SET NULL"), nullable=True)
    customer_order_id = Column(Integer, ForeignKey("customer_orders.id", ondelete="SET NULL"), nullable=True)
    deployment_record_id = Column(Integer, ForeignKey("deployment_records.id", ondelete="SET NULL"), nullable=True)
    is_hidden = Column(Boolean, nullable=False, default=False)
    hidden_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    hidden_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    items = relationship("UnitPhotoItem", back_populates="photo",
                         cascade="all, delete-orphan")


class UnitPhotoItem(Base):
    """N:M photo↔item tags (one photo can show several units' labels)."""
    __tablename__ = "unit_photo_items"

    photo_id = Column(Integer, ForeignKey("unit_photos.id", ondelete="CASCADE"), primary_key=True)
    item_id = Column(Integer, ForeignKey("item_schema.items.id", ondelete="CASCADE"), primary_key=True)

    photo = relationship("UnitPhoto", back_populates="items")
    item = relationship("Item")


# ---------------------------------------------------------------------------
# 16. Encrypted Credentials Vault
# ---------------------------------------------------------------------------
class DeviceCredential(Base):
    __tablename__ = "device_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("item_schema.items.id", ondelete="SET NULL"), nullable=True)  # migration 080 (item 30)
    credential_type = Column(String(32), nullable=False)  # "login", "pin", "api_key"
    username = Column(LargeBinary, nullable=True)  # Fernet-encrypted
    password = Column(LargeBinary, nullable=True)  # Fernet-encrypted
    notes = Column(LargeBinary, nullable=True)  # Fernet-encrypted
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# 16a. Vendor Profiles (contact info and notes for vendors in inventory)
# ---------------------------------------------------------------------------
class VendorProfile(Base):
    __tablename__ = "vendor_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # name must match the vendor string used in inventory tables (case-insensitive match at query time)
    name = Column(String(128), unique=True, nullable=False)
    display_name = Column(String(128), nullable=True)   # optional pretty name (e.g. "Axis Communications AB")
    contact_name = Column(String(128), nullable=True)
    contact_email = Column(String(256), nullable=True)
    contact_phone = Column(String(64), nullable=True)
    website = Column(String(512), nullable=True)
    is_oem = Column(Boolean, default=False, nullable=False)  # True if this is an OEM supplier for edge boxes
    categories_supplied = Column(Text, nullable=True)        # comma-separated: "Edge Boxes, Cameras"
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# 16b. Departments (permission templates for RBAC)
# ---------------------------------------------------------------------------
# Permission state ENUM types — DDL is owned by migration 048.
# create_type=False tells SQLAlchemy NOT to emit CREATE TYPE during
# Base.metadata.create_all(); reads/writes still go through the existing type.
# Since we pass string literals (not a Python enum.Enum class), values come
# back as plain Python strings — JSON-encodable, no .value access needed.
user_permission_state = PG_ENUM(
    'inherit', 'grant', 'block',
    name='user_permission_state',
    create_type=False,
)
department_permission_state = PG_ENUM(
    'grant', 'block',
    name='department_permission_state',
    create_type=False,
)


# Permission column constants. Canonical home — imported by admin.py and
# future migrations. The user side adds one extra column (view_sensitive_customers)
# that has no department equivalent.
DEPARTMENT_PERMISSION_COLUMNS = (
    "can_view_receipts", "can_manage_warranty", "can_manage_trials",
    "can_manage_procurement", "can_manage_sites", "can_manage_users",
    "can_manage_system", "can_view_audit_log", "can_access_receiving",
    "can_access_map", "can_access_disposal", "can_access_credentials",
    "can_manage_provisioning", "can_view_provisioning",
)
USER_PERMISSION_COLUMNS = DEPARTMENT_PERMISSION_COLUMNS + ("view_sensitive_customers",)


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    # Permission flags — department_permission_state ENUM: 'grant' | 'block'.
    # Defaults for department members. User-level 'inherit' falls back here.
    can_view_receipts = Column(department_permission_state, nullable=False, server_default='block')
    can_manage_warranty = Column(department_permission_state, nullable=False, server_default='block')
    can_manage_trials = Column(department_permission_state, nullable=False, server_default='block')
    can_manage_procurement = Column(department_permission_state, nullable=False, server_default='block')
    can_manage_sites = Column(department_permission_state, nullable=False, server_default='block')
    can_manage_users = Column(department_permission_state, nullable=False, server_default='block')
    can_manage_system = Column(department_permission_state, nullable=False, server_default='block')
    can_view_audit_log = Column(department_permission_state, nullable=False, server_default='block')
    can_access_receiving = Column(department_permission_state, nullable=False, server_default='block')
    can_access_map = Column(department_permission_state, nullable=False, server_default='block')
    can_access_disposal = Column(department_permission_state, nullable=False, server_default='block')
    can_access_credentials = Column(department_permission_state, nullable=False, server_default='block')
    can_manage_provisioning = Column(department_permission_state, nullable=False, server_default='block')
    can_view_provisioning = Column(department_permission_state, nullable=False, server_default='block')
    created_at = Column(DateTime, server_default=func.now())

    def __getitem__(self, key):
        return getattr(self, key)


# ---------------------------------------------------------------------------
# 16b. Users (individual accounts with bcrypt hashed passwords)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    display_name = Column(String(128), nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(32), nullable=False, default="viewer")  # ceo | admin | warranty_admin | trials_admin | procurement_admin | editor | viewer
    is_active = Column(Boolean, default=True)
    email = Column(String(256), nullable=True)                   # used for Slack auto-match
    slack_user_id = Column(String(64), nullable=True)            # Slack user ID (U0123456), cached after first lookup
    slack_auto_match = Column(Boolean, default=True, nullable=False)  # attempt auto-lookup by email
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    # Permission flags — user_permission_state ENUM: 'inherit' | 'grant' | 'block'.
    # 'inherit' falls back to the department's value (grant or block).
    # 'grant' / 'block' are explicit overrides on the user.
    # view_sensitive_customers is the exception: no department equivalent, so its
    # default is 'block' and the application should never write 'inherit' to it
    # (the DB type permits it but the API rejects it).
    can_view_receipts = Column(user_permission_state, nullable=False, server_default='inherit')
    can_manage_warranty = Column(user_permission_state, nullable=False, server_default='inherit')
    can_manage_trials = Column(user_permission_state, nullable=False, server_default='inherit')
    can_manage_procurement = Column(user_permission_state, nullable=False, server_default='inherit')
    can_manage_sites = Column(user_permission_state, nullable=False, server_default='inherit')
    can_manage_users = Column(user_permission_state, nullable=False, server_default='inherit')
    can_manage_system = Column(user_permission_state, nullable=False, server_default='inherit')
    can_view_audit_log = Column(user_permission_state, nullable=False, server_default='inherit')
    can_access_receiving = Column(user_permission_state, nullable=False, server_default='inherit')
    can_access_map = Column(user_permission_state, nullable=False, server_default='inherit')
    can_access_disposal = Column(user_permission_state, nullable=False, server_default='inherit')
    can_access_credentials = Column(user_permission_state, nullable=False, server_default='inherit')
    can_manage_provisioning = Column(user_permission_state, nullable=False, server_default='inherit')
    can_view_provisioning = Column(user_permission_state, nullable=False, server_default='inherit')
    view_sensitive_customers = Column(user_permission_state, nullable=False, server_default='block')
    must_change_password = Column(Boolean, default=True, nullable=False)
    password_changed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)   # throttled update on every authenticated request

    department = relationship("Department", backref="members", lazy="joined")

    # Admin-level roles (CEO included — has all admin access except credentials)
    _ADMIN_LEVEL_ROLES = ADMIN_LEVEL_ROLES

    # --- Three-state permission resolution ---

    def _resolve_perm(self, attr: str) -> bool:
        """Three-state resolution: user override > department default > False.

        User columns are user_permission_state ENUM:
          'inherit' = look up department's value (which is 'grant' or 'block')
          'grant'   = explicit grant; user has access
          'block'   = explicit block; user denied even if department grants

        Note: view_sensitive_customers has no department equivalent. For that
        column, 'inherit' is never set (DB default is 'block') so the inherit
        branch is unreachable for it — the read still resolves cleanly.
        """
        val = self.__dict__.get(attr)  # raw column value, bypasses properties
        if val == 'inherit':
            if self.department_id and self.department:
                dept_val = getattr(self.department, attr, None)
                return dept_val == 'grant'  # department side: 'grant' or 'block'
            return False
        return val == 'grant'

    # --- Domain admin helpers (role OR resolved flag) ---

    @property
    def has_warranty_admin(self):
        return self.role in self._ADMIN_LEVEL_ROLES + ("warranty_admin",) or self._resolve_perm("can_manage_warranty")

    @property
    def has_trials_admin(self):
        return self.role in self._ADMIN_LEVEL_ROLES + ("trials_admin",) or self._resolve_perm("can_manage_trials")

    @property
    def has_procurement_admin(self):
        return self.role in self._ADMIN_LEVEL_ROLES + ("procurement_admin",) or self._resolve_perm("can_manage_procurement")

    @property
    def has_sites_admin(self):
        return self.role in self._ADMIN_LEVEL_ROLES or self._resolve_perm("can_manage_sites")

    @property
    def has_receipts_access(self):
        return (self.role in self._ADMIN_LEVEL_ROLES
                or self._resolve_perm("can_view_receipts"))

    @property
    def is_admin_tier(self):
        return self.role in self._ADMIN_LEVEL_ROLES

    @property
    def is_editor_or_above(self):
        return self.role in self._ADMIN_LEVEL_ROLES + ("editor", "warranty_admin", "trials_admin", "procurement_admin")

    @property
    def has_any_admin(self):
        return (self.role in self._ADMIN_LEVEL_ROLES + ("warranty_admin", "trials_admin", "procurement_admin")
                or self._resolve_perm("can_view_receipts") or self._resolve_perm("can_manage_warranty")
                or self._resolve_perm("can_manage_trials") or self._resolve_perm("can_manage_procurement")
                or self._resolve_perm("can_manage_sites"))

    # --- Granular page/feature access helpers ---

    @property
    def has_user_management(self):
        return self.role in self._ADMIN_LEVEL_ROLES or self._resolve_perm("can_manage_users")

    @property
    def has_system_admin(self):
        return self.role in self._ADMIN_LEVEL_ROLES or self._resolve_perm("can_manage_system")

    @property
    def has_audit_access(self):
        return self.is_admin_tier or self.can_view_audit_log == 'grant'

    @property
    def has_receiving_access(self):
        return self.is_editor_or_above or self._resolve_perm("can_access_receiving")

    @property
    def has_map_access(self):
        return self.role == "map_kiosk" or self.is_editor_or_above or self._resolve_perm("can_access_map")

    @property
    def has_disposal_access(self):
        return self.is_editor_or_above or self._resolve_perm("can_access_disposal")

    @property
    def has_credentials_access(self):
        # CEO explicitly excluded from credentials — must have explicit flag
        if self.role == "ceo":
            return self._resolve_perm("can_access_credentials")
        return self.is_editor_or_above or self._resolve_perm("can_access_credentials")

    # --- Provisioning access (separate view vs manage) ---

    @property
    def has_provisioning_manage(self):
        """Full CRUD on provisioning records."""
        return (self.role in self._ADMIN_LEVEL_ROLES
                or self._resolve_perm("can_manage_provisioning")
                or self._resolve_perm("can_manage_sites"))

    @property
    def has_provisioning_view(self):
        """Read-only provisioning access (includes manage users)."""
        return self.has_provisioning_manage or self._resolve_perm("can_view_provisioning")

    @property
    def has_sensitive_customers_access(self):
        """Access to sensitive customer orders (hidden from most users)."""
        return (self.role in self._ADMIN_LEVEL_ROLES
                or self._resolve_perm("view_sensitive_customers"))


# ---------------------------------------------------------------------------
# 17. Audit Log (full audit trail for accountability)
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now())
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    event_type = Column(String(32), nullable=False)
    target_table = Column(String(64), nullable=True)
    target_id = Column(Integer, nullable=True)
    action = Column(String(16), nullable=True)  # create | update | delete | view | approve | dismiss
    old_values = Column(JSONB, nullable=True)
    new_values = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    details = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 18. OUI Allowlist (dashboard-configurable manufacturer prefixes)
# ---------------------------------------------------------------------------
class OUIAllowlist(Base):
    __tablename__ = "oui_allowlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    oui_prefix = Column(String(8), unique=True, nullable=False)  # e.g. "E4:30:22"
    manufacturer = Column(String(128), nullable=True)
    maps_to_table = Column(String(64), nullable=True)  # target inventory table
    is_active = Column(Boolean, default=True)
    added_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 19. Pending Devices (staging area for discovered devices awaiting approval)
# ---------------------------------------------------------------------------
class PendingDevice(Base):
    __tablename__ = "pending_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mac_address = Column(String(64), nullable=False)
    ip_address = Column(String(45), nullable=True)
    hostname = Column(String(128), nullable=True)
    manufacturer = Column(String(128), nullable=True)
    suggested_category = Column(item_categories_enum, nullable=True)  # migration 080 (item 30)
    scanner_id = Column(String(64), nullable=True)
    network_segment = Column(String(32), nullable=True)
    first_seen = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime, server_default=func.now())
    status = Column(String(16), default="pending")  # pending | approved | dismissed
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    dismiss_reason = Column(Text, nullable=True)

    # Scan-intake fields (H3, migration 064): what the receive flow knew
    # about the unit — previously discarded on the pending path (the serial
    # survived only inside the mac_address placeholder).
    serial = Column(String(64), nullable=True)
    model = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)
    receiving_event_id = Column(
        Integer, ForeignKey("receiving_events.id", ondelete="SET NULL"), nullable=True
    )


# ---------------------------------------------------------------------------
# Device Warranties (basic tracking on items, item 30 S4)
# ---------------------------------------------------------------------------
class DeviceWarranty(Base):
    __tablename__ = "device_warranties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    item_id = Column(Integer, ForeignKey("item_schema.items.id", ondelete="SET NULL"), nullable=True)  # migration 080 (item 30)
    vendor = Column(String(128))
    warranty_start = Column(Date)
    warranty_end = Column(Date)
    notes = Column(Text, nullable=True)  # migration 082 (item 30 S4)

    REQUIRED_FIELDS = ["item_id", "warranty_start", "warranty_end"]


# ---------------------------------------------------------------------------
# 25. Sites (physical locations — internal labs, customer sites, partners)
# ---------------------------------------------------------------------------
class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    site_type = Column(String(32), nullable=False)  # internal_lab | customer_site | partner | warehouse | office
    customer = Column(String(255), nullable=True)  # Customer/org name (for customer_site/partner types)
    address = Column(Text, nullable=True)
    city = Column(String(128), nullable=True)
    state = Column(String(64), nullable=True)
    country = Column(String(64), nullable=True)
    contact_name = Column(String(128), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    # Map + geocoding (Migration 063: sites is the unified typed place table).
    # Coordinates live on the site; units inherit their site pin. geocode_query
    # caches the address string last resolved so re-geocode fires only on change.
    geo_lat = Column(Float, nullable=True)
    geo_lng = Column(Float, nullable=True)
    show_on_map = Column(Boolean, nullable=False, server_default="false")
    geocoded_at = Column(DateTime, nullable=True)
    geocode_query = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


    SITE_TYPES = {
        "internal_lab": "Internal Lab",
        "customer_site": "Customer Site",
        "partner": "Partner",
        "warehouse": "Warehouse",
        "office": "Office",
    }


# ---------------------------------------------------------------------------
# Device Provisioning — track pre-deployment workflow stages
# ---------------------------------------------------------------------------
DEFAULT_PROVISIONING_STAGES = [
    # ── Approved PO ──
    {"name": "po_in",            "label": "PO In",        "completed": False, "completed_at": None, "completed_by": None},
    {"name": "scoped",           "label": "Scoped",       "completed": False, "completed_at": None, "completed_by": None},
    {"name": "sourced",          "label": "Sourced",      "completed": False, "completed_at": None, "completed_by": None},
    {"name": "ready",            "label": "Ready",        "completed": False, "completed_at": None, "completed_by": None},
    # ── Sourcing ──
    {"name": "ordered",          "label": "Order",        "completed": False, "completed_at": None, "completed_by": None},
    {"name": "tracking",         "label": "Tracking",     "completed": False, "completed_at": None, "completed_by": None},
    {"name": "deliver",          "label": "Deliver",      "completed": False, "completed_at": None, "completed_by": None},
    {"name": "received",         "label": "Received",     "completed": False, "completed_at": None, "completed_by": None},
    # ── Building ──
    {"name": "staged",           "label": "Staged",       "completed": False, "completed_at": None, "completed_by": None},
    {"name": "building",         "label": "Building",     "completed": False, "completed_at": None, "completed_by": None},
    {"name": "registered",       "label": "Registered",   "completed": False, "completed_at": None, "completed_by": None},
    {"name": "licensed",         "label": "Licensed",     "completed": False, "completed_at": None, "completed_by": None},
    # ── Testing / Validation ──
    {"name": "hw_check",         "label": "HW Check",     "completed": False, "completed_at": None, "completed_by": None},
    {"name": "sw_version",       "label": "SW Ver",       "completed": False, "completed_at": None, "completed_by": None},
    {"name": "pva_events",       "label": "PVA/Events",   "completed": False, "completed_at": None, "completed_by": None},
    {"name": "certified",        "label": "Cert'd",       "completed": False, "completed_at": None, "completed_by": None},
    # ── Shipping ──
    {"name": "packed",           "label": "Packed",       "completed": False, "completed_at": None, "completed_by": None},
    {"name": "labeled",          "label": "Labeled",      "completed": False, "completed_at": None, "completed_by": None},
    {"name": "pickup",           "label": "Pickup",       "completed": False, "completed_at": None, "completed_by": None},
    {"name": "transit",          "label": "Transit",      "completed": False, "completed_at": None, "completed_by": None},
    # ── Deployment: Scheduled ──
    {"name": "dep_confirmed",    "label": "Confirmed",    "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_se_assigned",  "label": "SE Assigned",  "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_site_ready",   "label": "Site Ready",   "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_parts_staged", "label": "Parts Staged", "completed": False, "completed_at": None, "completed_by": None},
    # ── Deployment: In Transit ──
    {"name": "dep_packed",       "label": "Packed",       "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_shipped",      "label": "Shipped",      "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_in_transit",   "label": "In Transit",   "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_delivered",    "label": "Delivered",    "completed": False, "completed_at": None, "completed_by": None},
    # ── Deployment: On-Site ──
    {"name": "dep_arrived",      "label": "Arrived",      "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_unpacked",     "label": "Unpacked",     "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_cabled",       "label": "Cabled",       "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_powered_on",   "label": "Powered On",   "completed": False, "completed_at": None, "completed_by": None},
    # ── Deployment: Installing ──
    {"name": "dep_hw_install",   "label": "HW Install",   "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_configured",   "label": "Configured",   "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_cameras_up",   "label": "Cameras Up",   "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_testing",      "label": "Testing",      "completed": False, "completed_at": None, "completed_by": None},
    # ── Deployment: Complete ──
    {"name": "dep_verified",     "label": "Verified",     "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_signoff",      "label": "Sign-off",     "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_docs_sent",    "label": "Docs Sent",    "completed": False, "completed_at": None, "completed_by": None},
    {"name": "dep_closed",       "label": "Closed",       "completed": False, "completed_at": None, "completed_by": None},
]

STAGE_GROUPS = {
    "new":        ["po_in", "scoped", "sourced", "ready"],
    "sourcing":   ["ordered", "tracking", "deliver", "received"],
    "building":   ["staged", "building", "registered", "licensed"],
    "testing":    ["hw_check", "sw_version", "pva_events", "certified"],
    "shipped":    ["packed", "labeled", "pickup", "transit"],
    "scheduled":  ["dep_confirmed", "dep_se_assigned", "dep_site_ready", "dep_parts_staged"],
    "in_transit": ["dep_packed", "dep_shipped", "dep_in_transit", "dep_delivered"],
    "on_site":    ["dep_arrived", "dep_unpacked", "dep_cabled", "dep_powered_on"],
    "installing": ["dep_hw_install", "dep_configured", "dep_cameras_up", "dep_testing"],
    "complete":   ["dep_verified", "dep_signoff", "dep_docs_sent", "dep_closed"],
}

STAGE_LABELS = {
    "po_in": "PO In", "scoped": "Scoped", "sourced": "Sourced", "ready": "Ready",
    "ordered": "Order", "tracking": "Tracking", "deliver": "Deliver", "received": "Received",
    "staged": "Staged", "building": "Building", "registered": "Reg'd", "licensed": "Licensed",
    "hw_check": "HW Check", "sw_version": "SW Ver", "pva_events": "PVA/Evt", "certified": "Cert'd",
    "packed": "Packed", "labeled": "Labeled", "pickup": "Pickup", "transit": "Transit",
    "dep_confirmed": "Confirm", "dep_se_assigned": "SE Asgn",
    "dep_site_ready": "Site Rdy", "dep_parts_staged": "Parts",
    "dep_packed": "Packed", "dep_shipped": "Shipped",
    "dep_in_transit": "Transit", "dep_delivered": "Deliv'd",
    "dep_arrived": "Arrived", "dep_unpacked": "Unpack",
    "dep_cabled": "Cabled", "dep_powered_on": "Power On",
    "dep_hw_install": "HW Inst", "dep_configured": "Config",
    "dep_cameras_up": "Cameras", "dep_testing": "Testing",
    "dep_verified": "Verified", "dep_signoff": "Sign-off",
    "dep_docs_sent": "Docs", "dep_closed": "Closed",
}


# Derived lookups over the stage taxonomy (single source: STAGE_GROUPS and
# DEFAULT_PROVISIONING_STAGES above). Route modules import these instead of
# re-deriving the taxonomy, so it cannot drift again.
STAGE_ORDER = [s["name"] for s in DEFAULT_PROVISIONING_STAGES]
STAGE_INDEX = {name: i for i, name in enumerate(STAGE_ORDER)}
STAGE_TO_GROUP = {sub: grp for grp, subs in STAGE_GROUPS.items() for sub in subs}


class DeviceProvisioning(Base):
    __tablename__ = "device_provisioning"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    current_stage = Column(String(32), nullable=False, default="po_in")
    fulfillment_type = Column(String(32), nullable=True)  # build | prebuilt_software | prebuilt_finished; NULL = not in fulfillment
    stages = Column(JSONB, nullable=False)

    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    priority = Column(String(16), default="normal")
    is_complete = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)

    # Pipeline tracking fields (Migration 005)
    due_date = Column(Date, nullable=True)
    start_date = Column(Date, nullable=True)
    location_note = Column(Text, nullable=True)
    deployment_bucket = Column(String(32), nullable=True)

    # Customer Order link (Migration 018)
    customer_order_id = Column(Integer, ForeignKey("customer_orders.id", ondelete="SET NULL"), nullable=True)

    # The unit (Migration 056). Every row links an item since item 30; the
    # legacy device_table/device_id pair dropped in migration 083.
    item_id = Column(Integer, ForeignKey("item_schema.items.id", ondelete="SET NULL"), nullable=True)

    # Assignment type (Migration 057): how a provisioned device is assigned -
    # sale | pilot | demo | internal (see ASSIGNMENT_TYPES). Product-agnostic;
    # only the C2C sale path is wired. Distinct from deployment_type (device
    # classification / order channel). Nullable; legacy rows leave it NULL.
    assignment_type = Column(String(32), nullable=True)

    # Per-camera loan return date (Migration 058); NULL = still out. The
    # order-level return status is derived (returned vs still-out).
    returned_date = Column(Date, nullable=True)

    # Deployment visit link (Migration 072): which installation visit put this
    # unit on site. Nullable because units are provisioned before visits are
    # planned; SET NULL so deleting a visit does not delete its units. See
    # docs/specs/link-units-to-deployments.md.
    deployment_record_id = Column(Integer, ForeignKey("deployment_records.id", ondelete="SET NULL"), nullable=True)

    # Zendesk integration (Migration 006)
    zendesk_ticket_id = Column(Integer, nullable=True)

    # Validation report (Migration 008)
    validation_report_path = Column(String(512), nullable=True)
    validation_result = Column(String(16), nullable=True)  # PASS, FAIL, WARN
    validation_date = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    site = relationship("Site")
    assignee = relationship("User", foreign_keys=[assigned_to])
    creator = relationship("User", foreign_keys=[created_by])
    customer_order = relationship("CustomerOrder", back_populates="provisioning_records")
    item = relationship("Item", foreign_keys=[item_id])

    PRIORITY_TYPES = {
        "low": "Low",
        "normal": "Normal",
        "high": "High",
        "urgent": "Urgent",
    }

    DEPLOYMENT_BUCKETS = {
        "customer_po": "Customer POs",
        "confirmed_pilot": "Confirmed Pilots",
        "in_progress": "In Progress",
        "certified": "Certified Devices",
        "in_inventory": "In Inventory",
    }

    # How a provisioned device is assigned (Migration 057). Shared vocabulary;
    # only 'sale' is wired today. pilot/demo/internal are defined-but-not-built.
    ASSIGNMENT_TYPES = {
        "sale": "Sale",
        "pilot": "Pilot",
        "demo": "Demo",
        "internal": "Internal",
    }


# ---------------------------------------------------------------------------
# 26. Customer Orders — track customer orders from Salesforce through delivery
# ---------------------------------------------------------------------------

class CustomerOrder(Base):
    __tablename__ = "customer_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_number = Column(String(32), unique=True, nullable=False)  # AT-2001, AT-2002, …
    salesforce_order_id = Column(String(64), nullable=True)
    salesforce_opp_id = Column(String(64), nullable=True)
    po_number = Column(String(64), unique=True, nullable=True)  # Salesforce customer PO; app-level gate for pipeline entry
    # Order classification (Migration 058) - single source of truth for the order
    # type; see ORDER_TYPES. Backfilled 'sale' for existing orders. Non-sale types
    # (pilot/try_and_buy/demo) carry no PO and are loans. Retires reliance on
    # device_provisioning.assignment_type for classification.
    order_type = Column(String(32), nullable=False, server_default="sale")
    # Loan due date (Migration 058) for non-sale order types; per-camera return
    # lives on device_provisioning.returned_date and order return status derives.
    expected_return = Column(Date, nullable=True)
    # Build ownership (Migration 074, values renamed in 086): in_house or oem,
    # see OWNERS. The partner is set exactly when the OEM owns the order. The CHECK
    # customer_orders_owner_partner_check in migration 074 enforces that, not
    # this model. See docs/specs/order-owner-split-slice-1.md.
    owner = Column(String(16), nullable=False, server_default="in_house")
    oem_partner_id = Column(Integer, ForeignKey("oem_partners.id"), nullable=True)
    customer_name = Column(String(256), nullable=False)
    customer_account = Column(String(256), nullable=True)
    sales_engineer = Column(String(128), nullable=True)
    sales_engineer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deployment_type = Column(String(32), default="direct")  # direct | via_integrator | via_distributor
    integrator_name = Column(String(256), nullable=True)
    distributor_name = Column(String(256), nullable=True)
    default_fulfillment_type = Column(String(32), nullable=True)  # build | prebuilt_software | prebuilt_finished; pre-fills device rows
    due_date = Column(Date, nullable=True)
    status = Column(String(32), default="new")  # new | sourcing | building | testing | shipped | delivered | installed
    sku_requirements = Column(JSONB, default=list)  # [{model, qty, source: stock|oem|tbd}]
    pre_site_survey = Column(Text, nullable=True)
    post_install_notes = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_sensitive = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # ── Shipping fields (migration 021) ──
    shipped_date = Column(Date, nullable=True)
    delivered_date = Column(Date, nullable=True)
    carrier = Column(String(64), nullable=True)
    tracking_number = Column(String(128), nullable=True)
    shipping_address = Column(Text, nullable=True)
    ship_method = Column(String(32), nullable=True)  # 'carrier' or 'transferred'
    recipient_name = Column(String(256), nullable=True)

    sales_engineer_user = relationship("User", foreign_keys=[sales_engineer_id])
    creator = relationship("User", foreign_keys=[created_by])
    provisioning_records = relationship("DeviceProvisioning", back_populates="customer_order")
    oem_pos = relationship("OEMPurchaseOrder", back_populates="customer_order", cascade="all, delete-orphan")
    oem_partner = relationship("OEMPartner")
    deployment_records = relationship(
        "DeploymentRecord",
        back_populates="customer_order",
        cascade="all, delete-orphan",
    )

    ORDER_STATUSES = {
        "new": "New",
        "sourcing": "Sourcing",
        "building": "Building",
        "testing": "Testing",
        "shipped": "Shipped",
        "delivered": "Delivered",
        "installed": "Installed",
        # Terminal (docs/specs/customer-order-cancel.md). Code-mediated:
        # set only by POST /api/orders/{id}/cancel, never by a status
        # edit, and there is no un-cancel.
        "cancelled": "Cancelled",
    }

    STATUS_COLORS = {
        "new": "var(--text-muted)",
        "sourcing": "var(--warning, #f39c12)",
        "building": "var(--info, #3498db)",
        "testing": "var(--info, #3498db)",
        "shipped": "var(--accent, #9b59b6)",
        "delivered": "var(--success, #27ae60)",
        "installed": "var(--success, #27ae60)",
        "cancelled": "var(--danger, #e74c3c)",
    }

    # Order classification vocabulary (Migration 058) - the single source of truth.
    # Non-sale types are loans (no PO). try_and_buy is new; order_type is a plain
    # varchar so this is an app-level addition, no DB enum change.
    ORDER_TYPES = {
        "sale": "Sale/PO",
        "pilot": "Pilot",
        "try_and_buy": "Try and Buy",
        "demo": "Demo",
    }

    # Build ownership vocabulary (migration 074). Plain varchar, app-level
    # vocabulary, same pattern as ORDER_TYPES. See
    # docs/specs/order-owner-split-slice-1.md.
    OWNERS = {
        "in_house": "In-house",
        "oem": "OEM",
    }


class OEMPurchaseOrder(Base):
    __tablename__ = "oem_purchase_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_order_id = Column(Integer, ForeignKey("customer_orders.id", ondelete="SET NULL"), nullable=True)
    vendor_name = Column(String(128), nullable=False)
    po_number = Column(String(64), nullable=True)
    sku = Column(String(128), nullable=False)
    qty_ordered = Column(Integer, nullable=False, default=1)
    qty_received = Column(Integer, nullable=False, default=0)
    order_date = Column(Date, nullable=True)
    expected_delivery = Column(Date, nullable=True)
    received_date = Column(Date, nullable=True)
    status = Column(String(32), default="ordered")  # ordered | in_production | acceptance | receiving | verified | cancelled
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    OEM_STATUSES = [
        "ordered",
        "in_production",
        "acceptance",
        "receiving",
        "verified",
        "cancelled",
    ]

    OEM_STATUS_LABELS = {
        "ordered":       "Ordered",
        "in_production": "In Production",
        "acceptance":    "Acceptance",
        "receiving":     "Receiving",
        "verified":      "Verified",
        "cancelled":     "Cancelled",
    }

    customer_order = relationship("CustomerOrder", back_populates="oem_pos")


class OEMPartner(Base):
    """Who builds, certifies and ships an order (Migration 074).

    Deliberately separate from VendorProfile, which is supplier and
    manufacturer analytics name-matched to inventory strings, and from
    OEMPurchaseOrder.vendor_name, which records who a procurement PO line
    was placed with. See docs/specs/order-owner-split-slice-1.md.
    """
    __tablename__ = "oem_partners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# Deployment Records — post-ship installation tracking
# ---------------------------------------------------------------------------
class DeploymentRecord(Base):
    __tablename__ = "deployment_records"

    id = Column(Integer, primary_key=True)
    customer_order_id = Column(Integer, ForeignKey("customer_orders.id", ondelete="CASCADE"), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    address = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="scheduled")
    scheduled_date = Column(Date, nullable=True)
    installed_date = Column(Date, nullable=True)
    se_assigned_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    integrator_name = Column(String(256), nullable=True)
    integrator_contact = Column(String(256), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # ── Class constants ──
    DEPLOYMENT_STATUSES = [
        "scheduled",
        "in_transit",
        "on_site",
        "installing",
        "complete",
        "cancelled",
    ]

    DEPLOYMENT_STATUS_LABELS = {
        "scheduled": "Scheduled",
        "in_transit": "In Transit",
        "on_site": "On-Site",
        "installing": "Installing",
        "complete": "Complete",
        "cancelled": "Cancelled",
    }

    # ── Relationships ──
    customer_order = relationship("CustomerOrder", back_populates="deployment_records")
    site = relationship("Site", foreign_keys=[site_id])
    se_assigned = relationship("User", foreign_keys=[se_assigned_id])
    creator = relationship("User", foreign_keys=[created_by])


# ---------------------------------------------------------------------------
# User Tour Progress — tracks which guided tours each user has completed
# ---------------------------------------------------------------------------
class UserTourProgress(Base):
    __tablename__ = "user_tour_progress"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tour_id = Column(String(64), nullable=False)
    completed_at = Column(DateTime, server_default=func.now())
    dismissed = Column(Boolean, default=False)

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "tour_id", name="unique_user_tour"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_type = Column(String(64), nullable=False)  # e.g. provisioning_advance
    title = Column(String(256), nullable=False)
    message = Column(Text, nullable=False)
    link = Column(String(512), nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    dismissed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    actor = relationship("User")


class NotificationSubscription(Base):
    """Per-user subscription to specific notification events or provisioning records.

    Subscription types:
    - Global event type:   event_type="provisioning_advance", resource_type=None, resource_id=None
      → DM on every provisioning advance
    - Record watch:        event_type=None, resource_type="provisioning", resource_id=<prov_id>
      → DM on any event for this specific provisioning record
    """
    __tablename__ = "notification_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(64), nullable=True)    # e.g. "provisioning_advance"; NULL = all events for resource
    resource_type = Column(String(64), nullable=True) # e.g. "provisioning"; NULL = global event subscription
    resource_id = Column(Integer, nullable=True)      # specific record ID; NULL = all records of resource_type
    deliver_slack = Column(Boolean, default=True, nullable=False)
    deliver_inapp = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", backref="subscriptions")

    __table_args__ = (
        UniqueConstraint("user_id", "event_type", "resource_type", "resource_id",
                         name="unique_user_subscription"),
    )


# Item 30 S4: the review queue and sidebar count work on item categories.
# edge_box carries the same sites-admin gate as the edge_boxes table did.
CATEGORIES_REQUIRING_SITES_ADMIN = frozenset({"edge_box"})


def user_can_approve_category(user, category: str | None) -> bool:
    """Check if a user may approve or dismiss a pending device of this category."""
    if category in CATEGORIES_REQUIRING_SITES_ADMIN:
        return user.has_sites_admin
    return user.is_editor_or_above


def get_approvable_categories(user) -> list[str]:
    """Item categories the user can approve pending devices into, sorted."""
    return sorted(c for c in item_categories_enum.enums if user_can_approve_category(user, c))


# ---------------------------------------------------------------------------
# item_schema enums
# ---------------------------------------------------------------------------
# item_categories_enum is defined near the top of this module.

item_statuses_enum = SAEnum(
    'Deployed', 'Ready to Deploy', 'Pending', 'Un-deployable',
    'Decommissioned', 'Unassigned',
    'Checked Out',
    'Installed',  # containment-managed (migration 065) — set/cleared by the
                  # install/uninstall routes, absent from hand-edit lists
    name='item_statuses',
    schema='public'
)

# Status vocabulary derivation (docs/specs/item-decommission.md): the enum
# above is the single authority. Code-managed statuses are entered and
# cleared only by their owning routes (checkout/checkin, containment
# install/uninstall, decommission/reactivate); hand-editable lists derive
# by subtraction. A surface that needs one back (receiving's Checked Out)
# declares it as an explicit extra, never as a restated list.
ITEM_STATUSES = list(item_statuses_enum.enums)
CODE_MANAGED_ITEM_STATUSES = ("Checked Out", "Installed", "Decommissioned")
HAND_EDITABLE_ITEM_STATUSES = [
    s for s in ITEM_STATUSES if s not in CODE_MANAGED_ITEM_STATUSES
]

component_actions_enum = SAEnum(
    'installed', 'uninstalled', 'moved',
    name='component_actions',
    schema='public'
)

# item_schema.current_containment — a SQL VIEW (migration 065), THE read path
# for containment state: latest component_history event per component, present
# only while installed/moved. Defined on its OWN MetaData so create_all never
# tries to create it as a table (fresh DBs get the view from db/10_extras.sql +
# migration 065). One-hop parent resolution is correct by invariant: units
# cannot be installed as components, so a parent is never itself contained.
_containment_view_metadata = MetaData()
current_containment = Table(
    "current_containment", _containment_view_metadata,
    Column("component_item_id", Integer, primary_key=True),
    Column("parent_item_id", Integer),
    Column("slot_label", String(100)),
    Column("installed_date", Date),
    Column("event_id", Integer),
    schema="item_schema",
)


# ---------------------------------------------------------------------------
# item_schema.items — unified inventory table (new schema)
# ---------------------------------------------------------------------------
class Item(Base):
    __tablename__ = 'items'
    __table_args__ = {'schema': 'item_schema'}

    id                         = Column(Integer, primary_key=True, autoincrement=True)
    item_name                  = Column(Text, nullable=True)
    item_manufacturer          = Column(String(1024), nullable=True)
    item_model                 = Column(String(1024), nullable=True)
    item_sn                    = Column(String(512), nullable=True)
    item_category              = Column(item_categories_enum, nullable=True)
    item_status                = Column(item_statuses_enum, nullable=True)
    location_id                = Column(Integer, ForeignKey('sites.id', ondelete='SET NULL'), nullable=True)  # Migration 063: sites is the place table
    department_or_owner        = Column(String(1024), nullable=True)
    item_mac_address_1         = Column(String(64), nullable=True)
    item_mac_address_2         = Column(String(64), nullable=True)
    item_storage_size_gb       = Column(Float, nullable=True)
    platform_uuid              = Column(String(512), nullable=True)
    item_sku                   = Column(String(512), ForeignKey('item_schema.part_numbers.item_sku'), nullable=True)
    item_pn                    = Column(String(512), nullable=True)
    item_associated_pn         = Column(String(512), nullable=True)
    # Real FK to public.vendor_profiles (migration 075), ON DELETE SET NULL.
    vendor_id                  = Column(Integer, ForeignKey("vendor_profiles.id", ondelete="SET NULL"), nullable=True)
    item_vendor                = Column(String(1024), nullable=True)
    date_purchased             = Column(Date, nullable=True)
    intended_purpose           = Column(String(1024), nullable=True)
    dispatched_date            = Column(Date, nullable=True)
    tracking_number            = Column(String(512), nullable=True)
    notes                      = Column(Text, nullable=True)
    created_at                 = Column(Date, server_default=text(LOCAL_TODAY_SQL))
    last_updated               = Column(Date, server_default=text(LOCAL_TODAY_SQL), onupdate=literal_column(LOCAL_TODAY_SQL, Date))
    attributes                 = Column(JSONB, nullable=True)

    # Decommission lifecycle (migration 073, docs/specs/item-decommission.md):
    # set by the decommission action, cleared by reactivation. The row and
    # its history survive decommission.
    decommission_reason        = Column(Text, nullable=True)
    decommission_date          = Column(Date, nullable=True)
    decommissioned_by          = Column(String(128), nullable=True)

    # The triage required-field set. Single source: TRIAGE_ROLES in
    # app/routes/triage.py reads this list rather than restating it.
    REQUIRED_FIELDS_HARDWARE = [
        "item_name", "item_manufacturer", "item_model", "item_sn",
        "item_category", "item_status", "location_id",
        "department_or_owner", "item_sku", "item_pn", "vendor_id",
    ]
    # Default — the only triage set, and what the generic dispatcher reads
    REQUIRED_FIELDS = REQUIRED_FIELDS_HARDWARE

    location = relationship('Site', foreign_keys=[location_id])  # Migration 063
    part_number = relationship('ItemPartNumber', foreign_keys=[item_sku])


# Dead after Migration 063 (rows folded into sites; nothing points here).
# Preserved for rollback; drop in a later cleanup migration.
class ItemLocation(Base):
    __tablename__ = 'locations'
    __table_args__ = {'schema': 'item_schema'}

    id               = Column(Integer, primary_key=True, autoincrement=True)
    nickname         = Column(String(255), nullable=False)
    location_type    = Column(String(100), nullable=True)
    address_line_1   = Column(String(255), nullable=True)
    address_line_2   = Column(String(255), nullable=True)
    city             = Column(String(100), nullable=True)
    state            = Column(String(100), nullable=True)
    zip              = Column(String(20), nullable=True)
    country          = Column(String(100), default='United States')
    is_international = Column(Boolean, default=False)
    geo_lat          = Column(Float, nullable=True)
    geo_lng          = Column(Float, nullable=True)
    show_on_map      = Column(Boolean, default=False)
    contact_name     = Column(String(255), nullable=True)
    contact_email    = Column(String(255), nullable=True)
    contact_phone    = Column(String(50), nullable=True)
    customer         = Column(String(255), nullable=True)
    is_active        = Column(Boolean, default=True)
    notes            = Column(Text, nullable=True)
    created_at       = Column(Date, server_default=text(LOCAL_TODAY_SQL))
    last_updated     = Column(Date, server_default=text(LOCAL_TODAY_SQL))


class ItemPartNumber(Base):
    __tablename__ = 'part_numbers'
    __table_args__ = {'schema': 'item_schema'}

    id              = Column(Integer, primary_key=True, autoincrement=True)
    item_sku        = Column(String(512), unique=True, nullable=False)
    sku_description = Column(Text, nullable=True)
    item_category   = Column(item_categories_enum, nullable=True)
    is_legacy       = Column(Boolean, default=False)
    is_customer_pn  = Column(Boolean, default=False)
    location_id     = Column(Integer, ForeignKey('sites.id', ondelete='SET NULL'), nullable=True)  # Migration 063
    created_by      = Column(String(100), nullable=True)
    created_at      = Column(Date, server_default=text(LOCAL_TODAY_SQL))
    notes           = Column(Text, nullable=True)


class ItemReceipt(Base):
    __tablename__ = 'receipts'
    __table_args__ = {'schema': 'item_schema'}

    id                = Column(Integer, primary_key=True, autoincrement=True)
    # Real FK to public.vendor_profiles (migration 075), ON DELETE SET NULL.
    vendor_id         = Column(Integer, ForeignKey("vendor_profiles.id", ondelete="SET NULL"), nullable=True)
    purchase_order    = Column(String(100), nullable=True)
    record_type       = Column(String(20), nullable=False)
    transaction_date  = Column(Date, nullable=False)
    file_path         = Column(String(500), nullable=True)
    original_filename = Column(String(255), nullable=True)
    notes             = Column(Text, nullable=True)
    created_by        = Column(String(100), nullable=False)
    created_at        = Column(Date, server_default=text(LOCAL_TODAY_SQL))


class ReceiptItem(Base):
    __tablename__ = 'receipt_items'
    __table_args__ = {'schema': 'item_schema'}

    id         = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer, ForeignKey('item_schema.receipts.id'), nullable=False)
    item_id    = Column(Integer, ForeignKey('item_schema.items.id'), nullable=False)
    quantity   = Column(Integer, default=1)
    notes      = Column(Text, nullable=True)

    receipt = relationship('ItemReceipt', foreign_keys=[receipt_id])
    item    = relationship('Item', foreign_keys=[item_id])


class ItemMaintenanceLog(Base):
    __tablename__ = 'maintenance_log'
    __table_args__ = {'schema': 'item_schema'}

    # The entry types the item page offers. entry_type is a plain varchar, so
    # this list is the only vocabulary; the page renders 'firmware_update' as
    # 'Firmware Update'.
    ENTRY_TYPES = ("inspection", "repair", "cleaning", "firmware_update",
                   "part_replacement", "calibration", "other")

    id               = Column(Integer, primary_key=True, autoincrement=True)
    item_id          = Column(Integer, ForeignKey('item_schema.items.id'), nullable=False)
    entry_type       = Column(String(50), nullable=False)
    description      = Column(Text, nullable=False)
    performed_by     = Column(String(100), nullable=True)
    maintenance_date = Column(Date, server_default=text(LOCAL_TODAY_SQL))
    component_id     = Column(Integer, nullable=True)
    created_by       = Column(String(100), nullable=False)
    created_at       = Column(Date, server_default=text(LOCAL_TODAY_SQL))

    item = relationship('Item', foreign_keys=[item_id])


class ItemComponentHistory(Base):
    __tablename__ = 'component_history'
    __table_args__ = {'schema': 'item_schema'}

    id             = Column(Integer, primary_key=True, autoincrement=True)
    item_id        = Column(Integer, ForeignKey('item_schema.items.id'), nullable=False)
    parent_item_id = Column(Integer, ForeignKey('item_schema.items.id'), nullable=True)
    action         = Column(component_actions_enum, nullable=False)
    slot_label     = Column(String(100), nullable=True)
    action_date    = Column(Date, server_default=text(LOCAL_TODAY_SQL))
    performed_by   = Column(String(100), nullable=True)
    notes          = Column(Text, nullable=True)
    created_at     = Column(Date, server_default=text(LOCAL_TODAY_SQL))

    item        = relationship('Item', foreign_keys=[item_id])
    parent_item = relationship('Item', foreign_keys=[parent_item_id])


class ItemCheckout(Base):
    __tablename__ = 'checkouts'
    __table_args__ = {'schema': 'item_schema'}

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    item_id                = Column(Integer, ForeignKey('item_schema.items.id'), nullable=False)
    checked_out_to_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    checked_out_to_name    = Column(String(255), nullable=True)
    checkout_date          = Column(Date, server_default=text(LOCAL_TODAY_SQL), nullable=False)
    checkin_date           = Column(Date, nullable=True)
    prior_status           = Column(item_statuses_enum, nullable=True)
    checked_out_by         = Column(String(100), nullable=True)
    notes                  = Column(Text, nullable=True)
    created_at             = Column(Date, server_default=text(LOCAL_TODAY_SQL))

    item                = relationship('Item', foreign_keys=[item_id])
    checked_out_to_user = relationship('User', foreign_keys=[checked_out_to_user_id])


class BuildCertification(Base):
    __tablename__ = "build_certification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_provisioning_id = Column(
        Integer, ForeignKey("device_provisioning.id", ondelete="CASCADE"), nullable=False
    )
    device_uuid = Column(String(64), nullable=True)
    hardware_validation = Column(JSONB, nullable=True)
    software_version = Column(String(64), nullable=True)
    license_counts = Column(JSONB, nullable=True)
    qa_checklist = Column(JSONB, nullable=True)
    certified_by = Column(String(128), nullable=True)
    co_certified_by = Column(String(128), nullable=True)
    certified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    oem_serial      = Column(String(64), nullable=True)
    reason          = Column(String(20), nullable=False, server_default="initial")
    qa_status       = Column(String(20), nullable=False, server_default="pending")
    hw_status       = Column(String(20), nullable=False, server_default="pending")
    cert_status     = Column(String(20), nullable=False, server_default="pending")
    co_certified_at = Column(DateTime, nullable=True)
    customer_name   = Column(String(256), nullable=True)
    order_number    = Column(String(64), nullable=True)
    sku             = Column(String(128), nullable=True)
    # C2C-mimic cancel event fields (migration 061): a cancel is a NEW append-only
    # row with cert_status='cancelled' carrying these; certify rows leave them NULL.
    cancel_reason = Column(Text, nullable=True)
    cancelled_by = Column(String(128), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)


class BuildCertificationFile(Base):
    __tablename__ = "build_certification_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    build_certification_id = Column(
        Integer, ForeignKey("build_certification.id", ondelete="CASCADE"), nullable=False
    )
    kind = Column(String(16), nullable=False, server_default="source")   # 'source' | 'composite'
    oem_serial = Column(String(64), nullable=True)
    original_name = Column(String(512), nullable=False)
    stored_name = Column(String(512), nullable=False)
    content_type = Column(String(128), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_by = Column(String(128), nullable=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=func.now())


class InstallationCertification(Base):
    __tablename__ = "installation_certification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    deployment_record_id = Column(
        Integer, ForeignKey("deployment_records.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    status = Column(String(16), nullable=False, server_default="pending")
    installer_name = Column(String(128), nullable=True)
    installer_company = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)
    completion_date = Column(Date, nullable=True)
    pdf_original_name = Column(String(256), nullable=True)
    pdf_stored_name = Column(String(256), nullable=True)
    pdf_content_type = Column(String(128), nullable=True)
    pdf_size_bytes = Column(Integer, nullable=True)
    certified_by = Column(String(128), nullable=True)
    certified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    created_by = Column(String(128), nullable=True)


class C2CCertification(Base):
    __tablename__ = "c2c_certification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_provisioning_id = Column(
        Integer, ForeignKey("device_provisioning.id", ondelete="CASCADE"),
        nullable=False
    )
    # Snapshot of the camera serial at certification, for lifetime history.
    camera_serial_snapshot = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, server_default="pending")  # pending | certified
    # Checklist booleans: {powered_on, firmware_verified, qr_site_connected, registered}
    checklist = Column(JSONB, nullable=True)
    # Point-in-time firmware/plugin/license evidence; shape iterates (JSONB, migration-free).
    firmware_evidence = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    certified_by = Column(String(128), nullable=True)   # internal certifier display_name
    certified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    created_by = Column(String(128), nullable=True)
    # Append-only cancel event (Migration 059): a cancel is a NEW row with
    # status="cancelled" carrying reason + who + when; certify events leave these NULL.
    cancel_reason = Column(Text, nullable=True)
    cancelled_by = Column(String(128), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)


class C2CCertificationFile(Base):
    """Source files + generated composite for a C2C cert EVENT (append-only). Bytes on disk
    under C2C_CERT_UPLOAD_DIR/<camera_serial>/<stored_name>; only metadata in the DB."""
    __tablename__ = "c2c_certification_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    c2c_certification_id = Column(
        Integer, ForeignKey("c2c_certification.id", ondelete="CASCADE"), nullable=False
    )
    camera_serial = Column(String(64), nullable=True)   # lifetime anchor for the on-disk subdir
    kind = Column(String(16), nullable=False, server_default="source")   # 'source' | 'composite'
    original_name = Column(String(512), nullable=False)
    stored_name = Column(String(512), nullable=False)
    content_type = Column(String(128), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_by = Column(String(128), nullable=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=func.now())

# ----
# Map visibility curation (Migration 062)
# ----
class MapVisibility(Base):
    """Server-side map curation flags (deployment map redesign).

    level: customer | site | unit. key is the normalized identity:
    customers/sites use lower(trim(free-text name)) because customer and
    site are strings across the schema, not tables; units use
    'item:{id}' / 'edge_box:{id}' because item_schema items carry no
    per-unit map flag column (legacy edge_boxes.show_on_map is honored
    in addition). Presence of a row means HIDDEN; unhide deletes it.
    Read through app/map_visibility.py, never directly in routes.
    """
    __tablename__ = "map_visibility"
    __table_args__ = (
        UniqueConstraint("level", "key", name="uq_map_visibility_level_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(16), nullable=False)
    key = Column(String(512), nullable=False)
    label = Column(String(512), nullable=True)
    hidden_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ----
# Delete request queue (Migration 078, docs/specs/delete-request-queue.md)
# ----
class DeleteRequest(Base):
    """A request to delete an item or a vendor profile.

    Filed by editor tier and above, decided by admin tier. target_id has no
    foreign key because the target is gone once a request is approved;
    target_label keeps the history readable. At most one pending request per
    target (partial unique index, migration 078). Read and written through
    app/delete_requests.py and app/routes/delete_requests.py.
    """
    __tablename__ = "delete_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_table = Column(String(32), nullable=False)
    target_id = Column(Integer, nullable=False)
    target_label = Column(String(256), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    requested_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    decided_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)

    requester = relationship("User", foreign_keys=[requested_by])
    decider = relationship("User", foreign_keys=[decided_by])

