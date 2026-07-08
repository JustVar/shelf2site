"""Offline breached / common-password blocklist (NIST SP 800-63B Rev 4).

A top-N common/breached password list is loaded ONCE at import into a module-level set, so each
check is an O(1) set membership test. There are NO outbound network calls, ever.

Fail-open: if the file is absent or unreadable, the set is empty and a startup WARNING is logged
- a missing list never breaks logins or password changes (length is still enforced by the
validator). The file is plaintext, one password per line, matched case-insensitively, and lives
under PASSWORD_BLOCKLIST_PATH (a bind-mounted runtime data dir on apphost), NOT in git.
"""
import logging
from pathlib import Path

from .config import settings

_log = logging.getLogger("app.password_blocklist")


def _load() -> set:
    path = Path(settings.PASSWORD_BLOCKLIST_PATH)
    if not path.exists():
        _log.warning(
            "Password blocklist not found at %s - blocklist check DISABLED (length still "
            "enforced). Place a common/breached-password list there and restart to enable it.",
            path,
        )
        return set()
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            entries = {line.strip().lower() for line in fh if line.strip()}
        _log.warning("Password blocklist loaded: %d entries from %s", len(entries), path)
        return entries
    except Exception as exc:  # fail-open on any read error
        _log.warning("Password blocklist load FAILED (%s) at %s - check DISABLED", exc, path)
        return set()


# Loaded once at import (i.e. at app startup, per worker).
_BLOCKLIST = _load()


def is_blocked(password: str) -> bool:
    """True if the password is in the loaded blocklist (case-insensitive). Empty list -> False."""
    if not _BLOCKLIST:
        return False
    return password.strip().lower() in _BLOCKLIST


def blocklist_size() -> int:
    """Number of entries loaded (0 when the file is absent/unreadable). For startup diagnostics."""
    return len(_BLOCKLIST)
