"""Generic accessors refuse models outside the TABLE_MODELS family.

get_serial and get_display_name were written for the 22 per-category inventory
models. Both matched by shape rather than by family, so a model outside it was
absorbed silently: get_serial matched Item.part_number, which is a RELATIONSHIP,
and returned an ItemPartNumber where a string belongs; get_display_name found no
branch for Item and fell through to a "device" column Item does not have,
returning a bare hyphen. Both rendered as plausible text.

No live path passes an Item to either one: all seven get_serial call sites
resolve through TABLE_MODELS, which has no items key. These tests exist for the
caller who has not been written yet.
"""

import pytest

from app.models import EdgeBox, Item, ItemPartNumber, Monitor, get_display_name, get_serial


def test_get_serial_refuses_a_relationship_match():
    """The original defect: hasattr matched Item.part_number, a RELATIONSHIP."""
    item = Item(item_name="C2C Camera SX-01", item_sn="C2C-SX-0001")
    item.part_number = ItemPartNumber(brand_sku="PVA-100-30NR")

    assert hasattr(item, "part_number"), "the collision that caused the defect"
    assert "part_number" not in Item.__mapper__.column_attrs, "but not a column"

    with pytest.raises(TypeError) as exc:
        get_serial(item)

    msg = str(exc.value)
    assert "Item" in msg
    assert "_resolve_unit_serial" in msg, "the message must name what to call instead"


def test_get_serial_refuses_regardless_of_relationship_state():
    """Structure, not value. A value-shaped guard would pass here and raise on
    the test above: same model, different row, different outcome. The column
    check does not vary by row."""
    item = Item(item_name="C2C Camera SX-02", item_sn="C2C-SX-0002")
    assert item.part_number is None, "brand_sku is NULL, so the relationship is None"

    with pytest.raises(TypeError):
        get_serial(item)


def test_get_display_name_refuses_a_model_with_no_branch():
    """Item.__tablename__ is 'items', which matches no branch, and Item has no
    'device' column to fall back on."""
    item = Item(item_name="C2C Camera SX-01", item_sn="C2C-SX-0001")

    with pytest.raises(TypeError) as exc:
        get_display_name(item)

    msg = str(exc.value)
    assert "Item" in msg
    assert "items" in msg
    assert "_resolve_device_name" in msg, "the message must name what to call instead"


def test_get_serial_unchanged_for_inventory_models():
    """The refusal must not disturb the family these were written for."""
    assert get_serial(EdgeBox(serial="SEED-GX-1")) == "SEED-GX-1"
    assert get_serial(EdgeBox()) == "-"
    assert get_serial(Monitor(device="Dell U2720Q")) == "-"


def test_get_display_name_unchanged_for_inventory_models():
    assert get_display_name(EdgeBox(org="Acme", site_name="Main St")) == "Acme - Main St"
    assert get_display_name(EdgeBox(serial="SEED-GX-1")) == "SEED-GX-1"
    assert get_display_name(Monitor(device="Dell U2720Q")) == "Dell U2720Q"
    assert get_display_name(Monitor()) == "-"
