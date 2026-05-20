"""On-demand network scan trigger route."""

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import require_system_admin, User
from ..config import settings
from ..database import get_db

router = APIRouter()


@router.post("/scan/trigger")
async def trigger_scan(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """On-demand full scan: returns ALL discovered devices (ignores OUI filter).

    Admin only. Results are temporary and not auto-inserted into any table.
    """
    from scanner.network_scanner import scan_subnets
    from scanner.oui_lookup import lookup_manufacturer

    subnets = settings.SCAN_SUBNETS

    log_event(
        db, "scan_triggered",
        request=request,
        user_id=user.id,
        action="create",
        details=f"On-demand scan triggered for subnets: {', '.join(subnets)}",
    )

    # Run scan in thread pool to avoid blocking
    devices = await asyncio.to_thread(scan_subnets, subnets)

    results = []
    for d in devices:
        manufacturer = d.manufacturer or lookup_manufacturer(d.mac)
        results.append({
            "mac": d.mac,
            "ip": d.ip,
            "hostname": d.hostname,
            "manufacturer": manufacturer,
        })

    log_event(
        db, "scan_completed",
        request=request,
        user_id=user.id,
        action="create",
        details=f"On-demand scan found {len(results)} devices on {', '.join(subnets)}",
        new_values={"device_count": len(results)},
    )

    return JSONResponse(content={
        "status": "ok",
        "subnets": subnets,
        "devices": results,
        "count": len(results),
    })
