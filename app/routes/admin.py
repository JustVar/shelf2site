"""Admin routes: OUI Reference, user management, audit log viewer."""

import tempfile
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import (
    create_user, get_current_user, hash_password, require_admin,
    require_editor, require_user_manager, require_system_admin, require_audit_viewer,
    VALID_ROLES, ROLE_DISPLAY, SUB_ADMIN_ROLES,
    ROLE_TIER, get_assignable_roles, can_manage_user, User, validate_password_strength,
)
from ..config import settings
from ..database import get_db
from ..models import (
    AuditLog, OUIAllowlist, TABLE_DISPLAY_NAMES, Department, User as UserModel,
    USER_PERMISSION_COLUMNS, DEPARTMENT_PERMISSION_COLUMNS,
    ItemPartNumber, Item, ADMIN_LEVEL_ROLES,
)
from .dashboard import ALL_CATEGORIES, category_display
from ..spreadsheet_sync import parse_excel, compare_with_database, apply_changes

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


def _cycle_perm(current_val):
    """Cycle: 'inherit' → 'grant' → 'block' → 'inherit'."""
    if current_val == 'inherit':
        return 'grant'
    if current_val == 'grant':
        return 'block'
    return 'inherit'


def _perm_label(val):
    """Human-readable label for an enum permission value."""
    return {"inherit": "Inherit", "grant": "Granted", "block": "Revoked"}.get(val, str(val))


# USER_PERMISSION_COLUMNS imported from ..models — canonical home (15 names).
# DEPARTMENT_PERMISSION_COLUMNS imported similarly (14 names, no view_sensitive_customers).


# ---------------------------------------------------------------------------
# OUI Reference (Network Device Identification)
# ---------------------------------------------------------------------------

