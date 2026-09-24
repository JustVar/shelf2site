"""Local time for everything the app shows: America/Chicago, DST handled.

docs/specs/local-time.md. Storage stays UTC. A naive datetime from the
database is UTC wall time; an aware one converts as it is. A date is a
calendar day and is never converted. Conversion happens only on the way out.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("America/Chicago")


def to_local(value):
    """The value as an aware datetime in APP_TZ.

    None and a date that is not a datetime come back unchanged. A naive
    datetime is taken as UTC.
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TZ)


def fmt_local(value, fmt):
    """to_local, then strftime. None gives an empty string.

    Put %Z in the format wherever a time is shown, so it reads CDT or CST.
    """
    if value is None:
        return ""
    return to_local(value).strftime(fmt)


def local_now():
    """The current moment as an aware datetime in APP_TZ."""
    return datetime.now(APP_TZ)


def local_today():
    """Today's date in Central, not in UTC."""
    return local_now().date()


def register(env):
    """Add the localtime filter to a Jinja environment, and nothing else.

    Every module that builds Jinja2Templates calls this once, next to its
    base_path global. tests/test_localtime.py checks that.
    """
    env.filters["localtime"] = fmt_local
