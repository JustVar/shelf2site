"""Network scanner using nmap for device discovery.

Shared by both local (NUC 1) and remote (NUC 2+) scanner modes.
"""

import logging
from dataclasses import dataclass

from .hostname_resolver import resolve_hostname

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredDevice:
    mac: str
    ip: str
    hostname: str | None = None
    manufacturer: str | None = None
    os_hint: str | None = None


def scan_subnet(subnet: str) -> list[DiscoveredDevice]:
    """Perform a ping sweep + ARP scan on the given subnet.

    Args:
        subnet: CIDR notation, e.g. '192.0.2.0/24'

    Returns:
        List of discovered devices with MAC, IP, and optional metadata.
    """
    try:
        import nmap
    except ImportError:
        logger.error(
            "python-nmap is not installed. Install with: pip install python-nmap"
        )
        return []

    scanner = nmap.PortScanner()
    devices = []

    try:
        logger.info(f"Scanning subnet: {subnet}")
        # -sn: ping scan (no port scan) -- fast discovery
        # -PR: ARP ping (works on local subnet for MAC addresses)
        scanner.scan(hosts=subnet, arguments="-sn -PR")

        for host in scanner.all_hosts():
            if scanner[host].state() != "up":
                continue

            mac = None
            vendor = None
            # Try nmap's hostname first (fast but often empty)
            hostname = scanner[host].hostname() or None

            # MAC address is in the 'addresses' dict
            addresses = scanner[host].get("addresses", {})
            mac = addresses.get("mac")

            # Vendor info from nmap's OUI database
            if "vendor" in scanner[host] and mac:
                vendor = scanner[host]["vendor"].get(mac)

            if not mac:
                # Local machine won't have a MAC from nmap, skip it
                continue

            # If nmap didn't find a hostname, try hybrid DNS/NetBIOS lookup
            if not hostname:
                hostname = resolve_hostname(host, timeout=2.0)

            devices.append(DiscoveredDevice(
                mac=mac.lower(),
                ip=host,
                hostname=hostname,
                manufacturer=vendor,
            ))

        logger.info(f"Discovered {len(devices)} devices on {subnet}")

    except nmap.PortScannerError as e:
        logger.error(f"nmap scan failed: {e}")
    except Exception as e:
        logger.error(f"Scan error on {subnet}: {e}")

    return devices


def scan_subnets(subnets: list[str]) -> list[DiscoveredDevice]:
    """Scan multiple subnets and return combined results."""
    all_devices = []
    seen_macs = set()

    for subnet in subnets:
        for device in scan_subnet(subnet):
            if device.mac not in seen_macs:
                seen_macs.add(device.mac)
                all_devices.append(device)

    return all_devices
