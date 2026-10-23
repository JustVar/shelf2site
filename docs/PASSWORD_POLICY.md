# Password policy

What the app enforces when a password is **set**, why, and what it deliberately does not catch.

Everything below applies at *set* time only — `change-password` and admin *create user*.
Nothing is enforced at *verify* time, so a rule added tomorrow can never lock out an account
whose password was set today. (This is not theoretical: a verify-time 72-byte check would have
locked out anyone whose stored hash was of a truncated password. See `app/auth.py`.)

## The rules, in the order they fire

| # | Rule | Where | Message |
|---|---|---|---|
| 1 | at least `PASSWORD_MIN_LENGTH` (15) characters, **measured after `.strip()`** | `app/auth.py` | "Password must be at least 15 characters." |
| 2 | at most 72 **bytes** (bcrypt truncates silently past this) | `app/auth.py` | "Password is too long — use at most 72 characters." |
| 3 | not in the offline breached-password blocklist | `app/password_blocklist.py` | "This password has appeared in known breaches…" |
| 4 | does not contain the account's **username** as a word | `app/password_rules.py` | "Password must not contain your username." |
| 5 | does not contain a configured **context word** | `app/password_rules.py` | "Password must not contain the word 'shelf2site'." |
| 6 | not a **repeated pattern** | `app/password_rules.py` | "Password is a repeated pattern…" |
| 7 | not a pure **sequence** | `app/password_rules.py` | "Password is a simple sequence…" |
| 8 | not a **keyboard walk** | `app/password_rules.py` | "Password is a keyboard pattern…" |

