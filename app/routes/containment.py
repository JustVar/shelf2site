"""Containment write routes: install / uninstall / move + picker candidates.

Every write is one component_history event plus the containment-managed
status flip; current state is always derived through the
current_containment view (app/containment.py). Editor-gated.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_editor
from ..config import settings
from ..containment import (
    UNIT_CATEGORIES, get_current_parent, installed_component_ids,
)
from ..database import get_db
from ..models import Item, ItemComponentHistory, User
from .intake import STATUSES as HAND_EDIT_STATUSES

router = APIRouter()
BP = settings.ROOT_PATH.rstrip("/")


def _err(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def _get_item(db: Session, item_id) -> Item | None:
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return None
    return db.query(Item).filter(Item.id == item_id).first()


def _label(item: Item) -> str:
    return item.item_name or item.item_sn or f"item #{item.id}"


def _guard_parent(db: Session, parent) -> JSONResponse | None:
    if parent is None:
        return _err(404, "Parent unit not found")
    if parent.item_category not in UNIT_CATEGORIES:
        return _err(400, f"{_label(parent)} is not a parent-eligible unit "
                         "(edge box, cloud box, C2C camera, or computer)")
    return None


@router.post("/api/containment/install")
async def install_component(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    body = await request.json()
    component = _get_item(db, body.get("component_item_id"))
    parent = _get_item(db, body.get("parent_item_id"))

    if component is None:
        return _err(404, "Component item not found")
    parent_error = _guard_parent(db, parent)
    if parent_error:
        return parent_error
    if component.id == parent.id:
        return _err(400, "An item cannot be installed into itself")
    if component.item_category in UNIT_CATEGORIES:
        # Also forecloses cycles: parents can never themselves be contained.
        return _err(400, f"{_label(component)} is a unit "
                         f"({component.item_category}) — units cannot be "
                         "installed as components")
    if component.item_status == "Decommissioned":
        # Code-mediated (docs/specs/item-decommission.md): reactivate first.
        return _err(409, f"{_label(component)} is decommissioned - reactivate it first")
    if component.item_status == "Checked Out":
        return _err(409, f"{_label(component)} is checked out — check it in first")
    existing = get_current_parent(db, component.id)
    if existing:
        return _err(409, f"{_label(component)} is already installed in "
                         f"{_label(existing['parent'])} — move it or uninstall first")

    slot_label = (body.get("slot_label") or "").strip() or None
    event = ItemComponentHistory(
        item_id=component.id,
        parent_item_id=parent.id,
        action="installed",
        slot_label=slot_label,
        performed_by=user.display_name or user.username,
        notes=(body.get("notes") or "").strip() or None,
    )
    component.item_status = "Installed"
    db.add(event)
    db.commit()

    log_event(
        db, "component_installed",
        request=request,
        user_id=user.id,
        target_table="items",
        target_id=component.id,
        action="update",
        details=f"Installed {_label(component)} into {_label(parent)}"
                + (f" (slot {slot_label})" if slot_label else ""),
    )

    return JSONResponse(content={
        "status": "installed",
        "component_item_id": component.id,
        "parent_item_id": parent.id,
        "slot_label": slot_label,
    })


@router.post("/api/containment/uninstall")
async def uninstall_component(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    body = await request.json()
    component = _get_item(db, body.get("component_item_id"))
    if component is None:
        return _err(404, "Component item not found")

    current = get_current_parent(db, component.id)
    if not current:
        return _err(409, f"{_label(component)} is not installed in anything")

    # Spec said "default In Storage" — that value predates the enum; the
    # item_statuses equivalent is Unassigned (same mapping H2 established).
    status_after = (body.get("status_after") or "").strip() or "Unassigned"
    if status_after not in HAND_EDIT_STATUSES:
        return _err(400, f"'{status_after}' is not a valid standalone status")

    event = ItemComponentHistory(
        item_id=component.id,
        parent_item_id=current["parent_item_id"],
        action="uninstalled",
        slot_label=current["slot_label"],
        performed_by=user.display_name or user.username,
        notes=(body.get("notes") or "").strip() or None,
    )
    component.item_status = status_after
    db.add(event)
    db.commit()

    log_event(
        db, "component_uninstalled",
        request=request,
        user_id=user.id,
        target_table="items",
        target_id=component.id,
        action="update",
        details=f"Uninstalled {_label(component)} from "
                f"{_label(current['parent']) if current['parent'] else '?'}"
                f" -> {status_after}",
    )

    return JSONResponse(content={
        "status": "uninstalled",
        "component_item_id": component.id,
        "status_after": status_after,
    })


@router.post("/api/containment/move")
async def move_component(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    body = await request.json()
    component = _get_item(db, body.get("component_item_id"))
    new_parent = _get_item(db, body.get("new_parent_item_id"))

    if component is None:
        return _err(404, "Component item not found")
    current = get_current_parent(db, component.id)
    if not current:
        return _err(409, f"{_label(component)} is not installed — use install")
    parent_error = _guard_parent(db, new_parent)
    if parent_error:
        return parent_error
    if new_parent.id == component.id:
        return _err(400, "An item cannot be installed into itself")
    if new_parent.id == current["parent_item_id"]:
        return _err(400, f"{_label(component)} is already installed in "
                         f"{_label(new_parent)}")

    slot_label = (body.get("slot_label") or "").strip() or None
    # A single atomic 'moved' event: it carries the NEW parent; the previous
    # residency is implied by the prior event (model semantics).
    event = ItemComponentHistory(
        item_id=component.id,
        parent_item_id=new_parent.id,
        action="moved",
        slot_label=slot_label,
        performed_by=user.display_name or user.username,
        notes=(body.get("notes") or "").strip() or None,
    )
    db.add(event)
    db.commit()

    log_event(
        db, "component_moved",
        request=request,
        user_id=user.id,
        target_table="items",
        target_id=component.id,
        action="update",
        details=f"Moved {_label(component)} from "
                f"{_label(current['parent']) if current['parent'] else '?'} "
                f"to {_label(new_parent)}",
    )

    return JSONResponse(content={
        "status": "moved",
        "component_item_id": component.id,
        "parent_item_id": new_parent.id,
        "slot_label": slot_label,
    })


@router.get("/api/containment/candidates")
def containment_candidates(
    mode: str,
    q: str = "",
    exclude_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Picker search. mode=units -> parent-eligible units;
    mode=components -> installable items (non-unit, not installed,
    not checked out)."""
    if mode not in ("units", "components"):
        return _err(400, "mode must be 'units' or 'components'")

    query = db.query(Item)
    if mode == "units":
        query = query.filter(Item.item_category.in_(list(UNIT_CATEGORIES)))
    else:
        query = query.filter(
            Item.item_category.isnot(None),
            Item.item_category.notin_(list(UNIT_CATEGORIES)),
            or_(Item.item_status.is_(None), Item.item_status != "Checked Out"),
        )
        installed = installed_component_ids(db)
        if installed:
            query = query.filter(Item.id.notin_(list(installed)))

    q = (q or "").strip()
    if q:
        # escape ilike wildcards — scanned serials can contain % / _
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        query = query.filter(or_(
            Item.item_name.ilike(like),
            Item.item_sn.ilike(like),
        ))
    if exclude_id:
        query = query.filter(Item.id != exclude_id)

    rows = query.order_by(Item.item_name).limit(20).all()
    return JSONResponse(content={"results": [
        {
            "id": r.id,
            "name": r.item_name or "(unnamed)",
            "serial": r.item_sn,
            "category": r.item_category,
            "status": r.item_status,
        }
        for r in rows
    ]})
