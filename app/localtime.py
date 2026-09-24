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


def parse_utc(text):
    """An ISO timestamp string as naive UTC wall time, the way the database stores it.

    An offset converts to UTC; no offset is taken as UTC already. None, an
    empty string, a date with no time, or text that does not parse gives None.
    """
    if not text:
        return None
    text = str(text).strip()
    try:
        date.fromisoformat(text)
        return None  # a bare date is a calendar day, not a moment
    except ValueError:
        pass
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def fmt_stamp(text, fmt):
    """parse_utc, then fmt_local. For times stored as ISO text (provisioning stage stamps)."""
    return fmt_local(parse_utc(text), fmt)


def register(env):
    """Add the localtime and localstamp filters to a Jinja environment, and nothing else.

    Every module that builds Jinja2Templates calls this once, next to its
    base_path global. tests/test_localtime.py checks that.
    """
    env.filters["localtime"] = fmt_local
    env.filters["localstamp"] = fmt_stamp
