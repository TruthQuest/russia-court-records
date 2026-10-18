"""HTML parsers for court sites. Header-keyword driven, so minor layout changes don't break them.

Run probe.py against a live page first; if a parser returns nothing, adjust the keyword lists in
config.yaml (parsers: section) rather than editing code.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .dockets import docket_key

WS = re.compile(r"\s+")

DEFAULT_RESULT_COLS = {
    "docket": ["номер дела", "№ дела", "номер"],
    "received": ["дата поступления", "поступило"],
    "info": ["информация по делу", "стороны", "категория", "фио", "лица", "участник", "статья"],
    "judge": ["судья", "председательствующ"],
    "decision_date": ["дата решения", "дата рассмотрения"],
    "decision": ["решение", "результат", "состояние"],
    "acts": ["судебные акты", "акт"],
}

JUDGE_LABELS = ["судья", "председательствующий", "председательствующий судья", "судья-докладчик", "докладчик"]
UID_RE = re.compile(r"\b\d{2}[A-ZА-Я]{2}\d{4}-\d{2}-\d{4}-\d{6}-\d{2}\b")
CYR_NAME_RE = re.compile(
    r"\b([А-ЯЁ][А-ЯЁа-яё-]{1,40})\s+(?:([А-ЯЁ])\.\s?([А-ЯЁ])\.?|([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+(?:вич|вна|чна|ична|ич|оглы|кызы)"
    r"|[А-ЯЁ][а-яё]+\s+(?:оглы|кызы|угли|улы|уулу)))"
)
# the same in capitals ("МАСЛОВ СЕРГЕЙ ВЛАДИМИРОВИЧ"), as some courts list defendants
CYR_NAME_UPPER_RE = re.compile(
    r"\b([А-ЯЁ]{2,40}(?:-[А-ЯЁ]{2,})?)\s+([А-ЯЁ]{2,})\s+([А-ЯЁ]{2,}(?:ВИЧ|ВНА|ЧНА|ИЧНА|ИЧ|ОГЛЫ|КЫЗЫ)|[А-ЯЁ]{2,}\s+(?:ОГЛЫ|КЫЗЫ|УГЛИ|УЛЫ|УУЛУ))\b"
)
HIDDEN_RE = re.compile(r"информация\s+скрыта|данные\s+скрыты|скрыт[оаы]?\b", re.I)


def soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception:  # lxml missing
        return BeautifulSoup(html or "", "html.parser")


def text(el) -> str:
    if el is None:
        return ""
    return WS.sub(" ", el.get_text(" ", strip=True)).strip()


def _rows(table: Tag) -> list[list[Tag]]:
    out = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = tr.find_all(["td", "th"], recursive=False)
        if cells:
            out.append(cells)
    return out


def tables(html: str) -> list[list[list[Tag]]]:
    s = soup(html)
    return [_rows(t) for t in s.find_all("table")]


def _map_columns(header: list[str], colspec: dict[str, list[str]]) -> dict[str, int]:
    m = {}
    for field, kws in colspec.items():
        for i, h in enumerate(header):
            hl = h.lower()
            if any(k in hl for k in kws) and i not in m.values():
                m[field] = i
                break
    return m


def parse_results(html: str, base_url: str, colspec: dict | None = None) -> list[dict]:
    """Parse a search-results table (sudrf or mos-gorsud). Returns one dict per case row."""
    colspec = colspec or DEFAULT_RESULT_COLS
    best: list[dict] = []
    for rows in tables(html):
        if len(rows) < 2:
            continue
        hdr_i = None
        for i, r in enumerate(rows[:4]):
            hdr = [text(c) for c in r]
            m = _map_columns(hdr, colspec)
            if "docket" in m and ("judge" in m or "info" in m):
                hdr_i, cmap = i, m
                break
        if hdr_i is None:
            continue
        out = []
        for r in rows[hdr_i + 1:]:
            vals = [text(c) for c in r]
            if len(vals) < len(cmap) or not any(vals):
                continue
            row = {f: (vals[i] if i < len(vals) else "") for f, i in cmap.items()}
            dk = docket_key(row.get("docket", ""))
            if not dk:
                continue
            link = None
            for c in r:
                a = c.find("a", href=True)
                if a and ("case" in a["href"] or "details" in a["href"] or "name_op=case" in a["href"]):
                    link = a["href"]
                    break
            if link is None:
                a = r[cmap["docket"]].find("a", href=True)
                link = a["href"] if a else ""
            row["docket_key"] = dk
            row["case_url"] = urljoin(base_url, link) if link else ""
            row["row_text"] = " | ".join(vals)
            # names from the parties/info cell only, so the judge's name never counts as the defendant
            row["names"] = "; ".join(extract_names(row.get("info") or row["row_text"]))
            out.append(row)
        if len(out) > len(best):
            best = out
    return best


def extract_names(s: str) -> list[str]:
    names = []
    for m in CYR_NAME_RE.finditer(s or ""):
        if m.group(2):
            n = f"{m.group(1)} {m.group(2)}.{m.group(3)}."
        else:
            n = f"{m.group(1)} {m.group(4)} {m.group(5)}"
        if n not in names:
            names.append(n)
    for m in CYR_NAME_UPPER_RE.finditer(s or ""):
        n = " ".join(w.capitalize() for w in (m.group(1), m.group(2))) + " " + " ".join(w.capitalize() for w in m.group(3).split())
        if n not in names and not any(x.split()[0].lower() == n.split()[0].lower() for x in names):
            names.append(n)
    return names


def hidden_names(s: str) -> int:
    """Defendants the court lists with the name withheld ("<Информация скрыта>")."""
    return len(HIDDEN_RE.findall(s or ""))


def label_values(html) -> list[tuple[str, str, str]]:
    """All (section, label, value) pairs from 2-column rows, dt/dd, and div.left/div.right patterns.
    Takes HTML text or an already parsed page."""
    s = html if isinstance(html, BeautifulSoup) else soup(html)
    out = []
    section = ""
    for t in s.find_all("table"):
        for r in _rows(t):
            if len(r) == 1:
                cand = text(r[0])
                if cand and len(cand) < 80:
                    section = cand
                continue
            if len(r) == 2:
                lab, val = text(r[0]), text(r[1])
                if lab and len(lab) < 120:
                    out.append((section, lab, val))
    for dl in s.find_all("dl"):
        for dt_ in dl.find_all("dt"):
            dd = dt_.find_next_sibling("dd")
            out.append(("", text(dt_), text(dd)))
    for left in s.select(".left, .row_card .left, .caption"):
        right = left.find_next_sibling()
        if right is not None:
            out.append(("", text(left), text(right)))
    return out


def section_tables(html: str) -> dict[str, list[dict]]:
    """Multi-column tables keyed by the nearest preceding title (e.g. 'ДВИЖЕНИЕ ДЕЛА', 'ЛИЦА')."""
    s = soup(html)
    out: dict[str, list[dict]] = {}
    for t in s.find_all("table"):
        rows = _rows(t)
        if len(rows) < 2:
            continue
        title = ""
        start = 0
        if len(rows[0]) == 1:
            title, start = text(rows[0][0]), 1
        if not title:
            prev = t.find_previous(["h1", "h2", "h3", "h4", "b", "strong", "div"])
            title = text(prev)[:80] if prev else ""
        if start >= len(rows):
            continue
        hdr = [text(c) for c in rows[start]]
        if len(hdr) < 3:
            continue
        recs = []
        for r in rows[start + 1:]:
            vals = [text(c) for c in r]
            if len(vals) == len(hdr):
                recs.append(dict(zip(hdr, vals)))
        if recs:
            out.setdefault(title or f"table{len(out)}", []).extend(recs)
    return out


def parse_card(html: str, base_url: str) -> dict:
    """Extract judge, UID, docket, court and related links from a case card page."""
    lv = label_values(html)
    judges = []
    kv = {}
    for sec, lab, val in lv:
        ll = lab.lower().rstrip(":").strip()
        kv.setdefault(ll, val)
        if ll in JUDGE_LABELS or ll.startswith("судья") or "председательствующ" in ll:
            v = re.sub(r"^(судья|председательствующий)\s*:?\s*", "", val, flags=re.I).strip()
            if v and v not in judges:
                judges.append(v)
    raw = soup(html).get_text(" ", strip=True)
    uid = UID_RE.search(raw)
    docket = ""
    for k in ("номер дела", "номер дела в первой инстанции", "№ дела"):
        if kv.get(k):
            docket = kv[k]
            break
    if not docket:
        m = re.search(r"(?:дело|номер дела)\s*№?\s*([\d-]+/\d{4})", raw, re.I)
        docket = m.group(1) if m else ""
    links = []
    host = urlsplit(base_url).netloc
    for a in soup(html).find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        h2 = urlsplit(href).netloc
        if h2 and h2 != host and ("sudrf.ru" in h2 or "mos-gorsud" in h2) and "case" in href:
            links.append(href)
    return {
        "judges": judges,
        "judge": judges[0] if judges else "",
        "uid": uid.group(0) if uid else "",
        "docket": docket,
        "docket_key": docket_key(docket),
        "decision_date": kv.get("дата решения", "") or kv.get("дата рассмотрения", ""),
        "result": kv.get("результат рассмотрения", "") or kv.get("решение", ""),
        "category": kv.get("категория дела", "") or kv.get("категория", ""),
        "names": extract_names(raw),
        "linked_cases": sorted(set(links)),
        "sections": section_tables(html),
    }


COURT_TYPES = [
    ("military_district", [r"окружн\w* военн", r"флотск\w* военн"]),
    ("garrison", [r"гарнизонн\w* военн"]),
    ("appellate", [r"апелляционн\w* суд"]),
    ("cassation", [r"кассационн\w* суд"]),
    ("regional", [r"областн\w* суд", r"краев\w* суд", r"верховн\w* суд республики", r"суд\s+\w+\s+автономн",
                  r"московск\w* городск\w* суд", r"санкт-петербургск\w* городск\w* суд",
                  r"севастопольск\w* городск\w* суд", r"суд еврейской", r"суд (ханты|ямало|ненецк|чукотск)"]),
    ("district", [r"районн\w* суд", r"городск\w* суд", r"межрайонн\w* суд"]),
]


def court_type(name: str) -> str:
    n = (name or "").lower()
    if "мировой" in n or "мировых" in n or "арбитраж" in n:
        return "skip"
    for t, pats in COURT_TYPES:
        if any(re.search(p, n) for p in pats):
            return t
    return "other"


def parse_directory(html: str, base_url: str) -> list[dict]:
    """Court list page -> [{name, url, host, court_type}]."""
    out, seen = [], set()
    s = soup(html)
    for a in s.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        host = urlsplit(href).netloc
        if not host.endswith("sudrf.ru") or host in ("sudrf.ru", "www.sudrf.ru", "bsr.sudrf.ru"):
            continue
        name = text(a)
        if "суд" not in name.lower():
            container = a.find_parent(["li", "tr", "div"])
            name = text(container)[:200] if container else name
        if "суд" not in name.lower() or host in seen:
            continue
        seen.add(host)
        ct = court_type(name)
        if ct == "skip":
            continue
        out.append({"name": name, "url": f"https://{host}", "host": host, "court_type": ct})
    return out


def form_fields(html: str) -> list[dict]:
    """List <form> inputs: helps discover search parameter names on a court site."""
    out = []
    s = soup(html)
    for form in s.find_all("form"):
        action = form.get("action", "")
        for inp in form.find_all(["input", "select", "textarea"]):
            nm = inp.get("name")
            if not nm:
                continue
            lab = ""
            if inp.get("id"):
                l_ = s.find("label", attrs={"for": inp["id"]})
                lab = text(l_)
            if not lab:
                prev = inp.find_previous(string=True)
                lab = (prev or "").strip()[:60]
            out.append({"form_action": action, "name": nm, "type": inp.get("type", inp.name),
                        "value": inp.get("value", ""), "label": lab})
    return out
