"""Offline breached / common-password blocklist (NIST SP 800-63B Rev 4).

A top-N common/breached password list is read ONCE at import into a module-level set, so each
check is an O(1) set membership test. There are NO outbound network calls, ever.

Only entries at least PASSWORD_MIN_LENGTH characters long are kept in memory. A shorter entry
can never be the answer to `is_blocked`, because validate_password_strength rejects anything
under the minimum before it ever consults the blocklist. Filtering at load time therefore costs
no coverage and saves the bulk of the memory: at a 15-character minimum, roughly 5.5k of the
939k entries survive, per gunicorn worker. The filter reads PASSWORD_MIN_LENGTH at startup, so
lowering the minimum and restarting re-activates the shorter entries with no file regeneration.

Fail-open: if the file is absent or unreadable, the set is empty and a startup WARNING is logged
- a missing list never breaks logins or password changes (length is still enforced by the
validator). The file is plaintext, one password per line, matched case-insensitively, and lives
under PASSWORD_BLOCKLIST_PATH (a bind-mounted runtime data dir on apphost), NOT in git.
"""
import logging
from pathlib import Path

from .config import settings

_log = logging.getLogger("app.password_blocklist")


def _load() -> tuple[set, int]:
    """Return (active entries >= PASSWORD_MIN_LENGTH, total entries in the file)."""
    path = Path(settings.PASSWORD_BLOCKLIST_PATH)
    min_length = settings.PASSWORD_MIN_LENGTH
    if not path.exists():
        _log.warning(
            "Password blocklist not found at %s - blocklist check DISABLED (length still "
            "enforced). Place a common/breached-password list there and restart to enable it.",
            path,
        )
        return set(), 0
    try:
        active: set[str] = set()
        total = 0
        # Streamed line by line: the full file is never held in memory at once.
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                entry = line.strip().lower()
                if not entry:
                    continue
                total += 1
                if len(entry) >= min_length:
                    active.add(entry)
        _log.warning(
            "Password blocklist: %s of %s entries active at min length %d (from %s)",
            f"{len(active):,}", f"{total:,}", min_length, path,
        )
        return active, total
    except Exception as exc:  # fail-open on any read error
        _log.warning("Password blocklist load FAILED (%s) at %s - check DISABLED", exc, path)
        return set(), 0


# Loaded once at import (i.e. at app startup, per worker).
_BLOCKLIST, _TOTAL_ENTRIES = _load()


def is_blocked(password: str) -> bool:
    """True if the password is in the loaded blocklist (case-insensitive). Empty list -> False.

    Entries shorter than PASSWORD_MIN_LENGTH are not loaded, so this answers False for them.
    That is safe only because the length check runs first; do not call this as a standalone
    "has this password ever been breached" oracle.
    """
    if not _BLOCKLIST:
        return False
    return password.strip().lower() in _BLOCKLIST


def blocklist_size() -> int:
    """Entries active in memory (0 when the file is absent/unreadable). For startup diagnostics."""
    return len(_BLOCKLIST)


def blocklist_total() -> int:
    """Entries present in the file, before the length filter. 0 when absent/unreadable."""
    return _TOTAL_ENTRIES