@router.get("/admin/oui", response_class=HTMLResponse)
def oui_reference(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Render the OUI Reference page (viewable by editors+, editable by admins)."""
    from ..models import (
        EdgeBox, Camera, AccessControl, Phone,
        MobileDevice, NetworkEquipment, TABLE_MODELS
    )

    entries = db.query(OUIAllowlist).order_by(OUIAllowlist.manufacturer, OUIAllowlist.oui_prefix).all()

    # Count devices per OUI across all tables with MAC addresses
    tables_with_macs = [
        EdgeBox, Camera, AccessControl,
        Phone, MobileDevice, NetworkEquipment
    ]

    oui_stats = []
    for entry in entries:
        device_count = 0
        oui_pattern = f"{entry.oui_prefix}:%"
        for model in tables_with_macs:
            if hasattr(model, "mac_address"):
                device_count += db.query(model).filter(
                    model.mac_address.ilike(oui_pattern)
                ).count()
        oui_stats.append({"entry": entry, "device_count": device_count})

    # Group by manufacturer for the grouped view
    from collections import OrderedDict
    mfr_map: dict[str, dict] = OrderedDict()
    for stat in oui_stats:
        mfr = stat["entry"].manufacturer or "Unknown Manufacturer"
        if mfr not in mfr_map:
            mfr_map[mfr] = {
                "manufacturer": mfr,
                "oui_entries": [],
                "total_devices": 0,
                "categories": set(),
            }
        mfr_map[mfr]["oui_entries"].append(stat)
        mfr_map[mfr]["total_devices"] += stat["device_count"]
        cat = stat["entry"].maps_to_table
        if cat:
            mfr_map[mfr]["categories"].add(cat)

    # Sort groups alphabetically; convert category sets to sorted lists
    vendor_groups = sorted(mfr_map.values(), key=lambda g: g["manufacturer"].lower())
    for g in vendor_groups:
        g["categories"] = sorted(g["categories"])

    total_ouis = len(entries)
    total_devices = sum(s["device_count"] for s in oui_stats)
    unique_manufacturers = len(mfr_map)

    return templates.TemplateResponse("admin_oui.html", {
        "request": request,
        "vendor_groups": vendor_groups,
        "total_ouis": total_ouis,
        "total_devices": total_devices,
        "unique_manufacturers": unique_manufacturers,
        "user": user,
        "table_names": TABLE_DISPLAY_NAMES,
    })


@router.post("/admin/oui/add")
async def add_oui_entry(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Add a new OUI prefix to the allowlist."""
    form = await request.form()
    oui_prefix = form.get("oui_prefix", "").strip().upper()
    manufacturer = form.get("manufacturer", "").strip()
    maps_to_table = form.get("maps_to_table", "").strip()

    if not oui_prefix or len(oui_prefix) != 8:
        return JSONResponse(status_code=400, content={
            "error": "OUI prefix must be 8 characters (e.g. E4:30:22)"
        })

    existing = db.query(OUIAllowlist).filter(OUIAllowlist.oui_prefix == oui_prefix).first()
    if existing:
        return JSONResponse(status_code=409, content={
            "error": f"OUI prefix {oui_prefix} already exists"
        })

    entry = OUIAllowlist(
        oui_prefix=oui_prefix,
        manufacturer=manufacturer or None,
        maps_to_table=maps_to_table or None,
        added_by=user.id,
    )
    db.add(entry)
    db.commit()

    log_event(
        db, "oui_added",
        request=request,
        user_id=user.id,
        target_table="oui_allowlist",
        target_id=entry.id,
        action="create",
        new_values={"oui_prefix": oui_prefix, "manufacturer": manufacturer, "maps_to_table": maps_to_table},
        details=f"Added OUI {oui_prefix} ({manufacturer}) -> {maps_to_table}",
    )

    return JSONResponse(content={"status": "added", "id": entry.id})


@router.post("/admin/oui/{entry_id}/edit")
async def edit_oui_entry(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Edit an OUI entry (manufacturer name or table mapping)."""
    entry = db.query(OUIAllowlist).filter(OUIAllowlist.id == entry_id).first()
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    form = await request.form()
    new_manufacturer = form.get("manufacturer", "").strip()
    new_table = form.get("maps_to_table", "").strip()

    old_values = {
        "manufacturer": entry.manufacturer,
        "maps_to_table": entry.maps_to_table,
    }

    if new_manufacturer:
        entry.manufacturer = new_manufacturer
    if new_table:
        entry.maps_to_table = new_table

    db.commit()

    log_event(
        db, "oui_updated",
        request=request,
        user_id=user.id,
        target_table="oui_allowlist",
        target_id=entry.id,
        action="update",
        old_values=old_values,
        new_values={"manufacturer": entry.manufacturer, "maps_to_table": entry.maps_to_table},
        details=f"Updated OUI {entry.oui_prefix}",
    )

    return JSONResponse(content={"status": "updated"})


@router.post("/admin/oui/{entry_id}/toggle")
def toggle_oui_entry(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Toggle an OUI allowlist entry on/off."""
    entry = db.query(OUIAllowlist).filter(OUIAllowlist.id == entry_id).first()
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    entry.is_active = not entry.is_active
    db.commit()

    log_event(
        db, "oui_added" if entry.is_active else "oui_removed",
        request=request,
        user_id=user.id,
        target_table="oui_allowlist",
        target_id=entry.id,
        action="update",
        details=f"{'Enabled' if entry.is_active else 'Disabled'} OUI {entry.oui_prefix}",
    )

    return JSONResponse(content={"status": "toggled", "is_active": entry.is_active})


@router.delete("/admin/oui/{entry_id}")
def delete_oui_entry(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Remove an OUI prefix from the allowlist."""
    entry = db.query(OUIAllowlist).filter(OUIAllowlist.id == entry_id).first()
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    oui_prefix = entry.oui_prefix
    db.delete(entry)
    db.commit()

    log_event(
        db, "oui_removed",
        request=request,
        user_id=user.id,
        target_table="oui_allowlist",
        target_id=entry_id,
        action="delete",
        details=f"Deleted OUI {oui_prefix}",
    )

    return JSONResponse(content={"status": "deleted"})


# ---------------------------------------------------------------------------
# Part Numbers (Company SKU catalog)
# ---------------------------------------------------------------------------

@router.get("/admin/part-numbers", response_class=HTMLResponse)
def part_numbers_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """SKU catalog. Viewable by editors+, editable by system admins."""
    rows = (
        db.query(ItemPartNumber)
        .order_by(ItemPartNumber.item_category, ItemPartNumber.brand_sku)
        .all()
    )
    # usage count per SKU (plain string match on item.brand_sku)
    usage = {}
    for sku, cnt in (
        db.query(Item.brand_sku, func.count(Item.id))
        .filter(Item.brand_sku.isnot(None))
        .group_by(Item.brand_sku)
        .all()
    ):
        usage[sku] = cnt
    pn_rows = [{"pn": r, "usage": usage.get(r.brand_sku, 0)} for r in rows]
    categories = [{"value": c, "display": category_display(c)} for c in ALL_CATEGORIES]
    return templates.TemplateResponse("admin_part_numbers.html", {
        "request": request,
        "user": user,
        "pn_rows": pn_rows,
        "categories": categories,
        "total_skus": len(rows),
        "total_in_use": sum(1 for r in pn_rows if r["usage"] > 0),
    })


@router.post("/admin/part-numbers/add")
async def add_part_number(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Create a new SKU."""
    form = await request.form()
    sku = (form.get("brand_sku") or "").strip()
    desc = (form.get("sku_description") or "").strip()
    category = (form.get("item_category") or "").strip()
    is_legacy = form.get("is_legacy") == "on"
    is_customer_pn = form.get("is_customer_pn") == "on"
    notes = (form.get("notes") or "").strip()

    if not sku:
        return JSONResponse(status_code=400, content={"error": "Company SKU is required"})
    if db.query(ItemPartNumber).filter(ItemPartNumber.brand_sku == sku).first():
        return JSONResponse(status_code=409, content={"error": f"SKU '{sku}' already exists"})

    pn = ItemPartNumber(
        brand_sku=sku,
        sku_description=desc or None,
        item_category=category or None,
        is_legacy=is_legacy,
        is_customer_pn=is_customer_pn,
        notes=notes or None,
        created_by=user.username,
    )
    db.add(pn)
    db.commit()
    log_event(
        db, "part_number_added", request=request, user_id=user.id,
        target_table="part_numbers", target_id=pn.id, action="create",
        new_values={"brand_sku": sku, "item_category": category},
        details=f"Added SKU {sku}",
    )
    return JSONResponse(content={"status": "added", "id": pn.id})


@router.post("/admin/part-numbers/{pn_id}/edit")
async def edit_part_number(
    pn_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Edit a SKU's description/category/flags/notes. The brand_sku value
    itself is NOT editable (it is the catalog key; items reference it by string)."""
    pn = db.query(ItemPartNumber).filter(ItemPartNumber.id == pn_id).first()
    if not pn:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    form = await request.form()
    old = {"sku_description": pn.sku_description, "item_category": str(pn.item_category),
           "is_legacy": pn.is_legacy, "is_customer_pn": pn.is_customer_pn}

    pn.sku_description = (form.get("sku_description") or "").strip() or None
    category = (form.get("item_category") or "").strip()
    pn.item_category = category or None
    pn.is_legacy = form.get("is_legacy") == "on"
    pn.is_customer_pn = form.get("is_customer_pn") == "on"
    pn.notes = (form.get("notes") or "").strip() or None
    db.commit()
    log_event(
        db, "part_number_updated", request=request, user_id=user.id,
        target_table="part_numbers", target_id=pn.id, action="update",
        old_values=old, details=f"Updated SKU {pn.brand_sku}",
    )
    return JSONResponse(content={"status": "updated"})


@router.delete("/admin/part-numbers/{pn_id}")
def delete_part_number(
    pn_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Delete a SKU - HARD-BLOCKED if any item references it (plain string match,
    no DB FK), to prevent orphaning item.brand_sku values."""
    pn = db.query(ItemPartNumber).filter(ItemPartNumber.id == pn_id).first()
    if not pn:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    ref_count = db.query(Item).filter(Item.brand_sku == pn.brand_sku).count()
    if ref_count > 0:
        return JSONResponse(status_code=409, content={
            "error": f"Cannot delete: {ref_count} item(s) use SKU '{pn.brand_sku}'. "
                     f"Reassign those items first."
        })

    sku = pn.brand_sku
    db.delete(pn)
    db.commit()
    log_event(
        db, "part_number_removed", request=request, user_id=user.id,
        target_table="part_numbers", target_id=pn_id, action="delete",
        details=f"Deleted SKU {sku}",
    )
    return JSONResponse(content={"status": "deleted"})


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@router.get("/admin/users", response_class=HTMLResponse)
def user_management_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Render the user management page."""
    query = db.query(UserModel)
    # Hide test/debug/service accounts from non-superadmin users
    if user.role != "justin_admin":
        query = query.filter(
            ~UserModel.username.like("test_%"),
            ~UserModel.username.like("dbg_%"),
            ~UserModel.username.like("svc_%"),
            ~UserModel.username.like("smoke_%"),
        )
    users = query.order_by(UserModel.username).all()
    departments = db.query(Department).order_by(Department.name).all()

    # Build sanitized users_json for client-side drawer (no password hashes, no tokens).
    # Permission columns are nullable bool — None means "inherit from department".
    def _user_to_dict(u):
        return {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "department_id": u.department_id,
            "department_name": u.department.name if u.department else None,
            "slack_user_id": u.slack_user_id,
            "slack_auto_match": u.slack_auto_match,
            "must_change_password": u.must_change_password,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "can_view_receipts": u.can_view_receipts,
            "can_manage_warranty": u.can_manage_warranty,
            "can_manage_trials": u.can_manage_trials,
            "can_manage_procurement": u.can_manage_procurement,
            "can_manage_sites": u.can_manage_sites,
            "can_manage_users": u.can_manage_users,
            "can_manage_system": u.can_manage_system,
            "can_view_audit_log": u.can_view_audit_log,
            "can_access_receiving": u.can_access_receiving,
            "can_access_map": u.can_access_map,
            "can_access_disposal": u.can_access_disposal,
            "can_access_credentials": u.can_access_credentials,
            "can_manage_provisioning": u.can_manage_provisioning,
            "can_view_provisioning": u.can_view_provisioning,
            "view_sensitive_customers": u.view_sensitive_customers,
        }

    users_json = [_user_to_dict(u) for u in users]
    departments_json = [{"id": d.id, "name": d.name} for d in departments]

    # Fuller department payload for the drawer permission grid: id + name + the
    # 14 inherited can_* columns. Used client-side to compute the resolved state
    # of a 'inherit' user-level value. view_sensitive_customers is intentionally
    # absent — it has no department equivalent.
    _DEPT_PERM_COLS_FOR_JSON = (
        "can_view_receipts", "can_manage_warranty", "can_manage_trials",
        "can_manage_procurement", "can_manage_sites", "can_manage_users",
        "can_manage_system", "can_view_audit_log", "can_access_receiving",
        "can_access_map", "can_access_disposal", "can_access_credentials",
        "can_manage_provisioning", "can_view_provisioning",
    )
    departments_full_json = [
        {"id": d.id, "name": d.name,
         **{col: getattr(d, col) for col in _DEPT_PERM_COLS_FOR_JSON}}
        for d in departments
    ]

    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "users": users,
        "users_json": users_json,
        "user": user,
        "departments": departments,
        "departments_json": departments_json,
        "departments_full_json": departments_full_json,
    })


@router.post("/admin/users/add")
async def add_user(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Create a new user account."""
    form = await request.form()
    username = form.get("username", "").strip()
    display_name = form.get("display_name", "").strip()
    password = form.get("password", "")
    role = form.get("role", "viewer")

    if not username or not password:
        return JSONResponse(status_code=400, content={"error": "Username and password required"})
    strength_error = validate_password_strength(password, username=username)
    if strength_error:
        return JSONResponse(status_code=400, content={"error": f"Password too weak: {strength_error}"})
    if role not in VALID_ROLES:
        return JSONResponse(status_code=400, content={"error": f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}"})
    if role == "justin_admin":
        return JSONResponse(status_code=403, content={"error": "Cannot create users with Super Admin role"})
    assignable = get_assignable_roles(user.role)
    if role not in assignable:
        return JSONResponse(status_code=403, content={"error": f"You cannot assign the {ROLE_DISPLAY.get(role, role)} role"})

    existing = db.query(UserModel).filter(UserModel.username == username).first()
    if existing:
        return JSONResponse(status_code=409, content={"error": f"Username '{username}' already exists"})

    new_user = create_user(db, username, display_name or username, password, role)

    log_event(
        db, "user_created",
        request=request,
        user_id=user.id,
        target_table="users",
        target_id=new_user.id,
        action="create",
        details=f"Created user '{username}' with role '{role}'",
    )

    return JSONResponse(content={"status": "created", "id": new_user.id})


@router.post("/admin/users/{user_id}/toggle")
def toggle_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Activate or deactivate a user account."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    if target.id == user.id:
        return JSONResponse(status_code=400, content={"error": "Cannot deactivate yourself"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.is_active = not target.is_active
    db.commit()

    log_event(
        db, "user_updated",
        request=request,
        user_id=user.id,
        target_table="users",
        target_id=target.id,
        action="update",
        details=f"{'Activated' if target.is_active else 'Deactivated'} user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "is_active": target.is_active})


@router.post("/api/admin/reset-password/{user_id}")
def reset_user_password(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Reset a user's password to a secure random temporary password."""
    import secrets
    import string

    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    # Generate secure random temporary password (16 chars: letters + digits)
    alphabet = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(alphabet) for _ in range(16))

    # Update user's password hash and force password change on next login
    target.password_hash = hash_password(temp_password)
    target.must_change_password = True
    target.password_changed_at = None
    db.commit()

    log_event(
        db, "password_reset",
        request=request,
        user_id=user.id,
        target_table="users",
        target_id=target.id,
        action="update",
        details=f"Admin '{user.username}' reset password for user '{target.username}'",
    )

    return JSONResponse(content={
        "status": "reset",
        "username": target.username,
        "temp_password": temp_password,
    })


@router.post("/api/admin/toggle-receipts/{user_id}")
def toggle_receipts_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle the receipts permission for a user (admin only)."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    # Admin-level roles always have access, do not toggle
    if target.role in ADMIN_LEVEL_ROLES:
        return JSONResponse(
            status_code=400,
            content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have receipts access"}
        )
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_view_receipts = _cycle_perm(target.can_view_receipts)
    db.commit()

    log_event(
        db, "receipts_permission_toggled",
        request=request,
        user_id=user.id,
        target_table="users",
        target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_view_receipts)} receipts access for user '{target.username}'",
    )

    return JSONResponse(content={
        "status": "toggled",
        "username": target.username,
        "can_view_receipts": target.can_view_receipts,
    })


@router.post("/api/admin/toggle-warranty/{user_id}")
def toggle_warranty_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle warranty management permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES + ("warranty_admin",):
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have warranty access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_manage_warranty = _cycle_perm(target.can_manage_warranty)
    db.commit()

    log_event(
        db, "warranty_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_manage_warranty)} warranty management for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_manage_warranty": target.can_manage_warranty})


@router.post("/api/admin/toggle-trials/{user_id}")
def toggle_trials_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle trials management permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES + ("trials_admin",):
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have trials access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_manage_trials = _cycle_perm(target.can_manage_trials)
    db.commit()

    log_event(
        db, "trials_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_manage_trials)} trials management for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_manage_trials": target.can_manage_trials})


@router.post("/api/admin/toggle-procurement/{user_id}")
def toggle_procurement_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle procurement management permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES + ("procurement_admin",):
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have procurement access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_manage_procurement = _cycle_perm(target.can_manage_procurement)
    db.commit()

    log_event(
        db, "procurement_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_manage_procurement)} procurement management for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_manage_procurement": target.can_manage_procurement})


@router.post("/api/admin/toggle-sites/{user_id}")
def toggle_sites_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle sites management permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have sites access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_manage_sites = _cycle_perm(target.can_manage_sites)
    db.commit()

    log_event(
        db, "sites_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_manage_sites)} sites management for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_manage_sites": target.can_manage_sites})


@router.post("/api/admin/toggle-users/{user_id}")
def toggle_users_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle user management permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have user management access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_manage_users = _cycle_perm(target.can_manage_users)
    db.commit()

    log_event(
        db, "users_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_manage_users)} user management for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_manage_users": target.can_manage_users})


@router.post("/api/admin/toggle-system/{user_id}")
def toggle_system_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle system administration permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have system admin access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_manage_system = _cycle_perm(target.can_manage_system)
    db.commit()

    log_event(
        db, "system_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_manage_system)} system admin for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_manage_system": target.can_manage_system})


