#!/usr/bin/env python3
"""Hand-check a random sample of record-to-case links and estimate precision.

    python precision_sample.py --draw 50          -> work/precision_sample.csv (fill in `correct` with yes/no)
    python precision_sample.py --score             -> work/kg/precision.json (used by export_html.py)

The sample file contains defendant names from OVD-Info and links to court cards so a person can judge each link.
It is a working file: keep it in work/ (git-ignored) and never share it.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv

FIELDS = ["correct", "note", "record_id", "ovd_name", "ovd_docket", "ovd_region", "ovd_city", "ovd_articles",
          "ovd_verdict_date", "court_name", "court_docket", "card_judge", "decision_date", "result", "rule", "card_url"]


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--draw", type=int); ap.add_argument("--score", action="store_true")
    ap.add_argument("--seed", type=int, default=20261015)
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    path = work_path(cfg, "precision_sample.csv")
    if a.draw:
        H = read_csv(work_path(cfg, "hearings.csv"))
        C = {c["record_id"]: c for c in read_csv(work_path(cfg, "cases.csv"))}
        mp = work_path(cfg, "matches.csv")
        M = {(m["record_id"], m["court_id"]): m for m in (read_csv(mp) if mp.exists() else [])}
        rows = random.Random(a.seed).sample(H, min(a.draw, len(H)))
        out = []
        for h in rows:
            c = C.get(h["record_id"], {})
            out.append({"correct": "", "note": "", "record_id": h["record_id"], "ovd_name": c.get("name", ""),
                        "ovd_docket": c.get("docket_raw", ""), "ovd_region": c.get("region", ""), "ovd_city": c.get("city", ""),
                        "ovd_articles": c.get("articles", ""), "ovd_verdict_date": c.get("verdict_date", ""),
                        "court_name": h["court_name"], "court_docket": h["docket"], "card_judge": h["judge"],
                        "decision_date": h["decision_date"], "result": h["result"],
                        "rule": M.get((h["record_id"], h["court_id"]), {}).get("rule", ""), "card_url": h["card_url"]})
        write_csv(path, out, FIELDS)
        LOG.info("open %s, check each card, set correct=yes/no, then run --score", path)
    if a.score:
        rows = [r for r in read_csv(path) if r["correct"].strip().lower() in ("yes", "no")]
        k = sum(1 for r in rows if r["correct"].strip().lower() == "yes")
        p, lo, hi = wilson(k, len(rows))
        res = {"checked": len(rows), "correct": k, "precision": p, "ci95_low": lo, "ci95_high": hi,
               "by_rule": {}}
        for r in rows:
            d = res["by_rule"].setdefault(r["rule"] or "unrecorded", [0, 0])
            d[0] += r["correct"].strip().lower() == "yes"; d[1] += 1
        out = Path(cfg["_work"]) / "kg" / "precision.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=1), "utf-8")
        LOG.info("precision %.1f%% (%d/%d), 95%% CI %.1f%% to %.1f%% -> %s", 100 * p, k, len(rows), 100 * lo, 100 * hi, out)


if __name__ == "__main__":
    main()
