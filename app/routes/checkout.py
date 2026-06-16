"""Hardware check-out / check-in (custody tracking).

Check-out: an existing item leaves custody. We save its current status as
prior_status, flip item.item_status to 'Checked Out', and open a row in
item_schema.checkouts (checkin_date NULL = still out).

Check-in: close the open checkout row (set checkin_date) and restore the
item's prior_status. Closed rows form the per-item custody history.

Write actions require editor-or-above. The check-out *recipient* can be any
active user (FK) or a free-text name (external people / projects).
"""

from pathlib import Path
from datetime import date

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth import get_current_user, User
from ..audit import log_event
from ..config import settings
from ..database import get_db
from ..models import Item, ItemCheckout, User as UserModel

router = APIRouter(tags=["checkout"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


def _active_users(db: Session):
    return (
        db.query(UserModel)
        .filter(UserModel.is_active.is_(True))
        .order_by(UserModel.display_name)
        .all()
    )


@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Form to check an item out: pick an eligible item + a recipient."""
    eligible = (
        db.query(Item)
        .filter(Item.item_status != "Checked Out")
        .order_by(Item.item_name)
        .all()
    )
    return templates.TemplateResponse(
        "checkout.html",
        {
            "request": request,
            "user": user,
            "eligible_items": eligible,
            "users_for_picker": _active_users(db),
        },
    )


@router.post("/checkout")
def do_checkout(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    item_id: int = Form(...),
    checked_out_to_user_id: str = Form(""),
    checked_out_to_name: str = Form(""),
    notes: str = Form(""),
):
    """Open a checkout: flip status to 'Checked Out', insert checkouts row."""
    if not user.is_editor_or_above:
        return RedirectResponse(f"{BP}/checkout?toast=Not+permitted", status_code=303)

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return RedirectResponse(
            f"{BP}/checkout?toast=Item+not+found", status_code=303
        )
    if item.item_status == "Checked Out":
        return RedirectResponse(
            f"{BP}/items/{item.id}?toast=Already+checked+out", status_code=303
        )

    uid = int(checked_out_to_user_id) if checked_out_to_user_id.strip() else None
    name = checked_out_to_name.strip() or None
    if uid is None and name is None:
        return RedirectResponse(
            f"{BP}/checkout?toast=Pick+a+recipient", status_code=303
        )

    co = ItemCheckout(
        item_id=item.id,
        checked_out_to_user_id=uid,
        checked_out_to_name=name,
        prior_status=item.item_status,
        checked_out_by=user.display_name,
        notes=notes.strip() or None,
    )
    item.item_status = "Checked Out"
    db.add(co)
    db.commit()
    db.refresh(co)

    log_event(
        db,
        "item_checkout",
        request=request,
        user_id=user.id,
        target_table="checkouts",
        target_id=co.id,
        action="create",
        details=f"Checked out item #{item.id} to {name or 'user#' + str(uid)}",
    )
    return RedirectResponse(
        f"{BP}/items/{item.id}?toast=Checked+out", status_code=303
    )


@router.get("/checkin", response_class=HTMLResponse)
def checkin_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List currently-open checkouts to pick one for return."""
    open_rows = (
        db.query(ItemCheckout)
        .filter(ItemCheckout.checkin_date.is_(None))
        .order_by(ItemCheckout.checkout_date)
        .all()
    )
    rows = []
    for co in open_rows:
        item = db.query(Item).filter(Item.id == co.item_id).first()
        recipient = co.checked_out_to_name
        if not recipient and co.checked_out_to_user_id:
            u = db.query(UserModel).filter(
                UserModel.id == co.checked_out_to_user_id
            ).first()
            recipient = u.display_name if u else f"user#{co.checked_out_to_user_id}"
        rows.append({"checkout": co, "item": item, "recipient": recipient or "—"})

    return templates.TemplateResponse(
        "checkin.html",
        {"request": request, "user": user, "open_checkouts": rows},
    )


@router.post("/checkin")
def do_checkin(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    checkout_id: int = Form(...),
    notes: str = Form(""),
):
    """Close an open checkout: set checkin_date, restore item.item_status."""
    if not user.is_editor_or_above:
        return RedirectResponse(f"{BP}/checkin?toast=Not+permitted", status_code=303)

    co = (
        db.query(ItemCheckout)
        .filter(ItemCheckout.id == checkout_id, ItemCheckout.checkin_date.is_(None))
        .first()
    )
    if not co:
        return RedirectResponse(
            f"{BP}/checkin?toast=Checkout+not+found+or+already+returned",
            status_code=303,
        )

    item = db.query(Item).filter(Item.id == co.item_id).first()
    co.checkin_date = date.today()
    if notes.strip():
        co.notes = (co.notes + "\n" if co.notes else "") + notes.strip()
    if item:
        item.item_status = co.prior_status or "Unassigned"
    db.commit()

    log_event(
        db,
        "item_checkin",
        request=request,
        user_id=user.id,
        target_table="checkouts",
        target_id=co.id,
        action="update",
        details=f"Checked in item #{co.item_id}",
    )
    target = f"{BP}/items/{co.item_id}" if item else f"{BP}/checkin"
    return RedirectResponse(f"{target}?toast=Checked+in", status_code=303)


def _broadcast_custody(db, user, source):
    """Invalidate sidebar counts + publish triage SSE, mirroring the inventory
    bulk handler. Custody flips item_status but 'Checked Out' is a valid status,
    so gap counts rarely move; we broadcast for cross-surface consistency."""
    from ..sidebar_cache import invalidate_sidebar_counts
    from .sse import publish_event
    from .triage import TRIAGE_ROLES, _count_role_gaps, get_triage_total_count
    invalidate_sidebar_counts()
    role_counts = {k: _count_role_gaps(db, k) for k in TRIAGE_ROLES.keys()}
    publish_event("triage_gap_changed", {
        "item_id": None,
        "field_name": "item_status",
        "user_id": user.id,
        "role_counts": role_counts,
        "total_items_with_gaps": get_triage_total_count(db),
    })


@router.post("/checkout/bulk")
async def do_bulk_checkout(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check out many items to one shared recipient. Skips items already out."""
    if not user.is_editor_or_above:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

    form = await request.form()
    item_ids = [int(i) for i in form.getlist("item_ids")]
    checked_out_to_user_id = (form.get("checked_out_to_user_id") or "").strip()
    checked_out_to_name = (form.get("checked_out_to_name") or "").strip()
    notes = (form.get("notes") or "").strip()

    if not item_ids:
        return JSONResponse({"success": False, "error": "No items selected"}, status_code=400)

    uid = int(checked_out_to_user_id) if checked_out_to_user_id else None
    name = checked_out_to_name or None
    if uid is None and name is None:
        return JSONResponse({"success": False, "error": "Pick a recipient"}, status_code=400)

    items = db.query(Item).filter(Item.id.in_(item_ids)).all()
    updated, skipped_ids = 0, []
    new_checkouts = []
    for item in items:
        if item.item_status == "Checked Out":
            skipped_ids.append(item.id)
            continue
        co = ItemCheckout(
            item_id=item.id,
            checked_out_to_user_id=uid,
            checked_out_to_name=name,
            prior_status=item.item_status,
            checked_out_by=user.display_name,
            notes=notes or None,
        )
        item.item_status = "Checked Out"
        db.add(co)
        new_checkouts.append((item.id, co))
        updated += 1
    # items found in neither query (bad ids) are silently skipped
    found_ids = {i.id for i in items}
    skipped_ids += [iid for iid in item_ids if iid not in found_ids]

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    for item_id, co in new_checkouts:
        db.refresh(co)
        log_event(
            db, "item_checkout", request=request, user_id=user.id,
            target_table="checkouts", target_id=co.id, action="create",
            details=f"Bulk checked out item #{item_id} to {name or 'user#' + str(uid)}",
        )
    _broadcast_custody(db, user, "checkout_bulk")
    return JSONResponse({
        "success": True,
        "updated_count": updated,
        "skipped_count": len(skipped_ids),
        "skipped_ids": skipped_ids,
    })


@router.post("/checkin/bulk")
async def do_bulk_checkin(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check in many items: close each open checkout, restore prior_status.
    Skips items with no open checkout."""
    if not user.is_editor_or_above:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

    form = await request.form()
    item_ids = [int(i) for i in form.getlist("item_ids")]
    notes = (form.get("notes") or "").strip()

    if not item_ids:
        return JSONResponse({"success": False, "error": "No items selected"}, status_code=400)

    open_rows = (
        db.query(ItemCheckout)
        .filter(ItemCheckout.item_id.in_(item_ids), ItemCheckout.checkin_date.is_(None))
        .all()
    )
    closed = []
    seen = set()
    for co in open_rows:
        item = db.query(Item).filter(Item.id == co.item_id).first()
        co.checkin_date = date.today()
        if notes:
            co.notes = (co.notes + "\n" if co.notes else "") + notes
        if item:
            item.item_status = co.prior_status or "Unassigned"
        closed.append((co.item_id, co.id))
        seen.add(co.item_id)

    skipped_ids = [iid for iid in item_ids if iid not in seen]

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    for item_id, co_id in closed:
        log_event(
            db, "item_checkin", request=request, user_id=user.id,
            target_table="checkouts", target_id=co_id, action="update",
            details=f"Bulk checked in item #{item_id}",
        )
    _broadcast_custody(db, user, "checkin_bulk")
    return JSONResponse({
        "success": True,
        "updated_count": len(closed),
        "skipped_count": len(skipped_ids),
        "skipped_ids": skipped_ids,
    })
