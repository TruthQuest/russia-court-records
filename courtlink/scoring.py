"""Score a court-site hit against an OVD-Info case. Weights live in config.yaml (matching:)."""
from __future__ import annotations

import json
import re

from rapidfuzz import fuzz

from .common import days_between, parse_date
from .translit import skeleton

DEFAULT_W = {
    "docket_exact": 5.0, "docket_prior": 4.0, "docket_mismatch": -2.0,
    "name_strong": 3.0, "name_weak": 1.5, "name_conflict": -3.0,
    "date_close": 2.0, "date_near": 0.5, "date_far": -1.0,
    "article": 1.0, "article_conflict": -3.0,
    "accept": 6.0, "review": 3.0, "margin": 2.0,
    "date_close_days": 7, "date_near_days": 60,
}

ART_RE = re.compile(r"ст\.\s*(\d{2,3}(?:\.\d{1,2})?)")


def surname_of(name: str) -> str:
    """Court names are 'Фамилия И.О.' or 'Фамилия Имя Отчество': surname first."""
    toks = (name or "").replace(".", ". ").split()
    return toks[0] if toks else ""


def name_score(ovd_last: str, ovd_first: str, page_names: list[str]) -> tuple[float, str]:
    """Best fuzzy similarity (0-100) of OVD surname to any surname on the page, plus the name."""
    if not ovd_last or not page_names:
        return -1.0, ""
    target = skeleton(ovd_last)
    best, who = 0.0, ""
    for n in page_names:
        sc = fuzz.ratio(target, skeleton(surname_of(n)))
        if ovd_first and len(n.split()) >= 2:
            first_tok = n.split()[1]
            if skeleton(first_tok)[:1] and skeleton(first_tok)[:1] != skeleton(ovd_first)[:1]:
                sc -= 15
        if sc > best:
            best, who = sc, n
    return best, who


def score_hit(case: dict, hit: dict, w: dict | None = None) -> tuple[float, dict]:
    w = {**DEFAULT_W, **(w or {})}
    s, why = 0.0, {}
    keys = set(filter(None, case.get("docket_keys", "").split(";")))
    cur = case.get("docket_key", "")
    hk = hit.get("docket_key", "")
    if hk and cur and hk == cur:
        s += w["docket_exact"]; why["docket"] = "exact"
    elif hk and hk in keys:
        s += w["docket_prior"]; why["docket"] = "prior"
    elif cur and hk:
        s += w["docket_mismatch"]; why["docket"] = "mismatch"

    names = [n for n in (hit.get("names") or "").split("; ") if n]
    ns, who = name_score(case.get("last_name", ""), case.get("first_name", ""), names)
    if ns >= 90:
        s += w["name_strong"]; why["name"] = f"{who} ({ns:.0f})"
    elif ns >= 80:
        s += w["name_weak"]; why["name"] = f"{who} ({ns:.0f})"
    elif ns >= 0 and names:
        s += w["name_conflict"]; why["name"] = f"conflict best={who} ({ns:.0f})"

    hd = parse_date(hit.get("decision_date", ""))
    gaps = [days_between(hd, v) for v in (case.get("verdict_date"), case.get("first_verdict_date")) if hd and v]
    d = min(gaps) if gaps else None
    if d is not None:
        if d <= w["date_close_days"]:
            s += w["date_close"]
        elif d <= w["date_near_days"]:
            s += w["date_near"]
        else:
            s += w["date_far"]
        why["date_gap_days"] = d

    arts = set(filter(None, case.get("articles", "").split(";")))
    page_arts = set(ART_RE.findall(hit.get("row_text", "") or hit.get("info", "")))
    if arts and arts & page_arts:
        s += w["article"]; why["article"] = ",".join(sorted(arts & page_arts))
    elif arts and page_arts:
        s += w["article_conflict"]; why["article"] = "conflict: court " + ",".join(sorted(page_arts)[:4])
    return s, why


def decide(scored: list[tuple[float, dict]], w: dict | None = None) -> str:
    """scored: [(score, hit)] sorted desc. Returns accept / review / reject for the top hit."""
    w = {**DEFAULT_W, **(w or {})}
    if not scored:
        return "none"
    top = scored[0][0]
    second = scored[1][0] if len(scored) > 1 else float("-inf")
    if top >= w["accept"] and top - second >= w["margin"]:
        return "accept"
    if top >= w["review"]:
        return "review"
    return "reject"


