"""Moving an order along its track, and the documents attached to it.
See docs/specs/one-board-two-tracks.md."""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_provisioning_manager, require_provisioning_viewer
from ..config import settings
from ..database import get_db
from ..localtime import local_today
from ..models import CustomerOrder, OrderDocument, User
from ..order_tracks import StepRefused, advance, column_label, track_of

router = APIRouter()

# Vendor paperwork arrives as PDFs, scans, photos, spreadsheets or text.
DOC_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
DOC_MAX_BYTES = 25 * 1024 * 1024


def _visible_order(db: Session, order_id: int, user: User):
    """The order, or None when it does not exist or the user may not see it."""
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if order is None or (order.is_sensitive and not user.has_sensitive_customers_access):
        return None
    return order


@router.post("/api/orders/{order_id}/advance")
async def advance_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Move the order to the next column on its track (body: {"to": column})."""
    order = _visible_order(db, order_id, user)
    if order is None:
        return JSONResponse(status_code=404, content={"error": "Order not found"})
    try:
        body = await request.json()
    except ValueError:
        body = {}
    to = str((body or {}).get("to") or "").strip()
    old_status = order.status
    try:
        result = advance(db, order, to, local_today())
    except StepRefused as e:
        db.rollback()
        return JSONResponse(status_code=409, content={"error": str(e)})
    db.commit()
    track = track_of(order)
    log_event(
        db, "order_advanced", request=request, user_id=user.id,
        target_table="customer_orders", target_id=order.id, action="update",
        old_values={"status": old_status, "column": result["from"]},
        new_values={"status": order.status, "column": result["to"],
                    "units_deployed": result["units_deployed"],
                    "units_returned": result["units_returned"]},
        details=(f"Moved {order.order_number} from {column_label(track, result['from'])} "
                 f"to {column_label(track, result['to'])}"),
    )
    return {"ok": True, "column": result["to"], "label": column_label(track, result["to"]),
            "status": order.status, "units_deployed": result["units_deployed"],
            "units_returned": result["units_returned"]}


@router.post("/api/orders/{order_id}/documents")
async def upload_order_document(
    order_id: int,
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("certification"),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    """Attach a file to the order: a vendor certificate, validation report,
    shipping paperwork or anything else. Stored as sent, never parsed."""
    order = _visible_order(db, order_id, user)
    if order is None:
        return JSONResponse(status_code=404, content={"error": "Order not found"})
    kind = (kind or "").strip()
    if kind not in OrderDocument.KINDS:
        return JSONResponse(status_code=400, content={"error": "Unknown document kind: " + (kind or "(blank)")})
    ext = Path(file.filename or "").suffix.lower()
    if ext not in DOC_TYPES:
        return JSONResponse(status_code=400, content={
            "error": "Allowed file types: " + ", ".join(sorted(e.lstrip(".").upper() for e in DOC_TYPES))})
    content = await file.read()
    if not content:
        return JSONResponse(status_code=400, content={"error": "The file is empty"})
    if len(content) > DOC_MAX_BYTES:
        return JSONResponse(status_code=413, content={"error": "The file is larger than 25 MB"})

    folder = Path(settings.ORDER_DOC_UPLOAD_DIR) / str(order.id)
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = uuid.uuid4().hex + ext
    (folder / stored_name).write_bytes(content)
    doc = OrderDocument(
        customer_order_id=order.id, kind=kind,
        original_name=(file.filename or stored_name)[:255], stored_name=stored_name,
        content_type=DOC_TYPES[ext], size_bytes=len(content),
        note=(note or "").strip() or None,
        uploaded_by=user.display_name or user.username,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    log_event(
        db, "order_document_uploaded", request=request, user_id=user.id,
        target_table="customer_orders", target_id=order.id, action="create",
        new_values={"document_id": doc.id, "kind": kind, "name": doc.original_name},
        details=f"Attached {OrderDocument.KINDS[kind].lower()} document {doc.original_name} to {order.order_number}",
    )
    return {"ok": True, "id": doc.id, "original_name": doc.original_name, "kind": kind}


@router.get("/orders/documents/{doc_id}")
def download_order_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_viewer),
):
    doc = db.query(OrderDocument).filter(OrderDocument.id == doc_id).first()
    if doc is None or _visible_order(db, doc.customer_order_id, user) is None:
        return JSONResponse(status_code=404, content={"error": "Document not found"})
    path = Path(settings.ORDER_DOC_UPLOAD_DIR) / str(doc.customer_order_id) / doc.stored_name
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "The file is missing on disk"})
    return FileResponse(path=str(path), filename=doc.original_name,
                        media_type=doc.content_type or "application/octet-stream",
                        content_disposition_type="inline")


@router.delete("/api/orders/documents/{doc_id}")
def delete_order_document(
    doc_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_provisioning_manager),
):
    doc = db.query(OrderDocument).filter(OrderDocument.id == doc_id).first()
    if doc is None:
        return JSONResponse(status_code=404, content={"error": "Document not found"})
    order = _visible_order(db, doc.customer_order_id, user)
    if order is None:
        return JSONResponse(status_code=404, content={"error": "Document not found"})
    path = Path(settings.ORDER_DOC_UPLOAD_DIR) / str(doc.customer_order_id) / doc.stored_name
    name, kind = doc.original_name, doc.kind
    db.delete(doc)
    db.commit()
    if path.exists():
        path.unlink()
    log_event(
        db, "order_document_deleted", request=request, user_id=user.id,
        target_table="customer_orders", target_id=order.id, action="delete",
        old_values={"document_id": doc_id, "kind": kind, "name": name},
        details=f"Removed document {name} from {order.order_number}",
    )
    return {"ok": True}
