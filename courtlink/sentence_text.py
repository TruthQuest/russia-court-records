"""Sentence extraction from free text: OVD-Info stories (English) and court acts or results (Russian).

parse_all(text) returns every sentence mention in order of appearance; the first is usually the first-instance
sentence and the last the most recent (after appeal). Each mention:
    kind      custodial | suspended | forced_labour | correctional_labour | restriction | compulsory_works |
              fine | acquittal | medical
    months    term in months (custodial, suspended, labour, restriction); None if not stated
    fine_rub  fine in roubles; None if none
    regime    colony regime when stated (general, strict, special, settlement, prison)
    phrase    the matched text, for checking
The parser is rule-based and conservative: a mention without a recognisable term keeps months=None rather than
guessing. Check it on a sample (sentences.py --sample) before relying on it.
"""
from __future__ import annotations

import re

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
           "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22,
           "twenty-three": 23, "twenty-four": 24, "twenty-five": 25, "a": 1, "an": 1, "half": 0.5,
           "один": 1, "одного": 1, "два": 2, "двух": 2, "три": 3, "трех": 3, "трёх": 3, "четыре": 4, "четырех": 4,
           "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11,
           "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
           "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20}
NUM = r"(\d+(?:[.,]\d+)?|[a-zа-яё\-]+)"


def _n(tok: str | None) -> float | None:
    if not tok:
        return None
    t = tok.lower().replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return WORDNUM.get(t)


# term: "6 years and 6 months", "six and a half years", "2.5 years", "10 months", "6 (шесть) лет 6 месяцев"
TERM_EN = re.compile(rf"{NUM}(?:\s+and\s+a\s+half)?[\s-]+years?(?:\s+(?:and\s+)?{NUM}\s+months?)?|{NUM}[\s-]+months?", re.I)
TERM_RU = re.compile(rf"{NUM}(?:\s*\([а-яё\s]+\))?\s+(?:год(?:а|у)?|лет)(?:\s+{NUM}(?:\s*\([а-яё\s]+\))?\s+месяц(?:а|ев)?)?"
                     rf"|{NUM}(?:\s*\([а-яё\s]+\))?\s+месяц(?:а|ев)?", re.I)
FINE = re.compile(r"(?:fine[d]?\s+(?:of\s+)?|штраф\w*\s+в\s+размере\s+)(?:RUB\s*)?([\d\s.,]+)\s*(million|thousand|тыс\w*|млн\w*)?\s*"
                  r"(?:roubles|rubles|руб|RUB)?", re.I)

KINDS = [  # order matters: the most specific first
    ("acquittal", re.compile(r"\bacquitt\w*|оправда\w*", re.I)),
    ("medical", re.compile(r"compulsory (?:psychiatric |medical )?treatment|psychiatric hospital|принудительн\w+ лечени\w+|принудительн\w+ мер\w* медицинского|психиатрическ\w+ стационар", re.I)),
    ("suspended", re.compile(r"suspended|conditional(?:ly)? sentence|probation|условн\w+|испытательн\w+ срок", re.I)),
    ("forced_labour", re.compile(r"forced labou?r|принудительн\w+ работ", re.I)),
    ("correctional_labour", re.compile(r"correctional labou?r|исправительн\w+ работ", re.I)),
    ("compulsory_works", re.compile(r"compulsory (?:community )?work|mandatory work|обязательн\w+ работ", re.I)),
    ("restriction", re.compile(r"restriction of (?:liberty|freedom)|restricted freedom|ограничени\w+ свободы", re.I)),
    ("custodial", re.compile(r"penal colony|prison|imprisonment|in custody|behind bars|colony|лишени\w+ свободы|колони\w+|тюрьм\w+", re.I)),
    ("fine", re.compile(r"\bfine[d]?\b|штраф", re.I)),
]
REGIME = re.compile(r"(general|strict|special|maximum)[\s-]+(?:security|regime)|settlement colony|колони\w+[\s-]+поселени\w+|"
                    r"(общего|строгого|особого) режима|отбыванием[^.;]{0,40}тюрьм\w+|serve[^.;]{0,30}in prison", re.I)
TRIGGER = re.compile(r"sentenced|\bfined\b|sentence of|(?:was given|received|handed (?:down|him|her))\s+(?:a |an |the )?"
                     r"(?:[\w-]+\s){0,4}?(?:sentence|years?|months?|fine)\b|acquitted|"
                     r"приговор\w*|назначи\w+\s+(?:наказани\w+|штраф\w*)|оправда\w+|осужд\w+|приговорил\w*", re.I)