@router.post("/api/admin/toggle-audit/{user_id}")
def toggle_audit_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle audit log viewing permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES + SUB_ADMIN_ROLES:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have audit log access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_view_audit_log = _cycle_perm(target.can_view_audit_log)
    db.commit()

    log_event(
        db, "audit_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_view_audit_log)} audit log access for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_view_audit_log": target.can_view_audit_log})


@router.post("/api/admin/toggle-receiving/{user_id}")
def toggle_receiving_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle receiving & intake page access for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.is_editor_or_above:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have receiving access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_access_receiving = _cycle_perm(target.can_access_receiving)
    db.commit()

    log_event(
        db, "receiving_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_access_receiving)} receiving access for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_access_receiving": target.can_access_receiving})


@router.post("/api/admin/toggle-map/{user_id}")
def toggle_map_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle edge box map access for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.is_editor_or_above:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have map access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_access_map = _cycle_perm(target.can_access_map)
    db.commit()

    log_event(
        db, "map_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_access_map)} map access for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_access_map": target.can_access_map})


@router.post("/api/admin/toggle-disposal/{user_id}")
def toggle_disposal_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle disposal & EOL page access for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.is_editor_or_above:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have disposal access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_access_disposal = _cycle_perm(target.can_access_disposal)
    db.commit()

    log_event(
        db, "disposal_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_access_disposal)} disposal access for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_access_disposal": target.can_access_disposal})


