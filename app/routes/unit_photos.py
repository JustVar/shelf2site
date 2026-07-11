"""Unit/shipment photo API (shipment-photos slice).

RBAC: editor+ uploads, tags, soft-hides; hard delete is admin-only.
Viewers can list/see photos EXCEPT those attached to a sensitive order
(composed with has_sensitive_customers_access, masking as absence).
Kiosk sessions never reach these routes (the /api middleware confinement).
"""
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import get_current_user, require_admin, require_editor
from ..config import settings
from ..database import get_db
from ..models import (
    CustomerOrder, DeviceProvisioning, Item, ReceivingEvent,
    UnitPhoto, UnitPhotoItem, User,
)
from ..photo_store import PhotoValidationError, save_unit_photo

logger = logging.getLogger(__name__)
router = APIRouter()
BP = settings.ROOT_PATH.rstrip("/")

DIRECTIONS = ("inbound", "outbound")


def _order_visible(db: Session, order_id: int | None, user: User) -> bool:
    if not order_id or user.has_sensitive_customers_access:
        return True
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    return not (order and order.is_sensitive)


def _photo_visible(db: Session, photo: UnitPhoto, user: User) -> bool:
    """Sensitive-order photos are invisible to non-privileged users."""
    return _order_visible(db, photo.customer_order_id, user)


def _tag_serials(db: Session, photo: UnitPhoto, serials: list[str]) -> list[dict]:
    """Resolve serials to item_schema items (case-insensitive — same rule as
    the scan routing) and tag. Unresolved serials are reported, never fatal."""
    results = []
    existing = {t.item_id for t in photo.items}
    for raw in serials:
        s = (raw or "").strip()
        if not s:
            continue
        item = db.query(Item).filter(func.lower(Item.item_sn) == s.lower()).first()
        if not item:
            results.append({"serial": s, "error": "not found in inventory"})
            continue
        if item.id not in existing:
            db.add(UnitPhotoItem(photo_id=photo.id, item_id=item.id))
            existing.add(item.id)
        results.append({"serial": s, "item_id": item.id})
    return results


def _photo_payload(photo: UnitPhoto, tagged: list[dict] | None = None) -> dict:
    return {
        "photo_id": photo.id,
        "direction": photo.direction,
        "caption": photo.caption,
        "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
        "file_url": f"{BP}/api/photos/{photo.id}/file",
        "thumb_url": f"{BP}/api/photos/{photo.id}/thumb",
        "items": [{"item_id": t.item_id,
                   "serial": t.item.item_sn if t.item else None} for t in photo.items],
        **({"tagged": tagged} if tagged is not None else {}),
    }


@router.post("/api/photos")
async def upload_unit_photo(
    request: Request,
    file: UploadFile = File(...),
    direction: str = Form(...),
    caption: str = Form(""),
    receiving_event_id: int | None = Form(None),
    customer_order_id: int | None = Form(None),
    deployment_record_id: int | None = Form(None),
    serials: str = Form(""),          # comma/newline separated, tagged on upload
    tag_order_units: bool = Form(False),  # outbound: pre-tag the order's still-out units
    run_ocr: bool = Form(False),      # receive-page label OCR (supersedes /api/receive/photo)
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    if direction not in DIRECTIONS:
        return JSONResponse(status_code=400, content={"error": "direction must be inbound or outbound"})
    if customer_order_id and not _order_visible(db, customer_order_id, user):
        return JSONResponse(status_code=404, content={"error": "Order not found"})
    if receiving_event_id:
        if not db.query(ReceivingEvent.id).filter(
                ReceivingEvent.id == receiving_event_id).first():
            return JSONResponse(status_code=400, content={"error": "Receiving event not found"})
        n = db.query(UnitPhoto).filter(
            UnitPhoto.receiving_event_id == receiving_event_id,
            UnitPhoto.is_hidden.is_(False)).count()
        if n >= settings.UNIT_PHOTO_MAX_PER_EVENT:
            return JSONResponse(status_code=400, content={
                "error": f"This event already has {n} photos "
                         f"(cap {settings.UNIT_PHOTO_MAX_PER_EVENT})."})

    content = await file.read()
    try:
        stored = save_unit_photo(content, file.content_type, file.filename or "")
    except PhotoValidationError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    photo = UnitPhoto(
        file_path=stored["file_path"],
        thumb_path=stored["thumb_path"],
        direction=direction,
        caption=(caption or "").strip() or None,
        taken_at=stored["taken_at"] or datetime.utcnow(),
        original_filename=file.filename,
        file_size=stored["file_size"],
        uploaded_by=user.id,
        receiving_event_id=receiving_event_id,
        customer_order_id=customer_order_id,
        deployment_record_id=deployment_record_id,
    )
    db.add(photo)
    db.flush()

    tagged = _tag_serials(db, photo, serials.replace("\n", ",").split(","))
    if tag_order_units and customer_order_id:
        # Outbound capture points pre-tag the order's still-out item-linked
        # units; the tag set stays adjustable afterwards.
        for prov in db.query(DeviceProvisioning).filter(
                DeviceProvisioning.customer_order_id == customer_order_id,
                DeviceProvisioning.item_id.isnot(None),
                DeviceProvisioning.returned_date.is_(None)).all():
            if prov.item_id not in {t.item_id for t in photo.items}:
                db.add(UnitPhotoItem(photo_id=photo.id, item_id=prov.item_id))
    db.commit()
    db.refresh(photo)

    log_event(
        db, "unit_photo_uploaded",
        request=request, user_id=user.id,
        target_table="unit_photos", target_id=photo.id, action="create",
        details=f"{direction} photo ({stored['file_size']} bytes), "
                f"event={receiving_event_id or '—'} order={customer_order_id or '—'}, "
                f"tags={len(photo.items)}",
    )

    payload = _photo_payload(photo, tagged)
    if run_ocr:
        try:
            from scanner.ocr_processor import process_photo_for_intake
            payload["ocr"] = process_photo_for_intake(
                Path(settings.PHOTO_UPLOAD_DIR) / photo.file_path)
        except Exception as e:
            payload["ocr"] = {"_ocr_error": str(e)}
    return JSONResponse(content=payload)


@router.get("/api/photos")
def list_unit_photos(
    item_id: int | None = None,
    order_id: int | None = None,
    event_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(UnitPhoto).filter(UnitPhoto.is_hidden.is_(False))
    if item_id:
        q = q.join(UnitPhotoItem).filter(UnitPhotoItem.item_id == item_id)
    elif order_id:
        q = q.filter(UnitPhoto.customer_order_id == order_id)
    elif event_id:
        q = q.filter(UnitPhoto.receiving_event_id == event_id)
    else:
        return JSONResponse(status_code=400, content={"error": "item_id, order_id or event_id required"})
    photos = [p for p in q.order_by(UnitPhoto.taken_at.asc(), UnitPhoto.id.asc()).all()
              if _photo_visible(db, p, user)]
    uploader_ids = {p.uploaded_by for p in photos if p.uploaded_by}
    names = {u.id: u.display_name for u in
             db.query(User).filter(User.id.in_(uploader_ids or {0})).all()}
    return JSONResponse(content={"photos": [
        {**_photo_payload(p), "uploaded_by": names.get(p.uploaded_by)} for p in photos
    ]})


def _serve(db, photo_id, user, thumb):
    photo = db.query(UnitPhoto).filter(UnitPhoto.id == photo_id).first()
    if not photo or photo.is_hidden or not _photo_visible(db, photo, user):
        return JSONResponse(status_code=404, content={"error": "Photo not found"})
    path = Path(settings.PHOTO_UPLOAD_DIR) / (photo.thumb_path if thumb else photo.file_path)
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "File missing on disk"})
    return FileResponse(path=str(path), media_type="image/jpeg",
                        filename=photo.original_filename or f"photo-{photo.id}.jpg",
                        content_disposition_type="inline")


