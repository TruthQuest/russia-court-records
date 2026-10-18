#!/usr/bin/env python3
"""Step 7. Candidate matches between judges and sanctions/PEP lists (OpenSanctions).

    curl -L -o targets.simple.csv https://data.opensanctions.org/datasets/latest/default/targets.simple.csv
    python 07_sanctions_match.py --os targets.simple.csv

-> work/sanctions_candidates.csv   every candidate pair, for HUMAN REVIEW (fill review_decision:
                                   confirmed | rejected | unsure, plus review_note with the evidence)
Nothing here asserts that a judge is sanctioned. Court records give surname + initials; many Russians
share them. Confirm each pair against the listing's stated position/court before publishing.
"""
from __future__ import annotations

import argparse
import collections
import re

from rapidfuzz import fuzz

from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv
from courtlink.translit import skeleton

PATRONYMIC_RE = re.compile(r"(vich|vna|ovna|evna|ichna|chna|ich|вич|вна|ична|чна|ич)$", re.I)
JUDICIARY_RE = re.compile(r"judge|court|judicia|судь|суд\b|суда\b|tribunal", re.I)


def name_variants(row: dict) -> list[str]:
    out = [row.get("name", "")]
    for col in ("aliases",):
        out += [x.strip() for x in (row.get(col) or "").split(";") if x.strip()]
    return [v for v in dict.fromkeys(out) if v]


def analyse(variant: str) -> list[tuple[str, str, str, str]]:
    """Possible (surname, first_initial, patronymic_initial, first_name) readings of a name string."""
    if "," in variant:
        sur, rest = variant.split(",", 1)
        toks = [sur.strip()] + rest.split()
        orders = [0]
    else:
        toks = variant.split()
        orders = range(len(toks))
    out = []
    for si in orders:
        if si >= len(toks):
            continue
        sur = toks[si]
        rest = [t for i, t in enumerate(toks) if i != si]
        pat = next((t for t in rest if PATRONYMIC_RE.search(t)), "")
        first = next((t for t in rest if t != pat), "")
        out.append((sur, skeleton(first)[:1], skeleton(pat)[:1], first))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--os", help="OpenSanctions targets.simple.csv")
    ap.add_argument("--min-score", type=float)
    ap.add_argument("--all-countries", action="store_true", help="do not restrict to ru / unknown country")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    path = a.os or cfg["sanctions"].get("opensanctions_csv")
    min_score = a.min_score or float(cfg["sanctions"].get("min_score", 85))

    judges = read_csv(work_path(cfg, "judges.csv"))
    block = collections.defaultdict(list)
    n = 0
    for r in read_csv(path):
        if r.get("schema") != "Person":
            continue
        if not a.all_countries:
            cs = (r.get("countries") or "").lower()
            if cs and "ru" not in cs.split(";"):
                continue
        n += 1
        for v in name_variants(r):
            for sur, i1, i2, first in analyse(v):
                sk = skeleton(sur)
                if len(sk) >= 3:
                    block[sk[:3]].append((sk, i1, i2, first, v, r))
    LOG.info("sanctions persons indexed: %d", n)

    out = []
    for j in judges:
        jsk = skeleton(j["surname"])
        ji1, ji2 = skeleton(j["i1"])[:1], skeleton(j["i2"])[:1]
        best: dict[str, dict] = {}
        for sk, i1, i2, first, v, r in block.get(jsk[:3], []):
            s = fuzz.ratio(jsk, sk)
            if s < min_score:
                continue
            i1m = (i1 == ji1) if i1 else None
            i2m = (i2 == ji2) if i2 else None
            if i1m is False or i2m is False:  # a different initial means a different person
                continue
            score = s + (10 if i1m else 0) + (10 if i2m else 0)
            if j.get("first") and first:
                score += (fuzz.ratio(skeleton(j["first"]), skeleton(first)) - 80) / 4
            prev = best.get(r["id"])
            if prev is None or score > prev["score"]:
                best[r["id"]] = {
                    "judge_id": j["judge_id"], "judge": j["display"], "court_name": j.get("court_name", ""),
                    "n_records": j.get("n_records", ""), "os_id": r["id"], "os_name": r.get("name", ""),
                    "matched_variant": v, "score": round(score, 1), "surname_ratio": round(s, 1),
                    "first_initial_match": i1m, "patronymic_initial_match": i2m,
                    "mentions_judiciary": bool(JUDICIARY_RE.search(" ".join(str(x) for x in r.values()))),
                    "birth_date": r.get("birth_date", ""), "datasets": r.get("dataset", "") or r.get("datasets", ""),
                    "sanctions": (r.get("sanctions") or "")[:300],
                    "os_url": f"https://www.opensanctions.org/entities/{r['id']}/",
                    "review_decision": "", "review_note": "",
                }
        out += sorted(best.values(), key=lambda x: -x["score"])[:5]
    out.sort(key=lambda x: (-x["mentions_judiciary"], -x["score"]))
    write_csv(work_path(cfg, "sanctions_candidates.csv"), out)
    LOG.info("judges=%d  with >=1 candidate=%d  with judiciary-flagged candidate=%d", len(judges),
             len({o["judge_id"] for o in out}), len({o["judge_id"] for o in out if o["mentions_judiciary"]}))


if __name__ == "__main__":
    main()