@router.post("/api/admin/toggle-credentials/{user_id}")
def toggle_credentials_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle credentials vault access for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    # CEO does NOT auto-get credentials — only non-CEO editor+ are blocked
    if target.is_editor_or_above and target.role != "ceo":
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have credentials access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_access_credentials = _cycle_perm(target.can_access_credentials)
    db.commit()

    log_event(
        db, "credentials_permission_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_access_credentials)} credentials access for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_access_credentials": target.can_access_credentials})


@router.post("/api/admin/change-role/{user_id}")
async def change_user_role(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Change a user's role (with hierarchy enforcement)."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    body = await request.json()
    new_role = (body.get("role") or "").strip()

    if not new_role:
        return JSONResponse(status_code=400, content={"error": "Role is required"})
    if new_role == "justin_admin":
        return JSONResponse(status_code=403, content={"error": "Cannot assign Super Admin role"})
    assignable = get_assignable_roles(user.role)
    if new_role not in assignable:
        return JSONResponse(status_code=403, content={"error": f"You cannot assign the {ROLE_DISPLAY.get(new_role, new_role)} role"})
    if new_role == target.role:
        return JSONResponse(status_code=400, content={"error": "User already has this role"})

    old_role = target.role
    target.role = new_role
    db.commit()

    log_event(
        db, "role_changed",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        old_values={"role": old_role},
        new_values={"role": new_role},
        details=f"Changed role for '{target.username}' from {ROLE_DISPLAY.get(old_role, old_role)} to {ROLE_DISPLAY.get(new_role, new_role)}",
    )

    return JSONResponse(content={
        "status": "changed",
        "username": target.username,
        "old_role": old_role,
        "new_role": new_role,
    })


@router.delete("/api/admin/delete-user/{user_id}")
def delete_user_account(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Permanently delete a user account (with hierarchy enforcement).

    Deactivation is the default way to retire a user — audit rows are legal
    history and reference users.id, so hard delete is only possible for
    accounts that never did anything. Callers get a 409 pointing at the
    deactivate toggle instead of a foreign-key 500.
    """
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.id == user.id:
        return JSONResponse(status_code=400, content={"error": "Cannot delete yourself"})
    if target.role == "justin_admin":
        return JSONResponse(status_code=403, content={"error": "Cannot delete Super Admin account"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    audit_rows = db.query(func.count(AuditLog.id)).filter(AuditLog.user_id == target.id).scalar() or 0
    if audit_rows:
        return JSONResponse(status_code=409, content={
            "error": (
                f"'{target.username}' has {audit_rows} audit-log entries recording actions they took. "
                "Deactivate the account instead — deactivated users cannot log in but their history stays intact. "
                "Hard delete is only available for accounts with no recorded activity."
            ),
        })

    username = target.username
    target_id = target.id
    db.delete(target)
    try:
        db.commit()
    except IntegrityError:
        # Some other table still references this user (error_log, checkouts, ...).
        db.rollback()
        return JSONResponse(status_code=409, content={
            "error": (
                f"'{username}' is still referenced by other records and cannot be hard-deleted. "
                "Deactivate the account instead to preserve history."
            ),
        })

    log_event(
        db, "user_deleted",
        request=request, user_id=user.id,
        target_table="users", target_id=target_id,
        action="delete",
        details=f"Deleted user '{username}'",
    )

    return JSONResponse(content={"status": "deleted", "username": username})


# ---------------------------------------------------------------------------
# Provisioning Permission Toggles
# ---------------------------------------------------------------------------

@router.post("/api/admin/toggle-provisioning-manage/{user_id}")
def toggle_provisioning_manage_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle provisioning management (full CRUD) permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have provisioning management access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_manage_provisioning = _cycle_perm(target.can_manage_provisioning)
    db.commit()

    log_event(
        db, "perm_prov_manage_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_manage_provisioning)} provisioning management for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_manage_provisioning": target.can_manage_provisioning})


@router.post("/api/admin/toggle-provisioning-view/{user_id}")
def toggle_provisioning_view_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle provisioning view-only permission for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have provisioning access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.can_view_provisioning = _cycle_perm(target.can_view_provisioning)
    db.commit()

    log_event(
        db, "perm_prov_view_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.can_view_provisioning)} provisioning view access for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "can_view_provisioning": target.can_view_provisioning})


@router.post("/api/admin/toggle-sensitive-customers/{user_id}")
def toggle_sensitive_customers_permission(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Toggle sensitive customer orders access for a user."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role in ADMIN_LEVEL_ROLES:
        return JSONResponse(status_code=400, content={"error": f"{ROLE_DISPLAY.get(target.role, target.role)} users always have sensitive access"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    target.view_sensitive_customers = _cycle_perm(target.view_sensitive_customers)
    db.commit()

    log_event(
        db, "perm_sensitive_customers_toggled",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"{_perm_label(target.view_sensitive_customers)} sensitive customer access for user '{target.username}'",
    )

    return JSONResponse(content={"status": "toggled", "username": target.username, "view_sensitive_customers": target.view_sensitive_customers})


# ---------------------------------------------------------------------------
# Department Assignment
# ---------------------------------------------------------------------------

@router.post("/api/admin/users/{user_id}/department")
async def assign_user_department(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Assign a user to a department (or remove from department with department_id=null)."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    body = await request.json()
    department_id = body.get("department_id")  # None to remove from department

    old_dept_name = target.department.name if target.department else "None"

    if department_id:
        dept = db.query(Department).filter(Department.id == int(department_id)).first()
        if not dept:
            return JSONResponse(status_code=404, content={"error": "Department not found"})
        target.department_id = dept.id
        new_dept_name = dept.name
    else:
        target.department_id = None
        new_dept_name = "None"

    db.commit()

    log_event(
        db, "user_department_changed",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"Changed department for '{target.username}' from '{old_dept_name}' to '{new_dept_name}'",
    )

    return JSONResponse(content={
        "status": "changed",
        "username": target.username,
        "department_id": target.department_id,
        "department_name": new_dept_name,
    })


# ---------------------------------------------------------------------------
# User profile self-update (email for Slack auto-match)
# ---------------------------------------------------------------------------

@router.patch("/api/users/{user_id}")
async def update_user_self(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Allow a user to update their own email (used for Slack DM auto-match)."""
    if user_id != user.id:
        return JSONResponse(status_code=403, content={"error": "You can only update your own profile"})
    body = await request.json()
    if "email" in body:
        email = (body["email"] or "").strip() or None
        user.email = email
        db.commit()
    return JSONResponse(content={"status": "ok"})


# ---------------------------------------------------------------------------
# Department Management
# ---------------------------------------------------------------------------

@router.patch("/api/admin/users/{user_id}")
async def admin_patch_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Partial update of identity fields on any user. Admin-only.

    Accepts JSON body with any subset of: display_name, email, slack_user_id,
    slack_auto_match. Other fields are silently ignored.
    """
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    body = await request.json()
    changes = []

    if "display_name" in body:
        new_val = (body["display_name"] or "").strip()
        if not new_val:
            return JSONResponse(status_code=400, content={"error": "Display name cannot be empty"})
        if new_val != target.display_name:
            old = target.display_name
            target.display_name = new_val
            changes.append(f"display_name: '{old}' → '{new_val}'")

    if "email" in body:
        new_val = (body["email"] or "").strip().lower() or None
        if new_val != target.email:
            old = target.email or "(empty)"
            target.email = new_val
            changes.append(f"email: '{old}' → '{new_val or '(empty)'}'")

    if "slack_user_id" in body:
        new_val = (body["slack_user_id"] or "").strip() or None
        if new_val != target.slack_user_id:
            old = target.slack_user_id or "(empty)"
            target.slack_user_id = new_val
            changes.append(f"slack_user_id: '{old}' → '{new_val or '(empty)'}'")

    if "slack_auto_match" in body:
        new_val = bool(body["slack_auto_match"])
        if new_val != target.slack_auto_match:
            target.slack_auto_match = new_val
            changes.append(f"slack_auto_match: {not new_val} → {new_val}")

    if not changes:
        return JSONResponse(content={"status": "no_change", "user_id": target.id})

    db.commit()

    log_event(
        db, "user_profile_updated",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"Updated profile for '{target.username}': {'; '.join(changes)}",
    )

    return JSONResponse(content={
        "status": "updated",
        "user_id": target.id,
        "display_name": target.display_name,
        "email": target.email,
        "slack_user_id": target.slack_user_id,
        "slack_auto_match": target.slack_auto_match,
        "changes": len(changes),
    })


@router.post("/api/admin/users/{user_id}/lock")
def admin_acquire_user_lock(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Acquire an editing lock on a user record. Returns 409 if held by another admin."""
    from ..locks import acquire_lock, escalate_lock, get_lock
    key = f"users:{user_id}"
    existing = get_lock(key)
    if existing and existing.get("user_id") != user.id:
        return JSONResponse(status_code=409, content={
            "error": "User is being edited by another admin",
            "held_by": existing.get("display_name") or existing.get("username") or "another admin",
        })
    acquire_lock(key, user.id, user.username, user.display_name)
    escalate_lock(key, user.id)
    return JSONResponse(content={"status": "locked", "key": key})


@router.post("/api/admin/users/{user_id}/unlock")
def admin_release_user_lock(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Release the editing lock. Idempotent — safe to call even if not held."""
    from ..locks import release_lock
    release_lock(f"users:{user_id}", user.id)
    return JSONResponse(content={"status": "unlocked"})


@router.post("/api/admin/users/{user_id}/permissions")
async def admin_update_user_permissions(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Bulk-update permission ENUM states on a single user.

    Body: partial JSON dict mapping column name → 'inherit' | 'grant' | 'block'.
    Keys outside the allowlist reject with 400. Values outside the enum reject
    with 400. The drawer normally sends only 'grant' or 'block' (it surfaces
    the third state as a separate UI mode), but the endpoint accepts all three
    for completeness.

    Role-tier guards (e.g. "admin always has receipts access") are NOT enforced
    here — the @property layer in models.py OR-merges role grants on top of
    column overrides, so writing 'block' on an admin user is a no-op at the
    read site. That trade-off is documented in docs/U2_U3_RENAME_FOLLOWUPS.md.
    """
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if not can_manage_user(user, target):
        return JSONResponse(status_code=403, content={"error": "You cannot manage this user"})

    body = await request.json()
    valid_states = {'inherit', 'grant', 'block'}

    # Validation pass — all-or-nothing
    for k, v in body.items():
        if k not in USER_PERMISSION_COLUMNS:
            return JSONResponse(status_code=400, content={
                "error": f"Unknown permission column: {k}"
            })
        if v not in valid_states:
            return JSONResponse(status_code=400, content={
                "error": f"Invalid value for {k}: {v!r}. Must be one of {sorted(valid_states)}."
            })
        if k == "view_sensitive_customers" and v == "inherit":
            return JSONResponse(status_code=400, content={
                "error": "view_sensitive_customers does not support 'inherit' (no department equivalent). Use 'grant' or 'block'."
            })

    # Apply changes; track diff for audit log
    changes = []
    for k, v in body.items():
        old = getattr(target, k)
        if old != v:
            setattr(target, k, v)
            changes.append(f"{k}: {old} → {v}")

    if not changes:
        return JSONResponse(content={"status": "no_change", "user_id": target.id})

    db.commit()

    log_event(
        db, "user_permissions_updated",
        request=request, user_id=user.id,
        target_table="users", target_id=target.id,
        action="update",
        details=f"Updated permissions for '{target.username}': {', '.join(changes)}",
    )

    return JSONResponse(content={
        "status": "updated",
        "user_id": target.id,
        "changes": len(changes),
    })


@router.get("/admin/departments", response_class=HTMLResponse)
def department_management_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Render the department management page."""
    departments = db.query(Department).order_by(Department.name).all()

    def _department_to_payload(d):
        return {
            "id": d.id,
            "name": d.name,
            "description": d.description or "",
            "members": [
                {
                    "id": m.id,
                    "username": m.username,
                    "display_name": m.display_name,
                    "role": m.role,
                }
                for m in d.members if m.is_active
            ],
            **{col: getattr(d, col) for col in DEPARTMENT_PERMISSION_COLUMNS},
        }

    departments_payload = [_department_to_payload(d) for d in departments]

    return templates.TemplateResponse("admin_departments.html", {
        "request": request,
        "user": user,
        "departments": departments,                   # kept for legacy fallback
        "departments_payload": departments_payload,   # new — used by v2 JS
    })


@router.post("/admin/departments/add")
async def add_department(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Create a new department."""
    body = await request.json()
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()

    if not name:
        return JSONResponse(status_code=400, content={"error": "Department name is required"})
    if len(name) > 64:
        return JSONResponse(status_code=400, content={"error": "Department name must be 64 characters or less"})

    existing = db.query(Department).filter(Department.name == name).first()
    if existing:
        return JSONResponse(status_code=400, content={"error": f"Department '{name}' already exists"})

    dept = Department(name=name, description=description)
    db.add(dept)
    db.commit()
    db.refresh(dept)

    log_event(
        db, "department_created",
        request=request, user_id=user.id,
        target_table="departments", target_id=dept.id,
        action="create",
        details=f"Created department '{name}'",
    )

    return JSONResponse(content={"status": "created", "department_id": dept.id, "name": dept.name})


@router.put("/api/admin/departments/{department_id}")
async def update_department(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Update department name/description."""
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        return JSONResponse(status_code=404, content={"error": "Department not found"})

    body = await request.json()
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()

    if name and name != dept.name:
        existing = db.query(Department).filter(Department.name == name, Department.id != department_id).first()
        if existing:
            return JSONResponse(status_code=400, content={"error": f"Department '{name}' already exists"})
        dept.name = name
    if "description" in body:
        dept.description = description

    db.commit()

    log_event(
        db, "department_updated",
        request=request, user_id=user.id,
        target_table="departments", target_id=dept.id,
        action="update",
        details=f"Updated department '{dept.name}'",
    )

    return JSONResponse(content={"status": "updated", "department_id": dept.id, "name": dept.name})


@router.delete("/api/admin/departments/{department_id}")
def delete_department(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Delete a department (sets members' department_id to NULL)."""
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        return JSONResponse(status_code=404, content={"error": "Department not found"})

    dept_name = dept.name
    member_count = len(dept.members)

    # Unassign all members first
    for member in dept.members:
        member.department_id = None

    db.delete(dept)
    db.commit()

    log_event(
        db, "department_deleted",
        request=request, user_id=user.id,
        target_table="departments", target_id=department_id,
        action="delete",
        details=f"Deleted department '{dept_name}' ({member_count} members unassigned)",
    )

    return JSONResponse(content={"status": "deleted", "name": dept_name, "members_unassigned": member_count})


@router.post("/api/admin/departments/{department_id}/permissions")
async def update_department_permissions(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Batch-update a department's permission flags."""
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        return JSONResponse(status_code=404, content={"error": "Department not found"})

    body = await request.json()
    perm_cols = DEPARTMENT_PERMISSION_COLUMNS  # canonical 14-tuple from models.py

    changes = []
    for col in perm_cols:
        if col in body:
            raw = body[col]
            # Wire format is 'grant'/'block' strings (U3 rebuild); ignore anything else.
            if raw not in ('grant', 'block'):
                continue
            new_val = raw
            old_val = getattr(dept, col)
            if old_val != new_val:
                setattr(dept, col, new_val)
                changes.append(f"{col}: {old_val} → {new_val}")

    db.commit()

    if changes:
        log_event(
            db, "department_permissions_updated",
            request=request, user_id=user.id,
            target_table="departments", target_id=dept.id,
            action="update",
            details=f"Updated permissions for department '{dept.name}': {', '.join(changes)}",
        )

    return JSONResponse(content={"status": "updated", "department_id": dept.id, "changes": len(changes)})


@router.post("/api/admin/departments/{department_id}/lock")
def admin_acquire_department_lock(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Acquire an editing lock on a department record. Returns 409 if held by someone else."""
    from ..locks import acquire_lock, escalate_lock, get_lock
    key = f"departments:{department_id}"
    existing = get_lock(key)
    if existing and existing.get("user_id") != user.id:
        return JSONResponse(status_code=409, content={
            "error": "Department is being edited by another admin",
            "held_by": existing.get("display_name") or existing.get("username") or "another admin",
        })
    acquire_lock(key, user.id, user.username, user.display_name)
    escalate_lock(key, user.id)
    return JSONResponse(content={"status": "locked", "key": key})


@router.post("/api/admin/departments/{department_id}/unlock")
def admin_release_department_lock(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_manager),
):
    """Release the editing lock. Idempotent — safe to call even if not held."""
    from ..locks import release_lock
    release_lock(f"departments:{department_id}", user.id)
    return JSONResponse(content={"status": "unlocked"})


# ---------------------------------------------------------------------------
# Audit Log Viewer
# ---------------------------------------------------------------------------

@router.get("/admin/audit", response_class=HTMLResponse)
def audit_log_page(
    request: Request,
    event_type: str = "",
    user_filter: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_audit_viewer),
):
    """Render the audit log viewer.

    Gated by require_audit_viewer: admin tier, or an explicit user-level
    can_view_audit_log = 'grant'. Inherited department grants do not count.
    Everyone who reaches this page sees every entry; there is no area scoping.
    """
    query = db.query(AuditLog).order_by(desc(AuditLog.timestamp))

    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    if user_filter:
        query = query.filter(AuditLog.user_id == int(user_filter))

    total_entries = query.count()
    entries = query.limit(500).all()

    # Resolve user display names for the log entries
    user_ids = {e.user_id for e in entries if e.user_id}
    users_map = {}
    if user_ids:
        for u in db.query(UserModel).filter(UserModel.id.in_(user_ids)).all():
            users_map[u.id] = u.display_name

    # Both filter option lists are derived from the log itself. A hardcoded list
    # drifts the moment a new log_event call site lands, which is how the old
    # dropdown came to offer nine event types that matched no rows at all.
    actor_ids = [r[0] for r in db.query(AuditLog.user_id)
                 .filter(AuditLog.user_id.isnot(None)).distinct().all()]
    all_users = (db.query(UserModel).filter(UserModel.id.in_(actor_ids))
                 .order_by(UserModel.display_name).all()) if actor_ids else []

    # Group event types on the leading segment. Groups of one collapse into
    # Other, which sorts last; everything else sorts alphabetically.
    seen_types = [r[0] for r in db.query(AuditLog.event_type).distinct().all() if r[0]]
    buckets = {}
    for et in seen_types:
        buckets.setdefault(et.split("_", 1)[0], []).append(et)
    loners = []
    for key in [k for k, v in buckets.items() if len(v) < 2]:
        loners.extend(buckets.pop(key))
    event_groups = [(k, sorted(v)) for k, v in sorted(buckets.items())]
    if loners:
        event_groups.append(("Other", sorted(loners)))

    return templates.TemplateResponse("admin_audit.html", {
        "request": request,
        "entries": entries,
        "users_map": users_map,
        "all_users": all_users,
        "event_groups": event_groups,
        "total_entries": total_entries,
        "current_event_type": event_type,
        "current_user_filter": user_filter,
        "user": user,
    })


# ---------------------------------------------------------------------------
# Spreadsheet Sync (Excel Upload + Diff Viewer)
# ---------------------------------------------------------------------------

@router.get("/admin/spreadsheet-sync", response_class=HTMLResponse)
def spreadsheet_sync_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Render the spreadsheet sync page for uploading Excel files."""
    return templates.TemplateResponse("admin_spreadsheet_sync.html", {
        "request": request,
        "user": user,
    })


@router.post("/admin/spreadsheet-sync/upload")
async def upload_spreadsheet(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Upload Excel file, parse it, and generate diff preview."""
    if not file.filename.endswith(('.xlsx', '.xls')):
        return JSONResponse(status_code=400, content={
            "error": "Only Excel files (.xlsx, .xls) are supported"
        })

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Parse Excel file
        tables_data = parse_excel(tmp_path)

        # Compare with database
        changes = compare_with_database(tables_data, db)

        # Organize changes by action type
        adds = [c for c in changes if c.action == "add"]
        updates = [c for c in changes if c.action == "update"]
        skips = [c for c in changes if c.action == "skip"]

        # Serialize changes for JSON response
        changes_json = []
        for change in changes:
            change_dict = {
                "table": change.table,
                "table_display": TABLE_DISPLAY_NAMES.get(change.table, change.table),
                "action": change.action,
                "serial": change.serial,
                "row_data": change.row_data,
            }
            if change.existing_data:
                change_dict["existing_data"] = change.existing_data
            if change.changes:
                # Convert changes dict to list for easier rendering
                change_dict["field_changes"] = [
                    {"field": k, "old": v[0], "new": v[1]}
                    for k, v in change.changes.items()
                ]
            changes_json.append(change_dict)

        return JSONResponse(content={
            "status": "success",
            "stats": {
                "total": len(changes),
                "adds": len(adds),
                "updates": len(updates),
                "skips": len(skips),
            },
            "changes": changes_json,
        })

    except Exception as e:
        logger.error(f"Spreadsheet sync error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={
            "error": f"Failed to process spreadsheet: {str(e)}"
        })
    finally:
        # Clean up temp file
        tmp_path.unlink(missing_ok=True)


@router.post("/admin/spreadsheet-sync/apply")
async def apply_spreadsheet_changes(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Apply approved changes from spreadsheet to database."""
    body = await request.json()
    changes_data = body.get("changes", [])

    if not changes_data:
        return JSONResponse(status_code=400, content={
            "error": "No changes provided"
        })

    # Reconstruct DeviceChange objects from JSON
    from ..spreadsheet_sync import DeviceChange

    changes = []
    for c in changes_data:
        change = DeviceChange(
            table=c["table"],
            action=c["action"],
            serial=c["serial"],
            row_data=c["row_data"],
            existing_data=c.get("existing_data"),
            changes=None,  # Not needed for apply
        )
        changes.append(change)

    try:
        # Apply changes to database
        stats = apply_changes(changes, db, user.id)

        log_event(
            db, "spreadsheet_sync",
            request=request,
            user_id=user.id,
            action="update",
            details=(
                f"Spreadsheet sync completed: "
                f"{stats['added']} added, {stats['updated']} updated, {stats['skipped']} skipped"
            ),
            new_values=stats,
        )

        return JSONResponse(content={
            "status": "success",
            "stats": stats,
        })

    except Exception as e:
        logger.error(f"Failed to apply spreadsheet changes: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={
            "error": f"Failed to apply changes: {str(e)}"
        })


# ---------------------------------------------------------------------------
# Storage Monitor
# ---------------------------------------------------------------------------

@router.get("/admin/storage", response_class=HTMLResponse)
def storage_monitor_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Display storage usage and photo statistics."""
    import shutil
    import os
    from datetime import datetime
    from ..models import IntakePhoto

    photo_dir = Path(settings.PHOTO_UPLOAD_DIR)

    # Disk usage stats
    try:
        stat = shutil.disk_usage(photo_dir.parent if photo_dir.exists() else "/")
        disk_total_gb = stat.total / (1024**3)
        disk_used_gb = stat.used / (1024**3)
        disk_free_gb = stat.free / (1024**3)
        disk_percent = (stat.used / stat.total) * 100
    except Exception:
        disk_total_gb = disk_used_gb = disk_free_gb = disk_percent = 0

    # Photo directory stats
    photo_count = 0
    photo_size_bytes = 0
    event_photos = 0
    unlinked_photos = 0
    oldest_date = None
    newest_date = None

    if photo_dir.exists():
        for root, dirs, files in os.walk(photo_dir):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    file_path = Path(root) / file
                    try:
                        stat = file_path.stat()
                        photo_size_bytes += stat.st_size
                        photo_count += 1

                        # Track oldest/newest
                        file_time = datetime.fromtimestamp(stat.st_mtime)
                        if oldest_date is None or file_time < oldest_date:
                            oldest_date = file_time
                        if newest_date is None or file_time > newest_date:
                            newest_date = file_time

                        # Categorize by directory
                        if 'event_' in root:
                            event_photos += 1
                        elif 'unlinked' in root:
                            unlinked_photos += 1
                    except Exception:
                        pass

    photo_size_mb = photo_size_bytes / (1024**2)
    photo_size_gb = photo_size_bytes / (1024**3)

    # Database photo records
    db_photo_count = db.query(IntakePhoto).count()

    # Calculate growth rate (photos per day)
    growth_rate = 0
    if oldest_date and newest_date and oldest_date != newest_date:
        days_span = (newest_date - oldest_date).days or 1
        growth_rate = photo_count / days_span

    # Estimate time until full (at current growth rate)
    days_until_full = None
    if growth_rate > 0 and disk_free_gb > 0:
        avg_photo_size_mb = photo_size_mb / photo_count if photo_count > 0 else 5
        photos_until_full = (disk_free_gb * 1024) / avg_photo_size_mb
        days_until_full = int(photos_until_full / growth_rate)

    return templates.TemplateResponse("admin_storage.html", {
        "request": request,
        "user": user,
        "disk_total_gb": round(disk_total_gb, 1),
        "disk_used_gb": round(disk_used_gb, 1),
        "disk_free_gb": round(disk_free_gb, 1),
        "disk_percent": round(disk_percent, 1),
        "photo_count": photo_count,
        "photo_size_mb": round(photo_size_mb, 1),
        "photo_size_gb": round(photo_size_gb, 2),
        "event_photos": event_photos,
        "unlinked_photos": unlinked_photos,
        "db_photo_count": db_photo_count,
        "oldest_date": oldest_date,
        "newest_date": newest_date,
        "growth_rate": round(growth_rate, 1),
        "days_until_full": days_until_full,
    })
