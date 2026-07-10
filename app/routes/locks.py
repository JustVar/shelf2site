"""Lock management API endpoints for concurrent edit awareness.

Endpoints:
  POST /api/locks/acquire    — acquire a viewing lock
  POST /api/locks/escalate   — escalate to editing lock
  POST /api/locks/release    — release a lock
  POST /api/locks/heartbeat  — keep lock alive
  GET  /api/locks/{key}      — check lock status
  GET  /api/locks            — list all active locks (admin only)
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..auth import get_current_user, require_admin, require_editor, User
from ..locks import (
    acquire_lock, escalate_lock, release_lock, heartbeat, get_lock, get_all_locks,
)
from .sse import publish_event

logger = logging.getLogger(__name__)

router = APIRouter()


async def _parse_body(request: Request) -> dict:
    """Parse JSON body, handling both application/json and text/plain (sendBeacon)."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return await request.json()
    raw = await request.body()
    return json.loads(raw) if raw else {}


# Lock mutations are editor-tier (2026-07 auth census): locks exist only to
# guard edit flows, and every UI path that acquires one is already behind an
# editor-gated control. Viewers keep read access to lock status below.
@router.post("/locks/acquire")
async def api_acquire_lock(
    request: Request,
    user: User = Depends(require_editor),
):
    body = await request.json()
    resource_key = body.get("resource_key")
    if not resource_key:
        return JSONResponse(status_code=400, content={"error": "resource_key required"})

    result = acquire_lock(
        resource_key, user.id, user.username, user.display_name,
    )

    if result.get("granted") and not result.get("conflict"):
        publish_event("lock_acquired", {
            "resource_key": resource_key,
            "user_id": user.id,
            "display_name": user.display_name,
            "level": "viewing",
        })
        logger.info("Lock acquired: key=%s user=%s(id=%s)", resource_key, user.display_name, user.id)

    return JSONResponse(content=result)


@router.post("/locks/escalate")
async def api_escalate_lock(
    request: Request,
    user: User = Depends(require_editor),
):
    body = await request.json()
    resource_key = body.get("resource_key")
    if not resource_key:
        return JSONResponse(status_code=400, content={"error": "resource_key required"})

    result = escalate_lock(resource_key, user.id)

    if result.get("escalated"):
        publish_event("lock_escalated", {
            "resource_key": resource_key,
            "user_id": user.id,
            "display_name": user.display_name,
            "level": "editing",
        })

    return JSONResponse(content=result)


@router.post("/locks/release")
async def api_release_lock(
    request: Request,
    user: User = Depends(require_editor),
):
    body = await _parse_body(request)
    resource_key = body.get("resource_key")
    if not resource_key:
        return JSONResponse(status_code=400, content={"error": "resource_key required"})

    released = release_lock(resource_key, user.id)

    if released:
        publish_event("lock_released", {
            "resource_key": resource_key,
            "user_id": user.id,
            "reason": "manual",
        })
        logger.info("Lock released: key=%s user=%s(id=%s)", resource_key, user.display_name, user.id)

    return JSONResponse(content={"released": released})


@router.post("/locks/heartbeat")
async def api_heartbeat(
    request: Request,
    user: User = Depends(require_editor),
):
    body = await request.json()
    resource_key = body.get("resource_key")
    if not resource_key:
        return JSONResponse(status_code=400, content={"error": "resource_key required"})

    alive = heartbeat(resource_key, user.id)
    return JSONResponse(content={"alive": alive})


@router.get("/locks/{resource_key:path}")
async def api_get_lock(
    resource_key: str,
    user: User = Depends(get_current_user),
):
    lock = get_lock(resource_key)
    return JSONResponse(content={"lock": lock})


@router.get("/locks")
async def api_list_locks(
    user: User = Depends(require_admin),
):
    return JSONResponse(content={"locks": get_all_locks()})
