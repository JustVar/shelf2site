"""Contract tests for the structural password rules and the length-filtered blocklist.

The cases below are the survivors of an adversarial corpus (175 passwords generated
blind to this implementation, then attacked by a false-positive hunter and a bypass
hunter). Every "must pass" case here is one that some plausible implementation of the
same spec would wrongly reject — they are the spec, not decoration.

Rule of thumb when adding a rule: a false positive locks a real user out of a
passphrase they believe is strong, and they get no way to diagnose it. Prefer a miss.
"""

import pytest

from app.auth import validate_password_strength
from app.config import settings
from app.password_blocklist import blocklist_size, blocklist_total, is_blocked
from app.password_rules import (
    MIN_STRIPPED_LEN,
    check_composition,
    contains_username,
    find_context_word,
    is_keyboard_walk,
    is_repeated_pattern,
    is_sequence,
)

# Structural rules are tested through the rule functions, not through
# validate_password_strength, because many of these strings are ALSO in the breach
# blocklist and it short-circuits first.


# ── Rule 1: repeated pattern ───────────────────────────────────────────────

@pytest.mark.parametrize("password", [
    "aaaaaaaaaaaaaaa",              # one character, 15 times
    "zzzzzzzzzzzzzzzzzzzz",
    "abcabcabcabcabc",              # 3-char block, exactly 5 repeats
    "abcabcabcabcabcab",            # ... with a truncated tail
    "ababababababababab",           # 2 distinct characters
    "aaaaaaaaaaaaaab",              # near-repeat: 2 distinct, no exact period
    "silver12silver12",             # an 8-char secret in a 16-char coat
    "correcthorsecorrecthorse",     # 12-char block doubled: still under the minimum
    "bluehorizon7bluehorizon7",
    "hb7kq9hb7kq9hb7",              # 6-char block, 2.5 repeats
    "dragon12dragon12",
    "sunshine-sunshine",            # only found once separators are stripped
    "pass-word-pass-word",
    "qwerty12-qwerty12",
    "mango-tiger42mango-tiger42",
])
def test_repeated_patterns_are_rejected(password):
    assert is_repeated_pattern(password) is True


@pytest.mark.parametrize("password", [
    "correct-horse-c",              # minimal period 14, but only 1.07 periods
    "correct-horse-battery-staple",
    "velvet-thunder-maple-River-88",
    "chachacha-samba-night-42",     # a repeating PREFIX, not a repeating string
    "murmur-lagoon-velvet-8823",
    "tomtomtom-riverbank",
    "abababab-cd-efgh12",
    "abcdefghijklmnoabcdefghijklmno",  # 15-char unit: the secret meets the minimum
])
def test_ordinary_passphrases_are_not_repeated_patterns(password):
    assert is_repeated_pattern(password) is False


def test_a_repeated_unit_at_the_minimum_length_is_allowed():
    """The rule targets a secret SHORTER than the minimum, padded by repetition.

    A 15-character unit doubled is a 15-character secret, which is exactly what the
    policy asks for, so it passes. A 14-character unit doubled does not.
    """
    unit = "abcdefghijklmno"
    assert len(unit) == settings.PASSWORD_MIN_LENGTH
    assert is_repeated_pattern(unit * 2) is False
    assert is_repeated_pattern("abcdefghijklmn" * 2) is True


# ── Rule 2: sequences ──────────────────────────────────────────────────────

@pytest.mark.parametrize("password", [
    "123456789012345",      # ascending digits, cyclic wrap
    "012345678901234567",
    "abcdefghijklmnop",     # ascending letters
    "ponmlkjihgfedcba",     # descending letters
    "9876543210987654",     # descending digits
    "ABCDEFGHIJKLMNOP",     # casefolded first
    "abcdef-ghijklmno",     # a separator does not save it
])
def test_pure_sequences_are_rejected(password):
    assert is_sequence(password) is True


@pytest.mark.parametrize("password", [
    "abc-mountain-river-42",     # merely CONTAINS an ascending run
    "lemon-123-turquoise",
    "xyz-galaxy-pinewood-7",
    "123456-sunset-meadow",
    "890123-harbor-tulip-5",
    "zyx-mountain-harbor-6",
    "abcde-guitar-midnight-2026",
])
def test_passphrases_containing_a_short_run_are_not_sequences(password):
    assert is_sequence(password) is False


# ── Rule 3: keyboard walks ─────────────────────────────────────────────────

@pytest.mark.parametrize("password", [
    "qwertyuiopasdfgh",        # rows read straight through
    "gfdsapoiuytrewq",         # ... reversed
    "1q2w3e4r5t6y7u8i9o0p",    # the zigzag
    "qazwsxedcrfvtgb",         # a column walk
    "zaqxswcdevfrbgt",         # bottom-up columns
    "qwertyuiop-asdfghjkl",    # separators do not save it
    "qazwsx-edcrfv-tgb",
    "1q2w3e4r5t-6y7u8i9o",
])
def test_keyboard_walks_are_rejected(password):
    assert is_keyboard_walk(password) is True


