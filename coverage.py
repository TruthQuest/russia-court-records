#!/usr/bin/env python3
"""Coverage report per region: where docketed cases end up and why. Aggregates only (no names),
safe to paste or share.

    python coverage.py                 all regions with searched cases
    python coverage.py --iso RU-BA     one region, plus per-court search states
"""
from __future__ import annotations

import argparse
import collections
from pathlib import Path

from courtlink.common import load_config, read_csv, setup_logging, work_path


def rd(cfg, name):
    p = Path(work_path(cfg, name))
    return read_csv(p) if p.exists() else []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--iso")
    ap.add_argument("--csv", help="also write a per-region coverage table (used by export_html.py --coverage)")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    cases = {c["record_id"]: c for c in rd(cfg, "cases.csv") if c["docket"] and c["level_hint"] != "magistrate"}
    cands = collections.defaultdict(set)
    for r in rd(cfg, "candidates.csv"):
        cands[r["record_id"]].add(r["reason"].split(":")[0])
    log = rd(cfg, "search_log.csv")
    searched = {r["record_id"] for r in log}
    matched = {r["record_id"] for r in rd(cfg, "matches.csv")}
    review = {r["record_id"] for r in rd(cfg, "review_queue.csv")}
    unres = {r["record_id"]: r for r in rd(cfg, "unresolved.csv")}

    def route(c):
        r = cands[c["record_id"]]
        if c["level_hint"].startswith("mosgorsud"):
            return "moscow"
        if "prefix_2" in r:
            return "regional_or_military"
        if "region_scan" in r:
            return "region_scan"
        if "city_district_court" in r:
            return "city_court"
        return "no_route"

    by = collections.defaultdict(collections.Counter)
    for c in cases.values():
        for iso in filter(None, (x.strip() for x in c["iso"].split(","))):
            if a.iso and iso != a.iso:
                continue
            rid = c["record_id"]
            rt = route(c)
            b = by[iso]
            b["docketed"] += 1
            if rid not in searched:
                b[f"not_searched:{rt}"] += 1
            elif rid in matched:
                b[f"matched:{rt}"] += 1
            elif rid in review:
                b["review"] += 1
            else:
                reason = unres.get(rid, {}).get("reason", "no_hit")
                b[f"unresolved:{rt}:{reason}"] += 1

    # courts a region's cases pointed to that were never searched successfully (captcha unanswered, blocked, error)
    ok = {(r["record_id"], r["court_id"]) for r in log if r.get("state") in ("results", "empty")}
    unsearched = collections.defaultdict(set)
    for r in log:
        c = cases.get(r["record_id"])
        if c and (r["record_id"], r["court_id"]) not in ok and r.get("state") not in ("results", "empty"):
            for iso in filter(None, (x.strip() for x in c["iso"].split(","))):
                unsearched[iso].add(r["court_id"])
    if a.csv:
        names = {}
        for c in cases.values():
            for iso in filter(None, (x.strip() for x in c["iso"].split(","))):
                names.setdefault(iso, c.get("region", iso))
        out = []
        for iso, b in sorted(by.items(), key=lambda x: -x[1]["docketed"]):
            if not any(k.startswith(("matched", "unresolved", "review")) for k in b):
                continue
            searched_n = b["docketed"] - sum(v for k, v in b.items() if k.startswith("not_searched"))
            out.append({"region": f"{names.get(iso, iso)} ({iso})", "docketed": b["docketed"], "searched": searched_n,
                        "matched": sum(v for k, v in b.items() if k.startswith("matched")),
                        "courts_unsearched": len(unsearched[iso]),
                        "cases_obstructed": sum(v for k, v in b.items() if k.startswith("unresolved") and
                                                any(x in k for x in ("captcha", "blocked", "error", "unknown")))})
        from courtlink.common import write_csv
        write_csv(a.csv, out, ["region", "docketed", "searched", "matched", "courts_unsearched", "cases_obstructed"])
    rows = [(iso, b) for iso, b in by.items() if a.iso or any(k.startswith(("matched", "unresolved", "review")) for k in b)]
    for iso, b in sorted(rows, key=lambda x: -x[1]["docketed"]):
        searched_n = b["docketed"] - sum(v for k, v in b.items() if k.startswith("not_searched"))
        m = sum(v for k, v in b.items() if k.startswith("matched"))
        print(f"\n{iso}  docketed {b['docketed']}  searched {searched_n}  matched {m}"
              f"  ({100 * m / max(searched_n, 1):.0f}% of searched)")
        for k, v in sorted(b.items()):
            if k != "docketed":
                print(f"   {v:4d}  {k}")

    if a.iso:
        ids = {rid for rid, c in cases.items() if a.iso in c["iso"]}
        st = collections.defaultdict(collections.Counter)
        for r in log:
            if r["record_id"] in ids:
                st[r["court_id"]][r["state"]] += 1
        print("\nsearch states per court (records x queries):")
        for court, cnt in sorted(st.items(), key=lambda x: -sum(x[1].values())):
            print(f"   {court:40s} " + "  ".join(f"{k}={v}" for k, v in sorted(cnt.items())))


if __name__ == "__main__":
    main()
