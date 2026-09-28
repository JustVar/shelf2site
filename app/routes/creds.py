"""Credentials vault route: item-native, session auth protected, audit logged.

Item 30 S4 (docs/specs/retire-legacy-inventory.md): credentials hang off
item_schema.items through device_credentials.item_id (migration 080, filled
by migration 081). The item detail page reads this route; the old
per-legacy-table route and its dead modal are retired.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_credentials_access, User
from ..credentials import decrypt
from ..database import get_db
from ..models import DeviceCredential, Item

router = APIRouter()


@router.get("/items/{item_id}")
def get_item_credentials(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_credentials_access),
):
    """Decrypted credentials for one item. Every access is audit-logged."""
    if not db.query(Item.id).filter(Item.id == item_id).first():
        return JSONResponse(status_code=404, content={"error": "Item not found"})

    creds = (
        db.query(DeviceCredential)
        .filter(DeviceCredential.item_id == item_id)
        .order_by(DeviceCredential.id)
        .all()
    )

    # Audit log: credential view (even if none are stored)
    log_event(
        db, "credential_viewed",
        request=request,
        user_id=user.id,
        target_table="items",
        target_id=item_id,
        action="view",
        details=f"{user.display_name} viewed {len(creds)} credential(s) for item {item_id}",
    )

    return JSONResponse(content={"credentials": [
        {
            "id": cred.id,
            "credential_type": cred.credential_type,
            "username": decrypt(cred.username),
            "password": decrypt(cred.password),
            "notes": decrypt(cred.notes),
        }
        for cred in creds
    ]})
