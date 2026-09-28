"""Cached sidebar counts — avoids recomputing on every page load.

Provides triage_count and pending_count with a short TTL cache.
Used by the Jinja2 context processor registered in main.py.
"""

import time
from sqlalchemy.orm import Session
from .models import DeleteRequest, PendingDevice, get_approvable_categories

_cache: dict = {}
_TTL = 15  # seconds

_stats_cache: dict = {}
_STATS_TTL = 30  # seconds for category stats


def get_category_stats_cached(compute_fn, db):
    """Return cached category stats. Refreshes after TTL expires."""
    now = time.time()
    if "stats" not in _stats_cache or now - _stats_cache["stats"][1] > _STATS_TTL:
        _stats_cache["stats"] = (compute_fn(db), now)
    return _stats_cache["stats"][0]


def invalidate_category_stats():
    """Bust the category stats cache immediately — call after any device write."""
    _stats_cache.clear()


_triage_cache: dict = {}
_TRIAGE_TTL = 13  # seconds for triage page


def get_triage_cached(compute_fn, db):
    """Return cached triage results. Refreshes after TTL expires."""
    now = time.time()
    if "triage_data" not in _triage_cache or now - _triage_cache["triage_data"][1] > _TRIAGE_TTL:
        _triage_cache["triage_data"] = (compute_fn(db), now)
    return _triage_cache["triage_data"][0]


def invalidate_triage_cache():
    """Bust the triage cache immediately — call after any device write."""
    _triage_cache.clear()


def invalidate_sidebar_counts():
    """Bust the sidebar triage count and all per-user pending counts.
    Call after any write that could change those numbers."""
    _cache.pop("triage", None)
    for k in list(_cache.keys()):
        if k.startswith("pending_"):
            _cache.pop(k, None)


def _compute_triage_count(db: Session) -> int:
    """Count unique items with >=1 gap across any triage role.
    Delegates to the triage module, which owns the role definitions and
    SQL union filter. Lazy import avoids a circular dependency."""
    from .routes.triage import get_triage_total_count
    return get_triage_total_count(db)


def get_sidebar_counts(db: Session, user=None) -> dict:
    """Return cached sidebar counts. Refreshes after TTL expires."""
    now = time.time()

    # Triage count
    if "triage" not in _cache or now - _cache["triage"][1] > _TTL:
        _cache["triage"] = (_compute_triage_count(db), now)
    triage_count = _cache["triage"][0]

    # Pending count (user-specific based on approvable tables)
    pending_count = 0
    if user:
        cache_key = f"pending_{user.id}"
        if cache_key not in _cache or now - _cache[cache_key][1] > _TTL:
            from sqlalchemy import or_
            approvable = get_approvable_categories(user)
            count = (
                db.query(PendingDevice)
                .filter(
                    PendingDevice.status == "pending",
                    or_(
                        PendingDevice.suggested_category.in_(approvable),
                        PendingDevice.suggested_category.is_(None),
                    ),
                )
                .count()
            )
            _cache[cache_key] = (count, now)
        pending_count = _cache[cache_key][0]

    # Pending delete requests (item 41 slice C): admin tier only. Not cached:
    # the cache lives in each of the six workers and only the worker that
    # handled a request write would drop its copy, so an admin could see a
    # stale count after approving the last request. One count on a small table.
    delete_request_count = 0
    if user is not None and user.is_admin_tier:
        delete_request_count = (
            db.query(DeleteRequest).filter(DeleteRequest.status == "pending").count()
        )

    return {
        "triage_count": triage_count,
        "pending_count": pending_count,
        "delete_request_count": delete_request_count,
    }