Rules 1–3 are NIST SP 800-63B Rev 4. There are no character-class rules ("must contain a
digit") — NIST advises against them. Rules 4–8 exist because a 15-character *minimum* invites
a 15-character *pattern*: `aaaaaaaaaaaaaaa`, `qwertyuiopasdfgh`, `shelf2site-shelf2site`. The breach
list cannot help there, because only its long entries are ever consulted (see below).

## The blocklist is filtered by length at load

The file on disk holds **939,466** entries. Only those at least `PASSWORD_MIN_LENGTH` long are
loaded into memory — **5,532** at a 15-character minimum. A shorter entry can never be the
answer to `is_blocked()`, because rule 1 rejects the password before rule 3 runs. Filtering
costs no coverage and drops roughly 385 MB across the six gunicorn workers.

Because the entries are filtered by length, **rule 1 must measure the same string the lookup
will see**. `is_blocked()` normalizes with `.strip()`, so the minimum-length check does too.
Otherwise `"monkey123      "` (a nine-character secret padded to fifteen) would clear the
minimum and then miss the `monkey123` entry, which the loader had already dropped. That
regression was introduced by the length filter and caught by adversarial review — it is
pinned by `test_whitespace_padding_cannot_smuggle_a_short_secret_past_the_minimum`.

The filter reads `PASSWORD_MIN_LENGTH` at startup, so **lowering the minimum and restarting
re-activates the shorter entries with no file regeneration**. Startup logs the split:

```
Password blocklist: 5,532 of 939,466 entries active at min length 15 (from data/security/password-blocklist.txt)
```

Absent or unreadable file ⇒ empty set, a WARNING, and the check fails open. Length is still
enforced. `is_blocked()` is therefore **not** a general "was this ever breached" oracle — do
not call it as one.

## Two asymmetries, both settled by measurement

These look like inconsistencies. They are not; each was chosen after running an adversarial
corpus of 175 passwords (generated blind to the implementation) through both options.

**Separators are stripped for rules 6–8, and not for rule 5.**
Stripping closes real bypasses — `qwertyuiop-asdfghjkl`, `qazwsx-edcrfv-tgb`,
`sunshine-sunshine`, `pass-word-pass-word` all slip through without it. But stripping the
context-word check would splice `compass-wordsmith-42` into `compasswordsmith42`, which
contains `password`, rejecting a perfectly strong passphrase.

For the **repetition** rule specifically, the stripped form counts only when it alone clears
the length minimum — i.e. when it could plausibly *be* the whole secret. `couscous!@#$%^&*`
strips to `couscous`, whose period is 4; without this guard the eight symbols carrying real
entropy vanish and the user is told "Password is a repeated pattern" about a repetition they
cannot see.

**The username is matched on letter boundaries; context words are matched as plain substrings.**
A username is an arbitrary human name that turns up inside ordinary English. A plain substring
test rejects `disgraceful…` for user *grace*, `romance…` for *roman*, `slogan…` for *logan*,
`carolina…` for *carol*, `immigrant…` for *grant*, `chamber…` for *amber* — six strong
passphrases, all measured. Boundary matching still catches `grace-2026`, `my.grace.x` and
`ander-son-2026` (the stripped form restores the split username). Context words get the
opposite treatment because the embedded form is exactly the attack: `myassettrackerlogin9`
has no boundary, and must still be rejected.

## What a "repeated pattern" means

Not "has a repeating prefix" — `chachacha-samba-night-42` is fine. The password is rejected
when the secret the user actually chose is **shorter than the minimum and padded by repeating
it**: its minimal period is under `PASSWORD_MIN_LENGTH` *and* it spans at least one and a half
periods (with at least 3 characters of the second). So:

- `silver12silver12` — an 8-character secret in a 16-character coat → rejected
- `silver12silver1` — the same secret, one character shorter → also rejected. Requiring *two*
  full periods would have missed it; dropping one trailing character was a complete bypass.
- `abcdefghijklmno` × 2 — a 15-character secret, which meets the policy → allowed
- `correct-horse-c` — minimal period 14, but only 1.07 periods; at period 14 the rule needs
  21 characters before it fires → allowed

Also rejected: two or fewer distinct characters (`aaaaaaaaaaaaaab`).

## Known gaps (accepted, not oversights)

**Misses** — weak passwords the rules let through:

- **Leetspeak** of a context word: `P@ssw0rdForWork1`, `S0terix2024Rocks`, `@ssettr@cker123`,
  `j0hnsmith-secure1`. Digits and symbols are not folded to letters.
- **Mixed-class sequences**: `0123456789abcdef`, `abcdefghij123456`. Rules 7–8 require the
  whole password to be one run of one class.
- **Cross-script homoglyphs**: a Cyrillic `а` (U+0430) in `pаssword-mountain42` reads as the
  banned word but is not folded. Matching is NFKC-normalized, which handles *compatibility*
  characters — fullwidth `ｐａｓｓｗｏｒｄ` **is** caught — but not confusables from another script.
- **Doubled-key rows**: `qqwweerrttyyuuii` is a keyboard row typed twice per key. It is
  neither a contiguous walk segment nor periodic.

**False positives** — strong passwords the rules reject:

- `go-green-shelf2sites-basketball-99` and `i-hate-remembering-passwords-42`. Both contain a
  configured word as a plain substring (`shelf2site` inside `shelf2sites`, `password` inside
  `passwords`). This is inherent to "reject passwords *containing* a context word". The
  rejection names the offending word, so the user can fix it in one try.

Closing the leetspeak and cross-script gaps means a character-folding table applied before
rule 5 — self-contained, and left out here only to keep this change to what was approved.
Catching doubled-key rows means replacing the fixed walk list with an adjacency-graph
detector: a larger change, and the weakest of the three in expected value.

## Configuration

| Setting | Default | Notes |
|---|---|---|
| `PASSWORD_MIN_LENGTH` | `15` | also selects which blocklist entries load |
| `PASSWORD_BLOCKLIST_PATH` | `data/security/password-blocklist.txt` | bind-mounted from the host, not in git |
| `PASSWORD_CONTEXT_WORDS` | `shelf2site,assettracker,asset-tracker,password` | comma-separated; grow it freely |
| `PASSWORD_CONTEXT_WORD_MIN_LEN` | `5` | words shorter than this are never enforced |

A context word below the minimum length is silently ignored — a 3-letter word would reject a
large share of ordinary English, and a 3-letter username would make the account unusable.

## Paths that do NOT validate

`POST /api/admin/reset-password/{id}` generates a random 16-character password and hashes it
without validation. That is intentional: it is machine-generated, single-use, and the account
is flagged `must_change_password`, so the user's real password does go through every rule.
`app.auth.create_user()` (used by `scripts/create_admin_user.py`) likewise does not validate.

## Running the tests

```bash
docker compose exec -T app python -m pytest tests/test_password_rules.py -q
```

Every "must pass" case in that file is a password some plausible implementation of this spec
would wrongly reject. They are the specification, not decoration — do not delete one to make a
new rule green.
