"""Decode routing table for /api/receive/scan (SCANNER_AUDIT §4, approved design).

Pure classification — no DB access here. `preprocess()` normalizes the raw
decode (whitespace/control strip, GS1-128 extraction); `classify()` runs the
12-rule table on the uppercased value and returns the class key. The lookups
and guidance strings live with the endpoint in receiving.py, so every scan
surface (receive page, quick mode, fulfillment scan-to-find) gets the same
routing by construction.

Two faithful-implementation notes against the §4 table:
  * Rule 8 (12-hex MAC-vs-serial ambiguity) requires at least one A-F digit —
    otherwise rule 11's `^\\d{12}$` row (UPC-A) would be unreachable, and a
    pure-digit consumer barcode is far likelier a UPC than a MAC.
  * Rule 11 accepts 12-15 digits (not just 12/15): EAN-13 and GTIN-14
    consumer codes must land on the "product/shipping code" guidance per the
    §8 bench expectation, not fall through to a generic serial miss.
"""
import re

# GS1-128 application identifiers we extract. Fixed-length AIs consume
# exactly their payload; variable-length AIs run to the next GS (\x1d) or
# end of string. Anything unknown stops the parse (rest treated opaque).
_GS1_FIXED = {"00": 18, "01": 14, "11": 6, "13": 6, "15": 6, "17": 6}
_GS1_VARIABLE = {"10": 20, "21": 20, "240": 30}

GS = "\x1d"


def _parse_gs1(payload: str) -> dict:
    """Parse an AI stream (bare or parenthesized). Returns {} if nothing parses."""
    out = {}
    s = payload
    while s:
        s = s.lstrip(GS)
        if not s:
            break
        m = re.match(r"^\((\d{2,4})\)", s)
        if m:
            ai, s = m.group(1), s[m.end():]
        else:
            ai = None
            for cand in sorted(set(_GS1_FIXED) | set(_GS1_VARIABLE), key=len, reverse=True):
                if s.startswith(cand):
                    ai, s = cand, s[len(cand):]
                    break
            if ai is None:
                break  # unknown AI — stop, keep what we have
        if ai in _GS1_FIXED:
            n = _GS1_FIXED[ai]
            out[ai], s = s[:n], s[n:]
        else:
            n = _GS1_VARIABLE.get(ai, 20)
            end = s.find(GS)
            # parenthesized streams delimit with the next "(" instead of GS
            paren = s.find("(")
            if end == -1 or (paren != -1 and paren < end):
                end = paren
            chunk = s if end == -1 else s[:end]
            out[ai], s = chunk[:n], s[len(chunk):]
    return out


def preprocess(raw: str) -> tuple[str, dict]:
    """Strip whitespace/control chars; detect + unwrap GS1-128.

    Returns (value_to_classify, gs1) where gs1 is {} for non-GS1 scans and
    otherwise maps extracted AIs: 'serial' (AI 21), 'gtin' (AI 01),
    'sscc' (AI 00) plus the raw AI dict under 'ais'.
    """
    s = "".join(ch for ch in (raw or "") if ch == GS or ord(ch) >= 32).strip()
    gs1_body = None
    if s.startswith("]C1"):
        gs1_body = s[3:]
    elif GS in s or re.match(r"^\(\d{2,4}\)", s):
        gs1_body = s
    if gs1_body is not None:
        ais = _parse_gs1(gs1_body)
        if ais:
            gs1 = {"ais": ais}
            if ais.get("21"):
                gs1["serial"] = ais["21"].strip()
            if ais.get("01"):
                gs1["gtin"] = ais["01"]
            if ais.get("00"):
                gs1["sscc"] = ais["00"]
            # An SSCC drives classification in its bare-label form (AI "00"
            # + 18 digits) so rule 4 matches it exactly like a direct scan.
            value = (gs1.get("serial")
                     or ("00" + gs1["sscc"] if gs1.get("sscc") else None)
                     or gs1.get("gtin") or s)
            return value.strip(), gs1
    return s, {}


# ── the 12-rule table (§4) — evaluated in order on the UPPERCASED value ──────

_MAC_SEPARATED = re.compile(r"^([0-9A-F]{2}[:-]){5}[0-9A-F]{2}$")
_MAC_DOTTED = re.compile(r"^[0-9A-F]{4}\.[0-9A-F]{4}\.[0-9A-F]{4}$")
_UUID = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
_UPS = re.compile(r"^1Z[0-9A-Z]{16}$")
_SSCC = re.compile(r"^00\d{18}$")
_LONG_DIGITS = re.compile(r"^\d{20,22}$")
_ORDER = re.compile(r"^(SO|AT)-\d{4,}$")  # AT- numbers predate the Shelf2Site rename
_UNIT_PN = re.compile(r"^(PVA|EDGE|E2C)[A-Z0-9-]*-\d{5,6}$")
_SKU = re.compile(r"^(PVA|EDGE|E2C)[A-Z0-9]*-[A-Z0-9-]+$")
_HEX12 = re.compile(r"^[0-9A-F]{12}$")
_QNAP = re.compile(r"^Q[A-Z0-9]{9,}$")
_AMBIG_DIGITS = re.compile(r"^\d{12,15}$")


def classify(value: str) -> str:
    """Return the routing class for one preprocessed scan value."""
    v = (value or "").strip().upper()
    if not v:
        return "empty"
    if _MAC_SEPARATED.match(v) or _MAC_DOTTED.match(v):
        return "mac"
    if _UUID.match(v):
        return "uuid"
    if _UPS.match(v):
        return "tracking"
    if _SSCC.match(v) or _LONG_DIGITS.match(v):
        return "tracking"
    if _ORDER.match(v):
        return "order_number"
    if _UNIT_PN.match(v):
        return "unit_pn"
    if _SKU.match(v):
        return "sku"
    if _HEX12.match(v) and not v.isdigit():
        return "hex12"
    if v.startswith("USCF"):
        return "uscf_serial"
    if _QNAP.match(v) and v.isalnum():
        return "qnap_candidate"
    if _AMBIG_DIGITS.match(v):
        return "ambiguous_digits"
    if 3 <= len(v) <= 100:
        return "serial"
    return "unclassified"


def mac_from_bare_hex(v: str) -> str:
    """AABBCCDDEEFF -> AA:BB:CC:DD:EE:FF (caller guarantees 12 hex chars)."""
    v = v.upper()
    return ":".join(v[i:i + 2] for i in range(0, 12, 2))
