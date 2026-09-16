"""Unit tests for app.toast_redirect. No server, no database.

Spec: docs/specs/toast-redirect-kind.md, the commit 2 gate.
"""
from urllib.parse import parse_qs, urlsplit

import pytest

from app.toast_redirect import TOAST_KINDS, toast_redirect


def _query(response):
    return parse_qs(urlsplit(response.headers["location"]).query, keep_blank_values=True)


def test_status_is_303():
    assert toast_redirect("/x", "Done").status_code == 303


def test_success_matches_the_legacy_url_shape():
    r = toast_redirect("/assettracker/items/7", "Checked out")
    assert r.headers["location"] == "/assettracker/items/7?toast=Checked+out"


def test_success_sends_no_toast_type():
    assert "toast_type" not in _query(toast_redirect("/x", "Done"))
    assert "toast_type" not in _query(toast_redirect("/x", "Done", "success"))


@pytest.mark.parametrize("kind", ["error", "warning", "info"])
def test_other_kinds_send_toast_type(kind):
    assert _query(toast_redirect("/x", "Hi", kind))["toast_type"] == [kind]


def test_message_round_trips_after_one_decode():
    message = "50% off & more #1: 1+1"
    assert _query(toast_redirect("/x", message))["toast"] == [message]


def test_existing_query_is_kept():
    q = _query(toast_redirect("/x?keep=1", "Hi", "info"))
    assert q["keep"] == ["1"]
    assert q["toast"] == ["Hi"]
    assert q["toast_type"] == ["info"]


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        toast_redirect("/x", "Hi", "bogus")


def test_kinds_match_the_handler():
    assert TOAST_KINDS == ("success", "error", "warning", "info")
