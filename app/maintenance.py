"""In-memory service maintenance announcement state.

No database — state lives in memory and resets on restart (intentional, since
announcements are only meaningful before a restart). The admin broadcasts via
SSE; a polling fallback serves clients that reconnect after the SSE drops.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class MaintenanceAnnouncement:
    active: bool = False
    message: str = ""
    restart_at: Optional[datetime] = None   # UTC aware; None = no specific time
    announced_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        minutes_remaining: Optional[int] = None
        if self.restart_at:
            delta = (self.restart_at - datetime.now(timezone.utc)).total_seconds()
            minutes_remaining = max(0, int(delta // 60))
        return {
            "active": self.active,
            "message": self.message,
            "restart_at": self.restart_at.isoformat() if self.restart_at else None,
            "announced_at": self.announced_at.isoformat() if self.announced_at else None,
            "minutes_remaining": minutes_remaining,
        }


_state = MaintenanceAnnouncement()


def get_announcement() -> MaintenanceAnnouncement:
    return _state


def set_announcement(message: str, restart_at: Optional[datetime] = None) -> dict:
    _state.active = True
    _state.message = message
    _state.restart_at = restart_at
    _state.announced_at = datetime.now(timezone.utc)
    return _state.to_dict()


def clear_announcement() -> dict:
    _state.active = False
    _state.message = ""
    _state.restart_at = None
    _state.announced_at = None
    return _state.to_dict()
