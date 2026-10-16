"""The two fulfillment tracks: which one an order is on, which column it sits
in, and what moving it one step does. See docs/specs/one-board-two-tracks.md.

The stored order status vocabulary (CustomerOrder.ORDER_STATUSES) is not
changed here. Each track maps it onto its own columns; a pilot's Returned
column is derived from its units, never stored.
"""
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import CustomerOrder, DeviceProvisioning, Item, OrderDocument

VENDOR, STOCK = "vendor", "stock"

TRACKS = {
    VENDOR: "Vendor",
    STOCK: "Pilots & demos",
}

COLUMNS = {
    VENDOR: [("ordered", "Ordered"), ("building", "Building"),
             ("shipped", "Shipped"), ("installed", "Installed")],
    STOCK: [("assigned", "Assigned"), ("shipped", "Shipped"),
            ("at_site", "Out at site"), ("returned", "Returned")],
}

# Stored status to column, per track. None means off the board.
STATUS_COLUMN = {
    VENDOR: {
        "new": "ordered", "sourcing": "ordered",
        "building": "building", "testing": "building",
        "shipped": "shipped", "delivered": "shipped",
        "installed": "installed",
        "cancelled": None,
    },
    STOCK: {
        "new": "assigned", "sourcing": "assigned",
        "building": "assigned", "testing": "assigned",
        "shipped": "shipped",
        "delivered": "at_site", "installed": "at_site",
        "cancelled": None,
    },
}

FINISHED = {VENDOR: "installed", STOCK: "returned"}

# The one legal next step from each column, and its button label.
NEXT_STEP = {
    VENDOR: {"ordered": "building", "building": "shipped", "shipped": "installed"},
    STOCK: {"assigned": "shipped", "shipped": "at_site", "at_site": "returned"},
}
STEP_LABELS = {
    (VENDOR, "building"): "Start build",
    (VENDOR, "shipped"): "Mark shipped",
    (VENDOR, "installed"): "Mark installed",
    (STOCK, "shipped"): "Mark shipped",
    (STOCK, "at_site"): "Mark out at site",
    (STOCK, "returned"): "Mark returned",
}

PRE_SHIP = ("new", "sourcing", "building", "testing")
DUE_BACK_WINDOW_DAYS = 30


def track_of(order) -> str:
    """Sale orders are vendor work; pilots, demos and try-and-buy are lent from stock."""
    return VENDOR if order.order_type == "sale" else STOCK


def column_label(track: str, key: str) -> str:
    return dict(COLUMNS[track]).get(key, key)


def column_of(order, linked: int = 0, still_out: int = 0):
    """The board column for an order, or None when it is off the board.

    linked and still_out count the order's item-linked units; a pilot whose
    units are all back is Returned whatever its stored status says."""
    track = track_of(order)
    col = STATUS_COLUMN[track].get(order.status, "ordered" if track == VENDOR else "assigned")
    if col is None:
        return None
    if track == STOCK and linked > 0 and still_out == 0:
        return "returned"
    return col


def unit_counts(db: Session, order_ids) -> dict:
    """{order id: (linked, still_out)} for item-linked units."""
    ids = list(order_ids)
    if not ids:
        return {}
    rows = (
        db.query(
            DeviceProvisioning.customer_order_id,
            func.count(DeviceProvisioning.id),
            func.count(DeviceProvisioning.id).filter(DeviceProvisioning.returned_date.is_(None)),
        )
        .filter(DeviceProvisioning.customer_order_id.in_(ids),
                DeviceProvisioning.item_id.isnot(None))
        .group_by(DeviceProvisioning.customer_order_id)
        .all()
    )
    return {oid: (linked, out) for oid, linked, out in rows}


def cert_doc_orders(db: Session, order_ids) -> set:
    """Orders that carry at least one certification document."""
    ids = list(order_ids)
    if not ids:
        return set()
    return {
        oid for (oid,) in db.query(OrderDocument.customer_order_id)
        .filter(OrderDocument.customer_order_id.in_(ids), OrderDocument.kind == "certification")
        .distinct().all()
    }


def flags(order, column: str, still_out: int, has_cert_doc: bool, today: date) -> dict:
    """The tile and badge conditions for one on-board order."""
    track = track_of(order)
    finished = column == FINISHED[track]
    late = False
    due_back_soon = False
    if not finished:
        if track == VENDOR:
            late = bool(order.due_date and order.due_date < today)
        else:
            if order.status in PRE_SHIP and order.due_date and order.due_date < today:
                late = True
            if still_out and order.expected_return and order.expected_return < today:
                late = True
            if still_out and order.expected_return:
                days = (order.expected_return - today).days
                due_back_soon = 0 <= days <= DUE_BACK_WINDOW_DAYS
    docs_missing = track == VENDOR and column in ("shipped", "installed") and not has_cert_doc
    return {"open": not finished, "late": late, "due_back_soon": due_back_soon,
            "docs_missing": docs_missing}


def mark_units_deployed(db: Session, order) -> int:
    """Shipping moves the order's still-out item-linked units out the door:
    their inventory rows go Deployed. Installed, Checked Out and
    Decommissioned are managed elsewhere and never overwritten."""
    changed = 0
    linked = (
        db.query(DeviceProvisioning)
        .filter(DeviceProvisioning.customer_order_id == order.id,
                DeviceProvisioning.item_id.isnot(None),
                DeviceProvisioning.returned_date.is_(None))
        .all()
    )
    for rec in linked:
        item = db.query(Item).filter(Item.id == rec.item_id).first()
        if item and item.item_status not in ("Installed", "Checked Out", "Decommissioned", "Deployed"):
            item.item_status = "Deployed"
            changed += 1
    return changed


class StepRefused(Exception):
    """A move the order's track does not allow; the message is for the user."""


def advance(db: Session, order: CustomerOrder, to: str, today: date) -> dict:
    """Move an order one step along its track. Raises StepRefused when the
    move is not the next step or a gate holds it. Does not commit."""
    if order.status == "cancelled":
        raise StepRefused("A cancelled order cannot move")
    track = track_of(order)
    counts = unit_counts(db, [order.id]).get(order.id, (0, 0))
    current = column_of(order, *counts)
    expected = NEXT_STEP[track].get(current)
    if expected is None:
        raise StepRefused("This order is already " + column_label(track, current))
    if to != expected:
        raise StepRefused("The next step from " + column_label(track, current) + " is "
                          + column_label(track, expected))
    if order.order_type == "sale" and current == "ordered" and not order.po_number:
        raise StepRefused("Add the customer PO before starting the build")

    result = {"from": current, "to": to, "units_deployed": 0, "units_returned": 0}
    if to == "building":
        order.status = "building"
    elif to == "shipped":
        if track == STOCK and counts[0] == 0:
            raise StepRefused("Assign at least one unit from stock before shipping")
        order.status = "shipped"
        order.shipped_date = order.shipped_date or today
        result["units_deployed"] = mark_units_deployed(db, order)
    elif to == "installed":
        order.status = "installed"
        order.delivered_date = order.delivered_date or today
    elif to == "at_site":
        order.status = "delivered"
        order.delivered_date = order.delivered_date or today
    elif to == "returned":
        if counts[0] == 0:
            raise StepRefused("This order has no units to return")
        out = (
            db.query(DeviceProvisioning)
            .filter(DeviceProvisioning.customer_order_id == order.id,
                    DeviceProvisioning.item_id.isnot(None),
                    DeviceProvisioning.returned_date.is_(None))
            .all()
        )
        for p in out:
            p.returned_date = today
        result["units_returned"] = len(out)
    return result
