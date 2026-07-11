"""Per-unit dossier PDF (shipment-photos slice).

Mirrors the C2C composite builder (the refined fitz pattern: hebo/helv
closures with str coercion, auto page-break, live render self-check inside
the builder). One call = one item's full story: details, containment +
place, custody, component history, order/deployment history, receipts,
and every visible photo with caption/date/direction, chronological.

Sensitive-order composition: rows and photos tied to a sensitive order are
omitted for users without sensitive-customer access — a dossier printed by
a viewer must not say more than the pages they can open.
"""
from datetime import datetime
from pathlib import Path

import fitz

from .config import settings
from .models import (
    CustomerOrder, DeploymentRecord, DeviceProvisioning, Site,
    UnitPhoto, UnitPhotoItem, User,
)

MARGIN = 56


def _fmt(v):
    if v is None or v == "":
        return "—"
    return str(v)


def build_item_dossier_pdf(db, item, user, helpers) -> bytes:
    """helpers = dict with the item_detail query functions (receipts,
    components, checkouts, containment) — passed in to avoid a route-module
    import cycle."""
    doc = fitz.open()
    page = doc.new_page()
    y = MARGIN

    def line(text, size=11, dy=16, bold=False, color=(0, 0, 0)):
        nonlocal y, page
        if y > page.rect.height - MARGIN:
            page = doc.new_page()
            y = MARGIN
        font = "hebo" if bold else "helv"
        page.insert_text((MARGIN, y), str(text), fontsize=size, fontname=font, color=color)
        y += dy

    def gap(dy=10):
        nonlocal y
        y += dy

    def section(title):
        gap(8)
        line(title, size=13, dy=20, bold=True, color=(0.15, 0.15, 0.3))

    can_sensitive = user.has_sensitive_customers_access

    # ── header ───────────────────────────────────────────────────────────
    line(f"Unit Dossier — {item.item_sn or item.item_name or f'item #{item.id}'}",
         size=18, dy=26, bold=True)
    line(f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC by {user.display_name or user.username}",
         size=9, dy=14, color=(0.4, 0.4, 0.4))
    gap(6)

    # ── details ──────────────────────────────────────────────────────────
    section("Item Details")
    site = db.query(Site).filter(Site.id == item.location_id).first() if item.location_id else None
    for label, val in [
        ("Name", item.item_name), ("Serial", item.item_sn),
        ("Category", item.item_category), ("Status", item.item_status),
        ("Manufacturer", item.item_manufacturer), ("Model", item.item_model),
        ("MAC 1", item.item_mac_address_1), ("MAC 2", item.item_mac_address_2),
        ("SKU", item.brand_sku), ("Unit PN", item.brand_pn),
        ("Location", site.name if site else None),
        ("Department/Owner", item.department_or_owner),
        ("Purchased", item.date_purchased),
    ]:
        line(f"{label}: {_fmt(val)}")

    # ── containment + effective place ────────────────────────────────────
    ctm = helpers["containment"](db, item)
    section("Containment")
    if ctm["parent"]:
        p = ctm["parent"]["parent"]
        psite = db.query(Site).filter(Site.id == p.location_id).first() if p.location_id else None
        line(f"Installed in: {p.item_name or p.item_sn or f'item #{p.id}'} "
             f"(slot {_fmt(ctm['parent'].get('slot_label'))}, since {_fmt(ctm['parent'].get('installed_date'))})")
        line(f"Effective place (from parent): {_fmt(psite.name if psite else None)}")
    elif ctm["children"]:
        line(f"Unit with {len(ctm['children'])} installed component(s):")
        for ch in ctm["children"]:
            it = ch["item"]
            line(f"  - {it.item_name or it.item_sn or f'item #{it.id}'} "
                 f"(slot {_fmt(ch.get('slot_label'))}, since {_fmt(ch.get('installed_date'))})", size=10)
    else:
        line("Standalone — not installed in any unit.")

    # ── custody ──────────────────────────────────────────────────────────
    section("Custody History")
    checkouts = helpers["checkouts"](db, item.id)
    if not checkouts:
        line("No check-outs recorded.")
    for c in checkouts:
        state = "still out" if c["is_open"] else f"returned {c['checkin_date']}"
        line(f"{c['checkout_date']}: to {c['recipient']} ({state})", size=10)

    # ── component history ────────────────────────────────────────────────
    section("Component History")
    components = helpers["components"](db, item.id)
    if not components:
        line("No component events.")
    for c in components:
        ev = c["event"]
        role = "into" if c["as_component"] else "component:"
        line(f"{ev.action_date}: {ev.action} {role} {_fmt(c['counterpart_name'])}"
             f"{f' (slot {ev.slot_label})' if ev.slot_label else ''}", size=10)

    # ── orders & deployments ─────────────────────────────────────────────
    section("Order & Deployment History")
    provs = (db.query(DeviceProvisioning)
             .filter(DeviceProvisioning.item_id == item.id)
             .order_by(DeviceProvisioning.id).all())
    order_ids = [p.customer_order_id for p in provs if p.customer_order_id]
    orders = {o.id: o for o in db.query(CustomerOrder).filter(
        CustomerOrder.id.in_(order_ids or [0])).all()}
    printed = 0
    for p in provs:
        o = orders.get(p.customer_order_id)
        if not o:
            continue
        if o.is_sensitive and not can_sensitive:
            continue  # masked — same rule as every other surface
        printed += 1
        state = f"returned {p.returned_date}" if p.returned_date else "active"
        line(f"{o.order_number} — {o.customer_name} ({CustomerOrder.ORDER_TYPES.get(o.order_type, o.order_type)}, "
             f"order {o.status}, unit {state})", size=10)
        for dep in db.query(DeploymentRecord).filter(
                DeploymentRecord.customer_order_id == o.id).all():
            dsite = dep.site.name if dep.site else (dep.address or "—")
            line(f"    deployment: {dep.status}, site {dsite}, "
                 f"scheduled {_fmt(dep.scheduled_date)}, installed {_fmt(dep.installed_date)}", size=9)
    if not printed:
        line("No order linkage.")

    # ── receipts ─────────────────────────────────────────────────────────
    section("Receipts")
    receipts = helpers["receipts"](db, item.id)
    if not receipts:
        line("No receipts attached.")
    for r in receipts:
        line(f"{r['transaction_date']}: {r['record_type']} "
             f"PO {_fmt(r['purchase_order'])} ({_fmt(r['original_filename'])})", size=10)

    # ── photos, chronological, one per page ──────────────────────────────
    photos = (db.query(UnitPhoto)
              .join(UnitPhotoItem, UnitPhotoItem.photo_id == UnitPhoto.id)
              .filter(UnitPhotoItem.item_id == item.id,
                      UnitPhoto.is_hidden.is_(False))
              .order_by(UnitPhoto.taken_at.asc(), UnitPhoto.id.asc()).all())
    visible = []
    for ph in photos:
        if ph.customer_order_id:
            o = db.query(CustomerOrder).filter(CustomerOrder.id == ph.customer_order_id).first()
            if o and o.is_sensitive and not can_sensitive:
                continue
        visible.append(ph)
    uploader = {u.id: u.display_name for u in db.query(User).filter(
        User.id.in_({p.uploaded_by for p in visible if p.uploaded_by} or {0})).all()}

    section(f"Photos ({len(visible)})")
    if not visible:
        line("No photos.")
    for ph in visible:
        ipage = doc.new_page()
        head = (f"{ph.direction.upper()} — "
                f"{ph.taken_at.strftime('%Y-%m-%d %H:%M') if ph.taken_at else '—'}"
                f" — by {uploader.get(ph.uploaded_by, '—')}")
        ipage.insert_text((MARGIN, MARGIN), head, fontsize=11, fontname="hebo")
        if ph.caption:
            ipage.insert_text((MARGIN, MARGIN + 16), str(ph.caption), fontsize=10, fontname="helv")
        rect = ipage.rect + (MARGIN, MARGIN + 30, -MARGIN, -MARGIN)
        fpath = Path(settings.PHOTO_UPLOAD_DIR) / ph.file_path
        try:
            ipage.insert_image(rect, filename=str(fpath), keep_proportion=True)
        except Exception:
            ipage.insert_text((MARGIN, MARGIN + 40),
                              f"Could not embed photo: {ph.file_path}",
                              fontsize=12, fontname="hebo", color=(0.8, 0, 0))

    out = doc.tobytes()
    doc.close()
    # live render self-check (c2c pattern): never hand out a broken PDF
    check = fitz.open(stream=out, filetype="pdf")
    if check.page_count < 1:
        raise RuntimeError("dossier render produced an empty PDF")
    for p in check:
        p.get_text()
    check.close()
    return out
