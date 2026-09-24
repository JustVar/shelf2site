"""Intune Device Sync — admin page and Graph API sync endpoints."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import require_system_admin
from ..audit import log_event
from ..config import settings
from ..localtime import register
from ..database import get_db
from ..models import Computer, IntuneSyncLog, User

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


def _intune_configured() -> bool:
    return bool(settings.INTUNE_TENANT_ID and settings.INTUNE_CLIENT_ID and settings.INTUNE_CLIENT_SECRET)


async def _get_intune_token() -> str | None:
    """Obtain a Microsoft Graph API access token via client credentials."""
    import httpx
    url = f"https://login.microsoftonline.com/{settings.INTUNE_TENANT_ID}/oauth2/v2.0/token"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, data={
                "grant_type": "client_credentials",
                "client_id": settings.INTUNE_CLIENT_ID,
                "client_secret": settings.INTUNE_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            })
            data = resp.json()
            return data.get("access_token")
    except Exception:
        return None


@router.get("/admin/intune", response_class=HTMLResponse)
def intune_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Intune sync configuration and status page."""
    configured = _intune_configured()
    recent_logs = (
        db.query(IntuneSyncLog)
        .order_by(IntuneSyncLog.synced_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse("admin_intune.html", {
        "request": request,
        "user": user,
        "configured": configured,
        "auto_sync": settings.INTUNE_AUTO_SYNC,
        "recent_logs": recent_logs,
        "tenant_id_set": bool(settings.INTUNE_TENANT_ID),
        "client_id_set": bool(settings.INTUNE_CLIENT_ID),
        "client_secret_set": bool(settings.INTUNE_CLIENT_SECRET),
    })


@router.post("/api/intune/test")
async def test_intune_connection(
    request: Request,
    user: User = Depends(require_system_admin),
):
    """Test Microsoft Graph API connectivity with configured credentials."""
    if not _intune_configured():
        return JSONResponse(status_code=400, content={"error": "Intune credentials not configured. Set INTUNE_TENANT_ID, INTUNE_CLIENT_ID, and INTUNE_CLIENT_SECRET in .env"})

    token = await _get_intune_token()
    if not token:
        return JSONResponse(status_code=400, content={"error": "Failed to obtain access token. Check tenant ID, client ID, and client secret."})

    # Test by fetching device count (top=1 is enough to confirm access)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices?$top=1&$select=id",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                count_hint = data.get("@odata.count", "?")
                return JSONResponse(content={"status": "ok", "message": f"Connection successful. Graph API accessible.", "device_hint": count_hint})
            return JSONResponse(status_code=400, content={"error": f"Graph API returned {resp.status_code}. Check app permissions (DeviceManagementManagedDevices.Read.All)."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/api/intune/sync")
async def trigger_intune_sync(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Trigger a manual Intune device sync."""
    if not _intune_configured():
        return JSONResponse(status_code=400, content={"error": "Intune credentials not configured"})

    log = IntuneSyncLog(
        synced_by=user.id,
        status="running",
        devices_found=0, devices_added=0, devices_updated=0, devices_skipped=0,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    token = await _get_intune_token()
    if not token:
        log.status = "error"
        log.error_message = "Failed to obtain access token"
        db.commit()
        return JSONResponse(status_code=400, content={"error": log.error_message})

    # Fetch all managed devices (paginate through @odata.nextLink)
    import httpx
    devices = []
    url = "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices?$select=id,deviceName,serialNumber,manufacturer,model,operatingSystem,osVersion,complianceState,lastSyncDateTime"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            while url:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                if resp.status_code != 200:
                    raise RuntimeError(f"Graph API {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                devices.extend(data.get("value", []))
                url = data.get("@odata.nextLink")
    except Exception as e:
        log.status = "error"
        log.error_message = str(e)[:500]
        db.commit()
        return JSONResponse(status_code=500, content={"error": log.error_message})

    log.devices_found = len(devices)

    for dev in devices:
        os_type = (dev.get("operatingSystem") or "").lower()
        serial = (dev.get("serialNumber") or "").strip()
        intune_id = dev.get("id", "")
        device_name = dev.get("deviceName") or dev.get("model") or "Unknown"
        manufacturer = dev.get("manufacturer") or ""
        model = dev.get("model") or ""
        os_version = dev.get("osVersion") or ""
        compliance = dev.get("complianceState") or "unknown"
        last_sync_raw = dev.get("lastSyncDateTime")
        last_sync = None
        if last_sync_raw:
            try:
                last_sync = datetime.fromisoformat(last_sync_raw.replace("Z", "+00:00"))
            except Exception:
                pass

        # Only sync Windows devices into computers table for now
        if "windows" not in os_type and "mac" not in os_type:
            log.devices_skipped += 1
            continue

        # Try to match by Intune device ID first, then serial number
        computer = None
        if intune_id:
            computer = db.query(Computer).filter(Computer.intune_device_id == intune_id).first()
        if not computer and serial:
            computer = db.query(Computer).filter(Computer.serial == serial).first()

        if computer:
            computer.intune_device_id = intune_id
            computer.intune_compliance = compliance
            computer.intune_last_checkin = last_sync
            if not computer.vendor and manufacturer:
                computer.vendor = manufacturer
            if not computer.model and model:
                computer.model = model
            if not computer.os_version and os_version:
                computer.os_version = os_version
            log.devices_updated += 1
        else:
            # Create a stub record — status "Synced from Intune", not active
            new_computer = Computer(
                device_name=device_name,
                serial=serial or None,
                vendor=manufacturer or None,
                model=model or None,
                os_version=os_version or None,
                intune_device_id=intune_id,
                intune_compliance=compliance,
                intune_last_checkin=last_sync,
                discovered_by="intune_import",
            )
            db.add(new_computer)
            log.devices_added += 1

    log.status = "success"
    db.commit()

    log_event(db, "intune_sync", request=request, user_id=user.id,
              target_table="computers", action="update",
              details=f"Intune sync: {log.devices_found} found, {log.devices_added} added, {log.devices_updated} updated, {log.devices_skipped} skipped")

    return JSONResponse(content={
        "status": "success",
        "devices_found": log.devices_found,
        "devices_added": log.devices_added,
        "devices_updated": log.devices_updated,
        "devices_skipped": log.devices_skipped,
    })


@router.get("/api/intune/sync-log")
def get_sync_log(
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Return the last 20 Intune sync runs."""
    logs = (
        db.query(IntuneSyncLog)
        .order_by(IntuneSyncLog.synced_at.desc())
        .limit(20)
        .all()
    )
    return JSONResponse(content={
        "logs": [
            {
                "id": l.id,
                "synced_at": l.synced_at.isoformat() if l.synced_at else None,
                "synced_by": l.synced_by,
                "devices_found": l.devices_found,
                "devices_added": l.devices_added,
                "devices_updated": l.devices_updated,
                "devices_skipped": l.devices_skipped,
                "status": l.status,
                "error_message": l.error_message,
            }
            for l in logs
        ]
    })
