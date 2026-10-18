"""Transliteration for matching OVD-Info Latin names against Cyrillic court records.

Two directions:
  cyr_to_lat()     deterministic, used to compare Cyrillic court-page names with OVD Latin names
  lat_to_cyr()     lossy, yields a few candidate spellings for surname searches on court sites
skeleton()         a loose comparison key that erases common romanization differences
"""
from __future__ import annotations

import itertools
import re

_C2L = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

CYR_RE = re.compile(r"[А-Яа-яЁё]")


def has_cyrillic(s: str) -> bool:
    return bool(CYR_RE.search(s or ""))


def cyr_to_lat(s: str) -> str:
    out = []
    for ch in (s or ""):
        lo = ch.lower()
        if lo in _C2L:
            t = _C2L[lo]
            out.append(t.capitalize() if ch.isupper() and t else t)
        else:
            out.append(ch)
    return "".join(out)


_SKEL_RULES = [
    (r"[''`ʹ]", ""),
    (r"shch|sch", "s"),
    (r"zh", "z"),
    (r"kh", "h"),
    (r"ts|tz", "c"),
    (r"ch", "c"),
    (r"sh", "s"),
    (r"(iy|yy|ij|yj|ii)$", "y"),
    (r"(iy|yy|ij|yj|ii)(?=\s)", "y"),
    (r"yu|iu|ju", "u"),
    (r"ya|ia|ja", "a"),
    (r"yo|jo", "e"),
    (r"ye|je", "e"),
    (r"j", "y"),
    (r"i", "y"),
    (r"w", "v"),
    (r"x", "ks"),
    (r"(.)\1", r"\1"),
]


def skeleton(s: str) -> str:
    """Loose key: transliterate if Cyrillic, lowercase, collapse romanization variants."""
    s = cyr_to_lat(s) if has_cyrillic(s) else (s or "")
    s = s.lower()
    s = re.sub(r"[^a-z\s'-]", " ", s)
    s = re.sub(r"[-\s]+", " ", s).strip()
    for pat, rep in _SKEL_RULES:
        s = re.sub(pat, rep, s)
    return s


# Latin to Cyrillic candidates. Each rule: (latin, [cyrillic options]); longest first.
_L2C = [
    ("shch", ["щ"]), ("sch", ["щ"]), ("zh", ["ж"]), ("kh", ["х"]), ("ts", ["ц"]), ("tz", ["ц"]),
    ("ch", ["ч"]), ("sh", ["ш"]), ("yu", ["ю"]), ("iu", ["ю"]), ("ya", ["я"]), ("yo", ["ё", "е"]),
    ("ye", ["е"]), ("iy", ["ий", "ый"]), ("yy", ["ый"]), ("ij", ["ий"]), ("y", ["ы", "й", "и"]),
    ("j", ["й"]), ("e", ["е", "э"]), ("a", ["а"]), ("b", ["б"]), ("v", ["в"]), ("g", ["г"]),
    ("d", ["д"]), ("z", ["з"]), ("i", ["и"]), ("k", ["к"]), ("l", ["л"]), ("m", ["м"]),
    ("n", ["н"]), ("o", ["о"]), ("p", ["п"]), ("r", ["р"]), ("s", ["с"]), ("t", ["т"]),
    ("u", ["у"]), ("f", ["ф"]), ("h", ["х"]), ("c", ["к"]), ("w", ["в"]), ("x", ["кс"]),
    ("q", ["к"]), ("'", ["ь"]),
]
_VOWELS = set("aeiouy")


def _choices(word: str) -> list[list[str]]:
    w = word.lower()
    i, slots = 0, []
    while i < len(w):
        for lat, opts in _L2C:
            if w.startswith(lat, i):
                prev = w[i - 1] if i else ""
                o = list(opts)
                if lat == "y":
                    # y after a vowel is usually й; word-final after a consonant is -ий/-ый (Kagarlitsky)
                    if prev in _VOWELS:
                        o = ["й", "ы"]
                    elif i + 1 == len(w):
                        o = ["ий", "ый", "и"]
                    else:
                        o = ["ы", "и"]
                if lat == "e":
                    o = ["э", "е"] if i == 0 else (["е", "э"] if prev in _VOWELS else ["е"])
                if lat == "ye":
                    o = ["е"] if i == 0 or prev in _VOWELS else ["ье", "е"]
                if lat in ("iy", "yy", "ij") and i + len(lat) != len(w):
                    o = ["ий"] if lat != "yy" else ["ый"]
                slots.append(o)
                i += len(lat)
                break
        else:
            slots.append([w[i]])
            i += 1
    return slots


def lat_to_cyr(word: str, limit: int = 4) -> list[str]:
    """Up to `limit` Cyrillic candidates, most likely first."""
    slots = _choices(word)
    out = []
    for combo in itertools.product(*slots):
        cand = "".join(combo)
        cand = "-".join(p[:1].upper() + p[1:] for p in cand.split("-"))
        if cand not in out:
            out.append(cand)
        if len(out) >= limit:
            break
    return out


def split_ovd_name(name: str) -> tuple[str, str]:
    """OVD-Info EN names are 'First Last'. Returns (first, last); last='' if only one token."""
    toks = [t for t in re.split(r"\s+", (name or "").strip()) if t]
    if len(toks) >= 2:
        return " ".join(toks[:-1]), toks[-1]
    return (toks[0] if toks else ""), ""
