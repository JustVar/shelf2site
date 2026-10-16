"""Structural password rules for the long-password regime.

A 15-character minimum invites a specific failure: passwords that are long but
trivially guessable — "aaaaaaaaaaaaaaa", "123456789012345", "qwertyuiopasdfgh",
"shelf2site-shelf2site". The breach blocklist cannot catch these, because only ~5.5k
of its entries are long enough to be consulted at all.

These are NOT character-class composition rules (NIST SP 800-63B Rev 4 advises
against "must contain a digit"). They reject *structure*: repetition, sequences,
keyboard walks, and context-specific words.

Every rule is applied where a password is SET, never where it is verified — the
same seam as the bcrypt 72-byte cap, and for the same reason: an existing account
whose password predates a rule must keep being able to log in.

Design bias: a false positive here silently locks a user out of a passphrase they
believe is strong, so each rule matches the WHOLE password (sequences, walks) or a
whole configured word (context words). A passphrase that merely *contains* "abc",
"qwe" or "sot" passes.

Two asymmetries were settled by measuring an adversarial corpus rather than by
argument, and they are the reason this module is not three lines of `in`:

  * Separators are STRIPPED before the structural checks (repetition, sequence,
    walk) and NOT before the context-word check. Stripping closes real bypasses
    ("qwertyuiop-asdfghjkl", "sunshine-sunshine"), but if applied to the word
    check it would make "compass-wordsmith-42" contain "password".

  * The username is matched on letter boundaries; the configured words are matched
    as plain substrings. A username is an arbitrary human name that turns up inside
    ordinary English -- "grace" in "disgraceful", "roman" in "romance", "logan" in
    "slogan" -- so a plain substring test rejects good passphrases. The configured
    words are product terms, where the embedded form ("myassettrackerlogin9") is
    exactly what we want to catch and a boundary test would miss it.
"""

import re
import unicodedata

from .config import settings

# Only context words at least this long are enforced. Below it, a word would
# reject a large share of ordinary English (and a 3-letter username would be
# unusable). Configurable, but 5 is the floor this was reasoned about at.
CONTEXT_WORD_MIN_LEN = settings.PASSWORD_CONTEXT_WORD_MIN_LEN

# A password with no more distinct characters than this is a repeated pattern by
# any reasonable reading, even when it has no exact period ("aaaaaaaaaaaaaab").
MAX_TRIVIAL_DISTINCT_CHARS = 2

# A repetition must cover at least one and a half periods, and at least this many
# characters of the second one. Without it, dropping a single trailing character hides
# the padding: "silver12silver12" is caught but "silver12silver1" would not be.
MIN_REPEAT_TAIL = 3

# QWERTY walks. A password is rejected when it is a contiguous segment of one of
# these (or of its reverse) — that is, when the whole password IS the walk.
_KEYBOARD_WALKS = (
    # physical rows
    "`1234567890-=",
    "qwertyuiop[]\\",
    "asdfghjkl;'",
    "zxcvbnm,./",
    # rows read straight through, the way a long "random" mash is actually typed
    "qwertyuiopasdfghjklzxcvbnm",
    "1234567890qwertyuiopasdfghjklzxcvbnm",
    # the classic zigzag and diagonal patterns
    "1q2w3e4r5t6y7u8i9o0p",
    "1qaz2wsx3edc4rfv5tgb6yhn7ujm8ik,9ol.0p;/",
    # columns, top-to-bottom then bottom-to-top
    "qazwsxedcrfvtgbyhnujmik,ol.p;/",
    "zaqxswcdevfrbgtnhymju,ki.lo/;p",
    # numeric keypad: rows read down, columns read across, and the two diagonals
    "789456123",
    "741852963",
    "147258369",
    "159357",
)

# Ascending runs. Digits are tripled so a cyclic wrap ("890123456789012") is still
# a contiguous segment. Reverses are added below for the descending case.
_SEQUENCES = (
    "0123456789" * 3,
    "abcdefghijklmnopqrstuvwxyz",
)


