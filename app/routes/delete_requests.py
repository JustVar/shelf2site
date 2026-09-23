"""Delete request queue routes. Spec: docs/specs/delete-request-queue.md."""

from pathlib import Path

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import delete_requests as dr
from ..audit import log_event, model_to_dict
from ..auth import require_admin, require_editor, User
from ..config import settings
from ..database import get_db
from ..models import DeleteRequest

router = APIRouter(tags=["delete_requests"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


def _err(message, status, **extra):
    body = {"error": message}
    body.update(extra)
    return JSONResponse(body, status_code=status)


def _invalidate_counts():
    from ..sidebar_cache import (
        invalidate_category_stats, invalidate_sidebar_counts, invalidate_triage_cache,
    )
    invalidate_sidebar_counts()
    invalidate_triage_cache()
    invalidate_category_stats()


@router.post("/api/delete-requests")
def file_delete_request(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """File a request. One pending request per target; items must be clean."""
    target_table = payload.get("target_table")
    if target_table not in dr.TARGETS:
        return _err("Unknown record type", 400)
    try:
        target_id = int(payload.get("target_id"))
    except (TypeError, ValueError):
        return _err("A record id is required", 400)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        return _err("A reason is required", 400)

    target = dr.load_target(db, target_table, target_id)
    if target is None:
        return _err("Record not found", 404)
    if dr.pending_for(db, target_table, target_id):
        return _err("A delete request is already pending for this record", 409)
    if target_table == "items":
        blockers = dr.item_blockers(db, target_id)
        if blockers:
            return _err(
                "This item has history (" + ", ".join(blockers) + ") and cannot be "
                "deleted. Decommission it instead.",
                409, links=blockers,
            )

    req = DeleteRequest(
        target_table=target_table,
        target_id=target_id,
        target_label=dr.target_label(target_table, target),
        reason=reason,
        status="pending",
        requested_by=user.id,
    )
    db.add(req)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _err("A delete request is already pending for this record", 409)

    log_event(db, "delete_requested", request=request, user_id=user.id,
              target_table=target_table, target_id=target_id, action="request",
              new_values={"request_id": req.id, "reason": reason},
              details="Delete requested: " + req.target_label)
    _invalidate_counts()
    return JSONResponse({"ok": True, "id": req.id})


def _pending_or_error(db, request_id):
    req = (db.query(DeleteRequest)
           .filter(DeleteRequest.id == request_id)
           .with_for_update()
           .first())
    if req is None:
        return None, _err("Request not found", 404)
    if req.status != "pending":
        return None, _err("This request is no longer pending", 409)
    return req, None


@router.post("/api/delete-requests/{request_id}/withdraw")
def withdraw_delete_request(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """The requester withdraws their own pending request."""
    req, error = _pending_or_error(db, request_id)
    if error:
        db.rollback()
        return error
    if req.requested_by != user.id:
        db.rollback()
        return _err("Only the requester can withdraw this request", 403)
    req.status = "withdrawn"
    req.decided_by = user.id
    req.decided_at = func.now()
    db.commit()
    log_event(db, "delete_request_withdrawn", request=request, user_id=user.id,
              target_table=req.target_table, target_id=req.target_id, action="withdraw",
              new_values={"request_id": req.id},
              details="Delete request withdrawn: " + req.target_label)
    _invalidate_counts()
    return JSONResponse({"ok": True})


@router.post("/api/delete-requests/{request_id}/reject")
def reject_delete_request(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Reject. The requester is not told; the audit log records it."""
    req, error = _pending_or_error(db, request_id)
    if error:
        db.rollback()
        return error
    req.status = "rejected"
    req.decided_by = user.id
    req.decided_at = func.now()
    db.commit()
    log_event(db, "delete_request_rejected", request=request, user_id=user.id,
              target_table=req.target_table, target_id=req.target_id, action="reject",
              new_values={"request_id": req.id},
              details="Delete request rejected: " + req.target_label)
    _invalidate_counts()
    return JSONResponse({"ok": True})


@router.post("/api/delete-requests/{request_id}/approve")
def approve_delete_request(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Approve: check again, delete the target, close the request. One transaction."""
    req, error = _pending_or_error(db, request_id)
    if error:
        db.rollback()
        return error

    target = dr.load_target(db, req.target_table, req.target_id, lock=True)
    if target is None:
        db.rollback()
        return _err("The record no longer exists. Reject this request to close it.", 409)

    snapshot = model_to_dict(target)
    if req.target_table == "items":
        blockers = dr.item_blockers(db, req.target_id)
        if blockers:
            db.rollback()
            return _err(
                "This item now has history (" + ", ".join(blockers) + ") and cannot "
                "be deleted. The request stays pending.",
                409, links=blockers,
            )
        dr.delete_item(db, req.target_id)
    else:
        dr.delete_vendor(db, target)

    req.status = "approved"
    req.decided_by = user.id
    req.decided_at = func.now()
    db.commit()

    log_event(db, "delete_request_approved", request=request, user_id=user.id,
              target_table=req.target_table, target_id=req.target_id, action="approve",
              new_values={"request_id": req.id},
              details="Delete request approved: " + req.target_label)
    if req.target_table == "items":
        log_event(db, "item_deleted", request=request, user_id=user.id,
                  target_table="items", target_id=req.target_id, action="delete",
                  old_values=snapshot,
                  details="Deleted item by request #" + str(req.id) + ": " + req.target_label)
    else:
        log_event(db, "vendor_deleted", request=request, user_id=user.id,
                  target_table="vendor_profiles", target_id=req.target_id, action="delete",
                  old_values=snapshot,
                  details="Deleted vendor profile by request #" + str(req.id) + ": "
                          + req.target_label)
    _invalidate_counts()
    return JSONResponse({"ok": True})


def _row(db, req):
    exists = dr.load_target(db, req.target_table, req.target_id) is not None
    return {
        "id": req.id,
        "kind": "Item" if req.target_table == "items" else "Vendor",
        "label": req.target_label,
        "path": dr.target_path(req.target_table, req.target_id) if exists else None,
        "reason": req.reason,
        "status": req.status,
        "requester": (req.requester.display_name or req.requester.username)
                     if req.requester else "(removed user)",
        "decider": (req.decider.display_name or req.decider.username)
                   if req.decider else "",
        "requested_at": req.requested_at,
        "decided_at": req.decided_at,
    }


@router.get("/admin/delete-requests", response_class=HTMLResponse)
def delete_requests_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    pending = (db.query(DeleteRequest)
               .filter(DeleteRequest.status == "pending")
               .order_by(DeleteRequest.requested_at.asc(), DeleteRequest.id.asc())
               .all())
    decided = (db.query(DeleteRequest)
               .filter(DeleteRequest.status != "pending")
               .order_by(DeleteRequest.decided_at.desc().nullslast(), DeleteRequest.id.desc())
               .limit(50)
               .all())
    return templates.TemplateResponse("admin_delete_requests.html", {
        "request": request,
        "user": user,
        "pending": [_row(db, r) for r in pending],
        "decided": [_row(db, r) for r in decided],
    })
