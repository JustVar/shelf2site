"""Every enabled tour's selectors exist on its own page.

lint_tour_selectors (app/tours.py) already knew how to check this, but no
test ran it, so a page redesign could strand a tour step silently. Disabled
tours are kept for the record and are not checked.
"""
import pytest

from app.tours import TOURS, lint_tour_selectors

ENABLED = [t["id"] for t in TOURS if t.get("enabled")]


@pytest.mark.parametrize("tour_id", ENABLED)
def test_enabled_tour_selectors_exist(tour_id, capsys):
    assert lint_tour_selectors(tour_id) == 0, capsys.readouterr().out[-2000:]