def _with_reverses(strings: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(s for base in strings for s in (base, base[::-1]))


_WALK_HAYSTACKS = _with_reverses(_KEYBOARD_WALKS)
_SEQUENCE_HAYSTACKS = _with_reverses(_SEQUENCES)

_NON_ALNUM = re.compile(r"[^0-9a-z]+")

# A separator-stripped form shorter than this is not worth testing: it carries too
# little of the original, and an EMPTY string is a substring of every haystack,
# which would reject a symbol-only password outright.
MIN_STRIPPED_LEN = 8


def fold(text: str) -> str:
    """Casefold, after NFKC-normalizing compatibility characters to their ASCII twins.

    casefold() alone folds case but not compatibility forms, so the fullwidth
    "ｐａｓｓｗｏｒｄ" would not contain the ASCII "password" and would sail past the
    context-word check while reading as the banned word to any human.

    NFKC does not fold homoglyphs from other scripts: a Cyrillic "а" in "pаssword"
    still evades. That is a known, documented gap (see docs/PASSWORD_POLICY.md).
    """
    return unicodedata.normalize("NFKC", text).casefold()


def _variants(password: str) -> tuple[str, ...]:
    """The folded password, plus its separator-stripped form when meaningful.

    Structural rules run over both, so "qwertyuiop-asdfghjkl" cannot hide a walk
    behind punctuation.

    An empty password yields NO variants: "" is a substring of every haystack, so an
    empty string would otherwise report as a keyboard walk. The length check makes that
    unreachable through validate_password_strength, but these predicates are public.
    """
    text = fold(password)
    if not text:
        return ()
    stripped = _NON_ALNUM.sub("", text)
    if stripped != text and len(stripped) >= MIN_STRIPPED_LEN:
        return (text, stripped)
    return (text,)


def _repeat_variants(password: str) -> tuple[str, ...]:
    """Variants for the repetition rule only.

    The stripped form counts here only when it alone clears the length minimum — that
    is, when it could be the whole secret. Otherwise stripping invents a repetition
    that is not in the password the user typed: "couscous!@#$%^&*" strips to "couscous",
    whose period is 4, and the eight symbols carrying real entropy vanish. The user
    would see "Password is a repeated pattern" and have no way to see why.
    """
    text = fold(password)
    if not text:
        return ()
    stripped = _NON_ALNUM.sub("", text)
    if stripped != text and len(stripped) >= settings.PASSWORD_MIN_LENGTH:
        return (text, stripped)
    return (text,)


def _minimal_period(text: str) -> int:
    """Smallest p such that text[i] == text[i % p] for every i. len(text) when aperiodic."""
    n = len(text)
    for p in range(1, n):
        if all(text[i] == text[i % p] for i in range(p, n)):
            return p
    return n


def _is_repetition(text: str) -> bool:
    if len(set(text)) <= MAX_TRIVIAL_DISTINCT_CHARS:
        return True
    period = _minimal_period(text)
    if period >= settings.PASSWORD_MIN_LENGTH:
        return False
    # One and a half periods, and at least MIN_REPEAT_TAIL characters of the second.
    return len(text) >= period + max((period + 1) // 2, MIN_REPEAT_TAIL)


def is_repeated_pattern(password: str) -> bool:
    """True when the password is a short unit repeated to reach the length minimum.

    Two ways in:
      1. At most MAX_TRIVIAL_DISTINCT_CHARS distinct characters.
      2. It repeats with a period shorter than the length minimum, covering at least
         one and a half periods — i.e. the secret the user actually chose is shorter
         than the minimum, and they padded it by repeating.

    Requiring only one and a half periods, rather than two, is what catches the
    truncated tail: "silver12silver1" is the same 8-character secret as
    "silver12silver12", one character shorter. Requiring *more* than one is what keeps
    the rule off ordinary passphrases: "correct-horse-c" has a minimal period of 14
    (its last character happens to equal its first) but only 1.07 periods, and at
    period 14 the rule demands 21 characters before it fires.
    """
    return any(_is_repetition(v) for v in _repeat_variants(password))


def is_sequence(password: str) -> bool:
    """True when the WHOLE password is an ascending or descending run of digits or letters."""
    return any(v in haystack for v in _variants(password) for haystack in _SEQUENCE_HAYSTACKS)


def is_keyboard_walk(password: str) -> bool:
    """True when the WHOLE password is a contiguous segment of a known QWERTY walk."""
    return any(v in haystack for v in _variants(password) for haystack in _WALK_HAYSTACKS)


def enforced_context_words() -> set[str]:
    """The configured context words, minus anything too short to be safe to match."""
    return {
        fold(w) for w in settings.PASSWORD_CONTEXT_WORDS
        if len(w) >= CONTEXT_WORD_MIN_LEN
    }


def find_context_word(password: str) -> str | None:
    """Return the configured context word the password contains, or None.

    Matching is a plain substring test on the casefolded password. Separators are
    deliberately NOT stripped: stripping them would make "compass-wordsmith-42"
    contain "password", rejecting a perfectly good passphrase.

    The username is deliberately NOT handled here — it needs boundary matching, and
    folding it into this set would silently give it plain-substring semantics. Use
    contains_username().
    """
    text = fold(password)
    # Longest first, so the message names the most specific word it matched.
    for word in sorted(enforced_context_words(), key=len, reverse=True):
        if word in text:
            return word
    return None


def contains_username(password: str, username: str | None) -> bool:
    """True when the password uses the account's username as a standalone word.

    Bounded by letters on both sides, so "grace" matches "grace-2026" and "my.grace"
    but not "disgraceful". Usernames are arbitrary names that occur inside ordinary
    English; a plain substring test measurably rejects good passphrases ("roman" in
    "romance", "logan" in "slogan", "carol" in "carolina").

    Checked against the separator-stripped form too, so "ander-son-2026" does not hide
    the username "anderson" behind a hyphen. Stripping removes only non-letters, which
    can destroy a letter boundary but never create one, so it adds no false positives.
    """
    if not username:
        return False
    folded = fold(username)
    if len(folded) < CONTEXT_WORD_MIN_LEN:
        return False
    pattern = rf"(?<![^\W\d_]){re.escape(folded)}(?![^\W\d_])"
    return any(re.search(pattern, v) for v in _variants(password))


def check_composition(password: str, username: str | None = None) -> str | None:
    """Return a friendly, specific error message, or None when the password passes."""
    if contains_username(password, username):
        return "Password must not contain your username."

    word = find_context_word(password)
    if word:
        return f"Password must not contain the word '{word}'."

    if is_repeated_pattern(password):
        return "Password is a repeated pattern. Use a mix of unrelated words."

    if is_sequence(password):
        return "Password is a simple sequence of letters or numbers."

    if is_keyboard_walk(password):
        return "Password is a keyboard pattern. Avoid runs of adjacent keys."

    return None
