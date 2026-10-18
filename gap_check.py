#!/usr/bin/env python3
"""Is a 'not in OVD-Info' registration really missing from OVD-Info, or did the name check miss it?

    python gap_check.py --article 354.1            every gap registration under that article
    python gap_check.py --docket 2-42/2025          one registration

For each court registration in work/analysis/not_in_ovd.csv, prints the defendant names the court lists and the
closest OVD-Info records in the same region carrying the same article (surname similarity, record ID, docket, start
date). It also lists OVD-Info records under the article in that region that were matched to no court registration.
Prints to the terminal only and writes nothing: the names stay on this computer.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from rapidfuzz import fuzz

from courtlink.common import court_id_from_url, load_config, read_csv, work_path
from courtlink.parsers import extract_names, parse_results
from courtlink.translit import skeleton


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--article"); ap.add_argument("--docket")
    ap.add_argument("--top", type=int, default=3)
    a = ap.parse_args()
    cfg = load_config(a.config)
    W = Path(cfg["_work"])
    gaps = read_csv(W / "analysis" / "not_in_ovd.csv")
    if a.article:
        gaps = [g for g in gaps if g["article"].startswith(a.article)]
    if a.docket:
        gaps = [g for g in gaps if g["docket"] == a.docket]
    want = {(g["court_id"], g["docket"]) for g in gaps}
    names = collections.defaultdict(set)
    for meta_p in (W / "cache").glob("*.json"):
        try:
            meta = json.loads(meta_p.read_text("utf-8"))
        except Exception:
            continue
        url = meta.get("url", "")
        if "name_op=r" not in url or meta.get("status") != 200:
            continue
        cid = court_id_from_url(url)
        if not any(c == cid for c, _ in want):
            continue
        body = (meta_p.with_suffix(".body")).read_bytes().decode(meta.get("encoding") or "utf-8", errors="replace")
        for r in parse_results(body, url):
            if (cid, r["docket_key"]) in want:
                info = r.get("info") or r.get("row_text", "")
                names[(cid, r["docket_key"])] |= set(extract_names(info)) or {f"(no name on the list: {info[:60]})"}
    cases = read_csv(work_path(cfg, "cases.csv"))
    linked = {m["record_id"] for m in read_csv(work_path(cfg, "matches.csv"))} if work_path(cfg, "matches.csv").exists() else set()
    for g in gaps:
        art = g["article"].split()[0]
        pool = [c for c in cases if g["region"].split()[0] in c.get("iso", "") and art in c.get("articles", "").split(";")]
        print(f"\n{g['court']}  {g['docket']}  {g['article']}  received {g['received']}  outcome {g['outcome']}")
        for n in sorted(names.get((g["court_id"], g["docket"]), {"(registration not found in the cache)"})):
            print(f"   court lists: {n}")
            sur = skeleton(n.split()[0]) if n and not n.startswith("(") else ""
            scored = sorted(((fuzz.ratio(sur, skeleton(c.get("last_name") or "")), c) for c in pool if sur), key=lambda x: -x[0])
            for sc, c in scored[: a.top]:
                print(f"      {sc:5.0f}  {c.get('first_name', '')} {c.get('last_name', '') or '(name withheld)'}  "
                      f"{c['record_id']}  docket {c.get('docket') or '-'}  started {c.get('started_date') or '-'}"
                      f"{'  [linked elsewhere]' if c['record_id'] in linked else ''}")
    if a.article:
        for iso in sorted({g["region"].split()[0] for g in gaps}):
            free = [c for c in cases if iso in c.get("iso", "") and a.article in c.get("articles", "").split(";") and c["record_id"] not in linked]
            print(f"\nOVD-Info records under {a.article} in {iso} not docket-linked to any registration: {len(free)}")
            for c in free:
                print(f"   {c.get('first_name', '')} {c.get('last_name', '') or '(name withheld)'}  {c['record_id']}  "
                      f"docket {c.get('docket') or '-'}  started {c.get('started_date') or '-'}  city {c.get('city', '')}")


if __name__ == "__main__":
    main()
