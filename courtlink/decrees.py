"""Parse presidential decrees appointing federal judges ("О назначении судей федеральных судов").

The decree text is a run of headings and names:

    Назначить на шестилетний срок полномочий:
    председателем Абаканского городского суда Республики Хакасия
    ИВАНОВА Ивана Петровича – заместителя председателя этого суда;
    ...
    Назначить:
    судьями Верховного суда Республики Башкортостан
    ПЕТРОВУ Анну Сергеевну – судью Кировского районного суда города Уфы Республики Башкортостан;

parse_decree(text) -> list of appointments: position (chair | deputy_chair | judge), court (genitive, as written),
surname (accusative, as written), first, patronymic, prev (the text after the dash: previous post, if any).
Names are in the accusative; nominative_candidates() gives the surname forms to compare with case cards.
The format was written from the published decrees' layout and must be checked on one real decree before a full run
(appointments.py --check FILE prints what it parsed).
"""
from __future__ import annotations

import re

from .translit import skeleton

NAME = re.compile(r"\b([А-ЯЁ]{2,}(?:-[А-ЯЁ]{2,})?)\s+([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+"
                  r"([А-ЯЁ][а-яё]+(?:\s+(?:оглы|кызы|угли|улы))?)")
POS = re.compile(r"(заместител(?:ем|ями)\s+председателя|председател(?:ем|ями)|судь(?:ей|ями))\s+", re.I)
DATE = re.compile(r"(?:от\s+)?(\d{1,2})[.\s]+(\d{2}|января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
                  r"[.\s]+(\d{4})\s*(?:г(?:ода|\.)?)?\s*№\s*(\d+)", re.I)
MONTHS = {m: i for i, m in enumerate(["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
                                      "октября", "ноября", "декабря"], 1)}
DASH = re.compile(r"^\s*[–—\-,]\s*")


def decree_meta(text: str) -> tuple[str, str]:
    """(date, number) of the decree itself: the date next to 'Указ', else the signature block at the end. Dates of
    laws cited in the preamble ('Закона ... от 26 июня 1992 г. № 3132-I') are skipped."""
    t = re.sub(r"\s+", " ", text or "")
    ms = [m for m in DATE.finditer(t) if not t[m.end(): m.end() + 2].startswith("-")
          and "закон" not in t[max(0, m.start() - 80): m.start()].lower()]
    if not ms:
        return "", ""
    head = [m for m in ms if "указ" in t[max(0, m.start() - 80): m.start()].lower()]
    d, mo, y, no = (head[0] if head else ms[-1]).groups()
    mo = MONTHS.get(mo.lower(), mo)
    return f"{y}-{int(mo):02d}-{int(d):02d}", no


def position_class(pos: str) -> str:
    p = pos.lower()
    return "deputy_chair" if p.startswith("заместител") else "chair" if p.startswith("председател") else "judge"


def parse_decree(text: str) -> list[dict]:
    t = re.sub(r"\s+", " ", text or "")
    names = [m for m in NAME.finditer(t) if not m.group(1) in ("РФ", "РОССИЙСКОЙ", "ФЕДЕРАЦИИ")]
    out, heading = [], None
    for i, m in enumerate(names):
        prev_end = names[i - 1].end() if i else 0
        gap = t[prev_end: m.start()]
        # the previous entry's "– previous post;" sits at the start of this gap
        if i:
            tail = re.split(r"[;]|\.\s", gap, maxsplit=1)[0]
            out[-1]["prev"] = DASH.sub("", tail).strip(" .;")
        head_zone = re.split(r"[;:]", gap)[-1]
        ps = list(POS.finditer(head_zone))
        if ps:
            h = ps[-1]
            court = head_zone[h.end():].strip(" ,.;:")
            heading = (position_class(h.group(1)), court)
        if not heading:
            continue
        out.append({"position": heading[0], "court": heading[1], "surname": m.group(1), "first": m.group(2),
                    "patronymic": m.group(3), "prev": ""})
    if names and out:
        tail = re.split(r"[;]|\.\s", t[names[-1].end():], maxsplit=1)[0]
        out[-1]["prev"] = DASH.sub("", tail).strip(" .;")
    return out


def female(patronymic: str) -> bool:
    return bool(re.search(r"(вну|чну|кызы)$", patronymic.lower()))


def nominative_candidates(surname_acc: str, patronymic_acc: str) -> set[str]:
    s = surname_acc.capitalize() if "-" not in surname_acc else "-".join(x.capitalize() for x in surname_acc.split("-"))
    lo = s.lower()
    c = {s}
    if female(patronymic_acc):
        if lo.endswith("ую"):
            c.add(s[:-2] + "ая")
        if lo.endswith("юю"):
            c.add(s[:-2] + "яя")
        if lo.endswith("у"):
            c.add(s[:-1] + "а")
    else:
        if lo.endswith(("ого", "его")):
            c |= {s[:-3] + "ий", s[:-3] + "ой", s[:-3] + "ый"}
        if lo.endswith("а"):
            c.add(s[:-1])
        if lo.endswith("я"):
            c |= {s[:-1] + "ь", s[:-1] + "й"}
    return c


STOP = {"суд", "суда", "судов", "город", "города", "г", "области", "края", "республики", "автономного", "округа",
        "этого", "района", "федерации", "российской"}


ENDINGS = sorted("ого его ому ему ой ий ый ая ое ые ых их ую юю ом ем а я ы и у ю е о ь".split(), key=len, reverse=True)


def stem(w: str) -> str:
    """Strip one case/adjective ending (genitive in decrees, nominative on court sites), then cap at 6 letters."""
    for e in ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            w = w[: -len(e)]
            break
    return w[:6]


def court_tokens(name: str) -> set[str]:
    n = re.sub(r"\bг\.\s*", "город ", (name or "").lower())
    toks = re.findall(r"[а-яё0-9]+", n)
    return {stem(w) for w in toks if w not in STOP and len(w) > 2}


def court_similarity(a: str, b: str) -> float:
    A, B = court_tokens(a), court_tokens(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))  # Dice: both names must be mostly explained


def court_level(text: str) -> float:
    t = (text or "").lower()
    if "верховного суда российской федерации" in t:
        return 4
    if "кассационн" in t or "апелляционн" in t:
        return 3
    if re.search(r"областн|краев|верховного суда республики|суда автономн|автономной области|окружного военного|флотского военного|"
                 r"городского суда (?:москвы|санкт-петербурга|севастополя)|московского городского|санкт-петербургского городского", t):
        return 2
    if "арбитраж" in t:
        return 0
    if "миров" in t or "судебного участка" in t:
        return 0.5
    return 1


def name_key(surname: str, first: str, patronymic: str) -> tuple[str, str, str]:
    return skeleton(surname), skeleton(first)[:1], skeleton(patronymic)[:1]
