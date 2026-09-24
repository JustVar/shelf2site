"""Error tracking routes — self-hosted error monitoring.

Endpoints:
  POST /api/errors/report      — log a frontend or backend error (authenticated)
  GET  /api/errors              — list recent errors (admin only)
  POST /api/errors/{id}/resolve — mark an error as resolved (admin only)
  DELETE /api/errors/prune      — delete errors older than N days (admin only)
  GET  /admin/errors            — admin error log page
"""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth import get_current_user, require_system_admin, User
from ..config import settings
from ..localtime import register
from ..database import SessionLocal

from sqlalchemy import text

router = APIRouter()

_base_dir = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(_base_dir / "app" / "templates"))
templates.env.globals["base_path"] = settings.ROOT_PATH.rstrip("/")
register(templates.env)


def _fingerprint(message: str, url: str = "", source: str = "frontend") -> str:
    """Generate a short hash to group identical errors."""
    raw = f"{source}:{message}:{url}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def log_error(
    source: str,
    message: str,
    stack: str = None,
    url: str = None,
    user_id: int = None,
    username: str = None,
    browser: str = None,
    context: dict = None,
    level: str = "error",
):
    """Write an error to the error_log table. Safe to call from anywhere."""
    fp = _fingerprint(message, url or "", source)
    db = SessionLocal()
    try:
        db.execute(
            text("""
                INSERT INTO error_log (source, level, message, stack, url, user_id, username, browser, context, fingerprint)
                VALUES (:source, :level, :message, :stack, :url, :user_id, :username, :browser, :context, :fingerprint)
            """),
            {
                "source": source,
                "level": level,
                "message": message[:2000],
                "stack": (stack or "")[:4000] or None,
                "url": (url or "")[:512] or None,
                "user_id": user_id,
                "username": username,
                "browser": (browser or "")[:256] or None,
                "context": str(context) if context else None,
                "fingerprint": fp,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ── Frontend error report endpoint ──────────────────────────────────────────

@router.post("/api/errors/report")
async def report_error(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Accept error reports from the browser JS error handler."""
    body = await request.json()
    message = body.get("message", "Unknown error")
    stack = body.get("stack")
    url = body.get("url")
    browser = request.headers.get("user-agent", "")
    level = body.get("level", "error")
    context = body.get("context")

    log_error(
        source="frontend",
        message=message,
        stack=stack,
        url=url,
        user_id=user.id,
        username=user.username,
        browser=browser,
        context=context,
        level=level,
    )
    return JSONResponse(content={"ok": True})


# ── Error list API (admin only) ────────────────────────────────────────────

@router.get("/api/errors")
def list_errors(
    request: Request,
    user: User = Depends(require_system_admin),
    page: int = 1,
    source: str = None,
    level: str = None,
):
    """Return paginated error log entries, newest first."""
    per_page = 50
    offset = (page - 1) * per_page

    db = SessionLocal()
    try:
        where_clauses = []
        params = {"limit": per_page, "offset": offset}

        if source:
            where_clauses.append("source = :source")
            params["source"] = source
        if level:
            where_clauses.append("level = :level")
            params["level"] = level

        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql

        rows = db.execute(
            text(f"""
                SELECT id, created_at, source, level, message, stack, url,
                       user_id, username, browser, fingerprint
                FROM error_log
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        ).fetchall()

        total = db.execute(
            text(f"SELECT COUNT(*) FROM error_log {where_sql}"),
            params,
        ).scalar()

        errors = []
        for r in rows:
            errors.append({
                "id": r[0],
                "created_at": r[1].isoformat() if r[1] else None,
                "source": r[2],
                "level": r[3],
                "message": r[4],
                "stack": r[5],
                "url": r[6],
                "user_id": r[7],
                "username": r[8],
                "browser": r[9],
                "fingerprint": r[10],
            })

        return JSONResponse(content={
            "errors": errors,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        })
    finally:
        db.close()


# ── Prune old errors (admin only) ──────────────────────────────────────────

@router.delete("/api/errors/prune")
def prune_errors(
    request: Request,
    user: User = Depends(require_system_admin),
    days: int = 30,
):
    """Delete error log entries older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = SessionLocal()
    try:
        result = db.execute(
            text("DELETE FROM error_log WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        db.commit()
        return JSONResponse(content={"deleted": result.rowcount, "older_than_days": days})
    finally:
        db.close()


# ── Admin error log page ───────────────────────────────────────────────────

@router.get("/admin/errors", response_class=HTMLResponse)
def error_log_page(
    request: Request,
    user: User = Depends(require_system_admin),
):
    """Render the admin error log page."""
    db = SessionLocal()
    try:
        # Summary stats
        total = db.execute(text("SELECT COUNT(*) FROM error_log")).scalar()
        today_count = db.execute(
            text("SELECT COUNT(*) FROM error_log WHERE created_at > NOW() - INTERVAL '24 hours'")
        ).scalar()
        frontend_count = db.execute(
            text("SELECT COUNT(*) FROM error_log WHERE source = 'frontend' AND created_at > NOW() - INTERVAL '24 hours'")
        ).scalar()
        backend_count = db.execute(
            text("SELECT COUNT(*) FROM error_log WHERE source = 'backend' AND created_at > NOW() - INTERVAL '24 hours'")
        ).scalar()

        # Recent errors (latest 100)
        rows = db.execute(
            text("""
                SELECT id, created_at, source, level, message, url, username, fingerprint
                FROM error_log
                ORDER BY created_at DESC
                LIMIT 100
            """)
        ).fetchall()

        errors = []
        for r in rows:
            errors.append({
                "id": r[0],
                "created_at": r[1],
                "source": r[2],
                "level": r[3],
                "message": r[4][:120] if r[4] else "",
                "url": r[5],
                "username": r[6],
                "fingerprint": r[7],
            })

        # Top repeated errors (by fingerprint)
        top_errors = db.execute(
            text("""
                SELECT fingerprint, message, source, COUNT(*) as cnt,
                       MAX(created_at) as last_seen
                FROM error_log
                GROUP BY fingerprint, message, source
                ORDER BY cnt DESC
                LIMIT 10
            """)
        ).fetchall()

        grouped = []
        for r in top_errors:
            grouped.append({
                "fingerprint": r[0],
                "message": r[1][:100] if r[1] else "",
                "source": r[2],
                "count": r[3],
                "last_seen": r[4],
            })

        return templates.TemplateResponse("admin_errors.html", {
            "request": request,
            "user": user,
            "total": total,
            "today_count": today_count,
            "frontend_count": frontend_count,
            "backend_count": backend_count,
            "errors": errors,
            "grouped": grouped,
        })
    finally:
        db.close()


# ── Error detail API (for expanding stack traces) ──────────────────────────

@router.get("/api/errors/{error_id}")
def get_error_detail(
    error_id: int,
    user: User = Depends(require_system_admin),
):
    """Return full error details including stack trace."""
    db = SessionLocal()
    try:
        row = db.execute(
            text("""
                SELECT id, created_at, source, level, message, stack, url,
                       user_id, username, browser, context, fingerprint
                FROM error_log WHERE id = :id
            """),
            {"id": error_id},
        ).fetchone()

        if not row:
            return JSONResponse(status_code=404, content={"error": "Not found"})

        return JSONResponse(content={
            "id": row[0],
            "created_at": row[1].isoformat() if row[1] else None,
            "source": row[2],
            "level": row[3],
            "message": row[4],
            "stack": row[5],
            "url": row[6],
            "user_id": row[7],
            "username": row[8],
            "browser": row[9],
            "context": row[10],
            "fingerprint": row[11],
        })
    finally:
        db.close()