@pytest.mark.parametrize("password", [
    "asdf-mountain-cloud-8",     # merely BEGINS with a walk
    "qwe-lantern-basket-55",
    "zxc-riverbend-maple-3",
    "qazwsx-and-blueberry",
    "1qaz2wsx-brambles-99",
    "qwerty-sunrise-falcon-9241",
])
def test_passphrases_containing_a_short_walk_are_not_walks(password):
    assert is_keyboard_walk(password) is False


def test_a_symbol_only_password_is_not_a_walk_or_a_sequence():
    """Stripping separators can empty a string, and "" is a substring of everything."""
    symbols = "!@#$%^&*()_+{}|"
    assert len(symbols) >= settings.PASSWORD_MIN_LENGTH
    assert is_keyboard_walk(symbols) is False
    assert is_sequence(symbols) is False


def test_the_empty_password_is_not_a_walk_a_sequence_or_a_repetition():
    """"" is a substring of every haystack. The length check makes this unreachable
    through validate_password_strength, but the predicates are public."""
    assert is_keyboard_walk("") is False
    assert is_sequence("") is False
    assert is_repeated_pattern("") is False
    assert find_context_word("") is None


def test_the_stripped_variant_is_ignored_when_it_is_too_short():
    assert MIN_STRIPPED_LEN >= 4


def test_find_context_word_never_matches_a_username():
    """The username needs boundary matching; it must not leak into the plain-substring set."""
    assert find_context_word("disgraceful-mango-lantern-72") is None
    assert "grace" not in __import__("app.password_rules", fromlist=["x"]).enforced_context_words()


# ── Rule 4a: configured context words (plain substring) ────────────────────

@pytest.mark.parametrize("password,word", [
    ("brand-mountain-river", "brand"),
    ("my-BrAnD-phrase-9", "brand"),          # casefolded
    ("my-assettracker-login-99", "assettracker"),
    ("myASSETTRACKERlogin9", "assettracker"),    # embedded, no separators
    ("the-asset-tracker-vault", "asset-tracker"),
    ("brand2-fields-999", "brand"),
    ("Go-ASSETTRACKER-Team-Winner", "assettracker"),
    ("my-password-is-long-99", "password"),
])
def test_context_words_are_rejected_anywhere_in_the_password(password, word):
    assert find_context_word(password) == word


@pytest.mark.parametrize("password", [
    "isotope-ladder-vault-9",     # "sot" is not "brand"
    "sotto-voce-brisket-9",
    "sotheby-meadow-lantern",     # "sot" is not "brand"
    "soteri-museum-tour-42",      # one letter short
    "compass-lantern-quilt",      # "pass" is not "password"
    "crossword-tunnel-vault",     # "word" is not "password"
    "asset-manager-jungle",       # bare "asset" is not configured
    "asset-management-review-2026q3",
])
def test_incidental_fragments_of_context_words_pass(password):
    assert find_context_word(password) is None


@pytest.mark.parametrize("password", [
    "compass-wordsmith-42",
    "bypass-wordplay-nine1",
    "overpass-wording-lake",
])
def test_separators_are_not_stripped_for_context_words(password):
    """Stripping them would splice "pass" + "word" into "password" and reject a good phrase."""
    assert find_context_word(password) is None
    assert validate_password_strength(password) is None


# ── Rule 4b: the account's own username (boundary matched) ─────────────────

@pytest.mark.parametrize("password,username", [
    ("walter-secret-vault-2026", "walter"),
    ("jvarughese-portal-92x", "jvarughese"),
    ("grace-2026-lantern-x", "grace"),
    ("my.grace.lantern.99x", "grace"),
    ("casey-the-purple-dragon", "casey"),
    ("ander-son-2026!!", "anderson"),      # username split by a separator
])
def test_a_password_using_the_username_as_a_word_is_rejected(password, username):
    assert contains_username(password, username) is True
    assert check_composition(password, username) == "Password must not contain your username."


@pytest.mark.parametrize("password,username", [
    ("disgraceful-mango-lantern-72", "grace"),
    ("romance-thunder-velvet-8841", "roman"),
    ("immigrant-harbor-crimson-59", "grant"),
    ("chamber-echoes-glacier-3378", "amber"),
    ("campaign-slogan-bicycle-4471", "logan"),
    ("carolina-reaper-saffron-9920", "carol"),
])
def test_a_username_occurring_inside_an_ordinary_word_does_not_reject(password, username):
    """Usernames are arbitrary names. "grace" lives inside "disgraceful"; a plain
    substring test would reject six perfectly strong passphrases."""
    assert contains_username(password, username) is False
    assert validate_password_strength(password, username) is None


@pytest.mark.parametrize("password,username", [
    ("jonquil-meadow-river-8", "jon"),        # 3 chars: never checked
    ("a-jus-tified-brisket-9", "jus"),
    ("chocolate-parade-77", "ola"),
    ("alex-mountain-voyage-3", "alexander"),  # only a fragment of the username
])
def test_short_or_partial_usernames_do_not_reject(password, username):
    assert contains_username(password, username) is False


