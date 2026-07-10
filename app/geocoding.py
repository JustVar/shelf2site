"""Address geocoding (Nominatim / OpenStreetMap by default).

Forward-geocodes a free-text address to lat/lng for the deployment map.
Config-driven so the provider is swappable and cleanly disabled when
unconfigured. Honors a >=1 req/sec rate limit (Nominatim usage policy)
through a process-wide async lock, and callers cache the resolved query on
the row so a re-geocode fires only when the address text changes. Every
failure is graceful: geocode() returns None, the caller saves without
coordinates and the UI offers a retry / pick-on-map fallback.

Egress note: apphost's app container must reach GEOCODER_BASE_URL. If
egress is blocked, geocode() returns None and the flow degrades to the
map Fix (set-location) path.
"""

import asyncio
import time

import httpx

from .config import settings

_lock = asyncio.Lock()
_last_call = 0.0


def compose_address(*parts) -> str:
    """Join address components into a single geocoder query string."""
    return ", ".join(p.strip() for p in parts if p and str(p).strip())


async def geocode(query: str):
    """Resolve an address string to {lat, lng, display_name} or None.

    Never raises: any transport error, non-200, empty result, or malformed
    payload yields None so the caller can save-without-coordinates.
    """
    query = (query or "").strip()
    if not query or not settings.GEOCODER_ENABLED or not settings.GEOCODER_BASE_URL:
        return None
    global _last_call
    async with _lock:
        wait = settings.GEOCODER_RATE_LIMIT_S - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=settings.GEOCODER_TIMEOUT_S) as client:
                resp = await client.get(
                    settings.GEOCODER_BASE_URL,
                    params={"q": query, "format": "json", "limit": 1},
                    headers={"User-Agent": settings.GEOCODER_USER_AGENT},
                )
            _last_call = time.monotonic()
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data:
                return None
            top = data[0]
            lat, lng = float(top["lat"]), float(top["lon"])
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                return None
            return {"lat": lat, "lng": lng, "display_name": top.get("display_name", "")}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            _last_call = time.monotonic()
            return None
