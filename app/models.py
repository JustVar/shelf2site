"""SQLAlchemy ORM models for the hardware inventory system.

15 inventory tables + 5 system tables + 2 intake tables + 2 site tables:
  - device_credentials (encrypted vault)
  - users (individual accounts, bcrypt)
  - audit_log (full audit trail)
  - oui_allowlist (dashboard-configurable OUI prefixes)
  - pending_devices (approval queue for auto-discovered devices)
  - receiving_events (shipment intake tracking)
  - intake_photos (label photos for receiving events/devices)
  - sites (physical locations / customer sites)
  - device_assignments (device-to-site ownership tracking)
"""

from datetime import datetime

from sqlalchemy import (
    Enum as SAEnum,
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, LargeBinary,
    MetaData, Numeric, String, Table, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import MACADDR
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.orm import relationship

from .database import Base


# ---------------------------------------------------------------------------
# Mixin for common columns shared by all inventory tables
# ---------------------------------------------------------------------------
class InventoryMixin:
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    data_completeness = Column(Float, default=0.0)
    discovered_by = Column(String(64), default="manual")  # manual | scanner:<id> | intune_import
    network_segment = Column(String(32), nullable=True)  # lab | office | customer
    last_seen = Column(DateTime, nullable=True)

    # Procurement tracking (applies to all inventory items)
    vendor = Column(String(128), nullable=True)  # Supplier/vendor (e.g., B&H, Amazon, CDW)
    purchase_date = Column(Date, nullable=True)  # Order/purchase date
    purchase_price = Column(Numeric(10, 2), nullable=True)  # Purchase cost
    purchase_order = Column(String(64), nullable=True)  # PO number
    supplier_invoice = Column(String(128), nullable=True)  # Invoice number
    procurement_method = Column(String(32), nullable=True)  # direct_purchase | rental | donation | transfer | trial | warranty_replacement


# ---------------------------------------------------------------------------
# 1. Edge Boxes (merged: Edge Boxes + Customer Edge Boxes + Pilots)
# ---------------------------------------------------------------------------
class EdgeBox(InventoryMixin, Base):
    __tablename__ = "edge_boxes"

    org = Column(String(255), nullable=True)
    customer = Column(String(255), nullable=True)
    site_name = Column(String(255), nullable=True)
    serial = Column(String(64), nullable=True)
    status = Column(String(64), nullable=True)
    part_number = Column(String(64), nullable=True)
    sku_version = Column(String(16), default="legacy", nullable=False)  # "legacy" (PVA-*) or "2026" (EDGE*)
    warranty_id = Column(String(64), nullable=True)
    mac_address = Column(String(64), nullable=True, unique=True)
    mac_address_2 = Column(String(64), nullable=True)
    external_id = Column(String(64), nullable=True)
    uuid = Column(String(128), nullable=True)
    last_updated = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    location = Column(String(100), nullable=True)
    form_factor = Column(String(20), nullable=True)
    partner = Column(String(100), nullable=True)
    incomplete_reason = Column(Text, nullable=True)
    pilot_type = Column(String(32), nullable=True)  # Partner | Customer
    deployment_type = Column(String(32), nullable=True)  # internal | customer | pilot | demo | trade_show
    geo_lat = Column(Float, nullable=True)
    geo_lng = Column(Float, nullable=True)
    show_on_map = Column(Boolean, default=True, nullable=False)  # Admin-only: privacy control for customer deployments

    REQUIRED_FIELDS = ["serial", "mac_address", "part_number", "status", "deployment_type", "location", "form_factor"]
    CUSTOMER_REQUIRED_FIELDS = ["serial", "mac_address", "part_number", "status", "deployment_type", "location", "form_factor"]
    CUSTOMER_DEPLOYMENT_TYPES = ["customer", "pilot", "demo"]


# ---------------------------------------------------------------------------
# 3. GPUs
# ---------------------------------------------------------------------------
class GPU(InventoryMixin, Base):
    __tablename__ = "gpus"

    gpu_serial = Column(String(64), nullable=True)
    model = Column(String(128), nullable=True)
    status = Column(String(64), nullable=True)
    associated_device_serial = Column(String(64), nullable=True)
    last_updated = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["gpu_serial", "model", "status"]


# ---------------------------------------------------------------------------
# 4. Part Numbers (reference table)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. Monitors
# ---------------------------------------------------------------------------
class Monitor(InventoryMixin, Base):
    __tablename__ = "monitors"

    device = Column(String(255), nullable=True)
    model = Column(String(128), nullable=True)
    model_code = Column(String(64), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)

    REQUIRED_FIELDS = ["device", "serial", "location"]


# ---------------------------------------------------------------------------
# 6. Computers (merged: Computers + All Computers/Intune)
# ---------------------------------------------------------------------------
class Computer(InventoryMixin, Base):
    __tablename__ = "computers"

    device = Column(String(255), nullable=True)
    device_name = Column(String(128), nullable=True)
    model = Column(String(128), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)
    # Intune fields
    intune_device_id = Column(String(128), nullable=True)
    intune_compliance = Column(String(32), nullable=True)
    os = Column(String(64), nullable=True)
    os_version = Column(String(64), nullable=True)
    primary_user_upn = Column(String(255), nullable=True)
    intune_last_checkin = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["device_name", "serial", "assigned_to"]


# ---------------------------------------------------------------------------
# 7. Phones
# ---------------------------------------------------------------------------
class Phone(InventoryMixin, Base):
    __tablename__ = "phones"

    device = Column(String(255), nullable=True)
    model = Column(String(128), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)

    REQUIRED_FIELDS = ["device", "serial", "assigned_to"]


# ---------------------------------------------------------------------------
# 8. Mobile Devices (testing devices)
# ---------------------------------------------------------------------------
class MobileDevice(InventoryMixin, Base):
    __tablename__ = "mobile_devices"

    device = Column(String(255), nullable=True)
    model_name = Column(String(128), nullable=True)
    model_number = Column(String(64), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)  # PINs stripped, moved to credentials vault

    REQUIRED_FIELDS = ["device", "serial", "assigned_to"]


# ---------------------------------------------------------------------------
# 9. Cameras
# ---------------------------------------------------------------------------
class Camera(InventoryMixin, Base):
    __tablename__ = "cameras"

    manufacturer = Column(String(128), nullable=True)
    model = Column(String(128), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    device_name = Column(String(128), nullable=True)
    ip_address = Column(String(45), nullable=True)
    mac_address = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)  # Credentials stripped, moved to vault
    deployment_type = Column(String(32), nullable=True, default='internal')

    REQUIRED_FIELDS = ["manufacturer", "model", "serial", "deployment_type"]
    CUSTOMER_REQUIRED_FIELDS = ["manufacturer", "model", "serial", "deployment_type", "location"]
    CUSTOMER_DEPLOYMENT_TYPES = ["customer", "pilot", "demo"]


# ---------------------------------------------------------------------------
# 10. Network Equipment
# ---------------------------------------------------------------------------
class NetworkEquipment(InventoryMixin, Base):
    __tablename__ = "network_equipment"

    device = Column(String(255), nullable=True)
    model_name = Column(String(128), nullable=True)
    model_number = Column(String(64), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)

    REQUIRED_FIELDS = ["device", "serial"]


# ---------------------------------------------------------------------------
# 11. Access Control
# ---------------------------------------------------------------------------
class AccessControl(InventoryMixin, Base):
    __tablename__ = "access_control"

    manufacturer = Column(String(128), nullable=True)
    model = Column(String(128), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    device_name = Column(String(128), nullable=True)
    ip_address = Column(String(45), nullable=True)
    mac_address = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    deployment_type = Column(String(32), nullable=True, default='internal')

    REQUIRED_FIELDS = ["manufacturer", "model", "serial", "deployment_type"]
    CUSTOMER_REQUIRED_FIELDS = ["manufacturer", "model", "serial", "deployment_type", "location"]
    CUSTOMER_DEPLOYMENT_TYPES = ["customer", "pilot", "demo"]


# ---------------------------------------------------------------------------
# 12. Webcams
# ---------------------------------------------------------------------------
class Webcam(InventoryMixin, Base):
    __tablename__ = "webcams"

    device = Column(String(255), nullable=True)
    model = Column(String(128), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)

    REQUIRED_FIELDS = ["device", "serial", "assigned_to"]


# ---------------------------------------------------------------------------
# 13. Printers
# ---------------------------------------------------------------------------
class Printer(InventoryMixin, Base):
    __tablename__ = "printers"

    device = Column(String(255), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)  # Credentials stripped, moved to vault

    REQUIRED_FIELDS = ["device", "serial"]


# ---------------------------------------------------------------------------
# 14. Office Equipment
# ---------------------------------------------------------------------------
class OfficeEquipment(InventoryMixin, Base):
    __tablename__ = "office_equipment"

    device = Column(String(255), nullable=True)
    model_name = Column(String(128), nullable=True)
    model_number = Column(String(64), nullable=True)
    serial = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    purpose = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)

    REQUIRED_FIELDS = ["device", "serial"]


# ---------------------------------------------------------------------------
# 15. NAS Devices (dual-NIC, bay-based storage appliances)
# ---------------------------------------------------------------------------
class NASDevice(InventoryMixin, Base):
    __tablename__ = "nas_devices"

    model = Column(String(128), nullable=True)
    serial = Column(String(64), nullable=True, unique=True)
    manufacturer = Column(String(128), nullable=True)
    mac_address_1 = Column(String(64), nullable=True)
    mac_address_2 = Column(String(64), nullable=True)
    bay_count = Column(Integer, nullable=True)
    ram_gb = Column(String(32), nullable=True)
    firmware_version = Column(String(64), nullable=True)
    location = Column(String(255), nullable=True)
    status = Column(String(64), nullable=True)
    assigned_to = Column(String(128), nullable=True)
    ip_address = Column(String(45), nullable=True)
    purchase_order = Column(String(64), nullable=True)
    receiving_event_id = Column(Integer, ForeignKey("receiving_events.id"), nullable=True)
    notes = Column(Text, nullable=True)

    REQUIRED_FIELDS = ["model", "serial", "manufacturer", "status"]

    # Relationship to individual drives
    drives = relationship("NASDrive", back_populates="nas_device", cascade="all, delete-orphan")


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


# ---------------------------------------------------------------------------
# Intake Photos (label photos for receiving events / devices)
# ---------------------------------------------------------------------------
class IntakePhoto(Base):
    __tablename__ = "intake_photos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receiving_event_id = Column(Integer, ForeignKey("receiving_events.id"), nullable=True)
    device_table = Column(String(64), nullable=True)
    device_id = Column(Integer, nullable=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=True)
    content_type = Column(String(64), nullable=True)
    file_size = Column(Integer, nullable=True)
    caption = Column(String(255), nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 16. Encrypted Credentials Vault
# ---------------------------------------------------------------------------
class DeviceCredential(Base):
    __tablename__ = "device_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_table = Column(String(64), nullable=False)  # e.g., "cameras", "printers"
    device_id = Column(Integer, nullable=False)
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
    "can_view_financial", "can_manage_warranty", "can_manage_trials",
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
    can_view_financial = Column(department_permission_state, nullable=False, server_default='block')
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
    can_view_financial = Column(user_permission_state, nullable=False, server_default='inherit')
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
    _ADMIN_LEVEL_ROLES = ("justin_admin", "system_admin", "admin", "ceo")

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
    def has_financial_access(self):
        return (self.role in self._ADMIN_LEVEL_ROLES + ("procurement_admin",)
                or self._resolve_perm("can_view_financial")
                or self._resolve_perm("can_manage_procurement"))

    @property
    def is_editor_or_above(self):
        return self.role in self._ADMIN_LEVEL_ROLES + ("editor", "warranty_admin", "trials_admin", "procurement_admin")

    @property
    def has_any_admin(self):
        return (self.role in self._ADMIN_LEVEL_ROLES + ("warranty_admin", "trials_admin", "procurement_admin")
                or self._resolve_perm("can_view_financial") or self._resolve_perm("can_manage_warranty")
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
        return (self.role in self._ADMIN_LEVEL_ROLES + ("warranty_admin", "trials_admin", "procurement_admin")
                or self._resolve_perm("can_view_audit_log"))

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
    suggested_table = Column(String(64), nullable=True)
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
# 20. Device Warranties (polymorphic warranty tracking)
# ---------------------------------------------------------------------------
class DeviceWarranty(InventoryMixin, Base):
    __tablename__ = "device_warranties"

    device_table = Column(String(64), nullable=False)
    device_id = Column(Integer, nullable=False)

    warranty_scope = Column(String(16), nullable=False, default="external")  # external | internal
    warranty_tier = Column(String(32))  # standard | extended | premium
    vendor = Column(String(128))
    purchase_date = Column(Date)
    warranty_start = Column(Date)
    warranty_end = Column(Date)
    warranty_type = Column(String(64))  # manufacturer | third-party | extended
    warranty_holder = Column(String(32), default="brand")  # brand | oem | vendor | customer
    registration_number = Column(String(128), unique=True)
    coverage_details = Column(Text)
    auto_renew = Column(Boolean, default=False)
    renewal_cost = Column(Numeric(10, 2))
    registration_status = Column(String(32))  # registered | not_registered | not_required

    # Internal loaner fields (only used when warranty_scope='internal')
    loaner_from_team = Column(String(128))
    loaner_to_team = Column(String(128))
    loaner_contact = Column(String(128))
    loaner_agreement = Column(String(128))

    claims = relationship("WarrantyClaim", back_populates="warranty", cascade="all, delete-orphan")

    REQUIRED_FIELDS = ["device_table", "device_id", "warranty_end", "vendor"]


# ---------------------------------------------------------------------------
# 21. Warranty Claims / RMA Tracking
# ---------------------------------------------------------------------------
class WarrantyClaim(Base):
    __tablename__ = "warranty_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    warranty_id = Column(Integer, ForeignKey("device_warranties.id", ondelete="CASCADE"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    claim_number = Column(String(128), unique=True)
    claim_date = Column(Date, nullable=False)
    issue_description = Column(Text)
    claim_status = Column(String(32))  # opened | approved | shipped | received | closed | denied

    rma_number = Column(String(128))
    tracking_number = Column(String(128))
    shipped_date = Column(Date)
    expected_return = Column(Date)
    received_date = Column(Date)
    replacement_device_sn = Column(String(128))
    resolution_notes = Column(Text)

    warranty = relationship("DeviceWarranty", back_populates="claims")

    REQUIRED_FIELDS = ["warranty_id", "claim_date", "claim_status"]


# ---------------------------------------------------------------------------
# 22. Vendor Trials (Try & Buy evaluation tracking)
# ---------------------------------------------------------------------------
class VendorTrial(InventoryMixin, Base):
    __tablename__ = "vendor_trials"

    device_table = Column(String(64), nullable=False)
    device_id = Column(Integer, nullable=False)

    vendor = Column(String(128), nullable=False)
    trial_type = Column(String(64))  # evaluation | demo | extended_trial
    received_date = Column(Date, nullable=False)
    return_deadline = Column(Date, nullable=False)
    decision_deadline = Column(Date)

    trial_status = Column(String(32))  # active | approved_purchase | returned | extended | overdue
    decision = Column(String(32))  # pending | approved | declined
    decision_date = Column(Date)
    decision_notes = Column(Text)

    purchase_order = Column(String(128))
    purchase_price = Column(Numeric(10, 2))

    return_tracking = Column(String(128))
    returned_date = Column(Date)

    evaluation_notes = Column(Text)
    test_results = Column(Text)
    pros = Column(Text)
    cons = Column(Text)

    REQUIRED_FIELDS = ["device_table", "device_id", "vendor", "received_date", "return_deadline"]


# ---------------------------------------------------------------------------
# 23. Device Dispositions (EOL / disposal tracking)
# ---------------------------------------------------------------------------
class DeviceDisposition(InventoryMixin, Base):
    __tablename__ = "device_dispositions"

    device_table = Column(String(64), nullable=False)
    device_id = Column(Integer, nullable=False)

    disposition_type = Column(String(32))  # recycled | donated | sold | destroyed | archived
    disposition_date = Column(Date, nullable=False)
    reason = Column(Text)

    sanitization_method = Column(String(64))  # dod_wipe | nist_clear | physical_destruction | degauss
    sanitization_date = Column(Date)
    sanitization_verified_by = Column(String(128))
    certificate_number = Column(String(128))
    certificate_file_path = Column(String(512))

    transferred_to = Column(String(128))
    transfer_method = Column(String(64))  # sold | donated | recycled
    transfer_value = Column(Numeric(10, 2))
    transfer_notes = Column(Text)

    REQUIRED_FIELDS = ["device_table", "device_id", "disposition_type", "disposition_date"]


# ---------------------------------------------------------------------------
# 24. NAS Drives (individual drive/component tracking)
# ---------------------------------------------------------------------------
class NASDrive(InventoryMixin, Base):
    __tablename__ = "nas_drives"

    nas_device_id = Column(Integer, ForeignKey("nas_devices.id", ondelete="CASCADE"), nullable=False)
    bay_number = Column(Integer, nullable=False)

    serial_number = Column(String(128), unique=True)
    manufacturer = Column(String(128))
    model = Column(String(128))
    capacity_gb = Column(Integer)
    drive_type = Column(String(32))  # hdd | ssd | nvme
    interface = Column(String(32))  # sata | sas | nvme

    drive_status = Column(String(32))  # active | failed | removed | standby
    install_date = Column(Date)
    removal_date = Column(Date)
    health_status = Column(String(32))  # good | warning | critical
    smart_data = Column(Text)

    warranty_end = Column(Date)

    nas_device = relationship("NASDevice", back_populates="drives")

    REQUIRED_FIELDS = ["nas_device_id", "bay_number", "serial_number"]

    __table_args__ = (
        UniqueConstraint("nas_device_id", "bay_number", name="unique_nas_bay"),
    )


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

    assignments = relationship("DeviceAssignment", back_populates="site", cascade="all, delete-orphan")

    SITE_TYPES = {
        "internal_lab": "Internal Lab",
        "customer_site": "Customer Site",
        "partner": "Partner",
        "warehouse": "Warehouse",
        "office": "Office",
    }


# ---------------------------------------------------------------------------
# 26. Device Assignments (polymorphic device-to-site + ownership tracking)
# ---------------------------------------------------------------------------
class DeviceAssignment(Base):
    __tablename__ = "device_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_table = Column(String(64), nullable=False)
    device_id = Column(Integer, nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    ownership = Column(String(32), nullable=False)  # owned | partner_loaner | customer_loaner | evaluation
    assigned_date = Column(Date, server_default=func.now())
    expected_return = Column(Date, nullable=True)  # For loaners/evaluations
    returned_date = Column(Date, nullable=True)
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)  # False when returned/reassigned
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    site = relationship("Site", back_populates="assignments")

    OWNERSHIP_TYPES = {
        "owned": "Owned",
        "partner_loaner": "Partner Loaner",
        "customer_loaner": "Customer Loaner",
        "evaluation": "Evaluation",
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
    device_table = Column(String(64), nullable=False)
    device_id = Column(Integer, nullable=False)
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

    # C2C option D link (Migration 056): points a provisioning row at a camera
    # entered as unified inventory (item_schema.items) instead of a legacy public.*
    # row. Nullable; legacy rows leave it NULL. See docs/specs/c2c-catalog-and-accessories.md.
    item_id = Column(Integer, ForeignKey("item_schema.items.id", ondelete="SET NULL"), nullable=True)

    # Assignment type (Migration 057): how a provisioned device is assigned -
    # sale | pilot | demo | internal (see ASSIGNMENT_TYPES). Product-agnostic;
    # only the C2C sale path is wired. Distinct from deployment_type (device
    # classification / order channel). Nullable; legacy rows leave it NULL.
    assignment_type = Column(String(32), nullable=True)

    # Per-camera loan return date (Migration 058); NULL = still out. The
    # order-level return status is derived (returned vs still-out).
    returned_date = Column(Date, nullable=True)

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
    contract_value = Column(Numeric(12, 2), nullable=True)
    hardware_cost = Column(Numeric(12, 2), nullable=True)
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
    }

    STATUS_COLORS = {
        "new": "var(--text-muted)",
        "sourcing": "var(--warning, #f39c12)",
        "building": "var(--info, #3498db)",
        "testing": "var(--info, #3498db)",
        "shipped": "var(--accent, #9b59b6)",
        "delivered": "var(--success, #27ae60)",
        "installed": "var(--success, #27ae60)",
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


class IntuneSyncLog(Base):
    """Tracks each Intune device sync run (manual or scheduled)."""
    __tablename__ = "intune_sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    synced_at = Column(DateTime, server_default=func.now())
    synced_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    devices_found = Column(Integer, default=0, nullable=False)
    devices_added = Column(Integer, default=0, nullable=False)
    devices_updated = Column(Integer, default=0, nullable=False)
    devices_skipped = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default="pending", nullable=False)  # pending | running | success | error
    error_message = Column(Text, nullable=True)

    triggered_by = relationship("User")


# ---------------------------------------------------------------------------
# Device components — generic parent↔component join table
# ---------------------------------------------------------------------------
class DeviceComponent(Base):
    __tablename__ = 'device_components'

    id              = Column(Integer, primary_key=True)
    parent_table    = Column(String(50), nullable=False)
    parent_id       = Column(Integer, nullable=False)
    component_table = Column(String(50), nullable=False)
    component_id    = Column(Integer, nullable=False)
    slot_label      = Column(String(50))
    installed_date  = Column(Date)
    removed_date    = Column(Date)
    installed_by    = Column(String(100))
    notes           = Column(Text)
    created_at      = Column(DateTime, default=datetime.utcnow)

    @property
    def is_active(self):
        return self.removed_date is None


# ---------------------------------------------------------------------------
# 17. NUCs
# ---------------------------------------------------------------------------
class NUC(InventoryMixin, Base):
    __tablename__ = "nucs"

    serial = Column(String(64), nullable=True)
    status = Column(String(64), nullable=True)
    location = Column(String(100), nullable=True)
    mac_address = Column(String(64), nullable=True, unique=True)
    mac_address_2 = Column(String(64), nullable=True)
    uuid = Column(String(128), nullable=True)
    purpose = Column(Text, nullable=True)
    org = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    last_updated = Column(DateTime, nullable=True)
    deployment_type = Column(String(32), nullable=True, default='internal')

    REQUIRED_FIELDS = ["serial", "status", "location", "deployment_type"]
    CUSTOMER_REQUIRED_FIELDS = ["serial", "status", "location", "deployment_type", "mac_address"]
    CUSTOMER_DEPLOYMENT_TYPES = ["customer", "pilot", "demo"]


# ---------------------------------------------------------------------------
# 18. UPS
# ---------------------------------------------------------------------------
class UPS(InventoryMixin, Base):
    __tablename__ = "ups"

    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    serial = Column(String(64), nullable=True)
    va_rating = Column(String(32), nullable=True)
    wattage = Column(String(32), nullable=True)
    location = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    last_updated = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["manufacturer", "model", "serial", "location"]


# ---------------------------------------------------------------------------
# 19. RAM Modules
# ---------------------------------------------------------------------------
class RamModule(InventoryMixin, Base):
    __tablename__ = "ram_modules"

    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    ram_type = Column(String(32), nullable=True)
    serial = Column(String(64), nullable=True)
    capacity_gb = Column(Integer, nullable=True)
    speed_mhz = Column(Integer, nullable=True)
    status = Column(String(64), nullable=True)
    location = Column(String(100), nullable=True)
    associated_device_serial = Column(String(64), nullable=True)
    last_updated = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["manufacturer", "ram_type", "capacity_gb", "status"]


# ---------------------------------------------------------------------------
# 20. CPUs
# ---------------------------------------------------------------------------
class CPU(InventoryMixin, Base):
    __tablename__ = "cpus"

    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    socket = Column(String(32), nullable=True)
    serial = Column(String(64), nullable=True)
    status = Column(String(64), nullable=True)
    location = Column(String(100), nullable=True)
    associated_device_serial = Column(String(64), nullable=True)
    last_updated = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["manufacturer", "model", "status"]


# ---------------------------------------------------------------------------
# 21. PSUs
# ---------------------------------------------------------------------------
class PSU(InventoryMixin, Base):
    __tablename__ = "psus"

    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    serial = Column(String(64), nullable=True)
    wattage_rating = Column(String(32), nullable=True)
    efficiency = Column(String(32), nullable=True)
    status = Column(String(64), nullable=True)
    location = Column(String(100), nullable=True)
    associated_device_serial = Column(String(64), nullable=True)
    last_updated = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["manufacturer", "model", "serial", "status"]


# ---------------------------------------------------------------------------
# 22. Motherboards
# ---------------------------------------------------------------------------
class Motherboard(InventoryMixin, Base):
    __tablename__ = "motherboards"

    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    socket = Column(String(32), nullable=True)
    serial = Column(String(64), nullable=True)
    status = Column(String(64), nullable=True)
    associated_device_serial = Column(String(64), nullable=True)
    last_updated = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["manufacturer", "model", "serial", "status"]


# ---------------------------------------------------------------------------
# 23. PC Cooling
# ---------------------------------------------------------------------------
class PCCooling(InventoryMixin, Base):
    __tablename__ = "pc_cooling"

    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    cooling_type = Column(String(32), nullable=True)
    serial = Column(String(64), nullable=True)
    speed_rpm = Column(String(32), nullable=True)
    status = Column(String(64), nullable=True)
    associated_device_serial = Column(String(64), nullable=True)
    location = Column(String(100), nullable=True)
    last_updated = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["manufacturer", "model", "status"]


# ---------------------------------------------------------------------------
# 24. PC Accessories
# ---------------------------------------------------------------------------
class PCAccessory(InventoryMixin, Base):
    __tablename__ = "pc_accessories"

    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    accessory_type = Column(String(32), nullable=True)
    serial = Column(String(64), nullable=True)
    status = Column(String(64), nullable=True)
    associated_device_serial = Column(String(64), nullable=True)
    location = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    last_updated = Column(DateTime, nullable=True)

    REQUIRED_FIELDS = ["manufacturer", "model", "serial", "status"]


# ---------------------------------------------------------------------------
# 25. Hard Drives (standalone — no InventoryMixin)
# ---------------------------------------------------------------------------
class HardDrive(Base):
    __tablename__ = "hard_drives"

    id = Column(Integer, primary_key=True, autoincrement=True)
    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    drive_type = Column(String(32), nullable=True)
    form_factor = Column(String(32), nullable=True)
    serial = Column(String(64), nullable=True, unique=True)
    capacity_tb = Column(Float, nullable=True)
    capacity_gb = Column(Integer, nullable=True)
    interface = Column(String(32), nullable=True)
    rpm = Column(String(16), nullable=True)
    status = Column(String(64), nullable=True)
    location = Column(String(100), nullable=True)
    associated_device_serial = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    last_updated = Column(DateTime, nullable=True)
    discovered_by = Column(String(64), nullable=True)
    data_completeness = Column(Float, default=0.0)
    network_segment = Column(String(32), nullable=True)
    last_seen = Column(DateTime, nullable=True)
    vendor = Column(String(255), nullable=True)
    purchase_date = Column(Date, nullable=True)
    purchase_price = Column(Float, nullable=True)
    purchase_order = Column(String(128), nullable=True)
    supplier_invoice = Column(String(128), nullable=True)
    procurement_method = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    REQUIRED_FIELDS = ["manufacturer", "model", "drive_type", "capacity_tb", "status"]


# ---------------------------------------------------------------------------
# Model registry for dynamic lookups
# ---------------------------------------------------------------------------
TABLE_MODELS = {
    "edge_boxes": EdgeBox,
    "gpus": GPU,
    "monitors": Monitor,
    "computers": Computer,
    "phones": Phone,
    "mobile_devices": MobileDevice,
    "cameras": Camera,
    "network_equipment": NetworkEquipment,
    "access_control": AccessControl,
    "webcams": Webcam,
    "printers": Printer,
    "office_equipment": OfficeEquipment,
    "nas_devices": NASDevice,
    "nucs": NUC,
    "ups": UPS,
    "ram_modules": RamModule,
    "cpus": CPU,
    "psus": PSU,
    "motherboards": Motherboard,
    "pc_cooling": PCCooling,
    "pc_accessories": PCAccessory,
    "hard_drives": HardDrive,
}


def compute_completeness(instance) -> float:
    """Calculate data completeness percentage for an inventory model instance."""
    model_class = type(instance)

    # Check if this model has conditional required fields based on deployment_type
    customer_deployment_types = getattr(model_class, 'CUSTOMER_DEPLOYMENT_TYPES', None)
    if customer_deployment_types is not None:
        deployment_type = getattr(instance, 'deployment_type', None)
        if deployment_type in customer_deployment_types:
            required = getattr(model_class, 'CUSTOMER_REQUIRED_FIELDS', [])
        else:
            required = getattr(model_class, 'REQUIRED_FIELDS', [])
    else:
        required = getattr(model_class, 'REQUIRED_FIELDS', [])

    if not required:
        return 100.0
    filled = sum(1 for f in required if getattr(instance, f, None) not in (None, ""))
    return round((filled / len(required)) * 100, 1)


# ---------------------------------------------------------------------------
# Pretty display names for table keys
# ---------------------------------------------------------------------------
TABLE_DISPLAY_NAMES = {
    "edge_boxes": "Edge Boxes",
    "gpus": "GPUs",
    "monitors": "Monitors",
    "computers": "Computers",
    "phones": "Phones",
    "mobile_devices": "Mobile Devices",
    "cameras": "Cameras",
    "network_equipment": "Network Equipment",
    "access_control": "Access Control",
    "webcams": "Webcams",
    "printers": "Printers",
    "office_equipment": "Office Equipment",
    "nas_devices": "NAS Devices",
    "nucs": "NUCs",
    "ups": "UPS",
    "ram_modules": "RAM Modules",
    "cpus": "CPUs",
    "psus": "PSUs",
    "motherboards": "Motherboards",
    "pc_cooling": "PC Cooling",
    "pc_accessories": "PC Accessories",
    "hard_drives": "Hard Drives",
}


# ---------------------------------------------------------------------------
# Review queue permission helpers
# ---------------------------------------------------------------------------
TABLES_REQUIRING_SITES_ADMIN = frozenset({"edge_boxes", "trade_show_boxes"})


def user_can_approve_table(user, table_name: str) -> bool:
    """Check if a user has permission to approve devices into a given table."""
    if table_name in TABLES_REQUIRING_SITES_ADMIN:
        return user.has_sites_admin
    return user.is_editor_or_above


def get_approvable_tables(user) -> list[str]:
    """Return sorted list of table names the user can approve devices into."""
    return sorted(t for t in TABLE_MODELS if user_can_approve_table(user, t))


# ---------------------------------------------------------------------------
# Helpers for unified multi-table view
# ---------------------------------------------------------------------------
def get_display_name(instance) -> str:
    """Extract a human-readable display name from any inventory model."""
    table = instance.__class__.__tablename__

    # manufacturer + model pattern
    if table in ("cameras", "access_control", "nas_devices", "ups", "ram_modules",
                 "cpus", "psus", "motherboards", "pc_cooling", "pc_accessories",
                 "hard_drives"):
        mfr = getattr(instance, "manufacturer", "") or ""
        mdl = getattr(instance, "model", "") or ""
        return f"{mfr} {mdl}".strip() or "-"

    # GPU uses model
    if table == "gpus":
        return getattr(instance, "model", None) or "-"

    # Computers: prefer device_name, fall back to device
    if table == "computers":
        return (getattr(instance, "device_name", None)
                or getattr(instance, "device", None) or "-")

    # Edge boxes: org - site_name
    if table == "edge_boxes":
        org = getattr(instance, "org", "") or ""
        site = getattr(instance, "site_name", "") or ""
        combined = f"{org} - {site}".strip(" -")
        return combined or getattr(instance, "serial", "-") or "-"

    # NUCs: serial or org
    if table == "nucs":
        return getattr(instance, "serial", None) or getattr(instance, "org", None) or "-"

    # Default: "device" column (monitors, phones, mobile_devices, etc.)
    return getattr(instance, "device", None) or "-"


def get_serial(instance) -> str:
    """Extract serial number from any inventory model."""
    if hasattr(instance, "serial"):
        return getattr(instance, "serial", None) or "-"
    if hasattr(instance, "gpu_serial"):
        return getattr(instance, "gpu_serial", None) or "-"
    if hasattr(instance, "part_number"):
        return getattr(instance, "part_number", None) or "-"
    return "-"


def get_status(instance) -> str:
    """Extract status from any inventory model."""
    return getattr(instance, "status", None) or "-"


def get_mac(instance) -> str:
    """Extract MAC address from any inventory model."""
    return (getattr(instance, "mac_address", None)
            or getattr(instance, "mac_address_1", None)
            or "-")


# ---------------------------------------------------------------------------
# item_schema enums
# ---------------------------------------------------------------------------
item_categories_enum = SAEnum(
    'access_control', 'camera', 'computer', 'cpu', 'motherboard',
    'gpu', 'ram', 'storage_drive', 'psu', 'cpu_cooler', 'case_fan',
    'pci', 'product_cabling', 'consumables', 'edge_box', 'ups',
    'mobile_device', 'monitor', 'network', 'office_equipment', 'pc_accessories',
    'camera_c2c', 'cloud_box',
    name='item_categories',
    schema='public'
)

item_statuses_enum = SAEnum(
    'Deployed', 'Ready to Deploy', 'Pending', 'Un-deployable',
    'Decommissioned', 'Unassigned',
    'Checked Out',
    'Installed',  # containment-managed (migration 065) — set/cleared by the
                  # install/uninstall routes, absent from hand-edit lists
    name='item_statuses',
    schema='public'
)

component_actions_enum = SAEnum(
    'installed', 'uninstalled', 'moved',
    name='component_actions',
    schema='public'
)

# item_schema.current_containment — a SQL VIEW (migration 065), THE read path
# for containment state: latest component_history event per component, present
# only while installed/moved. Defined on its OWN MetaData so create_all never
# tries to create it as a table (fresh DBs get the view from db_init +
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
    appliance_uuid                = Column(String(512), nullable=True)
    brand_sku                = Column(String(512), ForeignKey('item_schema.part_numbers.brand_sku'), nullable=True)
    brand_pn                 = Column(String(512), nullable=True)
    item_associated_brand_pn = Column(String(512), nullable=True)
    vendor_id                  = Column(Integer, nullable=True)
    item_vendor                = Column(String(1024), nullable=True)
    date_purchased             = Column(Date, nullable=True)
    intended_purpose           = Column(String(1024), nullable=True)
    dispatched_date            = Column(Date, nullable=True)
    tracking_number            = Column(String(512), nullable=True)
    notes                      = Column(Text, nullable=True)
    created_at                 = Column(Date, server_default=func.current_date())
    last_updated               = Column(Date, server_default=func.current_date(), onupdate=func.current_date())
    attributes                 = Column(JSONB, nullable=True)

    # Role-based required fields for triage
    REQUIRED_FIELDS_HARDWARE = [
        "item_name", "item_manufacturer", "item_model", "item_sn",
        "item_category", "item_status", "location_id",
        "department_or_owner", "brand_sku", "brand_pn", "vendor_id",
    ]
    REQUIRED_FIELDS_ACCOUNTING = [
        "item_name", "item_model", "item_sn", "item_category",
        "item_status", "location_id", "department_or_owner",
        "brand_sku", "brand_pn", "vendor_id",
        "date_purchased", "intended_purpose", "dispatched_date",
    ]
    REQUIRED_FIELDS_DEPLOYMENT = [
        "item_name", "item_sn", "item_category", "item_status",
        "location_id", "department_or_owner", "item_mac_address_1",
        "item_mac_address_2", "item_storage_size_gb", "appliance_uuid",
        "brand_sku", "brand_pn", "intended_purpose",
        "dispatched_date", "tracking_number",
    ]
    # Default — broadest set for general triage checks
    REQUIRED_FIELDS = REQUIRED_FIELDS_HARDWARE

    location = relationship('Site', foreign_keys=[location_id])  # Migration 063
    part_number = relationship('ItemPartNumber', foreign_keys=[brand_sku])


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
    created_at       = Column(Date, server_default=func.current_date())
    last_updated     = Column(Date, server_default=func.current_date())


class ItemPartNumber(Base):
    __tablename__ = 'part_numbers'
    __table_args__ = {'schema': 'item_schema'}

    id              = Column(Integer, primary_key=True, autoincrement=True)
    brand_sku     = Column(String(512), unique=True, nullable=False)
    sku_description = Column(Text, nullable=True)
    item_category   = Column(item_categories_enum, nullable=True)
    is_legacy       = Column(Boolean, default=False)
    is_customer_pn  = Column(Boolean, default=False)
    location_id     = Column(Integer, ForeignKey('sites.id', ondelete='SET NULL'), nullable=True)  # Migration 063
    created_by      = Column(String(100), nullable=True)
    created_at      = Column(Date, server_default=func.current_date())
    notes           = Column(Text, nullable=True)


class ItemReceipt(Base):
    __tablename__ = 'receipts'
    __table_args__ = {'schema': 'item_schema'}

    id                = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id         = Column(Integer, nullable=True)
    purchase_order    = Column(String(100), nullable=True)
    record_type       = Column(String(20), nullable=False)
    transaction_date  = Column(Date, nullable=False)
    file_path         = Column(String(500), nullable=True)
    original_filename = Column(String(255), nullable=True)
    notes             = Column(Text, nullable=True)
    created_by        = Column(String(100), nullable=False)
    created_at        = Column(Date, server_default=func.current_date())


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

    id               = Column(Integer, primary_key=True, autoincrement=True)
    item_id          = Column(Integer, ForeignKey('item_schema.items.id'), nullable=False)
    entry_type       = Column(String(50), nullable=False)
    description      = Column(Text, nullable=False)
    performed_by     = Column(String(100), nullable=True)
    maintenance_date = Column(Date, server_default=func.current_date())
    component_id     = Column(Integer, nullable=True)
    created_by       = Column(String(100), nullable=False)
    created_at       = Column(Date, server_default=func.current_date())

    item = relationship('Item', foreign_keys=[item_id])


class ItemComponentHistory(Base):
    __tablename__ = 'component_history'
    __table_args__ = {'schema': 'item_schema'}

    id             = Column(Integer, primary_key=True, autoincrement=True)
    item_id        = Column(Integer, ForeignKey('item_schema.items.id'), nullable=False)
    parent_item_id = Column(Integer, ForeignKey('item_schema.items.id'), nullable=True)
    action         = Column(component_actions_enum, nullable=False)
    slot_label     = Column(String(100), nullable=True)
    action_date    = Column(Date, server_default=func.current_date())
    performed_by   = Column(String(100), nullable=True)
    notes          = Column(Text, nullable=True)
    created_at     = Column(Date, server_default=func.current_date())

    item        = relationship('Item', foreign_keys=[item_id])
    parent_item = relationship('Item', foreign_keys=[parent_item_id])


class ItemCheckout(Base):
    __tablename__ = 'checkouts'
    __table_args__ = {'schema': 'item_schema'}

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    item_id                = Column(Integer, ForeignKey('item_schema.items.id'), nullable=False)
    checked_out_to_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    checked_out_to_name    = Column(String(255), nullable=True)
    checkout_date          = Column(Date, server_default=func.current_date(), nullable=False)
    checkin_date           = Column(Date, nullable=True)
    prior_status           = Column(item_statuses_enum, nullable=True)
    checked_out_by         = Column(String(100), nullable=True)
    notes                  = Column(Text, nullable=True)
    created_at             = Column(Date, server_default=func.current_date())

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
    appliance_version = Column(String(64), nullable=True)
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