@router.get("/api/photos/{photo_id}/file")
def serve_unit_photo(photo_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return _serve(db, photo_id, user, thumb=False)


@router.get("/api/photos/{photo_id}/thumb")
def serve_unit_photo_thumb(photo_id: int, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    return _serve(db, photo_id, user, thumb=True)


@router.post("/api/photos/{photo_id}/tags")
async def retag_unit_photo(
    photo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Add serials / remove item ids. Editor+ can retag any time."""
    photo = db.query(UnitPhoto).filter(UnitPhoto.id == photo_id).first()
    if not photo or photo.is_hidden or not _photo_visible(db, photo, user):
        return JSONResponse(status_code=404, content={"error": "Photo not found"})
    body = await request.json()
    tagged = _tag_serials(db, photo, body.get("add") or [])
    for item_id in (body.get("remove") or []):
        db.query(UnitPhotoItem).filter(
            UnitPhotoItem.photo_id == photo.id,
            UnitPhotoItem.item_id == int(item_id)).delete()
    db.commit()
    db.refresh(photo)
    log_event(db, "unit_photo_retagged", request=request, user_id=user.id,
              target_table="unit_photos", target_id=photo.id, action="update",
              details=f"tags now {len(photo.items)}")
    return JSONResponse(content=_photo_payload(photo, tagged))


@router.post("/api/photos/{photo_id}/hide")
async def hide_unit_photo(
    photo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Soft-hide (the spec's deletion): audited, reversible by admins in DB."""
    photo = db.query(UnitPhoto).filter(UnitPhoto.id == photo_id).first()
    if not photo or not _photo_visible(db, photo, user):
        return JSONResponse(status_code=404, content={"error": "Photo not found"})
    photo.is_hidden = True
    photo.hidden_by = user.id
    photo.hidden_at = datetime.utcnow()
    db.commit()
    log_event(db, "unit_photo_hidden", request=request, user_id=user.id,
              target_table="unit_photos", target_id=photo.id, action="delete",
              details=f"soft-hidden {photo.file_path}")
    return JSONResponse(content={"status": "hidden", "photo_id": photo.id})


@router.delete("/api/photos/{photo_id}")
async def delete_unit_photo(
    photo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Hard delete — admin only. Removes files and the row."""
    photo = db.query(UnitPhoto).filter(UnitPhoto.id == photo_id).first()
    if not photo:
        return JSONResponse(status_code=404, content={"error": "Photo not found"})
    for rel in (photo.file_path, photo.thumb_path):
        try:
            (Path(settings.PHOTO_UPLOAD_DIR) / rel).unlink(missing_ok=True)
        except OSError:
            logger.warning("unit-photo delete: could not remove %s", rel)
    db.delete(photo)
    db.commit()
    log_event(db, "unit_photo_deleted", request=request, user_id=user.id,
              target_table="unit_photos", target_id=photo_id, action="delete",
              details=f"hard-deleted {photo.file_path}")
    return JSONResponse(content={"status": "deleted", "photo_id": photo_id})