"""Credentials vault route — session auth protected + audit logged."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_credentials_access, User
from ..credentials import decrypt
from ..database import get_db
from ..models import DeviceCredential, TABLE_MODELS

router = APIRouter()


@router.get("/{table_name}/{device_id}")
def get_credentials(
    table_name: str,
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_credentials_access),
):
    """Get decrypted credentials for a specific device.

    Requires editor or admin role. Every access is audit-logged.
    """
    if table_name not in TABLE_MODELS:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown table: {table_name}"},
        )

    creds = (
        db.query(DeviceCredential)
        .filter(
            DeviceCredential.device_table == table_name,
            DeviceCredential.device_id == device_id,
        )
        .all()
    )

    # Audit log: credential view (even if no creds found)
    log_event(
        db, "credential_viewed",
        request=request,
        user_id=user.id,
        target_table=table_name,
        target_id=device_id,
        action="view",
        details=f"{user.display_name} viewed credentials for {table_name}/{device_id}",
    )

    if not creds:
        return JSONResponse(
            status_code=404,
            content={"error": "No credentials found for this device"},
        )

    results = []
    for cred in creds:
        results.append({
            "id": cred.id,
            "credential_type": cred.credential_type,
            "username": decrypt(cred.username),
            "password": decrypt(cred.password),
            "notes": decrypt(cred.notes),
        })

    return JSONResponse(content={"credentials": results})
