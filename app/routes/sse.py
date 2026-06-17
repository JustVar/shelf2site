"""Server-Sent Events for real-time dashboard updates.

Multi-worker fan-out via Postgres LISTEN/NOTIFY:
  - Every worker opens a dedicated asyncpg connection and LISTENs on
    'asset_tracker_events'.
  - publish_event() sends a NOTIFY over a dedicated publisher connection.
  - Each worker's listener callback forwards the payload to its local
    _event_queues, so every connected SSE client receives every event.

This replaces the previous in-memory-only broadcast which was worker-local
and therefore broken under gunicorn with >1 worker.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from ..auth import get_session_user_id, User
from ..config import settings
from ..database import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()

# Postgres NOTIFY channel name
PG_CHANNEL = "asset_tracker_events"
# Postgres NOTIFY payload limit is 8000 bytes; leave headroom for channel name + overhead.
PAYLOAD_MAX_BYTES = 7500

# In-memory queue list — one queue per SSE client connected to THIS worker.
# Events arriving via the asyncpg LISTEN callback are fanned out into these queues.
_event_queues: list[asyncio.Queue] = []

# Dedicated asyncpg connections, one per worker.
_listen_conn: Optional[asyncpg.Connection] = None
_publish_conn: Optional[asyncpg.Connection] = None
# Serializes NOTIFY calls so a single asyncpg connection is used safely.
_publish_lock: Optional[asyncio.Lock] = None
# Main event loop captured at startup — lets sync callers schedule async NOTIFYs.
_main_loop: Optional[asyncio.AbstractEventLoop] = None
# Listener reconnect supervisor task + shutdown signal.
_listen_supervisor_task: Optional[asyncio.Task] = None
_shutdown_event: Optional[asyncio.Event] = None


def _asyncpg_dsn() -> str:
    """Convert settings.DATABASE_URL to an asyncpg-compatible DSN.

    asyncpg does not accept the SQLAlchemy '+driver' suffix (e.g.
    'postgresql+psycopg2://...'). Our URL uses plain 'postgresql://' so
    this is usually a no-op, but we normalize defensively.
    """
    url = settings.DATABASE_URL
    if url.startswith("postgresql+"):
        scheme, _, rest = url.partition("://")
        url = f"postgresql://{rest}"
    return url


async def _open_listener() -> None:
    """Open the listener connection and register the NOTIFY callback.

    Used by both startup and the reconnect supervisor. Sets the module-level
    _listen_conn global.
    """
    global _listen_conn
    _listen_conn = await asyncpg.connect(_asyncpg_dsn())
    await _listen_conn.add_listener(PG_CHANNEL, _on_notify)


async def _listener_supervisor() -> None:
    """Keep the listener connection alive across Postgres restarts.

    Polls the connection state every few seconds; if it has dropped (e.g.
    Postgres restarted or a network blip), reconnects with exponential
    backoff and re-registers the LISTEN callback.

    NOTE: this restores the event channel, but events that were NOTIFYed
    while the connection was down are NOT replayed — Postgres NOTIFY is
    fire-and-forget, so any events during the outage window are lost. SSE
    clients resume receiving NEW events after reconnect.
    """
    backoff = 1.0
    backoff_max = 30.0
    while _shutdown_event is not None and not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=2.0)
            break  # shutdown signalled
        except asyncio.TimeoutError:
            pass  # normal: 2s poll interval elapsed

        if _listen_conn is not None and not _listen_conn.is_closed():
            backoff = 1.0  # healthy, reset backoff
            continue

        # Connection is gone — attempt reconnect with backoff.
        logger.warning("SSE listener connection lost; reconnecting in %.1fs", backoff)
        try:
            if _shutdown_event.is_set():
                break
            await asyncio.wait_for(_shutdown_event.wait(), timeout=backoff)
            break  # shutdown signalled during backoff
        except asyncio.TimeoutError:
            pass
        try:
            await _open_listener()
            logger.info("SSE listener reconnected")
            backoff = 1.0
        except Exception as exc:
            logger.error("SSE listener reconnect failed: %s", exc)
            backoff = min(backoff * 2, backoff_max)


def _on_notify(connection, pid, channel, payload: str) -> None:
    """asyncpg LISTEN callback. Runs on the listener connection's event loop.

    Decodes the JSON payload and pushes the original JSON string to every
    local client queue. The payload string is opaque to the server after
    this point — _event_generator yields it verbatim to the browser.
    """
    try:
        data = json.loads(payload)
        event_type = data.get("type", "<unknown>")
    except Exception:
        event_type = "<unparsed>"

    # TODO: downgrade this log to DEBUG once SSE pubsub is proven stable in
    # production. Currently INFO for visibility during rollout.
    logger.debug("SSE LISTEN received event type=%s queues=%d", event_type, len(_event_queues))

    for q in _event_queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("SSE client queue full, dropping event for one client")


async def _async_notify(payload: str) -> None:
    """Run NOTIFY on the dedicated publisher connection.

    Uses pg_notify() function rather than the NOTIFY utility statement because
    NOTIFY channel, $1 does not reliably accept bound parameters — the payload
    can be sent as the literal string '$1'. pg_notify(channel, payload) is a
    regular function call that binds parameters correctly.
    """
    global _publish_conn
    if _publish_conn is None or _publish_lock is None:
        logger.warning("SSE publish skipped: publisher connection not initialized")
        return
    async with _publish_lock:
        try:
            await _publish_conn.execute("SELECT pg_notify($1, $2)", PG_CHANNEL, payload)
        except Exception as exc:
            logger.warning("SSE NOTIFY failed, reconnecting publisher: %s", exc)
            try:
                await _publish_conn.close()
            except Exception:
                pass
            try:
                _publish_conn = await asyncpg.connect(_asyncpg_dsn())
                await _publish_conn.execute("SELECT pg_notify($1, $2)", PG_CHANNEL, payload)
            except Exception as retry_exc:
                logger.error("SSE NOTIFY retry also failed: %s", retry_exc)


def publish_event(event_type: str, data: dict) -> None:
    """Broadcast an event to every connected SSE client across all workers.

    Fire-and-forget: schedules an async NOTIFY on the main event loop and
    returns immediately. Safe to call from sync or async contexts.

    Keeps the original (event_type, data) positional signature — no caller changes.
    """
    payload = json.dumps({"type": event_type, **data})

    payload_bytes = len(payload.encode("utf-8"))
    if payload_bytes > PAYLOAD_MAX_BYTES:
        logger.warning(
            "SSE publish DROPPED: payload %d bytes exceeds %d-byte limit "
            "(event type=%s). Consider splitting large events or storing data "
            "out-of-band and sending a reference.",
            payload_bytes, PAYLOAD_MAX_BYTES, event_type,
        )
        return

    # TODO: downgrade this log to DEBUG once SSE pubsub is proven stable in
    # production. Currently INFO for visibility during rollout.
    logger.debug("SSE NOTIFY sending type=%s size=%d", event_type, payload_bytes)

    if _main_loop is None:
        logger.warning("SSE publish skipped: main event loop not captured yet (startup not complete)")
        return

    try:
        asyncio.run_coroutine_threadsafe(_async_notify(payload), _main_loop)
    except Exception as exc:
        logger.error("SSE publish schedule failed: %s", exc)


def get_sse_client_count() -> int:
    """Return the number of currently connected SSE clients on THIS worker."""
    return len(_event_queues)


async def start_sse_pubsub() -> None:
    """Open the LISTEN and NOTIFY connections. Call from FastAPI lifespan startup."""
    global _listen_conn, _publish_conn, _publish_lock, _main_loop
    global _listen_supervisor_task, _shutdown_event

    _main_loop = asyncio.get_running_loop()
    _publish_lock = asyncio.Lock()
    _shutdown_event = asyncio.Event()
    dsn = _asyncpg_dsn()

    _safe_dsn = dsn
    if "@" in _safe_dsn and "://" in _safe_dsn:
        scheme, _, rest = _safe_dsn.partition("://")
        creds, _, host_part = rest.rpartition("@")
        if ":" in creds:
            user_part = creds.split(":", 1)[0]
            _safe_dsn = f"{scheme}://{user_part}:***@{host_part}"

    logger.info("SSE pubsub starting: channel=%s dsn=%s", PG_CHANNEL, _safe_dsn)

    await _open_listener()
    _publish_conn = await asyncpg.connect(dsn)

    _listen_supervisor_task = asyncio.create_task(_listener_supervisor())

    logger.info("SSE pubsub ready (listener + publisher connections open)")


async def stop_sse_pubsub() -> None:
    """Close LISTEN and NOTIFY connections. Call from FastAPI lifespan shutdown."""
    global _listen_conn, _publish_conn, _listen_supervisor_task
    logger.info("SSE pubsub shutting down")

    if _shutdown_event is not None:
        _shutdown_event.set()
    if _listen_supervisor_task is not None:
        _listen_supervisor_task.cancel()
        try:
            await _listen_supervisor_task
        except (asyncio.CancelledError, Exception):
            pass
        _listen_supervisor_task = None

    if _listen_conn is not None:
        try:
            await _listen_conn.remove_listener(PG_CHANNEL, _on_notify)
        except Exception as exc:
            logger.warning("SSE remove_listener failed: %s", exc)
        try:
            await _listen_conn.close()
        except Exception as exc:
            logger.warning("SSE listener close failed: %s", exc)
        _listen_conn = None

    if _publish_conn is not None:
        try:
            await _publish_conn.close()
        except Exception as exc:
            logger.warning("SSE publisher close failed: %s", exc)
        _publish_conn = None

    logger.info("SSE pubsub shut down")


async def _event_generator(request: Request) -> AsyncGenerator[dict, None]:
    """Yields SSE events for a single client connection."""
    queue: asyncio.Queue = asyncio.Queue()
    _event_queues.append(queue)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield {"event": "update", "data": data}
            except asyncio.TimeoutError:
                yield {"comment": "keepalive"}
    finally:
        _event_queues.remove(queue)


@router.get("/stream")
async def event_stream(request: Request):
    """SSE endpoint for real-time dashboard updates.

    Authenticates the user, releases the DB connection immediately, then
    streams events from the in-memory queue.
    """
    user_id = get_session_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=401)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        if user is None:
            raise HTTPException(status_code=401)
    finally:
        db.close()

    return EventSourceResponse(_event_generator(request))
