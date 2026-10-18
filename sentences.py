#!/usr/bin/env python3
"""Sentences per OVD-Info record, parsed from the export's text fields, for the judge severity analysis.

    python sentences.py                         uses ovd_csv from config.yaml (or --csv)
    python sentences.py --sample 40             also writes work/sentences_sample.csv to check by hand (fill `correct`)
    python sentences.py --score                 precision of the parser from the filled sample

Reads the columns "Hearings with sentence", "Story" and "Plot of the case" of the OVD-Info export (and the Russian
export if ovd_ru_csv is set). The first sentence mentioned is taken as the first-instance sentence, the last as the
latest (appeal or later). Writes work/sentences.csv: record_id, first_* and last_* kind/months/fine, mention count.
No names in sentences.csv; the sample file quotes story text and stays in work/ (private).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import sys

from courtlink.common import COL, LOG, load_config, read_csv, setup_logging, work_path, write_csv
from courtlink.sentence_text import parse_all

FIELDS = ["record_id", "first_kind", "first_months", "first_fine_rub", "first_regime", "last_kind", "last_months",
          "last_fine_rub", "in_absentia", "mentions", "source_column"]


def record_sentences(row: dict, cols: list[str]) -> dict | None:
    for c in cols:
        ms = parse_all(row.get(c, "") or "")
        if ms:
            f, l = ms[0], ms[-1]
            return {"first_kind": f["kind"], "first_months": f["months"] if f["months"] is not None else "",
                    "first_fine_rub": f["fine_rub"] or "", "first_regime": f["regime"], "last_kind": l["kind"],
                    "last_months": l["months"] if l["months"] is not None else "", "last_fine_rub": l["fine_rub"] or "",
                    "in_absentia": "1" if f["in_absentia"] else "",
                    "mentions": len(ms), "source_column": c, "_phrase": f["phrase"]}
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--csv")
    ap.add_argument("--sample", type=int, default=0); ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    setup_logging()
    csv.field_size_limit(sys.maxsize)
    cfg = load_config(a.config)
    sp = work_path(cfg, "sentences_sample.csv")
    if a.score:
        rows = [r for r in read_csv(sp) if r.get("correct", "").strip().lower() in ("yes", "no")]
        k = sum(r["correct"].strip().lower() == "yes" for r in rows)
        from coverage_gap import wilson
        lo, hi = wilson(k, len(rows))
        res = {"checked": len(rows), "correct": k, "precision": k / len(rows) if rows else None, "ci95": [lo, hi]}
        (work_path(cfg, "sentences_precision.json")).write_text(json.dumps(res, indent=1), "utf-8")
        LOG.info("sentence parser precision: %s", res)
        return
    path = a.csv or cfg.get("ovd_csv")
    if not path:
        raise SystemExit("give the OVD-Info export with --csv or set ovd_csv in config.yaml")
    src = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    cols = [COL["hearings"], COL["story"], COL["plot"]]
    cols = [c for c in cols if c in (src[0] if src else {})]
    out, phrases, stats = [], [], collections.Counter()
    for r in src:
        s = record_sentences(r, cols)
        if not s:
            stats["no_sentence_text"] += 1
            continue
        stats[s["first_kind"]] += 1
        phrases.append({"record_id": r[COL["record"]], "kind": s["first_kind"], "months": s["first_months"],
                        "fine_rub": s["first_fine_rub"], "phrase": s.pop("_phrase"), "correct": ""})
        out.append({"record_id": r[COL["record"]], **s})
    write_csv(work_path(cfg, "sentences.csv"), out, FIELDS)
    LOG.info("records: %d  with a sentence mention: %d  by first kind: %s", len(src), len(out), dict(stats))
    if a.sample:
        random.Random(11).shuffle(phrases)
        write_csv(sp, phrases[: a.sample], ["record_id", "kind", "months", "fine_rub", "phrase", "correct"])
        LOG.info("check %s by hand (correct = yes/no), then run: python sentences.py --score", sp)


if __name__ == "__main__":
    main()
