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
from fastapi.responses import RedirectResponse, HTMLResponse
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