def test_a_username_shorter_than_the_minimum_word_length_is_skipped():
    assert contains_username("jus-jus-jus-jus-jus", "jus") is False


# ── Message quality: specific, never generic, never internal ───────────────

@pytest.mark.parametrize("password,username,fragment", [
    ("walter-secret-vault-2026", "walter", "your username"),
    ("brand-mountain-river", None, "'brand'"),
    ("silver12silver12", None, "repeated pattern"),
    ("ponmlkjihgfedcba", None, "simple sequence"),
    ("gfdsapoiuytrewq", None, "keyboard pattern"),
])
def test_each_rejection_names_the_reason(password, username, fragment):
    message = check_composition(password, username)
    assert message and fragment in message


# ── Strong passwords still pass end to end ─────────────────────────────────

@pytest.mark.parametrize("password", [
    "correct-horse-battery-staple",
    "correct horse battery staple",
    "velvet-thunder-maple-River-88",
    "correct-horse-fiddle-97",
    "quiet-abc-lantern-42",
    "quiet-qwe-lantern-42",
    "mountain-river-hike-2026",
])
def test_strong_passphrases_pass_every_rule(password):
    assert validate_password_strength(password, username="testuser") is None


# ── The length-filtered blocklist ──────────────────────────────────────────

_no_blocklist = blocklist_size() == 0


@pytest.mark.skipif(_no_blocklist, reason="blocklist file absent - check is fail-open here")
def test_only_entries_at_least_the_minimum_length_are_loaded():
    assert blocklist_total() > blocklist_size(), "the length filter kept every entry"
    # A short breached password is deliberately NOT in memory: the length rule
    # rejects it first, so loading it would cost memory and buy nothing.
    assert is_blocked("password") is False
    assert validate_password_strength("password") is not None  # still rejected, on length


@pytest.mark.skipif(_no_blocklist, reason="blocklist file absent - check is fail-open here")
def test_a_long_breached_password_is_still_rejected():
    breached = "1q2w3e4r5t6y7u8i9o0p"
    assert len(breached) >= settings.PASSWORD_MIN_LENGTH
    assert is_blocked(breached) is True
    assert "known breaches" in validate_password_strength(breached)


@pytest.mark.skipif(_no_blocklist, reason="blocklist file absent - check is fail-open here")
def test_the_loaded_set_self_adapts_to_the_configured_minimum():
    """No regeneration step: every loaded entry clears the current minimum length."""
    from app.password_blocklist import _BLOCKLIST
    assert all(len(entry) >= settings.PASSWORD_MIN_LENGTH for entry in _BLOCKLIST)


# ── Regressions found by adversarial review of this change ─────────────────

@pytest.mark.parametrize("password", [
    "monkey123      ",   # 9-character secret padded with spaces to 15
    "   monkey123   ",
    "letmein12345   ",
    "               ",   # 15 spaces
])
def test_whitespace_padding_cannot_smuggle_a_short_secret_past_the_minimum(password):
    """is_blocked() looks up password.strip(), and the loader drops every entry shorter
    than the minimum. If the length gate measured the RAW string, a padded short breach
    password would clear the minimum AND miss the (unloaded) blocklist entry."""
    assert len(password) >= settings.PASSWORD_MIN_LENGTH
    error = validate_password_strength(password)
    assert error and "at least" in error


@pytest.mark.parametrize("password", [
    "my-pａssword-is-long-99",   # fullwidth 'a' (U+FF41) inside "password"
    "ｐａｓｓｗｏｒｄ１２３４５６７",       # entirely fullwidth
    "my-ＳＯＴＥＲＩＸ-phrase-9",
])
def test_compatibility_homoglyphs_do_not_hide_a_context_word(password):
    """casefold() folds case but not NFKC; these read as the banned word to a human."""
    assert find_context_word(password) is not None


def test_a_compatibility_homoglyph_does_not_hide_the_username():
    assert contains_username("anderｓon-2026", "anderson") is True


@pytest.mark.parametrize("password", [
    "silver12silver1",       # the 2-period case, one character shorter
    "hunter22hunter2",
    "dragon12dragon1",
    "147258369147258",       # numeric-keypad column walk, repeated
])
def test_a_truncated_final_repeat_does_not_hide_the_padding(password):
    assert is_repeated_pattern(password) is True


@pytest.mark.parametrize("password", [
    "789456123789456",       # numpad rows
    "741852963741852",       # numpad columns
])
def test_numeric_keypad_walks_are_rejected(password):
    assert is_keyboard_walk(password) or is_repeated_pattern(password)


@pytest.mark.parametrize("password", [
    "couscous!@#$%^&*",      # stripped form "couscous" has period 4 — but 8 symbols carry entropy
    "chowchow--------",
    "bonbon-Xq93$mZ!v",
])
def test_stripping_does_not_invent_a_repetition_that_is_not_in_the_password(password):
    """The stripped form only counts as "the secret" when it alone clears the minimum.
    Otherwise a user sees "repeated pattern" for a repetition they cannot see."""
    assert is_repeated_pattern(password) is False
    assert validate_password_strength(password) is None