def _months(seg: str) -> float | None:
    for rx in (TERM_EN, TERM_RU):
        for m in rx.finditer(seg):
            g = m.groups()
            txt = m.group(0).lower()
            if re.search(r"years?|год|лет", txt):
                y = _n(g[0])
                if y is None:
                    continue
                if "and a half" in txt:
                    y += 0.5
                return round(y * 12 + (_n(g[1]) or 0), 1)
            mo = _n(g[2])
            if mo is not None:
                return mo
    return None


def _fine(seg: str) -> float | None:
    m = FINE.search(seg)
    if not m:
        return None
    raw = m.group(1).strip().rstrip(".")
    if m.group(2) and re.fullmatch(r"\d+[.,]\d{1,2}", raw):  # "1,5 млн" / "1.5 million": decimal, not thousands
        raw = raw.replace(",", ".")
    else:
        raw = re.sub(r"[\s,]", "", raw)
    try:
        v = float(raw)
    except ValueError:
        return None
    mult = (m.group(2) or "").lower()
    if mult.startswith(("million", "млн")):
        v *= 1_000_000
    elif mult.startswith(("thousand", "тыс")):
        v *= 1_000
    return v if v >= 1000 else None


HALF = [(re.compile(r"\b(?:a|one) (?:year and a half|and a half years?)\b", re.I), "1.5 years"),
        (re.compile(r"\byear and a half\b", re.I), "1.5 years"),
        (re.compile(r"\bполтора\s+года\b", re.I), "1.5 года")]
REQUEST = re.compile(r"request|asked|demand|sought|seek|prosecutor|prosecution|просил|запрос|потребова|прокурор|гособвинител|обвинени", re.I)
ADMIN = re.compile(r"administrative|КоАП|административн", re.I)
CONTRAST = re.compile(r"although|but |while|whereas|asked|request|хотя|однако|просил|но ", re.I)
ABSENTIA = re.compile(r"in absentia|заочно", re.I)


def _kind(seg: str) -> str | None:
    """The penalty named first after the trigger; 'N years ... suspended/условно' in one clause is suspended."""
    found = sorted(((m.start(), i, k) for i, (k, rx) in enumerate(KINDS) for m in [rx.search(seg)] if m))
    if not found:
        return None
    pos, _, kind = found[0]
    if kind == "custodial":
        sm = KINDS[2][1].search(seg, pos)  # suspended
        if sm and sm.start() - pos < 80 and not CONTRAST.search(seg[pos: sm.start()]):
            return "suspended"
    return kind


def parse_all(text: str) -> list[dict]:
    out = []
    if not text:
        return out
    t = re.sub(r"\s+", " ", text)
    for rx, rep in HALF:
        t = rx.sub(rep, t)
    for m in TRIGGER.finditer(t):
        seg = t[m.start(): m.start() + 260]
        cut = re.search(r"(?<=[a-zа-яё)])\.\s+(?=[A-ZА-ЯЁ])", seg)  # stop at the end of the sentence
        if cut:
            seg = seg[: cut.start() + 1]
        before = re.split(r"[.;]\s", t[max(0, m.start() - 80): m.start()])[-1]  # same sentence only
        if REQUEST.search(before[-60:] + seg[:25]) and not re.match(r"sentenced|приговорил|осужд", m.group(0), re.I):
            continue  # a sentence the prosecution asked for, not one the court passed
        if ADMIN.search(before[-60:] + seg[:120]):
            continue  # administrative penalty, not a criminal sentence
        kind = _kind(seg)
        if not kind:
            continue
        months = None if kind in ("fine", "acquittal", "medical") else _months(seg)
        fine = _fine(seg)
        if kind == "custodial" and months is None and fine is not None and not re.search(r"colony|prison|лишени|колони", seg, re.I):
            kind = "fine"
        rg = REGIME.search(seg)
        out.append({"kind": kind, "months": months, "fine_rub": fine, "regime": (rg.group(0).lower() if rg else ""),
                    "in_absentia": bool(ABSENTIA.search(seg) or ABSENTIA.search(before[-30:])),
                    "phrase": seg[:200], "pos": m.start()})
    dedup = []
    for s in out:
        if dedup and s["pos"] - dedup[-1]["pos"] < 260:
            prev = dedup[-1]
            if s["kind"] == prev["kind"] and s["months"] == prev["months"]:
                continue  # the same event mentioned twice
            if s["kind"] == "fine" and prev["kind"] != "fine":
                prev["fine_rub"] = prev["fine_rub"] or s["fine_rub"]  # an additional fine on the same sentence
                continue
        dedup.append(s)
    return dedup
