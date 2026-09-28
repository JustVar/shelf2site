"""The local time helper and its template filter (docs/specs/local-time.md, slice A).

Behaviour: conversion across both 2026 daylight saving edges and the evening
case, from naive UTC (how the database returns timestamps) and from aware
values. A UTC passthrough fails every conversion case below.

Structural: every module under app/ that builds Jinja2Templates also calls
register, so the localtime filter exists in every template environment. The
module count is checked too, so a lost module is seen.

Render: the filter works through a real Jinja environment.
"""

import ast
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import jinja2
import pytest

from app.localtime import fmt_local, parse_utc, register, to_local

APP = Path(__file__).resolve().parents[1] / "app"
FMT = "%Y-%m-%d %H:%M %Z"

# Naive UTC in, Central out: both daylight saving edges and the evening case.
CASES = [
    (datetime(2026, 3, 8, 7, 59), "2026-03-08 01:59 CST"),
    (datetime(2026, 3, 8, 8, 0), "2026-03-08 03:00 CDT"),
    (datetime(2026, 11, 1, 6, 59), "2026-11-01 01:59 CDT"),
    (datetime(2026, 11, 1, 7, 0), "2026-11-01 01:00 CST"),
    (datetime(2026, 9, 25, 0, 30), "2026-09-24 19:30 CDT"),
]
CASE_IDS = ["spring-before", "spring-after", "fall-before", "fall-after", "evening"]


@pytest.mark.parametrize("naive, want", CASES, ids=CASE_IDS)
def test_naive_utc_converts(naive, want):
    assert fmt_local(naive, FMT) == want


@pytest.mark.parametrize("naive, want", CASES, ids=CASE_IDS)
def test_aware_utc_matches_its_naive_twin(naive, want):
    aware = naive.replace(tzinfo=timezone.utc)
    assert fmt_local(aware, FMT) == want


