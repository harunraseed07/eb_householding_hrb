"""String similarity and name helpers, written without extra dependencies.

A POC should not pull a heavyweight record linkage library to prove the idea.
These are the three primitives real matching needs: a fuzzy string score, a
phonetic key for blocking, and a nickname table so BOB and ROBERT compare as
the same given name rather than as a near miss.
"""

from __future__ import annotations

import re
import unicodedata


# ---------------------------------------------------------------------------
# Jaro-Winkler
# ---------------------------------------------------------------------------
def jaro(a: str, b: str) -> float:
    """Jaro similarity in [0, 1]. 1.0 means identical."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0

    window = max(la, lb) // 2 - 1
    if window < 0:
        window = 0

    a_flags = [False] * la
    b_flags = [False] * lb
    matches = 0

    for i, ch in enumerate(a):
        lo = max(0, i - window)
        hi = min(i + window + 1, lb)
        for j in range(lo, hi):
            if not b_flags[j] and b[j] == ch:
                a_flags[i] = b_flags[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    # Count transpositions among matched characters, in order.
    transpositions = 0
    k = 0
    for i in range(la):
        if not a_flags[i]:
            continue
        while not b_flags[k]:
            k += 1
        if a[i] != b[k]:
            transpositions += 1
        k += 1
    transpositions //= 2

    m = float(matches)
    return (m / la + m / lb + (m - transpositions) / m) / 3.0


def jaro_winkler(a: str, b: str, prefix_scale: float = 0.1) -> float:
    """Jaro with a bonus for a shared prefix. Favours real name variants."""
    score = jaro(a, b)
    if score <= 0.7:
        return score
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca != cb:
            break
        prefix += 1
    return score + prefix * prefix_scale * (1.0 - score)


# ---------------------------------------------------------------------------
# Soundex, used only as a blocking key (recall), never as a score
# ---------------------------------------------------------------------------
_SOUNDEX_MAP = {
    **dict.fromkeys("BFPV", "1"),
    **dict.fromkeys("CGJKQSXZ", "2"),
    **dict.fromkeys("DT", "3"),
    **dict.fromkeys("L", "4"),
    **dict.fromkeys("MN", "5"),
    **dict.fromkeys("R", "6"),
}


def soundex(value: str) -> str:
    value = re.sub(r"[^A-Z]", "", (value or "").upper())
    if not value:
        return ""
    head = value[0]
    codes = [_SOUNDEX_MAP.get(ch, "") for ch in value]
    out = [head]
    previous = codes[0]
    for ch, code in zip(value[1:], codes[1:]):
        if code and code != previous:
            out.append(code)
        if ch not in "HW":
            previous = code
        if len(out) == 4:
            break
    return "".join(out).ljust(4, "0")


# ---------------------------------------------------------------------------
# Nicknames. Bi-directional: every alias maps to a canonical root.
# ---------------------------------------------------------------------------
_NICKNAME_GROUPS = [
    ("ROBERT", ["BOB", "BOBBY", "ROB", "ROBBIE", "BERT"]),
    ("WILLIAM", ["BILL", "BILLY", "WILL", "WILLIE", "LIAM"]),
    ("ELIZABETH", ["LIZ", "LIZZY", "BETH", "BETSY", "ELIZA", "LIBBY"]),
    ("MICHAEL", ["MIKE", "MICKEY", "MICK"]),
    ("RICHARD", ["RICK", "RICKY", "DICK", "RICH"]),
    ("JAMES", ["JIM", "JIMMY", "JAMIE"]),
    ("JOHN", ["JACK", "JOHNNY", "JON"]),
    ("JOSEPH", ["JOE", "JOEY"]),
    ("KATHERINE", ["KATHY", "KATE", "KATIE", "KAT", "CATHY", "CATHERINE"]),
    ("MARGARET", ["MAGGIE", "MEG", "PEGGY", "MARGE"]),
    ("SUSAN", ["SUE", "SUSIE", "SUZY"]),
    ("JENNIFER", ["JEN", "JENNY", "JENNIE"]),
    ("THOMAS", ["TOM", "TOMMY"]),
    ("CHRISTOPHER", ["CHRIS", "TOPHER"]),
    ("PATRICIA", ["PAT", "PATTY", "TRISH"]),
    ("DANIEL", ["DAN", "DANNY"]),
    ("ANTHONY", ["TONY", "ANT"]),
    ("STEPHEN", ["STEVE", "STEVEN", "STEVIE"]),
    ("EDWARD", ["ED", "EDDIE", "TED", "NED"]),
    ("DEBORAH", ["DEB", "DEBBIE", "DEBRA"]),
    ("NICHOLAS", ["NICK", "NICKY"]),
    ("MATTHEW", ["MATT", "MATTY"]),
    ("ANDREW", ["ANDY", "DREW"]),
    ("BARBARA", ["BARB", "BABS"]),
    ("THERESA", ["TERRY", "TERESA", "TESS"]),
    ("LAWRENCE", ["LARRY", "LAUREN"]),
    ("FRANCIS", ["FRANK", "FRANCES", "FRAN"]),
    ("GREGORY", ["GREG"]),
    ("TIMOTHY", ["TIM", "TIMMY"]),
    ("VINCENT", ["VINNY", "VINCE"]),
]

NICKNAME_ROOT: dict[str, str] = {}
for _root, _aliases in _NICKNAME_GROUPS:
    NICKNAME_ROOT[_root] = _root
    for _alias in _aliases:
        NICKNAME_ROOT[_alias] = _root

NICKNAMES_BY_ROOT: dict[str, list[str]] = {r: a for r, a in _NICKNAME_GROUPS}


def given_name_root(name: str) -> str:
    """Collapse a given name to its canonical root, e.g. BOB -> ROBERT."""
    key = re.sub(r"[^A-Z]", "", (name or "").upper())
    return NICKNAME_ROOT.get(key, key)


def names_are_nickname_equivalent(a: str, b: str) -> bool:
    ra, rb = given_name_root(a), given_name_root(b)
    return bool(ra) and ra == rb and (a or "").upper() != (b or "").upper()


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
_STREET_SUFFIX = {
    "STREET": "ST", "ST": "ST",
    "AVENUE": "AVE", "AVE": "AVE", "AV": "AVE",
    "ROAD": "RD", "RD": "RD",
    "DRIVE": "DR", "DR": "DR",
    "LANE": "LN", "LN": "LN",
    "BOULEVARD": "BLVD", "BLVD": "BLVD",
    "COURT": "CT", "CT": "CT",
    "PLACE": "PL", "PL": "PL",
    "TERRACE": "TER", "TER": "TER",
    "CIRCLE": "CIR", "CIR": "CIR",
    "HIGHWAY": "HWY", "HWY": "HWY",
    "PARKWAY": "PKWY", "PKWY": "PKWY",
    "SQUARE": "SQ", "SQ": "SQ",
}

_UNIT_WORDS = {
    "APARTMENT": "APT", "APT": "APT", "#": "APT",
    "UNIT": "UNIT", "SUITE": "STE", "STE": "STE",
    "FLOOR": "FL", "FL": "FL", "NUMBER": "APT", "NO": "APT",
}

_DIRECTIONS = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW",
    "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}


def strip_accents(value: str) -> str:
    if not value:
        return ""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )


def normalize_name(value: str) -> str:
    """Upper case, drop punctuation and suffixes, squeeze whitespace."""
    value = strip_accents(value or "").upper()
    value = re.sub(r"\b(JR|SR|III|II|IV|MR|MRS|MS|DR)\b\.?", " ", value)
    value = re.sub(r"[^A-Z\s'-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_address(value: str) -> str:
    """Normalize a street line so '12 Maple Street' == '12 MAPLE ST'."""
    value = strip_accents(value or "").upper()
    value = value.replace(".", " ").replace(",", " ")
    value = re.sub(r"[^A-Z0-9#\s]", " ", value)
    tokens = [t for t in value.split() if t]
    out = []
    for token in tokens:
        token = _DIRECTIONS.get(token, token)
        token = _STREET_SUFFIX.get(token, token)
        token = _UNIT_WORDS.get(token, token)
        out.append(token)
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def normalize_unit(value: str) -> str:
    value = normalize_address(value)
    value = re.sub(r"\b(APT|UNIT|STE|FL)\b", "", value)
    return re.sub(r"\s+", "", value)


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_email(value: str) -> str:
    value = (value or "").strip().lower()
    if "@" not in value:
        return ""
    local, _, domain = value.partition("@")
    # Gmail-style dot and plus handling, applied generally for the demo.
    local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}"


def normalize_postal(value: str) -> str:
    digits = digits_only(value)
    return digits[:5] if len(digits) >= 5 else digits


def address_key(street: str, unit: str, city: str, state: str, postal: str) -> str:
    """The grouping key for a standard household. Empty if evidence is thin."""
    street_n = normalize_address(street)
    postal_n = normalize_postal(postal)
    if not street_n or not postal_n:
        return ""
    return "|".join([
        street_n,
        normalize_unit(unit),
        normalize_name(city),
        (state or "").upper().strip(),
        postal_n,
    ])
