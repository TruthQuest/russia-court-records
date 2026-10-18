#!/usr/bin/env python3
"""Step 4. Decide matches from hits.

    python 04_match.py                         -> work/matches.csv, review_queue.csv, unresolved.csv
    python 04_match.py --apply-review FILE     -> folds your decisions (review_decision=accept|reject) into matches

In review_queue.csv, set `review_decision` to accept on the ONE row per record you confirm, or reject.
"""
from __future__ import annotations

import argparse
import collections

from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv
from courtlink.scoring import decide_rules

MATCH_FIELDS = ["record_id", "court_id", "court_name", "court_type", "instance", "docket", "docket_key",
                "judge", "decision_date", "case_url", "score", "why", "rule", "confidence", "source", "source_url", "sha256",
                "fetched_at"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--apply-review")
    ap.add_argument("--review-top", type=int, default=3)
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    w = cfg.get("matching", {})

    if a.apply_review:
        matches = read_csv(work_path(cfg, "matches.csv"))
        have = {m["record_id"] for m in matches}
        n = 0
        for r in read_csv(a.apply_review):
            if r.get("review_decision", "").strip().lower() == "accept" and r["record_id"] not in have:
                r["source"] = "review"
                matches.append(r)
                have.add(r["record_id"])
                n += 1
        write_csv(work_path(cfg, "matches.csv"), matches, MATCH_FIELDS)
        LOG.info("added %d reviewed matches", n)
        return

    cases = {c["record_id"]: c for c in read_csv(work_path(cfg, "cases.csv"))}
    hits = collections.defaultdict(list)
    for h in read_csv(work_path(cfg, "hits.csv")):
        hits[h["record_id"]].append(h)
    searched = {r["record_id"] for r in read_csv(work_path(cfg, "search_log.csv"))}
    # an obstacle counts only if that court was never searched successfully for that record
    # (a captcha skipped in an early run and answered in a later sweep is not an obstacle)
    log_rows = read_csv(work_path(cfg, "search_log.csv"))
    ok_courts = {(r["record_id"], r["court_id"]) for r in log_rows if r.get("state") in ("results", "empty")}
    obstacles = collections.defaultdict(set)
    for r in log_rows:
        if (r["record_id"], r["court_id"]) in ok_courts:
            continue
        st = r.get("state", "")
        if st in ("captcha_skipped", "captcha_error"):
            obstacles[r["record_id"]].add("captcha")
        elif st == "host_blocked" or r.get("status") in ("403", "429", "451"):
            obstacles[r["record_id"]].add("blocked")
        elif st in ("error", "unknown"):
            obstacles[r["record_id"]].add(st)

    matches, review, unresolved, stats = [], [], [], collections.Counter()
    for rid in sorted(searched):
        # dedupe identical case rows found via several queries
        uniq = {}
        for h in hits.get(rid, []):
            k = (h["court_id"], h["docket_key"], h["case_url"])
            if k not in uniq or float(h["score"]) > float(uniq[k]["score"]):
                uniq[k] = h
        c = cases.get(rid, {})
        d, chosen, rule, conf = decide_rules(c, list(uniq.values()), w)
        stats[d] += 1
        if d == "accept":
            stats[f"rule:{rule}"] += 1
            matches.append({**chosen, "rule": rule, "confidence": conf, "source": "auto"})
        elif d == "review":
            stats[f"review:{rule}"] += 1
            for h in sorted(uniq.values(), key=lambda h: -float(h["score"]))[: a.review_top]:
                review.append({"review_decision": "", **h, "rule": rule, "ovd_name": c.get("name", ""),
                               "ovd_docket": c.get("docket_raw", ""), "ovd_city": c.get("city", ""),
                               "ovd_verdict_date": c.get("verdict_date", ""), "ovd_articles": c.get("articles", "")})
        else:
            unresolved.append({"record_id": rid, "obstacle_courts": ";".join(sorted(
                                   {r["court_id"] for r in log_rows if r["record_id"] == rid
                                    and (rid, r["court_id"]) not in ok_courts
                                    and r.get("state") not in ("results", "empty")})) if obstacles[rid] else "",
                               "reason": (rule or d) if not obstacles[rid] else ",".join(sorted(obstacles[rid])),
                               "candidates": len(uniq), "name": c.get("name", ""),
                               "docket": c.get("docket_raw", ""), "region": c.get("region", ""),
                               "city": c.get("city", ""), "verdict_date": c.get("verdict_date", "")})
    write_csv(work_path(cfg, "matches.csv"), matches, MATCH_FIELDS)
    write_csv(work_path(cfg, "review_queue.csv"), review,
              ["review_decision"] + MATCH_FIELDS[:-4] + ["decision", "names", "info", "ovd_name", "ovd_docket", "ovd_city",
                                                   "ovd_verdict_date", "ovd_articles", "source_url", "sha256",
                                                   "fetched_at"])
    write_csv(work_path(cfg, "unresolved.csv"), unresolved)
    tot = sum(v for k, v in stats.items() if ":" not in k) or 1
    for k, v in sorted(stats.items()):
        LOG.info("%-34s %5d  (%.1f%%)", k, v, 100 * v / tot)


if __name__ == "__main__":
    main()
