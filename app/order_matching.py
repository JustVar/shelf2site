"""Shared "what stock can fill this SKU requirement" matching.

ONE definition used by both the order-detail availability card and the
fulfillment board's Assign panel, so the two surfaces can never disagree
about what counts as an assignable unit.

A candidate is an item_schema.items row that:
  * matches the requirement string — case-insensitive equality on
    item_sku (catalog identity), with a fallback ilike on item_model
    for free-text requirements that are not catalog SKUs;
  * is 'Ready to Deploy' — explicitly staged stock. Unassigned/Pending
    rows are deliberately NOT offered (they have not been triaged), and
    the status filter also excludes Installed/Checked Out units;
  * has no still-out provisioning row (item_id link with returned_date
    IS NULL) — mirrors the C2C one-still-out-per-item invariant.

Legacy public.* tables are NOT consulted here; item_schema.items is the
system of record (2026-07 Casey import). The availability card still adds
legacy-table counts separately while those tables are retired.
"""
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .models import DeviceProvisioning, Item


def _escape_like(value: str) -> str:
    """Escape ilike wildcards — requirement strings are user text."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def candidate_items(db: Session, model: str) -> list[Item]:
    """Items that could fill one requirement line's model/SKU string."""
    model = (model or "").strip()
    if not model:
        return []
    still_out = (
        db.query(DeviceProvisioning.item_id)
        .filter(
            DeviceProvisioning.item_id.isnot(None),
            DeviceProvisioning.returned_date.is_(None),
        )
    )
    return (
        db.query(Item)
        .filter(
            or_(
                func.lower(Item.item_sku) == model.lower(),
                Item.item_model.ilike(f"%{_escape_like(model)}%"),
            ),
            Item.item_status == "Ready to Deploy",
            ~Item.id.in_(still_out),
        )
        .order_by(Item.id)
        .all()
    )


def requirement_lines(order) -> list[dict]:
    """Normalized {model, qty, source} lines off an order.

    Tolerates the legacy 'sku' key (pre-editor rows were written by hand
    through the API and both spellings exist in history); the editor and
    update route write the canonical 'model' key only.
    """
    lines = []
    for req in (order.sku_requirements or []):
        if not isinstance(req, dict):
            continue
        model = (req.get("model") or req.get("sku") or "").strip()
        if not model:
            continue
        try:
            qty = int(req.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        source = (req.get("source") or "tbd").strip() or "tbd"
        lines.append({"model": model, "qty": qty, "source": source})
    return lines
