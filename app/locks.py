"""DB-backed edit lock manager for concurrency awareness.

Locks are stored in PostgreSQL (edit_locks table) so they work correctly
across multiple gunicorn workers. Two lock levels:
  - 'viewing': user has opened the edit modal (soft lock, informational)
  - 'editing': user has started modifying fields (hard lock, blocks others)

Lock key format: "{resource_type}:{resource_id}" e.g. "warranty:42", "cameras:15"
"""

import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import text

from .database import SessionLocal

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_SECONDS = 300  # 5 minutes idle timeout

# Background cleanup task reference
_cleanup_task: Optional[asyncio.Task] = None


def _get_db():
    """Get a short-lived DB session for lock operations."""
    return SessionLocal()


def acquire_lock(
    resource_key: str, user_id: int, username: str, display_name: str,
) -> dict:
    """Acquire a 'viewing' lock. Returns lock status info.

    If another user holds a lock:
      - viewing: returns conflict info (caller can still proceed)
      - editing: returns conflict info (caller should be blocked)
    If the same user already has the lock, refreshes it.
    """
    now = time.time()
    db = _get_db()
    try:
        row = db.execute(
            text("SELECT user_id, level, display_name, acquired_at FROM edit_locks WHERE resource_key = :key"),
            {"key": resource_key},
        ).fetchone()

        if row and row[0] != user_id:
            return {
                "granted": row[1] == "viewing",
                "conflict": True,
                "lock_level": row[1],
                "locked_by": row[2],
                "locked_by_id": row[0],
                "locked_since": row[3],
            }

        # Upsert: insert or update if same user
        db.execute(
            text("""
                INSERT INTO edit_locks (resource_key, user_id, username, display_name, level, acquired_at, last_activity)
                VALUES (:key, :uid, :uname, :dname, 'viewing', :now, :now)
                ON CONFLICT (resource_key) DO UPDATE SET
                    user_id = :uid, username = :uname, display_name = :dname,
                    level = 'viewing', acquired_at = :now, last_activity = :now
            """),
            {"key": resource_key, "uid": user_id, "uname": username, "dname": display_name, "now": now},
        )
        db.commit()
        return {"granted": True, "conflict": False, "lock_level": "viewing"}
    finally:
        db.close()


def escalate_lock(resource_key: str, user_id: int) -> dict:
    """Escalate from 'viewing' to 'editing'.

    Only succeeds if the caller already holds the lock.
    """
    db = _get_db()
    try:
        row = db.execute(
            text("SELECT user_id, level, display_name FROM edit_locks WHERE resource_key = :key"),
            {"key": resource_key},
        ).fetchone()

        if not row:
            return {"escalated": False, "error": "No lock held"}
        if row[0] != user_id:
            return {
                "escalated": False,
                "conflict": True,
                "lock_level": row[1],
                "locked_by": row[2],
            }

        now = time.time()
        db.execute(
            text("UPDATE edit_locks SET level = 'editing', last_activity = :now WHERE resource_key = :key"),
            {"key": resource_key, "now": now},
        )
        db.commit()
        return {"escalated": True, "lock_level": "editing"}
    finally:
        db.close()


def release_lock(resource_key: str, user_id: int) -> bool:
    """Release a lock. Only the holder can release. Returns True if released."""
    db = _get_db()
    try:
        result = db.execute(
            text("DELETE FROM edit_locks WHERE resource_key = :key AND user_id = :uid"),
            {"key": resource_key, "uid": user_id},
        )
        db.commit()
        return result.rowcount > 0
    finally:
        db.close()


def heartbeat(resource_key: str, user_id: int) -> bool:
    """Update last_activity to prevent timeout. Returns True if lock exists."""
    now = time.time()
    db = _get_db()
    try:
        result = db.execute(
            text("UPDATE edit_locks SET last_activity = :now WHERE resource_key = :key AND user_id = :uid"),
            {"key": resource_key, "uid": user_id, "now": now},
        )
        db.commit()
        return result.rowcount > 0
    finally:
        db.close()


def get_lock(resource_key: str) -> Optional[dict]:
    """Get current lock info for a resource, or None."""
    db = _get_db()
    try:
        row = db.execute(
            text("SELECT resource_key, user_id, display_name, level, acquired_at FROM edit_locks WHERE resource_key = :key"),
            {"key": resource_key},
        ).fetchone()
        if not row:
            return None
        return {
            "resource_key": row[0],
            "user_id": row[1],
            "display_name": row[2],
            "level": row[3],
            "acquired_at": row[4],
        }
    finally:
        db.close()


def get_all_locks() -> list[dict]:
    """Return all active locks."""
    db = _get_db()
    try:
        rows = db.execute(
            text("SELECT resource_key, user_id, display_name, level, acquired_at FROM edit_locks")
        ).fetchall()
        return [
            {
                "resource_key": r[0],
                "user_id": r[1],
                "display_name": r[2],
                "level": r[3],
                "acquired_at": r[4],
            }
            for r in rows
        ]
    finally:
        db.close()


def cleanup_stale_locks() -> list[str]:
    """Remove locks idle longer than LOCK_TIMEOUT_SECONDS.
    Returns list of released resource keys for SSE notification."""
    now = time.time()
    cutoff = now - LOCK_TIMEOUT_SECONDS
    db = _get_db()
    try:
        rows = db.execute(
            text("SELECT resource_key FROM edit_locks WHERE last_activity < :cutoff"),
            {"cutoff": cutoff},
        ).fetchall()
        stale_keys = [r[0] for r in rows]
        if stale_keys:
            db.execute(
                text("DELETE FROM edit_locks WHERE last_activity < :cutoff"),
                {"cutoff": cutoff},
            )
            db.commit()
        return stale_keys
    finally:
        db.close()


async def _cleanup_loop():
    """Background task that runs cleanup every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        stale = cleanup_stale_locks()
        if stale:
            from .routes.sse import publish_event
            for key in stale:
                publish_event("lock_released", {
                    "resource_key": key,
                    "reason": "timeout",
                })


def start_lock_cleanup():
    """Start the background cleanup task. Called from lifespan."""
    global _cleanup_task
    _cleanup_task = asyncio.create_task(_cleanup_loop())
    return _cleanup_task
