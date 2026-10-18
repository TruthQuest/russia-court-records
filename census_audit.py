#!/usr/bin/env python3
"""Does the census find the cases we already know? A completeness check with no network.

    python census_audit.py                     all regions with census searches
    python census_audit.py --iso RU-SVE

Takes every OVD-Info record already docket-linked to a court registration (matches.csv) whose record carries one of the
census articles, registered in the census years, and asks whether the census search at that court found it:
  found                    the census search for that article lists the registration
  found_other_article      the court lists the registration, but not under that article (the court's article
                           differs from OVD-Info's, e.g. a different part or a re-qualification)
  missed                   the census search for that article at that court ran to the end and does not list it:
                           the census undercounts, look at these first
  search_unfinished        the census search at that court is not complete yet
  court_outside_census     the court is not a district or regional court (military courts are outside the sweep)
Prints counts and the missed registrations (court and docket only, no names).
"""
from __future__ import annotations

import argparse
import collections

from courtlink.constants import CENSUS_ARTICLES, LEVELS
from courtlink.common import load_config, read_csv, work_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--iso", nargs="*")
    ap.add_argument("--years", default="2022-2026")
    a = ap.parse_args()
    cfg = load_config(a.config)
    y1, y2 = (int(x) for x in a.years.split("-"))
    courts = {c["court_id"]: c for c in read_csv(work_path(cfg, "courts.csv"))}
    cases = {c["record_id"]: c for c in read_csv(work_path(cfg, "cases.csv"))}
    log = read_csv(work_path(cfg, "census_log.csv")) if work_path(cfg, "census_log.csv").exists() else []
    state = collections.defaultdict(set)
    for r in log:
        if r.get("mode") == "political":
            state[(r["court_id"], r["query"].split()[0])].add(r["state"])
    census = collections.defaultdict(set)  # (court, docket) -> articles it was listed under
    for r in read_csv(work_path(cfg, "census.csv")):
        census[(r["court_id"], r["docket_key"])] |= set(filter(None, r.get("article_queried", "").split(";")))
    out, missed = collections.Counter(), []
    seen = set()
    for m in read_csv(work_path(cfg, "matches.csv")):
        c = courts.get(m["court_id"], {})
        if a.iso and c.get("iso") not in a.iso:
            continue
        y = m["docket_key"].rsplit("/", 1)[-1]
        if not y.isdigit() or not (y1 <= int(y) <= y2):
            continue
        arts = set(filter(None, cases.get(m["record_id"], {}).get("articles", "").split(";"))) & set(CENSUS_ARTICLES)
        for art in sorted(arts):
            key = (m["court_id"], m["docket_key"], art)
            if key in seen:
                continue
            seen.add(key)
            st = state.get((m["court_id"], art), set())
            listed = census.get((m["court_id"], m["docket_key"]), set())
            if c.get("court_type") not in LEVELS:
                v = "court_outside_census"
            elif not (st & {"results", "empty"}):
                v = "search_unfinished"
            elif art in listed:
                v = "found"
            elif listed:
                v = "found_other_article"
            else:
                v = "missed"
                missed.append((m["court_id"], m["docket_key"], art, "/".join(sorted(st))))
            out[v] += 1
    tot = sum(out.values())
    checkable = out["found"] + out["found_other_article"] + out["missed"]
    print(f"known linked registrations under census articles: {tot}")
    for k in ("found", "found_other_article", "missed", "search_unfinished", "court_outside_census"):
        print(f"  {k:<22} {out[k]}")
    checked = out["found"] + out["found_other_article"] + out["missed"]
    if checked:
        print(f"census recall on known cases: {(out['found'] + out['found_other_article']) / checked:.0%} of {checked} checkable")
    for row in missed[:40]:
        print("  missed:", *row)
    import json
    from pathlib import Path
    outp = Path(cfg["_work"]) / "analysis"
    outp.mkdir(parents=True, exist_ok=True)
    tag = "_".join(a.iso) if a.iso else "all"
    (outp / f"census_audit_{tag}.json").write_text(json.dumps({"iso": a.iso or "all", **out, "checkable": checkable,
                                                                "missed_list": missed}, indent=1), "utf-8")


if __name__ == "__main__":
    main()
