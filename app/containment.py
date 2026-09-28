"""Component containment service (Option A, 2026-07-10).

item_schema.component_history (installed/uninstalled/moved events) is the
source of truth; the item_schema.current_containment SQL VIEW (migration 065)
is THE read path — no other surface derives containment its own way.

Invariants enforced by the write routes (app/routes/containment.py):
- a component can be inside at most one unit (install requires standalone);
- parents must be parent-eligible unit categories;
- unit-category items can never be installed as components — which also
  makes chains/cycles impossible, so one-hop parent resolution is complete;
- installed items carry the containment-managed status 'Installed'.
"""

from sqlalchemy.orm import Session

from .models import Item, current_containment

# Parent-eligible categories (decision 2026-07-10). NOTE: deliberately wider
# than map PRODUCT_CATEGORIES / triage _DEPLOY_CATEGORIES, which stay
# (edge_box, cloud_box, camera_c2c) — computers host components but do not
# pin on the deployment map.
# nas joined 2026-09-28 (item 30, migration 080): a NAS is a system and its
# drives are contained storage_drive items (retire-legacy-inventory.md 6a).
# receive.html keeps a JS copy, CTM_UNIT_CATS; change both together.
UNIT_CATEGORIES = frozenset({"edge_box", "cloud_box", "camera_c2c", "computer", "nas"})


def get_current_parent(db: Session, item_id: int) -> dict | None:
    """The unit an item is currently installed in, or None (standalone)."""
    row = db.execute(
        current_containment.select().where(
            current_containment.c.component_item_id == item_id
        )
    ).first()
    if not row:
        return None
    parent = db.query(Item).filter(Item.id == row.parent_item_id).first()
    return {
        "parent_item_id": row.parent_item_id,
        "parent": parent,
        "slot_label": row.slot_label,
        "installed_date": row.installed_date,
    }


def get_current_children(db: Session, parent_item_id: int) -> list[dict]:
    """Components currently installed in a unit, name-sorted."""
    rows = db.execute(
        current_containment.select().where(
            current_containment.c.parent_item_id == parent_item_id
        )
    ).fetchall()
    if not rows:
        return []
    by_id = {r.component_item_id: r for r in rows}
    items = (
        db.query(Item)
        .filter(Item.id.in_(list(by_id.keys())))
        .order_by(Item.item_name)
        .all()
    )
    return [
        {
            "item": it,
            "slot_label": by_id[it.id].slot_label,
            "installed_date": by_id[it.id].installed_date,
        }
        for it in items
    ]


def installed_component_ids(db: Session) -> set[int]:
    """All item ids currently installed in some unit (one query)."""
    rows = db.execute(
        current_containment.select().with_only_columns(
            current_containment.c.component_item_id
        )
    ).fetchall()
    return {r[0] for r in rows}


def effective_location_overrides(db: Session, item_ids) -> dict:
    """component_item_id -> the parent unit's location_id, for the given ids.

    Read-time place inheritance: an Installed component's effective place is
    its parent's place. Callers overlay this on stored location_id:
        eff = overrides.get(item.id, item.location_id)
    One query; ids absent from the result are not installed.
    """
    ids = list(item_ids)
    if not ids:
        return {}
    parent = Item.__table__.alias("containment_parent")
    rows = db.execute(
        current_containment.select()
        .with_only_columns(
            current_containment.c.component_item_id,
            parent.c.location_id,
        )
        .join(parent, parent.c.id == current_containment.c.parent_item_id)
        .where(current_containment.c.component_item_id.in_(ids))
    ).fetchall()
    return {r[0]: r[1] for r in rows}
