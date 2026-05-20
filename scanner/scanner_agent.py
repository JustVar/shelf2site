"""Standalone scanner agent for remote NUCs (NUC 2+).

Scans the local subnet and POSTs discoveries to the central NUC 1 API.
Designed to run as a systemd service.

Usage:
    python scanner_agent.py

Config via .env:
    SCANNER_MODE=remote
    SCAN_SUBNETS=192.168.x.0/24
    SCANNER_ID=office-nuc
    CENTRAL_API_URL=http://192.0.2.174:8081
    SCANNER_API_KEY=<shared-secret>
    SCAN_INTERVAL_SECONDS=120
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the same directory as this script, or parent
_script_dir = Path(__file__).resolve().parent
for env_path in [_script_dir / ".env", _script_dir.parent / ".env"]:
    if env_path.exists():
        load_dotenv(env_path)
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("scanner-agent")

# Config
CENTRAL_API_URL = os.getenv("CENTRAL_API_URL", "")
SCANNER_API_KEY = os.getenv("SCANNER_API_KEY", "")
SCANNER_ID = os.getenv("SCANNER_ID", "remote-nuc")
SCAN_SUBNETS = [s.strip() for s in os.getenv("SCAN_SUBNETS", "").split(",") if s.strip()]
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "120"))
PENDING_FILE = _script_dir / "pending_discoveries.json"


def _load_pending() -> list[dict]:
    """Load queued discoveries that failed to send."""
    if PENDING_FILE.exists():
        try:
            return json.loads(PENDING_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_pending(items: list[dict]):
    """Save failed discoveries for retry."""
    PENDING_FILE.write_text(json.dumps(items, indent=2))


def _clear_pending():
    """Remove the pending file after successful flush."""
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()


def send_discoveries(devices: list[dict], subnet: str) -> bool:
    """POST discovered devices to the central NUC API.

    Returns True on success, False on failure (will queue for retry).
    """
    import httpx

    url = f"{CENTRAL_API_URL.rstrip('/')}/api/discover"
    payload = {
        "scanner_id": SCANNER_ID,
        "subnet": subnet,
        "devices": devices,
    }
    headers = {
        "X-Scanner-Key": SCANNER_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                logger.info(
                    f"Sent {len(devices)} devices -> "
                    f"{data.get('new', 0)} new, {data.get('updated', 0)} updated"
                )
                return True
            else:
                logger.error(
                    f"Central API returned {resp.status_code}: {resp.text}"
                )
                return False
    except Exception as e:
        logger.error(f"Failed to reach central API at {url}: {e}")
        return False


def scan_and_report():
    """Run one scan cycle: scan subnets, send results, handle failures."""
    from network_scanner import scan_subnets

    # Scan all configured subnets
    devices = scan_subnets(SCAN_SUBNETS)

    if not devices:
        logger.info("No devices discovered this cycle")
        return

    # Convert to dicts for JSON serialization
    device_dicts = [
        {
            "mac": d.mac,
            "ip": d.ip,
            "hostname": d.hostname,
            "manufacturer": d.manufacturer,
            "os_hint": d.os_hint,
        }
        for d in devices
    ]

    # Try to send current discoveries
    subnet_str = ",".join(SCAN_SUBNETS)
    success = send_discoveries(device_dicts, subnet_str)

    if not success:
        # Queue for retry
        pending = _load_pending()
        pending.extend(device_dicts)
        _save_pending(pending)
        logger.warning(f"Queued {len(device_dicts)} devices for retry (total pending: {len(pending)})")
    else:
        # Try to flush any previously queued discoveries
        pending = _load_pending()
        if pending:
            logger.info(f"Flushing {len(pending)} queued discoveries...")
            if send_discoveries(pending, subnet_str):
                _clear_pending()
                logger.info("Pending queue flushed successfully")
            else:
                logger.warning("Failed to flush pending queue, will retry next cycle")


def main():
    if not CENTRAL_API_URL:
        logger.error("CENTRAL_API_URL is not set. Cannot run in remote mode.")
        sys.exit(1)
    if not SCAN_SUBNETS:
        logger.error("SCAN_SUBNETS is not set. Nothing to scan.")
        sys.exit(1)

    logger.info(f"Scanner agent starting")
    logger.info(f"  ID: {SCANNER_ID}")
    logger.info(f"  Subnets: {SCAN_SUBNETS}")
    logger.info(f"  Central API: {CENTRAL_API_URL}")
    logger.info(f"  Interval: {SCAN_INTERVAL}s")

    while True:
        try:
            scan_and_report()
        except KeyboardInterrupt:
            logger.info("Scanner agent stopped")
            break
        except Exception as e:
            logger.error(f"Scan cycle error: {e}")

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
