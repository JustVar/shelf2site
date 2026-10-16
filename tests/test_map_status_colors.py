"""The map colors a point by its item status. STATUS_COLORS must key on exactly
the item_statuses enum: a missing status draws grey with no legend entry, and
a key no item can have puts a dead entry in the legend."""

from app.models import ITEM_STATUSES
from app.routes.map import STATUS_COLORS


def test_map_status_colors_match_the_item_status_enum():
    assert set(STATUS_COLORS) == set(ITEM_STATUSES)