# --- rule-based decision -----------------------------------------------------------------------
# Docket numbers are unique within a court, so a docket hit is the anchor. The rules below decide,
# in order, what further evidence makes the hit the same prosecution. Every match records the rule
# that accepted it (and a confidence level) so the methods section can report the mix.

def features(case: dict, hit: dict, w: dict | None = None) -> dict:
    s, why = score_hit(case, hit, w)
    d = why.get("docket", "")
    a = why.get("article", "")
    n = why.get("name", "")
    m = re.search(r"\((\d+)\)\s*$", n)
    return {
        "score": s, "why": why,
        "docket": d in ("exact", "prior"),
        "article": "conflict" if a.startswith("conflict") else ("match" if a else "unknown"),
        "name": "conflict" if n.startswith("conflict") else ("match" if n else "unknown"),
        "name_sim": float(m.group(1)) if m else 0.0,
        "gap": why.get("date_gap_days"),
        "case_has_docket": bool(case.get("docket_key")),
    }


RULES = [  # (rule id, confidence, predicate); R1-R6 need the docket anchor, R7 is for docketless cases
    ("R1_docket+name", "high", lambda f: f["docket"] and f["name"] == "match" and f["name_sim"] >= 90),
    ("R7_name+article+date", "high", lambda f: not f["docket"] and f["article"] == "match" and f["gap"] is not None and f["gap"] <= 7),
    ("R7b_name+article_or_date", "medium", lambda f: not f["docket"]),
    ("R2_docket+article+date", "high", lambda f: f["article"] == "match" and f["gap"] is not None and f["gap"] <= 7),
    ("R3_docket+date", "high", lambda f: f["article"] != "conflict" and f["gap"] is not None and f["gap"] <= 7),
    ("R4_docket+name_weak", "medium", lambda f: f["name"] == "match"),
    ("R5_docket+article", "medium", lambda f: f["article"] == "match" and (f["gap"] is None or f["gap"] <= 400)),
    ("R6_docket_only", "low", lambda f: f["docket"] and f["article"] == "unknown" and f["gap"] is None),
]


def eligible(f: dict) -> bool:
    """Hard exclusions: no docket anchor, a different article, or a different named defendant
    without same-day decision and same article (which would mean a co-defendant row of the same case)."""
    if f["article"] == "conflict":
        return False
    if not f["docket"]:
        # cases with no docket in OVD-Info: a strong surname match is the anchor, plus article or date
        return (not f["case_has_docket"] and f["name"] == "match" and f["name_sim"] >= 90
                and (f["article"] == "match" or (f["gap"] is not None and f["gap"] <= 7)))
    if f["name"] == "conflict" and not (f["article"] == "match" and f["gap"] is not None and f["gap"] <= 7):
        return False
    return True


def decide_rules(case: dict, hits: list[dict], w: dict | None = None) -> tuple[str, dict | None, str, str]:
    """-> (decision, chosen_hit, rule, confidence). decision in accept / review / reject / none."""
    if not hits:
        return "none", None, "", ""
    feats = [(features(case, h, w), h) for h in hits]
    ok = [(f, h) for f, h in feats if eligible(f)]
    if not ok:
        return "reject", None, "excluded:" + ",".join(sorted({
            "no_docket" if not f["docket"] else "article_conflict" if f["article"] == "conflict" else "name_conflict"
            for f, _ in feats})), ""
    for rule, conf, pred in RULES:
        passing = [(f, h) for f, h in ok if pred(f)]
        if not passing:
            continue
        courts = {h["court_id"] for _, h in passing}
        if len(courts) == 1:
            f, h = max(passing, key=lambda x: x[0]["score"])
            return "accept", {**h, "score": round(f["score"], 2), "why": json.dumps(f["why"], ensure_ascii=False)}, rule, conf
        gaps = sorted((f["gap"], f["score"], h) for f, h in passing if f["gap"] is not None)
        if len(gaps) >= 2 and gaps[0][0] + 14 < gaps[1][0]:  # one court's date clearly closest
            g, sc, h = gaps[0]
            f = next(f for f, hh in passing if hh is h)
            return "accept", {**h, "score": round(sc, 2), "why": json.dumps(f["why"], ensure_ascii=False)}, rule + "+date_tiebreak", conf
        return "review", None, rule + ":tie_between_courts", conf
    return "reject", None, "no_rule", ""
