"""Directories under the upload roots that are named after user data.

Certification files are filed under a folder named after the unit's serial
number. A serial is free text an editor can set, so a value such as
"../../somewhere" must never reach the filesystem as a path. serial_dir()
reduces it to one safe path segment; ordinary serials (letters, digits, dot,
dash, underscore) come through unchanged, so existing folders still match.
"""
import re
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_segment(value, default: str = "unknown") -> str:
    """One path segment made from free text: no separators, no leading dots."""
    seg = _UNSAFE.sub("_", str(value or "")).lstrip(".")
    return seg[:128] or default


def serial_dir(root: str, serial) -> Path:
    """The folder for a serial under an upload root. Raises if it would escape."""
    base = Path(root).resolve()
    path = (base / safe_segment(serial)).resolve()
    if path.parent != base:
        raise ValueError("upload path escapes its root")
    return path
