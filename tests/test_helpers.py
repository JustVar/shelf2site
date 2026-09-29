"""Unit tests for the shared helpers the sweep consolidated or hardened.

No DB, no HTTP — these run in milliseconds and cover the logic that several
routes now depend on: MAC normalization, password strength, map visibility
cascade, and deal-type derivation.
"""

import pytest

from app.auth import BCRYPT_MAX_BYTES, hash_password, validate_password_strength, verify_password
from app.config import settings
from app.map_visibility import norm_key, unit_visible
from app.routes.map import _classify
from app.validation import normalize_mac, validate_mac_address


# ── MAC normalization (app/validation.py) ──────────────────────────────────
# The macaddr column rejects '' and dash-separated input; every write path now
# funnels through this one helper. Cousins of the fixed null-MAC bug.

@pytest.mark.parametrize("raw,expected", [
    ("AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF"),   # already canonical
    ("AA-BB-CC-DD-EE-FF", "AA:BB:CC:DD:EE:FF"),   # dash separated
    ("AABBCCDDEEFF", "AA:BB:CC:DD:EE:FF"),        # bare
    ("AABB.CCDD.EEFF", "AA:BB:CC:DD:EE:FF"),      # cisco dotted
    ("aa:bb:cc:dd:ee:ff", "AA:BB:CC:DD:EE:FF"),   # lowercase
    ("  AA:BB:CC:DD:EE:FF  ", "AA:BB:CC:DD:EE:FF"),  # surrounding space
])
def test_normalize_mac_accepts_every_format_and_canonicalizes(raw, expected):
    assert normalize_mac(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_normalize_mac_maps_empty_to_none_never_empty_string(raw):
    """An empty string into a macaddr column is an InvalidTextRepresentation 500."""
    assert normalize_mac(raw) is None


@pytest.mark.parametrize("raw", [
    "AA:BB:CC:DD:GG",      # too short AND non-hex
    "AA:BB:CC:DD:EE:GG",   # non-hex pair
    "AABBCCDDEEF",         # 11 chars
    "AABBCCDDEEFFA",       # 13 chars
    "not-a-mac",
])
def test_normalize_mac_rejects_invalid_input(raw):
    with pytest.raises(ValueError) as exc:
        normalize_mac(raw)
    assert "MAC address" in str(exc.value)


def test_validate_mac_address_wrapper_matches_normalize_mac():
    assert validate_mac_address("AA-BB-CC-DD-EE-FF") == (True, "AA:BB:CC:DD:EE:FF")
    assert validate_mac_address("") == (True, None)
    ok, err = validate_mac_address("AA:BB:CC:DD:GG")
    assert ok is False and "MAC address" in err


# ── Password strength (app/auth.py) ────────────────────────────────────────

def test_password_below_minimum_length_is_rejected():
    assert "at least" in validate_password_strength("short")


def test_password_over_bcrypt_limit_is_rejected_with_a_friendly_message():
    """Oversized passwords are rejected where they are SET, in the user's language."""
    err = validate_password_strength("y" * (BCRYPT_MAX_BYTES + 1))
    assert err and "too long" in err
    assert "bcrypt" not in err.lower() and "72 bytes" not in err


def test_oversized_passwords_still_verify_so_legacy_accounts_are_not_locked_out():
    """bcrypt 4.x truncates at 72 bytes instead of raising.

    Any account whose password was set before the max-length rule has a hash of
    the truncated form. verify_password must keep accepting the full string, or
    those users get "invalid username or password" with no way to diagnose it.
    If a future bcrypt restores the ValueError, this test fails and tells us to
    re-add a guard at the verify boundary.
    """
    long_pw = "y" * (BCRYPT_MAX_BYTES + 28)
    stored = hash_password(long_pw)          # must not raise
    assert verify_password(long_pw, stored) is True
    assert verify_password("y" * BCRYPT_MAX_BYTES, stored) is True   # truncation equivalence
    assert verify_password("z" * BCRYPT_MAX_BYTES, stored) is False


def test_multibyte_password_is_measured_in_bytes_not_characters():
    """'é' is 2 bytes in UTF-8 — 40 chars can still exceed the 72-byte limit."""
    pw = "é" * 40  # 80 bytes, 40 characters
    assert len(pw) < BCRYPT_MAX_BYTES < len(pw.encode("utf-8"))
    assert "too long" in validate_password_strength(pw)


def test_a_long_clean_password_passes_every_rule():
    assert validate_password_strength("correct-horse-fiddle-97") is None


@pytest.mark.skipif(
    __import__("app.password_blocklist", fromlist=["blocklist_size"]).blocklist_size() == 0,
    reason="blocklist file absent — check is fail-open here",
)
def test_a_breached_password_over_the_length_minimum_is_rejected():
    """Isolates the breach rule: this password is long enough to clear the length gate."""
    breached = "1q2w3e4r5t6y7u8i9o0p"
    assert len(breached) >= settings.PASSWORD_MIN_LENGTH
    err = validate_password_strength(breached)
    assert err and "known breaches" in err


# ── Map visibility cascade (app/map_visibility.py) ─────────────────────────

def _hidden(units=(), sites=(), customers=()):
    return {"unit": set(units), "site": set(sites), "customer": set(customers)}


def test_a_unit_with_nothing_hidden_is_visible():
    assert unit_visible(_hidden(), "item:1", "Acme", "HQ", False, False) is True


def test_unit_level_hide_wins():
    assert unit_visible(_hidden(units={"item:1"}), "item:1", "Acme", "HQ", False, False) is False


def test_site_level_hide_cascades_to_its_units():
    assert unit_visible(_hidden(sites={"hq"}), "item:1", "Acme", "HQ", False, False) is False


def test_customer_level_hide_cascades_to_its_units():
    assert unit_visible(_hidden(customers={"acme"}), "item:1", "Acme", "HQ", False, False) is False


def test_curation_keys_are_case_and_whitespace_insensitive():
    assert norm_key("  AcMe  ") == "acme"
    assert unit_visible(_hidden(customers={"acme"}), "item:1", "  ACME ", None, False, False) is False


def test_sensitive_order_is_hidden_from_a_viewer_without_the_grant():
    assert unit_visible(_hidden(), "item:1", "Acme", "HQ", True, False) is False


def test_sensitive_order_is_visible_to_a_viewer_with_the_grant():
    assert unit_visible(_hidden(), "item:1", "Acme", "HQ", True, True) is True


def test_a_hidden_unit_stays_hidden_even_with_the_sensitive_grant():
    """Curation and the sensitive rule are AND-ed; neither can override the other."""
    assert unit_visible(_hidden(units={"item:1"}), "item:1", "Acme", "HQ", True, True) is False


# ── Deal-type derivation (app/routes/map.py) ───────────────────────────────

class _Link:
    """Stand-in for the joined DeviceProvisioning/CustomerOrder row."""
    def __init__(self, order_type):
        self.order_type = order_type


@pytest.mark.parametrize("order_type,expected", [
    ("sale", "purchased"),
    ("pilot", "pilot"),
    ("try_and_buy", "try_and_buy"),
    ("demo", "demo"),
])
def test_order_linkage_wins_and_is_marked_as_order_provenance(order_type, expected):
    cls, provenance, link = _classify(_Link(order_type))
    assert (cls, provenance) == (expected, "order")
    assert link is not None


def test_no_linkage_is_unassigned():
    """Item 30 S4 retired the legacy deployment_type inference."""
    assert _classify(None) == ("unassigned", "none", None)


def test_an_unrecognized_order_type_is_unassigned():
    """A new order_type must not silently classify as a known deal class."""
    assert _classify(_Link("subscription"))[:2] == ("unassigned", "none")
