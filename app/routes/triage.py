"""Asset Triage — surfaces items missing role-required fields.

One role defines which fields matter: Hardware Inventory (hw). The accounting
and deployment roles were retired 2026-09-09; see
docs/specs/triage-single-role.md.

An item appears in the queue if it is missing ANY required field, or if it
fails one of the two data checks folded in from the retired deployment role
(place mismatch, containment divergence). Decommissioned items are excluded.

# TODO(perf): When item count exceeds ~5k, move gap computation from Python
#   to SQL (generated columns or a materialized view). Current path fetches
#   all matching rows, computes gaps in Python, then paginates.
"""

from pathlib import Path

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth import get_current_user, User
from ..config import settings
from ..database import get_db
from ..models import Item, ItemPartNumber, Site
from .dashboard import FL_CATEGORY_COLORS, ALL_CATEGORIES, category_display
from .intake import (
    STATUSES, _clean_str, _safe_int, _safe_float, _safe_date,
    _normalize_mac, _get_locations,
)
from ..locks import get_lock
from .sse import publish_event
import logging as _logging
_log = _logging.getLogger(__name__)

router = APIRouter(prefix="/triage", tags=["triage"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


TRIAGE_ROLES = {
    "hw": {
        "label": "Hardware inventory",
        # Single source: the list lives on the model and is read here
        # rather than restated (docs/specs/triage-single-role.md).
        "fields": Item.REQUIRED_FIELDS_HARDWARE,
    },
}

FIELD_LABELS = {
    "item_name": "Name",
    "item_manufacturer": "Manufacturer",
    "item_model": "Model",
    "item_sn": "Serial number",
    "item_category": "Category",
    "item_status": "Status",
    "location_id": "Location",
    "department_or_owner": "Dept / owner",
    "brand_sku": "Company SKU",
    "brand_pn": "Company P/N",
    "vendor_id": "Vendor ID",
    "date_purchased": "Date purchased",
    "intended_purpose": "Intended purpose",
    "dispatched_date": "Dispatched date",
    "item_mac_address_1": "MAC address 1",
    "item_mac_address_2": "MAC address 2",
    "item_storage_size_gb": "Storage (GB)",
    "appliance_uuid": "Appliance UUID",
    "tracking_number": "Tracking number",
    "place_check": "Place / status mismatch",
    "containment_check": "Installed place divergence",
}

FIELD_TYPES = {
    "item_name": "text", "item_manufacturer": "text", "item_model": "text",
    "item_sn": "text", "department_or_owner": "text", "brand_sku": "sku_select",
    "brand_pn": "text", "appliance_uuid": "text", "intended_purpose": "text",
    "tracking_number": "text",
    "item_mac_address_1": "mac", "item_mac_address_2": "mac",
    "item_storage_size_gb": "number",
    "vendor_id": "vendor",
    "date_purchased": "date", "dispatched_date": "date",
    "location_id": "location",
    "item_category": "category",
    "item_status": "status",
}

VALID_SORTS = {"modified_desc", "modified_asc", "gaps_desc", "gaps_asc", "name_asc", "name_desc"}
VALID_PER_PAGE = {25, 50, 100}

# Fields that are numeric non-FK (missing = NULL or 0)
_ZERO_MISSING_FIELDS = {"item_storage_size_gb"}
# Foreign key integer fields (missing = NULL only)
_FK_FIELDS = {"location_id", "vendor_id"}
# PostgreSQL macaddr / date / enum columns — NULL-only check at SQL level
# (comparing macaddr or date columns to '' throws InvalidTextRepresentation).
_NULL_ONLY_FIELDS = {
    "item_mac_address_1", "item_mac_address_2",
    "date_purchased", "dispatched_date",
    "item_category", "item_status",
}


def _installed_ids(db: Session) -> set:
    """Item ids currently installed in a unit (containment view)."""
    from ..containment import installed_component_ids
    return installed_component_ids(db)


def _is_missing(value, field_name: str) -> bool:
    """Return True if the value should count as 'missing' for triage."""
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if field_name in _ZERO_MISSING_FIELDS and value == 0:
        return True
    return False


def _compute_gaps(item: Item, fields: list[str], installed_ids: set = frozenset()) -> list[str]:
    """Return the subset of `fields` that are missing on this item.

    location_id is NOT a gap for an Installed component — its effective
    place follows the parent unit (Option A). Callers pass installed_ids so
    the Python path stays in sync with _gap_filter's SQL EXISTS."""
    gaps = [f for f in fields if _is_missing(getattr(item, f, None), f)]
    if item.id in installed_ids and "location_id" in gaps:
        gaps.remove("location_id")
    return gaps


# Deployable product units (only these have a customer-site lifecycle).
_DEPLOY_CATEGORIES = ("edge_box", "cloud_box", "camera_c2c")
_PLACE_CHECK = "place_check"
_CONTAINMENT_CHECK = "containment_check"


def _place_mismatch_ids(db: Session) -> set:
    """Item ids whose place and status disagree (Migration 063 lifecycle):
    a deployable unit marked Deployed that is not at a customer site, or one
    at a customer site whose status is not Deployed. A data smell, surfaced
    in the hardware triage role rather than a new page."""
    rows = (
        db.query(Item.id)
        .outerjoin(Site, Site.id == Item.location_id)
        .filter(
            Item.item_category.in_(_DEPLOY_CATEGORIES),
            or_(
                and_(Item.item_status == "Deployed",
                     or_(Site.id.is_(None), Site.site_type != "customer_site")),
                and_(or_(Item.item_status.is_(None), Item.item_status != "Deployed"), Site.site_type == "customer_site"),
            ),
        )
        .all()
    )
    return {r[0] for r in rows}


def _containment_divergence_ids(db: Session) -> set:
    """Installed components whose FROZEN stored place disagrees with the
    parent unit's place — a data-check finding (Option A), not a render
    error: read surfaces already show the inherited place."""
    from ..models import current_containment as cc
    parent = Item.__table__.alias("ctm_check_parent")
    rows = (
        db.query(Item.id)
        .join(cc, cc.c.component_item_id == Item.id)
        .join(parent, parent.c.id == cc.c.parent_item_id)
        .filter(
            Item.location_id.isnot(None),
            or_(
                parent.c.location_id.is_(None),
                Item.location_id != parent.c.location_id,
            ),
        )
        .all()
    )
    return {r[0] for r in rows}


def _gap_filter(role_fields: list[str]):
    """Build a SQLAlchemy OR-filter: items where at least one role field is missing."""
    conditions = []
    for field in role_fields:
        col = getattr(Item, field)
        if field == "location_id":
            # NULL stored place is not a gap while the item is Installed —
            # the effective place follows the parent unit (Option A). Keep
            # this EXISTS in sync with _compute_gaps' installed_ids check.
            from sqlalchemy import exists as _exists
            from ..models import current_containment as _cc
            _contained = _exists().where(_cc.c.component_item_id == Item.id)
            conditions.append(and_(col.is_(None), ~_contained))
        elif field in _FK_FIELDS or field in _NULL_ONLY_FIELDS:
            conditions.append(col.is_(None))
        elif field in _ZERO_MISSING_FIELDS:
            conditions.append(or_(col.is_(None), col == 0))
        else:
            conditions.append(or_(col.is_(None), col == ""))
    return or_(*conditions)


def _count_role_gaps(db: Session, role_key: str, extra_ids: set = None) -> int:
    """Number of items with at least one gap for the given role (plus any
    extra ids, e.g. the deploy place-check set)."""
    fields = TRIAGE_ROLES[role_key]["fields"]
    cond = _gap_filter(fields)
    if extra_ids:
        cond = or_(cond, Item.id.in_(extra_ids))
    return (
        db.query(func.count(Item.id))
        .filter(cond)
        .filter(Item.item_status.is_distinct_from("Decommissioned"))
        .scalar() or 0
    )


def get_triage_total_count(db: Session) -> int:
    """Count unique items with >=1 gap across ANY triage role (union).
    Public helper: used by sidebar_cache for the global nav badge."""
    mismatch = _place_mismatch_ids(db) | _containment_divergence_ids(db)
    union_filter = or_(*[_gap_filter(role["fields"]) for role in TRIAGE_ROLES.values()])
    if mismatch:
        union_filter = or_(union_filter, Item.id.in_(mismatch))
    return (
        db.query(func.count(Item.id))
        .filter(union_filter)
        .filter(Item.item_status.is_distinct_from("Decommissioned"))
        .scalar() or 0
    )


@router.get("/", response_class=HTMLResponse)
def triage_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    role: str = Query(default="hw"),
    page: int = Query(default=1),
    per_page: int = Query(default=25),
    sort: str = Query(default="modified_desc"),
):
    if not user:
        return RedirectResponse(f"{BP}/login")

    # Validate query params
    if role not in TRIAGE_ROLES:
        role = "hw"
    if sort not in VALID_SORTS:
        sort = "modified_desc"
    if per_page not in VALID_PER_PAGE:
        per_page = 25

    active_fields = TRIAGE_ROLES[role]["fields"]

    # The hardware role also carries the two data checks (Migration 063),
    # folded in when the deployment role was retired.
    place_mismatch_ids = _place_mismatch_ids(db)
    containment_divergence_ids = _containment_divergence_ids(db)
    installed_ids = _installed_ids(db)
    check_ids = place_mismatch_ids | containment_divergence_ids

    # Count for the single role
    role_counts = {
        k: _count_role_gaps(db, k, check_ids)
        for k in TRIAGE_ROLES.keys()
    }

    # Fetch all items with at least one gap, including check-only items.
    # Decommissioned items are out of the queue (backlog F2, following
    # docs/specs/item-decommission.md).
    gap_cond = _gap_filter(active_fields)
    if check_ids:
        gap_cond = or_(gap_cond, Item.id.in_(check_ids))
    base_query = (
        db.query(Item)
        .filter(gap_cond)
        .filter(Item.item_status.is_distinct_from("Decommissioned"))
    )

    # SQL-level sort where possible (modified, name)
    if sort == "modified_desc":
        base_query = base_query.order_by(Item.last_updated.desc().nullslast(), Item.id.desc())
    elif sort == "modified_asc":
        base_query = base_query.order_by(Item.last_updated.asc().nullsfirst(), Item.id.asc())
    elif sort == "name_asc":
        base_query = base_query.order_by(Item.item_name.asc().nullslast(), Item.id.asc())
    elif sort == "name_desc":
        base_query = base_query.order_by(Item.item_name.desc().nullsfirst(), Item.id.desc())

    all_matching = base_query.all()

    # Compute gaps per role, plus union across all roles (for expansion view)
    enriched = []
    for itm in all_matching:
        all_gaps = {k: _compute_gaps(itm, TRIAGE_ROLES[k]["fields"], installed_ids) for k in TRIAGE_ROLES.keys()}
        if itm.id in place_mismatch_ids:
            all_gaps["hw"] = all_gaps["hw"] + [_PLACE_CHECK]
        if itm.id in containment_divergence_ids:
            all_gaps["hw"] = all_gaps["hw"] + [_CONTAINMENT_CHECK]
        active_gaps = all_gaps[role]

        union_gaps = []
        for role_key in TRIAGE_ROLES:
            for g in all_gaps[role_key]:
                if g not in union_gaps:
                    union_gaps.append(g)

        enriched.append({
            "item": itm,
            "active_role_gaps": active_gaps,
            "active_role_gap_count": len(active_gaps),
            "all_gaps": all_gaps,
            "union_gaps": union_gaps,
        })

    # Python-level sort for gap-count sorts
    if sort == "gaps_desc":
        enriched.sort(key=lambda e: (-e["active_role_gap_count"], -(e["item"].id or 0)))
    elif sort == "gaps_asc":
        enriched.sort(key=lambda e: (e["active_role_gap_count"], e["item"].id or 0))

    # Paginate
    total_items = len(enriched)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    items = enriched[offset:offset + per_page]

    return templates.TemplateResponse("triage.html", {
        "request": request,
        "user": user,
        "items": items,
        "role": role,
        "roles": TRIAGE_ROLES,
        "role_counts": role_counts,
        "field_labels": FIELD_LABELS,
        "page": page,
        "per_page": per_page,
        "sort": sort,
        "total_items": total_items,
        "total_pages": total_pages,
        "category_colors": FL_CATEGORY_COLORS,
        "category_display": category_display,
        "locations_for_bulk": _get_locations(db),
        "statuses_for_bulk": STATUSES,
    })


@router.get("/fix/{item_id}/{field_name}", response_class=HTMLResponse)
def triage_fix_panel(
    request: Request,
    item_id: int,
    field_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Render the single-field editor partial for the fix panel."""
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)
    if field_name not in FIELD_LABELS:
        return HTMLResponse("Unknown field", status_code=400)

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    field_type = FIELD_TYPES.get(field_name, "text")
    current_value = getattr(item, field_name, None)

    if field_type == "date" and current_value is not None:
        try:
            current_value = current_value.isoformat()
        except Exception:
            current_value = ""
    elif current_value is None:
        current_value = ""
    else:
        # Enums render as "ItemCategory.edge_box"; strip the prefix via str coercion.
        # For enum types, .value gives the bare string.
        if hasattr(current_value, "value"):
            current_value = current_value.value
        else:
            current_value = str(current_value)

    ctx = {
        "request": request,
        "item": item,
        "field_name": field_name,
        "field_label": FIELD_LABELS[field_name],
        "field_type": field_type,
        "current_value": current_value,
    }
    if field_type == "location":
        ctx["locations"] = _get_locations(db)
    elif field_type == "status":
        ctx["statuses"] = STATUSES
    elif field_type == "category":
        ctx["categories"] = [
            {"value": c, "display": category_display(c)} for c in ALL_CATEGORIES
        ]
    elif field_type == "sku_select":
        ctx["part_numbers"] = (
            db.query(ItemPartNumber).order_by(ItemPartNumber.brand_sku).all()
        )

    return templates.TemplateResponse("partials/triage_fix_panel.html", ctx)


@router.post("/fix/{item_id}/{field_name}")
async def triage_fix_save(
    request: Request,
    item_id: int,
    field_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save a single field. Returns JSON with remaining gap counts for this item."""
    if not user or not user.is_editor_or_above:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    if field_name not in FIELD_LABELS:
        return JSONResponse({"success": False, "error": "Unknown field"}, status_code=400)

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return JSONResponse({"success": False, "error": "Item not found"}, status_code=404)

    # Lock enforcement — same pattern as item_detail POST
    lock = get_lock(f"items:{item_id}")
    if lock and lock.get("user_id") != user.id:
        holder = lock.get("display_name") or "another user"
        return JSONResponse(
            {"success": False, "error": f"This item is being edited by {holder}"},
            status_code=409,
        )

    form = await request.form()
    raw = form.get("value", "")
    field_type = FIELD_TYPES.get(field_name, "text")

    try:
        if field_type == "mac":
            new_value = _normalize_mac(raw)
        elif field_type == "date":
            new_value = _safe_date(raw)
        elif field_type == "number":
            new_value = _safe_float(raw)
        elif field_type in ("location", "vendor"):
            new_value = _safe_int(raw)
        elif field_type in ("category", "status"):
            # SQLAlchemy SAEnum accepts the raw string value; None clears the column.
            new_value = _clean_str(raw) or None
        else:
            new_value = _clean_str(raw)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

    # Reject no-op saves: if the user submits a value that coerces to None/empty
    # for a field that's currently missing, don't pretend success — return an error
    # so the user knows to enter a real value. This prevents the silent-failure
    # pattern where _safe_int("abc") → None → DB stays NULL → "saved" toast fires.
    if _is_missing(new_value, field_name):
        return JSONResponse(
            {"success": False, "error": f"{FIELD_LABELS[field_name]} cannot be empty or invalid."},
            status_code=400,
        )

    # brand_sku renders as a <select> of part_numbers (field_type sku_select),
    # so the UI only offers valid SKUs; this save-time check is the backstop.
    # brand_pn and item_associated_brand_pn are NOT FK-constrained — they're
    # plain String columns with no corresponding column in part_numbers, so
    # validation against the PN table would be nonsensical.
    if field_name == "brand_sku" and new_value:
        exists = db.query(ItemPartNumber.id).filter(
            ItemPartNumber.brand_sku == new_value
        ).first()
        if not exists:
            return JSONResponse({
                "success": False,
                "error": f"'{new_value}' is not a valid Company SKU. It must match an entry in the Part Numbers table.",
            }, status_code=400)

    if field_name == "item_status" and (
        new_value == "Decommissioned" or str(item.item_status) == "Decommissioned"
    ):
        # Code-mediated (docs/specs/item-decommission.md): entered and
        # left only through the decommission and reactivate actions.
        return JSONResponse({
            "success": False,
            "error": "Decommissioned is set from the item page decommission action",
        }, status_code=400)

    setattr(item, field_name, new_value)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        _log.error("Triage fix save failed: %s", e, exc_info=True)
        return JSONResponse({"success": False, "error": "Save failed"}, status_code=500)

    # Recompute gaps for this item across all three roles
    gaps_remaining = {
        k: len(_compute_gaps(item, TRIAGE_ROLES[k]["fields"], _installed_ids(db)))
        for k in TRIAGE_ROLES.keys()
    }
    union = set()
    for k in TRIAGE_ROLES:
        union.update(_compute_gaps(item, TRIAGE_ROLES[k]["fields"], _installed_ids(db)))
    total_gaps = len(union)
    # Union of all field names still missing on this item (across all roles).
    # Client uses this to reconcile its DOM rather than assuming save cleared the gap.
    missing_fields_union = sorted(union)

    _log.info("Triage fix: item=%d field=%s user=%s(id=%d) gaps_remaining=%s",
              item_id, field_name, user.display_name, user.id, gaps_remaining)

    # Invalidate cached sidebar counts BEFORE publishing so the next request
    # (including ones triggered by the SSE event) sees the fresh number.
    from ..sidebar_cache import invalidate_sidebar_counts
    invalidate_sidebar_counts()

    # Compute global per-role counts AFTER commit so all connected clients see the saved state.
    role_counts_global = {k: _count_role_gaps(db, k) for k in TRIAGE_ROLES.keys()}
    total_items_with_gaps = get_triage_total_count(db)
    publish_event("triage_gap_changed", {
        "item_id": item_id,
        "field_name": field_name,
        "user_id": user.id,
        "role_counts": role_counts_global,
        "total_items_with_gaps": total_items_with_gaps,
    })

    return JSONResponse({
        "success": True,
        "gaps_remaining": gaps_remaining,
        "total_gaps": total_gaps,
        "missing_fields": missing_fields_union,
    })


@router.post("/bulk")
async def triage_bulk_update(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Apply a single-field update to many items at once.
    Skips items that are locked by other users; returns counts."""
    if not user or not user.is_editor_or_above:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

    form = await request.form()
    action = form.get("action", "")
    value = form.get("value", "")
    item_ids = form.getlist("item_ids")

    try:
        item_ids = [int(i) for i in item_ids]
    except ValueError:
        return JSONResponse({"success": False, "error": "Invalid item IDs"}, status_code=400)

    if not item_ids:
        return JSONResponse({"success": False, "error": "No items selected"}, status_code=400)

    # Map action to (field_name, coercion)
    action_map = {
        "location": ("location_id", lambda v: _safe_int(v)),
        "department": ("department_or_owner", lambda v: _clean_str(v)),
        "status": ("item_status", lambda v: _clean_str(v) or None),
    }
    if action not in action_map:
        return JSONResponse({"success": False, "error": "Unknown action"}, status_code=400)

    field_name, coerce = action_map[action]
    try:
        new_value = coerce(value)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

    if new_value is None or (isinstance(new_value, str) and new_value == ""):
        return JSONResponse({"success": False, "error": "Value cannot be empty"}, status_code=400)

    if field_name == "item_status" and new_value == "Decommissioned":
        # Code-mediated (docs/specs/item-decommission.md): entered only via
        # the decommission action on the item page.
        return JSONResponse({
            "success": False,
            "error": "Decommissioned is set from the item page decommission action",
        }, status_code=400)

    items = db.query(Item).filter(Item.id.in_(item_ids)).all()
    updated = 0
    skipped = 0
    skipped_ids = []

    for item in items:
        # Lock check — skip items held by another user
        lock = get_lock(f"items:{item.id}")
        if lock and lock.get("user_id") != user.id:
            skipped += 1
            skipped_ids.append(item.id)
            continue
        if field_name == "item_status" and str(item.item_status) == "Decommissioned":
            # Decommissioned rows leave only via the reactivate action.
            skipped += 1
            skipped_ids.append(item.id)
            continue
        setattr(item, field_name, new_value)
        updated += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        _log.error("Bulk update failed: %s", e, exc_info=True)
        return JSONResponse({"success": False, "error": "Save failed"}, status_code=500)

    _log.info(
        "Triage bulk: user=%s(id=%d) action=%s updated=%d skipped=%d",
        user.display_name, user.id, action, updated, skipped,
    )

    # Single global SSE event; badge/tab counts recompute from DB.
    from ..sidebar_cache import invalidate_sidebar_counts
    invalidate_sidebar_counts()
    role_counts_global = {k: _count_role_gaps(db, k) for k in TRIAGE_ROLES.keys()}
    total_items_with_gaps = get_triage_total_count(db)
    publish_event("triage_gap_changed", {
        "item_id": None,  # bulk — no single item
        "field_name": field_name,
        "user_id": user.id,
        "role_counts": role_counts_global,
        "total_items_with_gaps": total_items_with_gaps,
    })

    return JSONResponse({
        "success": True,
        "updated_count": updated,
        "skipped_count": skipped,
        "skipped_ids": skipped_ids,
    })


@router.get("/export")
def triage_export_csv(
    request: Request,
    ids: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream a CSV of selected items' gap info. Useful for sharing triage
    work with people who don't use the app directly (e.g. accounting)."""
    if not user:
        return RedirectResponse(f"{BP}/login")

    try:
        item_ids = [int(i) for i in ids.split(",") if i.strip()]
    except ValueError:
        return JSONResponse({"error": "Invalid IDs"}, status_code=400)

    if not item_ids:
        return JSONResponse({"error": "No IDs provided"}, status_code=400)

    items = db.query(Item).filter(Item.id.in_(item_ids)).all()

    def row_for(item):
        all_gaps = {k: _compute_gaps(item, TRIAGE_ROLES[k]["fields"], _installed_ids(db)) for k in TRIAGE_ROLES.keys()}
        union = sorted(set().union(*all_gaps.values()))
        return {
            "id": item.id,
            "name": item.item_name or "",
            "category": str(item.item_category) if item.item_category else "",
            "status": str(item.item_status) if item.item_status else "",
            "manufacturer": item.item_manufacturer or "",
            "model": item.item_model or "",
            "sn": item.item_sn or "",
            "location_id": item.location_id or "",
            "department_or_owner": item.department_or_owner or "",
            "hw_gaps": ";".join(all_gaps["hw"]),
            "all_missing_fields": ";".join(union),
            "gap_count_total": len(union),
        }

    import io, csv
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "id", "name", "category", "status", "manufacturer", "model", "sn",
        "location_id", "department_or_owner",
        "hw_gaps", "all_missing_fields", "gap_count_total",
    ])
    writer.writeheader()
    for item in items:
        writer.writerow(row_for(item))

    from fastapi.responses import Response
    from datetime import datetime
    filename = f"triage-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
