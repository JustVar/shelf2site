"""Hybrid hostname resolver using DNS, mDNS, and NetBIOS.

Attempts multiple methods to resolve IP addresses to hostnames:
1. DNS reverse lookup (fastest, works if PTR records exist)
2. mDNS query (for Apple/Linux devices broadcasting .local names)
3. NetBIOS name query (for Windows devices)
"""

import logging
import socket
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_dns(ip: str, timeout: float = 1.0) -> Optional[str]:
    """Attempt DNS reverse lookup via socket.gethostbyaddr().

    Args:
        ip: IP address to resolve
        timeout: Socket timeout in seconds

    Returns:
        Hostname if found, None otherwise
    """
    try:
        socket.setdefaulttimeout(timeout)
        hostname, _, _ = socket.gethostbyaddr(ip)
        # Clean up FQDN to just hostname
        if hostname and '.' in hostname:
            hostname = hostname.split('.')[0]
        return hostname if hostname else None
    except (socket.herror, socket.gaierror, socket.timeout):
        return None
    except Exception as e:
        logger.debug(f"DNS lookup failed for {ip}: {e}")
        return None


def resolve_mdns(ip: str, timeout: float = 1.0) -> Optional[str]:
    """Attempt mDNS query for .local hostname.

    Args:
        ip: IP address to resolve
        timeout: Query timeout in seconds

    Returns:
        Hostname if found, None otherwise
    """
    try:
        from zeroconf import Zeroconf, ServiceBrowser
        # Quick mDNS PTR lookup
        zc = Zeroconf()
        try:
            # Query for the hostname via reverse IP lookup
            # This is a simplified approach - full mDNS would enumerate services
            # For now, we'll skip mDNS if zeroconf adds too much complexity
            # and rely on DNS + NetBIOS
            return None
        finally:
            zc.close()
    except ImportError:
        logger.debug("zeroconf not installed, skipping mDNS")
        return None
    except Exception as e:
        logger.debug(f"mDNS lookup failed for {ip}: {e}")
        return None


def resolve_netbios(ip: str, timeout: float = 1.0) -> Optional[str]:
    """Attempt NetBIOS name query for Windows devices.

    Args:
        ip: IP address to resolve
        timeout: Query timeout in seconds

    Returns:
        Hostname if found, None otherwise
    """
    try:
        from nmb.NetBIOS import NetBIOS
        nb = NetBIOS()
        try:
            # Query NetBIOS name
            # Port 137 NetBIOS name service
            names = nb.queryIPForName(ip, timeout=int(timeout))
            if names and len(names) > 0:
                # Return the first name (usually the computer name)
                hostname = names[0].decode('utf-8').strip()
                return hostname if hostname else None
            return None
        finally:
            nb.close()
    except ImportError:
        logger.debug("pysmb not installed, skipping NetBIOS")
        return None
    except Exception as e:
        logger.debug(f"NetBIOS lookup failed for {ip}: {e}")
        return None


def resolve_hostname(ip: str, timeout: float = 2.0) -> Optional[str]:
    """Hybrid hostname resolution with fallback chain.

    Tries DNS first (fastest), then NetBIOS for Windows devices.
    Skips mDNS for now to keep dependencies minimal.

    Args:
        ip: IP address to resolve
        timeout: Total timeout budget in seconds

    Returns:
        Hostname if found via any method, None otherwise
    """
    # Try DNS first (most reliable and fastest)
    hostname = resolve_dns(ip, timeout=timeout * 0.5)
    if hostname:
        logger.debug(f"Resolved {ip} via DNS: {hostname}")
        return hostname

    # Try NetBIOS for Windows devices
    hostname = resolve_netbios(ip, timeout=timeout * 0.5)
    if hostname:
        logger.debug(f"Resolved {ip} via NetBIOS: {hostname}")
        return hostname

    # Could add mDNS here in the future if needed
    # hostname = resolve_mdns(ip, timeout=remaining_time)

    logger.debug(f"No hostname found for {ip}")
    return None


def resolve_hostnames_batch(ips: list[str], timeout_per_ip: float = 2.0) -> dict[str, Optional[str]]:
    """Resolve hostnames for multiple IPs in batch.

    Args:
        ips: List of IP addresses to resolve
        timeout_per_ip: Timeout budget per IP in seconds

    Returns:
        Dictionary mapping IP -> hostname (or None if not found)
    """
    results = {}
    for ip in ips:
        results[ip] = resolve_hostname(ip, timeout=timeout_per_ip)
    return results
