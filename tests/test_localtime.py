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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import jinja2
import pytest

from app.localtime import fmt_local, register, to_local

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
    # 29 at slice A. More is fine; fewer means one was lost or renamed.
    assert len(TEMPLATE_MODULES) >= 29, sorted(TEMPLATE_MODULES)


@pytest.mark.parametrize("module", sorted(TEMPLATE_MODULES))
def test_every_template_module_registers_the_filter(module):
    assert TEMPLATE_MODULES[module], (
        "%s builds Jinja2Templates but never calls register(templates.env), "
        "so its templates cannot use the localtime filter" % module)


# -- Render ----------------------------------------------------------------------

def test_register_adds_only_the_filter():
    env = jinja2.Environment()
    filters_before, globals_before = set(env.filters), dict(env.globals)
    register(env)
    assert set(env.filters) - filters_before == {"localtime"}
    assert env.globals == globals_before


def test_filter_renders_through_jinja():
    env = jinja2.Environment()
    register(env)
    out = env.from_string('{{ v|localtime("%Y-%m-%d %H:%M %Z") }}').render(
        v=datetime(2026, 9, 25, 0, 30))
    assert out == "2026-09-24 19:30 CDT"
