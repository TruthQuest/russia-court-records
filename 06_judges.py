#!/usr/bin/env python3
"""Step 6. Judge entities and judge-case edges.

Reads work/hearings.csv (+ work/hearings_manual.csv from 08_manual.py if present)
-> work/judges.csv           one row per judge per court, with case counts
-> work/judge_edges.csv      hearing -> judge, joined to OVD-Info articles and dates
-> work/judge_unparsed.csv   judge strings that need a human look
-> work/case_clusters.csv    cases registered together in one court (consecutive case UIDs, shared
                             article): typically one investigation split into per-defendant cases.
                             n_clusters in judges.csv counts independent prosecutions, not files.
"""
from __future__ import annotations

import argparse
import collections
import re

from courtlink.common import LOG, load_config, parse_date, read_csv, setup_logging, work_path, write_csv
from courtlink.judges import judge_key, parse_judge, person_key


UID_PARTS = re.compile(r"^(\w{8})-\d{2}-(\d{4})-(\d{6})")


def cluster_uids(hearings: list[dict], cases: dict, gap: int) -> dict[str, str]:
    """uid -> cluster_id. Same court code and registration year, sequence numbers within `gap`
    of a neighbour (single linkage), and at least one shared OVD-Info article."""
    info = {}
    for h in hearings:
        m = UID_PARTS.match(h.get("uid", ""))
        if m:
            arts = set(filter(None, cases.get(h["record_id"], {}).get("articles", "").split(";")))
            code, yr, seq = m.group(1), m.group(2), int(m.group(3))
            d = info.setdefault(h["uid"], {"key": (code, yr), "seq": seq, "arts": set()})
            d["arts"] |= arts
    groups = collections.defaultdict(list)
    for uid, d in info.items():
        groups[d["key"]].append(uid)
    out = {}
    for (code, yr), uids in groups.items():
        uids.sort(key=lambda u: info[u]["seq"])
        cur = [uids[0]]
        def flush(c):
            for u in c:
                out[u] = f"{code}-{yr}-{info[c[0]]['seq']:06d}" + (f"+{len(c) - 1}" if len(c) > 1 else "")
        for u in uids[1:]:
            prev = cur[-1]
            if info[u]["seq"] - info[prev]["seq"] <= gap and (info[u]["arts"] & info[prev]["arts"]):
                cur.append(u)
            else:
                flush(cur); cur = [u]
        flush(cur)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    cases = {c["record_id"]: c for c in read_csv(work_path(cfg, "cases.csv"))}
    hearings = read_csv(work_path(cfg, "hearings.csv")) if work_path(cfg, "hearings.csv").exists() else []
    manual = work_path(cfg, "hearings_manual.csv")
    if manual.exists():
        hearings += read_csv(manual)
    LOG.info("hearings: %d", len(hearings))

    clusters = cluster_uids(hearings, cases, int(cfg.get("judges", {}).get("cluster_uid_gap", 10)))
    judges: dict[str, dict] = {}
    edges, bad = [], []
    for h in hearings:
        j = parse_judge(h.get("judge", ""))
        if not j:
            if h.get("judge"):
                bad.append({"hearing_id": h["hearing_id"], "court_id": h["court_id"], "judge_raw": h["judge"]})
            continue
        jid = judge_key(h["court_id"], j)
        rec = judges.setdefault(jid, {
            "judge_id": jid, "court_id": h["court_id"], "court_name": h.get("court_name", ""),
            "court_type": h.get("court_type", ""), "surname": j["surname"], "i1": j["i1"], "i2": j["i2"],
            "first": j["first"], "patronymic": j["patronymic"], "display": j["display"],
            "person_key": person_key(j), "former_surname": j.get("former_surname", ""),
            "records": set(), "cases": set(), "clusters": set(), "hearings": 0, "articles": collections.Counter(),
            "years": collections.Counter(),
        })
        if j["full"] and not rec["first"]:  # upgrade initials to full name when seen
            rec.update(first=j["first"], patronymic=j["patronymic"], display=j["display"])
        c = cases.get(h["record_id"], {})
        rec["records"].add(h["record_id"])
        case_key = h.get("uid") or f'{h["court_id"]}:{h.get("docket_key") or h.get("docket")}'
        rec["cases"].add(case_key)
        rec["clusters"].add(clusters.get(h.get("uid", ""), case_key))
        rec["hearings"] += 1
        new_record = h["record_id"] not in rec.setdefault("_arts_seen", set())
        rec["_arts_seen"].add(h["record_id"])
        if new_record:  # each article counted once per defendant
            for art in set(filter(None, c.get("articles", "").split(";"))):
                rec["articles"][art] += 1
        yr = (parse_date(h.get("decision_date", "")) or c.get("verdict_date", ""))[:4]
        if yr:
            rec["years"][yr] += 1
        edges.append({"hearing_id": h["hearing_id"], "record_id": h["record_id"], "judge_id": jid,
                      "court_id": h["court_id"], "instance": h.get("instance", ""), "docket": h.get("docket", ""),
                      "uid": h.get("uid", ""), "cluster_id": clusters.get(h.get("uid", ""), ""), "decision_date": h.get("decision_date", ""),
                      "articles": c.get("articles", ""), "verdict_date": c.get("verdict_date", ""),
                      "occupied": c.get("occupied", ""), "judge_source": h.get("judge_source", ""),
                      "card_url": h.get("card_url", ""), "card_sha256": h.get("card_sha256", "")})
    by_person = collections.defaultdict(set)
    for r in judges.values():
        by_person[r["person_key"]].add(r["court_id"])
    rows = []
    for r in judges.values():
        rows.append({**{k: v for k, v in r.items()
                        if k not in ("records", "cases", "clusters", "articles", "years", "_arts_seen")},
                     "n_records": len(r["records"]), "n_cases": len(r["cases"]), "n_clusters": len(r["clusters"]),
                     # same surname + initials in another court: possibly the same judge (seconded or
                     # transferred), possibly a namesake. Verify before merging.
                     "same_name_other_courts": ";".join(sorted(by_person[r["person_key"]] - {r["court_id"]})),
                     "top_articles": "; ".join(f"{k}:{v}" for k, v in r["articles"].most_common(6)),
                     "years": "; ".join(f"{k}:{v}" for k, v in sorted(r["years"].items()))})
    rows.sort(key=lambda r: -r["n_records"])
    write_csv(work_path(cfg, "judges.csv"), rows)
    write_csv(work_path(cfg, "judge_edges.csv"), edges)
    write_csv(work_path(cfg, "judge_unparsed.csv"), bad)
    cl = collections.defaultdict(lambda: {"uids": set(), "records": set(), "judges": set(), "court_id": "", "articles": set()})
    for e in edges:
        if e["cluster_id"] and "+" in e["cluster_id"]:
            d = cl[e["cluster_id"]]
            d["uids"].add(e["uid"]); d["records"].add(e["record_id"]); d["judges"].add(e["judge_id"].split(":")[1])
            d["court_id"] = e["court_id"]; d["articles"] |= set(filter(None, e["articles"].split(";")))
    write_csv(work_path(cfg, "case_clusters.csv"),
              [{"cluster_id": k, "court_id": d["court_id"], "n_cases": len(d["uids"]), "n_records": len(d["records"]),
                "n_judges": len(d["judges"]), "judges": ";".join(sorted(d["judges"])),
                "articles": ";".join(sorted(d["articles"])), "uids": ";".join(sorted(d["uids"]))}
               for k, d in sorted(cl.items(), key=lambda x: -len(x[1]["uids"]))],
              ["cluster_id", "court_id", "n_cases", "n_records", "n_judges", "judges", "articles", "uids"])
    if rows:
        n_cases = sum(r["n_cases"] for r in rows)
        top = sorted(rows, key=lambda r: -r["n_cases"])[:10]
        LOG.info("judges=%d  judge-case links=%d  judge-cluster links=%d  judge-defendant links=%d  "
                 "split-case clusters=%d  same-name-other-court judges=%d  top10 share of cases=%.1f%%",
                 len(rows), n_cases, sum(r["n_clusters"] for r in rows), sum(r["n_records"] for r in rows),
                 len(cl), sum(1 for r in rows if r["same_name_other_courts"]),
                 100 * sum(r["n_cases"] for r in top) / max(n_cases, 1))


if __name__ == "__main__":
    main()