def test_aware_non_utc_converts():
    # 12:00 at UTC-05:00 is 17:00 UTC, which is 11:00 CST in January.
    value = datetime(2026, 1, 15, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert fmt_local(value, FMT) == "2026-01-15 11:00 CST"


def test_label_is_the_real_abbreviation():
    assert fmt_local(datetime(2026, 7, 1, 17, 0), "%Z") == "CDT"
    assert fmt_local(datetime(2026, 1, 15, 18, 0), "%Z") == "CST"


def test_a_date_is_never_converted():
    day = date(2026, 9, 24)
    assert to_local(day) is day
    assert fmt_local(day, "%Y-%m-%d") == "2026-09-24"


def test_none_passes_through():
    assert to_local(None) is None
    assert fmt_local(None, FMT) == ""


# ISO text in, naive UTC out: an offset converts, no offset is UTC already.
PARSE_CASES = [
    ("2026-09-25T00:30:00.123456", datetime(2026, 9, 25, 0, 30, 0, 123456)),
    ("2026-09-25T00:30:00+00:00", datetime(2026, 9, 25, 0, 30)),
    ("2026-09-24T19:30:00-05:00", datetime(2026, 9, 25, 0, 30)),
    ("2026-09-25T00:30:00Z", datetime(2026, 9, 25, 0, 30)),
    ("2026-09-24", None),
    ("not a time", None),
    ("", None),
    (None, None),
]
PARSE_IDS = ["naive-micro", "utc-offset", "minus-five", "zulu",
             "bare-date", "garbage", "empty", "none"]


@pytest.mark.parametrize("text, want", PARSE_CASES, ids=PARSE_IDS)
def test_parse_utc(text, want):
    assert parse_utc(text) == want


# -- Structural ------------------------------------------------------------------

def _called_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _template_modules():
    """Every module under app/ that builds Jinja2Templates, and whether it calls register."""
    found = {}
    for path in sorted(APP.rglob("*.py")):
        called = _called_names(ast.parse(path.read_text(encoding="utf-8")))
        if "Jinja2Templates" in called:
            found[path.relative_to(APP.parent).as_posix()] = "register" in called
    return found


TEMPLATE_MODULES = _template_modules()


def test_template_modules_are_all_found():
    # 29 at slice A; 27 since item 30 S3 retired intune_routes and lifecycle.
    # More is fine; fewer means one was lost or renamed.
    assert len(TEMPLATE_MODULES) >= 27, sorted(TEMPLATE_MODULES)


@pytest.mark.parametrize("module", sorted(TEMPLATE_MODULES))
def test_every_template_module_registers_the_filter(module):
    assert TEMPLATE_MODULES[module], (
        "%s builds Jinja2Templates but never calls register(templates.env), "
        "so its templates cannot use the localtime filter" % module)


# -- Templates -------------------------------------------------------------------

TEMPLATES = APP / "templates"
STRFTIME = re.compile(r"([\w.]+)\.strftime\(")
UTC_WORD = re.compile(r"\bUTC\b")

# The Date sites: a calendar day is never converted, so .strftime( stays.
DATE_SITES = {
    "vendor_detail_profile.html": {"t.received_date", "t.return_deadline"},
    "partials/item_quick_view.html": {"item.last_updated"},
    "fulfillment.html": {
        "dr.scheduled_date", "dr.installed_date", "dr.cert_completion_date", "card.due_date"},
    "site_detail.html": {"a.assigned_date", "a.expected_return", "a.returned_date"},
    "item_detail.html": {
        "containment.parent.installed_date", "item.date_purchased", "item.dispatched_date",
        "r.transaction_date", "r.created_at", "ch.installed_date", "c.event.action_date",
        "m.maintenance_date", "co.checkin_date", "co.checkout_date",
        "item.created_at", "item.last_updated"},
    "receipts_list.html": {"r.transaction_date"},
    "provisioning_detail.html": {"rec.start_date", "rec.due_date"},
    "inventory.html": {"row.last_updated"},
    "receipt_detail.html": {"r.transaction_date", "r.created_at"},
}
ALLOWED = {(path, expr) for path, exprs in DATE_SITES.items() for expr in exprs}


def _template_strftime_sites():
    """Every (template path, expression) pair that calls .strftime( under app/templates."""
    found = set()
    for path in sorted(TEMPLATES.rglob("*.html")):
        rel = path.relative_to(TEMPLATES).as_posix()
        for expr in STRFTIME.findall(path.read_text(encoding="utf-8")):
            found.add((rel, expr))
    return found


def test_template_strftime_only_on_date_columns():
    extra = sorted(_template_strftime_sites() - ALLOWED)
    assert not extra, (
        "strftime on a value that is not a Date column, use |localtime: %s" % extra)


def test_no_template_prints_a_utc_label():
    hits = sorted(
        path.relative_to(TEMPLATES).as_posix()
        for path in TEMPLATES.rglob("*.html")
        if UTC_WORD.search(path.read_text(encoding="utf-8")))
    assert not hits, "a template still prints a UTC label: %s" % hits


# -- Render ----------------------------------------------------------------------

def test_register_adds_only_the_filters():
    env = jinja2.Environment()
    filters_before, globals_before = set(env.filters), dict(env.globals)
    register(env)
    assert set(env.filters) - filters_before == {"localtime", "localstamp"}
    assert env.globals == globals_before


def test_filter_renders_through_jinja():
    env = jinja2.Environment()
    register(env)
    out = env.from_string('{{ v|localtime("%Y-%m-%d %H:%M %Z") }}').render(
        v=datetime(2026, 9, 25, 0, 30))
    assert out == "2026-09-24 19:30 CDT"


def test_localstamp_renders_through_jinja():
    env = jinja2.Environment()
    register(env)
    template = env.from_string('{{ s|localstamp("%Y-%m-%d %H:%M %Z") }}')
    assert template.render(s="2026-09-25T00:30:00") == "2026-09-24 19:30 CDT"
    assert template.render(s=None) == ""


# -- Today (slice C) -------------------------------------------------------------

# Every date column with a default in the live catalog. Migration 079 reads the same set.
LIVE_DATE_DEFAULTS = (
    "SELECT table_schema, table_name, column_name, column_default "
    "FROM information_schema.columns "
    "WHERE data_type = 'date' AND column_default IS NOT NULL "
    "AND table_schema NOT IN ('pg_catalog', 'information_schema') "
    "ORDER BY table_schema, table_name, column_name")


def test_local_today_is_the_central_date(monkeypatch):
    import app.localtime as lt

    class FrozenClock(datetime):
        instant = None

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)

    monkeypatch.setattr(lt, "datetime", FrozenClock)
    # 00:30 UTC is 19:30 CDT the evening before; 05:30 UTC is 00:30 CDT.
    FrozenClock.instant = datetime(2026, 9, 25, 0, 30, tzinfo=timezone.utc)
    assert lt.local_today() == date(2026, 9, 24)
    FrozenClock.instant = datetime(2026, 9, 25, 5, 30, tzinfo=timezone.utc)
    assert lt.local_today() == date(2026, 9, 25)


