"""Full read of a sudrf case card: the CASE, PROGRESS (ДВИЖЕНИЕ ДЕЛА), FACES (ЛИЦА) and PARTIES (УЧАСТНИКИ) tabs.

All four tabs are in the one HTML page (the tabs are switched in the browser), so a cached card holds everything.
Column positions vary between court site versions, so columns are found by header keywords, as in parsers.py.

    parse_card_detail(html, url) -> {"case": {...}, "events": [...], "people": [...], "parties": [...]}

People come back without names: only whether the court withheld the name, the articles with parts, the date and the
result for that person. Parties come back with the role; a name is kept only for officials (prosecutors), never
for defence lawyers, victims or their representatives.
"""
from __future__ import annotations

import datetime as dt
import re

from .parsers import HIDDEN_RE, UID_RE, _rows, label_values, soup, text

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
ART_RE = re.compile(r"(?:ч\.?\s*(\d+(?:\.\d+)?)\s*)?ст\.?\s*(\d{2,3}(?:\.\d+)?)(?:\s*ч\.?\s*(\d+(?:\.\d+)?))?", re.I)

EVENT_COLS = {"event": ["наименование события", "событие"], "date": ["дата"], "time": ["время"],
              "venue": ["место проведения", "зал"], "result": ["результат события", "результат"],
              "basis": ["основание"], "note": ["примечание"], "posted": ["дата размещения", "размещ"]}
PEOPLE_COLS = {"name": ["фамилия", "фио", "лицо"], "articles": ["перечень статей", "статьи", "статья"],
               "date": ["дата рассмотрения"], "result": ["результат"]}
PARTY_COLS = {"role": ["вид лица", "процессуальн", "вид участника"], "name": ["фамилия", "наименование", "фио"]}

# per-person result on the FACES tab
PERSON_RESULTS = [("acquitted", r"оправдательн"), ("guilty", r"обвинительн"),
                  ("court_fine", r"судебн\w*\s+штраф"), ("medical", r"принудительн\w*\s+мер\w*\s+медицинск"),
                  ("dismissed", r"прекращ"), ("returned_to_prosecutor", r"возвращ\w*\s+прокурор"),
                  ("transferred", r"подсудност|передан\w*\s+по|направлен\w*\s+по"), ("joined", r"присоедин|соединен"),
                  ("suspended", r"приостановлен")]
EVENTS = [("registered", r"регистрац"), ("to_judge", r"передача\s+материалов\s+дела\s+судье|передан\w*\s+судье"),
          ("decision_on_case", r"решение\s+вопроса\s+о\s+поступившем"), ("preliminary", r"предварительн\w*\s+слушан"),
          ("hearing", r"судебное\s+заседание"), ("sentence_read", r"провозглашени\w*\s+приговор"),
          ("custody", r"мер\w*\s+пресечени|под\s+страж"),
          ("appeal", r"апелляц|жалоб|представлени"), ("to_higher_court", r"вышестоящ"),
          ("records", r"делопроизводств|оформлен|сдан\w*\s+в\s+отдел"), ("archive", r"архив")]
CUSTODY_RE = re.compile(r"под\s+страж|заключени\w*\s+под|домашн\w*\s+арест|мер\w*\s+пресечени", re.I)
EXTEND_RE = re.compile(r"продл", re.I)
POSTPONED_RE = re.compile(r"отложен", re.I)
BREAK_RE = re.compile(r"перерыв", re.I)
SENTENCE_RE = re.compile(r"приговор|постановлен\w*\s+приговор", re.I)
ROLES = [("prosecutor", r"прокурор|обвинител"), ("defence", r"защитник|адвокат"), ("victim", r"потерпевш"),
         ("representative", r"представител"), ("civil_party", r"гражданск\w*\s+(истец|ответчик)"),
         ("defendant", r"подсудим|обвиняем|осужденн")]


