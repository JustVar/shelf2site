"""Free-text PO ↔ oem_purchase_orders matching (SCANNER_AUDIT §3, starter tier).

oem_purchase_orders rows are per-SKU line items sharing one po_number, so a
matched PO returns a LIST of lines. Matching is case/space-insensitive TEXT
comparison — deliberately NOT an FK: the receiving event's purchase_order
stays free text, unmatched text just gets a quiet hint, and receiving never
blocks on a match. The same normalization is used everywhere (event create,
event panel, intake sync, OEM card) so the surfaces cannot disagree.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from .localtime import local_today
from .models import OEMPurchaseOrder


def norm_po(text: str | None) -> str:
    """Case/space-insensitive PO key ('po 123 ' == 'PO123')."""
    return "".join((text or "").split()).upper()


def norm_sku(text: str | None) -> str:
    return "".join((text or "").split()).upper()


def match_oem_lines(db: Session, po_text: str | None) -> list[OEMPurchaseOrder]:
    """All OEM PO line rows whose po_number matches the free text."""
    key = norm_po(po_text)
    if not key:
        return []
    return (
        db.query(OEMPurchaseOrder)
        .filter(
            OEMPurchaseOrder.po_number.isnot(None),
            func.upper(func.replace(OEMPurchaseOrder.po_number, " ", "")) == key,
        )
        .order_by(OEMPurchaseOrder.sku)
        .all()
    )


def oem_line_summary(rows: list[OEMPurchaseOrder]) -> list[dict]:
    return [
        {
            "id": r.id,
            "sku": r.sku,
            "qty_ordered": r.qty_ordered or 0,
            "qty_received": r.qty_received or 0,
            "status": r.status,
        }
        for r in rows
    ]


def sync_oem_receipt(db: Session, po_text: str | None, unit_sku: str | None) -> OEMPurchaseOrder | None:
    """One unit with `unit_sku` arrived against `po_text`: increment the
    matching line and advance its status per the existing OEM lifecycle
    (→ receiving on first receipt, → verified when the line is full).
    Returns the touched row, or None when nothing matched — a receive
    NEVER fails on a missing match. Caller commits.
    """
    sku_key = norm_sku(unit_sku)
    if not sku_key:
        return None
    for row in match_oem_lines(db, po_text):
        if norm_sku(row.sku) != sku_key or row.status == "cancelled":
            continue
        row.qty_received = (row.qty_received or 0) + 1
        if row.status in ("ordered", "in_production", "acceptance"):
            row.status = "receiving"
        if (row.qty_received or 0) >= (row.qty_ordered or 0) and row.status == "receiving":
            row.status = "verified"
            if not row.received_date:
                row.received_date = local_today()
        return row
    return None