def test_no_date_today_under_app():
    hits = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "today"):
                hits.append("%s:%d" % (path.relative_to(APP.parent).as_posix(), node.lineno))
    assert not hits, "%d calls read today on the UTC clock, use local_today(): %s" % (len(hits), hits)


def _model_date_defaults():
    """table.column -> default SQL, for every Date column in the models that has a default."""
    from sqlalchemy import Date
    from sqlalchemy.dialects import postgresql

    import app.models  # noqa: F401  registers every table on Base.metadata
    from app.database import Base

    found = {}
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, Date) and col.server_default is not None:
                arg = col.server_default.arg
                sql = arg if isinstance(arg, str) else str(arg.compile(dialect=postgresql.dialect()))
                found["%s.%s" % (table.fullname, col.name)] = sql
    return found


def test_model_date_defaults_use_central():
    found = _model_date_defaults()
    utc = sorted("%s = %s" % (k, v) for k, v in found.items() if "America/Chicago" not in v)
    assert not utc, "%d model date defaults use the UTC date: %s" % (len(utc), utc)
    assert len(found) == 13, sorted(found)


def test_item_last_updated_onupdate_uses_central():
    from sqlalchemy.dialects import postgresql

    from app.models import Item

    sql = str(Item.__table__.c.last_updated.onupdate.arg.compile(dialect=postgresql.dialect()))
    assert "America/Chicago" in sql, sql


def test_live_date_defaults_use_central():
    from sqlalchemy import text

    from app.database import engine

    with engine.connect() as conn:
        rows = conn.execute(text(LIVE_DATE_DEFAULTS)).fetchall()
    utc = sorted("%s.%s.%s = %s" % tuple(r) for r in rows if "America/Chicago" not in r[3])
    assert not utc, "%d live date defaults use the UTC date: %s" % (len(utc), utc)
    assert len(rows) == 16, [tuple(r) for r in rows]


def test_no_template_uses_a_utc_date_default():
    hits = sorted(
        path.relative_to(TEMPLATES).as_posix()
        for path in TEMPLATES.rglob("*.html")
        if "toISOString(" in path.read_text(encoding="utf-8"))
    assert not hits, "%d templates default a date input to the UTC date: %s" % (len(hits), hits)


# -- Files (slice D) -------------------------------------------------------------

# A time printed with a literal UTC label: after %M, %H or %S, or opening the string.
UTC_LABEL = re.compile(r"(%M|%H|%S) ?UTC|^ ?UTC\b")


def test_no_naive_datetime_now_under_app():
    hits = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "now" and not node.args and not node.keywords):
                continue
            # datetime.now() or datetime.datetime.now(); func.now() is SQL and stays.
            receiver = node.func.value
            if ((isinstance(receiver, ast.Name) and receiver.id == "datetime")
                    or (isinstance(receiver, ast.Attribute) and receiver.attr == "datetime")):
                hits.append("%s:%d" % (path.relative_to(APP.parent).as_posix(), node.lineno))
    assert not hits, "%d naive datetime.now() calls, use local_now(): %s" % (len(hits), hits)


def test_no_utc_label_in_app_python():
    hits = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and UTC_LABEL.search(node.value)):
                hits.append("%s:%d %r" % (path.relative_to(APP.parent).as_posix(), node.lineno, node.value))
    assert not hits, "%d app strings print a UTC label, use %%Z: %s" % (len(hits), hits)