def _date(s: str) -> str:
    m = DATE_RE.search(s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def _time(s: str) -> str:
    m = TIME_RE.search(s or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _classify(s: str, table) -> str:
    for k, pat in table:
        if re.search(pat, s or "", re.I):
            return k
    return "other" if s else ""


def articles(s: str) -> list[str]:
    """'ч.2 ст.284.1 УК РФ', 'Статья 284.1 Часть 2', 'ст.207.3 ч.2 п.д' -> ['284.1(2)']"""
    s = re.sub(r"[Сс]тать[яи]\s*", "ст.", s or "")
    s = re.sub(r"[Чч]аст[ьи]\s*", "ч.", s)
    out = []
    for p1, art, p2 in ART_RE.findall(s):
        part = p1 or p2
        a = f"{art}({part})" if part else art
        if a not in out:
            out.append(a)
    return out


def _tables(s):
    """(title, header, rows) for every table with a header row, title from a one-cell first row or the nearest heading."""
    for t in s.find_all("table"):
        rows = _rows(t)
        if len(rows) < 2:
            continue
        title, start = "", 0
        if len(rows[0]) == 1:
            title, start = text(rows[0][0]), 1
        if not title:
            prev = t.find_previous(["h1", "h2", "h3", "h4", "b", "strong", "th"])
            title = text(prev)[:80] if prev else ""
        if start >= len(rows):
            continue
        hdr = [text(c).lower() for c in rows[start]]
        body = [[text(c) for c in r] for r in rows[start + 1:]]
        yield title.lower(), hdr, body


def _map(hdr: list[str], spec: dict) -> dict:
    out = {}
    for k, kws in spec.items():
        for i, h in enumerate(hdr):
            if i in out.values():
                continue
            if any(kw in h for kw in kws):
                out[k] = i
                break
    return out


DOCKET_RE = re.compile(r"(?:дело|номер дела)\s*№?\s*(\d+[\w-]*-\d+/\d{4})", re.I)


def parse_card_detail(html: str, url: str = "") -> dict:
    s = soup(html)  # parsed once; every tab is read from this
    kv = {}
    for _sec, lab, val in label_values(s):
        kv.setdefault(lab.lower().rstrip(":").strip(), val)
    raw = s.get_text(" ", strip=True)
    uid = UID_RE.search(raw)
    dm = DOCKET_RE.search(raw)
    case = {"uid": uid.group(0) if uid else "",
            "docket": next((kv[k] for k in ("номер дела", "№ дела") if kv.get(k)), "") or (dm.group(1) if dm else ""),
            "received": _date(kv.get("дата поступления", "")),
            "judge": kv.get("судья", ""),
            "decided": _date(kv.get("дата рассмотрения", "") or kv.get("дата решения", "")),
            "result": kv.get("результат рассмотрения", ""),
            "panel": next((v for k, v in kv.items() if k.startswith("признак рассмотрения")), ""),
            "division": next((v for k, v in kv.items() if "обособленного подразделения" in k or "номер здания" in k), ""),
            "category": kv.get("категория дела", "")}
    events, people, parties = [], [], []
    for title, hdr, body in _tables(s):
        ev = _map(hdr, EVENT_COLS)
        if "event" in ev and "date" in ev and ("движение" in title or "result" in ev):
            for r in body:
                g = lambda k: r[ev[k]] if k in ev and ev[k] < len(r) else ""  # noqa: E731
                name, res, basis = g("event"), g("result"), g("basis")
                both = " ".join((name, res, basis))
                events.append({"event": name, "event_class": _classify(name, EVENTS), "date": _date(g("date")),
                               "time": _time(g("time")), "result": res, "basis": basis, "posted": _date(g("posted")),
                               "postponed": int(bool(POSTPONED_RE.search(res))),
                               "break": int(bool(BREAK_RE.search(res))),
                               "custody": int(bool(CUSTODY_RE.search(both))),
                               "custody_extended": int(bool(CUSTODY_RE.search(both) and EXTEND_RE.search(both))),
                               "sentence": int(bool(SENTENCE_RE.search(res)) and "отмен" not in res.lower())})
            continue
        pc = _map(hdr, PEOPLE_COLS)
        if "name" in pc and "articles" in pc:
            for r in body:
                g = lambda k: r[pc[k]] if k in pc and pc[k] < len(r) else ""  # noqa: E731
                res = g("result")
                people.append({"name_hidden": int(bool(HIDDEN_RE.search(g("name"))) or not g("name").strip()),
                               "articles": ";".join(articles(g("articles"))), "date": _date(g("date")),
                               "result": res, "result_class": _classify(res, PERSON_RESULTS) or "pending"})
            continue
        pa = _map(hdr, PARTY_COLS)
        if "role" in pa:
            for r in body:
                g = lambda k: r[pa[k]] if k in pa and pa[k] < len(r) else ""  # noqa: E731
                role = _classify(g("role"), ROLES)
                parties.append({"role": g("role"), "role_class": role,
                                "name": g("name") if role == "prosecutor" else ""})
    return {"case": case, "events": events, "people": people, "parties": parties}


def _dt(d: str, t: str):
    try:
        return dt.datetime.fromisoformat(f"{d}T{t or '00:00'}")
    except ValueError:
        return None


def summarize(d: dict) -> dict:
    """One row per card: what happened to the defendants, how the case moved, how fast, how late it was posted."""
    ev, pe = d["events"], d["people"]
    reg = next((e for e in ev if e["event_class"] == "registered"), None)
    toj = next((e for e in ev if e["event_class"] == "to_judge"), None)
    hearings = [e for e in ev if e["event_class"] in ("hearing", "preliminary", "sentence_read")]
    held = {e["date"] for e in hearings if e["date"]}
    sent = next((e for e in ev if e["sentence"] and e["date"]), None)
    received = d["case"]["received"] or (reg or {}).get("date", "")
    m2j = ""
    if reg and toj:
        a, b = _dt(reg["date"], reg["time"]), _dt(toj["date"], toj["time"])
        if a and b and reg["time"] and toj["time"]:
            m2j = int((b - a).total_seconds() // 60)
    days = lambda a, b: (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days if a and b else ""  # noqa: E731
    lags = [days(e["date"], e["posted"]) for e in ev if e["date"] and e["posted"]]
    cls = [p["result_class"] for p in pe]
    return {"uid": d["case"]["uid"], "received": received, "panel": d["case"]["panel"],
            "single_judge": int("единолично" in d["case"]["panel"].lower()) if d["case"]["panel"] else "",
            "division": d["case"]["division"], "people": len(pe), "names_hidden": sum(p["name_hidden"] for p in pe),
            "guilty": cls.count("guilty"), "acquitted": cls.count("acquitted"),
            "dismissed": sum(c in ("dismissed", "court_fine") for c in cls), "medical": cls.count("medical"),
            "returned": cls.count("returned_to_prosecutor"), "pending": cls.count("pending"),
            "hearing_days": len(held), "postponed": sum(e["postponed"] for e in hearings),
            "custody_decisions": sum(e["custody"] for e in ev), "custody_extensions": sum(e["custody_extended"] for e in ev),
            "minutes_to_judge": m2j, "first_hearing": min(held) if held else "",
            "sentence_date": sent["date"] if sent else "",
            "days_to_sentence": days(received, sent["date"]) if sent and received else "",
            "single_hearing_trial": int(bool(sent) and len(held) == 1),
            "max_posting_lag_days": max(lags) if lags else "",
            "prosecutors": sum(p["role_class"] == "prosecutor" for p in d["parties"]),
            "defence_lawyers": sum(p["role_class"] == "defence" for p in d["parties"]),
            "victims": sum(p["role_class"] == "victim" for p in d["parties"])}
