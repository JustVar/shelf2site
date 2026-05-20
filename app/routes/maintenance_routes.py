"""Service maintenance announcement routes.

Admins can broadcast a pre-restart banner to all active users via SSE.
No database required — state is in-memory and intentionally resets on restart.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import require_system_admin
from ..audit import log_event
from ..config import settings
from ..database import get_db
from ..maintenance import get_announcement, set_announcement, clear_announcement
from ..models import User
from ..routes.sse import publish_event, get_sse_client_count

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


@router.get("/admin/maintenance", response_class=HTMLResponse)
def maintenance_page(
    request: Request,
    user: User = Depends(require_system_admin),
):
    """Service maintenance announcement admin page."""
    return templates.TemplateResponse("admin_maintenance.html", {
        "request": request,
        "user": user,
        "announcement": get_announcement().to_dict(),
    })


@router.get("/api/maintenance/status")
def maintenance_status():
    """Return current maintenance announcement state — no auth required (needed for banner polling)."""
    data = get_announcement().to_dict()
    data["sse_clients"] = get_sse_client_count()
    return JSONResponse(content=data)


@router.get("/api/maintenance/active-users")
def active_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Return users who have made an authenticated request in the last 10 minutes.

    Used by the maintenance page to decide whether it is safe to restart without
    warning anyone — if only service/bot accounts are active, or no one is, the
    admin can skip the announcement.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    users = (
        db.query(User)
        .filter(
            User.is_active.is_(True),
            User.last_seen_at.isnot(None),
            User.last_seen_at >= cutoff,
        )
        .order_by(User.last_seen_at.desc())
        .all()
    )
    now = datetime.utcnow()
    return JSONResponse(content={
        "count": len(users),
        "sse_clients": get_sse_client_count(),
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "role": u.role,
                "minutes_ago": max(0, int((now - u.last_seen_at).total_seconds() // 60)),
            }
            for u in users
        ],
    })


@router.post("/api/maintenance/announce")
async def announce_maintenance(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Set a maintenance announcement and broadcast to all connected clients.

    Body:
        message (str): Announcement text shown in the banner
        minutes (int|null): Minutes until restart (optional). If provided, restart_at is computed.
    """
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse(status_code=400, content={"error": "Message is required"})

    minutes = body.get("minutes")
    restart_at = None
    if minutes is not None:
        try:
            restart_at = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"error": "minutes must be a number"})

    state = set_announcement(message, restart_at)

    # Broadcast to all connected SSE clients
    publish_event("maintenance", state)

    log_event(db, "maintenance_announced", request=request, user_id=user.id,
              action="create", details=f"Maintenance announced: {message[:100]}"
              + (f" (restart in {minutes} min)" if minutes else ""))

    return JSONResponse(content={"status": "announced", **state})


@router.post("/api/maintenance/clear")
def clear_maintenance(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Clear the active maintenance announcement."""
    state = clear_announcement()

    # Broadcast cleared state
    publish_event("maintenance", state)

    log_event(db, "maintenance_cleared", request=request, user_id=user.id,
              action="update", details="Maintenance announcement cleared")

    return JSONResponse(content={"status": "cleared", **state})


@router.post("/api/maintenance/force-reload")
def force_reload(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Broadcast a force-reload event to all connected clients.

    Use after deploying an update when you want all browsers to refresh
    immediately without waiting for users to notice.
    """
    publish_event("force_reload", {"reason": "Admin triggered page reload"})

    log_event(db, "maintenance_force_reload", request=request, user_id=user.id,
              action="update", details="Force-reload broadcast to all connected clients")

    return JSONResponse(content={"status": "broadcast"})
