"""Judge name normalization and entity keys."""
from __future__ import annotations

import re

from .translit import cyr_to_lat, skeleton

TITLE_RE = re.compile(r"^(судья|председательствующий( судья)?|судья-докладчик|докладчик)\s*:?\s*", re.I)
FULL_RE = re.compile(r"^([А-ЯЁ][а-яё-]+)\s+([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)$")
INIT_RE = re.compile(r"^([А-ЯЁ][а-яё-]+)\s+([А-ЯЁ])\.\s*([А-ЯЁ])\.?$")
INIT_FIRST_RE = re.compile(r"^([А-ЯЁ])\.\s*([А-ЯЁ])\.\s*([А-ЯЁ][а-яё-]+)$")


def parse_judge(raw: str) -> dict:
    """-> {surname, first, patronymic, i1, i2, full, display}. Empty dict if unparseable."""
    raw = (raw or "").strip()
    marked = raw[:1] in "*~#"  # sudrf prefixes some judge names with '*' or '~'; kept as a flag
    s = TITLE_RE.sub("", raw.lstrip("*~# ").strip())
    alias = re.search(r"\(([^)]+)\)", s)  # 'Карапетян Екатерина Александровна (Кобякова)': former surname
    s = re.sub(r"\s*\([^)]*\)", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;")
    s = s.split(",")[0].strip()
    m = FULL_RE.match(s)
    if m:
        sur, fi, pa = m.groups()
        return {"surname": sur, "first": fi, "patronymic": pa, "i1": fi[0], "i2": pa[0], "full": True,
                "display": f"{sur} {fi} {pa}", "former_surname": alias.group(1).strip() if alias else "",
                "marked": marked}
    m = INIT_RE.match(s)
    if m:
        sur, i1, i2 = m.groups()
        return {"surname": sur, "first": "", "patronymic": "", "i1": i1, "i2": i2, "full": False,
                "display": f"{sur} {i1}.{i2}."}
    m = INIT_FIRST_RE.match(s)
    if m:
        i1, i2, sur = m.groups()
        return {"surname": sur, "first": "", "patronymic": "", "i1": i1, "i2": i2, "full": False,
                "display": f"{sur} {i1}.{i2}."}
    return {}


def judge_key(court_id: str, j: dict) -> str:
    """Stable ID per judge per court: <court>:<surname-latin>_<i1><i2>."""
    if not j:
        return ""
    sur = re.sub(r"[^a-z]", "", cyr_to_lat(j["surname"]).lower())
    ini = cyr_to_lat(j["i1"] + j["i2"]).lower()[:4]
    return f"{court_id}:{sur}_{ini}"


def person_key(j: dict) -> str:
    """Court-independent key, used for blocking against sanctions lists."""
    if not j:
        return ""
    return f"{skeleton(j['surname'])}|{skeleton(j['i1'])[:1]}{skeleton(j['i2'])[:1]}"
