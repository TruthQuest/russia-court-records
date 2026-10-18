#!/usr/bin/env python3
"""Manual lookup path: the pilot, plus anything automation can't reach (captcha, blocks).

    python 08_manual.py make --iso RU-MOW --prefix 01 --n 50      -> work/manual_lookup.csv
    python 08_manual.py make --from-unresolved                    -> sheet for unresolved.csv cases
    python 08_manual.py ingest work/manual_lookup_filled.csv      -> work/hearings_manual.csv + pilot stats

Fill in: court_name, court_url, judge (as written on the card), card_url, uid, decision_date,
found (y/n), minutes_spent, notes. Save the card page (Ctrl+S) and put its file name in saved_file
so the provenance chain holds.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import pathlib
import random
import statistics
from urllib.parse import quote

from courtlink.common import LOG, court_id_from_url, load_config, read_csv, setup_logging, work_path, write_csv

FILL = ["found", "court_name", "court_url", "judge", "card_url", "uid", "decision_date", "saved_file",
        "minutes_spent", "notes", "looked_up_by"]


def hint(case: dict, cfg: dict) -> str:
    if case["level_hint"] == "magistrate":
        return "Moscow magistrate court (judicial section in docket); search the magistrates' portal (mos-sud.ru, VERIFY)"
    if case["level_hint"].startswith("mosgorsud") or "RU-MOW" in case["iso"]:
        mc = cfg["mosgorsud"]
        return f"{mc['base']}{mc['search_path']}?{mc['docket_param']}={quote(case['docket'] or '')}"
    return "https://bsr.sudrf.ru/bigs/portal.html  (search docket / surname; or the court site from candidates.csv)"


def make(cfg, a) -> None:
    cases = read_csv(work_path(cfg, "cases.csv"))
    if a.from_unresolved:
        ids = {r["record_id"] for r in read_csv(work_path(cfg, "unresolved.csv"))}
        cases = [c for c in cases if c["record_id"] in ids]
    if a.iso:
        cases = [c for c in cases if a.iso in c["iso"]]
    if a.prefix:
        cases = [c for c in cases if c["docket_prefix"] == a.prefix]
    random.Random(a.seed).shuffle(cases)
    cases = cases[: a.n] if a.n else cases
    cands = collections.defaultdict(list)
    if work_path(cfg, "candidates.csv").exists():
        for c in read_csv(work_path(cfg, "candidates.csv")):
            cands[c["record_id"]].append(f"{c['court_name']} {c['url']}")
    rows = [{"record_id": c["record_id"], "name": c["name"], "cyr_guess": c["cyr_last_candidates"],
             "docket": c["docket_raw"], "region": c["region"], "city": c["city"], "articles": c["articles"],
             "verdict_date": c["verdict_date"], "court_mentions": c["court_mentions"],
             "candidate_courts": " | ".join(cands[c["record_id"]][:4]), "search_hint": hint(c, cfg),
             **{f: "" for f in FILL}} for c in cases]
    write_csv(work_path(cfg, "manual_lookup.csv"), rows)


def ingest(cfg, path: str) -> None:
    rows = read_csv(path)
    out, mins, found = [], [], 0
    for r in rows:
        try:
            mins.append(float(r.get("minutes_spent") or "nan"))
        except ValueError:
            pass
        if r.get("found", "").strip().lower() not in ("y", "yes", "1", "true"):
            continue
        found += 1
        sha = ""
        if r.get("saved_file") and pathlib.Path(r["saved_file"]).exists():
            sha = hashlib.sha256(pathlib.Path(r["saved_file"]).read_bytes()).hexdigest()
        host = r.get("court_url", "").split("//")[-1].split("/")[0]
        out.append({"hearing_id": "m_" + hashlib.sha1((r["record_id"] + r.get("card_url", "")).encode()).hexdigest()[:12],
                    "record_id": r["record_id"], "court_id": court_id_from_url(host) if host else "manual",
                    "court_name": r.get("court_name", ""), "court_type": "", "instance": "criminal_first",
                    "docket": r.get("docket", ""), "docket_key": "", "uid": r.get("uid", ""),
                    "judge": r.get("judge", ""), "judges_all": r.get("judge", ""), "judge_source": "manual",
                    "decision_date": r.get("decision_date", ""), "result": "", "card_url": r.get("card_url", ""),
                    "card_sha256": sha, "card_fetched_at": "", "match_source": "manual", "results_sha256": ""})
    write_csv(work_path(cfg, "hearings_manual.csv"), out)
    mins = [m for m in mins if m == m]
    LOG.info("pilot: %d rows, found %d (%.0f%%), with judge %d, median minutes %.1f",
             len(rows), found, 100 * found / max(len(rows), 1), sum(bool(o["judge"]) for o in out),
             statistics.median(mins) if mins else float("nan"))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--iso"); m.add_argument("--prefix"); m.add_argument("--n", type=int, default=50)
    m.add_argument("--seed", type=int, default=7); m.add_argument("--from-unresolved", action="store_true")
    i = sub.add_parser("ingest")
    i.add_argument("path")
    ap.add_argument("--config")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    make(cfg, a) if a.cmd == "make" else ingest(cfg, a.path)


if __name__ == "__main__":
    main()
